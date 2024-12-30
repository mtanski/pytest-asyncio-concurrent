import asyncio
from contextlib import contextmanager
import inspect
from typing import Any, Callable, Generator, List, Optional, Coroutine, Dict, cast
import uuid
import warnings
import copy

import pytest
from _pytest import scope, timing, outcomes, runner, nodes, reports, warnings as pytest_warning
from pytest import (
    CallInfo,
    ExceptionInfo,
    PytestWarning,
    Session,
    Config,
    Function,
    Mark,
)

from .fixtures import *
from .hooks import *


class PytestAsyncioConcurrentGroupingWarning(PytestWarning):
    """Raised when Test from different parent grouped into same group."""


class PytestAsyncioConcurrentInvalidMarkWarning(PytestWarning):
    """Raised when Sync Test got marked."""

class PytestAysncioGroupInvokeError(BaseException):
    """Raised when AsyncioGroup got invoked"""    


# =========================== # Config # =========================== #
def pytest_configure(config: Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio_concurrent(group, timeout): " "mark the async tests to run concurrently",
    )


@pytest.hookimpl
def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    from . import hooks
    pluginmanager.add_hookspecs(hooks)


class AsyncioConcurrentGroup(Function):
    """
    The Function Group containing underneath children functions.
    """

    _children: List['AsyncioConcurrentGroupMember']
    have_same_parent: bool
    
    def __init__(self, 
        parent: nodes.Node, 
        originalname: str,
    ):
        self.have_same_parent = True
        self._children = []
        super().__init__(
            name=originalname,
            parent=parent,
            callobj=lambda : None,
        )

    def runtest(self) -> None:
        raise PytestAysncioGroupInvokeError()

    def setup(self) -> None:
        pass

    @property
    def children(self) -> List['AsyncioConcurrentGroupMember']:
        return self._children

    def add_child(self, item: Function) -> None:
        child_parent = list(item.iter_parents())[1]
        
        if child_parent is not self.parent:
            self.have_same_parent = False
            for child in self._children:
                child.add_marker("skip")
        
        if not self.have_same_parent:
            item.add_marker("skip")
        
        self._children.append(AsyncioConcurrentGroupMember.promote_from_function(item, self))


class AsyncioConcurrentGroupMember(Function):
    group: AsyncioConcurrentGroup
    _inner: Function
        
    @staticmethod
    def promote_from_function(item: Function, group: AsyncioConcurrentGroup) -> 'AsyncioConcurrentGroupMember':
        member = AsyncioConcurrentGroupMember.from_parent(
            name=item.name,
            parent=item.parent,
            callspec=item.callspec if hasattr(item, 'callspec') else None,
            callobj=item.obj,
            keywords=item.keywords,
            fixtureinfo=item._fixtureinfo,
            originalname=item.originalname,
        )

        AsyncioConcurrentGroupMember._rewrite_function_scoped_fixture(member)
        
        member.group = group
        member._inner = item
        return member
    
    def addfinalizer(self, fin):
        return self.group.addfinalizer(fin)

    @staticmethod
    def _rewrite_function_scoped_fixture(item: Function):
        for name, fixturedefs in item._request._arg2fixturedefs.items():
            if hasattr(item, "callspec") and name in item.callspec.params.keys():
                continue

            if fixturedefs[-1]._scope != scope.Scope.Function:
                continue
            
            new_fixdef = copy.copy(fixturedefs[-1])
            fixturedefs = list(fixturedefs[0:-1]) + [new_fixdef]
            item._request._arg2fixturedefs[name] = fixturedefs


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
            asycio_concurrent_groups[concurrent_group_name] = AsyncioConcurrentGroup.from_parent(
                parent=item.parent, originalname=f'AsyncioConcurrentGroup[{concurrent_group_name}]'
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
                Asyncio Concurrent Group [{group.name}] has children from different parents,
                skipping all of it's children.
                """
            )
        )
    
    children_passed_setup: List[Function] = []
    
    group.ihook.pytest_runtest_setup_async_group(group=group)
    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logstart(
            nodeid=childFunc.nodeid, location=childFunc.location
        )
        
    for childFunc in group.children:
        # if i == 0:
        #     report = runner.call_and_report(childFunc, "setup")
        # else:
        with _setupstate_setup_hijacked():
            report = runner.call_and_report(childFunc, "setup")            

        if report.passed:
            children_passed_setup.append(childFunc)
    
    _pytest_runtest_call_async_group(children_passed_setup)

    for childFunc in group.children:
        runner.call_and_report(childFunc, "teardown", nextitem=nextgroup)
    
    for childFunc in group.children:
        childFunc.ihook.pytest_runtest_logfinish(
            nodeid=childFunc.nodeid, location=childFunc.location
        )
        
    group.ihook.pytest_runtest_teardown_async_group(group=group, nextgroup=nextgroup)

    return True
        
        
def _pytest_runtest_call_async_group(items: List[Function]) -> None:
    def hook_invoker(item: Function) -> Callable[[], Coroutine]:
        def inner() -> Coroutine:
            return childFunc.ihook.pytest_runtest_call_async(item=item)

        return inner
        
    coros: List[Coroutine] = []
    loop = asyncio.get_event_loop()

    for childFunc in items:
        coros.append(_async_callinfo_from_call(hook_invoker(childFunc)))

    call_result = loop.run_until_complete(asyncio.gather(*coros))

    for childFunc, call in zip(items, call_result):
        report: reports.TestReport = childFunc.ihook.pytest_runtest_makereport(item=childFunc, call=call)
        childFunc.ihook.pytest_runtest_logreport(report=report)


@pytest.hookimpl(specname="pytest_runtest_call_async")
async def pytest_runtest_call_async_impl(item: Function) -> object:
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
def pytest_runtest_setup_async_group_impl(group: AsyncioConcurrentGroup) -> None:
    group.ihook.pytest_runtest_setup(item=group)


@pytest.hookimpl(specname="pytest_runtest_teardown_async_group")
def pytest_runtest_teardown_async_group_impl(
    group: 'AsyncioConcurrentGroup', 
    nextgroup: 'AsyncioConcurrentGroup'
) -> None:
    group.ihook.pytest_runtest_teardown(item=group, nextitem=nextgroup)


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


def _pytest_setupstate_setup_without_assert(self: runner.SetupState, item: Function) -> None:
    """temporary POC hack, make a hook to get replace this"""
    item.setup()

        
@contextmanager
def _setupstate_setup_hijacked() -> Generator[None, None, None]:
    original = getattr(runner.SetupState, "setup")
    setattr(runner.SetupState, "setup", _pytest_setupstate_setup_without_assert)

    yield

    setattr(runner.SetupState, "setup", original)


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
