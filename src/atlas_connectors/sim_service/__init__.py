"""Atlas Simulation connector service — the console engine (OPS-C4).

A tiny FastAPI deployable that generates deterministic synthetic source data
(sim-json dialect) per preset and injects it through the REAL connector
kernel — RawRecord → stamp() → CanonicalRecord → PublisherPort — so the
pipeline under test is exercised by its real front door (ADR-SIM-001).
It is a synthetic connector, not test scaffolding.
"""
