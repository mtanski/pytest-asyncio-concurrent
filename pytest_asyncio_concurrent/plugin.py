import asyncio
from contextlib import contextmanager
import inspect
from typing import Any, Callable, Generator, List, Optional, Coroutine, Dict, cast
import uuid
import warnings

import pytest
from _pytest import scope, timing, outcomes, runner
from pytest import (
    CallInfo,
    ExceptionInfo,
    FixtureDef,
    Item,
    PytestWarning,
    Session,
    Config,
    Function,
    Mark,
    TestReport,
)


class AsyncioConcurrentGroup(Function):
    """
    The Function Group containing underneath children functions.
    """

    _pytest_asyncio_concurrent_children: List[Function] = []

    #: While setup and teardown are performed upon all child items,
    #: call is only performed on tests passing setup step.
    _pytest_asyncio_passing_setup_children: List[Function] = []


class PytestAsyncioConcurrentGroupingWarning(PytestWarning):
    """Raised when Test from different parent grouped into same group."""


class PytestAsyncioConcurrentInvalidMarkWarning(PytestWarning):
    """Raised when Sync Test got marked."""


# =========================== # Config & Collection # =========================== #
def pytest_configure(config: Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio_concurrent(group, timeout): " "mark the async tests to run concurrently",
    )


@pytest.hookimpl(specname="pytest_runtestloop", wrapper=True)
def pytest_runtestloop_wrap_items_by_group(session: Session) -> Generator[None, Any, Any]:
    """
    Wrapping around pytest_runtestloop, grouping items with same asyncio concurrent group
    together before formal pytest_runtestloop, and ungroup them after everything done.
    The reason putting grouping logic here instead of pytest_pycollect_makeitem is to have
    the item collection summary before and after have correct information.
    """
    asycio_concurrent_groups: Dict[str, List[Function]] = {}
    items = session.items

    for item in items:
        if _get_asyncio_concurrent_mark(item) is None:
            continue

        concurrent_group_name = _get_asyncio_concurrent_group(item)
        if concurrent_group_name not in asycio_concurrent_groups:
            asycio_concurrent_groups[concurrent_group_name] = []
        asycio_concurrent_groups[concurrent_group_name].append(cast(Function, item))

    for asyncio_items in asycio_concurrent_groups.values():
        for item in asyncio_items:
            items.remove(item)

    for group_name, asyncio_items in asycio_concurrent_groups.items():
        items.append(group_asyncio_concurrent_function(group_name, asyncio_items))

    result = yield

    groups = [item for item in items if isinstance(item, AsyncioConcurrentGroup)]
    for group in groups:
        items.remove(group)
        for item in group._pytest_asyncio_concurrent_children:
            items.append(item)

    return result


def group_asyncio_concurrent_function(
    group_name: str, children: List[Function]
) -> AsyncioConcurrentGroup:
    """
    Grouping children with same mark into AsyncioConcurrentGroup.
    - Check all children have same parent:
        - if True: Group them
        - If False:
            - Give AsyncioConcurrentGroup function to emit a warning.
            - Give all children function a skip mark.
    - Rewrite all function scoped fixture registered on each child function,
        to avoid function scoped fixture got shared within same group.
    """

    parent = None
    have_same_parent = True
    for childFunc in children:
        p_it = childFunc.iter_parents()
        next(p_it)
        func_parent = next(p_it)

        if not parent:
            parent = func_parent
        elif parent is not func_parent:
            have_same_parent = False

    def _warn_children_with_different_parent():
        warnings.warn(
            PytestAsyncioConcurrentGroupingWarning(
                f"Asyncio Concurrent Group [{group_name}] has children from different parents"
            )
        )

    if not have_same_parent:
        for childFunc in children:
            childFunc.add_marker(pytest.mark.skip)

    for childFunc in children:
        _rewrite_function_scoped_fixture(childFunc)

    g_function = AsyncioConcurrentGroup.from_parent(
        parent,
        name=f"ayncio_concurrent_test_group[{group_name}]",
        callobj=_warn_children_with_different_parent if not have_same_parent else lambda: None,
    )

    g_function._pytest_asyncio_concurrent_children = children
    g_function._pytest_asyncio_passing_setup_children = children.copy()
    return g_function


def _rewrite_function_scoped_fixture(item: Function):
    for name, fixturedefs in item._request._arg2fixturedefs.items():
        if hasattr(item, "callspec") and name in item.callspec.params.keys():
            continue

        if fixturedefs[-1]._scope != scope.Scope.Function:
            continue

        new_fixdef = FixtureDef(
            config=item.config,
            baseid=fixturedefs[-1].baseid,
            argname=fixturedefs[-1].argname,
            func=fixturedefs[-1].func,
            scope=fixturedefs[-1]._scope,
            params=fixturedefs[-1].params,
            ids=fixturedefs[-1].ids,
            _ispytest=True,
        )
        fixturedefs = list(fixturedefs[0:-1]) + [new_fixdef]
        item._request._arg2fixturedefs[name] = fixturedefs


# =========================== # function call & setup & teardown #===========================#


@pytest.hookimpl(specname="pytest_runtest_setup", wrapper=True)
def pytest_runtest_setup_group_children(item: Item) -> Generator[None, None, None]:
    """
    - Hijack Session.SetupState setup function.
    - Setup child function AFTER group got setup.
    """

    if not isinstance(item, AsyncioConcurrentGroup):
        return (yield)

    result = yield

    with _setupstate_setup_hijacked():
        reports = [
            runner.call_and_report(childFunc, "setup")
            for childFunc in item._pytest_asyncio_concurrent_children
        ]
        item._pytest_asyncio_passing_setup_children = [
            childFunc
            for childFunc, report in zip(item._pytest_asyncio_concurrent_children, reports)
            if report.passed
        ]

    return result


def _pytest_setupstate_setup_without_assert(self: runner.SetupState, item: Item) -> None:
    """A 'no assertion' version of SetupState.setup, to setup colloctor tree in 'wrong' order."""
    self.stack[item] = ([item.teardown], None)
    item.setup()


@contextmanager
def _setupstate_setup_hijacked() -> Generator[None, None, None]:
    original = getattr(runner.SetupState, "setup")
    setattr(runner.SetupState, "setup", _pytest_setupstate_setup_without_assert)

    yield

    setattr(runner.SetupState, "setup", original)


@pytest.hookimpl(specname="pytest_pyfunc_call", wrapper=True)
def pytest_pyfunc_call_handle_group(pyfuncitem: Function) -> Generator[None, Any, Any]:
    """
    - Call children functions which passed setup steps AFTER group got called.
    - Gather all children funtion tasks, and run that in same event loop.
    - Make and wite report of all child function after loop finished.
    """

    result = yield
    if not isinstance(pyfuncitem, AsyncioConcurrentGroup):
        return result

    coros: List[Coroutine] = []
    loop = asyncio.get_event_loop()

    for childFunc in pyfuncitem._pytest_asyncio_passing_setup_children:
        coros.append(_async_callinfo_from_call(_pytest_function_call_async(childFunc)))

    call_result = loop.run_until_complete(asyncio.gather(*coros))

    for childFunc, call in zip(pyfuncitem._pytest_asyncio_passing_setup_children, call_result):
        report: TestReport = childFunc.ihook.pytest_runtest_makereport(item=childFunc, call=call)
        childFunc.ihook.pytest_runtest_logreport(report=report)

    return result


def _pytest_function_call_async(item: Function) -> Callable[[], Coroutine]:
    async def inner() -> Any:
        if not inspect.iscoroutinefunction(item.obj):
            warnings.warn(
                PytestAsyncioConcurrentInvalidMarkWarning(
                    "Marking a sync function with @asyncio_concurrent is invalid."
                )
            )

            pytest.skip("Marking a sync function with @asyncio_concurrent is invalid.")

        testfunction = item.obj
        testargs = {arg: item.funcargs[arg] for arg in item._fixtureinfo.argnames}
        return await testfunction(**testargs)

    return inner


# referencing CallInfo.from_call
async def _async_callinfo_from_call(func: Callable[[], Coroutine]) -> CallInfo:
    """An async version of CallInfo.from_call"""

    excinfo = None
    start = timing.time()
    precise_start = timing.perf_counter()
    try:
        result = await func()
    except BaseException:
        excinfo = ExceptionInfo.from_current()
        if isinstance(excinfo.value, outcomes.Exit) or isinstance(excinfo.value, KeyboardInterrupt):
            raise
        result = None

    precise_stop = timing.perf_counter()
    duration = precise_stop - precise_start
    stop = timing.time()

    callInfo: CallInfo = CallInfo(
        start=start,
        stop=stop,
        duration=duration,
        when="call",
        result=result,
        excinfo=excinfo,
        _ispytest=True,
    )

    return callInfo


@pytest.hookimpl(specname="pytest_runtest_teardown", wrapper=True)
def pytest_runtest_teardown_group_children(
    item: Item, nextitem: Optional[Item]
) -> Generator[None, None, None]:
    """
    - Hijack Session.SetupState teardown_exact function.
    - Teardown child function BEFORE group got teardown.
    """

    if not isinstance(item, AsyncioConcurrentGroup):
        return (yield)

    with _setupstate_teardown_hijacked(item._pytest_asyncio_concurrent_children):
        for childFunc in item._pytest_asyncio_concurrent_children:
            runner.call_and_report(childFunc, "teardown", nextitem=nextitem)

    return (yield)


def _pytest_setupstate_teardown_items_without_assert(
    items: List[Function],
) -> Callable[[runner.SetupState, Item], None]:
    """
    A 'no assertion' version of teardown_exact.
    Only tearing down the nodes given, cleaning up the SetupState.stack before getting caught.
    """

    def inner(self: runner.SetupState, nextitem: Item):
        for item in items:
            if item not in self.stack:
                continue

            finalizers, _ = self.stack.pop(item)
            these_exceptions = []
            while finalizers:
                fin = finalizers.pop()
                try:
                    fin()
                except Exception as e:
                    these_exceptions.append(e)

            if len(these_exceptions) == 1:
                raise these_exceptions[0]
            elif these_exceptions:
                msg = f"Errors during tearing down {item}"
                raise BaseExceptionGroup(msg, these_exceptions[::-1])

    return inner


@contextmanager
def _setupstate_teardown_hijacked(items: List[Function]) -> Generator[None, None, None]:
    original = getattr(runner.SetupState, "teardown_exact")
    setattr(
        runner.SetupState, "teardown_exact", _pytest_setupstate_teardown_items_without_assert(items)
    )

    yield

    setattr(runner.SetupState, "teardown_exact", original)


# =========================== # reporting #===========================#


@pytest.hookimpl(specname="pytest_runtest_protocol", tryfirst=True)
def pytest_runtest_protocol_skip_logging_for_group(
    item: Item, nextitem: Optional[Item]
) -> Optional[bool]:
    """
    Overwriting pytest_runtest_protocol AsyncioConcurrentGroup.
    Calling pytest_runtest_logstart and pytest_runtest_logfinish before and after tests start.
    Passing log param as False to runtestprotocol to avoid any reporting on AsyncioConcurrentGroup.
    """

    if not isinstance(item, AsyncioConcurrentGroup):
        return None

    for childFunc in item._pytest_asyncio_concurrent_children:
        childFunc.ihook.pytest_runtest_logstart(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

    runner.runtestprotocol(item, nextitem=nextitem, log=False)  # disable logging for group function

    for childFunc in item._pytest_asyncio_concurrent_children:
        childFunc.ihook.pytest_runtest_logfinish(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

    return True


def _get_asyncio_concurrent_mark(item: Item) -> Optional[Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: Item) -> str:
    marker = item.get_closest_marker("asyncio_concurrent")
    assert marker is not None

    return marker.kwargs.get("group", f"anonymous_[{uuid.uuid4()}]")
