# import pytest

pytest_plugins = ["pytester"]

# @pytest.fixture(autouse=True)
# def pytester_add_ini(pytester: pytest.Pytester) -> Generator[None, None, None]:
#     pytester.makeini(
#         """
#         [pytest]
#         asyncio_default_fixture_loop_scope=function
#         """
#     )
#     yield
