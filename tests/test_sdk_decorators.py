import pytest

from src.sdk.decorators import task


class TestTaskDecorator:
    def test_task_timeout_must_be_positive(self):
        async def handler():
            return "ok"

        with pytest.raises(ValueError, match="positive finite number"):
            task(timeout=0)(handler)

        with pytest.raises(ValueError, match="positive finite number"):
            task(timeout=-1)(handler)

    def test_task_timeout_must_be_finite_number(self):
        async def handler():
            return "ok"

        invalid_timeouts = ["5", None, True, float("inf"), float("nan")]
        for timeout in invalid_timeouts:
            with pytest.raises(ValueError, match="positive finite number"):
                task(timeout=timeout)(handler)

    def test_valid_timeout_is_recorded_in_task_config(self):
        async def handler():
            return "ok"

        wrapped = task(timeout=0.5)(handler)

        assert wrapped.__task_config__["timeout"] == 0.5
