import pytest

from atlas_connectors.adapters.camt053.parser import parse_balances

CAMT_MINIMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT-2026-001</Id>
      <Acct><Id><IBAN>FR7630006000011234567890189</IBAN></Id></Acct>
      <Bal>
        <Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="EUR">1000.00</Amt>
      </Bal>
      <Bal>
        <Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="EUR">1250.50</Amt>
      </Bal>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""

CAMT_MISSING_IBAN = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT-BAD</Id>
      <Bal>
        <Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="EUR">1.00</Amt>
      </Bal>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""


def test_parses_closing_booked_balance_only() -> None:
    records = parse_balances(CAMT_MINIMAL)
    assert len(records) == 1  # OPBD skipped, CLBD kept
    rec = records[0]
    assert rec.record_type == "bank_balance"
    assert rec.payload == {
        "iban": "FR7630006000011234567890189",
        "amount": "1250.50",
        "currency": "EUR",
        "balance_type": "closing_booked",
        "statement_id": "STMT-2026-001",
    }
    assert rec.source_system == "camt053"
    assert rec.raw_bytes == CAMT_MINIMAL


def test_malformed_statement_raises_never_guesses() -> None:
    """Poison files must raise (→ DLQ), never yield guessed financial data."""
    with pytest.raises(ValueError, match="missing IBAN"):
        parse_balances(CAMT_MISSING_IBAN)
