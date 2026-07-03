"""DEV canonical-record simulator — the stand-in for all adapters in DEV.

Per the DEV environment spec (§9) the internal simulator occupies the
connectors' place at the head of the ingestion → canonical → audit flow:
it publishes well-formed, tenant-tagged CanonicalRecord messages to the
canonical topic, which is how the DEV acceptance gate (§14: simulator →
topic → core → canonical row + immutable audit entry) is exercised.

Usage:
    atlas-simulate --count 5 --tenant 3f6c...d2 --stdout        # dry run
    atlas-simulate --count 5 --tenant 3f6c...d2 \
        --project fos-dev-500119 --topic atlas-dev-canonical-records
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlas_connectors.kernel.base import CanonicalRecord, CanonicalRecordType, RawRecord
from atlas_connectors.kernel.provenance import stamp
from atlas_connectors.kernel.publisher import PublisherPort, StdoutPublisher

# Adapter-internal record types → canonical enum (atlas-contracts). A balance
# snapshot updates the bank_account canonical record.
_CANONICAL_TYPE: dict[str, CanonicalRecordType] = {"bank_balance": "bank_account"}


def _sample_record(i: int) -> RawRecord:
    """A plausible bank-balance record, unique per call so source_hash differs."""
    payload = {
        "iban": f"FR76300060000112345678{i:03d}",
        "amount": f"{random.uniform(1_000, 250_000):.2f}",
        "currency": "EUR",
        "balance_type": "closing_booked",
        "statement_id": f"SIM-{uuid4().hex[:12]}",
    }
    raw = repr(payload).encode()
    return RawRecord(
        source_system="simulator",
        source_message_id=payload["statement_id"],
        record_type="bank_balance",
        payload=payload,
        raw_bytes=raw,
    )


def simulate(publisher: PublisherPort, *, tenant_id: UUID, count: int) -> int:
    for i in range(count):
        raw = _sample_record(i)
        publisher.publish(
            CanonicalRecord(
                event_id=uuid4(),
                tenant_id=tenant_id,
                record_type=_CANONICAL_TYPE[raw.record_type],
                payload=raw.payload,
                source_metadata=stamp(raw),
                trace_id=uuid4(),
                occurred_at=datetime.now(tz=UTC),
            )
        )
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish simulated CanonicalRecord messages")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--tenant", required=True, help="tenant_id (UUID)")
    parser.add_argument("--project", default="fos-dev-500119")
    parser.add_argument("--topic", default=None, help="Pub/Sub topic; omit with --stdout")
    parser.add_argument("--stdout", action="store_true", help="dry run: print instead of publish")
    args = parser.parse_args()

    publisher: PublisherPort
    if args.stdout or not args.topic:
        publisher = StdoutPublisher()
    else:
        from atlas_connectors.kernel.publisher import PubSubPublisher

        publisher = PubSubPublisher(args.project, args.topic)

    n = simulate(publisher, tenant_id=UUID(args.tenant), count=args.count)
    print(f"published {n} CanonicalRecord message(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
