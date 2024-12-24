from textwrap import dedent
import pytest


def test_grouping_error(pytester: pytest.Pytester):
    """Make sure tests got skipped if tests from different parent got marked as same group"""

    pytester.makepyfile(
        testA=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_A():
                assert 1 == 1
            """
        )
    )

    pytester.makepyfile(
        testB=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_A():
                assert 1 == 1

            @pytest.mark.asyncio_concurrent(group="B")
            async def test_B():
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest("testA.py", "testB.py")

    result.assert_outcomes(warnings=1, skipped=2, passed=1)


def test_marked_synced_error(pytester: pytest.Pytester):
    """Make sure tests got skipped if synced tests got marked"""
    
    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            def test_sync():
                assert 1 == 1

            @pytest.mark.asyncio_concurrent
            async def test_async():
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(warnings=1, skipped=1, passed=1)
