"""Run one adapter end-to-end: extract → stamp provenance → publish.

One deployable runs many adapters (see ARCHITECTURE.md D-1); this is the
single-adapter unit the scheduler composes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlas_connectors.kernel.base import BaseConnector, CanonicalRecord
from atlas_connectors.kernel.provenance import stamp
from atlas_connectors.kernel.publisher import PublisherPort


def run_adapter(connector: BaseConnector, publisher: PublisherPort, *, tenant_id: UUID) -> int:
    """Extract everything the connector yields, stamp it, publish it.

    tenant_id comes from the connector instance's own configuration — a
    connector is tenant-scoped; tenancy is never inferred from payload content.
    Returns the number of records published.
    """
    published = 0
    for raw in connector.extract():
        record = CanonicalRecord(
            tenant_id=tenant_id,
            record_type=raw.record_type,
            payload=raw.payload,
            source_metadata=stamp(raw),
            trace_id=uuid4(),
            occurred_at=datetime.now(tz=UTC),
        )
        publisher.publish(record)
        published += 1
    return published
