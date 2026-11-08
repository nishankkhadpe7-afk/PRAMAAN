"""Minimal P2 business lifecycle and T00 reconciliation endpoints."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import app as p1
from .upload_safety import UploadSafetyError, content_type, decode_base64
from . import t00

router = APIRouter(prefix="/p2", tags=["P2 business and T00"])


def init_p2(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE IF NOT EXISTS p2_customers(customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, gstin TEXT);
      CREATE TABLE IF NOT EXISTS p2_sales_orders(order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES p2_customers(customer_id), order_date TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_dispatches(dispatch_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES p2_sales_orders(order_id), dispatch_date TEXT NOT NULL, vehicle_no TEXT);
      CREATE TABLE IF NOT EXISTS p2_invoices(invoice_id TEXT PRIMARY KEY, bill_no TEXT NOT NULL UNIQUE, order_id TEXT NOT NULL REFERENCES p2_sales_orders(order_id), dispatch_id TEXT NOT NULL REFERENCES p2_dispatches(dispatch_id), invoice_date TEXT NOT NULL, net_cents INTEGER NOT NULL, tax_cents INTEGER NOT NULL, gross_cents INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_journals(journal_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES p2_invoices(invoice_id), posted INTEGER NOT NULL CHECK(posted=1), reverses TEXT UNIQUE REFERENCES p2_journals(journal_id));
      CREATE TABLE IF NOT EXISTS p2_journal_lines(journal_id TEXT NOT NULL REFERENCES p2_journals(journal_id), line_no INTEGER NOT NULL, account TEXT NOT NULL, debit_cents INTEGER NOT NULL CHECK(debit_cents>=0), credit_cents INTEGER NOT NULL CHECK(credit_cents>=0), CHECK((debit_cents>0 AND credit_cents=0) OR (credit_cents>0 AND debit_cents=0)), PRIMARY KEY(journal_id,line_no));
      CREATE TABLE IF NOT EXISTS p2_journal_reversals(reversal_id TEXT PRIMARY KEY REFERENCES p2_journals(journal_id), reverses TEXT NOT NULL REFERENCES p2_journals(journal_id), reason TEXT NOT NULL CHECK(length(reason) BETWEEN 10 AND 500), actor TEXT NOT NULL);
      CREATE TRIGGER IF NOT EXISTS p2_journal_reversals_no_update BEFORE UPDATE ON p2_journal_reversals BEGIN SELECT RAISE(ABORT,'reversal records are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_journal_reversals_no_delete BEFORE DELETE ON p2_journal_reversals BEGIN SELECT RAISE(ABORT,'reversal records are immutable'); END;
      CREATE TABLE IF NOT EXISTS p2_receipts(receipt_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES p2_invoices(invoice_id), amount_cents INTEGER NOT NULL CHECK(amount_cents>0), value_date TEXT NOT NULL, bank_ref TEXT);
      CREATE TABLE IF NOT EXISTS p2_credit_notes(credit_note_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES p2_invoices(invoice_id), credit_date TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0), reason TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_evidence(evidence_id TEXT PRIMARY KEY, object_type TEXT NOT NULL, object_id TEXT NOT NULL, sha256 TEXT NOT NULL, content_type TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_register_uploads(upload_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, period TEXT NOT NULL, row_count INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_register_rows(upload_id TEXT NOT NULL REFERENCES p2_register_uploads(upload_id), row_no INTEGER NOT NULL, raw_json TEXT NOT NULL, row_hash TEXT NOT NULL, PRIMARY KEY(upload_id,row_no));
      CREATE TABLE IF NOT EXISTS p2_related_party_uploads(upload_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, period TEXT NOT NULL, parsed_json TEXT NOT NULL, comparison_metadata TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_reconciliations(reconciliation_id TEXT PRIMARY KEY, upload_id TEXT NOT NULL REFERENCES p2_register_uploads(upload_id), findings_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p2_reconciliation_rules(reconciliation_id TEXT PRIMARY KEY REFERENCES p2_reconciliations(reconciliation_id), rule_json TEXT NOT NULL, rule_hash TEXT NOT NULL);
      CREATE TRIGGER IF NOT EXISTS p2_reconciliation_rules_no_update BEFORE UPDATE ON p2_reconciliation_rules BEGIN SELECT RAISE(ABORT,'reconciliation rules are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_reconciliation_rules_no_delete BEFORE DELETE ON p2_reconciliation_rules BEGIN SELECT RAISE(ABORT,'reconciliation rules are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_journal_lines_no_update BEFORE UPDATE ON p2_journal_lines BEGIN SELECT RAISE(ABORT,'posted journal lines are immutable; post a reversal'); END;
      CREATE TRIGGER IF NOT EXISTS p2_journal_lines_no_delete BEFORE DELETE ON p2_journal_lines BEGIN SELECT RAISE(ABORT,'posted journal lines are immutable; post a reversal'); END;
      CREATE TRIGGER IF NOT EXISTS p2_journals_no_update BEFORE UPDATE ON p2_journals BEGIN SELECT RAISE(ABORT,'posted journals are immutable; post a reversal'); END;
      CREATE TRIGGER IF NOT EXISTS p2_journals_no_delete BEFORE DELETE ON p2_journals BEGIN SELECT RAISE(ABORT,'posted journals are immutable; post a reversal'); END;
      CREATE TRIGGER IF NOT EXISTS p2_register_uploads_no_update BEFORE UPDATE ON p2_register_uploads BEGIN SELECT RAISE(ABORT,'preserved registers are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_register_uploads_no_delete BEFORE DELETE ON p2_register_uploads BEGIN SELECT RAISE(ABORT,'preserved registers are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_register_rows_no_update BEFORE UPDATE ON p2_register_rows BEGIN SELECT RAISE(ABORT,'preserved register rows are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_register_rows_no_delete BEFORE DELETE ON p2_register_rows BEGIN SELECT RAISE(ABORT,'preserved register rows are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_related_party_uploads_no_update BEFORE UPDATE ON p2_related_party_uploads BEGIN SELECT RAISE(ABORT,'related-party disclosures are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_related_party_uploads_no_delete BEFORE DELETE ON p2_related_party_uploads BEGIN SELECT RAISE(ABORT,'related-party disclosures are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_evidence_no_update BEFORE UPDATE ON p2_evidence BEGIN SELECT RAISE(ABORT,'evidence records are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_evidence_no_delete BEFORE DELETE ON p2_evidence BEGIN SELECT RAISE(ABORT,'evidence records are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_reconciliations_no_update BEFORE UPDATE ON p2_reconciliations BEGIN SELECT RAISE(ABORT,'reconciliations are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p2_reconciliations_no_delete BEFORE DELETE ON p2_reconciliations BEGIN SELECT RAISE(ABORT,'reconciliations are immutable'); END;
    """)


def db_open() -> sqlite3.Connection:
    db = p1.connect()
    from .security import identity
    if identity.get() is not None:
        return db
    init_p2(db)
    return db


def cents(value: Any) -> int:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError("amount must be positive with no more than two decimal places")
        return int(amount * 100)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid monetary amount") from exc


Identifier = Field(min_length=1, max_length=120)


def iso_date(value: str) -> str:
    """Accept only calendar-valid ISO dates (YYYY-MM-DD); stored text stays exactly as given."""
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("must be an ISO date (YYYY-MM-DD)")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be an ISO date (YYYY-MM-DD)") from exc
    return value


def money_amount(value: str) -> str:
    cents(value)  # raises ValueError with a safe message
    return value


class CustomerIn(BaseModel):
    customer_id: str = Identifier
    name: str = Field(min_length=1, max_length=200)
    gstin: str | None = Field(default=None, max_length=20)


class ReceiptIn(BaseModel):
    receipt_id: str = Identifier
    amount: str
    value_date: str
    bank_ref: str | None = Field(default=None, max_length=120)

    check_date = field_validator("value_date")(iso_date)
    check_amount = field_validator("amount")(money_amount)


class CreditNoteIn(BaseModel):
    credit_note_id: str = Identifier
    credit_date: str
    amount: str
    reason: str = Field(min_length=1, max_length=500)

    check_date = field_validator("credit_date")(iso_date)
    check_amount = field_validator("amount")(money_amount)


class EvidenceIn(BaseModel):
    evidence_id: str = Identifier
    content_base64: str
    content_type: str = "application/octet-stream"


class SaleIn(BaseModel):
    order_id: str = Identifier
    dispatch_id: str = Identifier
    invoice_id: str = Identifier
    journal_id: str = Identifier
    customer_id: str = Identifier
    order_date: str
    dispatch_date: str
    invoice_date: str
    bill_no: str = Identifier
    net_amount: str
    tax_amount: str = "0.00"
    vehicle_no: str | None = Field(default=None, max_length=40)
    receipt: ReceiptIn | None = None
    credit_note: CreditNoteIn | None = None
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=50)

    # C1: a single unreadable date used to block every later audit run. Dates must be
    # calendar-valid ISO values; ordering anomalies stay allowed because the audit tests them.
    check_dates = field_validator("order_date", "dispatch_date", "invoice_date")(iso_date)
    check_net = field_validator("net_amount")(money_amount)


class RegisterIn(BaseModel):
    period: str = Field(min_length=1, max_length=120)
    source_base64: str
    # "csv": UTF-8 CSV register. "tally_xml": a TallyPrime / Tally.ERP 9 XML export (Day Book or sales
    # vouchers); its sales vouchers become register rows and the XML itself is the preserved source.
    source_format: Literal["csv", "tally_xml"] = "csv"


class RelatedPartiesIn(BaseModel):
    period: str = Field(min_length=1, max_length=120)
    source_base64: str
    # Optional and advisory only: the stored records are always parsed from the source bytes (H5).
    records: list[dict[str, Any]] | None = None


RELATED_PARTY_PARSER = "rp-source-parser-v1"
TRUE_WORDS, FALSE_WORDS = {"true", "yes", "y", "1"}, {"false", "no", "n", "0", ""}
BOOLEAN_FIELDS = {"related", "related_party", "is_related_party"}
DATE_FIELDS = {"valid_from", "valid_to"}


def _normal_key(key: Any) -> str:
    return "_".join(str(key).strip().lower().split())


def _normal_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if key in BOOLEAN_FIELDS:
            if value.lower() in TRUE_WORDS:
                return True
            if value.lower() in FALSE_WORDS:
                return False
            raise ValueError(f"{key} must be yes/no or true/false")
        if value == "":
            return None
    if key in DATE_FIELDS and value is not None:
        iso_date(value)
    return value


def parse_related_parties(source: bytes) -> list[dict[str, Any]]:
    """Derive related-party records from the preserved source bytes (JSON array or CSV).

    The parsed records, not caller-supplied JSON, are what T01 later tests, so the vault
    hash and the tested records always describe the same disclosure.
    """
    try:
        text = source.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("related-party source must be UTF-8 JSON or CSV") from exc
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("related-party JSON is malformed") from exc
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError("related-party JSON must be an array of objects")
    else:
        try:
            rows = list(csv.DictReader(io.StringIO(text, newline="")))
        except csv.Error as exc:
            raise ValueError("related-party CSV is malformed") from exc
    records = []
    for row in rows:
        record = {}
        for key, value in row.items():
            if key is None:
                raise ValueError("related-party CSV row has more cells than headers")
            name = _normal_key(key)
            record[name] = _normal_value(name, value)
        if any(v not in (None, "") for v in record.values()):
            records.append(record)
    if not records:
        raise ValueError("related-party source contains no records")
    if len(records) > 10000:
        raise ValueError("related-party source exceeds 10,000 records")
    return records


def add_journal(db: sqlite3.Connection, journal_id: str, invoice_id: str, lines: list[tuple[str, int, int]], reverses: str | None = None) -> None:
    if len(lines) < 2 or any(d < 0 or c < 0 or (d > 0) == (c > 0) for _, d, c in lines):
        raise HTTPException(422, "journal needs at least two valid one-sided lines")
    if sum(d for _, d, _ in lines) != sum(c for _, _, c in lines):
        raise HTTPException(422, "journal is not balanced")
    db.execute("INSERT INTO p2_journals VALUES(?,?,1,?)", (journal_id, invoice_id, reverses))
    db.executemany("INSERT INTO p2_journal_lines VALUES(?,?,?,?,?)", [(journal_id, i, account, debit, credit) for i, (account, debit, credit) in enumerate(lines, 1)])


@router.post("/customers")
def create_customer(payload: CustomerIn) -> dict[str, Any]:
    db = db_open()
    try:
        db.execute("INSERT INTO p2_customers VALUES(?,?,?)", (payload.customer_id, payload.name, payload.gstin))
        p1.log_event(db, "client-demo", "customer_created", payload.customer_id, payload.model_dump())
        db.commit()
        return payload.model_dump()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "customer_id already exists") from exc
    finally:
        db.close()


@router.post("/sales")
def create_sale(payload: SaleIn) -> dict[str, Any]:
    try:
        tax_decimal = Decimal(payload.tax_amount)
        if not tax_decimal.is_finite() or tax_decimal < 0:
            raise ValueError("tax amount must be finite and non-negative")
        net, tax = cents(payload.net_amount), cents(tax_decimal) if tax_decimal > 0 else 0
        receipt_cents = cents(payload.receipt.amount) if payload.receipt else None
        credit_cents = cents(payload.credit_note.amount) if payload.credit_note else None
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(422, str(exc)) from exc
    evidence_ids = [e.evidence_id for e in payload.evidence]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise HTTPException(422, "evidence_id values must be unique within the request")
    decoded = []
    for evidence in payload.evidence:
        try:
            decoded.append((evidence, decode_base64(evidence.content_base64, label="evidence"), content_type(evidence.content_type)))
        except UploadSafetyError as exc:
            raise HTTPException(422, "invalid or oversized evidence") from exc
    gross = net + tax
    db = db_open()
    try:
        if not db.execute("SELECT 1 FROM p2_customers WHERE customer_id=?", (payload.customer_id,)).fetchone():
            raise HTTPException(404, "customer not found")
        db.execute("INSERT INTO p2_sales_orders VALUES(?,?,?)", (payload.order_id, payload.customer_id, payload.order_date))
        db.execute("INSERT INTO p2_dispatches VALUES(?,?,?,?)", (payload.dispatch_id, payload.order_id, payload.dispatch_date, payload.vehicle_no))
        db.execute("INSERT INTO p2_invoices VALUES(?,?,?,?,?,?,?,?)", (payload.invoice_id, payload.bill_no, payload.order_id, payload.dispatch_id, payload.invoice_date, net, tax, gross))
        lines = [("Accounts Receivable", gross, 0), ("Sales Revenue", 0, net)]
        if tax:
            lines.append(("Output Tax", 0, tax))
        add_journal(db, payload.journal_id, payload.invoice_id, lines)
        if payload.receipt:
            db.execute("INSERT INTO p2_receipts VALUES(?,?,?,?,?)", (payload.receipt.receipt_id, payload.invoice_id, receipt_cents, payload.receipt.value_date, payload.receipt.bank_ref))
        if payload.credit_note:
            db.execute("INSERT INTO p2_credit_notes VALUES(?,?,?,?,?)", (payload.credit_note.credit_note_id, payload.invoice_id, payload.credit_note.credit_date, credit_cents, payload.credit_note.reason))
        for evidence, content, safe_content_type in decoded:
            db.execute("INSERT INTO p2_evidence VALUES(?,?,?,?,?)", (evidence.evidence_id, "invoice", payload.invoice_id, p1.digest(content), safe_content_type))
        for _, content, _ in decoded:
            p1.store_blob(content)
        result = {"customer_id": payload.customer_id, "order_id": payload.order_id, "dispatch_id": payload.dispatch_id, "invoice_id": payload.invoice_id, "journal_id": payload.journal_id, "gross_amount": f"{gross / 100:.2f}", "evidence_ids": evidence_ids, "receipt_id": payload.receipt.receipt_id if payload.receipt else None, "credit_note_id": payload.credit_note.credit_note_id if payload.credit_note else None}
        p1.log_event(db, "client-demo", "sale_lifecycle_created", payload.invoice_id, result)
        db.commit()
        return result
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "duplicate or invalid lifecycle reference") from exc
    finally:
        db.close()


class ReversalIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reason: str = Field(min_length=10, max_length=500)


@router.post("/journals/{journal_id}/reverse")
def reverse_journal(journal_id: str, body: ReversalIn, reversal_id: str = Query(min_length=1, max_length=120)) -> dict[str, Any]:
    from .security import event_actor, identity
    caller = identity.get()
    if caller is not None and caller.get("channel") == "mcp":
        # Defence in depth: SecurityMiddleware already denies this action on the MCP channel.
        raise HTTPException(403, "DENIED: journal reversal requires an authenticated human session")
    actor = event_actor()
    db = db_open()
    try:
        original = db.execute("SELECT invoice_id FROM p2_journals WHERE journal_id=?", (journal_id,)).fetchone()
        if not original:
            raise HTTPException(404, "journal not found")
        original_lines = db.execute("SELECT account,debit_cents,credit_cents FROM p2_journal_lines WHERE journal_id=? ORDER BY line_no", (journal_id,)).fetchall()
        reverse_lines = [(line["account"], line["credit_cents"], line["debit_cents"]) for line in original_lines]
        add_journal(db, reversal_id, original["invoice_id"], reverse_lines, journal_id)
        db.execute("INSERT INTO p2_journal_reversals(reversal_id,reverses,reason,actor) VALUES(?,?,?,?)", (reversal_id, journal_id, body.reason, actor))
        p1.log_event(db, actor, "journal_reversed", reversal_id, {"reverses": journal_id, "reason": body.reason})
        db.commit()
        return {"journal_id": reversal_id, "reverses": journal_id, "balanced": True}
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "journal already reversed or reversal_id exists") from exc
    finally:
        db.close()


@router.post("/registers")
def upload_register(payload: RegisterIn) -> dict[str, Any]:
    report: dict[str, Any] = {}
    try:
        source = decode_base64(payload.source_base64, label="register source")
    except UploadSafetyError as exc:
        raise HTTPException(422, "invalid or oversized register source") from exc
    if payload.source_format == "tally_xml":
        from .document_import import DocumentReadError, parse_tally_sales
        try:
            read = parse_tally_sales(source)
        except DocumentReadError as exc:
            raise HTTPException(422, f"Tally import: {exc}") from exc
        rows = read["rows"]
        report = {"source_format": "tally_xml", "parser": read["parser"], "vouchers_seen": read["vouchers_seen"],
                  "skipped_vouchers": len(read["skipped"]), "skipped": read["skipped"][:50]}
        if not rows:
            raise HTTPException(422, f"Tally import: no usable sales vouchers among {read['vouchers_seen']} vouchers")
    else:
        try:
            text = source.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text, newline="")))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise HTTPException(422, "register must be base64-encoded UTF-8 CSV with a header") from exc
        if not rows:
            raise HTTPException(422, "register contains no data rows")
    sha = p1.store_blob(source)
    upload_id = "REG-" + uuid.uuid4().hex[:12]
    db = db_open()
    try:
        db.execute("INSERT INTO p2_register_uploads VALUES(?,?,?,?)", (upload_id, sha, payload.period, len(rows)))
        for row_no, row in enumerate(rows, 1):
            row_json = p1.canonical(row).decode()
            db.execute("INSERT INTO p2_register_rows VALUES(?,?,?,?)", (upload_id, row_no, row_json, p1.digest(row_json.encode())))
        p1.log_event(db, "auditor-demo", "register_imported", upload_id, {"sha256": sha, "row_count": len(rows), **{k: v for k, v in report.items() if k != "skipped"}})
        db.commit()
        return {"upload_id": upload_id, "sha256": sha, "row_count": len(rows), **report}
    finally:
        db.close()


@router.post("/related-parties")
def upload_related_parties(payload: RelatedPartiesIn) -> dict[str, Any]:
    try:
        source = decode_base64(payload.source_base64, label="related-party source")
    except UploadSafetyError as exc:
        raise HTTPException(422, "invalid or oversized related-party source") from exc
    try:
        records = parse_related_parties(source)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if payload.records is not None:
        supplied = [{_normal_key(k): v for k, v in r.items()} for r in payload.records]
        try:
            supplied = [{k: _normal_value(k, v) for k, v in r.items()} for r in supplied]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if p1.canonical(supplied) != p1.canonical(records):
            raise HTTPException(422, "records do not match the uploaded source file; the source is the record of disclosure")
    sha = p1.digest(source)
    upload_id = "RP-" + uuid.uuid4().hex[:12]
    metadata = {"parsed_row_count": len(records), "content_sha256": sha, "parser": RELATED_PARTY_PARSER, "comparison": "not run in P2"}
    db = db_open()
    try:
        db.execute("INSERT INTO p2_related_party_uploads VALUES(?,?,?,?,?)", (upload_id, sha, payload.period, p1.canonical(records).decode(), p1.canonical(metadata).decode()))
        p1.store_blob(source)
        p1.log_event(db, "auditor-demo", "related_parties_imported", upload_id, metadata)
        db.commit()
        return {"upload_id": upload_id, **metadata}
    finally:
        db.close()


def money_text(cents_value: int) -> str:
    return f"{Decimal(cents_value) / Decimal(100):.2f}"


@router.post("/registers/{upload_id}/reconcile")
def reconcile_register(upload_id: str) -> dict[str, Any]:
    db = db_open()
    try:
        upload = db.execute("SELECT * FROM p2_register_uploads WHERE upload_id=?", (upload_id,)).fetchone()
        if not upload:
            raise HTTPException(404, "register upload not found")
        rows = db.execute("SELECT row_no,raw_json FROM p2_register_rows WHERE upload_id=? ORDER BY row_no", (upload_id,)).fetchall()
        invoices = db.execute("SELECT i.*,c.name customer_name,c.gstin FROM p2_invoices i JOIN p2_sales_orders o USING(order_id) JOIN p2_customers c USING(customer_id) ORDER BY i.bill_no").fetchall()
        by_bill = {row["bill_no"]: row for row in invoices}
        found_bills = set()
        findings = []
        rule_hash = p1.digest(p1.canonical(t00.RULE))
        compared = {"Bill No": "bill_no", "Date": "invoice_date", "Customer": "customer_name", "Gross Amt": "gross_cents", "GST No": "gstin"}
        for row in rows:
            raw = json.loads(row["raw_json"])
            bill = raw.get("Bill No", raw.get("bill_no", ""))
            invoice = by_bill.get(bill)
            if invoice is None:
                missing_bill = t00.normalize("Bill No", bill)["status"] != "VALID"
                category = "PARSE_REVIEW" if missing_bill else "REGISTER_ONLY"
                findings.append({"finding_id": f"T00-v2-{upload_id}-{row['row_no']}-{category}", "test_id": "T00", "category": category, "row_no": row["row_no"], "bill_no": bill, "field_differences": [], "reason": "Missing invoice identifier; matching unavailable." if missing_bill else "Register row has no matching system invoice."})
                continue
            found_bills.add(bill)
            differences = []
            parse_reviews = []
            for register_field, invoice_field in compared.items():
                register_value = raw.get(register_field)
                system_value = money_text(invoice[invoice_field]) if invoice_field == "gross_cents" else invoice[invoice_field]
                comparison = t00.compare(register_field, register_value, system_value)
                if comparison["comparison"] == "DIFFERENT":
                    differences.append(comparison)
                elif comparison["comparison"] == "PARSE_REVIEW":
                    parse_reviews.append(comparison)
            if differences:
                findings.append({"finding_id": f"T00-v2-{upload_id}-{row['row_no']}-FIELD_DIFF", "test_id": "T00", "category": "FIELD_DIFF", "row_no": row["row_no"], "bill_no": bill, "field_differences": differences, "reason": "Normalized register values differ from the matched system invoice: " + ", ".join(d["field"] for d in differences) + "."})
            if parse_reviews:
                findings.append({"finding_id": f"T00-v2-{upload_id}-{row['row_no']}-PARSE_REVIEW", "test_id": "T00", "category": "PARSE_REVIEW", "row_no": row["row_no"], "bill_no": bill, "field_differences": parse_reviews, "reason": "Missing or invalid comparison inputs; review required, not a confirmed discrepancy."})
        for invoice in invoices:
            if invoice["bill_no"] not in found_bills:
                findings.append({"finding_id": f"T00-v2-{upload_id}-{invoice['invoice_id']}-SOR_ONLY", "test_id": "T00", "category": "SYSTEM_ONLY", "bill_no": invoice["bill_no"], "field_differences": [], "reason": "System invoice is absent from the uploaded register."})
        for finding in findings:
            finding.update({"ruleset_version": t00.RULE["version"], "ruleset_hash": rule_hash})
        reconciliation_id = "T00-" + p1.digest(p1.canonical([upload_id, rule_hash, findings]))[:12]
        db.execute("INSERT OR IGNORE INTO p2_reconciliations VALUES(?,?,?)", (reconciliation_id, upload_id, p1.canonical(findings).decode()))
        db.execute("INSERT OR IGNORE INTO p2_reconciliation_rules VALUES(?,?,?)", (reconciliation_id, p1.canonical(t00.RULE).decode(), rule_hash))
        p1.log_event(db, "auditor-demo", "register_reconciled", reconciliation_id, {"upload_id": upload_id, "finding_count": len(findings), "ruleset_version": t00.RULE["version"], "ruleset_hash": rule_hash})
        db.commit()
        return {"reconciliation_id": reconciliation_id, "upload_id": upload_id, "source_sha256": upload["sha256"], "ruleset": t00.RULE, "ruleset_version": t00.RULE["version"], "ruleset_hash": rule_hash, "findings": findings}
    finally:
        db.close()


@router.get("/journals/{journal_id}")
def get_journal(journal_id: str) -> dict[str, Any]:
    db = db_open()
    try:
        journal = db.execute("SELECT * FROM p2_journals WHERE journal_id=?", (journal_id,)).fetchone()
        if not journal:
            raise HTTPException(404, "journal not found")
        lines = [dict(row) for row in db.execute("SELECT * FROM p2_journal_lines WHERE journal_id=? ORDER BY line_no", (journal_id,))]
        try:
            record = db.execute("SELECT reason,actor FROM p2_journal_reversals WHERE reversal_id=?", (journal_id,)).fetchone()
        except sqlite3.OperationalError:
            record = None
        return {"journal_id": journal_id, "invoice_id": journal["invoice_id"], "posted": bool(journal["posted"]), "reverses": journal["reverses"], "reversal": dict(record) if record else None, "lines": lines, "balanced": sum(x["debit_cents"] for x in lines) == sum(x["credit_cents"] for x in lines)}
    finally:
        db.close()
