"""HTTP-push publisher binding — local/demo mode without a broker.

POSTs each CanonicalRecord to Core's real ingestion entrypoint
(`POST {core_url}/events/canonical`) wrapped in the exact Pub/Sub *push*
envelope shape Core already validates, so the HTTP path and the Pub/Sub path
are indistinguishable to ingestion (Atlas_Simulation_Conception §3).

Requires the `service` extra (httpx).
"""

from __future__ import annotations

import base64
from typing import Any

from atlas_connectors.kernel.base import CanonicalRecord


class HttpPushError(Exception):
    """Transport/server failure (non-2xx other than 400) — retryable upstream."""


class PoisonRecordError(HttpPushError):
    """Core answered 400: the record itself is invalid (poison).

    Callers count it as *rejected* in their emit report and move on — a poison
    record must never block the rest of the stream (README resilience rule).
    """


def push_envelope(record: CanonicalRecord) -> dict[str, Any]:
    """The Pub/Sub push envelope Core's `/events/canonical` expects."""
    data = base64.b64encode(record.model_dump_json().encode("utf-8")).decode("ascii")
    return {
        "message": {
            "data": data,
            "attributes": {
                "trace_id": str(record.trace_id),
                "tenant_id": str(record.tenant_id),
            },
        }
    }


class HttpPushPublisher:
    """PublisherPort binding that pushes straight to Core over HTTP."""

    def __init__(self, core_url: str, *, client: Any = None, timeout_s: float = 10.0) -> None:
        import httpx  # deferred: optional dependency (service extra)

        self._url = core_url.rstrip("/") + "/events/canonical"
        self._client: httpx.Client = client or httpx.Client(timeout=timeout_s)

    def publish(self, record: CanonicalRecord) -> None:
        response = self._client.post(
            self._url,
            json=push_envelope(record),
            headers={"X-Trace-Id": str(record.trace_id)},
        )
        if response.status_code == 400:
            raise PoisonRecordError(f"core rejected record as invalid: {response.text[:200]}")
        if not (200 <= response.status_code < 300):
            raise HttpPushError(f"core ingestion answered {response.status_code}")
