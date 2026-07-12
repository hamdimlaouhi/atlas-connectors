"""`connect.ingestion.v1` — nominal ingestion: accounts + uniform flows.

Conception §5: test-IBAN accounts under 1–2 synthetic entities;
`flows_per_account` flows uniform over `date_range`, mixed signs, `currencies`.
Ground truth: `{expected_accounts, expected_flows}`.
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

_LABELS = ("Virement", "Prélèvement", "Facture", "Règlement", "Encaissement")


@register
class ConnectIngestionGenerator:
    preset_id = "connect.ingestion.v1"
    module = "AtlasConnect"
    feature = "ingestion"
    label = "Ingestion nominale"
    description = "Comptes de test + flux uniformes sur la fenêtre — le pipeline complet s'allume."
    phase = 1
    param_schema = (
        ParamSpec("accounts", "int", 3, min=1, max=20),
        ParamSpec("flows_per_account", "int", 30, min=1, max=500),
        ParamSpec("date_range", "window", "last-90d", min=1, max=365),
        ParamSpec("currencies", "multi", ["EUR"], options=("EUR", "USD", "GBP", "CHF")),
        ParamSpec("source_format", "enum", "psd2", options=("psd2", "camt053", "mt940", "odata")),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        n_accounts: int = p["accounts"]
        flows_per_account: int = p["flows_per_account"]
        window_days: int = p["date_range"]
        currencies: list[str] = p["currencies"]

        batch = GeneratedBatch(source_format=str(p["source_format"]))
        n_entities = 1 if n_accounts == 1 else 2
        accounts: list[SimBankAccount] = []
        for i in range(n_accounts):
            account = SimBankAccount(
                iban=test_iban(rng),
                label=f"Compte courant {i + 1}",
                currency=currencies[i % len(currencies)],
                entity=entity_label(target_label, i % n_entities),
                balance=money(rng.uniform(10_000, 500_000)),
            )
            accounts.append(account)
            batch.records.append(("bank_account", account.model_dump(mode="json")))

        for account in accounts:
            for _ in range(flows_per_account):
                signed = rng.uniform(50, 25_000) * (1 if rng.random() < 0.5 else -1)
                flow = SimCashFlow(
                    account_iban=account.iban,
                    amount=money(signed),
                    currency=account.currency,
                    value_date=today - timedelta(days=rng.randint(0, window_days - 1)),
                    direction="credit" if signed >= 0 else "debit",
                    counterparty=rng.choice(COUNTERPARTIES),
                    label=rng.choice(_LABELS),
                    ref=f"ING-{rng.randint(100000, 999999)}",
                )
                batch.records.append(("cash_flow", flow.model_dump(mode="json")))

        batch.ground_truth = {
            "expected_accounts": n_accounts,
            "expected_flows": n_accounts * flows_per_account,
        }
        return batch
