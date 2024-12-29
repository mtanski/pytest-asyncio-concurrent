import asyncio
from contextlib import contextmanager
import inspect
from typing import Any, Callable, Generator, List, Optional, Coroutine, Dict, cast
import uuid
import warnings

import pytest
from _pytest import scope, timing, outcomes, runner, fixtures, nodes, reports, warnings as pytest_warning
from pytest import (
    CallInfo,
    ExceptionInfo,
    PytestWarning,
    Session,
    Config,
    Function,
    Mark,
)


class AsyncioConcurrentGroup():
    """
    The Function Group containing underneath children functions.
    """

    _children: List[Function]
    group_name: str
    have_same_parent: bool
    
    def __init__(self, group_name: str):
        self.group_name = group_name
        self.have_same_parent = True
        self._children = []

    @property
    def children(self) -> List[Function]:
        return self._children

    def add_child(self, item: Function) -> None:
        self._rewrite_function_scoped_fixture(item)
        if not self._children:
            self._children.append(item)
            return
        
        child_parent = list(item.iter_parents())[1]
        known_parent = list(self._children[0].iter_parents())[1]
        
        if child_parent is not known_parent:
            self.have_same_parent = False
        
        if not self.have_same_parent:
            item.add_marker("skip")
        
        self._children.append(item)
        
    
    def _rewrite_function_scoped_fixture(self, item: Function):
        for name, fixturedefs in item._request._arg2fixturedefs.items():
            if hasattr(item, "callspec") and name in item.callspec.params.keys():
                continue

            if fixturedefs[-1]._scope != scope.Scope.Function:
                continue

            new_fixdef = fixtures.FixtureDef(
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


@pytest.hookimpl
def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    from pytest_asyncio_concurrent import hooks
    pluginmanager.add_hookspecs(hooks)


@pytest.hookimpl(specname="pytest_runtestloop", wrapper=True)
def pytest_runtestloop_handle_async_by_group(session: Session) -> Generator[None, Any, Any]:
    """
    Wrapping around pytest_runtestloop, grouping items with same asyncio concurrent group
    together before formal pytest_runtestloop, handle async tests by group, 
    and ungroup them after everything done.
    """
    asycio_concurrent_groups: Dict[str, AsyncioConcurrentGroup] = {}
    items = session.items
    ihook = session.ihook

    for item in items:
        item = cast(Function, item)
        
        if _get_asyncio_concurrent_mark(item) is None:
            continue

        concurrent_group_name = _get_asyncio_concurrent_group(item)
        if concurrent_group_name not in asycio_concurrent_groups:
            asycio_concurrent_groups[concurrent_group_name] = AsyncioConcurrentGroup(concurrent_group_name)
        asycio_concurrent_groups[concurrent_group_name].add_child(item)

    
    groups = list(asycio_concurrent_groups.values())
    for async_group in groups:
        for item in async_group.children:
            items.remove(item)

    result = yield
    
    for i in range(len(groups)):
        async_group = groups[i]
        nextgroup = groups[i + 1] if i + 1 < len(groups) else None
        ihook.pytest_runtest_protocol_async_group(group=async_group, nextgroup=nextgroup)

    for async_group in groups:
        for item in async_group.children:
            items.append(item)

    return result


@pytest.hookimpl(specname="pytest_runtest_protocol_async_group")
def pytest_runtest_protocol_async_group_impl(
    group: AsyncioConcurrentGroup, 
    nextgroup: Optional[AsyncioConcurrentGroup]
) -> object:
    if not group.have_same_parent:
        for child in group.children:
            child.add_marker("skip")
        
        warnings.warn(
            PytestAsyncioConcurrentGroupingWarning(
                f"""
                Asyncio Concurrent Group [{group.group_name}] has children from different parents,
                skipping all of it's children.
                """
            )
        )
        
    children_passed_setup: List[Function] = []
    
    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logstart(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

    for i in range(len(group.children)):
        childFunc = group.children[i]

        if i == 0:
            report = runner.call_and_report(childFunc, "setup")
        else:
            with _setupstate_setup_hijacked():
                report = runner.call_and_report(childFunc, "setup")            

        if report.passed:
            children_passed_setup.append(childFunc)
    
    _pytest_runtest_call_async_group(children_passed_setup)

    for i in range(len(group.children)):
        childFunc = group.children[i]
        if i == len(group.children) - 1:
            runner.call_and_report(childFunc, "teardown", nextitem=(
                None if not nextgroup else nextgroup.children[0]
            ))
        else:
            with _setupstate_teardown_hijacked(group.children):
                runner.call_and_report(childFunc, "teardown", nextitem=(
                    None if not nextgroup else nextgroup.children[0]
                ))
    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logfinish(
            nodeid=childFunc.nodeid, location=childFunc.location
        )
    
    return True
        
        
def _pytest_runtest_call_async_group(items: List[Function]) -> None:
    coros: List[Coroutine] = []
    loop = asyncio.get_event_loop()

    for childFunc in items:
        coros.append(_async_callinfo_from_call(
            lambda: childFunc.ihook.pytest_runtest_call_async(item=childFunc)))

    call_result = loop.run_until_complete(asyncio.gather(*coros))

    for childFunc, call in zip(items, call_result):
        report: reports.TestReport = childFunc.ihook.pytest_runtest_makereport(item=childFunc, call=call)
        childFunc.ihook.pytest_runtest_logreport(report=report)


@pytest.hookimpl(specname="pytest_runtest_call_async")
async def pytest_runtest_call_async_impl(item: Function) -> Coroutine:
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


# =========================== # hacks #===========================#


def _pytest_setupstate_setup_without_assert(self: runner.SetupState, item: nodes.Item) -> None:
    """A 'no assertion' version of SetupState.setup, to setup colloctor tree in 'wrong' order."""
    self.stack[item] = ([item.teardown], None)
    item.setup()

        
@contextmanager
def _setupstate_setup_hijacked() -> Generator[None, None, None]:
    original = getattr(runner.SetupState, "setup")
    setattr(runner.SetupState, "setup", _pytest_setupstate_setup_without_assert)

    yield

    setattr(runner.SetupState, "setup", original)



def _pytest_setupstate_teardown_items_without_assert(
    items: List[Function],
) -> Callable[[runner.SetupState, nodes.Item], None]:
    """
    A 'no assertion' version of teardown_exact.
    Only tearing down the nodes given, cleaning up the SetupState.stack before getting caught.
    """

    def inner(self: runner.SetupState, nextitem: nodes.Item):
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


# =========================== # warnings #===========================#

@pytest.hookimpl(specname="pytest_runtest_protocol_async_group", wrapper=True, tryfirst=True)
def pytest_runtest_protocol_async_group_warning(
    group: 'AsyncioConcurrentGroup', 
    nextgroup: Optional['AsyncioConcurrentGroup']
) -> Generator[None, object, object]:
    config = group.children[0].config
    with pytest_warning.catch_warnings_for_item(
        config=config, ihook=group.children[0].ihook, when="runtest", item=None
    ):
        return (yield)


# =========================== # helper #===========================#


def _get_asyncio_concurrent_mark(item: nodes.Item) -> Optional[Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: nodes.Item) -> str:
    marker = item.get_closest_marker("asyncio_concurrent")
    assert marker is not None

    return marker.kwargs.get("group", f"anonymous_[{uuid.uuid4()}]")
