"""Turn a GeneratedBatch into CanonicalRecords THROUGH THE KERNEL and emit them.

This is ADR-SIM-001 made concrete: RawRecord → provenance.stamp() →
CanonicalRecord → PublisherPort — the exact path a live adapter takes. The only
distinction from a real feed is the provenance extension
(origin=SIMULATION, batch_id, seed, preset_id, generated_by), stamped here,
in-kernel, never optional on the sim path (G2).

source_hash is computed over the CANONICAL JSON of the payload dict
(sorted keys) so an identical payload ⇒ identical hash — which is what makes
`dup_source_hash` records collide and lets Core's idempotency prove itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from atlas_connectors.kernel.base import CanonicalRecord, CanonicalRecordType, RawRecord
from atlas_connectors.kernel.http_push import PoisonRecordError
from atlas_connectors.kernel.provenance import stamp
from atlas_connectors.kernel.publisher import PublisherPort
from atlas_connectors.sim_service.models import SIM_MODELS, GeneratedBatch


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic bytes for hashing: canonical JSON (sorted keys)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class EmitReport:
    expected: int
    emitted: int = 0
    rejected: int = 0
    source_hashes: list[dict[str, str]] = field(default_factory=list)


def build_canonical_records(
    batch: GeneratedBatch,
    *,
    tenant_id: UUID,
    trace_id: UUID,
    batch_id: UUID,
    seed: int,
    preset_id: str | None,
    generated_by: str,
) -> list[CanonicalRecord]:
    """Stamp every sim record through the kernel.

    A record whose (record_type, payload) already appeared in the batch reuses
    the FIRST occurrence's source_message_id: identical payload AND identical
    message id ⇒ the source_hash collision is a true duplicate, not an accident.
    """
    source_system = f"sim.{batch.source_format}"
    records: list[CanonicalRecord] = []
    first_seen: dict[tuple[str, bytes], str] = {}
    for i, (record_type, payload) in enumerate(batch.records):
        if record_type not in SIM_MODELS:
            raise ValueError(f"unknown sim record_type: {record_type!r}")
        raw_bytes = canonical_payload_bytes(payload)
        key = (record_type, raw_bytes)
        message_id = first_seen.setdefault(key, f"{batch_id}:{i}")
        raw = RawRecord(
            source_system=source_system,
            source_message_id=message_id,
            record_type=record_type,
            payload=payload,
            raw_bytes=raw_bytes,
        )
        meta = stamp(raw).model_copy(
            update={
                "origin": "SIMULATION",
                "batch_id": batch_id,
                "seed": seed,
                "preset_id": preset_id,
                "generated_by": generated_by,
            }
        )
        records.append(
            CanonicalRecord(
                event_id=uuid4(),
                tenant_id=tenant_id,
                record_type=cast(CanonicalRecordType, record_type),
                payload=payload,
                source_metadata=meta,
                trace_id=trace_id,
                occurred_at=datetime.now(tz=UTC),
            )
        )
    return records


def enrich_ground_truth(ground_truth: dict[str, Any], hashes: list[str]) -> dict[str, Any]:
    """Resolve generator-side record indices into emitted source_hashes so the
    manifest speaks the pipeline's idempotency language (Conception §5 tables)."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items()}
            index = out.get("record_index")
            if isinstance(index, int) and 0 <= index < len(hashes):
                out["source_hash"] = hashes[index]
            indices = out.get("record_indices")
            if isinstance(indices, list):
                out["source_hashes"] = [
                    hashes[j] for j in indices if isinstance(j, int) and 0 <= j < len(hashes)
                ]
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return cast(dict[str, Any], walk(ground_truth))


def emit(records: list[CanonicalRecord], publisher: PublisherPort) -> EmitReport:
    """Publish every record; a poison record (Core 400) counts as rejected and
    never blocks the rest of the stream (README resilience rule)."""
    report = EmitReport(expected=len(records))
    for record in records:
        try:
            publisher.publish(record)
        except PoisonRecordError:
            report.rejected += 1
        else:
            report.emitted += 1
        report.source_hashes.append(
            {
                "source_hash": record.source_metadata.source_hash,
                "record_type": record.record_type,
            }
        )
    return report
