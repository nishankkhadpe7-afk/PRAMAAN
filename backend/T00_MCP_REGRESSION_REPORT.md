# T00 normalization and MCP regression verification — 10 October 2026

**Task 1: PASS. Task 2: PASS using the official-SDK console fallback.** Ready for another manual demo after backend/frontend restart, reconciliation and a new snapshot. Overall P6 remains BLOCKED on the independent teammate rehearsal evidence; neither these tests nor the reported live DATA_ERROR review establish that requirement.

## Observed root cause and actual live-source replay

Read-only inspection of `.demo/runtime/p1.sqlite3` found two edited uploads, `REG-37aa9a55f5f7` and `REG-c2bc0af79f12`, each with **26 FIELD_DIFF rows: 26 Date differences and 26 Gross Amt differences**. T00 v1 used trimmed string equality and formatted system cents with two decimal places. Actual examples:

- `DEMO/26/001`: `3/20/2026` versus `2026-03-20`; `25900` versus `25900.00`.
- `DEMO/26/026`: `4/13/2026` versus `2026-04-13`; `58,400` versus `48400.00`.

The saved human review for `T00-REG-c2bc0af79f12-26-FIELD_DIFF` is DATA_ERROR. Its original decision, run and package were not changed. The two edited uploads preserve the same CSV SHA256, `555d134f7453121be7b2994423b382c0f140c19fb43c37954c6b2ad1b9343500`.

Read-only replay of those original register rows against the current system with v2 gives **one FIELD_DIFF per edited upload**, solely `DEMO/26/026 / Gross Amt`: register 5840000 cents, system 4840000 cents, signed difference **1000000 cents / INR 10000.00**. The unedited upload has zero FIELD_DIFF rows. All original source hashes validate. This replay did not persist new audit findings or alter the live demo.

The live demo's 26 P2 invoices lack GSTIN values. V1 silently skipped missing register values; v2 reports these separately as **PARSE_REVIEW/GAP**, never confirmed mismatches or silently equal values. Fixture-only register observations remain separate from the 26 matched business invoices.

## Versioned implementation and acceptance evidence

Rule: `p2-t00-v2`; canonical rule SHA256: `76d6874f617d6e4b9f118f81a1bf7774756e2fbbf606355fd3736f7e743236b8`.

| Requirement | Evidence |
| --- | --- |
| Field-aware equivalent formatting | `test_equivalent_values_and_identifier_boundaries`: calendar ISO/explicit US M/D/YYYY, equivalent exact cents, valid western/Indian grouping, trailing decimal zeros and customer whitespace. No locale guessing or D/M fallback. |
| Exactly the genuine INR 10000 difference | `test_only_edited_amount_differs_original_values_and_hashes_preserved`: 26 matched rows, one amount change, exactly one finding/field, signed cents/INR delta, raw values/hash/bytes unchanged; repeated reconciliation returns the same finding/result. Real Chrome test repeats this using actual isolated-demo business records. |
| Genuine date/customer/GSTIN/amount changes | `test_genuine_date_customer_gstin_and_amount_differences`: one changed row yields all four fields; exact day/cent deltas. Identifiers retain zeros, punctuation, whitespace and case. |
| Missing/invalid values are review inputs | `test_missing_invalid_and_fractional_cent_never_equal` and API review test: malformed groups, non-calendar dates, unsupported date formats, missing fields, fractional cents, exponents and currency symbols are not equal. No rounding/float comparison. |
| Rules and sources are traceable | Additive immutable `p2_reconciliation_rules` stores the canonical contract/hash, including zero-finding reconciliations. Snapshots retain reconciliation history; future views/findings/packages/receipts identify the selected v2 contract. UI displays raw values, normalized statuses/deltas and the actual T00 rule, rather than the P3 configuration. New workbooks include field comparisons. |
| Historical artifacts/reviews stay unchanged | `test_v1_snapshots_reviews_and_all_frozen_exports_survive_v2_reconciliation`: old v1 context, DATA_ERROR decision and XLSX/PDF/ZIP bytes remain identical after new reconciliation/run. Existing v1 contract is unchanged; no historical backfill. Six actual archived final-1/final-2 exports regenerated under the new renderer match their previous recorded hashes. |
| Permissions/regressions | Full P1–P6 suite passes; client reconciliation and auditor business writes still return 403. Snapshot/export/review protections and MCP human-conclusion exclusion remain intact. |

Future snapshots use the most recently invoked versioned reconciliation for each register, including repeated use of a stored comparison; existing snapshots retain their captured interpretation. New v2 finding IDs are distinct from v1 IDs. A new finding requires a new human review; the original DATA_ERROR conclusion is never copied silently. A calculated delta is not automatically a confirmed accounting impact.

Actual final Chrome finding: `T00-v2-REG-ef31e772b031-1-FIELD_DIFF`, run `P3-2bae7ff3dfa39ca6fa`, resolving references `REG:REG-ef31e772b031:1` and `SNAP:invoices:DEMO-I026`. Screenshot: `.demo/backup/t00-field-details.png` (copied from successful browser output and visually inspected).

## MCP executable verification

`test_external_sdk_console_stdio_and_streamable_http` launches separate real uvicorn/MCP processes against an isolated database and uses `Pramaan.backend.agent_console` / official MCP Python SDK 1.30.0 `ClientSession`:

- Both transports initialize and discover tools with authenticated credentials. Client lists include `create_customer` and exclude `create_audit_run`; auditor lists exclude `create_customer`.
- Client calls create customers and complete sales. Those invoice IDs appear through the same `/ui/business` route used by the web app, and direct inspection of that API's database confirms 10000 gross cents.
- Auditor calls verify logs, create runs, select samples, trace parties, retrieve evidence requests and read journals.
- A manually invoked `create_customer` by the auditor fails despite the tool's existence. No FORBIDDEN row is created; backend log includes actor `auditor-1`, channel `mcp`, action `security_denied`, object reference `create_customer:create_customer`.
- Revoked auditor and expired client credentials fail over stdio; HTTP `/mcp` rejects each invalid credential with 401. Role-escalation arguments fail. Existing injection/security tests remain passing.

This satisfies the executable P0/P1/P4 console path within the documented SQLite prototype scope. No connection through hosted ChatGPT, Claude or another hosted client was tested. Backend README specifies exact stdio launch/environment and authenticated Streamable HTTP URL/header requirements; OAuth/public hosted connectivity is not claimed.

## Actual verification results

- Initial targeted T00/P2/official-console suite: **9 passed in 100.282 seconds**. Final targeted T00/P6 read-model suite: **11 passed in 22.091 seconds**.
- Final complete backend suite: **35 passed in 198.946 seconds**, zero failures/errors/skips (29 previous tests plus six T00 regressions). Log: `.demo/t00-full-regression.log`.
- Frontend: **7 passed in 2.78 seconds**; TypeScript/production build passed, Vite 3.38 seconds.
- Final real Chrome suite: **3 passed in 76.355 seconds**, zero unexpected/flaky/skipped tests. Complete client/evidence/human/export/integrity flow, mobile/authentication flow and T00 formatting/details/rule flow. Results: `web/test-results/results.json`. Separate new disposable storage instances and ports 18000/15173 were used; the user's running frontend was not stopped.
- Python compilation and `git diff --check` pass. Hashes of 20 current-demo database/vault/manifest files remain unchanged. Dataset facts/manifest and prior packages/review history were not reset or rewritten.

An initial browser launch found port 5173 occupied and stopped safely; isolated ports resolved it. A TypeScript check caught use of a Node global in the Vite config; using Vite's typed `loadEnv` corrected it. Initial test-harness expectations were corrected to the existing review-queue schema. All final checks pass without relaxed security assertions.

Read-only replay details: `.demo/t00-live-source-verification.json`; preservation fingerprints: `.demo/t00-preservation.json`. Generated credentials remain ignored and absent from this report.

## Retained limitations and manual retest

See backend README for the non-reset retest steps: restart using the same storage, reconcile the edited upload, create a new run/snapshot, inspect the one amount FIELD_DIFF plus disclosed gaps, separately review and create a new package. Old snapshots intentionally retain old findings. P3 coverage gaps, circular/import-order limitation, SQLite/file-owner boundary, no external anchor, unverified official GST/IRP and hosted MCP compatibility remain unchanged. No independent teammate rehearsal completion is inferred. These two follow-up tasks pass; overall P6 evidence verification remains BLOCKED.
