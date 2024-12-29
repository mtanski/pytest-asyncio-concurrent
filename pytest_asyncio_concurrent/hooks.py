import pytest
from typing import TYPE_CHECKING, Optional, Coroutine

if TYPE_CHECKING:
    from .plugin import AsyncioConcurrentGroup

@pytest.hookspec(firstresult=True)
def pytest_runtest_protocol_async_group(
    group: 'AsyncioConcurrentGroup', 
    nextgroup: Optional['AsyncioConcurrentGroup']
) -> object:
    """
    the pytest_runtest_protocol for async group.
    """

@pytest.hookspec(firstresult=True)
def pytest_runtest_call_async(item: pytest.Item) -> Optional[Coroutine]:
    """
    the pytest_runtest_call for async function.
    """