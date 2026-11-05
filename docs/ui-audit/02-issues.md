# 02 — UI/UX issues (baseline, 5 Nov 2026)

Evidence = `docs/ui-audit/screenshots/before/…` and `01-baseline.json` (axe, overflow, console, requests).
Data: TEST FIXTURE `.demo/uiaudit` (232 findings, 70 client evidence uploads, 70 samples).
Baseline checks: `tsc -b` clean · Vitest 27/27 · `vite build` OK · Playwright 3/3 · axe: 5 serious rule types, 0 critical.
Not issues: the "failed requests" in the baseline are React StrictMode's dev-only aborted duplicate fetches (each paired with a successful one); the landing console error is a missing `/favicon.ico`.

| ID | Screen | Issue | Evidence | Sev | Proposed fix | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| UI-01 | Finding detail, findings table | AI/agent vs human provenance unclear: the human decision is a raw key/value dump; proposals have no timestamp and cannot be accepted or rejected; the findings table shows "Open review" whether or not an agent proposed something | finding-detail-1440-populated.png, run-findings-1440-populated.png | P0 | `ProvenanceTag` (Automated / Agent proposal / Human decision + actor + time); decision card; "Use as draft" on proposals; table column shows decision vs proposal | M |
| UI-02 | Auditor overview | Decorative "3D Forensic Transaction Network": canvas with random particles, auto-rotation and a false "real-time" claim; it states no fact a reviewer acts on | auditor-overview-1440-populated.png | P0 | Remove; replace with a factual per-run progress table (findings, decided, open, client documents outstanding) | M |
| UI-03 | Run integrity | "0 of 216 requested documents received" for a rerun even though the client uploaded 70 documents for the same sales: a rerun creates new requests that do not link evidence already received | run-integrity-1440-populated.png, client-inbox-1440-populated.png | P0 | Backend dependency (see below); UI copy now scopes the figure to "this run's requests" | backend |
| UI-04 | Finding detail | Copy buttons nested inside `<summary>` (nested-interactive ×9) and 14 px targets (target-size ×9) | 01-baseline.json finding-detail | P0 | Move the copy action out of `summary`; 24 px minimum | S |
| UI-05 | Run findings | 232 findings with no bulk selection, no bulk proposal/decision, no keyboard triage; no "showing N of M" | run-findings-1440-populated.png | P0 | Selectable rows, select-all-filtered, bulk review with preview → confirm → progress → per-item results; keyboard j/k/x | L |
| UI-06 | All signed-in screens | `label-content-name-mismatch` (48 nodes): brand link and chart bars have aria-labels that do not contain their visible text | 01-baseline.json | P1 | Drop the overriding aria-labels; visible text is the name | S |
| UI-07 | Overview, run summary | Chart sub-labels at `--tertiary` fail contrast (4.0:1, 13 nodes) | 01-baseline.json | P1 | Use `--subtle` (≥ 4.5:1) | S |
| UI-08 | Client dashboard, registers, integrity | Scrollable tables not keyboard-focusable (8 nodes) | 01-baseline.json | P1 | `tabIndex=0`, `role=region`, label on `.table-scroll` | S |
| UI-09 | Run summary | Horizontal overflow at 360 (370 px) and 390 (400 px) | 01-baseline.json overflow | P1 | Fix the wide row; assert no overflow in tests | S |
| UI-10 | Run findings | First column is a 40-character technical finding ID; the record and observation are secondary | run-findings-1440-populated.png | P1 | Lead with record + observation; ID secondary | S |
| UI-11 | Run requests / findings | No "request evidence" action exists anywhere; requests are created only by the sampler | 00-discovery.md | P1 | Backend dependency: no API to create ad-hoc evidence requests (see below) | backend |
| UI-12 | Workpapers, PDF memo | Export: nothing says what a package contains before creating it; packages hidden in a select; PDF memo has a wrapping headline figure, a near-empty page 3 and raw codes (`SCREEN_CLEAR`) | run-workpapers-1440-populated.png, /tmp memo render | P1 | "What's included" list, package list with digest/time, generation status; PDF/XLSX layout fixes (no number changes) | M |
| UI-13 | Run summary | No at-a-glance progress: decided vs open, proposals awaiting decision, client documents outstanding | run-summary-1440-populated.png | P1 | Progress strip built from existing context data | S |
| UI-14 | Global CSS | 26 font sizes, 14 radii, 29 gradient/glow rules | 00-discovery.md | P2 | Type/radius tokens; new primitives use only tokens; remove glow on primary buttons | M |
| UI-15 | Assistant | AI answers are marked "Guidance only" but not as AI-generated with model/time in a consistent tag | assistant-1440-populated.png | P2 | `ProvenanceTag kind=ai` on each answer | S |
| UI-16 | Run workspace | Register selector leads with an opaque `REG-…` id | run-summary-1440-populated.png | P2 | Lead with period and row count | S |
| UI-17 | Landing | Missing favicon (404) | 01-baseline.json | P3 | Add SVG favicon | S |

## Backend dependencies (not faked in the UI)
- **UI-03:** `p3.save_run` creates evidence requests for a rerun with `uploaded_docs=[]` even when matching `p3_evidence` already exists for that object and document type. Needed: on request creation, pre-fill `uploaded_docs` from existing evidence for (object_type, object_id, document_type) and log it — a change to evidence-request semantics, so it needs a product decision.
- **UI-11:** no endpoint to create an evidence request for a finding (only the sampler creates them). Needed: `POST /p3/audit-runs/{run}/evidence-requests` with object, document types and reason, auditor-only, logged.
- **Bulk review:** decisions use the existing per-finding endpoints (no bulk endpoint); the UI runs them one by one and reports each result.

## Status after Phase 4/5

| ID | Status |
|---|---|
| UI-01, UI-02, UI-04, UI-05 | Fixed |
| UI-03 | Copy fixed; root cause is a backend gap (logged) |
| UI-06 – UI-10, UI-12, UI-13 | Fixed |
| UI-11 | Backend gap: no evidence-request API (logged, no UI faked) |
| UI-14 – UI-17 | Fixed |
| UI-18 (new, P0) | Fixed: drawer stole focus back to the opener after the first keystroke |

Evidence: `05-after.json`, `screenshots/after/`, `web/e2e/journeys.spec.mjs`. Summary in `docs/UI_UX_AUDIT.md`.
