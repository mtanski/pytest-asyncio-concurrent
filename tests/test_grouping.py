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
                await asyncio.sleep(3)
                assert 1 == 1

            @pytest.mark.asyncio_concurrent(group="B")
            async def test_group_B():
                await asyncio.sleep(2)
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest()

    assert result.duration >= 5
    result.assert_outcomes(passed=2)


def test_groups_anonymous(pytester: pytest.Pytester):
    """Make sure tests without group specified treated as different group"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(3)
                assert 1 == 1

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(2)
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest()

    assert result.duration >= 5
    result.assert_outcomes(passed=2)


def test_groups_same(pytester: pytest.Pytester):
    """Make sure group with same group exceuted together."""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_group_anonymous_A():
                await asyncio.sleep(3)
                assert 1 == 1

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_group_anonymous_B():
                await asyncio.sleep(2)
                assert 1 == 1
            """
        )
    )

    result = pytester.runpytest()

    assert result.duration < 5
    result.assert_outcomes(passed=1)  # TODO: passed should be 2


def test_parametrize_without_group(pytester: pytest.Pytester):
    """Make sure parametrized tests without group specified treated as different group"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            g = 0

            @pytest.mark.parametrize("p", [0, 1, 2])
            @pytest.mark.asyncio_concurrent
            async def test_parametrize_no_group(p):
                global g
                await asyncio.sleep(p)

                assert g == p
                g += 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=3)
    assert result.duration >= 3


def test_parametrize_with_group(pytester: pytest.Pytester):
    """Make sure parametrized tests with group specified executed together"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            g = 0

            @pytest.mark.parametrize("p", [0, 1, 2])
            @pytest.mark.asyncio_concurrent(group="any")
            async def test_parametrize_with_group(p):
                global g
                await asyncio.sleep(p)

                assert g == p
                g += 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)  # TODO: passed should be 3
    assert result.duration < 3
