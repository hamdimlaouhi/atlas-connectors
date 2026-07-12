"""`finhub.consolidation.v1` — multi-entity, multi-currency consolidation.

Conception §5: `entities` × `accounts_per_entity` accounts across `currencies`,
one settled flow set. Ground truth: `{expected_entities, expected_total_eur_approx}`
(fixed indicative FX so the cockpit figure is checkable, not authoritative).
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

# Indicative, fixed FX for the *approx* ground truth only — never a product rate.
_EUR_RATE = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "CHF": 1.05}
_FLOWS_PER_ACCOUNT = 5  # "one settled flow set"


@register
class FinhubConsolidationGenerator:
    preset_id = "finhub.consolidation.v1"
    module = "AtlasFinhub"
    feature = "consolidation"
    label = "Consolidation multi-entités"
    description = "Arbre multi-entités et ventilation devises sur le cockpit consolidé."
    phase = 1
    param_schema = (
        ParamSpec("entities", "int", 4, min=1, max=15),
        ParamSpec("accounts_per_entity", "int", 2, min=1, max=10),
        ParamSpec("currencies", "multi", ["EUR", "USD"], options=("EUR", "USD", "GBP", "CHF")),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        n_entities: int = p["entities"]
        per_entity: int = p["accounts_per_entity"]
        currencies: list[str] = p["currencies"]

        batch = GeneratedBatch()
        total_eur = 0.0
        account_index = 0
        for e in range(n_entities):
            entity = entity_label(target_label, e)
            for _ in range(per_entity):
                currency = currencies[account_index % len(currencies)]
                balance = rng.uniform(20_000, 800_000)
                account = SimBankAccount(
                    iban=test_iban(rng),
                    label=f"Compte {currency} {account_index + 1}",
                    currency=currency,
                    entity=entity,
                    balance=money(balance),
                )
                total_eur += float(account.balance) * _EUR_RATE[currency]
                batch.records.append(("bank_account", account.model_dump(mode="json")))
                for _ in range(_FLOWS_PER_ACCOUNT):
                    signed = rng.uniform(100, 20_000) * (1 if rng.random() < 0.6 else -1)
                    flow = SimCashFlow(
                        account_iban=account.iban,
                        amount=money(signed),
                        currency=currency,
                        value_date=today - timedelta(days=rng.randint(0, 29)),
                        direction="credit" if signed >= 0 else "debit",
                        counterparty=rng.choice(COUNTERPARTIES),
                        label="Règlement consolidé",
                        ref=f"CONS-{rng.randint(100000, 999999)}",
                    )
                    batch.records.append(("cash_flow", flow.model_dump(mode="json")))
                account_index += 1

        batch.ground_truth = {
            "expected_entities": n_entities,
            "expected_accounts": n_entities * per_entity,
            "expected_total_eur_approx": round(total_eur, 2),
        }
        return batch
