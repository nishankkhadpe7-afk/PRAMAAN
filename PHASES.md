# Pramaan — Build phases and acceptance gates

> **Build rule:** one complete vertical slice first, then widen. A phase is not complete because code exists; its acceptance test must pass. The 36-hour schedule is an aggressive plan for four people **after P0 preparation is already complete**, not a guarantee that the entire target scope can be finished in 36 hours.

## Team ownership

| Role | Owns |
|---|---|
| **E — Engine & integrity** | Evidence provenance, T00–T15 as prioritised, sampling, snapshots, audit log and physical plausibility |
| **B — Backend & domain** | Schema, business lifecycle, journal posting, authorization policy and API |
| **M — MCP & AI** | MCP server, identity mapping, tool policies, extraction/narrative guardrails and agent-console fallback |
| **W — Workpapers, UI & data** | Synthetic generator/checker, import/export, workbook/memo and minimal React screens |

One person should be the integration owner responsible for keeping `docs/MASTER.md`, migrations, API contracts and the runnable demo aligned.

## P0 — Preparation before the event

| Task | Done when |
|---|---|
| Synthetic generator and hidden `truth.csv` | Same seed produces stable canonical data; audit runtime cannot read `truth.csv` or private test keys |
| Sales-register export | Columns match the official reference shape; original upload can be preserved verbatim |
| Schema and database roles | Migrations run cleanly; direct SQL writes by auditor role fail; tenant isolation tests exist |
| Versioned `ruleset.yaml` | Thresholds, tolerances, supported assertions and uncertain-input treatment are documented |
| MCP hello-world | A tool can be listed and called through at least one intended judge client; test a second client if time allows |
| Test-only signed payload | Demo sign/verify passes; tampering fails; all screens clearly label it as a test-only signature |
| CA mentor review | Review cut-off assumptions, sampling, proposed workpaper fields and accounting examples |

**P0 gate:** the synthetic dataset is reproducible, the app never sees the ground-truth file, and one authenticated MCP call works from outside the local process.

## P1 — One-sale vertical slice (0–6 hours)

**Goal:** import one row → preserve source → link system-of-record facts/evidence → run T06 and assertion-specific T12 → create a finding with evidence IDs → append integrity log → reproduce the logical workpaper result.

Minimum deliverables: party, invoice, dispatch, evidence, evidence-link and audit-event records; import vault; two deterministic tests; simple JSON finding; one-sheet XLSX export.

**Gate:** change one fixture value after snapshot creation. Pramaan detects the difference, identifies the affected transaction, and reproduces the same result for the same snapshot/rule/seed versions. A finding must link to stored evidence IDs that resolve.

**If behind:** defer the web UI and use API plus a small JSON review page. Do not skip provenance or the reproducibility receipt.

## P2 — Minimal business system and register reconciliation (6–13 hours)

Implement the smallest business lifecycle required to create traceable transactions: customer, sales order, dispatch, invoice, journal, receipt, credit note and supporting evidence. Add register upload and related-party upload, preserving source content and recording comparison metadata separately. Implement double-entry balance checks, reversal-only journal correction and T00 register-to-system reconciliation.

**Gate:** a script creates a batch of synthetic sales through the API; journals balance; an ordinary role cannot update/delete posted journal lines; T00 detects one planted register-only row and one field difference.

**Scope control:** enquiries/quotations and promotions can be represented minimally if required for a tested scenario. Do not build all UI screens before the gate passes.

## P3 — Audit tests, sample selection and evidence requests (13–20 hours)

Implement versioned rules for related-party tracing, cut-off review, missing expected movement evidence, revenue without a sale, document mismatch/reuse, credit notes and GST reconciliation as data allows. Add the 25–35-item Sales TOD design, the prescribed year-end cut-off sample, and Credit Note TOD. Record sample reasons, snapshot ID, persisted seed, rule/sampler versions, overlaps and exclusions. Implement the client evidence-request loop.

**Gate:** representative planted classes are detected; innocent traps are not left as confirmed exceptions; rerunning with the same snapshot, stored seed and versions returns identical selections/reasons; sampling limitations are shown where population coverage is incomplete.

**Caution:** do not claim statistical projection unless the sample design and inclusion probabilities support it and a qualified reviewer approves the method.

## P4 — MCP identity, authorization and post-test integrity (20–26 hours)

Expose client-employee and auditor toolsets through MCP. Every call resolves to a validated identity and passes API authorization. The MCP process has no direct DB access. Use constrained database roles/connection pools so an auditor identity cannot write business tables even if a tool call is manually constructed. Add role-filtered `tools/list` for usability, per-call authorization, tool-call logging, prompt-injection test fixtures, snapshot comparison and change-to-sample impact mapping.

**Gate:** a client token can perform permitted lifecycle actions; an auditor token can run read/audit actions; auditor write attempts are denied by the backend and DB boundary and logged; injected document instructions cause no unauthorized state change. Test the exact external MCP client(s) used for judging.

**Fallback:** if a specific hosted AI client cannot connect, use the supplied agent console over the same MCP server; do not misrepresent a local console test as interoperability with every model.

## P5 — Workpapers, differentiated tests and demo flow (26–32 hours)

Finish the four required workpaper sheets, findings sheet, provenance/receipt sheet and PDF findings memo. Add evidence chips and a clear sale-lifecycle view. Add physical plausibility and signed-payload tests only to the level supported by the validated input assumptions. The synthetic Demo IRP key must be visibly distinct from a real official-verification status. Verify that totals in the workbook and memo reconcile.

**Gate:** the workbook opens cleanly; every finding has a rule, evidence references, assertion and reason; memo totals reconcile; the source sales-register sheet is unchanged; all claims in the UI match actual demo capabilities.

## P6 — Freeze and rehearse (32–36 hours)

- No new features; bug fixes only.
- One reset command reloads a known clean dataset quickly.
- Rehearse the complete demo twice without editing code.
- Keep a backup demo recording and offline narrative fallback.
- Prepare judge instructions with short-lived credentials; never place reusable secrets in a public README.
- Run an adversarial rehearsal where a teammate chooses an irregularity not disclosed to the auditor operator.
- Capture actual metrics with the dataset seed and ruleset versions.

**Final gate:** the system runs from a clean reset twice, including an unseen-case test, traceable finding, post-test change detection, auditor write denial and workpaper download.

## Feature priority and cut list

### Protect first (core challenge path)

1. Original-register preservation and T00 register-to-system reconciliation.
2. Assertion-specific evidence provenance with honest `SUBSTANTIATED` / `INTERNAL_ONLY` / `GAP` / `INCONSISTENT` states.
3. Cut-off analysis that requires contract facts and escalates uncertainty.
4. Risk-aware sample selection with recorded reasons and reproducible reruns.
5. Evidence request/review loop and required workpaper outputs.
6. Auditor cannot write to business records; MCP actions are authorized server-side.
7. Snapshot/post-test change detection, impact mapping and tamper-evident log.
8. Synthetic planted cases and innocent traps with measured results.

### Defer if the gates are not passing

1. Regional-language OCR and broad document-type coverage.
2. OAuth beyond the tested token scheme.
3. Full offline/on-premise packaging and a promise of zero outbound network traffic.
4. Full real NIC/IRP integration before the official verification process is validated; keep clearly labelled test-only signing for the demo.
5. Counterparty cycle detection and threshold-splitting rules if core checks are incomplete.
6. GSTR-3B and complex tax-return handling if the available fixtures do not support reliable tests.
7. Animated dashboards, fancy charts and elaborate UI polish.

Do not call deferred requirements complete. If an official requirement is not implemented, state it in the demo and documentation rather than substituting a mock and implying production verification.

## Risk register

| Risk | Mitigation |
|---|---|
| Judge introduces an irregularity absent from the fixture set | General rules, held-out seeds, and adversarial rehearsal; do not hardcode transaction IDs |
| MCP client compatibility varies | Test actual clients; provide agent console fallback; use per-judge revocable credentials |
| LLM rate limits or outage | Core checks run deterministically without an LLM; cache only non-authoritative demo narratives |
| Scope creep | Acceptance gates and deferred list; freeze features in P6 |
| Incorrect accounting/cut-off assumptions | CA mentor reviews policy mappings and sample workpapers; uncertain cases go to review |
| Evidence looks real but is synthetic | Prominent DEMO labels and separate demo-key verification status |
| False positives overwhelm auditor | Innocent traps, per-class precision/recall and explicit review outcomes |
| Anchor or storage service unavailable | Report degraded verification state; do not claim an unanchored log is externally anchored |
