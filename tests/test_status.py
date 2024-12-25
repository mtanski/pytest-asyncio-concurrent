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
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_failed():
                raise AssertionError
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(failed=1, passed=1)


def test_skip(pytester: pytest.Pytester):
    """Make sure tests skip is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.skip(reason="")
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_skiping():
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_passing():
                pass
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(skipped=1, passed=1)


def test_skip_if(pytester: pytest.Pytester):
    """Make sure tests skip if is handled correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.skipif(1 == 1, reason="")
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_skiping():
                pass

            @pytest.mark.skipif(1 == 2, reason="")
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_passing():
                pass
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(skipped=1, passed=1)


def test_xfail_xpass(pytester: pytest.Pytester):
    """Make sure tests xfail and xpass is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.xfail
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_xfail():
                raise AssertionError
                
            @pytest.mark.xfail
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_xpass():
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_failing():
                raise AssertionError
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(failed=1, xfailed=1, xpassed=1)
