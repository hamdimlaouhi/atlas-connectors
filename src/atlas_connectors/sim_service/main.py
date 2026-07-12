"""Sim-service app factory + entrypoint (`atlas-sim-service`).

Minimal by design: trace middleware (echo/mint X-Trace-Id — every hop carries
a trace, workspace doctrine) + the gated /sim/v1 router. Governance (run
registry, roles, ledger) lives in Core's ops module, NOT here — this service
only generates, stamps and publishes, like any connector.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response

from atlas_connectors.sim_service.api import router
from atlas_connectors.sim_service.settings import SimSettings


def _trace_id_of(request: Request) -> str:
    header = request.headers.get("X-Trace-Id", "")
    try:
        return str(UUID(header))
    except ValueError:
        return str(uuid4())


def create_app() -> FastAPI:
    app = FastAPI(title="atlas-connectors — sim service", version="0.1.0")

    @app.middleware("http")
    async def trace_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = _trace_id_of(request)
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    # Liveness only — deliberately outside the gated /sim/v1 surface so the
    # runtime can probe the container even when the sim surface is dark.
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = SimSettings()
    uvicorn.run(app, host="0.0.0.0", port=settings.port)  # noqa: S104 — container binding


if __name__ == "__main__":
    run()
