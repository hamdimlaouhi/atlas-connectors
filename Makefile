.PHONY: install test lint simulate run-sim

install:
	pip install -e ".[dev,dev-gcp,service]"

test:
	pytest -q

lint:
	ruff check src tests
	mypy src

# Dry-run: 3 records for a throwaway tenant, printed to stdout.
simulate:
	atlas-simulate --count 3 --tenant 00000000-0000-4000-8000-000000000001 --stdout

# Sim connector service (the Simulation console engine) on :8095, gate open,
# HTTP-push mode toward a local Core. Fail-closed by default without these envs.
run-sim:
	ATLAS_SIM_ENABLED=true ATLAS_SIM_ENVIRONMENT=dev \
	ATLAS_SIM_CORE_INGEST_URL=http://localhost:8000 \
	atlas-sim-service
