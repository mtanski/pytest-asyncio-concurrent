import sys
from typing import Any, Callable, Dict, List

import pytest
from _pytest import outcomes


if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


class PytestAsyncioConcurrentGroupingWarning(pytest.PytestWarning):
    """Raised when Test from different parent grouped into same group."""


class PytestAsyncioConcurrentInvalidMarkWarning(pytest.PytestWarning):
    """Raised when Sync Test got marked."""


class PytestAysncioGroupInvokeError(BaseException):
    """Raised when AsyncioGroup got invoked"""


class AsyncioConcurrentGroup(pytest.Function):
    """
    The Function Group containing underneath children functions.
    AsyncioConcurrentGroup will be pushed onto `SetupState` representing all children.
    and in charging of holding and tearing down the finalizers from all children nodes.
    """

    children: List["AsyncioConcurrentGroupMember"]
    children_finalizer: Dict["AsyncioConcurrentGroupMember", List[Callable[[], Any]]]
    has_setup: bool

    def __init__(
        self,
        parent,
        originalname: str,
    ):
        self.has_setup = False
        self.children = []
        self.children_finalizer = {}
        super().__init__(
            name=originalname,
            parent=parent,
            callobj=lambda: None,
        )

    def runtest(self) -> None:
        raise PytestAysncioGroupInvokeError()

    def setup(self) -> None:
        pass

    def add_child(self, item: "AsyncioConcurrentGroupMember") -> None:
        item.group = self
        self.children.append(item)
        self.children_finalizer[item] = []

    def teardown_child(self, item: "AsyncioConcurrentGroupMember") -> None:
        finalizers = self.children_finalizer.pop(item)
        exceptions = []

        while finalizers:
            fin = finalizers.pop()
            try:
                fin()
            except outcomes.TEST_OUTCOME as e:
                exceptions.append(e)

        if len(exceptions) == 1:
            raise exceptions[0]
        elif len(exceptions) > 1:
            msg = f"errors while tearing down {item!r}"
            raise BaseExceptionGroup(msg, exceptions[::-1])

    def remove_child(self, item: "AsyncioConcurrentGroupMember") -> None:
        assert item in self.children
        self.children.remove(item)
        self.children_finalizer.pop(item)


class AsyncioConcurrentGroupMember(pytest.Function):
    """
    A light wrapper around Function, representing a child of AsyncioConcurrentGroup.
    The member won't be pushed to 'SetupState' to avoid assertion error. So instead of
    registering finalizers to the node, it redirecting addfinalizer to its group.
    """

    group: AsyncioConcurrentGroup
    _inner: pytest.Function

    @staticmethod
    def promote_from_function(item: pytest.Function) -> "AsyncioConcurrentGroupMember":
        member = AsyncioConcurrentGroupMember.from_parent(
            name=item.name,
            parent=item.parent,
            callspec=item.callspec if hasattr(item, "callspec") else None,
            callobj=item.obj,
            keywords=item.keywords,
            fixtureinfo=item._fixtureinfo,
            originalname=item.originalname,
        )

        member._inner = item
        return member

    def addfinalizer(self, fin: Callable[[], Any]) -> None:
        assert callable(fin)
        self.group.children_finalizer[self].append(fin)
