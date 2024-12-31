from textwrap import dedent
import pytest


def test_function_fixture_setup_error_isolation(pytester: pytest.Pytester):
    """
    Make sure that error in function scoped fixture setup stage
    is isolated from other function.
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture
            def fixture_function():
                raise AssertionError
                yield

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_A():
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_B(fixture_function):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_C():
                pass
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=2, errors=1)


def test_package_fixture_setup_error_repeating(pytester: pytest.Pytester):
    """
    Make sure that error in non-function scoped fixture setup stage
    will repeat on each test.
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="package")
            def fixture_package():
                raise AssertionError
                yield

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_A(fixture_package):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_B(fixture_package):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_C():
                pass
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, errors=2)


def test_usefixture_fixture_on_class_setup_error_repeating(pytester: pytest.Pytester):
    """
    Make sure that error in non-function scoped fixture setup stage
    will repeat on each test.
    The fixture is marked as usefixture on class level.
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="package")
            def fixture_usefixture():
                raise AssertionError
                yield

            @pytest.mark.usefixtures("fixture_usefixture")
            class TestClass:
                @pytest.mark.asyncio_concurrent(group="any")
                async def test_A():
                    pass

                @pytest.mark.asyncio_concurrent(group="any")
                async def test_B():
                    pass

                @pytest.mark.asyncio_concurrent(group="any")
                async def test_C():
                    pass
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(errors=3)


def test_function_fixture_teardown_error_repeating(pytester: pytest.Pytester):
    """
    Make sure that error in function scoped fixture teardown stage will repeat on each test.
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function")
            def fixture_function():
                yield
                raise AssertionError

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_A(fixture_function):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_B(fixture_function):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_C():
                pass
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=3, errors=2)


def test_package_fixture_teardown_error_once(pytester: pytest.Pytester):
    """
    Make sure that error in non-function scoped fixture teardown stage
    will only errored once on the last test teardown.
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="package")
            def fixture_package():
                yield
                raise AssertionError

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_A(fixture_package):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_B(fixture_package):
                pass

            @pytest.mark.asyncio_concurrent(group="any")
            async def test_C():
                pass
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=3, errors=1)
