# Pramaan backend — P1–P6 prototype services

## P4 MCP setup and verification

For the current web demo, use the same storage instance in every backend/provisioning terminal. From `Pramaan/`, set `$env:PYTHONPATH = (Split-Path -Parent $PWD.Path)` and `$env:PRAMAAN_DATA = (Resolve-Path .demo/runtime).Path` before starting the API or issuing credentials. Do not run reset against the current demo. The MCP adapter only calls `PRAMAAN_API_URL`; it does not open SQLite or load a separate dataset.

P4 uses the official MCP Python SDK 1.30.0 and delegates to the authenticated FastAPI services. Run these commands from the directory containing `Pramaan/` (the ELEV19 workspace):

```powershell
py -m venv Pramaan/.venv-p4
$pramaanPython = (Resolve-Path Pramaan/.venv-p4/Scripts/python.exe).Path
& $pramaanPython -m pip install -r Pramaan/backend/requirements.txt
& $pramaanPython -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal, provision a local identity and capture the credential without printing it. Never commit credentials or place them in command arguments:

```powershell
$pramaanPython = (Resolve-Path Pramaan/.venv-p4/Scripts/python.exe).Path
$env:PRAMAAN_TOKEN = (& $pramaanPython -m Pramaan.backend.security issue --subject judge-employee --role client_employee --ttl 900)
$env:PRAMAAN_API_URL = 'http://127.0.0.1:8000'
& $pramaanPython -m Pramaan.backend.agent_console
& $pramaanPython -m Pramaan.backend.agent_console create_customer --arguments '{"payload":{"customer_id":"DEMO-CUSTOMER","name":"Synthetic Customer"}}'
```

The console uses stdio by default. To use Streamable HTTP, start `& $pramaanPython -m Pramaan.backend.mcp_server --http` in another terminal, then set `$env:PRAMAAN_MCP_URL = 'http://127.0.0.1:8001/mcp'` before running the console. HTTP credentials arrive in the Authorization header and are revalidated by the API; initialization and tool discovery also require valid credentials. `PRAMAAN_MCP_PORT` changes the default port. Both transports use the same tools and authorization policy. Clear `PRAMAAN_MCP_URL` to return to stdio.

To switch identity, capture another token with `--subject judge-auditor --role auditor`. The auditor can invoke `verify_audit_log`, `create_audit_run`, `get_findings`, sample views, reproduction and change comparison; manually invoking client tools is denied. Revoke a token with `& $pramaanPython -m Pramaan.backend.security revoke` and enter it at the hidden prompt. Default lifetime is 15 minutes; maximum is one hour. Tokens are stored only as hashes in `credentials.sqlite3`, separately from business records. Set the same `PRAMAAN_DATA` for the API and provisioning CLI when using a non-default storage location.

For a synthetic audit demo, a trusted local administrator can load the existing pack before issuing judge credentials:

```powershell
& $pramaanPython -c 'from Pramaan.backend.security import bootstrap; from Pramaan.backend.p3 import import_fixture_dataset; bootstrap(); import_fixture_dataset()'
& $pramaanPython -m Pramaan.backend.agent_console create_audit_run --arguments '{"payload":{"period_start":"2025-04-01","period_end":"2026-03-31","sampling_seed":"judge-demo-seed-2026"}}'
```

Use the returned run ID in `get_post_test_changes` and `reproduce_workpaper` with `--arguments '{"run_id":"<run-id>"}'`. Tool discovery includes JSON schemas; writes reuse the existing P1/P2/P3 request bodies inside `payload`. Responses contain a summary and `untrusted_document_content`; list results support `limit` (20 by default, up to 100) and `offset`. P2 order, dispatch, invoice, journal and optional receipt/credit note creation remains atomic through `create_sale_lifecycle`. `send_evidence_requests` exposes the requests already created in the client inbox; it does not send messages externally. `export_workpaper` serves only the existing P1 XLSX as base64.

Run all automated checks from the same workspace directory:

```powershell
& $pramaanPython -m unittest discover -s Pramaan/backend/tests -v
& $pramaanPython -m compileall -q Pramaan/backend
```

The full regression suite includes actual subprocess interoperability through the supplied official-SDK console on stdio and Streamable HTTP. On Windows, the runner needs permission to create named pipes and local child processes. Hosted judging clients have not been tested; the console is the demonstrated fallback.

SQLite authorizers restrict identity-scoped application connections; SQLite has no database roles and cannot stop a file owner opening an unrestricted connection. Deploy one company per storage instance. PostgreSQL pools/grants, tenant isolation, OS isolation of the MCP process, external anchoring, OAuth and production rate limits remain future work. The broader MASTER tools whose underlying services are absent are not advertised. See [P4_VERIFICATION_REPORT.md](P4_VERIFICATION_REPORT.md) for gate evidence, the tested scope and migration requirements. The integrated frontend/local demo setup and tests are documented in the [root README](../README.md), [demo checklist](../DEMO.md) and [P6 verification report](P6_VERIFICATION_REPORT.md).

### External client connection contract

The executable fallback is `Pramaan.backend.agent_console` with official SDK 1.30.0. Stdio clients must launch the absolute `.venv-p4/Scripts/python.exe` with arguments `-m Pramaan.backend.mcp_server`, working directory containing `Pramaan/`, and environment `PYTHONPATH` pointing to that directory, `PRAMAAN_API_URL=http://127.0.0.1:8000`, and `PRAMAAN_TOKEN` containing a freshly provisioned identity token. Initialize the MCP session, then call `tools/list` and `tools/call`; tool schemas define supported arguments. These are launch parameters, not a claim that every hosted client's configuration UI supports them. Never persist actual tokens in source/example configurations or command arguments.

For Streamable HTTP, start `python -m Pramaan.backend.mcp_server --http` with the same API URL. Connect to `http://127.0.0.1:8001/mcp`, sending `Authorization: Bearer <fresh short-lived token>` on every request, including initialize/discovery. Configure the external client to support authenticated Streamable HTTP; the local adapter does not provide an OAuth flow or hosted/public endpoint. Loopback is reachable only from the local machine. Hosted ChatGPT/Claude or other agent compatibility remains untested. Do not expose the local server publicly to imply successful integration.

Verification now explicitly checks that MCP-created sales appear in `/ui/business` and the same database, on both transports. Auditor business-write attempts reach backend authorization, fail, and produce an auditor `security_denied` event on the MCP channel. Expiry/revocation are exercised on stdio and HTTP. See [T00_MCP_REGRESSION_REPORT.md](T00_MCP_REGRESSION_REPORT.md).

## T00 v2 normalization and manual retest

New reconciliations use `p2-t00-v2`. Dates accept calendar-valid `YYYY-MM-DD` and explicitly **US `M/D/YYYY`** slash dates (so `4/3/2026` means April 3). No locale inference, D/M fallback, two-digit years, Excel serial dates or timestamps. Convert day-first sources to ISO before uploading; Pramaan cannot infer their intended locale.

Money accepts signed decimal INR with validated western (`48,400`) or Indian (`1,23,456.70`) comma groups and equivalent decimal representations. Comparison uses exact Decimal/integer cents; no floats, rounding, exponent notation, currency symbols or fractional-cent values. Customer names collapse insignificant whitespace only. Invoice numbers and GST identifiers compare as exact text: no zero stripping, case folding, punctuation removal or identifier whitespace normalization. Original source bytes/cells/hashes remain unchanged.

Missing/invalid values produce explicit `PARSE_REVIEW` with raw values and parse statuses; these are gaps, not confirmed discrepancies. The current demo lacks GSTIN values for its 26 P2 invoices, so those gaps remain visible. `FIELD_DIFF` includes the field, original register/system values, normalized values and signed register-minus-system delta. The finding screen and new workbook Findings column expose these details. No observed amount becomes a human-confirmed impact automatically.

To retest the current demo without resetting:

1. Restart the backend with its existing `.demo/runtime` path and restart the frontend to load the changes. Startup adds only the reconciliation-rule metadata table/triggers; historical rows are not backfilled or rewritten.
2. Renew credentials in that same storage instance. As auditor, **Reconcile** the existing edited upload (currently `REG-c2bc0af79f12`), then create a **new audit run** or **Rerun with new snapshot**. Reopening an old run intentionally retains its v1 findings.
3. Open the new run's findings for the chosen upload. There should be one FIELD_DIFF for `DEMO/26/026`, register `58,400` versus system `48400.00`, delta `1000000` cents / `10000.00` INR. GSTIN gaps and fixture register-only observations remain separate.
4. Review the new finding with an authorized human credential and create a new package. The original DATA_ERROR decision and frozen package remain bound to their original run; conclusions are never copied silently.

Rules are captured with each new reconciliation and future snapshots/packages identify the T00 version/hash. The newest invoked v2 reconciliation is used for future findings, while previous comparisons remain preserved in snapshot history. Existing snapshots without metadata retain v1 interpretation; frozen v1 exports keep their original layout and bytes.

Targeted checks from `Pramaan/` (with `PYTHONPATH` set as above):

```powershell
.\.venv-p4\Scripts\python.exe -m unittest Pramaan.backend.tests.test_t00 Pramaan.backend.tests.test_p2 Pramaan.backend.tests.test_p4.P4GateTests.test_external_sdk_console_stdio_and_streamable_http -v
```

The full backend suite, frontend tests/build and three real Chrome flows pass; results are in the focused regression report. Browser checks can use a newly named disposable instance through `PRAMAAN_E2E_INSTANCE` and separate ports through `PRAMAAN_E2E_API_PORT` / `PRAMAAN_E2E_WEB_PORT`; default demo ports remain 8000/5173. Never reset the user's current instance for testing.

## P5 frozen workpapers and review

Install `Pramaan/backend/requirements-dev.txt` for the full test suite; `requirements.txt` supplies the backend runtime. Run the regression and compilation commands above. P5 tests independently read XLSX with openpyxl and PDFs with pypdf; exports use the existing standard-library OOXML approach and ReportLab.

Use authenticated API requests or the supplied MCP console for this workflow:

1. A client uploads the original UTF-8 CSV through `POST /p2/registers` (`source_base64`, `period`). An auditor reconciles it through `POST /p2/registers/{upload_id}/reconcile`.
2. Create a P3 audit run **after** uploading/reconciling. Its immutable snapshot includes raw register bytes, original cells, hashes, parsing metadata and T00 results. Rerun an older audit to capture the register; P5 rejects a register absent from its saved snapshot.
3. Inspect `GET /p5/runs/{run_id}/reviews`. Auditor agents may submit `POST /p5/runs/{run_id}/findings/{finding_id}/proposal`; proposals never finalize conclusions.
4. Final decisions use `POST /p5/runs/{run_id}/findings/{finding_id}/review`. A trusted administrator provisions the human auditor credential separately with `security issue --subject human-reviewer --role auditor --human-auditor`. Use the same Python module invocation as P4 provisioning. Keep this credential outside agent environments. Human identity relies on trusted provisioning. Final review is absent from MCP and denied for MCP-marked requests, clients and ordinary auditor credentials.
5. Create `POST /p5/runs/{run_id}/packages` with `{"upload_id":"<upload-id>","client_name":"<name>"}`. Download `/p5/packages/{package_id}/workpaper.xlsx`, `/memo.pdf`, or `/defensibility.zip`. Inspect the frozen JSON model at `GET /p5/packages/{package_id}` and lifecycle/evidence chips at `/p5/packages/{package_id}/sales/{invoice_id}`.

Review bodies require `outcome` (`EXCEPTION_CONFIRMED`, `EXPLAINED`, `DATA_ERROR`), a reason and `expected_revision` (initially 0). Quantified impact additionally requires `impact_inr` as a nonnegative decimal string with at most two decimal places, resolving `impact_basis_evidence_ids`, and `impact_group`. Findings about the same adjustment share one group and amount; totals count that group once and reject conflicting amounts. Amounts and proposed adjustments are human assertions, not automated accounting verification or journal postings. Unquantified findings are disclosed.

Packages pin snapshot, samples, rules, source hashes, review revisions and log coverage. Later reviews require a new package. Downloads read only the stored package after live data changes. New package creation rejects altered source bytes; P4 maps register/population changes conservatively to affected samples. JSON remains available if source cells exceed Excel limits or contain unsupported XML controls; XLSX/ZIP fail without truncation.

The workbook has the four required workpapers plus Findings, Summary, Impact Groups, Import Metadata, Receipt, Provenance, Coverage, Demonstration Checks and Tickmarks. Sales Register contains only original parsed cells, without added formatting, hashes or formulas. The ZIP includes exact uploaded bytes, workbook, memo, full report, per-sample evidence index, standards candidates, log verification and receipt. Standards candidates require CA review; this is not an NFRA certification.

P5 MCP tools are `create_export_package`, `export_p5_workpaper`, `export_memo`, `get_review_queue`, `propose_review_decision` and `get_p5_lifecycle`. Supply path IDs as arguments and request bodies inside `payload`. Binary exports return base64. The earlier `export_workpaper` retains P1 behavior. P5 artifacts are auditor-only at the API and constrained SQLite boundary.

Optional Demo IRP checks accept evidence type `application/vnd.pramaan.demo-irp+json`: an envelope with `payload` (`invoice_id`, `bill_no`, integer `gross_cents`) and `signature_base64`, signed over Pramaan canonical JSON. Configure a **test public key** as base64 raw Ed25519 bytes in backend `PRAMAAN_DEMO_IRP_PUBLIC_KEY`, then upload and rerun before packaging. Keys are administrator configured; documents cannot change them. Validity is labelled `DEMO_IRP_TEST_ONLY`, never official registration, independent verification or delivery. Audit runtime reads no private signing key.

Physical testing remains an unverified capacity screen. Contract/control dates, official IRP checks, independent assertion verification, other P3 gaps, external anchoring and hosted MCP compatibility remain unavailable. P6 connects lifecycle/reviewer views to the frontend through authorized read models while retaining P5 snapshot and review permissions. Exports are synchronous in this bounded prototype; MASTER's future asynchronous job architecture remains deferred. Byte identity is tested in the installed environment, not promised across upgrades. See [P5_VERIFICATION_REPORT.md](P5_VERIFICATION_REPORT.md). The P6 technical gate passed twice; overall P6 awaits the independent-person blind rehearsal.

# P1 one-sale slice

This is a local synthetic-data prototype for the P1 gate in `../PHASES.md`. It preserves the uploaded register bytes in a SHA-256 content-addressed vault, stores the selected source row separately, links evidence IDs to stored file hashes, snapshots the sale facts, and runs deterministic T06 and assertion-specific T12 rules. It produces JSON findings and a one-sheet XLSX.

T06 uses inclusive absolute tolerances for `value` and `quantity`, and configured exact comparisons for `gstin`, `pin`, and `vehicle_no` in `ruleset.yaml`. Each run stores the full ruleset JSON snapshot and hash; reproduction uses that stored configuration even if the ruleset file later changes. The file uses JSON syntax, a subset of YAML, so no YAML runtime dependency is needed. The import API retains `independently_verified` for compatibility but ignores it; P1 has no independent-verification adapter, so imported evidence cannot receive `SUBSTANTIATED` from a caller-supplied claim. T12 evaluates `occurrence`, `accuracy`, `cutoff`, and `classification` for every sale.

## Run locally

From the repository root:

```powershell
py -m pip install -r Pramaan/backend/requirements.txt
py -m uvicorn Pramaan.backend.app:app --reload
```

P4 now requires bearer credentials for every operation except `/health`; interactive docs are disabled by policy. Use authenticated HTTP or the MCP console described below. Submit `POST /sales` as a client employee with the body in `Pramaan/backend/sample_sale.json`, then use an auditor credential for these audit steps:

1. `POST /sales/DEMO-SALE-001/snapshot`
2. `POST /sales/DEMO-SALE-001/run?seed=demo-seed-1`
3. `GET /sales/DEMO-SALE-001/changes`
4. `POST /sales/DEMO-SALE-001/reproduce?run_id=<returned-run-id>`
5. Download `GET /runs/<returned-run-id>/workpaper.xlsx`; check `GET /integrity`.

To exercise post-snapshot detection, call `PATCH /sales/DEMO-SALE-001/records` with `{"record":"dispatch","field":"value","value":999}` after step 2, then repeat step 3. The prior run reproduces from its immutable stored snapshot, and the change response maps it to the affected sale, run and findings.

The patch requires a client-employee credential. Auditor credentials cannot perform it.

Storage defaults to `Pramaan/backend/data/`; set `PRAMAAN_DATA` to use another local directory. Reset the demo by stopping the server and removing that generated data directory.

## P1 scope and known limits

- Rules are deterministic and local. T06 compares invoice/dispatch `value` and `quantity` when both documents provide the field. T12 reports provenance per assertion and does not infer fraud from company-controlled evidence.
- The register's source file bytes are kept verbatim in the vault. `register_row` is a parsed representation for linking and review, separate from the original bytes.
- The hash-chained event log detects edits to its chain; it is not externally anchored or tamper-proof.
- P4 adds authenticated API/MCP access and constrained SQLite connections. This remains a single-company prototype without PostgreSQL roles, OS/process isolation, external anchoring, or production-grade evidence verification.
- Snapshot comparisons report the affected sale and all findings in its run. Field-level impact mapping and broad lifecycle propagation are later work.
- XLSX is generated with the Python standard library; exported container-byte identity is not promised.

Run the P1 acceptance tests from the repository root:

```powershell
py -m unittest discover -s Pramaan/backend/tests -v
```

## P2 business and T00 API

P2 adds `/p2/customers`, `/p2/sales`, `/p2/journals/{journal_id}`, `/p2/journals/{journal_id}/reverse` (requires a 10–500 character `reason` in the JSON body; human session only, denied on the MCP channel), `/p2/registers`, `/p2/related-parties`, and `/p2/registers/{upload_id}/reconcile`. A sale request creates the order, dispatch, invoice and a balanced receivable/revenue/tax journal together; receipt, credit note and invoice evidence can be supplied in that request. The sales endpoint can be called repeatedly to create a batch.

Posted journal headers and lines reject SQL update/delete; corrections append a reversing journal. Register/related-party source bytes go into the content-addressed vault; parsed rows and comparison metadata are held separately. T00 matches exact bill numbers, detects register-only/system-only rows, and compares Bill No, Date, Customer, Gross Amt and GST No. T00 v2 reports missing/invalid comparison inputs separately as PARSE_REVIEW; it does not silently skip them.

Run the P1 and P2 tests with `py -m unittest discover -s Pramaan/backend/tests -v`. P2 endpoint tests exercise the FastAPI ASGI app in-process; no external server/client interoperability is claimed.

## P3 audit, sampling and evidence requests

P3 adds `POST /p3/datasets/import`, `POST /p3/audit-runs` (period and explicit seed of at least 16 characters), `POST /p3/audit-runs/{run_id}/reproduce`, `POST /p3/audit-runs/{run_id}/rerun`, `GET /p3/audit-runs/{run_id}/evidence-requests`, and `POST /p3/evidence-requests/{request_id}/evidence`. Dataset import reads the fixed synthetic pack under `Pramaan/data/`, checks manifest SHA-256/bytes/row counts and schemas/references/arithmetic, preserves raw source bytes in the content-addressed vault, and writes normalized records transactionally into additive `p3_dataset_*` tables. Audit snapshots include the imported records by dataset ID. A rerun creates a new snapshot using the stored seed; client uploads are provenance-tagged as unverified and do not self-certify.

P3 rules and sample parameters are in `p3_ruleset.yaml`. The 25–35 Sales TOD, cut-off selection, and credit-note selection are deterministic for a snapshot/seed/version. Results explicitly avoid population projection. Imported synthetic sources now exercise T02 candidate edges, T05 unlinked revenue journal detection, T06 invoice/dispatch comparisons, T08 historical concentration signals, T10 test-only threshold patterns, T11 capacity review, T14 price/promotion candidates, and T15 synthetic return-row comparisons. T13 remains external-verification unavailable: placeholder IRNs/status rows are never treated as verified. Test-only policy thresholds and HSN/item mappings are labelled in the versioned ruleset; data-backed candidates are not final audit conclusions. See `P3_VERIFICATION_REPORT.md` for demonstrated checks and remaining gaps.
