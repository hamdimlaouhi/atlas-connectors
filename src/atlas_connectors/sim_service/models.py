"""sim-json record models — the manual-mode validation contract AND the shape
generators emit for *well-formed* records (Atlas_Simulation_Conception §5).

These are SOURCE-format payloads (what a connector hands the pipeline), never
CDM DTOs — normalization stays in Core. Firewall presets intentionally emit
payloads that VIOLATE these models (that is the point); only manual-mode input
and generator "good" records are validated against them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SimRecordType = Literal["bank_account", "cash_flow", "financial_transaction"]


def _require_decimal(value: str, *, signed: bool) -> str:
    try:
        Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal string: {value!r}") from exc
    if not signed and value.strip().startswith("-"):
        raise ValueError(f"must not be negative: {value!r}")
    return value


class SimBankAccount(BaseModel):
    """A synthetic bank account under a synthetic entity (subsidiary)."""

    iban: str = Field(pattern=r"^[A-Z]{2}[0-9A-Z]{12,30}$")
    label: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    entity: str
    balance: str

    @field_validator("balance")
    @classmethod
    def _balance_decimal(cls, value: str) -> str:
        return _require_decimal(value, signed=True)


class SimCashFlow(BaseModel):
    """One bank cash flow. `amount` is a signed decimal string; `booked_at`
    is optional and carries the intraday timestamp (off-hours anomalies)."""

    account_iban: str = Field(pattern=r"^[A-Z]{2}[0-9A-Z]{12,30}$")
    amount: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    value_date: date
    booked_at: datetime | None = None
    direction: Literal["credit", "debit"]
    counterparty: str
    label: str
    ref: str | None = None
    category_hint: str | None = None

    @field_validator("amount")
    @classmethod
    def _amount_decimal(cls, value: str) -> str:
        return _require_decimal(value, signed=True)


class SimErpEntry(BaseModel):
    """One ERP book-entry leg (record_type=financial_transaction)."""

    ref: str
    amount: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    entry_date: date
    label: str
    matches_iban: str | None = None

    @field_validator("amount")
    @classmethod
    def _amount_decimal(cls, value: str) -> str:
        return _require_decimal(value, signed=True)


# record_type → validating model (the manual-mode contract; Phase-1 types only)
SIM_MODELS: dict[str, type[BaseModel]] = {
    "bank_account": SimBankAccount,
    "cash_flow": SimCashFlow,
    "financial_transaction": SimErpEntry,
}


@dataclass
class GeneratedBatch:
    """What every PresetGenerator returns: sim-json records + the ground-truth
    manifest (Conception §5 / Appendix G) so a run doubles as a check."""

    records: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    ground_truth: dict[str, Any] = field(default_factory=dict)
    source_format: str = "json"  # → source_system = f"sim.{source_format}"
