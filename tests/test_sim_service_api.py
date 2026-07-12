"""Sim-service API: G1 gate (fail-closed), dispatch dry-run/emit, caps, manual
mode, dup-hash collision through the emitter."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from atlas_connectors.kernel.base import CanonicalRecord
from atlas_connectors.kernel.http_push import PoisonRecordError
from atlas_connectors.sim_service.api import get_publisher
from atlas_connectors.sim_service.main import create_app
from atlas_connectors.sim_service.settings import SimSettings, get_settings

TENANT = "00000000-0000-4000-8000-0000000000aa"
BATCH = "00000000-0000-4000-8000-00000000b001"
TRACE = "00000000-0000-4000-8000-0000000000bb"


class FakePublisher:
    def __init__(self) -> None:
        self.records: list[CanonicalRecord] = []

    def publish(self, record: CanonicalRecord) -> None:
        self.records.append(record)


class PoisonEveryOtherPublisher(FakePublisher):
    def publish(self, record: CanonicalRecord) -> None:
        super().publish(record)
        if len(self.records) % 2 == 0:
            raise PoisonRecordError("simulated 400")


def make_client(settings: SimSettings, publisher: FakePublisher | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    if publisher is not None:
        app.dependency_overrides[get_publisher] = lambda: publisher
    return TestClient(app)


def dispatch_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "tenant_id": TENANT,
        "batch_id": BATCH,
        "trace_id": TRACE,
        "mode": "auto",
        "preset_id": "connect.ingestion.v1",
        "params": {"accounts": 2, "flows_per_account": 3},
        "seed": 42,
        "dry_run": False,
        "generated_by": "op-tests",
        "target_label": "Société Test",
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- G1


@pytest.mark.parametrize(
    "settings",
    [
        SimSettings(enabled=False, environment="dev"),
        SimSettings(enabled=True, environment="production"),
        SimSettings(enabled=True, environment="PROD"),
    ],
)
def test_gate_fails_closed_with_404(settings: SimSettings) -> None:
    client = make_client(settings)
    assert client.get("/sim/v1/presets").status_code == 404
    assert client.get("/sim/v1/health").status_code == 404
    assert client.post("/sim/v1/dispatch", json=dispatch_body()).status_code == 404


def test_gate_opens_when_enabled_outside_prod() -> None:
    client = make_client(SimSettings(enabled=True, environment="dev"))
    assert client.get("/sim/v1/health").status_code == 200


# ----------------------------------------------------------------------- routes


def test_presets_lists_the_registry_with_param_schema() -> None:
    client = make_client(SimSettings(enabled=True))
    response = client.get("/sim/v1/presets")
    assert response.status_code == 200
    presets = {p["presetId"]: p for p in response.json()}
    assert len(presets) == 7
    ingestion = presets["connect.ingestion.v1"]
    assert ingestion["module"] == "AtlasConnect"
    assert ingestion["phase"] == 1
    assert ingestion["defaults"]["accounts"] == 3
    accounts_spec = next(s for s in ingestion["paramSchema"] if s["name"] == "accounts")
    assert accounts_spec == {"name": "accounts", "type": "int", "default": 3, "min": 1, "max": 20}


def test_trace_id_is_echoed_and_minted() -> None:
    client = make_client(SimSettings(enabled=True))
    echoed = client.get("/sim/v1/health", headers={"X-Trace-Id": TRACE})
    assert echoed.headers["X-Trace-Id"] == TRACE
    minted = client.get("/sim/v1/health", headers={"X-Trace-Id": "not-a-uuid"})
    assert minted.headers["X-Trace-Id"] != "not-a-uuid"


def test_dispatch_dry_run_previews_without_publishing() -> None:
    publisher = FakePublisher()
    client = make_client(SimSettings(enabled=True), publisher)
    response = client.post("/sim/v1/dispatch", json=dispatch_body(dry_run=True))
    assert response.status_code == 200
    body = response.json()
    assert body["expected_records"] == 2 + 2 * 3
    assert len(body["preview"]) == 8  # < the 20-record preview window
    assert body["ground_truth"] == {"expected_accounts": 2, "expected_flows": 6}
    assert publisher.records == []


def test_dispatch_dry_run_needs_no_publisher() -> None:
    client = make_client(SimSettings(enabled=True))  # nothing configured
    assert client.post("/sim/v1/dispatch", json=dispatch_body(dry_run=True)).status_code == 200


def test_dispatch_emit_without_publisher_is_503() -> None:
    client = make_client(SimSettings(enabled=True))
    assert client.post("/sim/v1/dispatch", json=dispatch_body()).status_code == 503


def test_dispatch_emits_through_the_kernel_with_sim_provenance() -> None:
    publisher = FakePublisher()
    client = make_client(SimSettings(enabled=True), publisher)
    response = client.post("/sim/v1/dispatch", json=dispatch_body())
    assert response.status_code == 200
    body = response.json()
    assert body["emitted"] == body["expected_records"] == 8
    assert body["rejected"] == 0
    assert len(body["source_hashes"]) == 8
    assert {h["record_type"] for h in body["source_hashes"]} == {"bank_account", "cash_flow"}
    record = publisher.records[0]
    meta = record.source_metadata
    assert meta.origin == "SIMULATION"
    assert str(meta.batch_id) == BATCH
    assert meta.seed == 42
    assert meta.preset_id == "connect.ingestion.v1"
    assert meta.generated_by == "op-tests"
    assert meta.source_system == "sim.psd2"
    assert meta.source_message_id == f"{BATCH}:0"
    assert str(record.tenant_id) == TENANT
    assert str(record.trace_id) == TRACE


def test_firewall_dup_records_collide_on_source_hash_and_message_id() -> None:
    publisher = FakePublisher()
    client = make_client(SimSettings(enabled=True), publisher)
    response = client.post(
        "/sim/v1/dispatch",
        json=dispatch_body(
            preset_id="connect.firewall.v1",
            params={"base_flows": 10, "bad_ratio": 0.3, "defect_types": ["dup_source_hash"]},
        ),
    )
    assert response.status_code == 200
    by_hash: dict[str, list[str]] = {}
    for record in publisher.records:
        by_hash.setdefault(record.source_metadata.source_hash, []).append(
            record.source_metadata.source_message_id
        )
    collided = {h: ids for h, ids in by_hash.items() if len(ids) > 1}
    assert sum(len(ids) - 1 for ids in collided.values()) == 3  # round(10 × 0.3)
    for ids in collided.values():
        assert len(set(ids)) == 1  # dup re-uses the FIRST occurrence's message id


def test_poison_records_count_as_rejected() -> None:
    publisher = PoisonEveryOtherPublisher()
    client = make_client(SimSettings(enabled=True), publisher)
    response = client.post("/sim/v1/dispatch", json=dispatch_body())
    assert response.status_code == 200
    body = response.json()
    assert body["expected_records"] == 8
    assert body["emitted"] == 4
    assert body["rejected"] == 4


def test_cap_is_enforced_with_422() -> None:
    client = make_client(SimSettings(enabled=True, max_records_per_run=10), FakePublisher())
    response = client.post(
        "/sim/v1/dispatch",
        json=dispatch_body(params={"accounts": 3, "flows_per_account": 10}),
    )
    assert response.status_code == 422
    assert "cap" in response.json()["detail"]


def test_unknown_preset_is_422() -> None:
    client = make_client(SimSettings(enabled=True), FakePublisher())
    response = client.post("/sim/v1/dispatch", json=dispatch_body(preset_id="pay.execute.v9"))
    assert response.status_code == 422


def test_ground_truth_indices_are_enriched_with_source_hashes() -> None:
    publisher = FakePublisher()
    client = make_client(SimSettings(enabled=True), publisher)
    response = client.post(
        "/sim/v1/dispatch",
        json=dispatch_body(
            preset_id="finhub.anomaly.v1", params={"base_flows": 20, "anomaly_count": 4}
        ),
    )
    assert response.status_code == 200
    body = response.json()
    injected = body["ground_truth"]["injected_anomalies"]
    assert len(injected) == 4
    emitted_hashes = {h["source_hash"] for h in body["source_hashes"]}
    for entry in injected:
        if "record_indices" in entry:
            assert set(entry["source_hashes"]) <= emitted_hashes
        else:
            assert entry["source_hash"] in emitted_hashes


# ----------------------------------------------------------------------- manual


def test_manual_mode_validates_and_emits() -> None:
    publisher = FakePublisher()
    client = make_client(SimSettings(enabled=True), publisher)
    manual = [
        {
            "record_type": "bank_account",
            "payload": {
                "iban": "FR76999990000000000000001",
                "label": "Compte manuel",
                "currency": "EUR",
                "entity": "Société Test Holding",
                "balance": "1000.00",
            },
        },
        {
            "record_type": "cash_flow",
            "payload": {
                "account_iban": "FR76999990000000000000001",
                "amount": "-42.00",
                "currency": "EUR",
                "value_date": "2026-07-01",
                "direction": "debit",
                "counterparty": "Fournitures Nébula SARL",
                "label": "Règlement manuel",
            },
        },
    ]
    response = client.post(
        "/sim/v1/dispatch", json=dispatch_body(mode="manual", preset_id=None, payload=manual)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["emitted"] == 2
    assert publisher.records[0].source_metadata.preset_id is None
    assert publisher.records[0].source_metadata.origin == "SIMULATION"


def test_manual_mode_rejects_invalid_records_with_422() -> None:
    client = make_client(SimSettings(enabled=True), FakePublisher())
    bad = [
        {"record_type": "cash_flow", "payload": {"amount": "NOT_A_NUMBER"}},
        {"record_type": "payment_order", "payload": {"amount": "1.00"}},  # phase-bleed
    ]
    response = client.post(
        "/sim/v1/dispatch", json=dispatch_body(mode="manual", preset_id=None, payload=bad)
    )
    assert response.status_code == 422
    invalid = response.json()["detail"]["invalid_records"]
    assert {e["index"] for e in invalid} == {0, 1}
    assert "not allowed" in invalid[1]["error"]
