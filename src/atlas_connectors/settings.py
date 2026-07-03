"""Runtime settings. Secrets never live here — they are injected from
Secret Manager (DEV) / Vault (target) into the environment at runtime."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    gcp_project: str = "fos-dev-500119"
    canonical_topic: str = "atlas-dev-canonical-records"
