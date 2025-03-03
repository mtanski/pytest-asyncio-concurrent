import inspect
import asyncio
import functools

from typing import Any, Dict, Generator

import pytest

from .context_aware_fixture import ContextAwareFixtureResult


@pytest.hookimpl(specname="pytest_fixture_setup", wrapper=True)
def pytest_fixture_setup_wrap_async(
    fixturedef: pytest.FixtureDef, request: pytest.FixtureRequest
) -> Generator[None, Any, Any]:
    is_context_aware = _is_context_aware_fixture(fixturedef.func)
    _wrap_async_fixture(fixturedef)

    if is_context_aware:
        _wrap_context_aware_fixture(fixturedef)

    return (yield)


@pytest.hookimpl(specname="pytest_runtest_setup", wrapper=True, trylast=True)
def pytest_runtest_setup_context_aware_fixture(item: pytest.Function) -> Generator[None, Any, Any]:
    hook_result = yield
    for key in list(item.funcargs.keys()):
        value = item.funcargs[key]
        if isinstance(value, ContextAwareFixtureResult):
            item.funcargs[key] = value.request_value(item)

    return hook_result


def _wrap_async_fixture(fixturedef: pytest.FixtureDef) -> None:
    """Wraps the fixture function of an async fixture in a synchronous function."""
    if inspect.isasyncgenfunction(fixturedef.func):
        _wrap_asyncgen_fixture(fixturedef)
    elif inspect.iscoroutinefunction(fixturedef.func):
        _wrap_asyncfunc_fixture(fixturedef)


def _wrap_asyncgen_fixture(fixturedef: pytest.FixtureDef) -> None:
    fixtureFunc = fixturedef.func

    @functools.wraps(fixtureFunc)
    def _asyncgen_fixture_wrapper(**kwargs: Any):
        event_loop = asyncio.get_event_loop()
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


def _wrap_asyncfunc_fixture(fixturedef: pytest.FixtureDef) -> None:
    fixtureFunc = fixturedef.func

    @functools.wraps(fixtureFunc)
    def _async_fixture_wrapper(**kwargs: Dict[str, Any]):
        event_loop = asyncio.get_event_loop()

        async def setup():
            res = await fixtureFunc(**kwargs)
            return res

        return event_loop.run_until_complete(setup())

    fixturedef.func = _async_fixture_wrapper  # type: ignore[misc]


def _wrap_context_aware_fixture(fixturedef: pytest.FixtureDef) -> None:
    """
    Wraps the fixture function to replace fixture value using ContextAwareFixtureResult,
    and value are replaced back inside pytest_runtest_setup.
    """

    fixtureFunc = fixturedef.func

    @functools.wraps(fixtureFunc)
    def _context_aware_fixture_wrapper(**kwargs: Dict[str, Any]):
        return ContextAwareFixtureResult(functools.partial(fixtureFunc, **kwargs), fixturedef.scope)

    fixturedef.func = _context_aware_fixture_wrapper  # type: ignore[misc]
    fixturedef.func._context_aware = False  # type: ignore


def _is_context_aware_fixture(obj: Any) -> bool:
    obj = getattr(obj, "__func__", obj)  # instance method maybe?
    return getattr(obj, "_context_aware", False)
