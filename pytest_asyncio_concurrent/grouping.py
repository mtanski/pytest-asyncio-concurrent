import copy
import inspect
import sys
from typing import Any, Callable, Dict, List, Sequence
import warnings

import pytest
from _pytest import fixtures
from _pytest import outcomes


if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


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
    The member won't be pushed to 'SetupState' to avoid assertion error. So instead of
    registering finalizers to the node, it redirecting addfinalizer to its group.
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

        # This is to solve two problem:
        # 1. Funtion scoped fixture result value got shared in different tests in same group.
        # 2. And fixture teardown got registered under right test using it.

        # FixtureDef for each fixture is unique and held in FixtureManger and got injected into
        # pytest.Item when the Item is constructed, and FixtureDef class is also in charge of
        # holding finalizers and cache value.

        # Fixture value caching is highly coupled with pytest entire lifecycle, implementing a
        # thirdparty fixture cache manager will be hard.
        # The first problem can be solved by shallow copy the fixtureDef, to split the cache_value.
        # The finalizers are stored in a private list property in fixtureDef, which need to touch
        # private API anyway.

        # If the private API change, finalizer errors from this fixture but in different
        # tests in same group will be reported in one function.

        for name, fixturedefs in item._fixtureinfo.name2fixturedefs.items():
            if hasattr(item, "callspec") and name in item.callspec.params.keys():
                continue

            if fixturedefs[-1].scope != "function":
                continue

            try:
                new_fixdef = fixtures.FixtureDef(
                    argname=fixturedefs[-1].argname,
                    scope=fixturedefs[-1].scope,
                    baseid=fixturedefs[-1].baseid,
                    config=item.config,
                    func=fixturedefs[-1].func,
                    ids=fixturedefs[-1].ids,
                    params=fixturedefs[-1].params,
                    _ispytest=True,  # Have to work around.
                )
            except:
                warnings.warn(
                    f"""
                    pytest {pytest.__version__} has a different private costructor API 
                    from what this plugin utilize. The teardown error in fixture {name}
                    might be reported in wrong place. 
                    Please raise an issue.
                """
                )
                new_fixdef = copy.copy(fixturedefs[-1])

            fixturedefs = list(fixturedefs[0:-1]) + [new_fixdef]
            item._fixtureinfo.name2fixturedefs[name] = fixturedefs


# =========================== # deselect # =========================== #


@pytest.hookimpl(specname="pytest_deselected")
def pytest_deselected_update_group(items: Sequence[pytest.Item]) -> None:
    """Remove item from group if deselected."""
    for item in items:
        if isinstance(item, AsyncioConcurrentGroupMember):
            item.group.remove_child(item)


# =========================== # setup & call & teardown # =========================== #


@pytest.hookimpl(specname="pytest_runtest_call_async")
async def pytest_runtest_call_async(item: pytest.Function) -> object:
    if not inspect.iscoroutinefunction(item.obj):
        warnings.warn(
            PytestAsyncioConcurrentInvalidMarkWarning(
                "Marking a sync function with @asyncio_concurrent is invalid."
            )
        )

        pytest.skip("Marking a sync function with @asyncio_concurrent is invalid.")

    testfunction = item.obj
    testargs = {arg: item.funcargs[arg] for arg in item._fixtureinfo.argnames}
    return await testfunction(**testargs)


@pytest.hookimpl(specname="pytest_runtest_setup_async_group")
def pytest_runtest_setup_async_group(item: AsyncioConcurrentGroup) -> None:
    """
    AsyncioConcurrentGroup is the only node got push to 'SetupState' in pytest.
    AsyncioConcurrentGroupMember are registered under the hood of their group.
    """
    assert not item.has_setup
    item.ihook.pytest_runtest_setup(item=item)
    item.has_setup = True


@pytest.hookimpl(specname="pytest_runtest_teardown_async_group")
def pytest_runtest_teardown_async_group(
    item: "AsyncioConcurrentGroup",
    nextitem: "AsyncioConcurrentGroup",
) -> None:
    assert item.has_setup
    assert len(item.children_finalizer) == 0
    item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
    item.has_setup = False
