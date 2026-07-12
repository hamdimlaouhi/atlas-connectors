"""Core types of the ingestion kernel.

`CanonicalRecord` / event shapes are OWNED by atlas-contracts (R-2). The models
here are placeholders mirroring the DEV environment spec (§9) and must be
reconciled when atlas-contracts publishes the authoritative schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field

# Canonical record types — closed enum per atlas-contracts
# schemas/events/canonical-record.schema.json. Adapter-internal RawRecord
# types are free-form; the mapping to this enum happens at publish time.
CanonicalRecordType = Literal[
    "bank_account", "cash_flow", "invoice", "party", "financial_transaction"
]


class SourceMetadata(BaseModel):
    """DORA L1 provenance — stamped on every record, never optional.

    The `origin`/`batch_id`/`seed`/`preset_id`/`generated_by` fields are the
    OPTIONAL simulation-provenance extension (atlas-contracts Appendix F,
    Atlas_Simulation_Conception §3 G2): a live feed leaves them None; the sim
    service stamps `origin="SIMULATION"` in-kernel so ingestion can never
    receive an untagged synthetic batch. Additive only — existing semantics
    are unchanged.
    """

    source_system: str
    source_message_id: str
    source_hash: str = Field(description="SHA-256 hex of the raw payload; the idempotency key")
    ingested_at: datetime
    mapping_rule_version: str = "v0.1"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    origin: str | None = None
    batch_id: UUID | None = None
    seed: int | None = None
    preset_id: str | None = None
    generated_by: str | None = None


class RawRecord(BaseModel):
    """What an adapter hands to the kernel: raw payload + source identity.

    No CDM semantics here — normalization to the canonical model is atlas-core's.
    """

    source_system: str
    source_message_id: str
    record_type: str
    payload: dict[str, Any]
    raw_bytes: bytes = Field(repr=False, exclude=True)


class CanonicalRecord(BaseModel):
    """Message published to the canonical-records topic.

    Aligned to atlas-contracts schemas/events/canonical-record.schema.json
    (the authoritative shape — R-2). Field names and the record_type enum
    must not drift from that schema.
    """

    event_id: UUID
    tenant_id: UUID
    record_type: CanonicalRecordType
    payload: dict[str, Any]
    source_metadata: SourceMetadata
    trace_id: UUID
    occurred_at: datetime


@runtime_checkable
class BaseConnector(Protocol):
    """One adapter = one messy external source behind this protocol.

    Read-only by design (Phase 1): extraction in, never write out.
    """

    source_system: str

    def extract(self) -> Iterator[RawRecord]:
        """Pull from the source and yield raw records. Must be safe to re-run
        (idempotent pulls only); the kernel stamps provenance and publishes."""
        ...
