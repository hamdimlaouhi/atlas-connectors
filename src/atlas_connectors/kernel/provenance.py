"""Provenance stamping — source_hash is the platform's idempotency key."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from atlas_connectors.kernel.base import RawRecord, SourceMetadata


def source_hash(raw: bytes) -> str:
    """Deterministic SHA-256 hex over the raw payload bytes.

    Re-ingesting identical source data MUST produce the identical hash —
    atlas-core dedupes on it, which is what makes re-ingestion safe.
    """
    return hashlib.sha256(raw).hexdigest()


def stamp(
    record: RawRecord, *, mapping_rule_version: str = "v0.1", confidence: float = 1.0
) -> SourceMetadata:
    """Build the SourceMetadata for a raw record at ingestion time."""
    return SourceMetadata(
        source_system=record.source_system,
        source_message_id=record.source_message_id,
        source_hash=source_hash(record.raw_bytes),
        ingested_at=datetime.now(tz=UTC),
        mapping_rule_version=mapping_rule_version,
        confidence=confidence,
    )
