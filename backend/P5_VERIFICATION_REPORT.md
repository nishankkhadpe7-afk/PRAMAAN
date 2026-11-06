# P5 verification — 10 October 2026

**Verdict: PASS against the P5 gate for the requested backend demonstration scope.** No frontend or P6 was started. Lifecycle/evidence-chip views are API outputs for a future UI; no existing UI makes unsupported claims. This verdict does not certify the full MASTER target, production deployment or unavailable audit checks.

## Exact PHASES.md acceptance gate

| Gate criterion | Evidence | Status |
| --- | --- | --- |
| Workbook opens cleanly | `test_workbook_opens_source_fidelity_provenance_and_links` opens the generated OOXML with independent openpyxl, checks the four required workpapers, Findings, Provenance/Receipt, sample row counts and Findings hyperlinks. Final workbook has 13 sheets; default styles and relationships parse without workbook warnings. | PASS |
| Every finding has a rule, evidence references, assertion and reason | Same test checks every exported finding's test, rule version/hash, assertion, reason, run/snapshot, source references and sample scope. All evidence IDs resolve to the frozen evidence index, with source/hash/row metadata. T00 uses snapshotted existing P2 reconciliation and its separately identified rule; P3 results are revalidated by the existing engine. | PASS |
| Memo totals reconcile | `test_pdf_pack_totals_and_human_supported_impact` confirms two human-reviewed findings share one INR 100.00 adjustment group. Package, numeric workbook summary, impact-group table and extracted PDF summary agree on INR 100.00 and two confirmed findings. Unquantified findings and lack of projection are disclosed. Each finding ID/assertion appears in the PDF. | PASS |
| Source sales-register sheet unchanged | Original duplicate headers, leading zeros, whitespace, quoted multiline text, blank row, empty fields and formula-like payloads survive unchanged as string cells. Source sheet has no added styles/formulas/hash columns. ZIP returns the exact original BOM/CRLF CSV bytes; receipt SHA256 matches them. Parsed source cells and normalized comparison metadata remain separate. | PASS |
| All UI claims match actual demo capabilities | Backend lifecycle timeline, evidence chips, workpapers and memo explicitly disclose source provenance, absent control dates, missing evidence, unsupported checks and no official verification/anchoring. `test_test_only_signature_capacity_and_evidence_chips` verifies demo-only signature labels and unverified chips. `test_pdf_pack_totals_and_human_supported_impact` checks control-date GAP and lifecycle findings. Frontend implementation is explicitly excluded by the user. | PASS in backend scope |

## Additional deliverable and security evidence

- Four workpapers reproduce MASTER section 10.1 fields; unavailable business/document/control facts remain explicit gaps. Findings includes automated state separately from human outcome, reviewer/reason, impact/group, adjustment and exception status. Provenance, Import Metadata, Receipt, Coverage and Tickmarks carry source references, parsing caveats, seed and rule/sampler/export/canonicalization versions.
- PDF contains per-finding facts versus inference, evidence provenance, assertion, test/rule, candidate standard, human decision, impact, proposed adjustment and unresolved questions. Candidate SA mappings refer to the [ICAI standards index](https://www.icai.org/post/auditing-review-and-other-standards-formerly-known-as-aas-complete-text) and require engagement/CA review; no compliance certification is implied.
- Defensibility ZIP contains workbook, memo, exact register, report model, per-sample evidence index, standards, captured log verification and receipt. It does not package fictitious independent evidence.
- `test_reviewer_permissions_proposals_and_immutable_history`: clients and ordinary auditor agents cannot finalize reviews, a forged human header fails, MCP-marked human credentials cannot finalize, proposals do not become conclusions, revisions append with optimistic concurrency, old packages retain prior conclusions. Clients cannot read/write packages or reviewer artifacts; constrained SQL denies agent final-review insertion and client artifact access. Trigger protections reject review mutation.
- Trusted credential provisioning adds a human-review capability; existing tokens remain ordinary credentials. No API/tool can issue or escalate it. Final review is not advertised as an MCP tool. Existing token expiry/revocation, API policy, denials and SQL boundaries remain active for all new routes.
- `test_reproduction_exports_ignore_live_changes_and_later_review`: repeated packaging with identical inputs yields the same content-addressed ID; XLSX/PDF/ZIP downloads are byte-identical in the installed environment. After changing live customer facts and register bytes, saved exports remain identical, P3 saved-run reproduction succeeds, P4 maps changes to affected samples, and new packaging rejects changed evidence.
- `test_legacy_missing_register_and_package_tamper_fail_closed`: attaching a live register absent from an old run fails. Immutable package triggers reject updates; deliberately bypassing a trigger as administrator still causes independent package-digest validation to reject export.
- `test_test_only_signature_capacity_and_evidence_chips`: Ed25519 demo verification matches covered invoice fields, rejects changed payloads, and reports no-key unavailable. Private test keys exist only in tests. Capacity excess is REVIEW, invalid capacity is GAP, and no unverified input produces IMPOSSIBLE. Demo checks remain separate from persisted P3 findings and do not confirm exceptions.
- The complete P4 adversarial/external MCP suite still passes: identity filtering and per-invocation backend authorization, forged/expired/revoked credentials, auditor API/SQL writes, inert injection fixtures and sample-impact mapping. Its real external console tests exercise stdio and Streamable HTTP; hosted clients remain unverified. New P5 API permissions are tested directly; individual P5 exports have not been separately exercised through hosted MCP clients.

## Actual verification

From `Pramaan/`, on Windows / Python 3.14:

```powershell
$env:PYTHONPATH="$PWD\.."
.venv-p4/Scripts/python.exe -m unittest discover -s backend/tests -v
.venv-p4/Scripts/python.exe -m compileall -q backend
git diff --check
```

- Full suite: **24 passed in 101.205 seconds; zero failures, errors or skips** (18 baseline plus 6 P5).
- Python compilation and whitespace checks passed. Existing synthetic manifest validation, corruption rejection and all P1–P4 assertions passed; no P5 edits to synthetic data or manifest.
- Runtime: MCP 1.30.0, FastAPI 0.128.8, Starlette 0.52.1, ReportLab 4.4.10, cryptography 50.0.2. Independent readers: openpyxl 3.1.5, pypdf 6.20.0; visual rendering: PyMuPDF 1.28.2.
- PDF visual QA: rendered all 62 pages to a contact sheet; inspected summary, finding and final pages at readable resolution; all extracted text blocks fall within page bounds. Workbook previews and cell-level checks cover the required sheets; final independent reader opens all 13 sheets. Native Excel/LibreOffice rendering was not tested. Preview truncation is not export truncation: full values remain in cells.
- Existing standard-library OOXML architecture was retained. The skill-specific spreadsheet artifact runtime is not exposed in this session; independent reading/previewing supplies QA. Some test fixture SQLite connections emit ResourceWarnings on Python 3.14; they did not cause test failures. No security check was disabled to pass tests.

## Remaining limits and scope

- Original source is UTF-8 CSV; workbook preserves its parsed columns/values, while ZIP preserves byte syntax exactly. No native XLSX import/format reconstruction is claimed. Excel cell-length/control-character constraints fail explicitly rather than modifying source values.
- Physical checks validate only arithmetic/synthetic capacity assumptions; route/time, overlap, load estimation and consignee verification remain unavailable. Demo signatures do not close the existing official T13 coverage gap. T03 contracts/control policy, full T12 independent assertion support, full T14, T02 cycles and extended T11 remain as documented in P3.
- References to whole rule-input source files are contextual references, not independently corroborated witnesses. Source/metadata hashes and immutable records establish traceability, not authenticity. Quantified impact requires a human reason and resolving basis references; the engine cannot independently establish the correctness of that accounting assessment.
- Human review capability relies on trusted credential issuance and secure handling, without interactive human-presence attestation or partner sign-off. Review/API views are provided; frontend is not implemented. Synchronous exports are suitable for this bounded prototype; asynchronous jobs from the broader MASTER architecture are deferred.
- SQLite application authorizers/triggers are not PostgreSQL database roles and cannot isolate against the file owner/compromised backend. PostgreSQL migration, tenant isolation and production deployment controls remain outstanding. The existing circular-import/import-order limitation remains; start through `backend.app`.
- Log/snapshots/packages are locally tamper-evident, not externally anchored. A privileged attacker replacing files, hashes and history together remains outside this boundary. Log coverage in each package is pinned to run creation and included review events; current integrity is separately available through P4.
- Byte identity is demonstrated within the installed dependency/platform environment; canonical digest is authoritative across unsupported dependency changes. No population projection, government registration, independent delivery assurance or hosted MCP compatibility is claimed.

No blocker remains for the demonstrated backend P5 acceptance gate. These limits remain outstanding target features rather than completed work.
