from textwrap import dedent
import pytest


def test_fail(pytester: pytest.Pytester):
    """Make sure tests failed is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_passing():
                assert 1 == 1

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_failed():
                assert 1 == 2
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(failed=1, passed=1)


def test_skip(pytester: pytest.Pytester):
    """Make sure tests failed is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.skip(reason="")
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_skiping():
                assert 1 == 1

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_passing():
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(skipped=1, passed=1)


def test_skip_if(pytester: pytest.Pytester):
    """Make sure tests failed is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.skipif(1 == 1, reason="")
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_skiping():
                assert 1 == 1

            @pytest.mark.skipif(1 == 2, reason="")
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_passing():
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(skipped=1, passed=1)


def test_xfail_xpass(pytester: pytest.Pytester):
    """Make sure tests failed is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.xfail
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_xfail():
                assert 1 == 2
                
            @pytest.mark.xfail
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_xpass():
                assert 1 == 1

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_failing():
                assert 1 == 2
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(failed=1, xfailed=1, xpassed=1)
