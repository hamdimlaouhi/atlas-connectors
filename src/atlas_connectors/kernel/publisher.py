"""Publisher port — adapters and the runner never import a broker SDK.

Bindings:
- StdoutPublisher  : local development / dry runs.
- PubSubPublisher  : DEV (GCP `fos-dev-500119`, topic `atlas-dev-canonical-records`).
- KafkaPublisher   : target binding per README — lands with the Kafka/Redpanda slice.
"""

from __future__ import annotations

import sys
from typing import Protocol

from atlas_connectors.kernel.base import CanonicalRecord


class PublisherPort(Protocol):
    def publish(self, record: CanonicalRecord) -> None: ...


class StdoutPublisher:
    """Dry-run binding: one JSON message per line."""

    def publish(self, record: CanonicalRecord) -> None:
        sys.stdout.write(record.model_dump_json() + "\n")


class PubSubPublisher:
    """DEV binding. Requires the `dev-gcp` extra (google-cloud-pubsub).

    Dead-lettering is broker-side in DEV: the push subscription retries with
    backoff and dead-letters to `atlas-dev-canonical-records-dlq` after 5
    attempts — the publisher does not implement DLQ logic itself.
    """

    def __init__(self, project_id: str, topic: str) -> None:
        from google.cloud import pubsub_v1  # deferred: optional dependency

        self._client = pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project_id, topic)

    def publish(self, record: CanonicalRecord) -> None:
        future = self._client.publish(
            self._topic_path,
            record.model_dump_json().encode("utf-8"),
            trace_id=str(record.trace_id),
            tenant_id=str(record.tenant_id),
        )
        future.result(timeout=30)
