import asyncio
import functools
import inspect
import uuid
import warnings

from typing import Any, Callable, Generator, List, Optional, Coroutine, Dict, cast

import pytest
from _pytest import timing
from _pytest import outcomes
from _pytest import runner
from _pytest import nodes
from _pytest import reports
from _pytest import fixtures
from _pytest import warnings as pytest_warning

from .grouping import AsyncioConcurrentGroup, AsyncioConcurrentGroupMember


class PytestAsyncioConcurrentGroupingWarning(pytest.PytestWarning):
    """Raised when Test from different parent grouped into same group."""


class PytestAsyncioConcurrentInvalidMarkWarning(pytest.PytestWarning):
    """Raised when Sync Test got marked."""


# =========================== # Config # =========================== #
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio_concurrent(group, timeout): " "mark the async tests to run concurrently",
    )


@pytest.hookimpl
def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    from . import hooks

    pluginmanager.add_hookspecs(hooks)


# =========================== # pytest_runtest # =========================== #

@pytest.hookimpl(specname="pytest_runtestloop", wrapper=True)
def pytest_runtestloop_handle_async_by_group(session: pytest.Session) -> Generator[None, Any, Any]:
    """
    Wrapping around pytest_runtestloop, grouping items with same asyncio concurrent group
    together before formal pytest_runtestloop, handle async tests by group,
    and ungroup them after everything done.
    """
    asycio_concurrent_groups: Dict[str, AsyncioConcurrentGroup] = {}
    items = session.items
    ihook = session.ihook

    for item in items:
        item = cast(pytest.Function, item)

        if _get_asyncio_concurrent_mark(item) is None:
            continue

        concurrent_group_name = _get_asyncio_concurrent_group(item)
        if concurrent_group_name not in asycio_concurrent_groups:
            asycio_concurrent_groups[concurrent_group_name] = AsyncioConcurrentGroup.from_parent(
                parent=item.parent, originalname=f"AsyncioConcurrentGroup[{concurrent_group_name}]"
            )
        asycio_concurrent_groups[concurrent_group_name].add_child(item)

    groups = list(asycio_concurrent_groups.values())
    for group in groups:
        for item in group.children:
            items.remove(item._inner)

    result = yield

    for i, group in enumerate(groups):
        nextgroup = groups[i + 1] if i + 1 < len(groups) else None
        ihook.pytest_runtest_protocol_async_group(group=group, nextgroup=nextgroup)

    for group in groups:
        for item in group.children:
            items.append(item._inner)

    return result


@pytest.hookimpl(specname="pytest_runtest_protocol_async_group")
def pytest_runtest_protocol_async_group(
    group: AsyncioConcurrentGroup, nextgroup: Optional[AsyncioConcurrentGroup]
) -> object:    
    if not group.have_same_parent:
        for child in group.children:
            child.add_marker("skip")

        warnings.warn(
            PytestAsyncioConcurrentGroupingWarning(
                f"""
                Asyncio Concurrent Group [{group.name}] has children from different parents,
                skipping all of it's children.
                """
            )
        )

    children_passed_setup: List[pytest.Function] = []

    group.ihook.pytest_runtest_setup_async_group(group=group)
    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logstart(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

    for childFunc in group.children:
        report = _call_and_report_setup_async_function(childFunc)

        if report.passed:
            children_passed_setup.append(childFunc)

    _pytest_runtest_call_async_group(children_passed_setup)

    for childFunc in group.children:
        _call_and_report_teardown_async_function(childFunc, nextitem=nextgroup)

    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logfinish(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

    group.ihook.pytest_runtest_teardown_async_group(group=group, nextgroup=nextgroup)

    return True


def _pytest_runtest_call_async_group(items: List[pytest.Function]) -> None:
    def hook_invoker(item: pytest.Function) -> Callable[[], Coroutine]:
        def inner() -> Coroutine:
            return childFunc.ihook.pytest_runtest_call_async(item=item)

        return inner

    coros: List[Coroutine] = []
    loop = asyncio.get_event_loop()

    for childFunc in items:
        coros.append(_async_callinfo_from_call(hook_invoker(childFunc)))

    call_result = loop.run_until_complete(asyncio.gather(*coros))

    for childFunc, call in zip(items, call_result):
        report: reports.TestReport = childFunc.ihook.pytest_runtest_makereport(
            item=childFunc, call=call
        )
        childFunc.ihook.pytest_runtest_logreport(report=report)


@pytest.hookimpl(specname="pytest_runtest_call_async")
async def pytest_runtest_call_async(item: pytest.Function) -> object:
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


@pytest.hookimpl(specname="pytest_runtest_setup_async_group")
def pytest_runtest_setup_async_group(group: AsyncioConcurrentGroup) -> None:
    group.ihook.pytest_runtest_setup(item=group)


@pytest.hookimpl(specname="pytest_runtest_teardown_async_group")
def pytest_runtest_teardown_async_group(
    group: "AsyncioConcurrentGroup",
    nextgroup: "AsyncioConcurrentGroup",
) -> None:
    group.ihook.pytest_runtest_teardown(item=group, nextitem=nextgroup)


@pytest.hookimpl(specname="pytest_runtest_setup")
def pytest_runtest_setup_handle_async_function(item: pytest.Item) -> None:
    if not isinstance(item, AsyncioConcurrentGroupMember):
        return

    item.setup()


@pytest.hookimpl(specname="pytest_runtest_teardown")
def pytest_runtest_teardown_handle_async_function(
    item: pytest.Item, nextitem: Optional[pytest.Item]
) -> None:
    if not isinstance(item, AsyncioConcurrentGroupMember):
        return

    # TODO: handle teardown gracfully
    pass


# =========================== # warnings #===========================#


@pytest.hookimpl(specname="pytest_runtest_protocol_async_group", wrapper=True, tryfirst=True)
def pytest_runtest_protocol_async_group_warning(
    group: "AsyncioConcurrentGroup", nextgroup: Optional["AsyncioConcurrentGroup"]
) -> Generator[None, object, object]:
    config = group.children[0].config
    with pytest_warning.catch_warnings_for_item(
        config=config, ihook=group.children[0].ihook, when="runtest", item=None
    ):
        return (yield)


# =========================== # fixture #===========================#


@pytest.hookimpl(specname="pytest_fixture_setup", tryfirst=True)
def pytest_fixture_setup_wrap_async(
    fixturedef: fixtures.FixtureDef[fixtures.FixtureValue], request: fixtures.SubRequest
) -> None:
    _wrap_async_fixture(fixturedef)


def _wrap_async_fixture(fixturedef: fixtures.FixtureDef) -> None:
    """Wraps the fixture function of an async fixture in a synchronous function."""
    if inspect.isasyncgenfunction(fixturedef.func):
        _wrap_asyncgen_fixture(fixturedef)
    elif inspect.iscoroutinefunction(fixturedef.func):
        _wrap_asyncfunc_fixture(fixturedef)


def _wrap_asyncgen_fixture(fixturedef: fixtures.FixtureDef) -> None:
    fixtureFunc = fixturedef.func

    @functools.wraps(fixtureFunc)
    def _asyncgen_fixture_wrapper(**kwargs: Any):
        event_loop = asyncio.new_event_loop()
        gen_obj = fixtureFunc(**kwargs)

        async def setup():
            res = await gen_obj.__anext__()  # type: ignore[union-attr]
            return res

        async def teardown() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)

        result = event_loop.run_until_complete(setup())
        yield result
        event_loop.run_until_complete(teardown())

    fixturedef.func = _asyncgen_fixture_wrapper  # type: ignore[misc]


def _wrap_asyncfunc_fixture(fixturedef: fixtures.FixtureDef) -> None:
    fixtureFunc = fixturedef.func

    @functools.wraps(fixtureFunc)
    def _async_fixture_wrapper(**kwargs: Dict[str, Any]):
        event_loop = asyncio.get_event_loop()

        async def setup():
            res = await fixtureFunc(**kwargs)
            return res

        return event_loop.run_until_complete(setup())

    fixturedef.func = _async_fixture_wrapper  # type: ignore[misc]


# =========================== # helper #===========================#


def _get_asyncio_concurrent_mark(item: nodes.Item) -> Optional[pytest.Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: nodes.Item) -> str:
    marker = item.get_closest_marker("asyncio_concurrent")
    assert marker is not None

    return marker.kwargs.get("group", f"anonymous_[{uuid.uuid4()}]")


# referencing CallInfo.from_call
async def _async_callinfo_from_call(func: Callable[[], Coroutine]) -> pytest.CallInfo:
    """An async version of CallInfo.from_call"""

    excinfo = None
    start = timing.time()
    precise_start = timing.perf_counter()
    try:
        result = await func()
    except BaseException:
        excinfo = pytest.ExceptionInfo.from_current()
        if isinstance(excinfo.value, outcomes.Exit) or isinstance(excinfo.value, KeyboardInterrupt):
            raise
        result = None

    precise_stop = timing.perf_counter()
    duration = precise_stop - precise_start
    stop = timing.time()

    callInfo: pytest.CallInfo = pytest.CallInfo(
        start=start,
        stop=stop,
        duration=duration,
        when="call",
        result=result,
        excinfo=excinfo,
        _ispytest=True,
    )

    return callInfo


# referencing runner.call_and_report
def _call_and_report_setup_async_function(item: AsyncioConcurrentGroupMember) -> pytest.TestReport:
    invoker = item.config.pluginmanager.subset_hook_caller(
        "pytest_runtest_setup", [runner]
    )
    reraise: tuple[type[BaseException], ...] = (outcomes.Exit,)
    if not item.config.getoption("usepdb", False):
        reraise += (KeyboardInterrupt,)
        
    call = pytest.CallInfo.from_call(lambda: invoker(item=item), when="setup", reraise=reraise)
    report: pytest.TestReport = item.ihook.pytest_runtest_makereport(item=item, call=call)
    item.ihook.pytest_runtest_logreport(report=report)

    if runner.check_interactive_exception(call, report):
        item.ihook.pytest_exception_interact(node=item, call=call, report=report)
    return report


def _call_and_report_teardown_async_function(
    item: AsyncioConcurrentGroupMember,
    nextitem: Optional[pytest.Item],
) -> pytest.TestReport:
    invoker = item.config.pluginmanager.subset_hook_caller(
        "pytest_runtest_teardown", [runner]
    )
    reraise: tuple[type[BaseException], ...] = (outcomes.Exit,)
    if not item.config.getoption("usepdb", False):
        reraise += (KeyboardInterrupt,)
        
    call = pytest.CallInfo.from_call(
        lambda: invoker(item=item, nextitem=nextitem), when="teardown", reraise=reraise
    )
    report: pytest.TestReport = item.ihook.pytest_runtest_makereport(item=item, call=call)
    item.ihook.pytest_runtest_logreport(report=report)

    if runner.check_interactive_exception(call, report):
        item.ihook.pytest_exception_interact(node=item, call=call, report=report)
    return report
