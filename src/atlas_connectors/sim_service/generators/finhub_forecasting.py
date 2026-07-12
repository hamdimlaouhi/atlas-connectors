"""`finhub.forecasting.v1` — ≥90 days of learnable cash-flow history.

Conception §5: deterministic recurring monthly flows (salaries −, rent −,
subscription −, customer invoices +) + variable daily collections with a
`seasonality` factor and `noise`. Ground truth:
`{days, recurring_series, expected_history_points}`.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Literal

from atlas_connectors.sim_service.generators.base import (
    ParamSpec,
    coerce_params,
    entity_label,
    money,
    register,
    test_iban,
)
from atlas_connectors.sim_service.models import GeneratedBatch, SimBankAccount, SimCashFlow

# (series name, day of month, base amount, direction, counterparty, category)
_Direction = Literal["credit", "debit"]
_RECURRING: tuple[tuple[str, int, float, _Direction, str, str], ...] = (
    ("salaries", 28, -42_000.0, "debit", "Paie Groupe Simulée", "payroll"),
    ("rent", 3, -8_500.0, "debit", "Foncière Simulée", "rent"),
    ("subscription", 5, -1_200.0, "debit", "Logiciels Simulés SAS", "saas"),
    ("customer_invoices", 12, 55_000.0, "credit", "Client Orion SAS", "sales"),
)


def _season_factor(day: date, mode: str) -> float:
    if mode == "weekly":
        return 1.0 + 0.25 * math.sin(2 * math.pi * day.weekday() / 7)
    if mode == "monthly":
        return 1.0 + 0.25 * math.sin(2 * math.pi * (day.day - 1) / 30)
    return 1.0


@register
class FinhubForecastingGenerator:
    preset_id = "finhub.forecasting.v1"
    module = "AtlasFinhub"
    feature = "forecasting"
    label = "Historique prévisionnel"
    description = (
        "≥90 jours d'historique : flux récurrents mensuels + encaissements variables "
        "avec saisonnalité et bruit — la régénération de prévision a de quoi apprendre."
    )
    phase = 1
    param_schema = (
        ParamSpec("days", "int", 120, min=90, max=730),
        ParamSpec("accounts", "int", 3, min=1, max=10),
        ParamSpec("seasonality", "enum", "monthly", options=("none", "weekly", "monthly")),
        ParamSpec("recurring_ratio", "float", 0.6, min=0.0, max=1.0),
        ParamSpec("noise", "float", 0.1, min=0.0, max=1.0),
    )

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch:
        p = coerce_params(self.param_schema, params)
        rng = random.Random(seed)
        days: int = p["days"]  # clamped ≥90 by the schema
        n_accounts: int = p["accounts"]
        seasonality: str = p["seasonality"]
        recurring_ratio: float = p["recurring_ratio"]
        noise: float = p["noise"]

        batch = GeneratedBatch()
        accounts: list[SimBankAccount] = []
        for i in range(n_accounts):
            account = SimBankAccount(
                iban=test_iban(rng),
                label=f"Compte courant {i + 1}",
                currency="EUR",
                entity=entity_label(target_label, i % 2),
                balance=money(rng.uniform(100_000, 400_000)),
            )
            accounts.append(account)
            batch.records.append(("bank_account", account.model_dump(mode="json")))

        # recurring_ratio scales the recurring mass vs the variable mass.
        recurring_scale = 2.0 * recurring_ratio
        variable_scale = 2.0 * (1.0 - recurring_ratio)
        history_points = 0
        start = today - timedelta(days=days - 1)
        main = accounts[0]
        for offset in range(days):
            day = start + timedelta(days=offset)
            # Deterministic monthly recurring flows on their fixed day of month.
            for name, dom, base, direction, counterparty, category in _RECURRING:
                if day.day != dom:
                    continue
                amount = base * recurring_scale
                flow = SimCashFlow(
                    account_iban=main.iban,
                    amount=money(amount),
                    currency="EUR",
                    value_date=day,
                    direction=direction,
                    counterparty=counterparty,
                    label=f"Récurrent {name}",
                    ref=f"REC-{name}-{day.isoformat()}",
                    category_hint=category,
                )
                batch.records.append(("cash_flow", flow.model_dump(mode="json")))
                history_points += 1
            # Variable collections: seasonality × (1 ± noise), on business days.
            if day.weekday() < 5 and variable_scale > 0:
                account = accounts[offset % len(accounts)]
                base_collect = 3_000.0 * variable_scale * _season_factor(day, seasonality)
                amount = base_collect * (1.0 + rng.uniform(-noise, noise))
                flow = SimCashFlow(
                    account_iban=account.iban,
                    amount=money(amount),
                    currency="EUR",
                    value_date=day,
                    direction="credit",
                    counterparty="Encaissements Clients Divers",
                    label="Encaissement variable",
                    ref=f"VAR-{day.isoformat()}-{offset}",
                    category_hint="sales",
                )
                batch.records.append(("cash_flow", flow.model_dump(mode="json")))
                history_points += 1

        batch.ground_truth = {
            "days": days,
            "recurring_series": [name for name, *_ in _RECURRING],
            "expected_history_points": history_points,
        }
        return batch
