"""`finhub.circuit_breaker.v1` — trigger the HITL freeze.

Conception §5: a small baseline + one `trigger_pattern`: `large_transfer`
(single 500 k€ to a first-seen IBAN) or `rapid_sequence` (8 transfers < 2 min).
Ground truth: `{expected_freeze: true, target_risk_score, trigger_records}` —
the emitter enriches each trigger record with its source_hash (trigger_hashes).
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

_BASELINE_FLOWS = 10
_LARGE_TRANSFER_EUR = 500_000.0
_RAPID_TRANSFERS = 8


@register
class FinhubCircuitBreakerGenerator:
    preset_id = "finhub.circuit_breaker.v1"
    module = "AtlasFinhub"
    feature = "circuit_breaker"
    label = "Disjoncteur / gel HITL"
    description = (
        "Motif déclencheur (virement massif vers IBAN inconnu ou rafale < 2 min) sur une "
        "petite base — score > 8 ⇒ gel HITL + alerte critique attendus."
    )
    phase = 1
    param_schema = (
        ParamSpec("target_risk_score", "float", 9.0, min=8.1, max=10.0),
        ParamSpec(
            "trigger_pattern",
            "enum",
            "large_transfer",
            options=("large_transfer", "rapid_sequence"),
        ),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        pattern: str = p["trigger_pattern"]

        batch = GeneratedBatch()
        account = SimBankAccount(
            iban=test_iban(rng),
            label="Compte courant 1",
            currency="EUR",
            entity=entity_label(target_label, 0),
            balance=money(rng.uniform(400_000, 900_000)),
        )
        batch.records.append(("bank_account", account.model_dump(mode="json")))

        for i in range(_BASELINE_FLOWS):
            day = today - timedelta(days=rng.randint(1, 29))
            flow = SimCashFlow(
                account_iban=account.iban,
                amount=money(-rng.uniform(200, 5_000)),
                currency="EUR",
                value_date=day,
                booked_at=datetime(day.year, day.month, day.day, rng.randint(9, 17), 0),
                direction="debit",
                counterparty=rng.choice(COUNTERPARTIES),
                label="Règlement courant",
                ref=f"CB-BASE-{i:03d}",
            )
            batch.records.append(("cash_flow", flow.model_dump(mode="json")))

        trigger_records: list[dict[str, Any]] = []
        first_seen_iban = test_iban(rng)  # never used by the baseline
        if pattern == "large_transfer":
            flow = SimCashFlow(
                account_iban=account.iban,
                amount=money(-_LARGE_TRANSFER_EUR),
                currency="EUR",
                value_date=today,
                booked_at=datetime(today.year, today.month, today.day, 14, 12),
                direction="debit",
                counterparty=f"Bénéficiaire inconnu {first_seen_iban[-4:]}",
                label="Virement massif vers IBAN inconnu",
                ref="CB-TRIG-000",
            )
            trigger_records.append({"record_index": len(batch.records)})
            batch.records.append(("cash_flow", flow.model_dump(mode="json")))
        else:  # rapid_sequence — 8 transfers inside 2 minutes
            base_time = datetime(today.year, today.month, today.day, 14, 10, 0)
            for s in range(_RAPID_TRANSFERS):
                flow = SimCashFlow(
                    account_iban=account.iban,
                    amount=money(-rng.uniform(8_000, 20_000)),
                    currency="EUR",
                    value_date=today,
                    booked_at=base_time + timedelta(seconds=14 * s),
                    direction="debit",
                    counterparty=f"Bénéficiaire inconnu {first_seen_iban[-4:]}",
                    label="Rafale de virements",
                    ref=f"CB-TRIG-{s:03d}",
                )
                trigger_records.append({"record_index": len(batch.records)})
                batch.records.append(("cash_flow", flow.model_dump(mode="json")))

        batch.ground_truth = {
            "expected_freeze": True,
            "target_risk_score": float(p["target_risk_score"]),
            "trigger_pattern": pattern,
            "trigger_records": trigger_records,
        }
        return batch
