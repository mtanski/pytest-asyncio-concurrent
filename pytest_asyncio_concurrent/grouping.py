import copy
import sys
from typing import Any, Callable, Dict, List

import pytest
from _pytest import scope
from _pytest import outcomes


if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


class PytestAysncioGroupInvokeError(BaseException):
    """Raised when AsyncioGroup got invoked"""


class AsyncioConcurrentGroup(pytest.Function):
    """
    The Function Group containing underneath children functions.
    And Holding the finalizer registered on all children nodes.
    """

    children: List["AsyncioConcurrentGroupMember"]
    children_have_same_parent: bool
    children_finalizer: Dict["AsyncioConcurrentGroupMember", List[Callable[[], Any]]]
    has_setup: bool

    def __init__(
        self,
        parent,
        originalname: str,
    ):
        self.children_have_same_parent = True
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

    def add_child(self, item: pytest.Function) -> "AsyncioConcurrentGroupMember":
        child_parent = list(item.iter_parents())[1]

        if child_parent is not self.parent:
            self.children_have_same_parent = False
            for child in self.children:
                child.add_marker("skip")

        if not self.children_have_same_parent:
            item.add_marker("skip")

        member = AsyncioConcurrentGroupMember.promote_from_function(item, self)
        self.children.append(member)
        self.children_finalizer[member] = []
        return member

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
    Redirecting addfinalizer to group. To handle teardown by ourselves.
    """

    group: AsyncioConcurrentGroup
    _inner: pytest.Function

    @staticmethod
    def promote_from_function(
        item: pytest.Function, group: AsyncioConcurrentGroup
    ) -> "AsyncioConcurrentGroupMember":
        AsyncioConcurrentGroupMember._rewrite_function_scoped_fixture(item)
        member = AsyncioConcurrentGroupMember.from_parent(
            name=item.name,
            parent=item.parent,
            callspec=item.callspec if hasattr(item, "callspec") else None,
            callobj=item.obj,
            keywords=item.keywords,
            fixtureinfo=item._fixtureinfo,
            originalname=item.originalname,
        )

        member.group = group
        member._inner = item
        return member

    def addfinalizer(self, fin: Callable[[], Any]) -> None:
        assert callable(fin)
        self.group.children_finalizer[self].append(fin)

    @staticmethod
    def _rewrite_function_scoped_fixture(item: pytest.Function):
        # TODO: this function in general utilized some private properties.
        # research to clean up as much as possible.

        for name, fixturedefs in item._fixtureinfo.name2fixturedefs.items():
            if hasattr(item, "callspec") and name in item.callspec.params.keys():
                continue

            if fixturedefs[-1]._scope != scope.Scope.Function:
                continue

            new_fixdef = copy.copy(fixturedefs[-1])
            if hasattr(new_fixdef, "_finalizers"):
                new_fixdef._finalizers = []  # type: ignore

            fixturedefs = list(fixturedefs[0:-1]) + [new_fixdef]
            item._fixtureinfo.name2fixturedefs[name] = fixturedefs
