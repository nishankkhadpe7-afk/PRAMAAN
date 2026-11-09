"""Snapshot-based workpaper packages and append-only human review history."""
from __future__ import annotations

import base64
import csv
import io
import json
from collections import defaultdict
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict

from . import app as p1, p3
from .security import identity
from .p5_checks import demo_signature, capacity_screen

router = APIRouter(prefix="/p5", tags=["P5 workpapers and human review"])
EXPORT_VERSION = "p5-ooxml-pdf-v1"
T00_RULE = {"version": "p2-t00-v1", "implementation": "existing p2.reconcile_register",
            "fields": ["Bill No", "Date", "Customer", "Gross Amt", "GST No"], "comparison": "exact trimmed text; monetary values formatted from cents"}
ASSERTIONS = {"T00": "completeness", "T01": "classification", "T02": "classification", "T03": "cutoff",
              "T04": "occurrence", "T05": "classification", "T06": "accuracy", "T07": "occurrence",
              "T08": "cutoff", "T09": "cutoff", "T10": "classification", "T11": "occurrence",
              "T12": "occurrence", "T13": "accuracy", "T14": "accuracy", "T15": "accuracy"}
FILES = {"T01": ["invoices.csv", "related_party_edges.csv"], "T02": ["related_party_edges.csv"],
         "T03": ["invoices.csv", "dispatches.csv", "journal_entries.csv"], "T04": ["invoices.csv", "dispatches.csv"],
         "T05": ["journal_entries.csv"], "T06": ["invoices.csv", "dispatches.csv"],
         "T08": ["invoices.csv", "historical_sales.csv"], "T10": ["invoices.csv", "threshold_policies.csv"],
         "T11": ["movement_routes.csv"], "T13": ["invoice_verification_status.csv", "invoices.csv"],
         "T14": ["invoices.csv", "price_lists.csv", "promotions.csv"], "T15": ["invoices.csv", "gstr1_rows.csv"]}
STANDARD_URL = "https://www.icai.org/post/auditing-review-and-other-standards-formerly-known-as-aas-complete-text"
STANDARDS = {key: {"candidate_standard": "SA 550 Related Parties" if key in {"T01", "T02"} else "SA 560 Subsequent Events" if key == "T09" else "SA 500 Audit Evidence",
                   "source": STANDARD_URL, "status": "Candidate mapping; engagement policy and CA review required"} for key in ASSERTIONS}


def init_p5(db):
    db.executescript("""
      CREATE TABLE IF NOT EXISTS p5_reviews(run_id TEXT NOT NULL REFERENCES p3_audit_runs(run_id), finding_id TEXT NOT NULL, revision INTEGER NOT NULL, decision_json TEXT NOT NULL, PRIMARY KEY(run_id,finding_id,revision));
      CREATE TABLE IF NOT EXISTS p5_proposals(seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES p3_audit_runs(run_id), finding_id TEXT NOT NULL, proposal_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p5_packages(package_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES p3_audit_runs(run_id), report_json TEXT NOT NULL, content_hash TEXT NOT NULL);
      CREATE TRIGGER IF NOT EXISTS p5_reviews_no_update BEFORE UPDATE ON p5_reviews BEGIN SELECT RAISE(ABORT,'review history is append-only'); END;
      CREATE TRIGGER IF NOT EXISTS p5_reviews_no_delete BEFORE DELETE ON p5_reviews BEGIN SELECT RAISE(ABORT,'review history is append-only'); END;
      CREATE TRIGGER IF NOT EXISTS p5_proposals_no_update BEFORE UPDATE ON p5_proposals BEGIN SELECT RAISE(ABORT,'proposals are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS p5_proposals_no_delete BEFORE DELETE ON p5_proposals BEGIN SELECT RAISE(ABORT,'proposals are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS p5_packages_no_update BEFORE UPDATE ON p5_packages BEGIN SELECT RAISE(ABORT,'export packages are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS p5_packages_no_delete BEFORE DELETE ON p5_packages BEGIN SELECT RAISE(ABORT,'export packages are immutable'); END;
    """)


def capture_registers(db, inline_sources=False):
    """Freeze register metadata, cells and rows. Source bytes are referenced by SHA-256 in the
    vault (H7); ``inline_sources`` rebuilds the legacy shape for comparing with older snapshots."""
    registers = []
    for row in db.execute("SELECT * FROM p2_register_uploads ORDER BY upload_id"):
        path = p1.VAULT / row["sha256"]
        raw = path.read_bytes() if path.is_file() else b""
        status = "VALID" if path.is_file() and p1.digest(raw) == row["sha256"] else "CHANGED_OR_MISSING"
        try:
            cells = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
        except (UnicodeError, csv.Error):
            cells = []
            status = "INVALID_ENCODING"
        reconciliations = []
        for reconciliation in db.execute("""SELECT * FROM p2_reconciliations WHERE upload_id=? ORDER BY
          COALESCE((SELECT MAX(seq) FROM events WHERE json_extract(event_json,'$.action')='register_reconciled'
            AND json_extract(event_json,'$.object_ref')=p2_reconciliations.reconciliation_id),0), rowid""", (row["upload_id"],)):
            metadata = db.execute("SELECT * FROM p2_reconciliation_rules WHERE reconciliation_id=?", (reconciliation["reconciliation_id"],)).fetchone()
            reconciliations.append({**dict(reconciliation), **({"rule": json.loads(metadata["rule_json"]), "rule_hash": metadata["rule_hash"]} if metadata else {})})
        registers.append({**dict(row), **({"source_base64": base64.b64encode(raw).decode()} if inline_sources else {}), "source_integrity": status,
                          "cells": cells, "metadata_source_rows": [index + 2 for index, cells_row in enumerate(cells[1:]) if cells_row],
                          "parsing_warnings": ["Original cells preserved separately; dictionary metadata may normalize duplicate headers or skip empty rows."],
                          "rows": [dict(r) for r in db.execute("SELECT * FROM p2_register_rows WHERE upload_id=? ORDER BY row_no", (row["upload_id"],))],
                          "reconciliations": reconciliations})
    return registers


def register_bytes(register):
    """Original register bytes: inline in legacy snapshots, otherwise read from the vault and
    verified against the frozen SHA-256 (H7)."""
    if "source_base64" in register:
        raw = base64.b64decode(register["source_base64"])
    else:
        path = p1.VAULT / register["sha256"]
        raw = path.read_bytes() if path.is_file() else b""
    if p1.digest(raw) != register["sha256"]:
        raise HTTPException(409, "snapshot source integrity failure")
    return raw


def stored_run(db, run_id):
    """Load a saved run after verifying it.

    Hashes are re-checked on every load. Full reproduction (re-running every test and the
    sampler) runs once per (run, stored result bytes, engine fingerprint) and its verdict is
    cached (H7); any edit to the stored result or to the engine code forces a recomputation.
    The Integrity tab always recomputes live.
    """
    row = db.execute("SELECT * FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "audit run not found")
    snapshot, result, rules = json.loads(row["snapshot_json"]), json.loads(row["result_json"]), json.loads(row["ruleset_json"])
    if p1.digest(p1.canonical(snapshot)) != row["snapshot_hash"] or p1.digest(p1.canonical(rules)) != result["ruleset_hash"]:
        raise HTTPException(409, "snapshot or ruleset integrity failure")
    result_sha = p1.digest(row["result_json"].encode())
    cached = db.execute("SELECT 1 FROM p3_run_verifications WHERE run_id=? AND result_sha=? AND snapshot_hash=? AND engine=?",
                        (run_id, result_sha, row["snapshot_hash"], p3.ENGINE_FINGERPRINT)).fetchone()
    if not cached:
        rebuilt, _, _ = p3.calculate(snapshot, row["period_start"], row["period_end"], row["sampling_seed"], rules, run_id)
        if rebuilt != result:
            raise HTTPException(409, "persisted audit result fails reproduction")
        db.execute("INSERT OR IGNORE INTO p3_run_verifications VALUES(?,?,?,?,?)", (run_id, result_sha, row["snapshot_hash"], p3.ENGINE_FINGERPRINT, datetime.now(timezone.utc).isoformat()))
        if not db.in_transaction or db.isolation_level is not None:
            db.commit()
    return dict(row), snapshot, result, rules


def selected_reconciliations(register):
    history = register["reconciliations"] if register else []
    versioned = [r for r in history if "rule" in r]
    # A new reconciliation replaces prior comparisons only in future snapshots.
    # Historical snapshots without metadata retain their original interpretation.
    return versioned[-1:] if versioned else history


def audit_findings(snapshot, result, register=None):
    findings = list(result["findings"])
    # Existing P2 reconciliation findings are frozen with the source upload; no live recalculation.
    if register and register["reconciliations"]:
        for reconciliation in selected_reconciliations(register):
            for f in json.loads(reconciliation["findings_json"]):
                rule = reconciliation.get("rule", T00_RULE)
                findings.append({**f, "ruleset_version": rule["version"], "ruleset_hash": reconciliation.get("rule_hash", p1.digest(p1.canonical(rule))),
                                 "object_ref": f.get("bill_no", "register"), "state": "GAP" if f["category"] == "PARSE_REVIEW" else "INCONSISTENT", "confirmed_exception": False,
                                 "reconciliation_id": reconciliation["reconciliation_id"]})
    return findings


def related_invoices(finding, snapshot, look=None):
    refs = set(finding.get("invoice_ids", [])) | {finding.get("invoice_id"), finding["object_ref"]}
    if look is None:  # callers outside enrich: same rules, scanning
        if finding.get("bill_no"):
            refs.update(i["invoice_id"] for i in snapshot["invoices"] if i["bill_no"] == finding["bill_no"])
        refs.update(i["invoice_id"] for i in snapshot["invoices"] if i["customer_id"] in {finding.get("customer_id"), finding["object_ref"]})
        refs.update(n["invoice_id"] for n in snapshot["credit_notes"] if n["credit_note_id"] == finding["object_ref"])
        return {ref for ref in refs if ref}
    if finding.get("bill_no"):
        refs |= look["invoices_by_bill"].get(finding["bill_no"], set())
    for customer in {finding.get("customer_id"), finding["object_ref"]}:
        refs |= look["invoices_by_customer"].get(customer, set())
    refs |= look["invoices_by_credit_note"].get(finding["object_ref"], set())
    return {ref for ref in refs if ref}


def evidence_index(snapshot, register):
    index = {}
    manifest = {r["file_name"]: r for r in (snapshot.get("dataset_manifest") or {}).get("files", [])}
    for name, records in sorted(snapshot.get("source_data", {}).items()):
        for row_no, record in enumerate(records, 1):
            ref = f"SRC:{snapshot['dataset_id']}:{name}:{row_no}"
            index[ref] = {"evidence_id": ref, "file_name": name, "source_row": row_no + 1, "sha256": manifest[name]["sha256"],
                          "row_hash": p1.digest(p1.canonical(record)), "record": record, "provenance": "SYNTHETIC_SOURCE_ROW_UNVERIFIED", "independently_verified": False}
    for table, key in (("invoices", "invoice_id"), ("credit_notes", "credit_note_id")):
        for record in snapshot[table]:
            ref = "SNAP:" + table + ":" + record[key]
            index[ref] = {"evidence_id": ref, "file_name": table, "record": record, "row_hash": p1.digest(p1.canonical(record)),
                          "provenance": "SYSTEM_RECORD_SNAPSHOT", "independently_verified": False}
    for record in snapshot["p2_evidence"] + snapshot["p3_evidence"]:
        index[record["evidence_id"]] = {**record, "file_name": "uploaded_evidence", "provenance": "COMPANY_SUPPLIED_UNVERIFIED", "independently_verified": False}
    metadata_source_rows = register.get("metadata_source_rows", [])
    for row in register.get("rows", []):
        ref = f"REG:{register['upload_id']}:{row['row_no']}"
        # row_no is 1-based; metadata_source_rows only contains non-empty rows so the
        # list may be shorter than the maximum row_no.  Fall back to a computed estimate.
        row_idx = row["row_no"] - 1
        source_row = metadata_source_rows[row_idx] if row_idx < len(metadata_source_rows) else row["row_no"] + 1
        index[ref] = {"evidence_id": ref, "file_name": "Sales Register", "source_row": source_row, "normalized_row_no": row["row_no"], "sha256": register["sha256"],
                      "row_hash": row["row_hash"], "record": json.loads(row["raw_json"]), "provenance": "CLIENT_REGISTER_UNVERIFIED", "independently_verified": False}
    rp = snapshot.get("related_party_upload")
    if rp:
        ref = "RP:" + rp["upload_id"]
        index[ref] = {"evidence_id": ref, "file_name": "related_party_upload", "sha256": rp["sha256"], "record": rp,
                      "provenance": "CLIENT_DISCLOSURE_UNVERIFIED", "independently_verified": False}
    return index


def _lookups(snapshot, result, index):
    """Lookup tables built once per request, so matching each finding to its evidence, related
    invoices and samples is a dictionary lookup instead of a scan (it used to be findings x rows)."""
    def group(pairs):
        out = defaultdict(set)
        for key, value in pairs:
            out[key].add(value)
        return out
    by_file = group((item["file_name"], ref) for ref, item in index.items())
    by_invoice = group((item.get("record", {}).get("invoice_id"), ref) for ref, item in index.items() if item["file_name"] == "invoices")
    by_credit_note = group((item.get("record", {}).get("credit_note_id"), ref) for ref, item in index.items() if item["file_name"] == "credit_notes")
    by_object = group((item.get("object_id"), ref) for ref, item in index.items() if item.get("object_id") is not None)
    by_register_row = group((item.get("normalized_row_no"), ref) for ref, item in index.items() if item["file_name"] == "Sales Register")
    samples = defaultdict(list)
    for position, item in enumerate(result["sample_items"]):
        samples[item["object_ref"]].append(position)
    return {"by_file": by_file, "by_invoice": by_invoice, "by_credit_note": by_credit_note, "by_object": by_object,
            "by_register_row": by_register_row, "samples": samples,
            "invoices_by_bill": group((i["bill_no"], i["invoice_id"]) for i in snapshot["invoices"]),
            "invoices_by_customer": group((i["customer_id"], i["invoice_id"]) for i in snapshot["invoices"]),
            "invoices_by_credit_note": group((n["credit_note_id"], n["invoice_id"]) for n in snapshot["credit_notes"])}


def enrich(findings, run, snapshot, result, index):
    enriched = []
    look = _lookups(snapshot, result, index)
    for finding in findings:
        refs = related_invoices(finding, snapshot, look)
        evidence = set(finding.get("evidence_ids", []))
        # Source-rule inputs are explicitly cited; broad inputs are marked as such.
        for file_name in FILES.get(finding["test_id"], []):
            evidence |= look["by_file"].get(file_name, set())
        for ref in refs:
            evidence |= look["by_invoice"].get(ref, set()) | look["by_object"].get(ref, set())
        evidence |= look["by_credit_note"].get(finding["object_ref"], set())
        if finding["test_id"] == "T00":
            evidence |= look["by_register_row"].get(finding["row_no"], set()) if finding.get("row_no") else look["by_file"].get("Sales Register", set())
        if finding["test_id"] == "T01":
            evidence |= look["by_file"].get("related_party_upload", set())
        if evidence and not evidence <= index.keys():
            raise HTTPException(409, "finding source references do not resolve")
        positions = sorted({p for ref in refs | {finding["object_ref"]} for p in look["samples"].get(ref, [])})
        samples = [{"sheet": s["sheet"], "object_ref": s["object_ref"], "selection_reason": s["selection_reason"]}
                   for s in (result["sample_items"][p] for p in positions)]
        enriched.append({**finding, "assertion": finding.get("assertion", ASSERTIONS[finding["test_id"]]), "run_id": run["run_id"],
                         "snapshot_hash": run["snapshot_hash"], "ruleset_version": run["ruleset_version"] if finding["test_id"] != "T00" else finding.get("ruleset_version", "p2-t00-v1"),
                         "ruleset_hash": result["ruleset_hash"] if finding["test_id"] != "T00" else finding.get("ruleset_hash", p1.digest(p1.canonical(T00_RULE))), "evidence_ids": sorted(evidence), "samples": samples,
                         "sample_scope": "selected" if samples else "population/source-level check; not a selected sample",
                         "standard": STANDARDS[finding["test_id"]], "known_facts": finding["reason"],
                         "inference": "Automated observation requiring human review; no confirmed exception.", "impact_inr": None,
                         "proposed_adjustment": "Undetermined; obtain facts and approved accounting policy.", "unresolved_questions": "Review source reliability, missing evidence and applicable engagement policy."})
    return enriched


def latest_reviews(db, run_id):
    reviews = {}
    for row in db.execute("SELECT finding_id,decision_json FROM p5_reviews WHERE run_id=? ORDER BY revision", (run_id,)):
        reviews[row["finding_id"]] = json.loads(row["decision_json"])
    return reviews


def reviewable(db, run_id):
    run, snapshot, result, rules = stored_run(db, run_id)
    registers = snapshot.get("register_uploads", [])
    # Review queue includes all snapshotted register reconciliations, keyed by stable finding ID.
    findings = list(result["findings"])
    for register in registers:
        findings.extend(audit_findings(snapshot, {"findings": []}, register))
    return run, snapshot, result, {f["finding_id"]: f for f in findings}


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["EXCEPTION_CONFIRMED", "EXPLAINED", "DATA_ERROR"]
    reason: str = Field(min_length=1, max_length=4096)
    expected_revision: int = Field(ge=0)
    impact_inr: str | None = None
    impact_basis_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    impact_group: str | None = Field(default=None, max_length=200)
    proposed_adjustment: str = Field(default="Undetermined; human accounting assessment required.", max_length=4096)


@router.get("/runs/{run_id}/reviews")
def get_review_queue(run_id: str):
    db = p3.db_open()
    try:
        _, _, result, findings = reviewable(db, run_id)
        reviews = latest_reviews(db, run_id)
        return {"run_id": run_id, "rule_coverage": result["rule_coverage"], "items": [
            {**f, "human_decision": reviews.get(key), "exception_status": "CONFIRMED_BY_HUMAN" if reviews.get(key, {}).get("outcome") == "EXCEPTION_CONFIRMED" else "REVIEWED" if key in reviews else "OPEN_REVIEW"}
            for key, f in sorted(findings.items())]}
    finally:
        db.close()


@router.post("/runs/{run_id}/findings/{finding_id}/review")
def record_review_decision(run_id: str, finding_id: str, payload: ReviewIn):
    caller = identity.get()
    if not caller or caller["role"] != "auditor" or not caller.get("human") or caller.get("channel") == "mcp":
        raise HTTPException(403, "human review capability required")
    return persist_review(run_id, finding_id, payload, proposal=False)


@router.post("/runs/{run_id}/findings/{finding_id}/proposal")
def propose_review_decision(run_id: str, finding_id: str, payload: ReviewIn):
    return persist_review(run_id, finding_id, payload, proposal=True)


def persist_review(run_id, finding_id, payload, proposal):
    db = p3.db_open()
    try:
        # H3: verify and validate before taking the write lock; the lock covers only the
        # revision check and the append, so concurrent requests are not blocked by recomputation.
        _, snapshot, result, findings = reviewable(db, run_id)
        if finding_id not in findings:
            raise HTTPException(404, "finding not in run")
        if not payload.reason.strip():
            raise HTTPException(422, "review reason required")
        if payload.impact_inr is not None:
            try:
                amount = Decimal(payload.impact_inr)
                if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2 or not payload.impact_group or not payload.impact_basis_evidence_ids:
                    raise ValueError()
                payload = payload.model_copy(update={"impact_inr": format(amount, ".2f")})
            except (InvalidOperation, ValueError):
                raise HTTPException(422, "supported nonnegative monetary impact and group required")
        indexes = {}
        for register in snapshot.get("register_uploads", []):
            indexes.update(evidence_index(snapshot, register))
        if not set(payload.impact_basis_evidence_ids) <= indexes.keys():
            raise HTTPException(422, "impact basis does not resolve to snapshot evidence")
        db.execute("BEGIN IMMEDIATE")
        previous = latest_reviews(db, run_id).get(finding_id, {})
        if not proposal and previous.get("revision", 0) != payload.expected_revision:
            raise HTTPException(409, "review was concurrently changed")
        decision = {**payload.model_dump(), "run_id": run_id, "finding_id": finding_id, "decided_by": identity.get()["subject"],
                    "decided_at": datetime.now(timezone.utc).isoformat(), "revision": previous.get("revision", 0) + 1,
                    "human_conclusion": not proposal}
        if proposal:
            db.execute("INSERT INTO p5_proposals(run_id,finding_id,proposal_json) VALUES(?,?,?)", (run_id, finding_id, p1.canonical(decision).decode()))
        else:
            db.execute("INSERT INTO p5_reviews VALUES(?,?,?,?)", (run_id, finding_id, decision["revision"], p1.canonical(decision).decode()))
        p1.log_event(db, decision["decided_by"], "review_proposed" if proposal else "human_review_recorded", finding_id, decision)
        db.commit()
        return decision
    finally:
        db.close()


class PackageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: str
    client_name: str = Field(default="Synthetic demo client", min_length=1, max_length=200)


@router.post("/runs/{run_id}/packages")
def create_export_package(run_id: str, payload: PackageIn):
    db = p3.db_open()
    try:
        # H3: the expensive verification and package assembly happen outside the write lock.
        run, snapshot, result, rules = stored_run(db, run_id)
        register = next((r for r in snapshot.get("register_uploads", []) if r["upload_id"] == payload.upload_id), None)
        if not register:
            raise HTTPException(409, "register is not in this immutable run; rerun after upload")
        register_bytes(register)
        index = evidence_index(snapshot, register)
        for sha in sorted({item["sha256"] for item in index.values() if item.get("sha256")}):
            path = p1.VAULT / sha
            if not path.is_file() or p1.digest(path.read_bytes()) != sha:
                raise HTTPException(409, "source evidence integrity failure")
        findings = enrich(audit_findings(snapshot, result, register), run, snapshot, result, index)
        checks = [{"object_ref": r["invoice_id"], **capacity_screen(r)} for r in snapshot.get("source_data", {}).get("movement_routes.csv", [])]
        public_key = os.environ.get("PRAMAAN_DEMO_IRP_PUBLIC_KEY", "")
        invoices = {i["invoice_id"]: i for i in snapshot["invoices"]}
        for evidence in snapshot["p3_evidence"]:
            raw = (p1.VAULT / evidence["sha256"]).read_bytes()
            if p1.digest(raw) != evidence["sha256"]:
                raise HTTPException(409, "snapshot evidence bytes changed")
            if evidence["content_type"] == "application/vnd.pramaan.demo-irp+json" and evidence["object_id"] in invoices:
                check = {"object_ref": evidence["object_id"], "evidence_id": evidence["evidence_id"], **demo_signature(raw, public_key, invoices[evidence["object_id"]])}
                checks.append(check)
        reviews = latest_reviews(db, run_id)
        groups = {}
        for f in findings:
            f["demonstration_checks"] = [c for c in checks if c["object_ref"] in related_invoices(f, snapshot) and c["test_id"] == f["test_id"]]
            review = reviews.get(f["finding_id"])
            f["human_decision"] = review
            f["exception_status"] = "CONFIRMED_BY_HUMAN" if review and review["outcome"] == "EXCEPTION_CONFIRMED" else "REVIEWED" if review else "OPEN_REVIEW"
            if review:
                if not set(review["impact_basis_evidence_ids"]) <= index.keys():
                    raise HTTPException(409, "review impact basis is outside selected export sources")
                f["impact_inr"], f["proposed_adjustment"] = review["impact_inr"], review["proposed_adjustment"]
                if review["outcome"] == "EXCEPTION_CONFIRMED" and review["impact_inr"] is not None:
                    group = review["impact_group"]
                    if group in groups and groups[group] != review["impact_inr"]:
                        raise HTTPException(409, "overlapping impact group has conflicting values")
                    groups[group] = review["impact_inr"]
        totals = {"supported_confirmed_impact_inr": format(sum((Decimal(v) for v in groups.values()), Decimal(0)), ".2f"),
                  "impact_groups": groups, "confirmed_exceptions": sum(f["exception_status"] == "CONFIRMED_BY_HUMAN" for f in findings),
                  "open_reviews": sum(f["exception_status"] == "OPEN_REVIEW" for f in findings),
                  "unquantified_findings": sum(f["impact_inr"] is None for f in findings), "population_projection_supported": False}
        verification = p1.verify_log()
        if not verification["valid"]:
            raise HTTPException(409, "audit log verification failed")
        review_hashes = {p1.digest(p1.canonical(f["human_decision"])) for f in findings if f["human_decision"]}
        run_events, review_events = [], []
        for row in db.execute("SELECT * FROM events ORDER BY seq"):
            event = json.loads(row["event_json"])
            if event["action"] == "p3_audit_run_created" and event["object_ref"] == run_id:
                run_events.append(dict(row))
            if event["action"] == "human_review_recorded" and event["payload_hash"] in review_hashes:
                review_events.append(dict(row))
        if not run_events:
            raise HTTPException(409, "audit creation event unavailable")
        # Pin the covered head to creation / included human reviews, not incidental read events.
        covered = max([run_events[0], *review_events], key=lambda row: row["seq"])
        verification = {"valid": True, "events_checked": covered["seq"], "head": covered["entry_hash"], "external_anchor": None,
                        "coverage": "audit creation and included human review history"}
        details = p3.run_details(db, run_id, run["period_start"], run["period_end"])
        # Packages stay self-contained: the verified original register bytes are embedded, so
        # exports never depend on the live vault after the package is frozen.
        packaged_register = {**register, "source_base64": base64.b64encode(register_bytes(register)).decode()}
        report = {"client_name": payload.client_name, "audit_name": details["audit_name"], "run_id": run_id, "snapshot": snapshot, "register": packaged_register, "result": result,
                  "audit_log_verification": {**verification, "external_anchor": None},
                  "findings": findings, "evidence_index": index, "differentiated_checks": checks, "totals": totals,
                  "standards": STANDARDS, "ruleset": rules, "reconciliation_rule": selected_reconciliations(register)[-1].get("rule", T00_RULE) if selected_reconciliations(register) else T00_RULE, "demo_public_key_fingerprint": p1.digest(public_key.encode()) if public_key else None,
                  "limitations": ["Synthetic or company-supplied sources are unverified.", "Official IRP verification unavailable; Demo signatures never prove registration or delivery.",
                                  "Missing evidence and unavailable checks are not confirmed exceptions.", "No external anchor; no population projection; proposed entries require human accounting assessment.",
                                  "T00 not run for selected register." if not register["reconciliations"] else "T00 uses the snapshotted P2 reconciliation."],
                  "receipt": {"snapshot_root": run["snapshot_hash"], "ruleset_version": run["ruleset_version"], "ruleset_hash": result["ruleset_hash"],
                              "sampler_version": run["sampler_version"], "sampling_seed": run["sampling_seed"], "canonicalization_version": p1.CANONICALIZATION,
                              "export_version": EXPORT_VERSION, "selection_digest": p1.digest(p1.canonical(result["sample_items"])), "source_sha256": register["sha256"], "external_anchor": None,
                              **({"reconciliation_rules": [{"reconciliation_id": r["reconciliation_id"], "version": r["rule"]["version"], "hash": r["rule_hash"]} for r in selected_reconciliations(register)]} if any("rule" in r for r in selected_reconciliations(register)) else {})}}
        content_hash = p1.digest(p1.canonical(report))
        package_id = "P5-" + content_hash
        db.execute("BEGIN IMMEDIATE")
        if latest_reviews(db, run_id) != reviews:
            raise HTTPException(409, "a review was recorded while the package was being built; create the package again")
        db.execute("INSERT OR IGNORE INTO p5_packages VALUES(?,?,?,?)", (package_id, run_id, p1.canonical(report).decode(), content_hash))
        p1.log_event(db, "auditor", "export_package_created", package_id, {"content_hash": content_hash, "run_id": run_id})
        db.commit()
        return {"package_id": package_id, "content_digest": content_hash, "totals": totals}
    finally:
        db.close()


def load_package(package_id):
    db = p3.db_open()
    try:
        row = db.execute("SELECT * FROM p5_packages WHERE package_id=?", (package_id,)).fetchone()
        if not row:
            raise HTTPException(404, "package not found")
        report = json.loads(row["report_json"])
        if p1.digest(p1.canonical(report)) != row["content_hash"] or package_id != "P5-" + row["content_hash"]:
            raise HTTPException(409, "export package integrity failure")
        return report, row["content_hash"]
    finally:
        db.close()


@router.get("/packages/{package_id}")
def get_export_package(package_id: str):
    report, content_hash = load_package(package_id)
    from . import explain
    ctx = explain.Context(report["snapshot"], report["result"], report.get("register"))
    return {"package_id": package_id, "content_digest": content_hash, **report, "exposure": explain.exposure(report["findings"], ctx)}


@router.get("/packages/{package_id}/workpaper.xlsx")
def export_p5_workpaper(package_id: str):
    from .p5_exports import workbook_bytes
    report, content_hash = load_package(package_id)
    try:
        raw = workbook_bytes(report, content_hash)
    except ValueError:
        raise HTTPException(422, "snapshot cannot be represented faithfully in Excel; retrieve JSON package")
    return Response(raw, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="Pramaan_workpaper.xlsx"'})


@router.get("/packages/{package_id}/memo.pdf")
def export_memo(package_id: str):
    from .p5_exports import memo_bytes
    report, content_hash = load_package(package_id)
    return Response(memo_bytes(report, content_hash), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="Pramaan_findings_memo.pdf"'})


@router.get("/packages/{package_id}/defensibility.zip")
def export_defensibility_pack(package_id: str):
    from .p5_exports import pack_bytes
    report, content_hash = load_package(package_id)
    try:
        raw = pack_bytes(report, content_hash)
    except ValueError:
        raise HTTPException(422, "snapshot cannot be represented faithfully in Excel; retrieve JSON package")
    return Response(raw, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="Pramaan_defensibility.zip"'})


@router.get("/packages/{package_id}/sales/{invoice_id}")
def get_p5_lifecycle(package_id: str, invoice_id: str):
    report, _ = load_package(package_id)
    invoice = next((r for r in report["snapshot"]["invoices"] if r["invoice_id"] == invoice_id), None)
    if not invoice:
        raise HTTPException(404, "sale not in snapshot")
    evidence = [e for e in report["evidence_index"].values() if e.get("object_id") == invoice_id]
    return {"run_id": report["run_id"], "snapshot_root": report["receipt"]["snapshot_root"], "invoice": invoice,
            "timeline": [{"event": key, "date": invoice.get(key), "status": "recorded" if invoice.get(key) else "unavailable"} for key in ("order_date", "dispatch_date", "invoice_date")],
            "control_date": None, "control_status": "GAP: contract/control policy unavailable", "evidence_chips": evidence,
            "findings": [f for f in report["findings"] if invoice_id in related_invoices(f, report["snapshot"])],
            "claims": ["Company-supplied evidence remains unverified.", "No delivery/control/official-registration conclusion is implied."]}
