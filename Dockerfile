FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[dev-gcp]"

# Non-root runtime (read-only workers; no shell needed)
RUN useradd --uid 1001 --no-create-home worker
USER worker

# Default: simulator dry-run; the runner entrypoint replaces this per adapter.
ENTRYPOINT ["atlas-simulate"]
CMD ["--help"]
