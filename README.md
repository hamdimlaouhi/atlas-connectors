# atlas-connectors

> Python 3.11 **ingestion adapters** for ERPs and banks. Extracts heterogeneous source data, stamps it with provenance (`source_metadata` + SHA-256 `source_hash`), and feeds it into the data fabric. **Read-only by design in Phase 1** — extraction in, never write out.

These are the "Connect, Don't Replace" adapters: Atlas overlays the company's in-place ERP/banking systems rather than replacing them. Connectors are the only repo that touches external source systems.

## Where this fits

```
SAP / Sage / banks / files ─→ [ atlas-connectors ] ─→ ingestion ─→ event bus ─→ atlas-core (Normalizer → CDM + audit)
```

Connectors **extract and stamp**; they hand a *raw payload + `source_hash`* to the pipeline. The ISO 20022 **canonical normalization, the data-quality firewall, and the CDM are core-owned** ([`atlas-core`](../atlas-core)) — connectors don't define financial semantics. They never call Product or Web.

## Responsibility

- Pull data from each source system on its own protocol, read-only.
- Attach `source_metadata` (source system, source message id, SHA-256 `source_hash`, ingestion timestamp, mapping-rule/model version, confidence score) — DORA L1 traceability.
- Use `source_hash` as the **idempotency key** so re-ingestion is safe.
- Publish to the ingestion pipeline (async, event-driven) for Core to normalize and audit.

## Adapters hosted

| Adapter | Protocol / source | Phase | Build (documented) |
|---|---|---|---|
| **PSD2 / Open Banking** | Aggregator (Bridge/Plaid/TrueLayer); OAuth bank consent; balances + 7-day transactions; ~4h auto-refresh; 90-day consent-expiry handling | 1 | Outsource (BridgeAPI ≈ €150/mo) |
| **SAP S/4HANA** | OData / RFC / BAPI; FI module (GL journals, third parties, invoices); SAP→CDM mapping + delta sync | 1 | Co-Design (Stijn Veldboer, ~€20,000 / 25 days) |
| **Sage 100/X3** | REST; GL, AP, AR | 1 | In-House (Kumar) |
| **Bank-file ingestion** | camt.053, camt.052 (intraday), MT940, AFB120 over **EBICS**; FEC import | 1 | In-House |
| **Invoice intake** | Upload → **Mindee** call (extraction compute runs in [`atlas-ai`](../atlas-ai); storage on OVH S3) | 1 | — |
| **Oracle ERP** | Integration spec present | later | — |
| **Payment-emission adapters** | BaaS partners (Treezor / Swan); pain.001 / pain.002 | 2 | — |
| **DLT settlement adapter** | AtlasCoin on-chain settlement | 3 | — |

> v0.1 sources in scope = **camt.053 + PSD2 (Bridge)**. MT940, SAP, Sage/Odoo as live API sources land in later phases.

## Data ownership

Owns **only** ingestion-staging state and the `source_metadata` it produces. It does **not** own the canonical model — that's Core. Each adapter is the anti-corruption boundary between one messy external format and the clean hand-off contract.

## Contract & sync vs async

- Emits ingestion/canonical events per the schemas in [`atlas-contracts`](../atlas-contracts).
- **Async / event-driven ingestion** — connectors run as background pulls/listeners, not on any synchronous read path.

## Stack

Python 3.11 · async ingestion workers · EBICS client · Kafka/Redpanda producers · Mindee (invoice OCR call) · provider SDKs (BridgeAPI, SAP OData, Sage REST).

## Guardrails

- **Read-only in Phase 1** — extraction only; no write capability. Payment-emission and settlement adapters (Phase 2/3) emit **only after** Core's HITL `execute` gate has authorized them — a connector never decides to move money on its own.
- **EU sovereignty** — connectors run in the EU; bank reads stay in-EU (in the FOS model, direct EBICS); Phase-1 payments are simulated, never emitted.
- **`source_hash` idempotency** on every re-ingestion; immutable provenance for the audit trail (reconstructible raw source → dashboard).
- **Resilience** — timeout on every connector/bank call; retries with backoff + jitter for idempotent pulls; failures route to the bus dead-letter queue.
- **Secrets** (bank/ERP credentials, OAuth tokens) in HashiCorp Vault, never in the repo.

## Build order (documented)

- **Slice 1** — PSD2 / Open Banking connector (US-020): balances + 7-day transactions normalized to CDM; bad records quarantined by Core's firewall.
- **Slice 2** — SAP S/4HANA connector (US-021) with delta sync; invoice intake → Mindee (US-022).

## Reference

- Platform architecture: [`atlas-tech-docs/Atlas_Solution_Architecture.md`](../atlas-tech-docs/Atlas_Solution_Architecture.md) — §5, §8 (ingestion flow), §9.
- Specs: [`01_AtlasConnect`](../atlas-tech-docs/specs/01_AtlasConnect_Spec.md) (§3, §11), [`03_AtlasPay`](../atlas-tech-docs/specs/03_AtlasPay_Spec.md) (Phase 2), [`05_AtlasCoin`](../atlas-tech-docs/specs/05_AtlasCoin_Spec.md) (Phase 3).
- Feeds: [`atlas-core`](../atlas-core) · Contracts: [`atlas-contracts`](../atlas-contracts) · Compute: [`atlas-ai`](../atlas-ai).
