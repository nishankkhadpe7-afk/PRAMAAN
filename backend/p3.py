"""P3 deterministic audit checks, sampling, and evidence-request loop."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import app as p1
from . import p3_dataset
from . import p3_crypto
from .upload_safety import UploadSafetyError, content_type, decode_base64

router = APIRouter(prefix="/p3", tags=["P3 audit, sampling, evidence requests"])
RULESET_PATH = Path(__file__).with_name("p3_ruleset.yaml")
SAMPLER_VERSION = "p3-hash-ranked-v1"


def db_open() -> sqlite3.Connection:
    db = p1.connect()
    from .security import identity
    if identity.get() is not None:
        return db
    from .p2 import init_p2
    init_p2(db)
    p3_dataset.init_dataset(db)
    db.executescript("""
      CREATE TABLE IF NOT EXISTS p3_audit_runs(run_id TEXT PRIMARY KEY, snapshot_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL, ruleset_json TEXT NOT NULL, ruleset_version TEXT NOT NULL, sampler_version TEXT NOT NULL, sampling_seed TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, result_json TEXT NOT NULL, rerun_of TEXT);
      CREATE TABLE IF NOT EXISTS p3_audit_labels(run_id TEXT PRIMARY KEY REFERENCES p3_audit_runs(run_id), audit_name TEXT NOT NULL, selected_upload_id TEXT);
      CREATE TABLE IF NOT EXISTS p3_samples(run_id TEXT NOT NULL, sheet TEXT NOT NULL, item_no INTEGER NOT NULL, object_ref TEXT NOT NULL, stratum TEXT NOT NULL, selection_reason TEXT NOT NULL, random_draw TEXT, inclusion_probability REAL, PRIMARY KEY(run_id,sheet,object_ref));
      CREATE TABLE IF NOT EXISTS p3_draws(run_id TEXT NOT NULL, sheet TEXT NOT NULL, object_ref TEXT NOT NULL, draw TEXT NOT NULL, rank INTEGER NOT NULL, selected INTEGER NOT NULL, PRIMARY KEY(run_id,sheet,object_ref));
      CREATE TABLE IF NOT EXISTS p3_evidence_requests(request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, sheet TEXT NOT NULL, sample_ref TEXT NOT NULL, object_type TEXT NOT NULL, required_docs TEXT NOT NULL, uploaded_docs TEXT NOT NULL, status TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p3_evidence(evidence_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES p3_evidence_requests(request_id), object_type TEXT NOT NULL, object_id TEXT NOT NULL, document_type TEXT NOT NULL, sha256 TEXT NOT NULL, content_type TEXT NOT NULL, controller TEXT NOT NULL, acquisition_channel TEXT NOT NULL, independently_verified INTEGER NOT NULL DEFAULT 0, verification_method TEXT);
    """)
    return db


def load_ruleset() -> dict[str, Any]:
    try:
        value = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
        if not value.get("version") or value.get("sampler_version") != SAMPLER_VERSION:
            raise ValueError("ruleset version or sampler version missing/unsupported")
        sales = value["sales_tod"]
        if not (25 <= int(sales["minimum"]) <= int(sales["target"]) <= int(sales["maximum"]) <= 35):
            raise ValueError("Sales TOD range must be within 25–35")
        if sales["high_value_threshold_classification"] != "synthetic_test_only" or Decimal(str(sales["high_value_threshold_inr"])) <= 0:
            raise ValueError("Sales TOD high-value threshold must be positive and test-only")
        if value["credit_note_tod"]["threshold_classification"] != "synthetic_test_only" or Decimal(str(value["credit_note_tod"]["high_value_threshold_inr"])) <= 0:
            raise ValueError("credit-note high-value threshold must be positive and test-only")
        if value["document_comparison"]["classification"] != "synthetic_test_only":
            raise ValueError("document comparison tolerances must be labeled test-only")
        for field in ("taxable_value_tolerance_inr", "quantity_tolerance"):
            if Decimal(str(value["document_comparison"][field])) < 0:
                raise ValueError(f"document comparison {field} cannot be negative")
        conc = value["period_end_concentration"]
        if int(conc["window_days"]) < 1 or int(conc["minimum_history_months"]) < 1 or Decimal(str(conc["multiple_threshold"])) <= 0 or conc["classification"] != "synthetic_test_only":
            raise ValueError("period-end concentration settings must be positive and test-only")
        if conc["amount_basis"] != "gross_amount":
            raise ValueError("period-end concentration amount basis must be explicit")
        split = value["transaction_splitting"]
        if int(split["window_days"]) < 1 or split["classification"] != "synthetic_test_only" or split["amount_basis"] != "gross_amount":
            raise ValueError("transaction-splitting window must be positive and test-only")
        if value["pricing"]["mapping_classification"] != "synthetic_test_only" or not isinstance(value["pricing"]["hsn_to_item_code"], dict):
            raise ValueError("price mappings must be explicit and test-only")
        if Decimal(str(value["pricing"]["unit_price_tolerance_inr"])) < 0:
            raise ValueError("price unit tolerance cannot be negative")
        t11 = value["t11"]
        if t11["classification"] != "synthetic_test_only":
            raise ValueError("T11 physical-plausibility parameters must be labeled test-only")
        if Decimal(str(t11["max_road_speed_kmph"])) <= 0 or Decimal(str(t11["speed_tolerance_kmph"])) < 0:
            raise ValueError("T11 speed bounds must be positive with a non-negative tolerance")
        if not isinstance(t11["verified_time_sources"], list):
            raise ValueError("T11 verified_time_sources must be a list")
        t13 = value["t13"]
        if t13["key_classification"] not in {"DEMO_IRP_TEST_ONLY", "OFFICIAL_IRP"}:
            raise ValueError("T13 key_classification must be DEMO_IRP_TEST_ONLY or OFFICIAL_IRP")
        if not isinstance(t13.get("trusted_public_key_b64", ""), str) or not t13.get("key_id"):
            raise ValueError("T13 trusted key id and public key (string, may be empty) are required")
        if int(t13["backdating_risk_days"]) < 0:
            raise ValueError("T13 backdating_risk_days cannot be negative")
        return value
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"invalid P3 ruleset: {exc}") from exc


class AuditRunIn(BaseModel):
    period_start: str
    period_end: str
    sampling_seed: str = Field(min_length=16)
    audit_name: str | None = Field(default=None, min_length=3, max_length=120)
    upload_id: str | None = None

    @field_validator("audit_name")
    @classmethod
    def readable_name(cls, value):
        if value is not None:
            value = value.strip()
            if len(value) < 3 or any(ord(char) < 32 for char in value):
                raise ValueError("audit name must contain at least three printable characters")
        return value


def default_audit_name(period_start, period_end):
    start, end = parse_date(period_start), parse_date(period_end)
    if start.month == 4 and start.day == 1 and end == date(start.year + 1, 3, 31):
        return f"Revenue audit - FY {start.year}-{str(end.year)[-2:]}"
    return f"Revenue audit - {start:%d %b %Y} to {end:%d %b %Y}"


def run_details(db, run_id, period_start, period_end):
    label = db.execute("SELECT audit_name,selected_upload_id FROM p3_audit_labels WHERE run_id=?", (run_id,)).fetchone()
    if label:
        return dict(label)
    number = db.execute("SELECT COUNT(*) FROM p3_audit_runs WHERE rowid <= (SELECT rowid FROM p3_audit_runs WHERE run_id=?)", (run_id,)).fetchone()[0]
    return {"audit_name": default_audit_name(period_start, period_end) + f" - Snapshot {number}", "selected_upload_id": None}


def selected_register(snapshot, upload_id=None):
    registers = snapshot.get("register_uploads", [])
    if upload_id:
        register = next((r for r in registers if r["upload_id"] == upload_id), None)
        if register is None:
            raise HTTPException(404, "register not in snapshot")
        return register
    return registers[-1] if registers else None


class EvidenceUploadIn(BaseModel):
    evidence_id: str
    document_type: str
    content_base64: str
    content_type: str = "application/octet-stream"
    controller: str
    acquisition_channel: str


@router.post("/datasets/import")
def import_fixture_dataset() -> dict[str, Any]:
    db = db_open()
    try:
        result = p3_dataset.import_endpoint(p3_dataset.DATA_DIR, db, p1.VAULT)
        return result
    finally:
        db.close()


def _dataset_rows(db: sqlite3.Connection) -> tuple[str | None, dict[str, list[dict[str, Any]]]]:
    dataset = db.execute("SELECT dataset_id FROM p3_dataset_imports ORDER BY imported_at DESC,dataset_id DESC LIMIT 1").fetchone()
    if not dataset:
        return None, {}
    dataset_id = dataset["dataset_id"]
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in p3_dataset.TABLES}
    for row in db.execute("SELECT file_name,record_json FROM p3_dataset_rows WHERE dataset_id=? ORDER BY file_name,row_no", (dataset_id,)):
        grouped[row["file_name"]].append(json.loads(row["record_json"]))
    return dataset_id, grouped


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"date must be ISO YYYY-MM-DD: {value}") from exc


def build_snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    dataset_id, source_rows = _dataset_rows(db)
    dataset_manifest = None
    if dataset_id:
        dataset = db.execute("SELECT manifest_sha256,dataset_version FROM p3_dataset_imports WHERE dataset_id=?", (dataset_id,)).fetchone()
        dataset_manifest = {"dataset_id": dataset_id, "manifest_sha256": dataset["manifest_sha256"], "dataset_version": dataset["dataset_version"], "files": [dict(row) for row in db.execute("SELECT file_name,sha256,byte_count,row_count FROM p3_dataset_files WHERE dataset_id=? ORDER BY file_name", (dataset_id,))]}
    invoices = []
    query = """
      SELECT i.*,o.customer_id,o.order_date,c.name customer_name,c.gstin,
             d.dispatch_id,d.dispatch_date,d.vehicle_no
      FROM p2_invoices i
      JOIN p2_sales_orders o USING(order_id)
      JOIN p2_customers c USING(customer_id)
      LEFT JOIN p2_dispatches d USING(dispatch_id)
      ORDER BY i.invoice_date,i.invoice_id
    """
    for row in db.execute(query):
        record = dict(row)
        record["journal_lines"] = [dict(line) for line in db.execute("SELECT j.journal_id,j.reverses,l.line_no,l.account,l.debit_cents,l.credit_cents FROM p2_journals j JOIN p2_journal_lines l USING(journal_id) WHERE j.invoice_id=? ORDER BY j.journal_id,l.line_no", (row["invoice_id"],))]
        invoices.append(record)
    dispatch_by_invoice = {row["invoice_id"]: row for row in source_rows.get("dispatches.csv", [])}
    journals_by_invoice: dict[str, list[dict[str, Any]]] = {}
    for line in source_rows.get("journal_entries.csv", []):
        if line["invoice_id"]:
            journals_by_invoice.setdefault(line["invoice_id"], []).append(line)
    p2_invoice_ids = {row["invoice_id"] for row in invoices}
    for source in source_rows.get("invoices.csv", []):
        if source["invoice_id"] in p2_invoice_ids:
            raise HTTPException(409, f"P3 fixture invoice ID collides with P2 invoice {source['invoice_id']}")
        dispatch = dispatch_by_invoice.get(source["invoice_id"], {})
        def cents(value: Any) -> int:
            return int(Decimal(str(value)) * 100)
        invoices.append({
            "invoice_id": source["invoice_id"], "bill_no": source["bill_no"], "invoice_date": source["invoice_date"],
            "customer_id": source["customer_id"], "customer_name": source["customer_name"], "gstin": source["buyer_gstin"],
            "gross_cents": cents(source["gross_amount"]), "net_cents": cents(source["taxable_amount"]),
            "tax_cents": cents(Decimal(source["cgst"]) + Decimal(source["sgst"]) + Decimal(source["igst"])),
            "quantity": source["quantity"], "hsn_code": source["hsn_code"], "dispatch_id": dispatch.get("dispatch_id"),
            "dispatch_date": dispatch.get("dispatch_date"), "vehicle_no": dispatch.get("vehicle_no"),
            "journal_lines": journals_by_invoice.get(source["invoice_id"], []), "fixture_source": True,
        })
    credit_notes = [dict(row) for row in db.execute("SELECT n.*,i.bill_no,i.invoice_date,o.customer_id FROM p2_credit_notes n JOIN p2_invoices i USING(invoice_id) JOIN p2_sales_orders o USING(order_id) ORDER BY n.credit_date,n.credit_note_id")]
    p2_evidence = [dict(row) for row in db.execute("SELECT * FROM p2_evidence ORDER BY evidence_id")]
    p3_evidence = [dict(row) for row in db.execute("SELECT * FROM p3_evidence ORDER BY evidence_id")]
    related_upload = db.execute("SELECT upload_id,sha256,period,parsed_json FROM p2_related_party_uploads ORDER BY rowid DESC LIMIT 1").fetchone()
    related = None if related_upload is None else {"upload_id": related_upload["upload_id"], "sha256": related_upload["sha256"], "period": related_upload["period"], "records": json.loads(related_upload["parsed_json"])}
    from .p5 import capture_registers
    registers = capture_registers(db)
    return {"invoices": invoices, "credit_notes": credit_notes, "p2_evidence": p2_evidence, "p3_evidence": p3_evidence, "related_party_upload": related, "dataset_id": dataset_id, "dataset_manifest": dataset_manifest, "source_data": source_rows, "synthetic_fixture": bool(dataset_id), **({"register_uploads": registers} if registers else {})}


def make_finding(test_id: str, object_ref: str, state: str, reason: str, **fields: Any) -> dict[str, Any]:
    finding_id = "F3-" + p1.digest(p1.canonical([test_id, object_ref, state, reason]))[:14]
    return {"finding_id": finding_id, "test_id": test_id, "object_ref": object_ref, "state": state, "reason": reason, "confirmed_exception": False, **fields}


def relationships(snapshot: dict[str, Any], invoice: dict[str, Any]) -> list[dict[str, Any]]:
    upload = snapshot["related_party_upload"]
    result = []
    tx_date = parse_date(invoice["invoice_date"])
    for relation in upload["records"] if upload else []:
        party_id = str(relation.get("customer_id", relation.get("party_id", "")))
        is_related = relation.get("related_party", relation.get("is_related_party", relation.get("related", False)))
        if party_id != invoice["customer_id"] or not is_related:
            continue
        start = parse_date(relation["valid_from"]) if relation.get("valid_from") else None
        end = parse_date(relation["valid_to"]) if relation.get("valid_to") else None
        if (start and tx_date < start) or (end and tx_date > end):
            continue
        result.append({"source_upload_id": upload["upload_id"], "valid_from": relation.get("valid_from"), "valid_to": relation.get("valid_to"), "relationship_type": relation.get("relationship_type", "disclosed")})
    tx_date = parse_date(invoice["invoice_date"])
    for edge in snapshot.get("source_data", {}).get("related_party_edges.csv", []):
        if edge["subject_type"] != "customer" or edge["subject_id"] != invoice["customer_id"] or edge["confidence"] != "disclosed":
            continue
        edge_start = parse_date(edge["valid_from"]) if edge.get("valid_from") else None
        edge_end = parse_date(edge["valid_to"]) if edge.get("valid_to") else None
        if (edge_start and tx_date < edge_start) or (edge_end and tx_date > edge_end):
            continue
        result.append({"source_upload_id": snapshot.get("dataset_id"), "source_ref": edge["source_ref"], "valid_from": edge["valid_from"], "valid_to": edge["valid_to"], "relationship_type": edge["relationship_type"]})
    return result


def detect_cycles(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enumerate elementary directed cycles in the counterparty graph.

    Deterministic: adjacency is sorted, and each cycle is reported once with its
    smallest node as the canonical start (only larger nodes are explored onward).
    """
    adjacency: dict[tuple[str, str], list[tuple[tuple[str, str], dict[str, Any]]]] = {}
    for edge in edges:
        u = (edge["subject_type"], edge["subject_id"])
        v = (edge["object_type"], edge["object_id"])
        adjacency.setdefault(u, []).append((v, edge))
    for node in adjacency:
        adjacency[node].sort(key=lambda item: (item[0], item[1]["edge_id"]))
    cycles: list[dict[str, Any]] = []
    seen: set[frozenset[tuple[str, str]]] = set()

    def walk(start: tuple[str, str], node: tuple[str, str], path_nodes: list[tuple[str, str]], path_edges: list[dict[str, Any]]) -> None:
        for nxt, edge in adjacency.get(node, []):
            if nxt == start and len(path_nodes) >= 2:
                key = frozenset(path_nodes)
                if key not in seen:
                    seen.add(key)
                    cycles.append({"node_refs": [list(n) for n in path_nodes], "node_ids": [n[1] for n in path_nodes],
                                   "path_ids": [n[1] for n in path_nodes] + [start[1]],
                                   "edge_ids": [e["edge_id"] for e in path_edges + [edge]]})
            elif nxt > start and nxt not in path_nodes:
                walk(start, nxt, path_nodes + [nxt], path_edges + [edge])

    for start in sorted(adjacency):
        walk(start, start, [start], [])
    cycles.sort(key=lambda c: (len(c["node_ids"]), c["edge_ids"]))
    return cycles


def calculate(snapshot: dict[str, Any], period_start: str, period_end: str, seed: str, ruleset: dict[str, Any], run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    start, end = parse_date(period_start), parse_date(period_end)
    if start > end:
        raise HTTPException(422, "period_start must not follow period_end")
    invoices = snapshot["invoices"]
    invoice_by_id = {invoice["invoice_id"]: invoice for invoice in invoices}
    findings: list[dict[str, Any]] = []
    related_by_invoice: dict[str, list[dict[str, Any]]] = {}

    # T01: disclosed relationships are dated and sourced; they are classification inputs, not fraud findings.
    for invoice in invoices:
        links = relationships(snapshot, invoice)
        related_by_invoice[invoice["invoice_id"]] = links
        for link in links:
            findings.append(make_finding("T01", invoice["invoice_id"], "DISCLOSED_RELATED_PARTY", "A dated disclosed relationship source identifies this customer on the invoice date; classification is not a fraud conclusion.", customer_id=invoice["customer_id"], source_upload_id=link["source_upload_id"], source_ref=link.get("source_ref"), relationship_type=link["relationship_type"], valid_from=link["valid_from"], valid_to=link["valid_to"]))

    source = snapshot.get("source_data", {})
    edges = source.get("related_party_edges.csv", [])
    for edge in edges:
        if edge["confidence"] != "candidate_requires_review":
            continue
        edge_start = parse_date(edge["valid_from"]) if edge.get("valid_from") else start
        edge_end = parse_date(edge["valid_to"]) if edge.get("valid_to") else end
        if edge_start <= end and edge_end >= start:
            findings.append(make_finding("T02", edge["edge_id"], "REVIEW", "Synthetic related-party edge is a candidate requiring human corroboration; it is not an established relationship or fraud finding.", subject_type=edge["subject_type"], subject_id=edge["subject_id"], object_type=edge["object_type"], object_id=edge["object_id"], relationship_type=edge["relationship_type"], source_ref=edge["source_ref"], confidence=edge["confidence"]))
    # T02 cycle detection: enumerate elementary directed cycles in the counterparty
    # graph (subject -> object). A cycle is a relationship pattern for review, never an
    # automatic fraud conclusion, and weak identifiers alone do not establish a party.
    for cycle in detect_cycles(edges):
        ref = "CYCLE:" + ":".join(cycle["node_ids"])
        findings.append(make_finding("T02", ref, "REVIEW", "A directed cycle exists in the synthetic counterparty graph (" + " -> ".join(cycle["path_ids"]) + "); review the circular pattern without inferring fraud. Weak shared identifiers alone do not establish a related party.", cycle_nodes=cycle["node_refs"], cycle_edge_ids=cycle["edge_ids"], cycle_path=cycle["path_ids"], cycle_length=len(cycle["node_ids"])))

    # T03: without contract/control facts, report a review gap for selected cut-off items; do not infer control from dispatch date.
    pre = sorted((i for i in invoices if parse_date(i["invoice_date"]) <= end), key=lambda i: (i["invoice_date"], i["invoice_id"]))
    post = sorted((i for i in invoices if parse_date(i["invoice_date"]) > end), key=lambda i: (i["invoice_date"], i["invoice_id"]))
    cutoff_cfg = ruleset["cutoff_tod"]
    cutoff_items = [(i, "last-before") for i in pre[-int(cutoff_cfg["before_count"]):]] + [(i, "first-after") for i in post[:int(cutoff_cfg["after_count"])]]
    for invoice, side in cutoff_items:
        findings.append(make_finding("T03", invoice["invoice_id"], "GAP", "No contract-derived transfer-of-control date or approved policy mapping is stored; dispatch/invoice dates alone do not establish the control date.", period_side=side, dispatch_date=invoice["dispatch_date"], invoice_date=invoice["invoice_date"]))

    # T04 checks the system dispatch link. P2 makes this mandatory, so a missing row is usually prevented by the FK.
    for invoice in invoices:
        if not invoice["dispatch_id"] or not invoice["dispatch_date"]:
            findings.append(make_finding("T04", invoice["invoice_id"], "GAP", "Expected dispatch record is missing."))

    # T05: standalone revenue credits are available only from the imported source ledger.
    journals: dict[str, list[dict[str, Any]]] = {}
    for line in source.get("journal_entries.csv", []):
        journals.setdefault(line["journal_id"], []).append(line)
    for journal_id, lines in journals.items():
        unlinked_revenue = [line for line in lines if not line["invoice_id"] and line["account"].casefold() == "sales revenue" and Decimal(line["credit"]) > 0]
        if unlinked_revenue:
            amount = sum((Decimal(line["credit"]) for line in unlinked_revenue), Decimal(0))
            findings.append(make_finding("T05", journal_id, "INCONSISTENT", "Revenue is credited in the supplied journal without an invoice reference; investigate the source and authorization.", revenue_credit=format(amount, "f"), source="synthetic fixture", confirmed_exception=False))

    # T06: imported invoice/dispatch comparisons use the persisted test-only tolerance policy.
    doc_rules = ruleset.get("document_comparison", {})
    source_invoices = {row["invoice_id"]: row for row in source.get("invoices.csv", [])}
    source_dispatches = {row["invoice_id"]: row for row in source.get("dispatches.csv", [])}
    value_tolerance = Decimal(str(doc_rules.get("taxable_value_tolerance_inr", "0")))
    qty_tolerance = Decimal(str(doc_rules.get("quantity_tolerance", "0")))
    for invoice_id, inv in source_invoices.items():
        dsp = source_dispatches.get(invoice_id)
        if not dsp:
            findings.append(make_finding("T06", invoice_id, "GAP", "No dispatch comparison row is available in the imported source data."))
            continue
        differences: dict[str, Any] = {}
        for field, dispatch_field, tolerance in (("taxable_amount", "taxable_value", value_tolerance), ("quantity", "quantity", qty_tolerance)):
            left, right = Decimal(inv[field]), Decimal(dsp[dispatch_field])
            if abs(left - right) > tolerance:
                differences[field] = {"invoice": format(left, "f"), "dispatch": format(right, "f"), "difference": format(abs(left-right), "f"), "tolerance": format(tolerance, "f")}
        if inv["buyer_gstin"] != dsp["gstin"]:
            differences["buyer_gstin"] = {"invoice": inv["buyer_gstin"], "dispatch": dsp["gstin"], "tolerance": "exact"}
        if differences:
            findings.append(make_finding("T06", invoice_id, "INCONSISTENT", "Imported invoice and dispatch fields differ under configured synthetic comparison tolerances.", differences=differences, confirmed_exception=False))

    # T08: compare end-window sales to the supplied historical customer-month averages.
    conc = ruleset.get("period_end_concentration", {})
    conc_days = int(conc.get("window_days", 1))
    window_start = end - timedelta(days=conc_days - 1)
    histories: dict[str, list[dict[str, Any]]] = {}
    for row in source.get("historical_sales.csv", []):
        histories.setdefault(row["customer_id"], []).append(row)
    current_totals: dict[str, Decimal] = {}
    for inv in source_invoices.values():
        inv_date = parse_date(inv["invoice_date"])
        if window_start <= inv_date <= end and inv_date >= start:
            current_totals[inv["customer_id"]] = current_totals.get(inv["customer_id"], Decimal(0)) + Decimal(inv["gross_amount"])
    min_months = int(conc.get("minimum_history_months", 1))
    multiple = Decimal(str(conc.get("multiple_threshold", "0")))
    for customer, total in current_totals.items():
        rows = histories.get(customer, [])
        if len(rows) < min_months:
            continue
        average = sum((Decimal(row["gross_sales"]) for row in rows), Decimal(0)) / len(rows)
        if average > 0 and total > average * multiple:
            findings.append(make_finding("T08", customer, "REVIEW", "Period-end sales exceed the configured test-only multiple of the available historical monthly average; this is a risk signal only.", window_start=window_start.isoformat(), window_end=end.isoformat(), current_gross=format(total, "f"), historical_months=len(rows), historical_monthly_average=format(average, "f"), threshold_multiple=format(multiple, "f"), threshold_classification=conc["classification"], confirmed_exception=False))

    # T10: threshold-splitting patterns are investigation candidates, never intent conclusions.
    split_rules = ruleset.get("transaction_splitting", {})
    split_days = int(split_rules.get("window_days", 0))
    for policy in source.get("threshold_policies.csv", []):
        if policy["rule_type"] != "split_transaction_window_total":
            continue
        if parse_date(policy["effective_from"]) > end or (policy["effective_to"] and parse_date(policy["effective_to"]) < end):
            continue
        threshold = Decimal(policy["threshold_inr"])
        by_customer: dict[str, list[dict[str, Any]]] = {}
        for inv in source_invoices.values():
            if start <= parse_date(inv["invoice_date"]) <= end and Decimal(inv["gross_amount"]) < threshold:
                by_customer.setdefault(inv["customer_id"], []).append(inv)
        for customer, rows in by_customer.items():
            rows.sort(key=lambda row: (row["invoice_date"], row["invoice_id"]))
            for index, first in enumerate(rows):
                for second in rows[index+1:]:
                    gap = (parse_date(second["invoice_date"]) - parse_date(first["invoice_date"])).days
                    if gap <= split_days and Decimal(first["gross_amount"]) + Decimal(second["gross_amount"]) >= threshold:
                        findings.append(make_finding("T10", first["invoice_id"] + ":" + second["invoice_id"], "REVIEW", "Two individually below-threshold invoices for one customer exceed a supplied test-only window total; context and intent are unknown.", customer_id=customer, invoice_ids=[first["invoice_id"], second["invoice_id"]], threshold_inr=format(threshold, "f"), threshold_policy_id=policy["policy_id"], threshold_policy_version=policy["policy_version"], window_days=split_days, threshold_classification=split_rules["classification"], confirmed_exception=False))

    # T11 physical plausibility P1-P5. Inputs are synthetic/unverified, so soft conflicts
    # are INCONSISTENT/GAP for review; a hard speed violation is IMPOSSIBLE only when the
    # timestamp came through a configured verified channel.
    t11 = ruleset["t11"]
    t11_invoices = {row["invoice_id"]: row for row in source.get("invoices.csv", [])}
    routes = source.get("movement_routes.csv", [])
    max_speed = Decimal(str(t11["max_road_speed_kmph"])) + Decimal(str(t11["speed_tolerance_kmph"]))
    verified_sources = set(t11["verified_time_sources"])

    def _ts(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    for route in routes:
        ref = route["invoice_id"]
        depart, arrive = _ts(route.get("depart_ts")), _ts(route.get("arrive_ts"))
        # P4 event order: arrival must not precede departure.
        if depart and arrive and arrive < depart:
            findings.append(make_finding("T11", ref, "INCONSISTENT", "P4 event order: recorded arrival precedes departure for this synthetic movement; human review required.", subcheck="P4_event_order", classification="synthetic_test_only", depart_ts=route["depart_ts"], arrive_ts=route["arrive_ts"], confirmed_exception=False))
        # P1 route/time feasibility: implied road speed against a hard maximum.
        elif depart and arrive and arrive > depart:
            hours = Decimal((arrive - depart).total_seconds()) / Decimal(3600)
            if hours > 0:
                implied = Decimal(route["distance_km"]) / hours
                if implied > max_speed:
                    verified = route.get("event_time_source") in verified_sources
                    state = "IMPOSSIBLE" if verified else "INCONSISTENT"
                    reason = ("P1 route/time: a verified-channel timestamp implies a road speed of "
                              + format(implied, ".1f") + " km/h over " + str(route["distance_km"])
                              + " km, exceeding the configured hard maximum. Treated as IMPOSSIBLE under the test ruleset; in production this requires independently validated telemetry."
                              if verified else
                              "P1 route/time: synthetic log timestamps imply a road speed of "
                              + format(implied, ".1f") + " km/h, exceeding the configured maximum; inputs are unverified, so this is review-only, not an impossibility conclusion.")
                    findings.append(make_finding("T11", ref, state, reason, subcheck="P1_route_time", classification="synthetic_test_only", implied_speed_kmph=format(implied, ".1f"), max_road_speed_kmph=str(t11["max_road_speed_kmph"]), distance_km=route["distance_km"], event_time_source=route.get("event_time_source"), inputs_independently_validated=False, confirmed_exception=False))
        # P3 load estimate: quantity against stated vehicle capacity.
        if Decimal(route["quantity_units"]) > Decimal(route["vehicle_capacity_units"]):
            findings.append(make_finding("T11", ref, "REVIEW", "P3 load estimate: synthetic route quantity exceeds the supplied synthetic vehicle capacity; sources are unverified, so this is review-only, not an impossibility conclusion.", subcheck="P3_load_estimate", classification="synthetic_test_only", quantity_units=route["quantity_units"], vehicle_capacity_units=route["vehicle_capacity_units"], source=route["event_time_source"], confirmed_exception=False))
        # P5 PIN / consignee: delivery consignee's GST state vs the billed party's GST state.
        buyer = t11_invoices.get(ref, {}).get("buyer_gstin") or ""
        consignee = route.get("consignee_gstin") or ""
        if buyer[:2] and consignee[:2] and buyer[:2] != consignee[:2]:
            findings.append(make_finding("T11", ref, "INCONSISTENT", "P5 PIN/consignee: the movement consignee's GST state code differs from the invoice buyer's GST state; delivery destination and billed party disagree, requiring review of place of supply.", subcheck="P5_pin_consignee", classification="synthetic_test_only", consignee_gstin_state=consignee[:2], buyer_gstin_state=buyer[:2], to_pin=route.get("to_pin"), from_pin=route.get("from_pin"), confirmed_exception=False))

    # P2 vehicle overlap: one vehicle on two movements whose time windows overlap.
    by_vehicle: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        if route.get("vehicle_no") and _ts(route.get("depart_ts")) and _ts(route.get("arrive_ts")):
            by_vehicle.setdefault(route["vehicle_no"], []).append(route)
    for vehicle, group in sorted(by_vehicle.items()):
        group.sort(key=lambda r: (r["depart_ts"], r["invoice_id"]))
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                f_start, f_end = _ts(first["depart_ts"]), _ts(first["arrive_ts"])
                s_start, s_end = _ts(second["depart_ts"]), _ts(second["arrive_ts"])
                if f_start <= s_end and s_start <= f_end:
                    pair = sorted([first["invoice_id"], second["invoice_id"]])
                    findings.append(make_finding("T11", ":".join(pair), "INCONSISTENT", "P2 vehicle overlap: vehicle " + vehicle + " appears on two synthetic movements whose time windows overlap; one vehicle cannot be in two places at once. Inputs are unverified; human review required.", subcheck="P2_vehicle_overlap", classification="synthetic_test_only", vehicle_no=vehicle, invoice_ids=pair, confirmed_exception=False))

    # T07 duplicate content across separate invoices is an investigation lead, never a confirmed exception by itself.
    evidence_by_hash: dict[str, list[dict[str, Any]]] = {}
    for evidence in snapshot["p2_evidence"] + snapshot["p3_evidence"]:
        if evidence["object_type"] == "invoice":
            evidence_by_hash.setdefault(evidence["sha256"], []).append(evidence)
    for sha, evidence_items in evidence_by_hash.items():
        invoice_refs = sorted({item["object_id"] for item in evidence_items})
        if len(invoice_refs) > 1:
            findings.append(make_finding("T07", sha, "REVIEW", "The same evidence bytes are associated with multiple invoices; verify whether this is legitimate shared support or a misassociation.", evidence_ids=sorted(item["evidence_id"] for item in evidence_items), invoice_ids=invoice_refs))

    cn_cfg = ruleset["credit_note_tod"]
    post_limit = end + timedelta(days=int(cn_cfg["post_period_days"]))
    for note in snapshot["credit_notes"]:
        credit_date = parse_date(note["credit_date"])
        if end < credit_date <= post_limit and parse_date(note["invoice_date"]) <= end:
            findings.append(make_finding("T09", note["credit_note_id"], "REVIEW", "A credit note was issued after period end against a pre-period invoice; timing alone does not establish an error.", invoice_id=note["invoice_id"], bill_no=note["bill_no"], credit_date=note["credit_date"], amount_cents=note["amount_cents"], reason_detail=note["reason"]))

    # T13: verify a signed e-invoice QR against the configured trusted key (DEMO by
    # default), cross-check the signed fields with the books, and flag registration-timing
    # risk. A later acknowledgement is a risk indicator, never proof; never IMPOSSIBLE.
    t13 = ruleset["t13"]
    t13_invoices = {row["invoice_id"]: row for row in source.get("invoices.csv", [])}
    for status in source.get("invoice_verification_status.csv", []):
        invoice_id = status["invoice_id"]
        envelope = status.get("signed_qr_envelope")
        if envelope:
            inv = t13_invoices.get(invoice_id, {})
            book_fields = {"irn": inv.get("irn"), "bill_no": inv.get("bill_no"), "buyer_gstin": inv.get("buyer_gstin"),
                           "seller_gstin": inv.get("seller_gstin"), "gross_cents": int(Decimal(str(inv.get("gross_amount", "0"))) * 100),
                           "hsn_code": str(inv.get("hsn_code")), "invoice_date": inv.get("invoice_date")}
            verdict = p3_crypto.verify_einvoice(envelope, t13["trusted_public_key_b64"], t13["key_id"], t13["key_classification"],
                                                book_fields, status.get("irn_ack_date"), inv.get("invoice_date"), int(t13["backdating_risk_days"]))
            extra = {key: value for key, value in verdict.items() if key not in {"test_id", "state", "reason"}}
            extra.update(evidence_origin=status["evidence_origin"], irn_present=status["irn_present"], qr_payload_present=status["qr_payload_present"])
            findings.append(make_finding("T13", invoice_id, verdict["state"], verdict["reason"], **extra))
        else:
            state = "UNVERIFIED" if status["signature_check"] == "NOT_PERFORMED" else "UNAVAILABLE"
            findings.append(make_finding("T13", invoice_id, state, "No signed QR payload supplied for this invoice; nothing to verify cryptographically.", irn_present=status["irn_present"], qr_payload_present=status["qr_payload_present"], signature_check=status["signature_check"], registration_timing_check=status["registration_timing_check"], evidence_origin=status["evidence_origin"], externally_verified=False, confirmed_exception=False))

    # T14: compare invoice unit amounts to explicitly mapped fixture price lists; promotions remain review candidates.
    pricing = ruleset.get("pricing", {})
    hsn_to_item = pricing.get("hsn_to_item_code", {})
    price_rows = source.get("price_lists.csv", [])
    for invoice in source_invoices.values():
        item_code = hsn_to_item.get(str(invoice["hsn_code"]))
        if not item_code:
            continue
        inv_date = parse_date(invoice["invoice_date"])
        applicable = [p for p in price_rows if p["item_code"] == item_code and p["customer_id"] == invoice["customer_id"] and parse_date(p["valid_from"]) <= inv_date and (not p["valid_to"] or parse_date(p["valid_to"]) >= inv_date)]
        if not applicable:
            continue
        unit = Decimal(invoice["taxable_amount"]) / Decimal(invoice["quantity"])
        list_price = Decimal(applicable[0]["unit_price"])
        price_tolerance = Decimal(str(pricing["unit_price_tolerance_inr"]))
        if abs(unit - list_price) > price_tolerance:
            findings.append(make_finding("T14", invoice["invoice_id"], "REVIEW", "Observed taxable unit value differs from the effective synthetic price list; verify item mapping and transaction terms.", observed_unit_value=format(unit,"f"), listed_unit_price=format(list_price,"f"), price_list_id=applicable[0]["price_list_id"], item_code=item_code, confirmed_exception=False))
    for promo in source.get("promotions.csv", []):
        if not promo["approval_ref"]:
            findings.append(make_finding("T14", promo["promotion_id"], "REVIEW", "Synthetic promotion has no approval reference. The fixture does not establish whether it was applied to an invoice.", customer_id=promo["customer_id"], item_code=promo["item_code"], valid_from=promo["valid_from"], valid_to=promo["valid_to"], source_type=promo["source_type"], confirmed_exception=False))

    # T15 compares only supplied synthetic return rows; row presence is not official filing verification.
    gstr_rows = source.get("gstr1_rows.csv", [])
    invoice_by_bill = {row["bill_no"]: row for row in source.get("invoices.csv", [])}
    for gstr in gstr_rows:
        invoice = invoice_by_bill[gstr["invoice_no"]]
        comparisons = {"invoice_date": (invoice["invoice_date"], gstr["invoice_date"]), "seller_gstin": (invoice["seller_gstin"], gstr["gstin"]), "buyer_gstin": (invoice["buyer_gstin"], gstr["buyer_gstin"])}
        for field in ("taxable_amount", "cgst", "sgst", "igst", "gross_amount"):
            gfield = {"taxable_amount": "taxable_value", "gross_amount": "gross_value"}.get(field, field)
            comparisons[field] = (Decimal(invoice[field]), Decimal(gstr[gfield]))
        differences = {field: {"books": str(left), "synthetic_return_row": str(right)} for field, (left, right) in comparisons.items() if left != right}
        if differences:
            findings.append(make_finding("T15", invoice["invoice_id"], "REVIEW", "Supplied synthetic GSTR-1 row differs from invoice books; this does not verify filing or establish a tax error.", differences=differences, return_period=gstr["return_period"], source_status=gstr["source_status"], externally_verified=False, confirmed_exception=False))

    # Expose source-specific coverage and external-verification limits in each immutable result.
    coverage = {
        "T01": {"status": "evaluated_disclosed_only", "disclosed_upload_id": snapshot["related_party_upload"]["upload_id"] if snapshot["related_party_upload"] else None, "synthetic_dataset_id": snapshot.get("dataset_id")},
        "T02": {"status": "candidate_edges_and_directed_cycles_evaluated" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["Candidate edges and graph cycles are review-only patterns; no external identity verification is provided and weak shared identifiers alone do not establish a related party."] if snapshot.get("dataset_id") else ["No related-party edge dataset imported."]},
        "T03": {"status": "review_required", "reason": "P2 stores no contract/control-date policy facts."},
        "T04": {"status": "evaluated_for_selected_samples", "limitations": ["Movement-document expectations apply to the configured selected-sample request set; P2 does not identify goods/service sale type or all legal EWB/POD requirements.", "Fixture dispatch document references are synthetic placeholders, not preserved source documents or independently verified movement evidence."]},
        "T05": {"status": "evaluated_imported_journal_rows" if snapshot.get("dataset_id") else "schema_limited", "limitations": ["P2 business journals still require invoice references; the independent imported journal source is synthetic."]},
        "T06": {"status": "evaluated_imported_taxable_value_quantity_gstin" if snapshot.get("dataset_id") else "schema_limited", "limitations": ["No invoice-side vehicle number exists in this fixture, so vehicle identity cannot be compared.", "All fixture records are synthetic and not independently verified."]},
        "T07": {"status": "evaluated_hash_reuse_review_only"},
        "T08": {"status": "evaluated_with_test_only_threshold" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["Configured window and multiple are synthetic test parameters, not audit policy or statutory thresholds.", "Only customers with the configured minimum history are assessed."]},
        "T09": {"status": "evaluated_post_period_90_day_window"},
        "T10": {"status": "evaluated_with_test_only_threshold" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["Threshold policy and time window are synthetic test parameters; review candidates do not imply intent."]},
        "T11": {"status": "physical_plausibility_p1_p5_evaluated" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["P1 route/time, P2 vehicle overlap, P3 load, P4 event order and P5 PIN/consignee are evaluated with explicit test-only speed/capacity assumptions.", "IMPOSSIBLE is emitted only for a hard speed violation on a configured verified-channel timestamp; all other conflicts are INCONSISTENT/REVIEW because the synthetic route facts are unverified."]},
        "T12": {"status": "not_evaluable", "reason": "P3 requested uploads are provenance-tagged but have no assertion mapping or verification workflow; P1 T12 remains separate."},
        "T13": {"status": "demo_signed_qr_adapter_evaluated" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["Signed QR envelopes are verified with real Ed25519 signature checking and field cross-checks, but against a DEMO key labelled " + ruleset["t13"]["key_classification"] + "; this is NOT official NIC/IRP verification.", "A later acknowledgement date is a backdating-risk indicator only, never proof; T13 never emits IMPOSSIBLE.", "Invoices without a signed QR payload remain UNVERIFIED/UNAVAILABLE."]},
        "T14": {"status": "fixture_price_comparison_and_promotion_candidates" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["HSN-to-item mapping is explicit synthetic ruleset configuration.", "Promotion application/discount field is absent; missing approval produces a review candidate only."]},
        "T15": {"status": "synthetic_row_comparison_only" if snapshot.get("dataset_id") else "not_evaluable", "limitations": ["Supplied GSTR rows are synthetic and not evidence that a return was filed or accepted.", "No return completeness claim is made.", "Place-of-supply treatment cannot be determined reliably from this fixture alone."]},
    }

    # Sales TOD: certainty/risk strata first, reserve a random stratum, then fill by seeded hash ranking.
    cfg = ruleset["sales_tod"]
    population = len(invoices)
    target = min(int(cfg["target"]), population)
    finding_map: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        finding_map.setdefault(finding["object_ref"], []).append(finding)
        if finding.get("invoice_id"):
            finding_map.setdefault(finding["invoice_id"], []).append(finding)
    sales_reasons: dict[str, list[str]] = {}
    high_threshold = Decimal(str(cfg["high_value_threshold_inr"])) * 100
    _risk_labels = {
        ("T07", "REVIEW"): "Duplicate document bytes across multiple invoices (T07 — verify shared support or misassociation)",
        ("T07", "INCONSISTENT"): "Duplicate document bytes across multiple invoices (T07 — inconsistency flagged)",
        ("T09", "REVIEW"): "Credit note issued after period end against a pre-period invoice (T09 — timing review required)",
        ("T09", "INCONSISTENT"): "Credit note timing inconsistency flagged (T09)",
    }
    for invoice in invoices:
        ref = invoice["invoice_id"]
        if related_by_invoice.get(ref):
            sales_reasons.setdefault(ref, []).append("Disclosed related-party transaction — classified as related-party exposure (T01)")
        risk = [_risk_labels.get((f["test_id"], f["state"]), f"{f['test_id']}: {f['state']}") for f in finding_map.get(ref, []) if f["test_id"] in {"T07", "T09"} and f["state"] in {"REVIEW", "INCONSISTENT"}]
        if risk:
            sales_reasons.setdefault(ref, []).extend(sorted(set(risk)))
        if Decimal(invoice["gross_cents"]) >= high_threshold:
            sales_reasons.setdefault(ref, []).append(f"High-value transaction at or above INR {cfg['high_value_threshold_inr']} (certainty selection — test-only threshold)")
    priorities = sorted(sales_reasons, key=lambda ref: (0 if any("related-party" in x for x in sales_reasons[ref]) else 1, 0 if any(x.startswith(("T07", "T09")) for x in sales_reasons[ref]) else 1, -invoice_by_id[ref]["gross_cents"], ref))
    random_min = min(int(cfg["random_minimum"]), target)
    certainty_budget = max(0, target - random_min) if population > target else max(0, target - min(random_min, max(0, population - len(priorities))))
    certainty_selected = priorities[:certainty_budget]
    selected_reasons: dict[str, tuple[str, str, str | None, float | None]] = {}
    for ref in certainty_selected:
        selected_reasons[ref] = ("certainty", "; ".join(sales_reasons[ref]), "", None)
    random_population = sorted(set(invoice_by_id) - set(certainty_selected))
    random_count = min(target - len(certainty_selected), len(random_population))
    sales_draws = sorted(((draw_rank(seed, ref), ref) for ref in random_population))
    probability = random_count / len(random_population) if random_population else None
    for rank, (draw, ref) in enumerate(sales_draws):
        selected = rank < random_count
        if selected:
            reason = f"Hash-ranked probability sample; draw rank {rank + 1} of {len(random_population)} remaining eligible items."
            selected_reasons[ref] = ("probability", reason, draw, probability)
    sample_items = [{"sheet": "sales_tod", "object_type": "invoice", "object_ref": ref, "stratum": selected_reasons[ref][0], "selection_reason": selected_reasons[ref][1], "random_draw": selected_reasons[ref][2], "inclusion_probability": selected_reasons[ref][3]} for ref in sorted(selected_reasons, key=lambda x: (invoice_by_id[x]["invoice_date"], x))]
    rp_population = {ref for ref, links in related_by_invoice.items() if links}
    rp_selected = rp_population & set(selected_reasons)

    # Cut-off sheet takes last N before and first M after; reduced populations are explicit.
    for invoice, side in cutoff_items:
        sample_items.append({"sheet": "cutoff_tod", "object_type": "invoice", "object_ref": invoice["invoice_id"], "stratum": side, "selection_reason": f"Cut-off: {side} period end, ordered by invoice date then ID.", "random_draw": None, "inclusion_probability": None})

    # Credit Note TOD: all 90-day post-period CNs, plus high-value and a deterministic random in-period subset.
    notes = snapshot["credit_notes"]
    note_by_id = {n["credit_note_id"]: n for n in notes}
    post_notes = [n for n in notes if end < parse_date(n["credit_date"]) <= post_limit]
    in_period = [n for n in notes if start <= parse_date(n["credit_date"]) <= end]
    cn_target = min(int(cn_cfg["in_period_random_target"]), len(in_period))
    cn_high = [n for n in in_period if Decimal(n["amount_cents"]) >= Decimal(str(cn_cfg["high_value_threshold_inr"])) * 100]
    cn_selected = {n["credit_note_id"]: ("high_value", f"In-period high-value credit note at/above INR {cn_cfg['high_value_threshold_inr']} under a synthetic test-only threshold.", None, None) for n in cn_high}
    remaining_cn = sorted((n["credit_note_id"] for n in in_period if n["credit_note_id"] not in cn_selected))
    cn_draws = sorted((draw_rank(seed, "CN:" + ref), ref) for ref in remaining_cn)
    random_cn_count = min(max(0, cn_target - len(cn_selected)), len(cn_draws))
    cn_probability = random_cn_count / len(cn_draws) if cn_draws else None
    for rank, (draw, ref) in enumerate(cn_draws):
        if rank < random_cn_count:
            cn_selected[ref] = ("probability", f"In-period credit note hash-ranked sample; draw rank {rank + 1} of {len(cn_draws)}.", draw, cn_probability)
    for note in post_notes:
        cn_selected[note["credit_note_id"]] = ("post_period_census", "All credit notes in configured 90-day post-period window.", None, 1.0)
    for ref, (stratum, reason, draw, inclusion) in sorted(cn_selected.items()):
        sample_items.append({"sheet": "credit_note_tod", "object_type": "credit_note", "object_ref": ref, "stratum": stratum, "selection_reason": reason, "random_draw": draw, "inclusion_probability": inclusion})

    # T04 evaluates the versioned movement-document request set for every selected workpaper item.
    typed_evidence = snapshot["p3_evidence"]
    source_dispatches = {row["invoice_id"]: row for row in source.get("dispatches.csv", [])}
    for sample in sample_items:
        if sample["sheet"] not in {"sales_tod", "cutoff_tod"}:
            continue
        required = ruleset["evidence_requests"][sample["sheet"]]
        movement_docs = {doc for doc in required if doc in {"e_way_bill", "lorry_receipt", "proof_of_delivery"}}
        present = {e["document_type"] for e in typed_evidence if e["object_type"] == "invoice" and e["object_id"] == sample["object_ref"]}
        dispatch = source_dispatches.get(sample["object_ref"], {})
        for document_type, field in (("e_way_bill", "eway_bill_no"), ("lorry_receipt", "document_no"), ("proof_of_delivery", "proof_of_delivery")):
            if dispatch.get(field):
                present.add(document_type)
        missing = sorted(movement_docs - present)
        if missing:
            findings.append(make_finding("T04", sample["object_ref"], "GAP", "Expected movement documents are missing from the selected sample: " + ", ".join(missing) + ". Missing records alone do not establish that goods did not move.", missing_documents=missing, sample_sheet=sample["sheet"]))

    probability_selected_refs = {ref for _, ref in sales_draws[:random_count]}
    coverage_report = {
        "sales_tod": {"eligible_population": population, "selected": len(selected_reasons), "target": int(cfg["target"]), "reduced_population": population < int(cfg["minimum"]), "selected_refs": sorted(selected_reasons), "not_selected_refs": sorted(set(invoice_by_id) - set(selected_reasons)), "related_party_eligible": len(rp_population), "related_party_selected": len(rp_selected), "related_party_omitted": sorted(rp_population - rp_selected), "certainty_count": len(certainty_selected), "certainty_refs": sorted(certainty_selected), "certainty_excluded_from_probability_refs": sorted(certainty_selected), "certainty_excluded_from_probability_count": len(certainty_selected), "probability_population": len(random_population), "probability_selected": random_count, "probability_selected_refs": sorted(probability_selected_refs), "probability_not_selected_refs": sorted(set(random_population) - probability_selected_refs), "population_projection_supported": False},
        "cutoff_tod": {"before_population": len(pre), "before_selected": min(len(pre), int(cutoff_cfg["before_count"])), "before_excluded_refs": [i["invoice_id"] for i in pre[:-int(cutoff_cfg["before_count"])]] if len(pre) > int(cutoff_cfg["before_count"]) else [], "after_population": len(post), "after_selected": min(len(post), int(cutoff_cfg["after_count"])), "after_excluded_refs": [i["invoice_id"] for i in post[int(cutoff_cfg["after_count"]):]]},
        "credit_note_tod": {"post_period_window_days": int(cn_cfg["post_period_days"]), "post_period_census_population": len(post_notes), "post_period_selected_refs": sorted(n["credit_note_id"] for n in post_notes), "post_period_outside_window_refs": sorted(n["credit_note_id"] for n in notes if parse_date(n["credit_date"]) > post_limit), "in_period_population": len(in_period), "in_period_selected": len(cn_selected) - len(post_notes), "in_period_not_selected_refs": sorted({n["credit_note_id"] for n in in_period} - set(cn_selected))},
    }
    sales_refs = set(selected_reasons)
    cutoff_refs = {invoice["invoice_id"] for invoice, _ in cutoff_items}
    cn_invoice_refs = {n["invoice_id"] for n in notes if n["credit_note_id"] in cn_selected}
    coverage_report["overlaps"] = {
        "sales_cutoff_invoice_refs": sorted(sales_refs & cutoff_refs),
        "sales_credit_note_invoice_refs": sorted(sales_refs & cn_invoice_refs),
        "cutoff_credit_note_invoice_refs": sorted(cutoff_refs & cn_invoice_refs),
    }
    findings.sort(key=lambda f: (f["test_id"], f["object_ref"], f["finding_id"]))
    manifest = snapshot.get("dataset_manifest")
    result = {"run_id": run_id, "snapshot_hash": p1.digest(p1.canonical(snapshot)), "source_dataset_id": manifest["dataset_id"] if manifest else None, "source_manifest_sha256": manifest["manifest_sha256"] if manifest else None, "ruleset_version": ruleset["version"], "ruleset_hash": p1.digest(p1.canonical(ruleset)), "sampler_version": ruleset["sampler_version"], "sampler_tie_break": "lexicographic draw hash, then object reference; draw=SHA-256(seed UTF-8 + NUL + object reference UTF-8)", "sampling_seed": seed, "period_start": period_start, "period_end": period_end, "findings": findings, "sample_items": sample_items, "coverage": coverage_report, "rule_coverage": coverage}
    draw_rows = [{"sheet": "sales_tod", "object_ref": ref, "draw": draw, "rank": rank, "selected": int(rank < random_count)} for rank, (draw, ref) in enumerate(sales_draws)] + [{"sheet": "credit_note_tod", "object_ref": ref, "draw": draw, "rank": rank, "selected": int(rank < random_cn_count)} for rank, (draw, ref) in enumerate(cn_draws)]
    return result, sample_items, draw_rows


def draw_rank(seed: str, ref: str) -> str:
    return p1.digest((seed + "\0" + ref).encode("utf-8"))


def save_run(db: sqlite3.Connection, snapshot: dict[str, Any], period_start: str, period_end: str, seed: str, ruleset: dict[str, Any], rerun_of: str | None = None) -> dict[str, Any]:
    snapshot_json = p1.canonical(snapshot).decode()
    snapshot_hash = p1.digest(snapshot_json.encode())
    ruleset_json = p1.canonical(ruleset).decode()
    run_id = "P3-" + p1.digest(p1.canonical([snapshot_hash, seed, ruleset["version"], ruleset_json, ruleset["sampler_version"], period_start, period_end]))[:18]
    result, samples, draws = calculate(snapshot, period_start, period_end, seed, ruleset, run_id)
    db.execute("INSERT OR IGNORE INTO p3_audit_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)", (run_id, snapshot_hash, snapshot_json, ruleset_json, ruleset["version"], ruleset["sampler_version"], seed, period_start, period_end, p1.canonical(result).decode(), rerun_of))
    db.execute("DELETE FROM p3_samples WHERE run_id=?", (run_id,))
    db.execute("DELETE FROM p3_draws WHERE run_id=?", (run_id,))
    for index, sample in enumerate(samples, 1):
        db.execute("INSERT INTO p3_samples VALUES(?,?,?,?,?,?,?,?)", (run_id, sample["sheet"], index, sample["object_ref"], sample["stratum"], sample["selection_reason"], sample["random_draw"], sample["inclusion_probability"]))
    for draw in draws:
        db.execute("INSERT INTO p3_draws VALUES(?,?,?,?,?,?)", (run_id, draw["sheet"], draw["object_ref"], draw["draw"], draw["rank"], draw["selected"]))
    for sample in samples:
        docs = ruleset["evidence_requests"][sample["sheet"]]
        request_id = "ER-" + p1.digest(p1.canonical([run_id, sample["sheet"], sample["object_ref"]]))[:16]
        db.execute("INSERT OR IGNORE INTO p3_evidence_requests VALUES(?,?,?,?,?,?,?,?)", (request_id, run_id, sample["sheet"], sample["object_ref"], sample["object_type"], p1.canonical(docs).decode(), "[]", "pending"))
    p1.log_event(db, "auditor-demo", "p3_audit_run_created", run_id, {"snapshot_hash": snapshot_hash, "sampling_seed": seed, "ruleset_version": ruleset["version"], "sampler_version": ruleset["sampler_version"]})
    return result


@router.post("/audit-runs")
def create_audit_run(payload: AuditRunIn) -> dict[str, Any]:
    start, end = parse_date(payload.period_start), parse_date(payload.period_end)
    if start > end:
        raise HTTPException(422, "period_start must not follow period_end")
    ruleset = load_ruleset()
    db = db_open()
    try:
        snapshot = build_snapshot(db)
        register = selected_register(snapshot, payload.upload_id)
        result = save_run(db, snapshot, payload.period_start, payload.period_end, payload.sampling_seed, ruleset)
        if any(r["source_integrity"] != "VALID" for r in snapshot.get("register_uploads", [])):
            raise HTTPException(409, "source register integrity failure")
        name = payload.audit_name or default_audit_name(payload.period_start, payload.period_end)
        db.execute("INSERT OR IGNORE INTO p3_audit_labels VALUES(?,?,?)", (result["run_id"], name, register["upload_id"] if register else None))
        p1.log_event(db, "auditor", "audit_named", result["run_id"], {"audit_name": name, "selected_upload_id": register["upload_id"] if register else None})
        db.commit()
        return result
    finally:
        db.close()


@router.post("/audit-runs/{run_id}/reproduce")
def reproduce_audit_run(run_id: str) -> dict[str, Any]:
    db = db_open()
    try:
        run = db.execute("SELECT * FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "P3 audit run not found")
        snapshot, ruleset = json.loads(run["snapshot_json"]), json.loads(run["ruleset_json"])
        rebuilt, _, _ = calculate(snapshot, run["period_start"], run["period_end"], run["sampling_seed"], ruleset, run_id)
        stored = json.loads(run["result_json"])
        return {"run_id": run_id, "identical": rebuilt == stored, "result": rebuilt}
    finally:
        db.close()


@router.post("/audit-runs/{run_id}/rerun")
def rerun_audit(run_id: str) -> dict[str, Any]:
    ruleset = load_ruleset()
    db = db_open()
    try:
        prior = db.execute("SELECT * FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
        if not prior:
            raise HTTPException(404, "P3 audit run not found")
        snapshot = build_snapshot(db)
        details = run_details(db, run_id, prior["period_start"], prior["period_end"])
        result = save_run(db, snapshot, prior["period_start"], prior["period_end"], prior["sampling_seed"], ruleset, rerun_of=run_id)
        if any(r["source_integrity"] != "VALID" for r in snapshot.get("register_uploads", [])):
            raise HTTPException(409, "source register integrity failure")
        db.execute("INSERT OR IGNORE INTO p3_audit_labels VALUES(?,?,?)", (result["run_id"], details["audit_name"], details["selected_upload_id"]))
        db.commit()
        return result
    finally:
        db.close()


@router.get("/audit-runs/{run_id}/evidence-requests")
def list_evidence_requests(run_id: str) -> dict[str, Any]:
    db = db_open()
    try:
        if not db.execute("SELECT 1 FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone():
            raise HTTPException(404, "P3 audit run not found")
        from .security import identity
        caller = identity.get()
        # Auditors also learn which received documents are already inside this frozen snapshot.
        in_snapshot = None
        if caller and caller.get("role") == "auditor":
            in_snapshot = {e["evidence_id"] for e in json.loads(db.execute("SELECT snapshot_json FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()["snapshot_json"])["p3_evidence"]}
        requests = []
        for row in db.execute("SELECT * FROM p3_evidence_requests WHERE run_id=? ORDER BY sheet,sample_ref", (run_id,)):
            item = dict(row)
            item["required_docs"] = json.loads(item["required_docs"])
            item["uploaded_docs"] = json.loads(item["uploaded_docs"])
            item["evidence"] = [{**dict(r), **({"in_snapshot": r["evidence_id"] in in_snapshot} if in_snapshot is not None else {})} for r in db.execute("SELECT evidence_id,document_type,sha256,content_type,controller,acquisition_channel,independently_verified FROM p3_evidence WHERE object_id=? AND object_type=? ORDER BY evidence_id", (item["sample_ref"], item["object_type"]))]
            requests.append(item)
        return {"run_id": run_id, "requests": requests}
    finally:
        db.close()


@router.post("/evidence-requests/{request_id}/evidence")
def submit_requested_evidence(request_id: str, payload: EvidenceUploadIn) -> dict[str, Any]:
    db = db_open()
    try:
        request = db.execute("SELECT * FROM p3_evidence_requests WHERE request_id=?", (request_id,)).fetchone()
        if not request:
            raise HTTPException(404, "evidence request not found")
        required = json.loads(request["required_docs"])
        if payload.document_type not in required:
            raise HTTPException(422, "document_type is not part of this request")
        if payload.document_type in json.loads(request["uploaded_docs"]):
            raise HTTPException(409, "requested document type already uploaded")
        try:
            content = decode_base64(payload.content_base64, label="evidence")
            safe_content_type = content_type(payload.content_type)
        except UploadSafetyError as exc:
            raise HTTPException(422, "invalid or oversized evidence") from exc
        sha = p1.digest(content)
        (p1.VAULT / sha).write_bytes(content)
        object_id = request["sample_ref"]
        db.execute("INSERT INTO p3_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)", (payload.evidence_id, request_id, request["object_type"], object_id, payload.document_type, sha, safe_content_type, payload.controller, payload.acquisition_channel, 0, None))
        uploaded = sorted(json.loads(request["uploaded_docs"]) + [payload.document_type])
        status = "fulfilled" if set(required) <= set(uploaded) else "partially_fulfilled"
        db.execute("UPDATE p3_evidence_requests SET uploaded_docs=?,status=? WHERE request_id=?", (p1.canonical(uploaded).decode(), status, request_id))
        # The same sale is often sampled by several audit runs. One document satisfies every
        # open request for that object and document type, so the client uploads it only once.
        also_satisfied = []
        for sibling in db.execute("SELECT * FROM p3_evidence_requests WHERE sample_ref=? AND object_type=? AND request_id<>?", (object_id, request["object_type"], request_id)).fetchall():
            sibling_required, sibling_uploaded = json.loads(sibling["required_docs"]), json.loads(sibling["uploaded_docs"])
            if payload.document_type in sibling_required and payload.document_type not in sibling_uploaded:
                sibling_uploaded = sorted(sibling_uploaded + [payload.document_type])
                sibling_status = "fulfilled" if set(sibling_required) <= set(sibling_uploaded) else "partially_fulfilled"
                db.execute("UPDATE p3_evidence_requests SET uploaded_docs=?,status=? WHERE request_id=?", (p1.canonical(sibling_uploaded).decode(), sibling_status, sibling["request_id"]))
                also_satisfied.append(sibling["request_id"])
        p1.log_event(db, "client-demo", "evidence_request_fulfilled" if status == "fulfilled" else "evidence_received", request_id, {"document_type": payload.document_type, "sha256": sha, "independently_verified": False, "also_satisfied_requests": also_satisfied})
        db.commit()
        return {"request_id": request_id, "evidence_id": payload.evidence_id, "sha256": sha, "uploaded_docs": uploaded, "required_docs": required, "status": status, "independently_verified": False, "also_satisfied_requests": also_satisfied}
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "evidence_id already exists or request reference invalid") from exc
    finally:
        db.close()
