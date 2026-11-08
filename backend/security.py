"""Single-company prototype policy. SQLite authorizers are not database roles."""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sqlite3
import threading
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
AUDITOR = {"get_sale", "create_snapshot", "run_audit", "detect_changes", "reproduce", "record_post_test_changes",
           "verify_log", "export_workpaper", "reconcile_register", "get_journal",
           "create_audit_run", "reproduce_audit_run", "rerun_audit",
           "list_evidence_requests", "post_test_changes", "audit_result", "whoami"}
AUDITOR |= {"create_export_package", "get_export_package", "export_p5_workpaper", "export_memo",
            "export_defensibility_pack", "get_review_queue", "record_review_decision", "propose_review_decision", "get_p5_lifecycle"}
CLIENT |= {"web_business", "web_registers", "web_inbox"}
AUDITOR |= {"web_business", "web_registers", "web_inbox", "web_runs", "web_run_context", "web_run_assistant", "web_events", "web_evidence_content", "web_audit_setup", "web_run_integrity", "web_access_log"}
# MCP egress-DLP audit logging is available to any authenticated identity/channel.
CLIENT |= {"egress_audit", "record_tool_denial"}
AUDITOR |= {"egress_audit", "record_tool_denial"}
# AgentX investigation agent (P6): deterministic tools, human-confirmed actions.
CLIENT |= {"upload_bank_statement", "list_bank_statements"}
AUDITOR |= {"list_bank_statements", "match_bank_transactions", "match_party", "investigate_finding", "list_investigations",
            "get_investigation", "propose_agent_action", "list_agent_actions", "confirm_agent_action", "reject_agent_action"}
TOOL_NAMES |= {"upload_bank_statement", "match_bank_transactions", "match_party", "investigate_finding", "propose_evidence_request", "list_agent_actions"}
HUMAN_ONLY = {"record_review_decision", "confirm_agent_action", "reject_agent_action"}
TOOL_NAMES |= {"create_export_package", "export_p5_workpaper", "export_memo", "propose_review_decision", "get_review_queue", "get_p5_lifecycle"}
BUSINESS = {"sales", "parties", "evidence", "links", "p2_customers", "p2_sales_orders",
            "p2_dispatches", "p2_invoices", "p2_journals", "p2_journal_lines", "p2_receipts",
            "p2_credit_notes", "p2_evidence", "p2_register_uploads", "p2_register_rows",
            "p2_related_party_uploads", "p4_record_versions", "p2_journal_reversals",
            "p6_bank_statements", "p6_bank_rows", "p3_document_reads"}
AUDIT = {"runs", "p2_reconciliations", "p3_audit_runs", "p3_samples", "p3_draws",
         "p3_evidence_requests", "p4_changes"}
AUDIT |= {"p5_packages", "p5_proposals", "p2_reconciliation_rules"}
AUDIT |= {"p3_audit_labels", "p3_run_verifications"}
AUDIT |= {"p6_investigations", "p6_actions"}
# access_log is read by auditors through /ui/access-log; only the logger connection writes it.


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
          CREATE TABLE IF NOT EXISTS access_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, subject TEXT, role TEXT, action TEXT NOT NULL, decision TEXT NOT NULL, channel TEXT NOT NULL, tool TEXT, suppressed INTEGER NOT NULL DEFAULT 0);
          CREATE INDEX IF NOT EXISTS access_log_decision ON access_log(decision, seq);
          CREATE TRIGGER IF NOT EXISTS access_log_no_update BEFORE UPDATE ON access_log BEGIN SELECT RAISE(ABORT,'access log is append-only'); END;
          CREATE TRIGGER IF NOT EXISTS access_log_no_delete BEFORE DELETE ON access_log BEGIN SELECT RAISE(ABORT,'access log is append-only'); END;
        """)
        from .p5 import init_p5
        init_p5(db)
        from .p6_agent import init_p6
        init_p6(db)
        db.close()
    finally:
        identity.reset(reset)
    with credential_db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS credentials(token_hash TEXT PRIMARY KEY, subject TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)")
        columns = {row[1] for row in db.execute("PRAGMA table_info(credentials)")}
        if "human" not in columns:
            db.execute("ALTER TABLE credentials ADD COLUMN human INTEGER NOT NULL DEFAULT 0")
        if "channel" not in columns:
            # H6 migration (additive, reversible): existing credentials keep 'any' channel behaviour.
            db.execute("ALTER TABLE credentials ADD COLUMN channel TEXT NOT NULL DEFAULT 'any'")
        if "issued_at" not in columns:
            db.execute("ALTER TABLE credentials ADD COLUMN issued_at REAL")


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


HUMAN_MAX_TTL = 7 * 24 * 3600  # S6: human-review credentials are never permanent and live at most 7 days.


def issue(subject, role, ttl=900, human=False, permanent=False, agent=False):
    """Issue a bearer credential. ``agent=True`` binds it to the MCP channel (H6): the server then
    treats every request with it as an agent request, whatever headers the caller sends."""
    if role not in {"client_employee", "auditor"} or not subject or (not permanent and not 1 <= ttl <= MAX_TTL):
        raise ValueError(f"valid subject, role and TTL (1-{MAX_TTL} seconds) required")
    if human and role != "auditor":
        raise ValueError("human review capability requires auditor role")
    if human and agent:
        raise ValueError("agent credentials cannot carry human review capability")
    if human and (permanent or ttl > HUMAN_MAX_TTL):
        raise ValueError(f"human review credentials must expire within {HUMAN_MAX_TTL} seconds")
    bootstrap()
    token = secrets.token_urlsafe(32)
    with credential_db() as db:
        now = time.time()
        expires = PERMANENT_EXPIRY if permanent else now + ttl
        db.execute("INSERT INTO credentials(token_hash,subject,role,expires,revoked,human,channel,issued_at) VALUES(?,?,?,?,0,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), subject, role, expires, int(human), "mcp" if agent else "any", now))
    return token


def list_credentials():
    """S6: metadata only (never token material) for local credential housekeeping."""
    bootstrap()
    with credential_db() as db:
        return [{"subject": r["subject"], "role": r["role"], "human": bool(r["human"]), "channel": r["channel"],
                 "expires": r["expires"], "active": not r["revoked"] and r["expires"] > time.time()}
                for r in db.execute("SELECT * FROM credentials ORDER BY expires DESC")]


def revoke_subject(subject):
    with credential_db() as db:
        return db.execute("UPDATE credentials SET revoked=1 WHERE subject=? AND revoked=0", (subject,)).rowcount


def revoke(token):
    with credential_db() as db:
        db.execute("UPDATE credentials SET revoked=1 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def authenticate(header):
    if not header.startswith("Bearer ") or len(header) > 256:
        return None
    with credential_db() as db:
        row = db.execute("SELECT * FROM credentials WHERE token_hash=?", (hashlib.sha256(header[7:].encode()).hexdigest(),)).fetchone()
    if row and not row["revoked"] and row["expires"] > time.time() and row["role"] in {"client_employee", "auditor"}:
        bound = row["channel"] if "channel" in row.keys() else "any"
        return {"subject": row["subject"], "role": row["role"], "human": bool(row["human"]) and bound != "mcp", "bound_channel": bound}
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
            if role == "logger":
                return deny()
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE}:
            return sqlite3.SQLITE_OK
        if action not in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
            return deny()
        if role == "logger":
            # Access-decision writer: append rows to access_log only (H2/S3).
            return sqlite3.SQLITE_OK if table == "access_log" and action == sqlite3.SQLITE_INSERT else deny()
        allowed = table == "events" and action == sqlite3.SQLITE_INSERT
        if role == "auditor":
            allowed |= table in AUDIT
            allowed |= table == "p5_reviews" and bool(caller.get("human")) and action == sqlite3.SQLITE_INSERT
            # P1 audit bookkeeping columns are separate from invoice/dispatch facts.
            allowed |= table == "sales" and action == sqlite3.SQLITE_UPDATE and column in {"snapshot_hash", "active_run"}
        elif role == "client_employee":
            # S2: the client appends business facts; it never rewrites or deletes them. The only
            # in-place updates are versioned P1 invoice/dispatch edits and evidence-request status.
            allowed |= table in BUSINESS and action == sqlite3.SQLITE_INSERT
            allowed |= table == "sales" and action == sqlite3.SQLITE_UPDATE and column in {"invoice", "dispatch"}
            allowed |= table == "p3_evidence" and action == sqlite3.SQLITE_INSERT
            allowed |= table == "p3_evidence_requests" and action == sqlite3.SQLITE_UPDATE and column in {"uploaded_docs", "status"}
        return sqlite3.SQLITE_OK if allowed else deny()
    db.enable_load_extension(False)
    db.set_authorizer(authorize)


UNAUTHENTICATED_LOG_LIMIT = 120  # rows per minute; the rest are counted, not written (S3)
_unauth_window = {"start": 0.0, "written": 0, "suppressed": 0}
_unauth_lock = threading.Lock()


def _unauthenticated_budget():
    """Returns (write_row, suppressed_since_last_row) for unauthenticated denials."""
    with _unauth_lock:
        now = time.monotonic()
        if now - _unauth_window["start"] >= 60:
            _unauth_window.update(start=now, written=0)
        if _unauth_window["written"] >= UNAUTHENTICATED_LOG_LIMIT:
            _unauth_window["suppressed"] += 1
            return False, 0
        _unauth_window["written"] += 1
        suppressed, _unauth_window["suppressed"] = _unauth_window["suppressed"], 0
        return True, suppressed


def security_event(caller, action, decision, channel="api", tool=None):
    """Record one access decision in the append-only access_log (H2).

    Access decisions are operational telemetry, kept out of the business/audit hash chain so
    reads do not grow the chain or contend for its write lock. Rows hold operation names and
    decisions only, never headers, credentials or document text.
    """
    suppressed = 0
    if caller is None:
        write, suppressed = _unauthenticated_budget()
        if not write:
            return
    from . import app as p1
    db = sqlite3.connect(p1.DB_PATH, cached_statements=0, timeout=15)
    try:
        db.execute("PRAGMA busy_timeout=15000")
        constrain(db, {"role": "logger"})
        from datetime import datetime, timezone
        db.execute("INSERT INTO access_log(at,subject,role,action,decision,channel,tool,suppressed) VALUES(?,?,?,?,?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(timespec="milliseconds"), caller["subject"] if caller else None,
                    caller["role"] if caller else None, str(action)[:80], decision, channel, tool if tool in TOOL_NAMES else None, suppressed))
        db.commit()
    finally:
        db.close()



def leaf_routes(application) -> list:
    """Every endpoint route with its full path, on old and new FastAPI.

    FastAPI <= 0.13x copies included routes into ``app.routes``. Newer FastAPI keeps included
    routers as wrapper objects and exposes the effective routes through the public
    ``fastapi.routing.iter_route_contexts`` (the same iterator its OpenAPI generator uses).
    The action name decides permissions, so resolution must never depend on private internals.
    """
    from fastapi import routing as fastapi_routing
    iterate = getattr(fastapi_routing, "iter_route_contexts", None)
    if iterate is None:
        return list(application.routes)
    return [context.route for context in iterate(application.routes)]


def resolve_route(application, scope):
    """The single route that fully matches this request (path and method), or None."""
    return next((r for r in leaf_routes(application) if r.matches(scope)[0] == Match.FULL), None)

class SecurityMiddleware:
    def __init__(self, app):
        self.app = app
        self.ready_path = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from anyio import to_thread
        from . import app as p1
        if self.ready_path != p1.DB_PATH:
            # Blocking SQLite work runs in the threadpool so one slow write never stalls the event loop (H3).
            await to_thread.run_sync(bootstrap)
            self.ready_path = p1.DB_PATH
        route = resolve_route(p1.app, scope)
        action = route.name if route else "unknown_operation"
        if action == "health":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        caller = await to_thread.run_sync(authenticate, headers.get(b"authorization", b"").decode("latin1"))
        # H6: an agent-bound credential is always the MCP channel. The header can only make a
        # request *more* restricted, never lift an agent credential out of the agent policy.
        channel = "mcp" if headers.get(b"x-pramaan-channel") == b"mcp" or (caller and caller.get("bound_channel") == "mcp") else "api"
        tool = headers.get(b"x-pramaan-tool", b"").decode("latin1")
        if caller:
            caller["channel"] = channel
            caller["tool"] = tool if tool in TOOL_NAMES else None
            # The raw credential is request-scoped only. It lets the server-side
            # MCP adapter re-authenticate this same caller; it is never logged or
            # returned in a response.
            caller["token"] = headers.get(b"authorization", b"").decode("latin1")[7:]
        permitted = caller and action in (CLIENT if caller["role"] == "client_employee" else AUDITOR)
        if action in HUMAN_ONLY:
            permitted = permitted and caller.get("human") and channel != "mcp"
        if permitted and agent_action_blocked(action, channel):
            permitted = False
        if not permitted:
            await to_thread.run_sync(security_event, caller, action, "denied", channel, tool)
            status = 403 if caller else 401
            return await JSONResponse({"code": "forbidden" if caller else "unauthenticated", "detail": "DENIED: invalid credential or forbidden operation"}, status_code=status)(scope, receive, send)
        marker = identity.set(caller)
        try:
            # Logs contain stable operation names and decisions, never headers or document text.
            await to_thread.run_sync(security_event, caller, action, "allowed", channel, tool)
            await self.app(scope, receive, send)
        finally:
            identity.reset(marker)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local administrator credential provisioning")
    parser.add_argument("operation", choices=["issue", "revoke", "list", "revoke-subject"])
    parser.add_argument("--subject", default="judge")
    parser.add_argument("--role", choices=["client_employee", "auditor"], default="auditor")
    parser.add_argument("--ttl", type=int, default=900)
    parser.add_argument("--permanent", action="store_true", help="Issue a locally persistent credential (revocable; use only for trusted local development)")
    parser.add_argument("--human-auditor", action="store_true", help="Trusted administrator grants human review capability; do not give this credential to agents")
    parser.add_argument("--agent", action="store_true", help="Bind the credential to the MCP agent channel (use for every token given to an AI agent)")
    args = parser.parse_args()
    if args.operation == "issue":
        print(issue(args.subject, args.role, args.ttl, human=args.human_auditor, permanent=args.permanent, agent=args.agent))
    elif args.operation == "list":
        import json
        print(json.dumps(list_credentials(), indent=2))
    elif args.operation == "revoke-subject":
        print(f"revoked {revoke_subject(args.subject)} credential(s) for {args.subject}")
    else:
        import getpass
        revoke(getpass.getpass("Credential to revoke: "))
