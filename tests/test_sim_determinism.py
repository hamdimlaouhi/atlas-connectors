"""Determinism is a dominant driver (Conception §2.3): identical
(preset_id, params, seed, today) ⇒ byte-identical payloads AND identical
source_hashes — the ML ground truth depends on it."""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

import pytest

from atlas_connectors.sim_service.emitter import build_canonical_records
from atlas_connectors.sim_service.generators import REGISTRY

TODAY = date(2026, 7, 1)
BATCH_ID = UUID("00000000-0000-4000-8000-00000000b001")
TENANT_ID = UUID("00000000-0000-4000-8000-0000000000aa")
TRACE_ID = UUID("00000000-0000-4000-8000-0000000000bb")


@pytest.mark.parametrize("preset_id", sorted(REGISTRY))
def test_same_inputs_produce_identical_payload_json(preset_id: str) -> None:
    generator = REGISTRY[preset_id]
    one = generator.generate({}, 42, "Société Test", today=TODAY)
    two = generator.generate({}, 42, "Société Test", today=TODAY)
    assert json.dumps(one.records, sort_keys=True) == json.dumps(two.records, sort_keys=True)
    assert one.ground_truth == two.ground_truth


@pytest.mark.parametrize("preset_id", sorted(REGISTRY))
def test_same_inputs_produce_identical_source_hashes(preset_id: str) -> None:
    generator = REGISTRY[preset_id]
    hashes: list[list[str]] = []
    for _ in range(2):
        batch = generator.generate({}, 42, "Société Test", today=TODAY)
        records = build_canonical_records(
            batch,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            batch_id=BATCH_ID,
            seed=42,
            preset_id=preset_id,
            generated_by="pytest",
        )
        hashes.append([r.source_metadata.source_hash for r in records])
    assert hashes[0] == hashes[1]


def test_different_seed_changes_the_batch() -> None:
    generator = REGISTRY["connect.ingestion.v1"]
    one = generator.generate({}, 42, "Société Test", today=TODAY)
    two = generator.generate({}, 43, "Société Test", today=TODAY)
    assert json.dumps(one.records, sort_keys=True) != json.dumps(two.records, sort_keys=True)
