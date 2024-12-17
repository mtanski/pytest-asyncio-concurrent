import asyncio
import sys
from typing import Callable, Generator, List, Optional, Sequence, Coroutine, Set, Dict, cast
import uuid

import pytest
from _pytest.fixtures import FuncFixtureInfo, SubRequest
from pytest import (
    FixtureDef,
    Item,
    Session,
    Config,
    Function,
    Mark,
)

CONCURRENT_CHILDREN = "_pytest_asyncio_concurrent_children"

def pytest_configure(config: Config) -> None:
    config.addinivalue_line(
        "markers", "asyncio_concurrent(group, timeout): " "mark the tests to run concurrently"
    )
    

@pytest.hookimpl(specname="pytest_collection_modifyitems", trylast=True)
def pytest_collection_modifyitems_sort_by_group(
    session: Session, config: Config, items: List[Function]
) -> None:
    """
    Group items with same asyncio concurrent group together, so they can be executed together in outer loop.
    """
    asycio_concurrent_groups: Dict[str, List[Function]] = {}
    
    for item in items:
        if _get_asyncio_concurrent_mark(item) is None:
            continue
        
        concurrent_group_name = _get_asyncio_concurrent_group(item)
        if concurrent_group_name not in asycio_concurrent_groups:
            asycio_concurrent_groups[concurrent_group_name] = []
        asycio_concurrent_groups[concurrent_group_name].append(item)
        
    for asyncio_items in asycio_concurrent_groups.values():
        for item in asyncio_items:
            items.remove(item)
    
    for group_name, asyncio_items in asycio_concurrent_groups.items():
        items.append(group_asyncio_concurrent_function(group_name, asyncio_items))

def group_asyncio_concurrent_function(group_name:str, children: List[Function]):
    parent = None
    for childFunc in children:
        p_it = childFunc.iter_parents()
        next(p_it)
        func_parent = next(p_it)
                
        if not parent:
            parent = func_parent
        elif parent is not func_parent:
            raise Exception("test case within same group should have same parent.")
    
    g_function = Function.from_parent(
        parent, 
        name=f"ayncio_concurrent_test_group[{group_name}]",
        callobj=wrap_children_into_single_callobj(children),
    )
    
    setattr(g_function, CONCURRENT_CHILDREN, children)
    return g_function
    
    
def wrap_children_into_single_callobj(children: list[Function]) -> Callable[..., None]:
    def inner() -> None:
        coros: List[Coroutine] = []
        loop = asyncio.get_event_loop()
        
        for childFunc in children:
            testfunction = childFunc.obj
            funcargs = childFunc.funcargs
            testargs = {arg: funcargs[arg] for arg in childFunc._fixtureinfo.argnames}
            coro = testfunction(**testargs)
            coros.append(coro)            
        
        loop.run_until_complete(asyncio.gather(*coros))
    
    return inner
    
# @pytest.hookimpl(tryfirst=True)
# def pytest_fixture_setup(
#     fixturedef: FixtureDef[object], request: SubRequest
# ) -> Generator[None, object, object]:
#     print(fixturedef, file=sys.stderr)
#     print(request, file=sys.stderr)
#     return (yield)

@pytest.hookimpl(specname="pytest_runtest_setup", trylast=True)
def pytest_runtest_setup_group_children(item: Item) -> None: # type: ignore
    if not hasattr(item, CONCURRENT_CHILDREN):
        return
    
    try:
        for child in cast(List[Item], getattr(item, CONCURRENT_CHILDREN)):
            item.session._setupstate.stack[child] = ([child.teardown], None)
            child.setup()
    except Exception as ex:
        raise Exception(f"Error when setting up {item.name}") from ex

    return 

@pytest.hookimpl(specname="pytest_runtest_teardown", tryfirst=True)
def pytest_runtest_teardown_group_children(item: Item, nextitem: Item | None) -> None: # type: ignore
    if not hasattr(item, CONCURRENT_CHILDREN):
        return
    
    print(item.session._setupstate.stack, file=sys.stderr)
    exceptions: List[BaseException] = []
    for child in cast(List[Item], getattr(item, CONCURRENT_CHILDREN)):
        finalizers, _ = item.session._setupstate.stack.pop(child)
        these_exceptions = []
        while finalizers:
            fin = finalizers.pop()
            try:
                fin()
            except Exception as e:
                these_exceptions.append(e)

        if len(these_exceptions) == 1:
            exceptions.extend(these_exceptions)
        elif these_exceptions:
            msg = f"Errors during tearing down {child}"
            exceptions.append(BaseExceptionGroup(msg, these_exceptions[::-1]))

    if exceptions:
        raise BaseExceptionGroup(f"Errors during tearing down {item.name}", exceptions)
    
    return

def _get_asyncio_concurrent_mark(item: Item) -> Optional[Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: Item) -> str:
    marker = item.get_closest_marker("asyncio_concurrent")
    assert marker is not None

    return marker.kwargs.get("group", f"anonymous_[{uuid.uuid4()}]")
