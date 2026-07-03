"""Retry with exponential backoff + jitter — for idempotent pulls only.

Guardrail (README): timeout on every connector/bank call; retries only where a
re-run is safe (source_hash makes republishing safe); poison data routes to the
DLQ rather than blocking the stream.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay_s: float = 1.0,
    max_delay_s: float = 30.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Call `fn`, retrying on `retryable` with exponential backoff + full jitter."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except retryable as exc:  # noqa: PERF203 — clarity over micro-perf here
            last = exc
            if attempt == attempts - 1:
                break
            delay = min(max_delay_s, base_delay_s * (2**attempt))
            time.sleep(random.uniform(0, delay))
    assert last is not None
    raise last
