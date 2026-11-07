"""Single-company prototype policy. SQLite authorizers are not database roles."""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar

from starlette.responses import JSONResponse
from starlette.routing import Match

identity = ContextVar("pramaan_identity", default=None)
TOOL_NAMES = {"create_customer", "create_sale_lifecycle", "upload_sale", "update_business_record",
              "upload_sales_register", "upload_related_parties", "respond_to_evidence_request",
              "create_audit_run", "run_tests", "reproduce_workpaper", "get_findings", "select_sales_tod",
              "select_cutoff_tod", "select_credit_note_tod", "get_post_test_changes", "verify_audit_log",
              "get_sale_lifecycle", "import_register_to_workpaper", "list_evidence_requests"}
TOOL_NAMES |= {"send_evidence_requests", "trace_related_parties", "get_witnesses", "create_sale_snapshot",
               "run_sale_tests", "get_sale_changes", "get_journal", "export_workpaper"}


class RestrictedConnection(sqlite3.Connection):
    def close(self):
        denied = getattr(self, "denied_operations", [])
        caller = getattr(self, "caller", None)
        super().close()
        self.denied_operations = []
        for action in denied:
            security_event(caller, action, "denied", "db")
CLIENT = {"import_sale", "update_business_record", "create_customer", "create_sale",
          "reverse_journal", "upload_register", "upload_related_parties",
          "submit_requested_evidence", "list_evidence_requests", "whoami"}
AUDITOR = {"get_sale", "create_snapshot", "run_audit", "detect_changes", "reproduce",
           "verify_log", "export_workpaper", "reconcile_register", "get_journal",
           "create_audit_run", "reproduce_audit_run", "rerun_audit",
           "list_evidence_requests", "post_test_changes", "audit_result", "whoami"}
AUDITOR |= {"create_export_package", "get_export_package", "export_p5_workpaper", "export_memo",
            "export_defensibility_pack", "get_review_queue", "record_review_decision", "propose_review_decision", "get_p5_lifecycle"}
CLIENT |= {"web_business", "web_registers", "web_inbox"}
AUDITOR |= {"web_business", "web_registers", "web_inbox", "web_runs", "web_run_context", "web_run_assistant", "web_events", "web_evidence_content", "web_audit_setup", "web_run_integrity"}
# MCP egress-DLP audit logging is available to any authenticated identity/channel.
CLIENT |= {"egress_audit"}
AUDITOR |= {"egress_audit"}
TOOL_NAMES |= {"create_export_package", "export_p5_workpaper", "export_memo", "propose_review_decision", "get_review_queue", "get_p5_lifecycle"}
BUSINESS = {"sales", "parties", "evidence", "links", "p2_customers", "p2_sales_orders",
            "p2_dispatches", "p2_invoices", "p2_journals", "p2_journal_lines", "p2_receipts",
            "p2_credit_notes", "p2_evidence", "p2_register_uploads", "p2_register_rows",
            "p2_related_party_uploads", "p4_record_versions", "p2_journal_reversals"}
AUDIT = {"runs", "p2_reconciliations", "p3_audit_runs", "p3_samples", "p3_draws",
         "p3_evidence_requests", "p4_changes"}
AUDIT |= {"p5_packages", "p5_proposals", "p2_reconciliation_rules"}
AUDIT |= {"p3_audit_labels"}


# Agent (MCP-channel) policy, enforced server-side in SecurityMiddleware.
# - Reversals are human-session only: no environment switch can enable them for agents.
# - Operations that create or edit the client's books/records are denied to agents
#   unless the operator explicitly sets PRAMAAN_MCP_BOOKS_WRITES=allow. Any other
#   value, including unset or a typo, denies (fail-closed).
# The channel is declared by the MCP adapter via a request header, so this stops the
# adapter path and is audit-logged; it does not stop a credential holder who calls
# the HTTP API directly. Do not issue agent credentials with client write authority
# unless that trust is intended.
MCP_ALWAYS_BLOCKED = {"reverse_journal"}
MCP_BOOKS_WRITES = {"create_sale", "import_sale", "update_business_record"}


def agent_action_blocked(action, channel, env=None):
    if channel != "mcp":
        return False
    if action in MCP_ALWAYS_BLOCKED:
        return True
    if action in MCP_BOOKS_WRITES:
        return (os.environ if env is None else env).get("PRAMAAN_MCP_BOOKS_WRITES") != "allow"
    return False


def event_actor():
    caller = identity.get()
    return caller["subject"] if caller else "offline-admin"


def bootstrap():
    """Trusted migration entry point; never used on a constrained connection."""
    from . import app as p1, p3
    reset = identity.set(None)
    try:
        db = p3.db_open()
        db.executescript("""
          CREATE TABLE IF NOT EXISTS p4_record_versions(seq INTEGER PRIMARY KEY, sale_id TEXT, record TEXT, field TEXT, before_json TEXT, after_json TEXT, actor TEXT);
          CREATE TABLE IF NOT EXISTS p4_changes(run_id TEXT NOT NULL, current_hash TEXT NOT NULL, report_json TEXT NOT NULL, PRIMARY KEY(run_id,current_hash));
          CREATE TRIGGER IF NOT EXISTS p4_versions_no_update BEFORE UPDATE ON p4_record_versions BEGIN SELECT RAISE(ABORT,'versions are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS p4_versions_no_delete BEFORE DELETE ON p4_record_versions BEGIN SELECT RAISE(ABORT,'versions are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS p4_runs_no_update BEFORE UPDATE ON p3_audit_runs BEGIN SELECT RAISE(ABORT,'audit snapshots are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS p4_runs_no_delete BEFORE DELETE ON p3_audit_runs BEGIN SELECT RAISE(ABORT,'audit snapshots are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS p4_p1_runs_no_update BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'audit snapshots are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS p4_p1_runs_no_delete BEFORE DELETE ON runs BEGIN SELECT RAISE(ABORT,'audit snapshots are immutable'); END;
        """)
        from .p5 import init_p5
        init_p5(db)
        db.close()
    finally:
        identity.reset(reset)
    with credential_db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS credentials(token_hash TEXT PRIMARY KEY, subject TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)")
        if "human" not in {row[1] for row in db.execute("PRAGMA table_info(credentials)")}:
            db.execute("ALTER TABLE credentials ADD COLUMN human INTEGER NOT NULL DEFAULT 0")


@contextmanager
def credential_db():
    from . import app as p1
    p1.ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p1.ROOT / "credentials.sqlite3")
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


MAX_TTL = 30 * 24 * 3600  # 30 days; demo/dev convenience. Short-lived tokens remain the recommended default.
# SQLite stores this as a normal numeric expiry, while it is effectively permanent
# for a local deployment (9999-12-31T23:59:59Z).  Keeping an expiry column makes
# permanent credentials work with existing databases and revocation logic.
PERMANENT_EXPIRY = 253402300799


def issue(subject, role, ttl=900, human=False, permanent=False):
    if role not in {"client_employee", "auditor"} or not subject or (not permanent and not 1 <= ttl <= MAX_TTL):
        raise ValueError(f"valid subject, role and TTL (1-{MAX_TTL} seconds) required")
    if human and role != "auditor":
        raise ValueError("human review capability requires auditor role")
    bootstrap()
    token = secrets.token_urlsafe(32)
    with credential_db() as db:
        expires = PERMANENT_EXPIRY if permanent else time.time() + ttl
        db.execute("INSERT INTO credentials(token_hash,subject,role,expires,revoked,human) VALUES(?,?,?,?,0,?)", (hashlib.sha256(token.encode()).hexdigest(), subject, role, expires, int(human)))
    return token


def revoke(token):
    with credential_db() as db:
        db.execute("UPDATE credentials SET revoked=1 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def authenticate(header):
    if not header.startswith("Bearer ") or len(header) > 256:
        return None
    with credential_db() as db:
        row = db.execute("SELECT * FROM credentials WHERE token_hash=?", (hashlib.sha256(header[7:].encode()).hexdigest(),)).fetchone()
    if row and not row["revoked"] and row["expires"] > time.time() and row["role"] in {"client_employee", "auditor"}:
        return {"subject": row["subject"], "role": row["role"], "human": bool(row["human"])}
    return None


def constrain(db, caller):
    role = caller["role"]
    if isinstance(db, RestrictedConnection):
        db.caller = caller
        db.denied_operations = []
    def deny():
        if isinstance(db, RestrictedConnection):
            db.denied_operations.append("sqlite_boundary")
        return sqlite3.SQLITE_DENY
    def authorize(action, table, column, database, source):
        if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}:
            return deny()
        if action == sqlite3.SQLITE_FUNCTION and column == "load_extension":
            return deny()
        if action == sqlite3.SQLITE_READ:
            if role == "client_employee" and table == "p3_audit_labels" and column in {"run_id", "audit_name"}:
                return sqlite3.SQLITE_OK
            if role == "client_employee" and table not in BUSINESS | {"p3_evidence_requests", "p3_evidence", "events"} and not (table == "p3_audit_runs" and column == "run_id"):
                return deny()
            if role == "logger" and table != "events":
                return deny()
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE}:
            return sqlite3.SQLITE_OK
        if action not in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
            return deny()
        allowed = table == "events" and action == sqlite3.SQLITE_INSERT
        if role == "auditor":
            allowed |= table in AUDIT
            allowed |= table == "p5_reviews" and bool(caller.get("human")) and action == sqlite3.SQLITE_INSERT
            # P1 audit bookkeeping columns are separate from invoice/dispatch facts.
            allowed |= table == "sales" and action == sqlite3.SQLITE_UPDATE and column in {"snapshot_hash", "active_run"}
        elif role == "client_employee":
            allowed |= table in BUSINESS
            allowed |= table == "p3_evidence" and action == sqlite3.SQLITE_INSERT
            allowed |= table == "p3_evidence_requests" and action == sqlite3.SQLITE_UPDATE and column in {"uploaded_docs", "status"}
        return sqlite3.SQLITE_OK if allowed else deny()
    db.enable_load_extension(False)
    db.set_authorizer(authorize)


def security_event(caller, action, decision, channel="api", tool=None):
    from . import app as p1
    db = sqlite3.connect(p1.DB_PATH, cached_statements=0)
    db.row_factory = sqlite3.Row
    # This connection can append log rows only, including for unauthenticated denials.
    constrain(db, {"role": "logger"})
    marker = identity.set({**caller, "channel": channel} if caller else None)
    try:
        ref = action + (":" + tool if tool in TOOL_NAMES else "")
        p1.log_event(db, caller["subject"] if caller else "unauthenticated", "security_" + decision, ref,
                     {"role": caller["role"] if caller else None, "decision": decision, "channel": channel, "tool": tool if tool in TOOL_NAMES else None})
        db.commit()
    finally:
        db.close()
        identity.reset(marker)


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app
        self.ready_path = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from . import app as p1
        if self.ready_path != p1.DB_PATH:
            bootstrap()
            self.ready_path = p1.DB_PATH
        route = next((r for r in p1.app.routes if r.matches(scope)[0] == Match.FULL), None)
        action = route.name if route else "unknown_operation"
        if action == "health":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        caller = authenticate(headers.get(b"authorization", b"").decode("latin1"))
        channel = "mcp" if headers.get(b"x-pramaan-channel") == b"mcp" else "api"
        tool = headers.get(b"x-pramaan-tool", b"").decode("latin1")
        if caller:
            caller["channel"] = channel
            # The raw credential is request-scoped only. It lets the server-side
            # MCP adapter re-authenticate this same caller; it is never logged or
            # returned in a response.
            caller["token"] = headers.get(b"authorization", b"").decode("latin1")[7:]
        permitted = caller and action in (CLIENT if caller["role"] == "client_employee" else AUDITOR)
        if action == "record_review_decision":
            permitted = permitted and caller.get("human") and channel != "mcp"
        if permitted and agent_action_blocked(action, channel):
            permitted = False
        if not permitted:
            security_event(caller, action, "denied", channel, tool)
            return await JSONResponse({"detail": "DENIED: invalid credential or forbidden operation"}, status_code=403 if caller else 401)(scope, receive, send)
        marker = identity.set(caller)
        try:
            # Logs contain stable operation names and decisions, never headers or document text.
            security_event(caller, action, "allowed", channel, tool)
            await self.app(scope, receive, send)
        finally:
            identity.reset(marker)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local administrator credential provisioning")
    parser.add_argument("operation", choices=["issue", "revoke"])
    parser.add_argument("--subject", default="judge")
    parser.add_argument("--role", choices=["client_employee", "auditor"], default="auditor")
    parser.add_argument("--ttl", type=int, default=900)
    parser.add_argument("--permanent", action="store_true", help="Issue a locally persistent credential (revocable; use only for trusted local development)")
    parser.add_argument("--human-auditor", action="store_true", help="Trusted administrator grants human review capability; do not give this credential to agents")
    args = parser.parse_args()
    if args.operation == "issue":
        print(issue(args.subject, args.role, args.ttl, human=args.human_auditor, permanent=args.permanent))
    else:
        import getpass
        revoke(getpass.getpass("Credential to revoke: "))
