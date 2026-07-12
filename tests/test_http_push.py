"""HttpPushPublisher — the envelope must be byte-compatible with the Pub/Sub
push shape Core's /events/canonical already validates."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from atlas_connectors.kernel.base import CanonicalRecord, SourceMetadata
from atlas_connectors.kernel.http_push import (
    HttpPushError,
    HttpPushPublisher,
    PoisonRecordError,
)

TENANT = UUID("00000000-0000-4000-8000-0000000000aa")
TRACE = UUID("00000000-0000-4000-8000-0000000000bb")


def make_record() -> CanonicalRecord:
    return CanonicalRecord(
        event_id=UUID("00000000-0000-4000-8000-0000000000ee"),
        tenant_id=TENANT,
        record_type="cash_flow",
        payload={"amount": "-42.00", "currency": "EUR"},
        source_metadata=SourceMetadata(
            source_system="sim.psd2",
            source_message_id="b:0",
            source_hash="0" * 64,
            ingested_at=datetime(2026, 7, 1, tzinfo=UTC),
            origin="SIMULATION",
        ),
        trace_id=TRACE,
        occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def client_returning(status_code: int, captured: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status_code)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_push_envelope_shape_and_endpoint() -> None:
    captured: list[httpx.Request] = []
    publisher = HttpPushPublisher(
        "http://core.local:8080/", client=client_returning(200, captured)
    )
    publisher.publish(make_record())

    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "http://core.local:8080/events/canonical"
    assert request.headers["X-Trace-Id"] == str(TRACE)
    envelope = json.loads(request.content)
    assert set(envelope) == {"message"}
    message = envelope["message"]
    assert message["attributes"] == {"trace_id": str(TRACE), "tenant_id": str(TENANT)}
    decoded = json.loads(base64.b64decode(message["data"]))
    assert decoded["record_type"] == "cash_flow"
    assert decoded["payload"] == {"amount": "-42.00", "currency": "EUR"}
    assert decoded["source_metadata"]["origin"] == "SIMULATION"


def test_400_raises_poison_record_error() -> None:
    publisher = HttpPushPublisher("http://core.local", client=client_returning(400, []))
    with pytest.raises(PoisonRecordError):
        publisher.publish(make_record())


def test_other_non_2xx_raises_http_push_error() -> None:
    publisher = HttpPushPublisher("http://core.local", client=client_returning(503, []))
    with pytest.raises(HttpPushError) as exc_info:
        publisher.publish(make_record())
    assert not isinstance(exc_info.value, PoisonRecordError)


def test_2xx_is_accepted() -> None:
    publisher = HttpPushPublisher("http://core.local", client=client_returning(204, []))
    publisher.publish(make_record())  # must not raise
