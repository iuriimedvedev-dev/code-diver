from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ..settings import Defaults


T = TypeVar("T")


@dataclass(slots=True)
class TransientGenerationRetry:
    attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS
    base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS
    max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS
    sleep: Callable[[float], None] = time.sleep
    jitter: Callable[[], float] = random.random

    def run(self, operation: Callable[[], T]) -> T:
        max_attempts = max(int(self.attempts), 1)
        for attempt in range(max_attempts):
            try:
                return operation()
            except Exception as exc:
                if attempt + 1 >= max_attempts or not self.is_transient(exc):
                    raise
                self.sleep(self._delay_seconds(attempt, exc))
        return operation()

    def is_transient(self, exc: Exception) -> bool:
        status = self._status_code(exc)
        if status in {408, 409, 425, 429, 500, 502, 503, 504}:
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "429",
                "503",
                "rate limit",
                "resource_exhausted",
                "too many requests",
                "quota",
                "unavailable",
                "deadline",
                "timed out",
                "timeout",
                "temporarily",
            )
        )

    def _delay_seconds(self, attempt: int, exc: Exception) -> float:
        retry_after = self._retry_after_seconds(exc)
        if retry_after is not None:
            return min(retry_after, max(float(self.max_delay_seconds), 0.0))
        base = max(float(self.base_delay_seconds), 0.0)
        cap = max(float(self.max_delay_seconds), base)
        exponential = min(base * (2**attempt), cap)
        return min(exponential + self.jitter(), cap)

    def _status_code(self, exc: Exception) -> int | None:
        for attribute in ("status_code", "code"):
            value = getattr(exc, attribute, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _retry_after_seconds(self, exc: Exception) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            headers = getattr(exc, "headers", None)
        if not headers:
            return None
        value = None
        if hasattr(headers, "get"):
            value = headers.get("retry-after") or headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return None
