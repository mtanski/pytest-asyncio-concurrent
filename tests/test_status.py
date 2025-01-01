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


def test_fail_multi(pytester: pytest.Pytester):
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
            async def test_failedA():
                raise AssertionError

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_failedB():
                raise AssertionError
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(failed=2, passed=1)


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


def test_selection(pytester: pytest.Pytester):
    """Make sure tests xfail and xpass is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_selectedA():
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_selectedB():
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_unselected():
                pass
            """
        )
    )

    result = pytester.runpytest("-k test_selected")
    result.assert_outcomes(deselected=1, passed=2)


def test_setup_error(pytester: pytest.Pytester):
    """Make sure tests xfail and xpass is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function", name="setup_error_fixture")
            def function_scoped_fiture_error_in_setup():
                raise AssertionError
                yield

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_xpass(setup_error_fixture):
                pass

            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(errors=1)


def test_teardown_error(pytester: pytest.Pytester):
    """Make sure tests xfail and xpass is reported correctly"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function", name="teardown_error_fixture")
            def function_scoped_fiture_error_in_teardown():
                yield
                raise AssertionError

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_xpass(teardown_error_fixture):
                pass

            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(errors=1, passed=1)


def test_cmd_select(pytester: pytest.Pytester):
    """Make sure group with same group exceuted together."""

    pytester.makepyfile(
        test_dummy=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_cmd_select_A():
                await asyncio.sleep(0.2)

            @pytest.mark.asyncio_concurrent(group="A")
            async def test_cmd_select_B():
                await asyncio.sleep(0.1)
            """
        )
    )

    result = pytester.runpytest("test_dummy.py::test_cmd_select_A")

    result.assert_outcomes(passed=1)
