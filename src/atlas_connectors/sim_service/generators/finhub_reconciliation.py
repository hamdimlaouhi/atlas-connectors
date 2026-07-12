"""`finhub.reconciliation.v1` — bank-flow ↔ ERP-leg pairs for the matcher.

Conception §5: `pairs` pairs sharing ref/amount/date; `round(pairs *
mismatch_ratio)` broken by `mismatch_types`: `amount` (±δ on the ERP leg),
`date` (+3 days), `missing_leg` (ERP omitted). Ground truth:
`{expected_auto_match_rate, mismatched_pairs}`.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from datetime import date, timedelta
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
from atlas_connectors.sim_service.models import (
    GeneratedBatch,
    SimBankAccount,
    SimCashFlow,
    SimErpEntry,
)

_MISMATCH_TYPES = ("amount", "date", "missing_leg")


@register
class FinhubReconciliationGenerator:
    preset_id = "finhub.reconciliation.v1"
    module = "AtlasFinhub"
    feature = "reconciliation"
    label = "Rapprochement banque/ERP"
    description = (
        "Paires flux bancaire + écriture ERP partageant réf/montant/date, avec une part "
        "de désaccords contrôlés — taux d'auto-rapprochement et exceptions vérifiables."
    )
    phase = 1
    param_schema = (
        ParamSpec("pairs", "int", 100, min=1, max=2000),
        ParamSpec("mismatch_ratio", "float", 0.15, min=0.0, max=1.0),
        ParamSpec("mismatch_types", "multi", list(_MISMATCH_TYPES), options=_MISMATCH_TYPES),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        pairs: int = p["pairs"]
        mismatch_types: list[str] = p["mismatch_types"]
        mismatch_count = round(pairs * float(p["mismatch_ratio"]))

        batch = GeneratedBatch()
        account = SimBankAccount(
            iban=test_iban(rng),
            label="Compte courant 1",
            currency="EUR",
            entity=entity_label(target_label, 0),
            balance=money(rng.uniform(50_000, 300_000)),
        )
        batch.records.append(("bank_account", account.model_dump(mode="json")))

        mismatched_pairs: list[dict[str, Any]] = []
        for i in range(pairs):
            ref = f"RECON-{i:05d}"
            amount = rng.uniform(100, 20_000)
            day = today - timedelta(days=rng.randint(0, 29))
            counterparty = rng.choice(COUNTERPARTIES)
            flow = SimCashFlow(
                account_iban=account.iban,
                amount=money(-amount),
                currency="EUR",
                value_date=day,
                direction="debit",
                counterparty=counterparty,
                label=f"Règlement {counterparty}",
                ref=ref,
            )
            batch.records.append(("cash_flow", flow.model_dump(mode="json")))

            mismatch = mismatch_types[i % len(mismatch_types)] if i < mismatch_count else None
            if mismatch == "missing_leg":
                mismatched_pairs.append({"ref": ref, "type": mismatch})
                continue  # ERP leg deliberately omitted
            erp_amount, erp_date = -amount, day
            if mismatch == "amount":
                erp_amount = -(amount + rng.uniform(1.0, 50.0))
            elif mismatch == "date":
                erp_date = day + timedelta(days=3)
            entry = SimErpEntry(
                ref=ref,
                amount=money(erp_amount),
                currency="EUR",
                entry_date=erp_date,
                label=f"Écriture {counterparty}",
                matches_iban=account.iban,
            )
            if mismatch is not None:
                mismatched_pairs.append(
                    {"ref": ref, "type": mismatch, "record_index": len(batch.records)}
                )
            batch.records.append(("financial_transaction", entry.model_dump(mode="json")))

        batch.ground_truth = {
            "expected_auto_match_rate": round((pairs - mismatch_count) / pairs, 4),
            "mismatched_pairs": mismatched_pairs,
        }
        return batch
