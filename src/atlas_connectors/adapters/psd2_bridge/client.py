"""BridgeAPI (PSD2 aggregator) connector — Slice 1 (US-020) stub.

Scope when implemented: OAuth bank consent, balances + 7-day transactions,
~4h auto-refresh. Read-only; credentials from Secret Manager / Vault.

TODO(US-020): 90-day consent-expiry handling — Bridge consents lapse after
90 days (PSD2); the adapter must surface expiring consents as events well
before lapse so the product can prompt re-consent, and must treat an expired
consent as a clean stop (no partial pulls), not an error loop.
"""

from __future__ import annotations

from collections.abc import Iterator

from atlas_connectors.kernel.base import RawRecord


class Psd2BridgeConnector:
    """BaseConnector implementation for BridgeAPI. Not yet implemented (Slice 1)."""

    source_system = "psd2_bridge"

    def __init__(self, *, api_base: str = "https://api.bridgeapi.io") -> None:
        self._api_base = api_base

    def extract(self) -> Iterator[RawRecord]:
        raise NotImplementedError(
            "Slice 1 (US-020): balances + 7-day transactions via BridgeAPI sandbox"
        )
