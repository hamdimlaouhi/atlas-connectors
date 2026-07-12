"""Sim-service runtime settings. Fail-closed by default: `enabled=False`.

Secrets never live here — injected from Secret Manager (DEV) / Vault (target).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SimSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_SIM_", env_file=".env", extra="ignore")

    enabled: bool = False
    environment: str = "dev"
    core_ingest_url: str = ""  # HTTP-push mode (local/demo): Core base URL
    gcp_project: str = ""  # Pub/Sub mode
    canonical_topic: str = ""  # Pub/Sub mode
    max_records_per_run: int = 5000
    port: int = 8095


def get_settings() -> SimSettings:
    """FastAPI dependency seam — override in tests, fresh env read per call."""
    return SimSettings()
