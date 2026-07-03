.PHONY: install test lint simulate

install:
	pip install -e ".[dev,dev-gcp]"

test:
	pytest -q

lint:
	ruff check src tests
	mypy src

# Dry-run: 3 records for a throwaway tenant, printed to stdout.
simulate:
	atlas-simulate --count 3 --tenant 00000000-0000-4000-8000-000000000001 --stdout
