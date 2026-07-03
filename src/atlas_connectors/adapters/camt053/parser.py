"""Minimal camt.053 parsing — balances from a bank end-of-day statement.

v0.1 scope (per README): camt.053 is one of the two first sources. This module
parses the closing-booked balance (CLBD) per account statement into RawRecords.
Full statement/transaction parsing lands with Slice 2 (file ingestion over EBICS).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from atlas_connectors.kernel.base import RawRecord

# camt.053.001.x namespaces vary by version; match on local-name via wildcard.
_NS_WILDCARD = "{*}"


def _find_text(el: ET.Element, path: str) -> str | None:
    node = el.find(path)
    return node.text if node is not None else None


def parse_balances(raw_xml: bytes, *, source_message_id: str | None = None) -> list[RawRecord]:
    """Parse closing-booked (CLBD) balances from a camt.053 document.

    Returns one RawRecord per statement carrying {iban, amount, currency,
    balance_type}. Anything malformed raises — the runner routes poison files
    to the DLQ; we never guess at financial data.
    """
    root = ET.fromstring(raw_xml)
    stmts = root.findall(f".//{_NS_WILDCARD}Stmt")
    records: list[RawRecord] = []

    for stmt in stmts:
        stmt_id = _find_text(stmt, f"{_NS_WILDCARD}Id") or "unknown-stmt"
        iban = _find_text(stmt, f"{_NS_WILDCARD}Acct/{_NS_WILDCARD}Id/{_NS_WILDCARD}IBAN")

        for bal in stmt.findall(f"{_NS_WILDCARD}Bal"):
            code = _find_text(
                bal, f"{_NS_WILDCARD}Tp/{_NS_WILDCARD}CdOrPrtry/{_NS_WILDCARD}Cd"
            )
            if code != "CLBD":  # closing booked only, v0.1
                continue
            amt_el = bal.find(f"{_NS_WILDCARD}Amt")
            if amt_el is None or amt_el.text is None or iban is None:
                raise ValueError(f"camt.053 statement {stmt_id}: missing IBAN or CLBD amount")

            payload: dict[str, Any] = {
                "iban": iban,
                "amount": amt_el.text,
                "currency": amt_el.get("Ccy"),
                "balance_type": "closing_booked",
                "statement_id": stmt_id,
            }
            records.append(
                RawRecord(
                    source_system="camt053",
                    source_message_id=source_message_id or stmt_id,
                    record_type="bank_balance",
                    payload=payload,
                    raw_bytes=raw_xml,
                )
            )
    return records
