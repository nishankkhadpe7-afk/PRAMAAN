"""Integrity views over existing P3 snapshots and samples."""
import json
from fastapi import APIRouter, Body, HTTPException
from . import app as p1, p3
from .security import identity

router = APIRouter(prefix="/p4", tags=["P4 identity and integrity"])


@router.get("/identity")
def whoami():
    # Request-scoped transport details (including the credential used internally
    # by the web MCP adapter) must never be reflected to a client.
    caller = identity.get() or {}
    from .upload_safety import max_upload_bytes
    # The upload limit lets the web app refuse an oversized file before sending it; the server
    # still enforces it (a browser shows only a vague network error when it rejects mid-upload).
    return {**{key: caller[key] for key in ("subject", "role", "human", "channel") if key in caller}, "max_upload_bytes": max_upload_bytes()}


@router.post("/tool-denials", status_code=204)
def record_tool_denial():
    """B9: explicit endpoint the MCP adapter calls when it refuses a tool call (unknown tool or
    invalid arguments). Records a 'denied' access decision; replaces a deliberate 404 hack."""
    from fastapi import Response
    from .security import security_event
    caller = identity.get()
    security_event(caller, "mcp_tool_rejected", "denied", caller.get("channel", "mcp") if caller else "mcp", caller.get("tool") if caller else None)
    return Response(status_code=204)


@router.post("/egress-audit")
def egress_audit(report: dict = Body(default={})):
    """Append the MCP egress-DLP report (categories/counts/field paths only, never
    raw values) to the hash-chained log, so the company has an auditable record of
    exactly what the AI boundary redacted or withheld."""
    return record_egress_report(report)


def record_egress_report(report: dict):
    safe = {
        "tool": str(report.get("tool", ""))[:64],
        "redaction_counts": {str(k)[:32]: int(v) for k, v in list((report.get("redaction_counts") or {}).items())[:20]},
        "fields_filtered": [str(f)[:128] for f in (report.get("fields_filtered") or [])][:200],
        "denied": bool(report.get("denied")),
        "denied_categories": [str(c)[:32] for c in (report.get("denied_categories") or [])][:20],
        "total_redactions": int(report.get("total_redactions") or 0),
    }
    db = p3.db_open()
    try:
        p1.log_event(db, "mcp-egress", "mcp_egress_filtered", safe["tool"] or "mcp", safe)
        db.commit()
        return {"logged": True, **safe}
    finally:
        db.close()


@router.get("/audit-runs/{run_id}")
def audit_result(run_id: str):
    db = p3.db_open()
    try:
        row = db.execute("SELECT result_json FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "run not found")
        return json.loads(row[0])
    finally:
        db.close()


def differences(before, after, path=""):
    if isinstance(before, list) and isinstance(after, list):
        return [field for index in range(max(len(before), len(after))) for field in
                (differences(before[index], after[index], path + "/" + str(index)) if index < min(len(before), len(after)) else [path + "/" + str(index)])]
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            location = path + "/" + key
            if key not in before or key not in after:
                changes.append(location)
            else:
                changes.extend(differences(before[key], after[key], location))
        return changes
    return [] if before == after else [path]


@router.get("/audit-runs/{run_id}/changes")
def post_test_changes(run_id: str):
    """Read-only change detection (B3): safe to call repeatedly and from agents."""
    db = p3.db_open()
    try:
        return change_report(db, run_id)
    finally:
        db.close()


@router.post("/audit-runs/{run_id}/changes")
def record_post_test_changes(run_id: str):
    """Record the current change report in the hash-chained log (explicit auditor action)."""
    db = p3.db_open()
    try:
        report = change_report(db, run_id)
        report["recorded"] = False
        if report["changed"]:
            stored = {k: v for k, v in report.items() if k != "recorded"}
            inserted = db.execute("INSERT OR IGNORE INTO p4_changes VALUES(?,?,?)", (run_id, report["current_hash"], p1.canonical(stored).decode())).rowcount
            if inserted:
                p1.log_event(db, "auditor", "post_test_change_detected", run_id, stored)
            db.commit()
            report["recorded"] = True
        return report
    finally:
        db.close()


def change_report(db, run_id):
    if True:
        run = db.execute("SELECT * FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "run not found")
        before = json.loads(run["snapshot_json"])
        current = p3.snapshot_like(db, before)
        current_hash = p1.digest(p1.canonical(current))
        covered = current["p2_evidence"] + current["p3_evidence"]
        if current["dataset_manifest"]:
            covered += current["dataset_manifest"]["files"]
        vault_mismatches = []
        for record in covered:
            sha = record["sha256"]
            if not p1.blob_intact(sha):
                vault_mismatches.append(sha)
        if vault_mismatches:
            current_hash = p1.digest(p1.canonical([current, sorted(vault_mismatches)]))
        old_invoices = {r["invoice_id"]: r for r in before["invoices"]}
        new_invoices = {r["invoice_id"]: r for r in current["invoices"]}
        changed_refs = {ref for ref in old_invoices.keys() | new_invoices.keys() if old_invoices.get(ref) != new_invoices.get(ref)}
        changed_refs.update(r["credit_note_id"] for r in before["credit_notes"] + current["credit_notes"] if r["invoice_id"] in changed_refs)
        for key in ("credit_notes", "p2_evidence", "p3_evidence"):
            if before[key] != current[key]:
                records = before[key] + current[key]
                changed_refs.update(r.get("invoice_id", r.get("object_id")) for r in records)
                changed_refs.update(r.get("credit_note_id") for r in records)
        # Population/risk inputs can alter selection: conservatively impact all samples.
        population_change = bool(vault_mismatches) or any(before[key] != current[key] for key in ("related_party_upload", "source_data", "dataset_manifest"))
        population_change |= before.get("register_uploads", []) != current.get("register_uploads", [])
        result = json.loads(run["result_json"])
        affected = [s for s in result["sample_items"] if population_change or s["object_ref"] in changed_refs]
        report = {"run_id": run_id, "changed": current_hash != run["snapshot_hash"],
                  "snapshot_hash": run["snapshot_hash"], "current_hash": current_hash,
                  "changed_fields": differences(before, current),
                  "vault_hash_mismatches": sorted(vault_mismatches),
                  "changed_object_refs": sorted(ref for ref in changed_refs if ref),
                  "affected_samples": [{"sheet": s["sheet"], "object_ref": s["object_ref"]} for s in affected],
                  "affected_finding_ids": [f["finding_id"] for f in result["findings"] if population_change or f["object_ref"] in changed_refs],
                  "impact_mapping": "conservative-all-samples" if population_change else "linked-object",
                  "external_anchor": None}
        return report
