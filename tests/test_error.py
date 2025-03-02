from textwrap import dedent
import pytest


def test_marked_synced_error(pytester: pytest.Pytester):
    """Make sure tests got skipped if synced tests got marked"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest

            @pytest.mark.asyncio_concurrent
            def test_sync():
                pass

            @pytest.mark.asyncio_concurrent
            async def test_async():
                pass
            """
        )
    )

    result = pytester.runpytest()
    result.assert_outcomes(warnings=1, skipped=1, passed=1)
