import pytest
from typing import Optional, Coroutine

from .plugin import AsyncioConcurrentGroup


@pytest.hookspec(firstresult=True)
def pytest_runtest_protocol_async_group(
    group: "AsyncioConcurrentGroup", nextgroup: Optional["AsyncioConcurrentGroup"]
) -> object:
    """
    The pytest_runtest_protocol for async group.
    """


@pytest.hookspec(firstresult=True)
def pytest_runtest_call_async(item: pytest.Item) -> Optional[Coroutine]:
    """
    The pytest_runtest_call for async function.
    """


@pytest.hookspec()
def pytest_runtest_setup_async_group(item: "AsyncioConcurrentGroup") -> None:
    """
    The pytest_runtest_setup for async group.
    Should be called before any of its children setup
    Also work as a safe guard to prevent polluting pytest environment.
    """


@pytest.hookspec()
def pytest_runtest_teardown_async_group(
    item: "AsyncioConcurrentGroup", nextitem: "AsyncioConcurrentGroup"
) -> None:
    """
    The pytest_runtest_teardown for async group.
    Should be called after all children finished teardown.
    Also work as a safe guard to prevent polluting pytest environment.
    """
