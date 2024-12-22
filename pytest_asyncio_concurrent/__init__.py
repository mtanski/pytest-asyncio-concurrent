"""The main point for importing pytest-asyncio-concurrent items."""

from typing import List
from .plugin import AsyncioConcurrentGroup

__all__: List[str] = [
    AsyncioConcurrentGroup.__name__,
]
