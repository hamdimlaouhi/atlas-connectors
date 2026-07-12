"""`finhub.anomaly.v1` — labeled anomalies over a stable baseline.

Conception §5: `base_flows` baseline (stable amounts per counterparty) +
`anomaly_count` labeled anomalies cycled over `anomaly_types`:
`amount_outlier` (12× the counterparty median), `off_hours` (03:00 timestamp),
`duplicate` (same ref/amount/day re-emitted), `structuring` (5 × 9 500 € the
same day). Ground truth `{injected_anomalies: [{type, record_index|record_indices}]}`
— exactly `anomaly_count` entries; the emitter enriches each with source_hash.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from atlas_connectors.sim_service.generators.base import (
    COUNTERPARTIES,
    ParamSpec,
    coerce_params,
    entity_label,
    money,
    register,
    test_iban,
)
from atlas_connectors.sim_service.models import GeneratedBatch, SimBankAccount, SimCashFlow

_ANOMALY_TYPES = ("amount_outlier", "off_hours", "duplicate", "structuring")
_STRUCTURING_AMOUNT = 9_500.0
_STRUCTURING_SLICES = 5


@register
class FinhubAnomalyGenerator:
    preset_id = "finhub.anomaly.v1"
    module = "AtlasFinhub"
    feature = "anomaly"
    label = "Anomalies étiquetées"
    description = (
        "Base stable par contrepartie + anomalies injectées (montant aberrant, horaire "
        "atypique, doublon, fractionnement) — détecté vs injecté se compare."
    )
    phase = 1
    param_schema = (
        ParamSpec("base_flows", "int", 200, min=10, max=2000),
        ParamSpec("anomaly_count", "int", 5, min=1, max=50),
        ParamSpec("anomaly_types", "multi", list(_ANOMALY_TYPES), options=_ANOMALY_TYPES),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        base_flows: int = p["base_flows"]
        anomaly_count: int = p["anomaly_count"]
        anomaly_types: list[str] = p["anomaly_types"]

        batch = GeneratedBatch()
        account = SimBankAccount(
            iban=test_iban(rng),
            label="Compte courant 1",
            currency="EUR",
            entity=entity_label(target_label, 0),
            balance=money(rng.uniform(100_000, 400_000)),
        )
        batch.records.append(("bank_account", account.model_dump(mode="json")))

        # Stable baseline: each counterparty keeps a median amount ± 5%.
        medians = {name: rng.uniform(500, 8_000) for name in COUNTERPARTIES}
        baseline: list[SimCashFlow] = []
        for i in range(base_flows):
            counterparty = COUNTERPARTIES[i % len(COUNTERPARTIES)]
            amount = medians[counterparty] * (1.0 + rng.uniform(-0.05, 0.05))
            day = today - timedelta(days=rng.randint(0, 59))
            flow = SimCashFlow(
                account_iban=account.iban,
                amount=money(-amount),
                currency="EUR",
                value_date=day,
                booked_at=datetime(day.year, day.month, day.day, rng.randint(9, 17), 30),
                direction="debit",
                counterparty=counterparty,
                label="Règlement fournisseur",
                ref=f"ANM-{i:05d}",
            )
            baseline.append(flow)
            batch.records.append(("cash_flow", flow.model_dump(mode="json")))

        injected: list[dict[str, Any]] = []
        for k in range(anomaly_count):
            kind = anomaly_types[k % len(anomaly_types)]
            counterparty = COUNTERPARTIES[k % len(COUNTERPARTIES)]
            median = medians[counterparty]
            day = today - timedelta(days=rng.randint(0, 20))
            if kind == "structuring":
                indices: list[int] = []
                for s in range(_STRUCTURING_SLICES):
                    flow = SimCashFlow(
                        account_iban=account.iban,
                        amount=money(-_STRUCTURING_AMOUNT),
                        currency="EUR",
                        value_date=day,
                        booked_at=datetime(day.year, day.month, day.day, 10, 5 + s),
                        direction="debit",
                        counterparty=counterparty,
                        label="Virement fractionné",
                        ref=f"ANM-STR-{k:03d}-{s}",
                    )
                    indices.append(len(batch.records))
                    batch.records.append(("cash_flow", flow.model_dump(mode="json")))
                injected.append({"type": kind, "record_indices": indices})
                continue
            if kind == "duplicate":
                source = baseline[k % len(baseline)]
                # Same ref/amount/value_date (the detection key) but a distinct
                # booked_at so the source_hash does NOT collide — it must pass
                # ingestion and be caught by the detection rule, not the deduper.
                dup = source.model_copy(
                    update={
                        "booked_at": (source.booked_at or datetime(day.year, day.month, day.day))
                        + timedelta(minutes=7)
                    }
                )
                injected.append({"type": kind, "record_index": len(batch.records)})
                batch.records.append(("cash_flow", dup.model_dump(mode="json")))
                continue
            if kind == "amount_outlier":
                flow = SimCashFlow(
                    account_iban=account.iban,
                    amount=money(-median * 12),
                    currency="EUR",
                    value_date=day,
                    booked_at=datetime(day.year, day.month, day.day, 11, 0),
                    direction="debit",
                    counterparty=counterparty,
                    label="Règlement fournisseur",
                    ref=f"ANM-OUT-{k:03d}",
                )
            else:  # off_hours
                flow = SimCashFlow(
                    account_iban=account.iban,
                    amount=money(-median),
                    currency="EUR",
                    value_date=day,
                    booked_at=datetime(day.year, day.month, day.day, 3, 0),
                    direction="debit",
                    counterparty=counterparty,
                    label="Règlement fournisseur",
                    ref=f"ANM-OFH-{k:03d}",
                )
            injected.append({"type": kind, "record_index": len(batch.records)})
            batch.records.append(("cash_flow", flow.model_dump(mode="json")))

        batch.ground_truth = {"injected_anomalies": injected}
        return batch
