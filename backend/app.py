from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("PRAMAAN_DATA", Path(__file__).parent / "data"))
DB_PATH = ROOT / "p1.sqlite3"
VAULT = ROOT / "vault"
RULESET_PATH = Path(__file__).with_name("ruleset.yaml")
CANONICALIZATION = "json-sort-utf8-v1"
BUSY_TIMEOUT_SECONDS = 15
ZERO_HASH = "0" * 64
app = FastAPI(title="Pramaan P1", version="0.1.0", description="Single-sale audit slice; synthetic/demo use.")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def connect() -> sqlite3.Connection:
    from .security import identity, constrain, RestrictedConnection
    if identity.get() is not None:
        db = sqlite3.connect(DB_PATH, cached_statements=0, factory=RestrictedConnection, timeout=BUSY_TIMEOUT_SECONDS)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_SECONDS * 1000)}")
        constrain(db, identity.get())
        return db
    ROOT.mkdir(parents=True, exist_ok=True)
    VAULT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_SECONDS)
    db.row_factory = sqlite3.Row
    # H3: WAL lets readers proceed while one writer commits; the busy timeout queues writers
    # instead of failing fast with "database is locked". WAL is persistent for the file.
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS sales (sale_id TEXT PRIMARY KEY, register_row TEXT NOT NULL, invoice TEXT NOT NULL, dispatch TEXT NOT NULL, source_sha256 TEXT, snapshot_hash TEXT, active_run TEXT);
      CREATE TABLE IF NOT EXISTS evidence (evidence_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content_type TEXT NOT NULL, controller TEXT NOT NULL, acquisition_channel TEXT NOT NULL, independently_verified INTEGER NOT NULL, assertions TEXT NOT NULL, verification_method TEXT);
      CREATE TABLE IF NOT EXISTS parties (party_id TEXT PRIMARY KEY, sale_id TEXT NOT NULL, record_json TEXT NOT NULL, FOREIGN KEY(sale_id) REFERENCES sales(sale_id));
      CREATE TABLE IF NOT EXISTS links (sale_id TEXT NOT NULL, evidence_id TEXT NOT NULL, PRIMARY KEY(sale_id,evidence_id), FOREIGN KEY(sale_id) REFERENCES sales(sale_id), FOREIGN KEY(evidence_id) REFERENCES evidence(evidence_id));
      CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_json TEXT NOT NULL, prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL UNIQUE);
      CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, sale_id TEXT NOT NULL, snapshot_hash TEXT NOT NULL, ruleset TEXT NOT NULL, seed TEXT NOT NULL, result_json TEXT NOT NULL, snapshot_json TEXT NOT NULL, ruleset_json TEXT);
      CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'event log is append-only'); END;
      CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'event log is append-only'); END;
    """)
    evidence_columns = {row[1] for row in db.execute("PRAGMA table_info(evidence)")}
    if "verification_method" not in evidence_columns:
        db.execute("ALTER TABLE evidence ADD COLUMN verification_method TEXT")
    run_columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
    if "ruleset_json" not in run_columns:
        db.execute("ALTER TABLE runs ADD COLUMN ruleset_json TEXT")
    db.commit()
    return db


def log_event(db: sqlite3.Connection, actor: str, action: str, ref: str, payload: Any) -> dict[str, Any]:
    from .security import identity
    caller = identity.get()
    if caller is not None:
        actor = caller["subject"]
    # Serialize head selection and append; domain writes already hold this lock.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    tail = db.execute("SELECT entry_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    prev = tail[0] if tail else ZERO_HASH
    event = {"actor": actor, "action": action, "object_ref": ref, "payload_hash": digest(canonical(payload))}
    if caller is not None:
        event.update(role=caller["role"], channel=caller.get("channel", "api"))
    event_hash = digest(bytes.fromhex(prev) + canonical(event))
    db.execute("INSERT INTO events(event_json,prev_hash,entry_hash) VALUES(?,?,?)", (canonical(event).decode(), prev, event_hash))
    return {**event, "prev_hash": prev, "entry_hash": event_hash}


class EvidenceIn(BaseModel):
    evidence_id: str = Field(min_length=1)
    content_type: str = "application/octet-stream"
    content_base64: str
    controller: str
    acquisition_channel: str
    # Kept for request compatibility, but caller claims are deliberately ignored.
    independently_verified: bool = False
    assertions: list[str]


class SaleIn(BaseModel):
    sale_id: str
    register_source_base64: str
    register_row: dict[str, Any]
    party: dict[str, Any]
    invoice: dict[str, Any]
    dispatch: dict[str, Any]
    evidence: list[EvidenceIn]


class RecordPatch(BaseModel):
    record: str
    field: str
    value: Any


def require_sale(db: sqlite3.Connection, sale_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM sales WHERE sale_id=?", (sale_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "sale not found")
    return row


def sale_state(db: sqlite3.Connection, sale_id: str) -> dict[str, Any]:
    sale = require_sale(db, sale_id)
    evidence = [dict(r) for r in db.execute("SELECT e.* FROM evidence e JOIN links l USING(evidence_id) WHERE l.sale_id=? ORDER BY e.evidence_id", (sale_id,))]
    for item in evidence:
        item["assertions"] = json.loads(item["assertions"])
        # Legacy caller-set flags are not trusted without a server-recorded method.
        item["independently_verified"] = bool(item["independently_verified"] and item["verification_method"])
    party = db.execute("SELECT record_json FROM parties WHERE sale_id=?", (sale_id,)).fetchone()
    return {"sale_id": sale_id, "register_source_sha256": sale["source_sha256"], "register_row": json.loads(sale["register_row"]), "party": json.loads(party[0]), "invoice": json.loads(sale["invoice"]), "dispatch": json.loads(sale["dispatch"]), "evidence": evidence}


def snapshot(db: sqlite3.Connection, sale_id: str) -> tuple[str, dict[str, Any]]:
    state = sale_state(db, sale_id)
    return digest(canonical(state)), state


REQUIRED_ASSERTIONS = ("occurrence", "accuracy", "cutoff", "classification")


def load_ruleset() -> dict[str, Any]:
    # The file uses JSON syntax, which is a strict subset of YAML, avoiding a runtime YAML dependency.
    try:
        config = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
        t06 = config["tests"]["T06"]
        value_tolerance = Decimal(t06["value_absolute_tolerance"])
        quantity_tolerance = Decimal(t06["quantity_absolute_tolerance"])
        if not config.get("version") or not value_tolerance.is_finite() or not quantity_tolerance.is_finite() or value_tolerance < 0 or quantity_tolerance < 0:
            raise ValueError("ruleset version and non-negative T06 tolerances are required")
        if not isinstance(t06.get("exact_fields", []), list):
            raise ValueError("T06 exact_fields must be a list")
        return config
    except (OSError, KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"invalid P1 ruleset configuration: {exc}") from exc


def run_rules(state: dict[str, Any], run_id: str, snapshot_hash: str, seed: str, ruleset: dict[str, Any] | None = None) -> dict[str, Any]:
    ruleset = ruleset or load_ruleset()
    ruleset_version = str(ruleset["version"])
    ruleset_hash = digest(canonical(ruleset))
    invoice, dispatch = state["invoice"], state["dispatch"]
    findings: list[dict[str, Any]] = []
    mismatches = []
    tolerance_config = ruleset["tests"]["T06"]
    for field, tolerance_key in (("value", "value_absolute_tolerance"), ("quantity", "quantity_absolute_tolerance")):
        if field in invoice and field in dispatch:
            try:
                difference = abs(Decimal(str(invoice[field])) - Decimal(str(dispatch[field])))
                if difference > Decimal(tolerance_config[tolerance_key]):
                    mismatches.append(field)
            except (InvalidOperation, TypeError, ValueError):
                mismatches.append(field)
    for field in tolerance_config.get("exact_fields", []):
        if field in invoice and field in dispatch:
            left = "".join(str(invoice[field]).upper().split())
            right = "".join(str(dispatch[field]).upper().split())
            if left != right:
                mismatches.append(field)
    if mismatches:
        findings.append({"finding_id": "F-" + digest(canonical([run_id, "T06", mismatches]))[:12], "test_id": "T06", "assertion": "accuracy", "state": "INCONSISTENT", "reason": "Invoice and dispatch disagree on: " + ", ".join(mismatches) + ".", "evidence_ids": [e["evidence_id"] for e in state["evidence"] if "accuracy" in e["assertions"]]})
    assertions = sorted(set(REQUIRED_ASSERTIONS) | {assertion for e in state["evidence"] for assertion in e["assertions"]})
    for assertion in assertions:
        relevant = [e for e in state["evidence"] if assertion in e["assertions"]]
        if assertion == "accuracy" and mismatches:
            status, reason = "INCONSISTENT", "Invoice and dispatch disagree beyond the configured T06 tolerance."
        elif not relevant:
            status, reason = "GAP", "No stored evidence is linked to this assertion."
        elif any(e["independently_verified"] and e["verification_method"] for e in relevant):
            status, reason = "SUBSTANTIATED", "At least one linked item has a recorded independent verification; scope remains limited to this assertion."
        else:
            status, reason = "INTERNAL_ONLY", "Linked evidence is company-controlled or has not been independently verified."
        findings.append({"finding_id": "F-" + digest(canonical([run_id, "T12", assertion, status]))[:12], "test_id": "T12", "assertion": assertion, "state": status, "reason": reason, "evidence_ids": [e["evidence_id"] for e in relevant]})
    return {"run_id": run_id, "sale_id": state["sale_id"], "snapshot_hash": snapshot_hash, "ruleset_version": ruleset_version, "ruleset_hash": ruleset_hash, "sampling_seed": seed, "canonicalization_version": CANONICALIZATION, "findings": findings}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "P1-P5", "p6_status": "technical gate only; independent rehearsal evidence pending", "mode": "local-demo"}


@app.post("/sales")
def import_sale(payload: SaleIn) -> dict[str, Any]:
    from .upload_safety import content_type, decode_base64
    # Validate every input before touching the database or the vault (B2).
    party_id = str(payload.party.get("party_id", ""))
    if not party_id:
        raise HTTPException(422, "party.party_id is required")
    evidence_ids = [e.evidence_id for e in payload.evidence]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise HTTPException(422, "evidence_id values must be unique within the request")
    try:
        source = decode_base64(payload.register_source_base64, label="register source")
    except ValueError as exc:
        raise HTTPException(422, "invalid or oversized register source") from exc
    decoded = []
    for evidence in payload.evidence:
        try:
            decoded.append((evidence, decode_base64(evidence.content_base64, label="evidence"), content_type(evidence.content_type)))
        except ValueError as exc:
            raise HTTPException(422, "invalid or oversized evidence") from exc
    source_hash = digest(source)
    db = connect()
    try:
        if db.execute("SELECT 1 FROM sales WHERE sale_id=?", (payload.sale_id,)).fetchone():
            raise HTTPException(409, "sale_id already exists")
        for evidence, raw, safe_content_type in decoded:
            # A request field cannot certify its own evidence. P1 has no independent-verification adapter.
            db.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)", (evidence.evidence_id, digest(raw), safe_content_type, evidence.controller, evidence.acquisition_channel, 0, canonical(evidence.assertions).decode(), None))
        db.execute("INSERT INTO sales(sale_id,register_row,invoice,dispatch,source_sha256) VALUES(?,?,?,?,?)", (payload.sale_id, canonical(payload.register_row).decode(), canonical(payload.invoice).decode(), canonical(payload.dispatch).decode(), source_hash))
        db.execute("INSERT INTO parties VALUES(?,?,?)", (party_id, payload.sale_id, canonical(payload.party).decode()))
        for evidence in payload.evidence:
            db.execute("INSERT INTO links VALUES(?,?)", (payload.sale_id, evidence.evidence_id))
        receipt = log_event(db, "client", "sale_imported", payload.sale_id, {"row": payload.register_row, "party": payload.party, "invoice": payload.invoice, "dispatch": payload.dispatch, "evidence_ids": evidence_ids})
        # Content-addressed writes happen only after every row was accepted; a later commit
        # failure can leave an unreferenced (harmless, identical-content) file, never a dangling row.
        store_blob(source)
        for _, raw, _ in decoded:
            store_blob(raw)
        db.commit()
        return {"sale_id": payload.sale_id, "source_sha256": source_hash, "evidence_ids": evidence_ids, "event": receipt}
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "sale, party or evidence identifier already exists") from exc
    finally:
        db.close()


def store_blob(raw: bytes) -> str:
    """Write content-addressed bytes to the vault atomically; returns the SHA-256."""
    sha = digest(raw)
    target = VAULT / sha
    if target.is_file() and digest(target.read_bytes()) == sha:
        return sha
    VAULT.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(sha + ".tmp-" + os.urandom(4).hex())
    temp.write_bytes(raw)
    os.replace(temp, target)
    return sha


@app.get("/sales/{sale_id}")
def get_sale(sale_id: str) -> dict[str, Any]:
    db = connect()
    try:
        return sale_state(db, sale_id)
    finally:
        db.close()


@app.patch("/sales/{sale_id}/records")
def update_business_record(sale_id: str, patch: RecordPatch) -> dict[str, Any]:
    """Versioned client edit; P4 middleware and connection policy enforce access."""
    if patch.record not in {"invoice", "dispatch"} or patch.field in {"sale_id", "evidence"}:
        raise HTTPException(422, "only invoice or dispatch facts can be updated")
    db = connect()
    try:
        sale = require_sale(db, sale_id)
        current = json.loads(sale[patch.record])
        before = current.get(patch.field)
        current[patch.field] = patch.value
        db.execute("INSERT INTO p4_record_versions(sale_id,record,field,before_json,after_json,actor) VALUES(?,?,?,?,?,?)", (sale_id, patch.record, patch.field, canonical(before).decode(), canonical(patch.value).decode(), event_actor()))
        # Use explicit column mapping instead of f-string interpolation for defense-in-depth.
        column = {"invoice": "invoice", "dispatch": "dispatch"}[patch.record]
        db.execute(f"UPDATE sales SET {column}=? WHERE sale_id=?", (canonical(current).decode(), sale_id))
        event = log_event(db, "client-demo", "business_record_updated", sale_id, {"record": patch.record, "field": patch.field, "before": before, "after": patch.value})
        db.commit()
        return {"sale_id": sale_id, "record": patch.record, "field": patch.field, "updated": True, "event": event}
    finally:
        db.close()


@app.post("/sales/{sale_id}/snapshot")
def create_snapshot(sale_id: str) -> dict[str, str]:
    db = connect()
    try:
        require_sale(db, sale_id)
        snap, _ = snapshot(db, sale_id)
        db.execute("UPDATE sales SET snapshot_hash=?,active_run=NULL WHERE sale_id=?", (snap, sale_id))
        log_event(db, "auditor", "snapshot_created", sale_id, {"snapshot_hash": snap})
        db.commit()
        return {"sale_id": sale_id, "snapshot_hash": snap, "canonicalization_version": CANONICALIZATION}
    finally:
        db.close()


@app.post("/sales/{sale_id}/run")
def run_audit(sale_id: str, seed: str = "p1-fixed-seed") -> dict[str, Any]:
    db = connect()
    try:
        sale = require_sale(db, sale_id)
        if not sale["snapshot_hash"]:
            raise HTTPException(409, "create a snapshot before running checks")
        current_hash, state = snapshot(db, sale_id)
        if current_hash != sale["snapshot_hash"]:
            raise HTTPException(409, "sale changed after snapshot; create a new snapshot before running")
        ruleset = load_ruleset()
        ruleset_json = canonical(ruleset).decode()
        run_id = "R-" + digest(canonical([sale_id, sale["snapshot_hash"], digest(ruleset_json.encode()), seed]))[:16]
        result = run_rules(state, run_id, sale["snapshot_hash"], seed, ruleset)
        encoded = canonical(result).decode()
        db.execute("INSERT OR IGNORE INTO runs(run_id,sale_id,snapshot_hash,ruleset,seed,result_json,snapshot_json,ruleset_json) VALUES(?,?,?,?,?,?,?,?)", (run_id, sale_id, sale["snapshot_hash"], result["ruleset_version"], seed, encoded, canonical(state).decode(), ruleset_json))
        db.execute("UPDATE sales SET active_run=? WHERE sale_id=?", (run_id, sale_id))
        log_event(db, "auditor", "audit_run_completed", run_id, result)
        db.commit()
        return {**result, "current_state_matches_snapshot": current_hash == sale["snapshot_hash"]}
    finally:
        db.close()


@app.get("/sales/{sale_id}/changes")
def detect_changes(sale_id: str) -> dict[str, Any]:
    db = connect()
    try:
        sale = require_sale(db, sale_id)
        if not sale["snapshot_hash"]:
            raise HTTPException(409, "no snapshot exists")
        current_hash, _ = snapshot(db, sale_id)
        changed = current_hash != sale["snapshot_hash"]
        result = {"changed": changed, "sale_id": sale_id if changed else None, "snapshot_hash": sale["snapshot_hash"], "current_hash": current_hash, "affected_run_id": sale["active_run"] if changed else None, "affected_finding_ids": []}
        if changed and sale["active_run"]:
            run = db.execute("SELECT result_json FROM runs WHERE run_id=?", (sale["active_run"],)).fetchone()
            if run:
                result["affected_finding_ids"] = [f["finding_id"] for f in json.loads(run[0])["findings"]]
        return result
    finally:
        db.close()


@app.post("/sales/{sale_id}/reproduce")
def reproduce(sale_id: str, run_id: str) -> dict[str, Any]:
    db = connect()
    try:
        require_sale(db, sale_id)
        run = db.execute("SELECT * FROM runs WHERE run_id=? AND sale_id=?", (run_id, sale_id)).fetchone()
        if not run:
            raise HTTPException(404, "run not found")
        if not run["ruleset_json"]:
            raise HTTPException(409, "run predates stored ruleset snapshots and cannot be reproduced safely")
        state = json.loads(run["snapshot_json"])
        reproduced = run_rules(state, run_id, run["snapshot_hash"], run["seed"], json.loads(run["ruleset_json"]))
        original = json.loads(run["result_json"])
        return {"run_id": run_id, "identical": reproduced == original, "result": reproduced, "snapshot_is_current": snapshot(db, sale_id)[0] == run["snapshot_hash"]}
    finally:
        db.close()


@app.get("/integrity")
def verify_log() -> dict[str, Any]:
    db = connect()
    try:
        previous, count = ZERO_HASH, 0
        for row in db.execute("SELECT * FROM events ORDER BY seq"):
            event = json.loads(row["event_json"])
            expected = digest(bytes.fromhex(previous) + canonical(event))
            if row["prev_hash"] != previous or row["entry_hash"] != expected:
                return {"valid": False, "broken_at_seq": row["seq"], "events_checked": count}
            previous, count = expected, count + 1
        return {"valid": True, "events_checked": count, "head": previous}
    finally:
        db.close()


def xlsx_bytes(result: dict[str, Any]) -> bytes:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rows = [["Finding ID", "Sale ID", "Test", "Assertion", "State", "Reason", "Evidence IDs", "Snapshot", "Ruleset", "Seed"]]
    for finding in result["findings"]:
        rows.append([finding["finding_id"], result["sale_id"], finding["test_id"], finding["assertion"], finding["state"], finding["reason"], ", ".join(finding["evidence_ids"]), result["snapshot_hash"], result["ruleset_version"], result["sampling_seed"]])
    sheet = Element("{%s}worksheet" % ns)
    data = SubElement(sheet, "{%s}sheetData" % ns)
    for ri, row in enumerate(rows, 1):
        row_el = SubElement(data, "{%s}row" % ns, {"r": str(ri)})
        for ci, val in enumerate(row, 1):
            col, n = "", ci
            while n:
                n, rem = divmod(n - 1, 26)
                col = chr(65 + rem) + col
            cell = SubElement(row_el, "{%s}c" % ns, {"r": f"{col}{ri}", "t": "inlineStr"})
            inline = SubElement(cell, "{%s}is" % ns)
            SubElement(inline, "{%s}t" % ns, {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = str(val)
    wb = Element("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook")
    sheets = SubElement(wb, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets")
    SubElement(sheets, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet", {"name": "P1 Findings", "sheetId": "1", "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "rId1"})
    rels = Element("{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
    SubElement(rels, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship", {"Id": "rId1", "Type": rel + "/worksheet", "Target": "worksheets/sheet1.xml"})
    root_rels = Element("{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
    SubElement(root_rels, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship", {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "Target": "xl/workbook.xml"})
    types = Element("{http://schemas.openxmlformats.org/package/2006/content-types}Types")
    SubElement(types, "{http://schemas.openxmlformats.org/package/2006/content-types}Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    SubElement(types, "{http://schemas.openxmlformats.org/package/2006/content-types}Default", {"Extension": "xml", "ContentType": "application/xml"})
    SubElement(types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {"PartName": "/xl/workbook.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"})
    SubElement(types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {"PartName": "/xl/worksheets/sheet1.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"})
    import io
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tostring(types, encoding="utf-8", xml_declaration=True))
        z.writestr("_rels/.rels", tostring(root_rels, encoding="utf-8", xml_declaration=True))
        z.writestr("xl/workbook.xml", tostring(wb, encoding="utf-8", xml_declaration=True))
        z.writestr("xl/_rels/workbook.xml.rels", tostring(rels, encoding="utf-8", xml_declaration=True))
        z.writestr("xl/worksheets/sheet1.xml", tostring(sheet, encoding="utf-8", xml_declaration=True))
    return out.getvalue()


@app.get("/runs/{run_id}/workpaper.xlsx")
def export_workpaper(run_id: str) -> Response:
    db = connect()
    try:
        row = db.execute("SELECT result_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "run not found")
        return Response(xlsx_bytes(json.loads(row[0])), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="Pramaan_{run_id}.xlsx"'})
    finally:
        db.close()


# P2 routes are isolated in their own module; P1 handlers and contracts remain unchanged.
from .p2 import router as p2_router

app.include_router(p2_router)

# P3 audit/sampling/evidence workflow is additive; P1/P2 route implementations stay frozen.
from .p3 import router as p3_router

app.include_router(p3_router)

from .security import SecurityMiddleware, event_actor
from .p4 import router as p4_router
app.include_router(p4_router)
from .p5 import router as p5_router
app.include_router(p5_router)
from .p6_agent import router as p6_router
app.include_router(p6_router)
from .web_views import router as web_router
app.include_router(web_router)
app.add_middleware(SecurityMiddleware)
from .body_limit import BodySizeLimitMiddleware
# Outermost: size is enforced before authentication, parsing or logging (S4).
app.add_middleware(BodySizeLimitMiddleware)

ERROR_CODES = {400: "bad_request", 401: "unauthenticated", 402: "provider_no_credit", 403: "forbidden", 404: "not_found",
               409: "conflict", 413: "payload_too_large", 422: "invalid_input", 429: "rate_limited", 503: "unavailable"}
GENERIC_MESSAGES = {404: "object not found", 409: "operation conflicts with current state", 422: "invalid operation input",
                    402: "assistant provider account has no credits; add billing credit or switch provider",
                    429: "assistant provider rate limit reached; wait briefly and retry",
                    503: "assistant provider is temporarily unavailable; retry shortly"}
# Provider/availability statuses keep fixed wording: their raw details can carry upstream provider text.
FIXED_MESSAGE_STATUSES = {402, 429, 503}


def error_body(status: int, detail: Any = None, **extra: Any) -> dict[str, Any]:
    """Stable, client-safe error contract: {code, detail[, fields]}.

    4xx details are messages authored in this codebase (never tracebacks, credentials or
    document text), so they are returned to explain *why* an operation was rejected.
    Server errors and provider failures keep fixed wording.
    """
    if status < 500 and status not in FIXED_MESSAGE_STATUSES and isinstance(detail, str) and detail.strip():
        message = detail.strip()[:300]
    else:
        message = GENERIC_MESSAGES.get(status, "operation rejected")
    return {"code": ERROR_CODES.get(status, "error"), "detail": message, **extra}


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, exc):
    # Field locations and validator messages only; submitted values are never reflected.
    fields = []
    for error in exc.errors()[:20]:
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        message = str(error.get("msg", "invalid value")).removeprefix("Value error, ")[:160]
        fields.append({"field": location or "body", "message": message})
    summary = "; ".join(f"{f['field']}: {f['message']}" for f in fields[:3])
    return JSONResponse(error_body(422, "Invalid request: " + summary if summary else "invalid request schema", fields=fields), status_code=422)


@app.exception_handler(HTTPException)
async def safe_operation_error(request, exc):
    retry = (exc.headers or {}).get("Retry-After") if exc.status_code == 429 else None
    return JSONResponse(error_body(exc.status_code, exc.detail), status_code=exc.status_code, headers={"Retry-After": retry} if retry else None)


@app.exception_handler(Exception)
async def safe_server_error(request, exc):
    # Never return tracebacks; the server log keeps the detail.
    import logging
    logging.getLogger("uvicorn.error").exception("Unhandled server error")
    return JSONResponse(error_body(500), status_code=500)
