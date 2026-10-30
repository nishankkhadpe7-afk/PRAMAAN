# P6 verification — 10 October 2026

Subsequent T00/MCP follow-up: see [T00_MCP_REGRESSION_REPORT.md](T00_MCP_REGRESSION_REPORT.md) for the corrected versioned reconciliation and latest 35-backend/7-frontend/3-browser verification. Original P6 rehearsal metrics below remain historical evidence. The independent teammate evidence blocker is unchanged.

**Overall P6 verdict: BLOCKED on verification of the independent-person blind rehearsal evidence.** The user reports that the teammate rehearsal is completed, but no scenario record or supporting artifacts were supplied or located in the workspace. Completion is reported, not independently verified. The previously demonstrated final technical gate remains **PASS**: two clean resets ran successfully with held-out cases, resolving findings, post-test change detection, auditor write denial/logging and workpaper downloads. Those automated cases do not establish human participation or operator blindness.

## Independent rehearsal evidence review

Read PHASES.md, DEMO.md and this report; inspected the workspace's rehearsal records, `.demo` directories and existing logs. Only the previously documented automated rounds and browser tests were located. Archived XLSX, PDF and ZIP hashes for both final automated rounds were recomputed and all six match `P6_REHEARSAL_RESULTS.json`. That verifies existing artifacts, not the reported teammate exercise. No reset, new rehearsal, feature change or security change was performed during this review.

| Required independent-rehearsal fact | Available evidence / assessment |
| --- | --- |
| Teammate/operator roles and date | User reports completion; roles, date and participant account not provided. |
| Actual teammate-selected scenario | Not supplied or located; do not attribute the automated bill/amount changes to a teammate. |
| Scenario unknown to auditor operator | Not documented; needs the teammate/operator account of selection, disclosure and assistance. |
| Detection result and finding/run IDs | Not supplied for the independent exercise. Existing automated IDs below remain separate. |
| Resolving source references, hashes, seed and versions | Not supplied for the independent exercise. Requires the matching persisted run/source record. |
| Screenshots or logs | No independent-rehearsal artifacts identified. Existing browser screenshots/recording demonstrate automated UI tests only. |
| Export results and integrity | No independent-exercise exports identified; previous automated export hashes still match. |
| Authorization and post-test impact checks | No independent-exercise checks identified; previous automated results remain valid within their scope. |
| Failures, missed findings or assistance | Unknown; absence of a record cannot establish that none occurred. |

Requested the completed record's location or a participant account with artifact references. Overall P6 remains BLOCKED until the evidence can be matched to the exact gate. This is not a finding that the reported rehearsal failed.

## Phase interpretation and acceptance evidence

The user explicitly authorized the missing React/Vite frontend while requesting P6. Integration was completed before freezing code; thereafter browser correctness fixes and rehearsal verification were performed. PHASES.md/MASTER.md were not changed or their gates relaxed. P1–P5 scopes and limitations remain intact.

| PHASES.md P6 requirement | Actual evidence | Verdict |
| --- | --- | --- |
| Freeze; no new features during rehearsal | Requested frontend/service integration precedes the freeze. Final two HTTP rounds ran sequentially without code edits; subsequent work records documentation/evidence. | PASS |
| One reset command reloads a known clean dataset quickly | `python -m Pramaan.backend.demo reset`: resolved-path guard permits only named children of dedicated `.demo`; no backend/data or source-pack deletion. Existing strict importer, 26 synthetic P2 lifecycles, P1 example, original register/reconciliation and initial audit run. `test_reset_is_bounded_preserves_fixture_hashes_and_source_values` resets twice and compares register bytes, manifest, seed and versions. Final full rehearsals including reset took 7.620/7.349 seconds each. | PASS |
| Rehearse complete demo twice without code edits | `demo rehearse --name final` executed two separate resets and real uvicorn/HTTP processes. Both exercise client actions, evidence response, new snapshot, review boundaries, human-capability decision, all exports, source revision, mapped impacts, denial logging and reproduction. | PASS for automated rehearsal |
| Backup recording and offline narrative | Actual Chrome walkthrough video `.demo/backup/demo.webm` (14 seconds, 1440×1000, 25fps), copied from the successful browser test. WebM demux/remux succeeded and verified the video stream and duration. Login/workpaper screenshots saved alongside it; DEMO.md contains the offline narrative and recreation instructions. No HTTP trace, raw credential header or reusable secret is published. | PASS |
| Judge instructions; short-lived credentials | README/DEMO document API/web/MCP startup and separate client/auditor/human provisioning. 900-second credentials, revocation and per-call validation retained. Source contains no provisioned credentials; generated files are ignored. Browser memory is cleared on reload/sign-out; human credentials are excluded from agent setup. | PASS |
| Teammate independently chooses an undisclosed irregularity | User reports the teammate exercise completed. Its scenario, operator blindness and supporting artifacts are not supplied or located. Existing automated random cases do not substitute for this evidence. | BLOCKED / evidence pending |
| Metrics with seed and versions | Per-round JSON captures manifest, seed, rule/sampler versions, finding, run/package IDs, artifact hashes, counts and elapsed time. Sanitized records are in `P6_REHEARSAL_RESULTS.json`. No precision/recall or human accuracy is invented. | PASS |

## Exact final gate

| Final-gate clause | Evidence from both frozen-code HTTP rounds |
| --- | --- |
| System runs from a clean reset twice | Final round 1/2 launch distinct fresh `.demo/final-1`/`final-2` instances and separate actual API subprocesses; all requests complete with expected HTTP status. |
| Unseen-case test | Fresh randomized register differences: bill `DEMO/26/022`, +7045 cents; bill `DEMO/26/017`, +2935 cents. Existing T00 detects each, without a hardcoded invoice trigger. This does not substitute for a human teammate exercise. |
| Traceable finding | `T00-REG-f50bd6db97dd-22-FIELD_DIFF` and `T00-REG-3908ca32eac6-17-FIELD_DIFF`: persisted run, rule/hash, assertion, reason and resolving snapshot source refs. |
| Post-test change detection | A later source revision is uploaded as a new preserved register. Each prior run detects changed inputs and conservatively maps 54 affected workpaper sample items. Original uploads are never overwritten; P1 versioned mutation tests also remain passing. |
| Auditor write denial | Actual customer-write HTTP request returns 403 in each round; no forbidden row exists and `security_denied` records the auditor actor. Ordinary auditor/client final-review attempts also return 403. |
| Workpaper download | Each round downloads actual XLSX, PDF and ZIP. Saved package bytes remain identical on repeat download after source revision; original register bytes match and saved-run reproduction returns identical. |

Each final round contains 95 automated observations and 54 workpaper items (30 Sales TOD, 23 cutoff, 1 Credit Note TOD; overlaps are not unique transactions). Counts are observations/items, not confirmed statutory exceptions. Fixtures are audit inputs, while T00 reconciles against the existing P2 system-of-record service; fixture register-only observations are not automatically fraud.

Seed: `pramaan-clean-demo-seed-2026`; ruleset: `p3-2026-02`; sampler: `p3-hash-ranked-v1`; canonical manifest SHA256: `32d81c6e60e31f504295ad732da1e14c1e5702e88a5a562c5f7f0ee392f039a3`.

## Frontend and integration verification

- Single React/Vite app, shared session/shell, client/auditor route guards and responsive navigation follow design.md's near-black surfaces, lavender CTA/focus accents, typography fallbacks, radii and breakpoint rules. No fabricated live records, risk scores, official badges or automatic fraud conclusions are used.
- Client workflows: actual dashboard/customers/sales, stored journals/receipts/credits, register/RP uploads, sample evidence inbox/response, provenance and available P1 change history. Auditor workflows: runs/setup, sample tables/reasons/coverage, findings/RP leads, source details, proposals versus human conclusions, immutable packages/downloads, log/change impact and real denial demonstration.
- New `/ui` views are authorized read models over existing tables and P5 snapshot/enrichment logic. No new audit rules, broad migrations or database engine were introduced. Clients cannot read audit-run context/events/download evidence artifacts or modify conclusions; auditor business writes remain blocked by API and SQLite boundaries. MCP tools and final-review restrictions remain unchanged.
- **Backend: 29 passed in 136.259 seconds, zero failures/errors/skips.** Includes all 24 P1–P5 tests and five new web-contract tests. Full Python compilation and `git diff --check` pass. P4 external official-SDK console tests pass on stdio and Streamable HTTP.
- **Frontend: 7 tests passed**, final run 3.02 seconds; `npm run build` and TypeScript checks pass. Final Vite build 3.27 seconds, JS 316.59KB (99.31KB gzip), CSS 16.98KB (4.09KB gzip). Lockfile records installed versions; use `npm ci`.
- **Browser: 2 tests passed in 23.6 seconds**, installed Chrome in fresh headless profiles, real local FastAPI/Vite. Main flow covers create customer/sale, preserved upload/reconcile, audit creation, samples/requests, client document response, role-route denial, versioned rerun, agent-only proposal, separate human decision, XLSX/PDF/ZIP downloads, backend write denial/event, post-test source change, identical frozen XLSX and cleared session on reload. Second test covers 390×844 navigation, no document-level horizontal overflow, rejected invalid credential and client audit-view denial. No page errors occurred in the complete flow.
- Visual QA inspected actual login, populated client dashboard, sampling/workpaper screens and mobile capture. Browser-discovered label/submission-feedback bugs were fixed and the tests rerun; security assertions were retained. Browser coverage is not a production usability or accessibility certification. Tablet/Firefox/Safari and native Office rendering were not exercised.
- The connected Browser runtime reported no available browser. Repo-local Playwright tests used installed Chrome instead. Recording references follow the [official Playwright documentation](https://playwright.dev/docs/videos); no compatibility with hosted MCP clients is inferred from those tests.

Commands: see README.md. Backend logs are `.demo/backend-full.log`; final rehearsal records are `.demo/final-{1,2}/rehearsal.json`; browser evidence/results are `web/test-results`; backups are `.demo/backup`. Generated credentials/data remain ignored; sanitized metrics are saved as a reviewable deliverable.

## Retained limitations and remaining blocker

P3 T03 contract/control policy, full T12 independent assertion verification, official T13/GST/IRP, full T14, T02 cycles and extended T11 remain incomplete. Demo signatures/capacity screens do not close them. Human review relies on trusted credential provisioning, not a human-presence attestation. No partner sign-off or automatic accounting assurance is implemented.

SQLite has no PostgreSQL roles, tenant isolation or protection against a file owner/compromised backend. One company per instance; no external anchor. Hashes establish traceability, not source authenticity. Existing circular imports/import order, synchronous jobs/exports and Python 3.14 fixture ResourceWarnings remain. No runtime ground-truth/private-key access was added. Native XLSX import/Office rendering and cross-upgrade byte identity remain unverified.

Custom evidence requests, external messaging and general P2 field edits are unavailable and disclosed in the UI/demo. P3 changes are demonstrated through new source uploads/evidence snapshots, without rewriting original records. Web credentials are in memory; refresh requires signing in again. Vite development proxy is the tested local hosting setup; production hosting, cross-company isolation, rate limits and hosted MCP compatibility remain unverified.

**Only completion blocker:** supply and verify the reported completed independent-person blind rehearsal record against PHASES.md. Automated technical gate and integrated demo remain verified; overall P6 is not labelled PASS until the independent exercise has evidence.
