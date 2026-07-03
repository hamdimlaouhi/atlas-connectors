# atlas-connectors — Architecture

> Companion to [`README.md`](README.md) (binding scope) and
> [`atlas-tech-docs/Atlas_Solution_Architecture.md`](../atlas-tech-docs/Atlas_Solution_Architecture.md) §5/§8/§9.
> Living document: update it as slices land; record load-bearing changes under **Decisions**.

## Context for Claude Code

- This repo is the **only** place that touches external source systems (banks, ERPs, files). It extracts, stamps provenance, and publishes — it never normalizes to CDM (Core owns that), never calls Product/Web, and is **read-only in Phase 1** (no write capability may exist in any adapter).
- Python 3.11, `src/` layout, package `atlas_connectors`. Pydantic v2 models. No framework — these are workers, not an API.
- Cross-repo message shapes (`CanonicalRecord`, ingestion events) belong to [`atlas-contracts`](../atlas-contracts); until the schema lands there, the local Pydantic models in `kernel/base.py` are placeholders mirroring the DEV spec and must be reconciled when `atlas-contracts` publishes the Avro/JSON schema.
- The DEV environment (GCP project `fos-dev-500119`, `europe-west9`) is already provisioned by `atlas-infra/install/dev`: topic `atlas-dev-canonical-records`, DLQ `atlas-dev-canonical-records-dlq`. There is no Kafka in DEV.
- Do not touch: financial semantics (no CDM mapping logic here beyond adapter-local shaping into `RawRecord`), payment emission (Phase 2, gated by Core HITL), secrets in code (Vault / Secret Manager only).

## Dominant drivers

1. **Heterogeneous, messy sources on independent clocks** — each source needs its own anti-corruption layer, isolated from the others.
2. **Provenance & idempotency are the product** (DORA L1 traceability): every record must carry `source_metadata` and a deterministic `source_hash`; re-ingestion must be safe.
3. **Read-only Phase 1 / EU sovereignty** — extraction only, EU-resident execution.
4. **Small team** — one deployable, many adapters; operational surface stays flat until a force splits it.

## Stack

| Concern | Target (per README) | DEV binding (GCP, provisioned) |
|---|---|---|
| Language | Python 3.11 | same |
| Models/config | Pydantic v2 + pydantic-settings | same |
| Event bus producer | Kafka/Redpanda | **Pub/Sub** → `atlas-dev-canonical-records` |
| Bank files | camt.053/052, MT940 over EBICS | camt.053 fixtures / simulator |
| Open banking | BridgeAPI (PSD2 aggregator) | stubbed client |
| Invoice OCR | Mindee call (compute in atlas-ai) | deferred to its slice |
| Secrets | HashiCorp Vault | Secret Manager (`atlas-dev-*`) |
| Runtime | async workers (container) | Cloud Run job / service (later slice) |

The bus difference is absorbed by a **publisher port** — adapters never import a broker SDK.

## Architecture

**Plugin / adapter architecture (ports & adapters, worker-shaped).** A small **ingestion kernel** owns everything generic; each source is a **plugin package** implementing one protocol. Chosen over one-service-per-connector because the adapters share 90% of their lifecycle (schedule → extract → stamp → publish → retry/DLQ) and a small team cannot operate N deployables; chosen over a monolithic script because source-specific mess must not leak across sources.

```
                    ┌──────────────── ingestion kernel ───────────────┐
 SAP / banks / files│ runner → BaseConnector.extract() → RawRecord    │
        (external)  │        → provenance stamp (source_hash)         │
                    │        → PublisherPort.publish()  → retry/DLQ   │
                    └───────────────┬─────────────────────────────────┘
        adapters: camt053 · psd2_bridge · (sap, sage, mt940 …)        │
                                    ▼
                 Kafka (target) / Pub/Sub (DEV) → atlas-core normalizer
```

- **`BaseConnector` protocol**: `extract() -> Iterator[RawRecord]`. An adapter converts *one* messy external format into `RawRecord` (raw payload + enough source identity to stamp provenance). Nothing else. CDM mapping is Core's.
- **Kernel** (`kernel/`): runner loop, provenance stamper (`source_hash` = SHA-256 of the raw payload — the idempotency key Core dedupes on), `PublisherPort` with `PubSubPublisher` (DEV), `StdoutPublisher` (local), `KafkaPublisher` (target, later), retry with exponential backoff + jitter, DLQ routing (broker-side in DEV: Pub/Sub dead-letters after 5 attempts).
- **Adapters are data, not services.** One deployable runs many adapters. **Split trigger** (only then): an adapter needing its own scale or cadence (e.g. SAP delta sync every minute vs 4-hour PSD2 refresh windows), or a fault domain that must not share a process (a flaky EBICS endpoint stalling other pulls).
- **The DEV simulator lives here** (`simulator.py`): per DEV spec §9 the internal simulator *occupies the connectors' place*, publishing well-formed `CanonicalRecord` messages (tenant-tagged) to the canonical topic. It is the head of the DEV acceptance flow: simulator → topic → core → canonical row + immutable audit entry. It is a first-class citizen of this repo, not test scaffolding — keep it aligned with the contract.

**Costs accepted:** a shared deployable means one bad adapter can starve the runner (mitigated by per-adapter timeouts); the publisher port adds an abstraction layer that pays off only when Kafka lands — that's fine, it's thin.

## Repository layout

```
src/atlas_connectors/
  kernel/
    base.py         # BaseConnector protocol, RawRecord, SourceMetadata, CanonicalRecord (placeholder → atlas-contracts)
    provenance.py   # source_hash (sha256), stamp()
    publisher.py    # PublisherPort, PubSubPublisher, StdoutPublisher
    retry.py        # backoff + jitter
    runner.py       # run one adapter end-to-end
  adapters/
    camt053/parser.py       # camt.053 XML → RawRecord (v0.1)
    psd2_bridge/client.py   # BridgeAPI client stub (v0.1; consent-expiry TODO)
  simulator.py      # DEV CanonicalRecord simulator CLI (atlas-simulate)
  settings.py
tests/
Dockerfile · Makefile · pyproject.toml
```

## Cross-cutting concerns

- **Provenance**: `SourceMetadata {source_system, source_message_id, source_hash, ingested_at, mapping_rule_version, confidence}` stamped on every record before publish. Never optional.
- **Idempotency**: `source_hash` is deterministic over raw bytes; re-running an extraction republishes the same hashes and Core dedupes. Tests must lock this.
- **Resilience**: timeout on every external call; retries (backoff+jitter) only for idempotent pulls; poison messages go to the DLQ, never block the stream.
- **Trace**: every published message carries `trace_id` (new UUID at ingestion; Core propagates it onward).
- **Secrets**: bank/ERP credentials and OAuth tokens from Secret Manager (DEV) / Vault (target) at runtime. Nothing in the repo, nothing in env files committed.
- **Tenancy**: every record carries `tenant_id` from the connector's own configuration (a connector instance is tenant-scoped); it is never inferred from payload content.

## Build order

1. **Kernel + simulator (this scaffold)** — publisher port, provenance, simulator CLI. *Acceptance:* `atlas-simulate --count 3 --tenant <uuid> --stdout` emits 3 valid CanonicalRecord JSON messages; with `--topic` they land in `atlas-dev-canonical-records` and (once atlas-core deploys) produce canonical rows + audit entries.
2. **Slice 1 — PSD2/Bridge (US-020)**: real BridgeAPI client, OAuth consent + 90-day expiry handling, balances + 7-day transactions. *Acceptance:* sandbox pull publishes records; bad records quarantined by Core's firewall.
3. **Slice 2 — camt.053 file ingestion + SAP S/4HANA (US-021) + invoice intake → Mindee (US-022).**
4. Later: MT940/EBICS live, Sage, Oracle; Phase 2 payment-emission adapters (only after Core HITL `execute` gate exists).

Verification: `make test` (pytest), `make lint` (ruff + mypy), `make simulate` (stdout dry-run).

## Decisions

- **D-1 Plugin kernel over service-per-connector** — shared lifecycle, one deployable, flat ops; split only on scale/cadence/fault-domain force (see above).
- **D-2 Publisher is a port** — Kafka (target) vs Pub/Sub (DEV, provisioned) is a binding, not an architecture; adapters must stay broker-agnostic.
- **D-3 Simulator is production code of this repo** — it is the DEV stand-in for all adapters and the driver of the DEV acceptance flow (spec §9/§14).
- **D-4 Local message models are placeholders** — authoritative schemas belong to `atlas-contracts`; reconcile on first publish there (flagged, R-2 contract drift).
- **D-5 Read-only Phase 1 is structural** — no adapter exposes a write path; payment emission arrives only as new, HITL-gated adapters in Phase 2.
