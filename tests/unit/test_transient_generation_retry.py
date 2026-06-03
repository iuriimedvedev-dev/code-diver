from __future__ import annotations

from types import SimpleNamespace

import pytest

from code_diver.generation import TransientGenerationRetry


pytestmark = pytest.mark.unit


def test_transient_generation_retry_retries_rate_limits() -> None:
    sleeps: list[float] = []
    calls = 0
    retry = TransientGenerationRetry(
        attempts=3,
        base_delay_seconds=2,
        max_delay_seconds=10,
        sleep=sleeps.append,
        jitter=lambda: 0,
    )

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("HTTP 429: RESOURCE_EXHAUSTED")
        return "ok"

    assert retry.run(flaky) == "ok"
    assert calls == 3
    assert sleeps == [2, 4]


def test_transient_generation_retry_respects_retry_after_header() -> None:
    sleeps: list[float] = []
    retry = TransientGenerationRetry(
        attempts=2,
        base_delay_seconds=2,
        max_delay_seconds=10,
        sleep=sleeps.append,
        jitter=lambda: 0,
    )
    error = RuntimeError("HTTP 503: unavailable")
    error.response = SimpleNamespace(headers={"Retry-After": "7"})  # type: ignore[attr-defined]

    def flaky() -> str:
        if not sleeps:
            raise error
        return "ok"

    assert retry.run(flaky) == "ok"
    assert sleeps == [7]


def test_transient_generation_retry_does_not_retry_bad_requests() -> None:
    calls = 0
    retry = TransientGenerationRetry(attempts=3, sleep=lambda _: None, jitter=lambda: 0)

    def broken() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("HTTP 400: invalid response_format")

    with pytest.raises(RuntimeError, match="HTTP 400"):
        retry.run(broken)
    assert calls == 1
