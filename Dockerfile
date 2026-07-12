FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[dev-gcp,service]"

# Non-root runtime (read-only workers; no shell needed)
RUN useradd --uid 1001 --no-create-home worker
USER worker

# Default: the sim connector service (the Simulation console engine,
# ADR-SIM-001). Gated fail-closed: it answers 404 on every /sim route unless
# ATLAS_SIM_ENABLED=true AND ATLAS_SIM_ENVIRONMENT is non-production.
#
# BREAKING vs the previous image: the default entrypoint was `atlas-simulate`.
# The CLI is still shipped — run it with:
#   docker run --entrypoint atlas-simulate <image> --count 3 --tenant <uuid> --stdout
EXPOSE 8095
ENTRYPOINT ["atlas-sim-service"]
