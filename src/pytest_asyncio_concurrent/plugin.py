import asyncio
import sys
from typing import  Any, Callable, List, Optional, Sequence, Coroutine, Set, Dict
import uuid

import pytest
from _pytest.fixtures import FuncFixtureInfo
from pytest import (
    Item,
    Session,
    Config,
    Function,
    Mark,
)


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
    # print(f"group_name {group_name}", file=sys.stderr)
    parent = None
    for childFunc in children:
        p_it = childFunc.iter_parents()
        next(p_it)
        func_parent = next(p_it)
                
        if not parent:
            parent = func_parent
        elif parent is not func_parent:
            raise Exception("test case within same group should have same parent.")
    
    argnames: Set[str] = set()
    initialnames: Set[str] = set()
    names_closure: Set[str] = set()
    name2fixturedefs: Dict[str, Sequence[pytest.FixtureDef[Any]]] = {}
    for childFunc in children:
        argnames.update(childFunc._fixtureinfo.argnames)
        initialnames.update(childFunc._fixtureinfo.initialnames)
        names_closure.update(childFunc._fixtureinfo.names_closure)
        name2fixturedefs.update(childFunc._fixtureinfo.name2fixturedefs)
        
    fixtureInfo = FuncFixtureInfo(tuple(argnames), tuple(initialnames), list(names_closure), name2fixturedefs)
    
    def wrap_children_into_single_callobj() -> Callable[..., None]:
        def inner(*args, **kwargs) -> None:
            coros: List[Coroutine] = []
            loop = asyncio.get_event_loop()
            
            for childFunc in children:
                testfunction = childFunc.obj
                testargs = {arg: kwargs[arg] for arg in childFunc._fixtureinfo.argnames}
                coro = testfunction(**testargs)
                coros.append(coro)            
            
            loop.run_until_complete(asyncio.gather(*coros))
        
        return inner
    
    g_function = Function.from_parent(
        parent, 
        name=f"ayncio_concurrent_test_group[{group_name}]",
        callobj=wrap_children_into_single_callobj(),
        fixtureinfo=fixtureInfo
    )
    
    setattr(g_function, "_children", children)
    return g_function
    

def _get_asyncio_concurrent_mark(item: Item) -> Optional[Mark]:
    return item.get_closest_marker("asyncio_concurrent")


def _get_asyncio_concurrent_group(item: Item) -> str:
    marker = item.get_closest_marker("asyncio_concurrent")
    assert marker is not None

    return marker.kwargs.get("group", f"default_group_of_{item.name}_{uuid.uuid4()}")
