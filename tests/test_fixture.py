from textwrap import dedent
import pytest


def test_fixture_handling(pytester: pytest.Pytester):
    """Make sure that tests is taking fixture value correctly."""

    pytester.makeconftest(
        dedent(
            """\
            import pytest

            @pytest.fixture
            def fixture_a():
                yield 1


            @pytest.fixture
            def fixture_b():
                yield 2
            """
        )
    )

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_fixture_multi(fixture_a, fixture_b):
                assert fixture_a == 1
                assert fixture_b == 2
            """
        )
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


def test_fixture_scopes(pytester: pytest.Pytester):
    """Make sure that tests can take fixture of different scops."""

    pytester.makeconftest(
        dedent(
            """\
            import pytest

            @pytest.fixture(scope="function")
            def fixture_function():
                yield "fixture_function"

            @pytest.fixture(scope="class")
            def fixture_class():
                yield "fixture_class"

            @pytest.fixture(scope="module")
            def fixture_module():
                yield "fixture_module"

            @pytest.fixture(scope="session")
            def fixture_session():
                yield "fixture_session"
            """
        )
    )

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_fixture_multi(
                fixture_function,
                fixture_class,
                fixture_module,
                fixture_session
            ):
                assert fixture_function == "fixture_function"
                assert fixture_class == "fixture_class"
                assert fixture_module == "fixture_module"
                assert fixture_session == "fixture_session"
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_fixture_isolation(pytester: pytest.Pytester):
    """Make sure that parametrized tests take handle function fixture isolation."""

    pytester.makeconftest(
        dedent(
            """\
            import pytest

            @pytest.fixture(scope="function")
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
            async def test_fixture_multi(fixture_function, fixture_module, p):
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
            async def test_fixture_multi(fixture_function, fixture_module, p):
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


def test_fixture_autouse(pytester: pytest.Pytester):
    """Make sure that tests can take autouse fixture"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            g_var = 0

            @pytest.fixture(autouse=True)
            def autoused_fixture():
                global g_var
                g_var = 1
                yield
                g_var = 0

            @pytest.mark.asyncio_concurrent
            async def test_fixture_dummy():
                global g_var
                assert g_var == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_fixture_usefixture(pytester: pytest.Pytester):
    """Make sure that tests can take usefixuture fixture"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            g_var = 0

            @pytest.fixture(autouse=True)
            def fixture_got_used():
                global g_var
                g_var = 1
                yield
                g_var = 0

            @pytest.mark.usefixtures("fixture_got_used")
            class TestDummyClass:
                @pytest.mark.asyncio_concurrent
                async def test_fixture_dummy(self):
                    global g_var
                    assert g_var == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_fixture_method(pytester: pytest.Pytester):
    """Make sure that tests can take method fixture defined in class"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            class TestDummyClass:
                @pytest.fixture(autouse=True)
                def fixture_method(self):
                    yield 1

                @pytest.mark.asyncio_concurrent
                async def test_fixture_dummy(self, fixture_method):
                    assert fixture_method == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_fixture_static_method(pytester: pytest.Pytester):
    """Make sure that tests can take method static fixture defined in class"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            class TestDummyClass:
                @pytest.fixture
                @staticmethod
                def fixture_method():
                    yield 1

                @pytest.mark.asyncio_concurrent
                async def test_fixture_dummy(self, fixture_method):
                    assert fixture_method == 1
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
