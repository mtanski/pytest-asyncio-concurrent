from textwrap import dedent
import pytest


def test_log(pytester: pytest.Pytester):
    """log should not break tests"""

    pytester.makepyfile(
        dedent(
            """\
            import asyncio
            import pytest
            import logging

            logger = logging.getLogger(__name__)

            @pytest.mark.parametrize("p", [0, 1, 2, 3, 4])
            @pytest.mark.asyncio_concurrent(group="log")
            async def test_log(p):
                await asyncio.sleep(p / 10)
                logger.info("info log would be captured")
                logger.debug("debug log would not be captured")
            """
        )
    )

    result = pytester.runpytest("--log-cli-level=INFO")
    result.assert_outcomes(passed=5, errors=0)
    assert len([line for line in result.outlines if "info log would be captured" in line]) == 5
    assert len([line for line in result.outlines if "debug log would not be captured" in line]) == 0
