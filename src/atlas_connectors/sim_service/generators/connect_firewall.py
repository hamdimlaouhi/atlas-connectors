"""`connect.firewall.v1` — data-quality firewall exercise.

Conception §5: `base_flows` good + `round(base_flows * bad_ratio)` bad records
cycled over `defect_types`: `missing_field` (currency stripped),
`incoherent_amount` (non-numeric or absurd 1e15), `dup_source_hash` (re-emit an
earlier good record VERBATIM — the emitter reuses the first occurrence's
source_message_id so the source_hash collides and Core dedupes).

Ground truth: `{expected_quarantined, expected_duplicates, per_record_reason}`.
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
from atlas_connectors.sim_service.models import GeneratedBatch, SimBankAccount, SimCashFlow


@register
class ConnectFirewallGenerator:
    preset_id = "connect.firewall.v1"
    module = "AtlasConnect"
    feature = "firewall"
    label = "Pare-feu qualité"
    description = (
        "Flux valides + enregistrements défectueux (champ manquant, montant incohérent, "
        "doublon source_hash) — la quarantaine et l'idempotence se prouvent."
    )
    phase = 1
    param_schema = (
        ParamSpec("base_flows", "int", 50, min=1, max=2000),
        ParamSpec("bad_ratio", "float", 0.3, min=0.0, max=1.0),
        ParamSpec(
            "defect_types",
            "multi",
            ["missing_field", "incoherent_amount", "dup_source_hash"],
            options=("missing_field", "incoherent_amount", "dup_source_hash"),
        ),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        base_flows: int = p["base_flows"]
        defect_types: list[str] = p["defect_types"]
        bad_count = round(base_flows * float(p["bad_ratio"]))

        batch = GeneratedBatch()
        account = SimBankAccount(
            iban=test_iban(rng),
            label="Compte courant 1",
            currency="EUR",
            entity=entity_label(target_label, 0),
            balance=money(rng.uniform(10_000, 200_000)),
        )
        batch.records.append(("bank_account", account.model_dump(mode="json")))

        good_payloads: list[dict[str, Any]] = []
        for _ in range(base_flows):
            signed = rng.uniform(50, 15_000) * (1 if rng.random() < 0.5 else -1)
            flow = SimCashFlow(
                account_iban=account.iban,
                amount=money(signed),
                currency="EUR",
                value_date=today - timedelta(days=rng.randint(0, 29)),
                direction="credit" if signed >= 0 else "debit",
                counterparty=rng.choice(COUNTERPARTIES),
                label="Règlement",
                ref=f"FW-{rng.randint(100000, 999999)}",
            )
            payload = flow.model_dump(mode="json")
            good_payloads.append(payload)
            batch.records.append(("cash_flow", payload))

        per_record_reason: dict[str, str] = {}
        expected_quarantined = 0
        expected_duplicates = 0
        for k in range(bad_count):
            defect = defect_types[k % len(defect_types)]
            index = len(batch.records)
            if defect == "dup_source_hash":
                # Re-emit an earlier good record verbatim: identical payload ⇒
                # identical canonical JSON ⇒ identical source_hash at the emitter.
                payload = dict(rng.choice(good_payloads))
                expected_duplicates += 1
            else:
                base = dict(rng.choice(good_payloads))
                base["ref"] = f"FW-BAD-{k:04d}"
                if defect == "missing_field":
                    base.pop("currency", None)
                else:  # incoherent_amount
                    base["amount"] = "NOT_A_NUMBER" if k % 2 == 0 else "999999999999999"
                payload = base
                expected_quarantined += 1
            per_record_reason[str(index)] = defect
            batch.records.append(("cash_flow", payload))

        batch.ground_truth = {
            "expected_quarantined": expected_quarantined,
            "expected_duplicates": expected_duplicates,
            "expected_bad": bad_count,
            "per_record_reason": per_record_reason,
        }
        return batch
