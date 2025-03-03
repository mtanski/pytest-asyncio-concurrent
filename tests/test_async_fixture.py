from textwrap import dedent
import pytest


def test_async_function_fixture(pytester: pytest.Pytester):
    """Make sure that async function fixture is got wrapped up"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function")
            async def async_fixture_function():
                await asyncio.sleep(0.1)
                return 1

            @pytest.mark.asyncio_concurrent
            async def test_fixture_async(async_fixture_function):
                assert async_fixture_function == 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


def test_async_gen_fixture(pytester: pytest.Pytester):
    """Make sure that async generator fixture is got wrapped up"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function")
            async def async_fixture_gen():
                await asyncio.sleep(0.1)
                yield 1

            @pytest.mark.asyncio_concurrent
            async def test_fixture_async(async_fixture_gen):
                assert async_fixture_gen == 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


def test_async_function_fixture_sync(pytester: pytest.Pytester):
    """
    Make sure that async function fixture is got wrapped up
    and consumerable by synced function
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function")
            async def async_fixture_function():
                await asyncio.sleep(0.1)
                return 1

            def test_fixture_async(async_fixture_function):
                assert async_fixture_function == 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


def test_async_gen_fixture_sync(pytester: pytest.Pytester):
    """
    Make sure that async generator fixture is got wrapped up
    and consumerable by synced function
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function")
            async def async_fixture_gen():
                await asyncio.sleep(0.1)
                yield 1

            def test_fixture_async(async_fixture_gen):
                assert async_fixture_gen == 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


def test_async_gen_fixture_error(pytester: pytest.Pytester):
    """
    Make sure that async generator fixture is got wrapped up
    and do not allow multiple yield
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.fixture(scope="function")
            async def async_fixture_gen():
                await asyncio.sleep(0.1)
                yield 1
                yield 1

            def test_fixture_async(async_fixture_gen):
                assert async_fixture_gen == 1
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, errors=1)


def test_async_fixture_context_aware(pytester: pytest.Pytester):
    """Make sure that async fixture can also be context aware."""
    
    pytester.makepyfile(
        testA=dedent(
            """\
            import asyncio
            import pytest
            import pytest_asyncio_concurrent

            @pytest_asyncio_concurrent.context_aware_fixture
            async async_context_aware_fixture():
                await asyncio.sleep(0.1)
                return []

            @pytest.mark.asyncio_concurrent(group="any")
            @pytest.mark.parametrize("p", [1, 2, 3])
            async def test_parametrize_concurrrent(async_context_aware_fixture, p):
                await asyncio.sleep(p / 10)
                async_context_aware_fixture.append(p)
                assert len(fixture_function) == 1
            """
        )
    )
    
def test_async_gen_fixture_context_aware(pytester: pytest.Pytester):
    """Make sure that async generator fixture can also be context aware."""
    
    pytester.makepyfile(
        testA=dedent(
            """\
            import asyncio
            import pytest
            import pytest_asyncio_concurrent

            @pytest_asyncio_concurrent.context_aware_fixture
            async async_context_aware_fixture():
                await asyncio.sleep(0.1)
                yield []

            @pytest.mark.asyncio_concurrent(group="any")
            @pytest.mark.parametrize("p", [1, 2, 3])
            async def test_parametrize_concurrrent(async_context_aware_fixture, p):
                await asyncio.sleep(p / 10)
                async_context_aware_fixture.append(p)
                assert len(fixture_function) == 1
            """
        )
    )