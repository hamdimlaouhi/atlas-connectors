"""source_hash is the platform idempotency key — lock its determinism."""

from atlas_connectors.kernel.base import RawRecord
from atlas_connectors.kernel.provenance import source_hash, stamp


def test_source_hash_is_deterministic() -> None:
    raw = b'{"iban": "FR7630006000011234567890189", "amount": "100.00"}'
    assert source_hash(raw) == source_hash(raw)


def test_source_hash_differs_on_any_byte_change() -> None:
    assert source_hash(b"payload-a") != source_hash(b"payload-b")


def test_reingestion_produces_identical_hash() -> None:
    """Re-running an extraction over identical source data must republish the
    same hash — that is what makes re-ingestion safe for Core to dedupe."""
    record = RawRecord(
        source_system="camt053",
        source_message_id="STMT-1",
        record_type="bank_balance",
        payload={"iban": "FR76...", "amount": "1.00"},
        raw_bytes=b"<Stmt>identical bytes</Stmt>",
    )
    first = stamp(record)
    second = stamp(record)
    assert first.source_hash == second.source_hash
    assert len(first.source_hash) == 64  # sha256 hex
