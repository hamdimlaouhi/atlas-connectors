"""PresetGenerator protocol, registry, param schema + shared fabrication helpers.

Determinism doctrine (Conception §2.3): ALL randomness flows through the
`random.Random(seed)` instance a generator creates; dates anchor to the
`today` the dispatcher passes (Europe/Paris date) — identical
`(preset_id, params, seed, today)` ⇒ byte-identical payloads.

No PII (Appendix I): IBANs come from a fabricated test range (FR76 9999…),
counterparty names from a small fabricated list.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

from atlas_connectors.sim_service.models import GeneratedBatch

ParamType = Literal["int", "float", "enum", "multi", "window"]


@dataclass(frozen=True)
class ParamSpec:
    """One form-driving parameter (Appendix D): type + default + clamp range."""

    name: str
    type: ParamType
    default: Any
    min: float | None = None
    max: float | None = None
    options: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "type": self.type, "default": self.default}
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.options is not None:
            out["options"] = list(self.options)
        return out


@runtime_checkable
class PresetGenerator(Protocol):
    """One preset = one class (S of SOLID); pure generate() (L: any entry
    substitutes). The dispatcher stays closed for modification (O)."""

    preset_id: str
    module: str
    feature: str
    label: str
    description: str
    phase: int
    param_schema: tuple[ParamSpec, ...]

    def generate(
        self, params: Mapping[str, Any], seed: int, target_label: str, *, today: date
    ) -> GeneratedBatch: ...


REGISTRY: dict[str, PresetGenerator] = {}

_G = TypeVar("_G", bound=type[Any])


def register(cls: _G) -> _G:
    """Class decorator: instantiate and index the generator by preset_id."""
    gen = cls()
    assert isinstance(gen, PresetGenerator), f"{cls!r} does not satisfy PresetGenerator"
    REGISTRY[gen.preset_id] = gen
    return cls


def defaults(schema: Sequence[ParamSpec]) -> dict[str, Any]:
    return {spec.name: spec.default for spec in schema}


def _clamp(value: float, spec: ParamSpec) -> float:
    if spec.min is not None:
        value = max(value, spec.min)
    if spec.max is not None:
        value = min(value, spec.max)
    return value


def _coerce_window(value: Any, spec: ParamSpec) -> int:
    """A window is a trailing day count: accepts int or "last-<N>d"."""
    days: float
    if isinstance(value, str) and value.startswith("last-") and value.endswith("d"):
        try:
            days = int(value[5:-1])
        except ValueError:
            return _coerce_window(spec.default, spec)
    else:
        try:
            days = int(value)
        except (TypeError, ValueError):
            return _coerce_window(spec.default, spec)
    return int(_clamp(days, spec))


def coerce_params(schema: Sequence[ParamSpec], params: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce + clamp user params against the schema (Conception §7 caps:
    "params clamped by schema"). Unknown keys are dropped; invalid values fall
    back to the default rather than erroring — the schema is the authority."""
    out = defaults(schema)
    for spec in schema:
        if spec.name not in params:
            if spec.type == "window":  # normalize the "last-Nd" default to days
                out[spec.name] = _coerce_window(spec.default, spec)
            continue
        value = params[spec.name]
        if spec.type == "int":
            try:
                out[spec.name] = int(_clamp(int(value), spec))
            except (TypeError, ValueError):
                pass
        elif spec.type == "float":
            try:
                out[spec.name] = float(_clamp(float(value), spec))
            except (TypeError, ValueError):
                pass
        elif spec.type == "enum":
            if spec.options and value in spec.options:
                out[spec.name] = value
        elif spec.type == "multi":
            if isinstance(value, (list, tuple)) and spec.options:
                kept = [v for v in value if v in spec.options]
                if kept:
                    out[spec.name] = kept
        elif spec.type == "window":
            out[spec.name] = _coerce_window(value, spec)
    return out


# ---------------------------------------------------------------------------
# Fabrication helpers (deterministic, PII-free)
# ---------------------------------------------------------------------------

# Fabricated counterparties — no real person or company (Appendix I / DPO).
COUNTERPARTIES: tuple[str, ...] = (
    "Fournitures Nébula SARL",
    "Client Orion SAS",
    "Ateliers du Lys",
    "Distribution Callisto",
    "Services Amarante",
    "Négoce Périclès",
    "Imprimerie Boréale",
    "Transports Zéphyr",
    "Conseil Hélianthe",
    "Matériaux Cassiopée",
)


def test_iban(rng: random.Random) -> str:
    """Fabricated test-range IBAN: FR76 9999… + seeded digits (27 chars)."""
    return "FR7699999" + "".join(str(rng.randint(0, 9)) for _ in range(18))


def money(value: float) -> str:
    """Decimal-string money — payloads carry decimals as strings, never floats."""
    return f"{value:.2f}"


def entity_label(target_label: str, index: int) -> str:
    suffixes = ("Holding", "Filiale Nord", "Filiale Sud", "Filiale Export", "Filiale Services")
    return f"{target_label} {suffixes[index % len(suffixes)]}"
