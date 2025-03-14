from textwrap import dedent
import pytest


def test_groups_different(pytester: pytest.Pytester):
    """Make sure group with different group exceuted seperately."""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent(group="B")
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    result = pytester.runpytest()

    assert result.duration >= 0.3
    result.assert_outcomes(passed=2)


def test_groups_anonymous(pytester: pytest.Pytester):
    """Make sure tests without group specified treated as different group"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_anonymous_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_anonymous_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    result = pytester.runpytest()

    assert result.duration >= 0.3
    result.assert_outcomes(passed=2)


def test_groups_same(pytester: pytest.Pytester):
    """Make sure group with same group exceuted together."""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_group_same_A():
                await asyncio.sleep(0.2)

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_group_same_B():
                await asyncio.sleep(0.1)
            """
        )
    )

    result = pytester.runpytest()

    assert result.duration < 0.3
    result.assert_outcomes(passed=2)


def test_parametrize_without_group(pytester: pytest.Pytester):
    """Make sure parametrized tests without group specified treated as different group"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            g_var = 0

            @pytest.mark.parametrize("p", [0, 1, 2])
            @pytest.mark.asyncio_concurrent
            async def test_parametrize_no_group(p):
                global g_var
                await asyncio.sleep(p / 10)

                assert g_var == p
                g_var += 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=3)
    assert result.duration >= 0.3


def test_parametrize_with_group(pytester: pytest.Pytester):
    """Make sure parametrized tests with group specified executed together"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            g_var = 0

            @pytest.mark.parametrize("p", [0, 1, 2])
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_parametrize_with_group(p):
                global g_var
                await asyncio.sleep(p / 10)

                assert g_var == p
                g_var += 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=3)
    assert result.duration < 0.3
