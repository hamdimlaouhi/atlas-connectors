"""Per-generator shape + ground-truth invariants (Conception §5 table)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from atlas_connectors.sim_service.generators import REGISTRY
from atlas_connectors.sim_service.models import SIM_MODELS, GeneratedBatch

TODAY = date(2026, 7, 1)


def generate(
    preset_id: str, params: dict[str, Any] | None = None, seed: int = 42
) -> GeneratedBatch:
    return REGISTRY[preset_id].generate(params or {}, seed, "Société Test", today=TODAY)


def test_registry_hosts_the_seven_phase1_presets() -> None:
    assert sorted(REGISTRY) == [
        "connect.firewall.v1",
        "connect.ingestion.v1",
        "finhub.anomaly.v1",
        "finhub.circuit_breaker.v1",
        "finhub.consolidation.v1",
        "finhub.forecasting.v1",
        "finhub.reconciliation.v1",
    ]
    assert all(gen.phase == 1 for gen in REGISTRY.values())


@pytest.mark.parametrize("preset_id", sorted(set(REGISTRY) - {"connect.firewall.v1"}))
def test_non_firewall_records_validate_against_sim_models(preset_id: str) -> None:
    """Every non-firewall record must satisfy the sim-json contract — the same
    models manual mode validates against (generator/manual shape parity)."""
    batch = generate(preset_id)
    assert batch.records
    for record_type, payload in batch.records:
        SIM_MODELS[record_type].model_validate(payload)


def test_ingestion_counts_match_ground_truth() -> None:
    batch = generate("connect.ingestion.v1", {"accounts": 4, "flows_per_account": 10})
    accounts = [p for t, p in batch.records if t == "bank_account"]
    flows = [p for t, p in batch.records if t == "cash_flow"]
    assert batch.ground_truth == {"expected_accounts": 4, "expected_flows": 40}
    assert len(accounts) == 4
    assert len(flows) == 40
    assert all(a["iban"].startswith("FR7699999") for a in accounts)


def test_ingestion_dates_stay_inside_the_window() -> None:
    batch = generate("connect.ingestion.v1", {"date_range": "last-30d"})
    for record_type, payload in batch.records:
        if record_type == "cash_flow":
            value_date = date.fromisoformat(payload["value_date"])
            assert TODAY >= value_date >= date(2026, 6, 2)


def test_firewall_bad_count_is_round_base_times_ratio() -> None:
    batch = generate("connect.firewall.v1", {"base_flows": 50, "bad_ratio": 0.3})
    gt = batch.ground_truth
    assert gt["expected_bad"] == round(50 * 0.3) == 15
    assert gt["expected_quarantined"] + gt["expected_duplicates"] == 15
    assert len(gt["per_record_reason"]) == 15
    # 1 account + 50 good + 15 bad
    assert len(batch.records) == 66


def test_firewall_defects_have_their_documented_shape() -> None:
    batch = generate("connect.firewall.v1", {"base_flows": 30, "bad_ratio": 0.5})
    payloads = [payload for _, payload in batch.records]
    for index_str, reason in batch.ground_truth["per_record_reason"].items():
        payload = payloads[int(index_str)]
        if reason == "missing_field":
            assert "currency" not in payload
        elif reason == "incoherent_amount":
            assert payload["amount"] in ("NOT_A_NUMBER", "999999999999999")
        else:  # dup_source_hash — verbatim re-emission of an earlier record
            first = next(i for i, p in enumerate(payloads) if p == payload)
            assert first < int(index_str)


def test_consolidation_entities_and_totals() -> None:
    batch = generate("finhub.consolidation.v1", {"entities": 3, "accounts_per_entity": 2})
    accounts = [p for t, p in batch.records if t == "bank_account"]
    assert batch.ground_truth["expected_entities"] == 3
    assert batch.ground_truth["expected_accounts"] == len(accounts) == 6
    assert len({a["entity"] for a in accounts}) == 3
    assert batch.ground_truth["expected_total_eur_approx"] > 0


def test_forecasting_covers_at_least_90_days() -> None:
    batch = generate("finhub.forecasting.v1", {"days": 10})  # clamped to the ≥90 floor
    gt = batch.ground_truth
    assert gt["days"] >= 90
    flows = [p for t, p in batch.records if t == "cash_flow"]
    assert gt["expected_history_points"] == len(flows)
    dates = {date.fromisoformat(p["value_date"]) for p in flows}
    assert (max(dates) - min(dates)).days >= 85  # spans (weekends carry no variable flow)
    assert set(gt["recurring_series"]) == {"salaries", "rent", "subscription", "customer_invoices"}
    refs = {p["ref"] for p in flows}
    assert any(r.startswith("REC-salaries-") for r in refs)


def test_anomaly_manifest_lists_exactly_anomaly_count() -> None:
    batch = generate("finhub.anomaly.v1", {"base_flows": 40, "anomaly_count": 7})
    injected = batch.ground_truth["injected_anomalies"]
    assert len(injected) == 7
    payloads = [payload for _, payload in batch.records]
    for entry in injected:
        if entry["type"] == "structuring":
            slices = [payloads[i] for i in entry["record_indices"]]
            assert len(slices) == 5
            assert {p["amount"] for p in slices} == {"-9500.00"}
            assert len({p["value_date"] for p in slices}) == 1
        elif entry["type"] == "off_hours":
            assert "T03:00" in payloads[entry["record_index"]]["booked_at"]


def test_anomaly_duplicate_shares_detection_key_but_not_hash() -> None:
    batch = generate("finhub.anomaly.v1", {"base_flows": 40, "anomaly_count": 8})
    payloads = [payload for _, payload in batch.records]
    dups = [e for e in batch.ground_truth["injected_anomalies"] if e["type"] == "duplicate"]
    assert dups
    for entry in dups:
        dup = payloads[entry["record_index"]]
        twins = [
            p
            for p in payloads
            if p is not dup
            and p.get("ref") == dup["ref"]
            and p.get("amount") == dup["amount"]
            and p.get("value_date") == dup["value_date"]
        ]
        assert twins  # detection key collides…
        assert all(p != dup for p in twins)  # …but the payload (hence hash) differs


def test_reconciliation_mismatched_pairs_length() -> None:
    batch = generate("finhub.reconciliation.v1", {"pairs": 40, "mismatch_ratio": 0.25})
    gt = batch.ground_truth
    assert len(gt["mismatched_pairs"]) == round(40 * 0.25) == 10
    assert gt["expected_auto_match_rate"] == 0.75
    erp = [p for t, p in batch.records if t == "financial_transaction"]
    missing = [m for m in gt["mismatched_pairs"] if m["type"] == "missing_leg"]
    assert len(erp) == 40 - len(missing)
    erp_refs = {p["ref"] for p in erp}
    for m in missing:
        assert m["ref"] not in erp_refs


def test_circuit_breaker_large_transfer() -> None:
    batch = generate("finhub.circuit_breaker.v1", {"trigger_pattern": "large_transfer"})
    gt = batch.ground_truth
    assert gt["expected_freeze"] is True
    assert gt["target_risk_score"] > 8
    assert len(gt["trigger_records"]) == 1
    _, payload = batch.records[gt["trigger_records"][0]["record_index"]]
    assert payload["amount"] == "-500000.00"


def test_circuit_breaker_rapid_sequence_fits_in_two_minutes() -> None:
    from datetime import datetime

    batch = generate("finhub.circuit_breaker.v1", {"trigger_pattern": "rapid_sequence"})
    triggers = batch.ground_truth["trigger_records"]
    assert len(triggers) == 8
    stamps = [
        datetime.fromisoformat(batch.records[t["record_index"]][1]["booked_at"])
        for t in triggers
    ]
    assert (max(stamps) - min(stamps)).total_seconds() < 120


def test_params_are_clamped_by_schema() -> None:
    batch = generate("connect.ingestion.v1", {"accounts": 999, "flows_per_account": -5})
    assert batch.ground_truth["expected_accounts"] == 20  # max clamp
    assert batch.ground_truth["expected_flows"] == 20  # 20 accounts × 1 flow (min clamp)


def test_invalid_enum_and_multi_fall_back_to_defaults() -> None:
    batch = generate(
        "connect.ingestion.v1",
        {"source_format": "sabotage", "currencies": ["XXX"], "accounts": 1},
    )
    assert batch.source_format == "psd2"
    flows = [p for t, p in batch.records if t == "cash_flow"]
    assert {p["currency"] for p in flows} == {"EUR"}
