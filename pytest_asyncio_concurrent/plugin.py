import asyncio
import functools
import inspect
import uuid
import warnings
import sys

from typing import (
    Any,
    Callable,
    Generator,
    List,
    Literal,
    Optional,
    Coroutine,
    Dict,
    Sequence,
    Union,
)

import pytest
from _pytest import timing
from _pytest import outcomes
from _pytest import warnings as pytest_warnings

from .grouping import (
    AsyncioConcurrentGroup,
    AsyncioConcurrentGroupMember,
    PytestAsyncioConcurrentInvalidMarkWarning,
    PytestAsyncioConcurrentGroupingWarning,
)

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


# =========================== # Config # =========================== #

asyncio_concurrent_group_key = pytest.StashKey[Dict[str, AsyncioConcurrentGroup]]()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio_concurrent(group, timeout): " "mark the async tests to run concurrently",
    )
    config.stash[asyncio_concurrent_group_key] = {}


@pytest.hookimpl
def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    from . import hooks
    from . import fixture_async

    pluginmanager.add_hookspecs(hooks)
    pluginmanager.register(fixture_async)


# =========================== # Collection # =========================== #

MakeItemResult = Union[
    None, pytest.Item, pytest.Collector, List[Union[pytest.Item, pytest.Collector]]
]


@pytest.hookimpl(specname="pytest_pycollect_makeitem", wrapper=True, trylast=True)
def pytest_pycollect_makeitem_make_group_and_member(
    collector: pytest.Collector, name: str, obj: object
) -> Generator[None, MakeItemResult, MakeItemResult]:
    ori_result = yield
    if ori_result is None:
        return None
    if not isinstance(ori_result, list):
        ori_result = [ori_result]

    result = []
    for item_or_collector in ori_result:
        if (
            not isinstance(item_or_collector, pytest.Function)
            or _get_asyncio_concurrent_mark(item_or_collector) is None
        ):
            result.append(item_or_collector)
            continue

        item = item_or_collector

        item = AsyncioConcurrentGroupMember.promote_from_function(item)
        result.append(item)

    return result


@pytest.hookimpl(specname="pytest_itemcollected")
def pytest_itemcollected_register_in_group(item: pytest.Item) -> None:
    if not isinstance(item, AsyncioConcurrentGroupMember):
        return

    known_groups = item.config.stash[asyncio_concurrent_group_key]

    group_name = _get_asyncio_concurrent_group(item)
    if group_name not in known_groups:
        known_groups[group_name] = AsyncioConcurrentGroup.from_parent(
            parent=item.parent, originalname=f"AsyncioConcurrentGroup[{group_name}]"
        )
    group = known_groups[group_name]

    group.add_child(item)


# =========================== # deselect # =========================== #


@pytest.hookimpl(specname="pytest_deselected")
def pytest_deselected_update_group(items: Sequence[pytest.Item]) -> None:
    """Remove item from group if deselected."""
    for item in items:
        if isinstance(item, AsyncioConcurrentGroupMember):
            item.group.remove_child(item)


# =========================== # pytest_runtestloop # =========================== #


@pytest.hookimpl(specname="pytest_runtestloop", wrapper=True)
def pytest_runtestloop_handle_async_by_group(session: pytest.Session) -> Generator[None, Any, Any]:
    """
    - Wrapping around pytest_runtestloop, grouping items with same group name together.
    - Run formal pytest_runtestloop without async tests.
    - Handle async tests by group, one at a time.
    - Ungroup them after everything done.
    """
    items = session.items
    ihook = session.ihook
    groups = list(session.config.stash[asyncio_concurrent_group_key].values())

    asyncio_concurrent_tests = [
        item for item in items if isinstance(item, AsyncioConcurrentGroupMember)
    ]
    assert sum([len(group.children) for group in groups]) == len(asyncio_concurrent_tests)

    for group in groups:
        for item in group.children:
            items.remove(item)

    result = yield

    for i, group in enumerate(groups):
        nextgroup = groups[i + 1] if i + 1 < len(groups) else None
        ihook.pytest_runtest_protocol_async_group(group=group, nextgroup=nextgroup)

    for group in groups:
        for item in group.children:
            items.append(item)

    return result


@pytest.hookimpl(specname="pytest_runtest_protocol_async_group")
def pytest_runtest_protocol_async_group(
    group: AsyncioConcurrentGroup, nextgroup: Optional[AsyncioConcurrentGroup]
) -> object:
    """
    Handling life cycle of async group tests. Calling pytest hooks in the same order as pytest core,
    but calling same hook on all tests in this group in batch. While for pytest_runtest_call,
    all tests are called and gathered, and await in a single event loop, which is how tests running
    concurrently.

    Hooks order:
    - pytest_runtest_logstart (batch)
    - pytest_runtest_setup_async_group (bank reporting under tests)
    - pytest_runtest_setup (batch) (and reporting)
    - pytest_runtest_call_async (batch) (and reporting)
    - pytest_runtest_teardown (batch) (and reporting)
    - pytest_runtest_teardown_async_group (bank reporting under tests)
    - pytest_runtest_logfinish (batch)
    """

    if not group.children_have_same_parent:
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

    item_passed_setup: List[AsyncioConcurrentGroupMember] = []
    coros: List[Coroutine] = []
    loop = asyncio.get_event_loop()

    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logstart(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

        report = _call_and_report(_setup_child(childFunc), childFunc, "setup")
        if report.passed:
            item_passed_setup.append(childFunc)

    for childFunc in item_passed_setup:
        coros.append(_call_and_report_runtest_async(childFunc, nextgroup))

    loop.run_until_complete(asyncio.gather(*coros))

    for childFunc in group.children:
        _call_and_report(_teardown_child(childFunc, nextgroup=nextgroup), childFunc, "teardown")

        childFunc.ihook.pytest_runtest_logfinish(
            nodeid=childFunc.nodeid, location=childFunc.location
        )

    return True


async def _call_and_report_runtest_async(
    item: AsyncioConcurrentGroupMember, nextgroup: Optional[AsyncioConcurrentGroup]
) -> None:
    callinfo = await _async_callinfo_from_call(
        functools.partial(item.ihook.pytest_runtest_call_async, item=item)  # type: ignore
    )
    report = item.ihook.pytest_runtest_makereport(item=item, call=callinfo)
    item.ihook.pytest_runtest_logreport(report=report)


def _setup_child(item: AsyncioConcurrentGroupMember) -> Callable[[], None]:
    """
    Setup flow for normal pytest tests:
    - Push all nodes onto `SetupState`, start from furthest.
    - Register fixture finalizers to repective node in `SetupState` according to its scope.
    Setup flow for async pytest tests:
    - Setup group
        - Push all nodes onto `SetupState`, start from furthest.
        - The node on the face will be `AsyncioConcurrentGroup`.
    - Setup individual tests.
        - Individual tests will not be pushed to SetupState.
        - If non function scoped, register finalizers on parent node in `SetupState`
        - If function scoped, register finalizers on its group.
    """

    def inner() -> None:
        if not item.group.has_setup:
            item.ihook.pytest_runtest_setup_async_group(item=item.group)

        item.config.pluginmanager.subset_hook_caller(
            "pytest_runtest_setup", [item.config.pluginmanager.get_plugin("runner")]
        )(item=item)

    return inner


def _teardown_child(
    item: AsyncioConcurrentGroupMember,
    nextgroup: Optional[AsyncioConcurrentGroup],
) -> Callable[[], None]:
    """
    Similar to setup.
    Teardown flow for normal pytest tests:
    - Remove all nodes not used in next item from `SetupState`, start from closest.
    - Call all finalizer on node removed.
    Teardown flow for async pytest tests:
    - Teardown individual tests.
        - Remove individual test from group, and let group call their finalizers.
    - Teardown group.
        - Remove all nodes not used in next item from `SetupState`, start from closest.
    """

    def inner() -> None:
        exceptions = []
        try:
            item.config.pluginmanager.subset_hook_caller(
                "pytest_runtest_teardown", [item.config.pluginmanager.get_plugin("runner")]
            )(item=item, nextitem=nextgroup)
        except Exception as e:
            exceptions.append(e)

        try:
            if len(item.group.children_finalizer) == 0:
                item.ihook.pytest_runtest_teardown_async_group(item=item.group, nextitem=nextgroup)
        except Exception as e:
            if isinstance(e, BaseExceptionGroup):
                exceptions.extend(e.exceptions)  # type: ignore
            else:
                exceptions.append(e)

        if len(exceptions) == 1:
            raise exceptions[0]
        elif len(exceptions) > 1:
            msg = f"errors while tearing down {item!r}"
            raise BaseExceptionGroup(msg, exceptions)

    return inner


# =========================== # group lifcycle # =========================== #


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
def pytest_runtest_setup_async_group(item: AsyncioConcurrentGroup) -> None:
    """
    AsyncioConcurrentGroup is the only node got push to 'SetupState' in pytest.
    AsyncioConcurrentGroupMember are registered under the hood of their group.
    """
    assert not item.has_setup
    item.ihook.pytest_runtest_setup(item=item)
    item.has_setup = True


@pytest.hookimpl(specname="pytest_runtest_teardown_async_group")
def pytest_runtest_teardown_async_group(
    item: "AsyncioConcurrentGroup",
    nextitem: "AsyncioConcurrentGroup",
) -> None:
    assert item.has_setup
    assert len(item.children_finalizer) == 0
    item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
    item.has_setup = False


# =========================== # async lifcycle redirection # =========================== #


@pytest.hookimpl(specname="pytest_runtest_setup")
def pytest_runtest_setup_handle_async_function(item: pytest.Item) -> None:
    """We have skipped the one in pytest.runner, but we still need setup."""
    if not isinstance(item, AsyncioConcurrentGroupMember):
        return

    item.setup()


@pytest.hookimpl(specname="pytest_runtest_teardown")
def pytest_runtest_teardown_handle_async_function(
    item: pytest.Item, nextitem: Optional[pytest.Item]
) -> None:
    """
    We have skipped the one in pytest.runner,
    redirecting to AsyncioConcurrentGroup for teardown.
    """
    if not isinstance(item, AsyncioConcurrentGroupMember):
        return

    item.group.teardown_child(item)


# =========================== # warnings #===========================#


@pytest.hookimpl(specname="pytest_runtest_protocol_async_group", wrapper=True, tryfirst=True)
def pytest_runtest_protocol_async_group_warning(
    group: "AsyncioConcurrentGroup", nextgroup: Optional["AsyncioConcurrentGroup"]
) -> Generator[None, object, object]:
    config = group.children[0].config
    with pytest_warnings.catch_warnings_for_item(
        config=config, ihook=group.children[0].ihook, when="runtest", item=None
    ):
        return (yield)


# =========================== # helper #===========================#


def _get_asyncio_concurrent_mark(item: pytest.Item) -> Optional[pytest.Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: pytest.Item) -> str:
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
def _call_and_report(
    func: Callable[[], None],
    item: pytest.Item,
    when: Literal["setup", "teardown"],
) -> pytest.TestReport:
    reraise: tuple[type[BaseException], ...] = (outcomes.Exit,)
    if not item.config.getoption("usepdb", False):
        reraise += (KeyboardInterrupt,)

    call = pytest.CallInfo.from_call(func, when=when, reraise=reraise)
    report: pytest.TestReport = item.ihook.pytest_runtest_makereport(item=item, call=call)
    item.ihook.pytest_runtest_logreport(report=report)

    if (
        call.excinfo
        and not isinstance(call.excinfo.value, outcomes.Skipped)
        and not hasattr(report, "wasxfail")
    ):
        item.ihook.pytest_exception_interact(node=item, call=call, report=report)
    return report
