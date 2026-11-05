# P4 verification — 10 October 2026

Verdict: **PASS for the P4 acceptance gate with the explicitly requested SQLite prototype boundary and supplied console fallback.** This does not certify PostgreSQL grants, hosted judge clients, the entire future MASTER tool inventory, or production deployment.

## Acceptance evidence

| Requirement / exact gate clause | Implemented control and automated evidence |
| --- | --- |
| Client token performs permitted lifecycle actions | `test_api_identity_permissions_and_no_secret_reflection` creates customer/sale and verifies balanced journal. `test_external_sdk_console_stdio_and_streamable_http` creates customers and full P2 sale lifecycles through the official MCP client on both transports. |
| Auditor token performs read/audit actions | Same external test lists its filtered toolset, verifies the audit log, and creates P3 audit runs through MCP. Authenticated P1 audit/snapshot/reproduction also passes. |
| Every protected call resolves validated identity and API policy | Fail-closed ASGI policy covers all existing routes; `/health` is the sole public route. Tokens resolve server-side to fixed subjects/roles, with expiry/revocation checked for each request. MCP has no domain or DB imports; it forwards credentials to the API. Unknown endpoints/tools and client attempts to create audit runs are denied. |
| Auditor writes denied by backend and DB boundary, and logged | External test manually calls the hidden customer tool as auditor and checks no row exists. API test denies business import, creation, reversal, register upload and patching. Direct constrained-SQL test denies business inserts/updates/deletes, journal writes, dataset modification, DDL, ATTACH and PRAGMA escape attempts. Connection denials append security events on close. API/MCP denials append immediately. |
| Role-filtered tool discovery and tool-call logging | Official SDK console lists tools per validated role; manually constructed calls still go to API authorization. Log events retain subject, role, channel, operation/tool reference and decision; request content is hashed rather than copied. Invalid-schema and unknown-tool requests also record denials. |
| Short-lived, revocable credentials and escalation resistance | Opaque 256-bit tokens; only SHA-256 token digests stored in a separate credential registry; 900-second default, enforced 3600-second maximum. Tests cover expiry, revocation, forged credentials and attempted role arguments. The external MCP test checks revoked/expired stdio calls and revoked HTTP requests. No credential-issuing HTTP tool exists. |
| Injected document instructions cause no unauthorized state change | Evidence fixture asks to change identity, delete journals and confirm findings. It is stored as untrusted content, never executed or fed into an action engine. Caller verification claims remain false/null. Role, schema and manual-write tests independently prove denied side effects. MCP results isolate returned data inside `untrusted_document_content`. This is boundary testing, not a claim that any arbitrary LLM resists injection. |
| Snapshots and post-test change-to-sample mapping | Authenticated P1 changes are versioned with actor and mapped to prior findings. P3 evidence additions map to affected sample objects. Out-of-band dataset changes are rehashed and conservatively mapped to all potentially affected samples/findings. Reports list changed field paths. Raw vault byte tampering is also detected. Prior stored snapshots still reproduce identical logical results. |
| Append-only audit log and snapshot protections | Existing log/journal triggers retained; version rows and P1/P3 run snapshots also reject updates/deletes. Repeated deterministic run creation uses INSERT OR IGNORE. Existing broken-chain regression passes. External anchoring is **not implemented**; change reports explicitly return a null anchor. |
| Exact external client used for fallback | Supplied `Pramaan.backend.agent_console`, official MCP Python SDK 1.30.0 `ClientSession`, runs against separate real API/MCP processes on Windows/Python 3.14. Both stdio and Streamable HTTP are tested. Hosted ChatGPT/Claude/Gemini/judge clients are not tested or certified. |
| P1–P3 / synthetic / reproducibility regressions | All 12 prior tests retained with original assertions. HTTP fixtures now provision real credentials; synthetic fixture provisioning is an offline administrator operation. Windows CRLF checkout bytes were restored to committed LF bytes and `.gitattributes` prevents conversion; manifest validation remains strict and unchanged. No synthetic facts or manifest digests changed. |

## Actual verification

Final full-suite run: 18 tests passed in 81.644 seconds.

From `Pramaan/`, with its parent on PYTHONPATH:

```powershell
$env:PYTHONPATH="$PWD\.."
.venv-p4/Scripts/python.exe -m unittest discover -s backend/tests -v
.venv-p4/Scripts/python.exe -m compileall -q backend
git diff --check
```

Full suite: **18 passed, 0 failures, 0 errors, 0 skipped** (12 P1–P3 + 6 P4). Python compilation and whitespace checks succeeded. The official SDK subprocess test requires Windows named pipes; the restricted sandbox denied their creation, so the full suite was run with approved execution outside that sandbox. No test was skipped or permission check weakened.

Python 3.14 emits non-failing ResourceWarning messages for some test-fixture SQLite connections using context managers; these do not change the test result. The credential registry explicitly closes its connections.

## Security limitations and migration preparation

- SQLite has **no database roles/grants**. Identity-scoped service connections use authorizers, disable statement caching/extensions, deny schema changes/attachment and restrict writes by table/column. Auditor connections may write audit tables and only P1 snapshot bookkeeping columns, never invoice/dispatch facts. Client connections cannot read audit results or write conclusions/snapshots; the inbox may read only the run ID for its existence check. The evidence workflow permits only evidence insertion and request fulfilment columns.
- These controls constrain application connections, not a file owner/administrator, arbitrary new SQLite connection, or compromised Python process. Trusted local migration/provisioning and offline service calls retain administrative access. The separate MCP process has no DB code or credential-store access through its interface, but is not OS-sandboxed against opening local files. A separate OS account/container without database/vault mounts is still required for that stronger boundary.
- One company per `PRAMAAN_DATA` instance. Multi-company tenancy is not implemented; do not share an instance among unrelated clients. Provisioning/revocation is a trusted local CLI operation. No OAuth discovery, issuer integration, rate limiter or external anchor exists. HTTP MCP binds loopback; remote deployment needs reviewed TLS, origins and host configuration.
- PostgreSQL migration must replace authorizers with separate business_writer/audit_writer/log-appender pools, remove ordinary DDL rights, enforce auditor SELECT-only access to business tables and tenant row policies, grant logging through an append-only function, and test direct SQL privileges. Offline migration credentials must remain separate. No such PostgreSQL migration or grant test is claimed here.
- Impact mapping is conservative for changed population/risk/source data and vault integrity failures; it can include more samples than ultimately need retesting. Detection occurs on comparison invocation, not through a continuous worker. File-owner replacement of the complete database and chain cannot be defeated without external anchoring.

## Scope and remaining work

The MCP catalog exposes 28 tools over implemented P1–P3 services. P2 individual order/dispatch/invoice/receipt/credit-note actions remain one atomic `create_sale_lifecycle` tool; enquiry/quotation/delivery/e-way-bill/manual-journal services do not exist. The broader MASTER catalog's narrative/review-proposal/graph-cycle/job/memo tools are not implemented or advertised. P1 XLSX export is exposed as base64; P5's complete workpapers/memo are not built. Evidence requests are created with runs and exposed in the client inbox; `send_evidence_requests` returns these persisted requests and does not send email.

No blocker remains for the demonstrated SQLite P4 gate. Full MASTER/R9 coverage, production database isolation, external anchoring and hosted-client compatibility remain unverified. P5 and frontend development were not started.

Run IDs now include period boundaries to prevent distinct immutable P3 audits colliding under the same snapshot/seed. Hash-chain head selection and append acquire a SQLite write transaction; concurrent authorized requests are tested without a chain fork.

## Changed files

- Added: `.gitattributes`, `backend/security.py`, `backend/p4.py`, `backend/mcp_server.py`, `backend/agent_console.py`, `backend/tests/auth_support.py`, `backend/tests/test_p4.py`, and this report.
- Updated: `.gitignore`, `PROGRESS.md`, `backend/README.md`, `backend/requirements.txt`, `backend/app.py`, `backend/p2.py`, `backend/p3.py`, and the three existing P1–P3 test files.
- Restored checkout line endings in `data/*` to the committed LF bytes. Git shows no semantic data diff; manifest hashes are unchanged.
