import asyncio
from typing import Any, Callable, Generator, List, Optional, Coroutine, Dict, cast
import uuid

import pytest
from _pytest import scope, timing, outcomes, runner
from pytest import (
    CallInfo,
    ExceptionInfo,
    FixtureDef,
    Item,
    Session,
    Config,
    Function,
    Mark,
    TestReport,
)


############################################################################ Config & Collection ############################################################################
def pytest_configure(config: Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio_concurrent(group, timeout): " "mark the tests to run concurrently",
    )


@pytest.hookimpl(specname="pytest_runtestloop", wrapper=True)
def pytest_runtestloop_wrap_items_by_group(
    session: Session
) -> Generator[None, Any, Any]:
    """
    Group items with same asyncio concurrent group together,
    so they can be executed together in outer loop.
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

class AsyncioConcurrentGroup(Function):
    _pytest_asyncio_concurrent_children: List[Function] = []
    _pytest_asyncio_concurrent_children_call_report: List[TestReport] = []

def group_asyncio_concurrent_function(group_name: str, children: List[Function]) -> AsyncioConcurrentGroup:
    parent = None
    for childFunc in children:
        p_it = childFunc.iter_parents()
        next(p_it)
        func_parent = next(p_it)

        if not parent:
            parent = func_parent
        elif parent is not func_parent:
            raise Exception("test case within same group should have same parent.")
        
        _rewrite_function_scoped_fixture(childFunc)

    g_function = AsyncioConcurrentGroup.from_parent(
        parent,
        name=f"ayncio_concurrent_test_group[{group_name}]",
        callobj=lambda: None,
    )

    g_function._pytest_asyncio_concurrent_children = children
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


############################################################################ function call & setup & teardown ############################################################################



@pytest.hookimpl(specname="pytest_runtest_setup", wrapper=True)
def pytest_runtest_setup_group_children(item: Item) -> Generator[None, None, None]:
    result = yield
    
    if not isinstance(item , AsyncioConcurrentGroup):
        return result

    for childFunc in item._pytest_asyncio_concurrent_children:
        call = CallInfo.from_call(_pytest_simple_setup(childFunc), "setup")
        report: TestReport = childFunc.ihook.pytest_runtest_makereport(item=childFunc, call=call)        
        childFunc.ihook.pytest_runtest_logreport(report=report)  

    return result


def _pytest_simple_setup(item: Item) -> Callable[[], None]:
    def inner() -> None:
        item.session._setupstate.stack[item] = ([item.teardown], None)
        item.setup()
    
    return inner


@pytest.hookimpl(specname="pytest_pyfunc_call", tryfirst=True)
def pytest_pyfunc_call_handle_group(pyfuncitem: Function) -> Any:
    if not isinstance(pyfuncitem , AsyncioConcurrentGroup):
        return None
    
    coros: List[Coroutine] = []
    loop = asyncio.get_event_loop()

    for childFunc in pyfuncitem._pytest_asyncio_concurrent_children:
        coros.append(_async_callinfo_from_call(_pytest_function_call_async(childFunc)))

    result = loop.run_until_complete(asyncio.gather(*coros))
    
    for childFunc, call in zip(pyfuncitem._pytest_asyncio_concurrent_children, result):
        report: TestReport = childFunc.ihook.pytest_runtest_makereport(item=childFunc, call=call)
        pyfuncitem._pytest_asyncio_concurrent_children_call_report.append(report)

    return True


def _pytest_function_call_async(item: Function) -> Callable[[], Coroutine]:
    async def inner() -> Any:
        testfunction = item.obj
        testargs = {arg: item.funcargs[arg] for arg in item._fixtureinfo.argnames}
        return await testfunction(**testargs)

    return inner


# referencing CallInfo.from_call
async def _async_callinfo_from_call(func: Callable[[], Coroutine]) -> CallInfo:
    excinfo = None
    start = timing.time()
    precise_start = timing.perf_counter()
    try:
        result = await func()
    except BaseException:
        excinfo = ExceptionInfo.from_current()
        if isinstance(excinfo.value, outcomes.Exit):
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
def pytest_runtest_teardown_group_children(item: Item, nextitem: Optional[Item]) -> Generator[None, None, None]:    
    if not isinstance(item , AsyncioConcurrentGroup):
        return (yield)

    for childFunc in item._pytest_asyncio_concurrent_children:
        call = CallInfo.from_call(_pytest_simple_teardown(childFunc), "teardown")
        report: TestReport = childFunc.ihook.pytest_runtest_makereport(item=childFunc, call=call)
        childFunc.ihook.pytest_runtest_logreport(report=report)

    return (yield)

def _pytest_simple_teardown(item: Item) -> Callable[[], None]:
    def inner() -> None:
        finalizers, _ = item.session._setupstate.stack.pop(item)
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

############################################################################ reporting ############################################################################

@pytest.hookimpl(specname="pytest_runtest_protocol", tryfirst=True)
def pytest_runtest_protocol_skip_logging_for_group(item: Item, nextitem: Optional[Item]) -> Optional[bool]:
    if not isinstance(item , AsyncioConcurrentGroup):
        return None
    
    # More testing required here, tests being reported twice on terminal if running in verbose mode.
    for childFunc in item._pytest_asyncio_concurrent_children:
        childFunc.ihook.pytest_runtest_logstart(nodeid=childFunc.nodeid, location=childFunc.location)

    runner.runtestprotocol(item, nextitem=nextitem, log=False)  # this is the only difference from the orignal hook.
    for childReport in item._pytest_asyncio_concurrent_children_call_report:
        item.ihook.pytest_runtest_logreport(report=childReport)
    
    for childFunc in item._pytest_asyncio_concurrent_children:
        childFunc.ihook.pytest_runtest_logfinish(nodeid=childFunc.nodeid, location=childFunc.location)

    return True
    

def _get_asyncio_concurrent_mark(item: Item) -> Optional[Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: Item) -> str:
    marker = item.get_closest_marker("asyncio_concurrent")
    assert marker is not None

    return marker.kwargs.get("group", f"anonymous_[{uuid.uuid4()}]")
