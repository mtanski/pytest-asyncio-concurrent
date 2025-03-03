from textwrap import dedent

import pytest

def test_context_aware_fixture_function_isolation(pytester: pytest.Pytester):
    """Make sure that context_aware_fixture handle function fixture isolation."""

    pytester.makeconftest(
        dedent(
            """\
            import pytest
            import pytest_asyncio_concurrent

            @pytest_asyncio_concurrent.context_aware_fixture
            def fixture_function():
                yield []

            @pytest.fixture(scope="module")
            def fixture_module():
                yield []
            """
        )
    )

    pytester.makepyfile(
        testA=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="any")
            @pytest.mark.parametrize("p", [1, 2, 3])
            async def test_parametrize_concurrrent(fixture_function, fixture_module, p):
                await asyncio.sleep(p / 10)

                fixture_module.append(p)
                fixture_function.append(p)

                assert len(fixture_function) == 1
                assert len(fixture_module) == p
            """
        )
    )

    pytester.makepyfile(
        testB=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            @pytest.mark.parametrize("p", [1, 2, 3])
            async def test_parametrize_sequential(fixture_function, fixture_module, p):
                await asyncio.sleep(p / 10)

                fixture_module.append(p)
                fixture_function.append(p)

                assert len(fixture_function) == 1
                assert len(fixture_module) == p
            """
        )
    )

    result = pytester.runpytest("testA.py", "testB.py")
    result.assert_outcomes(passed=6)


def test_context_aware_fixture_class_isolation(pytester: pytest.Pytester):
    """Make sure that context_aware_fixture handle class fixture isolation."""

    pytester.makeconftest(dedent(
            """\
            import pytest
            import pytest_asyncio_concurrent

            @pytest_asyncio_concurrent.context_aware_fixture(scope="class")
            def fixture_class():
                yield []
            """
        )
    )

    pytester.makepyfile(dedent(
            """\
            import asyncio
            import pytest

            class TestClassA:
                @pytest.mark.asyncio_concurrent(group="any")
                @pytest.mark.parametrize("p", [1, 2, 3])
                async def test_dummy_param(self, fixture_class, p):
                    await asyncio.sleep(p / 10)
                    fixture_class.append(p)
                    assert len(fixture_class) == p

            class TestClassB:
                @pytest.mark.asyncio_concurrent(group="any")
                @pytest.mark.parametrize("p", [1, 2, 3])
                async def test_dummy_param(self, fixture_class, p):
                    await asyncio.sleep(p / 10)
                    fixture_class.append(p)
                    assert len(fixture_class) == p
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=6)


def test_context_aware_fixture_module_isolation(pytester: pytest.Pytester):
    """Make sure that context_aware_fixture handle module fixture isolation."""

    pytester.makeconftest(dedent(
            """\
            import pytest
            import pytest_asyncio_concurrent

            @pytest_asyncio_concurrent.context_aware_fixture(scope="module")
            def fixture_module():
                yield []
            """
        )
    )

    pytester.makepyfile(testA=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="any")
            @pytest.mark.parametrize("p", [1, 2, 3])
            async def test_dummy_param(fixture_module, p):
                await asyncio.sleep(p / 10)
                fixture_module.append(p)
                assert len(fixture_module) == p
            """
        )
    )
    
    pytester.makepyfile(testB=dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent(group="any")
            @pytest.mark.parametrize("p", [1, 2, 3])
            async def test_dummy_param(fixture_module, p):
                await asyncio.sleep(p / 10)
                fixture_module.append(p)
                assert len(fixture_module) == p
            """
        )
    )

    result = pytester.runpytest("testA.py", "testB.py")
    result.assert_outcomes(passed=6)


def test_function_fixture_teardown_error_repeating(pytester: pytest.Pytester):
    """
    Make sure that error in function scoped fixture teardown stage will repeat on each test.
    """

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest
            import pytest_asyncio_concurrent

            @pytest_asyncio_concurrent.context_aware_fixture(scope="function")
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