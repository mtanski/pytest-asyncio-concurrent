import copy
from typing import List

import pytest
from _pytest import nodes
from _pytest import scope


class PytestAysncioGroupInvokeError(BaseException):
    """Raised when AsyncioGroup got invoked"""


class AsyncioConcurrentGroup(pytest.Function):
    """
    The Function Group containing underneath children functions.
    """

    _children: List["AsyncioConcurrentGroupMember"]
    children_have_same_parent: bool
    has_setup: bool

    def __init__(
        self,
        parent: nodes.Node,
        originalname: str,
    ):
        self.children_have_same_parent = True
        self.has_setup = False
        self._children = []
        super().__init__(
            name=originalname,
            parent=parent,
            callobj=lambda: None,
        )

    def runtest(self) -> None:
        raise PytestAysncioGroupInvokeError()

    def setup(self) -> None:
        pass

    @property
    def children(self) -> List["AsyncioConcurrentGroupMember"]:
        return self._children

    def add_child(self, item: pytest.Function) -> None:
        child_parent = list(item.iter_parents())[1]

        if child_parent is not self.parent:
            self.children_have_same_parent = False
            for child in self._children:
                child.add_marker("skip")

        if not self.children_have_same_parent:
            item.add_marker("skip")

        self._children.append(AsyncioConcurrentGroupMember.promote_from_function(item, self))


class AsyncioConcurrentGroupMember(pytest.Function):
    group: AsyncioConcurrentGroup
    _inner: pytest.Function

    @staticmethod
    def promote_from_function(
        item: pytest.Function, group: AsyncioConcurrentGroup
    ) -> "AsyncioConcurrentGroupMember":
        member = AsyncioConcurrentGroupMember.from_parent(
            name=item.name,
            parent=item.parent,
            callspec=item.callspec if hasattr(item, "callspec") else None,
            callobj=item.obj,
            keywords=item.keywords,
            fixtureinfo=item._fixtureinfo,
            originalname=item.originalname,
        )

        AsyncioConcurrentGroupMember._rewrite_function_scoped_fixture(member)

        member.group = group
        member._inner = item
        return member

    def addfinalizer(self, fin):
        return self.group.addfinalizer(fin)

    @staticmethod
    def _rewrite_function_scoped_fixture(item: pytest.Function):
        for name, fixturedefs in item._request._arg2fixturedefs.items():
            if hasattr(item, "callspec") and name in item.callspec.params.keys():
                continue

            if fixturedefs[-1]._scope != scope.Scope.Function:
                continue

            new_fixdef = copy.copy(fixturedefs[-1])
            fixturedefs = list(fixturedefs[0:-1]) + [new_fixdef]
            item._request._arg2fixturedefs[name] = fixturedefs
