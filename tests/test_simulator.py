import json
from uuid import UUID, uuid4

from atlas_connectors.kernel.base import CanonicalRecord
from atlas_connectors.simulator import simulate


class CapturePublisher:
    def __init__(self) -> None:
        self.records: list[CanonicalRecord] = []

    def publish(self, record: CanonicalRecord) -> None:
        self.records.append(record)


def test_simulator_publishes_tenant_tagged_canonical_records() -> None:
    tenant = uuid4()
    publisher = CapturePublisher()

    count = simulate(publisher, tenant_id=tenant, count=3)

    assert count == 3
    assert len(publisher.records) == 3
    for rec in publisher.records:
        assert rec.tenant_id == tenant
        assert rec.record_type == "bank_account"  # bank_balance → canonical enum
        assert isinstance(rec.event_id, UUID)
        assert len(rec.source_metadata.source_hash) == 64
        assert isinstance(rec.trace_id, UUID)
        # the wire format is JSON-serializable as-is
        assert json.loads(rec.model_dump_json())["tenant_id"] == str(tenant)
