"""/sim/v1 routes — presets, dispatch, health. ALL gated fail-closed (G1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from atlas_connectors.kernel.http_push import HttpPushError, HttpPushPublisher
from atlas_connectors.kernel.publisher import PublisherPort
from atlas_connectors.sim_service.emitter import (
    build_canonical_records,
    emit,
    enrich_ground_truth,
)
from atlas_connectors.sim_service.generators import REGISTRY
from atlas_connectors.sim_service.generators.base import defaults
from atlas_connectors.sim_service.models import SIM_MODELS, GeneratedBatch
from atlas_connectors.sim_service.settings import SimSettings, get_settings

_PARIS = ZoneInfo("Europe/Paris")
_PREVIEW_LIMIT = 20


def sim_gate(settings: Annotated[SimSettings, Depends(get_settings)]) -> SimSettings:
    """G1 — fail-closed: every /sim route is 404 unless explicitly enabled AND
    the environment is non-production. Not-found, not forbidden: in production
    the surface must not even admit it exists."""
    if not settings.enabled or settings.environment.lower().startswith("prod"):
        raise HTTPException(status_code=404, detail="Not Found")
    return settings


router = APIRouter(prefix="/sim/v1", dependencies=[Depends(sim_gate)])


def get_publisher(settings: Annotated[SimSettings, Depends(sim_gate)]) -> PublisherPort | None:
    """Publisher binding by settings (D of the conception's SOLID mapping):
    Pub/Sub when a topic is configured, HTTP push otherwise. Overridable in
    tests. None = unconfigured — only an actual emission needs one (503 there),
    a dry_run must stay side-effect-free and publisher-free."""
    if settings.gcp_project and settings.canonical_topic:
        from atlas_connectors.kernel.publisher import PubSubPublisher

        return PubSubPublisher(settings.gcp_project, settings.canonical_topic)
    if settings.core_ingest_url:
        return HttpPushPublisher(settings.core_ingest_url)
    return None


class ManualRecord(BaseModel):
    record_type: str
    payload: dict[str, Any]


class DispatchRequest(BaseModel):
    tenant_id: UUID
    batch_id: UUID
    trace_id: UUID
    mode: Literal["auto", "manual"]
    preset_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int = 42
    payload: list[ManualRecord] | None = None
    dry_run: bool = False
    generated_by: str
    target_label: str = "Société"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/presets")
def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "presetId": gen.preset_id,
            "module": gen.module,
            "feature": gen.feature,
            "label": gen.label,
            "description": gen.description,
            "phase": gen.phase,
            "paramSchema": [spec.as_dict() for spec in gen.param_schema],
            "defaults": defaults(gen.param_schema),
        }
        for gen in REGISTRY.values()
    ]


def _generate_auto(request: DispatchRequest) -> GeneratedBatch:
    if not request.preset_id:
        raise HTTPException(status_code=422, detail="preset_id is required in auto mode")
    generator = REGISTRY.get(request.preset_id)
    if generator is None:
        raise HTTPException(status_code=422, detail=f"unknown preset: {request.preset_id}")
    if generator.phase != 1:  # phase allow-list (spec §9 phase-bleed)
        raise HTTPException(status_code=422, detail=f"preset not in Phase 1: {request.preset_id}")
    today = datetime.now(tz=_PARIS).date()
    return generator.generate(
        request.params, request.seed, request.target_label, today=today
    )


def _validate_manual(request: DispatchRequest) -> GeneratedBatch:
    if not request.payload:
        raise HTTPException(status_code=422, detail="payload is required in manual mode")
    batch = GeneratedBatch()
    errors: list[dict[str, Any]] = []
    for i, item in enumerate(request.payload):
        model = SIM_MODELS.get(item.record_type)
        if model is None:  # feature allow-list: Phase-1 record types only
            errors.append({"index": i, "error": f"record_type not allowed: {item.record_type}"})
            continue
        try:
            validated = model.model_validate(item.payload)
        except ValidationError as exc:
            errors.append(
                {"index": i, "error": exc.errors(include_url=False, include_context=False)}
            )
            continue
        batch.records.append((item.record_type, validated.model_dump(mode="json")))
    if errors:
        raise HTTPException(status_code=422, detail={"invalid_records": errors})
    batch.ground_truth = {"mode": "manual", "expected_records": len(batch.records)}
    return batch


@router.post("/dispatch")
def dispatch(
    request: DispatchRequest,
    settings: Annotated[SimSettings, Depends(sim_gate)],
    publisher: Annotated[PublisherPort | None, Depends(get_publisher)],
) -> dict[str, Any]:
    batch = _generate_auto(request) if request.mode == "auto" else _validate_manual(request)

    if len(batch.records) > settings.max_records_per_run:
        raise HTTPException(
            status_code=422,
            detail=(
                f"batch of {len(batch.records)} records exceeds the cap of "
                f"{settings.max_records_per_run} records per run"
            ),
        )

    if request.dry_run:
        preview = [
            {"record_type": record_type, "payload": payload}
            for record_type, payload in batch.records[:_PREVIEW_LIMIT]
        ]
        return {
            "expected_records": len(batch.records),
            "preview": preview,
            "ground_truth": batch.ground_truth,
        }

    if publisher is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "no publisher configured "
                "(set ATLAS_SIM_CANONICAL_TOPIC or ATLAS_SIM_CORE_INGEST_URL)"
            ),
        )
    records = build_canonical_records(
        batch,
        tenant_id=request.tenant_id,
        trace_id=request.trace_id,
        batch_id=request.batch_id,
        seed=request.seed,
        preset_id=request.preset_id if request.mode == "auto" else None,
        generated_by=request.generated_by,
    )
    try:
        report = emit(records, publisher)
    except HttpPushError as exc:
        raise HTTPException(status_code=502, detail=f"emission failed: {exc}") from exc
    hashes = [entry["source_hash"] for entry in report.source_hashes]
    return {
        "expected_records": report.expected,
        "emitted": report.emitted,
        "rejected": report.rejected,
        "ground_truth": enrich_ground_truth(batch.ground_truth, hashes),
        "source_hashes": report.source_hashes,
    }
