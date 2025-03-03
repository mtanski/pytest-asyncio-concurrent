import functools
import inspect
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    Literal,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)

import pytest


_ScopeName = Literal["session", "package", "module", "class", "function"]
_R = TypeVar("_R")


@overload
def context_aware_fixture(
    fixture_function: Callable[..., _R],
    *,
    scope: Union[_ScopeName, Callable[[str, pytest.Config], _ScopeName]] = ...,
    params: Optional[Iterable[object]] = ...,
    autouse: bool = ...,
    ids: Union[
        Iterable[Union[str, float, int, bool, None]], Callable[[Any], Optional[object]], None
    ] = ...,
    name: Optional[str] = ...,
) -> Callable[..., _R]: ...


@overload
def context_aware_fixture(
    fixture_function: None = ...,
    *,
    scope: Union[_ScopeName, Callable[[str, pytest.Config], _ScopeName]] = ...,
    params: Optional[Iterable[object]] = ...,
    autouse: bool = ...,
    ids: Union[
        Iterable[Union[str, float, int, bool, None]], Callable[[Any], Optional[object]], None
    ] = ...,
    name: Optional[str] = ...,
) -> Callable[[Callable[..., _R]], Callable[..., _R]]: ...


def context_aware_fixture(
    fixture_function: Optional[Callable[..., _R]] = None,
    **kwargs: Any,
) -> Union[Callable[..., _R], Callable[[Callable[..., _R]], Callable[..., _R]]]:
    if fixture_function is not None:
        _mark_function_context_aware(fixture_function)
        return pytest.fixture(fixture_function, **kwargs)
    else:

        @functools.wraps(pytest.fixture)
        def inner(fixture_function: Callable[..., _R]) -> Callable[..., _R]:
            _mark_function_context_aware(fixture_function)
            return pytest.fixture(fixture_function, **kwargs)

        return inner


def _mark_function_context_aware(obj: Any) -> None:
    if hasattr(obj, "__func__"):
        # instance method, check the function object
        obj = obj.__func__
    obj._context_aware = True


class ContextAwareFixtureResult(Generic[_R]):
    """
    A class used to replace fixture return value, and handling cache behavior inside itself.
    Based on the provided, it cache result on different level of node. So that fixture value
    can be handled across modules, classes, and functions.
    """

    def __init__(self, fixtureFunc: Callable[[], _R], scope: _ScopeName) -> None:
        self._fixtureFunc = fixtureFunc
        self._scope: _ScopeName = scope
        self._cache: Dict[pytest.Item, _R] = {}

    def request_value(self, item: pytest.Item) -> _R:
        cache_node = self._find_cache_node(item)
        if cache_node not in self._cache:
            if not inspect.isgeneratorfunction(self._fixtureFunc):
                self._cache[cache_node] = self._fixtureFunc()
            else:
                fixtureFunc = cast(Callable[[], Generator[_R, None, None]], self._fixtureFunc)
                gen = fixtureFunc()
                self._cache[cache_node] = next(gen)
                item.addfinalizer(functools.partial(_teardown_yield_fixture, gen))

        return self._cache[cache_node]

    def _find_cache_node(self, item: pytest.Item) -> pytest.Item:
        prev = item
        for node in item.iter_parents():
            node = cast(pytest.Item, node)
            if _is_scope_bigger(_to_scope_name(node), self._scope):
                return prev
            prev = node

        return prev


def _is_scope_bigger(scope1: _ScopeName, scope2: _ScopeName) -> bool:
    scopes = ["session", "package", "module", "class", "function"]
    return scopes.index(scope1) < scopes.index(scope2)


def _to_scope_name(item: pytest.Item) -> _ScopeName:
    if isinstance(item, pytest.Function):
        return "function"
    elif isinstance(item, pytest.Class):
        return "class"
    elif isinstance(item, pytest.Module):
        return "module"
    elif (
        isinstance(item, pytest.Package)
        or isinstance(item, pytest.Dir)
        or isinstance(item, pytest.Directory)
    ):
        return "package"
    elif isinstance(item, pytest.Session):
        return "session"
    else:
        raise Exception(f"can not find valid scope for {item}.")


def _teardown_yield_fixture(it) -> None:
    try:
        next(it)
    except StopIteration:
        pass
