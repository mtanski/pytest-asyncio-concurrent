# from textwrap import dedent
# import pytest

# def test_fixture_handling(pytester: pytest.Pytester):
#     """Make sure that pytest accepts our fixture."""

#     pytester.makepyfile(
#         dedent(
#             """\
#             import asyncio
#             import pytest

#             @pytest.mark.asyncio_concurrent(group="A")
#             async def test_group_A():
#                 await asyncio.sleep(3)
#                 assert 1 == 1

#             @pytest.mark.asyncio_concurrent(group="B")
#             async def test_group_B():
#                 await asyncio.sleep(2)
#                 assert 1 == 1
#             """
#         )
#     )

#     result = pytester.runpytest_subprocess()

#     assert result.duration >= 5
#     result.assert_outcomes(passed=2)
