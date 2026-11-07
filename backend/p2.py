"""Minimal P2 business lifecycle and T00 reconciliation endpoints."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

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


class CustomerIn(BaseModel):
    customer_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    gstin: str | None = None


class ReceiptIn(BaseModel):
    receipt_id: str
    amount: str
    value_date: str
    bank_ref: str | None = None


class CreditNoteIn(BaseModel):
    credit_note_id: str
    credit_date: str
    amount: str
    reason: str


class EvidenceIn(BaseModel):
    evidence_id: str
    content_base64: str
    content_type: str = "application/octet-stream"


class SaleIn(BaseModel):
    order_id: str
    dispatch_id: str
    invoice_id: str
    journal_id: str
    customer_id: str
    order_date: str
    dispatch_date: str
    invoice_date: str
    bill_no: str
    net_amount: str
    tax_amount: str = "0.00"
    vehicle_no: str | None = None
    receipt: ReceiptIn | None = None
    credit_note: CreditNoteIn | None = None
    evidence: list[EvidenceIn] = Field(default_factory=list)


class RegisterIn(BaseModel):
    period: str
    source_base64: str


class RelatedPartiesIn(BaseModel):
    period: str
    source_base64: str
    records: list[dict[str, Any]]


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
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(422, str(exc)) from exc
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
            db.execute("INSERT INTO p2_receipts VALUES(?,?,?,?,?)", (payload.receipt.receipt_id, payload.invoice_id, cents(payload.receipt.amount), payload.receipt.value_date, payload.receipt.bank_ref))
        if payload.credit_note:
            db.execute("INSERT INTO p2_credit_notes VALUES(?,?,?,?,?)", (payload.credit_note.credit_note_id, payload.invoice_id, payload.credit_note.credit_date, cents(payload.credit_note.amount), payload.credit_note.reason))
        evidence_ids = []
        for evidence in payload.evidence:
            try:
                content = decode_base64(evidence.content_base64, label="evidence")
                safe_content_type = content_type(evidence.content_type)
            except UploadSafetyError as exc:
                raise HTTPException(422, "invalid or oversized evidence") from exc
            sha = p1.digest(content)
            (p1.VAULT / sha).write_bytes(content)
            db.execute("INSERT INTO p2_evidence VALUES(?,?,?,?,?)", (evidence.evidence_id, "invoice", payload.invoice_id, sha, safe_content_type))
            evidence_ids.append(evidence.evidence_id)
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
    try:
        source = decode_base64(payload.source_base64, label="register source")
        text = source.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
    except (UploadSafetyError, UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(422, "register must be base64-encoded UTF-8 CSV with a header") from exc
    if not rows:
        raise HTTPException(422, "register contains no data rows")
    sha = p1.digest(source)
    (p1.VAULT / sha).write_bytes(source)
    upload_id = "REG-" + uuid.uuid4().hex[:12]
    db = db_open()
    try:
        db.execute("INSERT INTO p2_register_uploads VALUES(?,?,?,?)", (upload_id, sha, payload.period, len(rows)))
        for row_no, row in enumerate(rows, 1):
            row_json = p1.canonical(row).decode()
            db.execute("INSERT INTO p2_register_rows VALUES(?,?,?,?)", (upload_id, row_no, row_json, p1.digest(row_json.encode())))
        p1.log_event(db, "auditor-demo", "register_imported", upload_id, {"sha256": sha, "row_count": len(rows)})
        db.commit()
        return {"upload_id": upload_id, "sha256": sha, "row_count": len(rows)}
    finally:
        db.close()


@router.post("/related-parties")
def upload_related_parties(payload: RelatedPartiesIn) -> dict[str, Any]:
    try:
        source = decode_base64(payload.source_base64, label="related-party source")
    except UploadSafetyError as exc:
        raise HTTPException(422, "invalid or oversized related-party source") from exc
    sha = p1.digest(source)
    (p1.VAULT / sha).write_bytes(source)
    upload_id = "RP-" + uuid.uuid4().hex[:12]
    metadata = {"parsed_row_count": len(payload.records), "content_sha256": sha, "comparison": "not run in P2"}
    db = db_open()
    try:
        db.execute("INSERT INTO p2_related_party_uploads VALUES(?,?,?,?,?)", (upload_id, sha, payload.period, p1.canonical(payload.records).decode(), p1.canonical(metadata).decode()))
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
