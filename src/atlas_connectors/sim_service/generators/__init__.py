"""Preset generators — one module per preset, self-registering (O of SOLID:
a new simulation type = one generator class; the dispatcher never changes)."""

from atlas_connectors.sim_service.generators import (  # noqa: F401 — import = register
    connect_firewall,
    connect_ingestion,
    finhub_anomaly,
    finhub_circuit_breaker,
    finhub_consolidation,
    finhub_forecasting,
    finhub_reconciliation,
)
from atlas_connectors.sim_service.generators.base import REGISTRY, PresetGenerator

__all__ = ["REGISTRY", "PresetGenerator"]
