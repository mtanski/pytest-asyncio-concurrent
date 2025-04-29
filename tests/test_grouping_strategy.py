from textwrap import dedent
import pytest


def test_parent_group_strategy__cli_seperate_file(pytester: pytest.Pytester):
    """Tests go under closest parent under group strategy"""

    pytester.makepyfile(testA=
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    pytester.makepyfile(testB=
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    result = pytester.runpytest("testA.py", "testB.py", "--default-group-strategy=parent")

    assert result.duration < 0.6
    result.assert_outcomes(passed=4)


def test_parent_group_strategy__cli_file_and_class(pytester: pytest.Pytester):
    """Tests go under closest parent under group strategy"""

    pytester.makepyfile(testA=
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    pytester.makepyfile(testB=
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            
            class TestDummyClass:
                @pytest.mark.asyncio_concurrent
                async def test_group_A(self):
                    await asyncio.sleep(0.1)

                @pytest.mark.asyncio_concurrent
                async def test_group_B(self):
                    await asyncio.sleep(0.2)
            """
        )
    )

    result = pytester.runpytest("testA.py", "testB.py", "--default-group-strategy=parent")

    assert result.duration < 0.9
    result.assert_outcomes(passed=6)


def test_parent_group_strategy__ini_seperate_file(pytester: pytest.Pytester):
    """Tests go under closest parent under group strategy"""

    pytester.makepyfile(testA=
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    pytester.makepyfile(testB=
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.3)
            """
        )
    )
    
    pytester.makeini(
        dedent(   
        """\
        [pytest]
        default_group_strategy = parent
        addopts = -p no:asyncio
        """
        )
    )

    result = pytester.runpytest("testA.py", "testB.py")

    assert result.duration < 0.6
    result.assert_outcomes(passed=4)
    

def test_parent_group_strategy__cli_invalid(pytester: pytest.Pytester):
    """Tests go under closest parent under group strategy"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    result = pytester.runpytest("--default-group-strategy=class")

    assert len(result.stderr.lines) > 0
    

def test_parent_group_strategy__ini_invalid(pytester: pytest.Pytester):
    """Tests go under closest parent under group strategy"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            async def test_group_A():
                await asyncio.sleep(0.1)

            @pytest.mark.asyncio_concurrent
            async def test_group_B():
                await asyncio.sleep(0.2)
            """
        )
    )

    pytester.makeini(
        dedent(   
        """\
        [pytest]
        default_group_strategy = class
        addopts = -p no:sugar no:asyncio
        """
        )
    )
    
    result = pytester.runpytest()
    assert len(result.stderr.lines) > 0