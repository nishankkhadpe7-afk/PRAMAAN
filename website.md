# Pramaan — Website Implementation Specification

> **Purpose:** Build the Pramaan web experience in parallel with backend work while preserving the architecture and acceptance gates defined in `MASTER.md` and `PHASES.md`.
>
> **Important:** This document does not create, reorder, relax, or replace any phase. A screen being designed or rendered does not mean its backend feature or phase is complete.

## 1. Source-of-truth and document precedence

Use these documents together; each has a different responsibility:

| Document | Authority | It controls |
|---|---|---|
| `MASTER.md` | Product, domain, architecture and security source of truth | What Pramaan does; evidence semantics; API/MCP policy; data integrity; outputs; domain rules |
| `design.md` | Visual design source of truth | Brand, color tokens, typography, spacing, visual hierarchy, component appearance, iconography, motion and design examples |
| `PHASES.md` | Delivery order and acceptance gates | What is implemented when, phase dependencies, acceptance tests and cut/defer decisions |
| `website.md` (this file) | Website implementation contract | Routes, workspace separation, reusable frontend structure, UI states, integration boundaries and frontend acceptance checks |

### Conflict rules

1. Do not copy, reinterpret, or replace the visual values from `design.md`. Read and implement its actual tokens and component rules. If `design.md` provides a token or component, reuse it rather than creating a competing one.
2. `MASTER.md` controls business meaning, permission boundaries, evidence statuses and audit behaviour. A visual design must not change these meanings.
3. `PHASES.md` controls delivery order and acceptance gates. A website task must not bypass a gate or cause later work to be treated as complete early.
4. If a visual treatment appears to conflict with a security, accessibility, evidence, or audit requirement, preserve the functional requirement and adapt the styling.
5. If an API or domain capability is not specified or implemented, show a clearly marked placeholder/mock state or omit the action. Do not invent backend behaviour.

Before implementation, place `design.md` in the repository at the path agreed by the team and inspect it. This file intentionally does not prescribe a separate palette, font family, design-token values, or component library that might conflict with it.

## 2. Product architecture: one platform, two workspaces

**Build one Pramaan product and one web application with two role-based workspaces. Do not build two disconnected applications.**

Pramaan contains two distinct functional domains behind the same application boundary:

- **Business system of record (`biz`)** — client business lifecycle records and accounting journals.
- **Audit and integrity domains (`audit` and `log`)** — audit runs, samples, evidence links, assertions, findings, review decisions, snapshots and integrity events.

These domains need separate schema/role and authorization controls as defined in `MASTER.md`; the website must not combine them into one unrestricted set of permissions. They are functional boundaries inside one platform, not a reason to duplicate the database, rules engine, or business logic.

The product has two primary identities:

| Identity | Workspace | Allowed purpose | Must not do |
|---|---|---|---|
| Client employee | Client Portal | Maintain permitted business records, upload registers and related-party data, respond to evidence requests, submit evidence | Set audit conclusions, change auditor review decisions, or access another tenant's data |
| Auditor | Auditor Workspace | Import/reconcile a register, create audit runs, inspect samples and evidence, run tests, review findings, verify integrity and export workpapers | Create, update or delete business records or journal entries |

The final audit outcome is a human action. An LLM may assist with extraction or draft explanations, but it must not make the final audit decision.

### What counts as a separate system?

- The **business domain** and the **audit/integrity domain** are separate bounded areas of responsibility with strict authorization boundaries.
- The **web UI**, **MCP server**, and **agent console** are different ways to access capabilities. They must use the same API policy and identity permissions; they are not independent copies of the business or audit rules.
- The client portal and auditor workspace should share one deployed frontend shell and shared UI components. Role-specific navigation and pages are permitted; separate codebases or data stores are not required by this design.

## 3. Website objectives and non-goals

### Objectives

1. Make the client evidence-submission workflow and auditor workflow understandable without training.
2. Make every displayed finding traceable to a rule/test, assertion, reason, and evidence reference.
3. Show provenance and uncertainty honestly; do not imply that a document proves more than it actually supports.
4. Provide clear progress for long-running imports, tests, graph analysis and exports.
5. Keep the UI thin: business rules, audit tests, sampling, permissions and final outcomes belong on the server.
6. Allow the design shell and reusable components to be built early using mock data, then connect features to real APIs as their phase gates pass.

### Non-goals

- Do not implement a second audit engine in the browser.
- Do not calculate authoritative tax/accounting results, sample selections, evidence states or final findings in frontend code.
- Do not treat frontend-only role hiding as authorization.
- Do not build every screen to production behaviour before the relevant `PHASES.md` gate passes.
- Do not add complex animations, elaborate charts, an embedded AI chat panel, or additional user roles unless `design.md`, `MASTER.md`, or a later approved requirement calls for them and phase timing permits it.

## 4. Navigation and route map

Use a single React application with a shared shell. Exact URL names can be adjusted to fit the existing repository, but preserve the role boundaries and page purposes below.

### Shared routes

| Route | Purpose | Notes |
|---|---|---|
| `/login` | Authenticate the user | Use the authentication approach actually implemented by the backend; do not invent a frontend-only identity switch |
| `/unauthorized` | Explain that the current identity cannot access the requested view | Avoid exposing protected record details |
| `/` | Redirect to the default workspace allowed for the authenticated identity | Do not assume a role or tenant from a URL parameter |

### Client Portal routes

| Route | Purpose | Priority |
|---|---|---|
| `/client` | Overview and pending actions | Shell/summary first |
| `/client/registers` | Upload sales register, inspect import status, upload related-party details | P2 core path |
| `/client/business` | Browse permitted business records and lifecycle events | P2, only to the extent implemented |
| `/client/evidence-requests` | View outstanding requests and required documents | P3 core path |
| `/client/evidence-requests/:requestId` | Upload/respond to a specific request and see its status | P3 core path |

### Auditor Workspace routes

| Route | Purpose | Priority |
|---|---|---|
| `/auditor` | Engagement/audit-run overview | Shell/summary first |
| `/auditor/runs/new` | Configure an audit run and period | Enable with the backend run-creation capability |
| `/auditor/runs/:runId` | Run summary, selected population and current progress | Incremental by phase |
| `/auditor/runs/:runId/samples` | Samples, stratum, selection reasons, exclusions and coverage | P3 core path |
| `/auditor/sales/:saleId` | Sale lifecycle, relevant facts, evidence and assertion states | P1 minimal vertical slice; widen later |
| `/auditor/runs/:runId/findings` | Findings list with rule, status, reason and impact where supported | P3 core path |
| `/auditor/findings/:findingId` | Finding detail, evidence references, known facts, inference and human review | P3/P5, incrementally |
| `/auditor/runs/:runId/workpapers` | Workbook, memo and receipt exports | P1 simple workbook; required outputs in P5 |
| `/auditor/runs/:runId/integrity` | Snapshot information, log verification and post-test changes | P4/P5 as the corresponding feature passes its gate |

Navigation may show future sections as disabled or not yet available in a development/demo build. Do not present a mocked capability as live. Route guards improve navigation and user experience; all protected API calls must still be authorized server-side.

## 5. Required screen behaviour

### 5.1 Shared application shell

Implement the global header, workspace navigation, page container, notifications/status area and account/session control in accordance with `design.md`.

Requirements:

- Current workspace and active navigation item must be clear.
- The layout must not hide essential status, evidence, or audit-trace information on narrow screens.
- Reuse common page titles, breadcrumbs, tables, empty states, loading states, forms, dialogs and status components.
- Use shared tokens/components from `design.md`; do not introduce one-off colors or arbitrary spacing values where a design token exists.
- A role may see only the navigation relevant to it, but navigation visibility is not a security control.

### 5.2 Client Portal

**Register upload and import status**

1. Accept only file types and size limits allowed by the server contract.
2. Show the chosen file name, type and size before submission.
3. Explain which upload is the original register and which file contains related-party details.
4. Show server validation/import results, row counts and warnings returned by the API.
5. Preserve the source file. The client must not be shown a UI action that edits the original uploaded register in place.
6. Long-running work should display a job state and poll/use the supported status channel; do not block the page indefinitely.

**Evidence-request inbox**

Each request should display its request/sample reference, requested document types, due/status information if returned by the service, and whether a submission is still needed. A submitted file is not automatically labelled independently verified. Display the server-assigned verification/provenance state only.

**Business records**

Allow only actions implemented and authorized for the client-employee identity. If a record is versioned, show its current state and change history when the API provides it. Corrections to posted journal activity must follow the backend's reversal/adjustment workflow; never provide an ordinary edit/delete control for immutable journal entries.

### 5.3 Auditor Workspace

**Audit-run setup and status**

Display the client/engagement and period information the user is authorized to access, status returned by the API, snapshot reference when created, and the current asynchronous job state. Do not claim a snapshot, test run, or integrity anchor exists until the API confirms it.

**Sampling table**

For each selected transaction, show the sample category/stratum, selection reason, key transaction fields, overlap/exclusion state if supplied, and linked finding/evidence availability. Make selected counts and coverage visible. If the backend says the sampling design does not support population projection, do not show projected population values or imply statistical assurance.

**Sale investigation view**

Present the transaction lifecycle as a timeline or structured sequence using facts returned by the API. Show related invoice/order, dispatch, e-way bill, delivery/POD, journal, receipt and credit-note references where available. Do not fabricate missing lifecycle events to complete the visual timeline.

Evidence display must preserve these distinctions:

- Who supplied/controls the evidence and how it was acquired.
- Whether the source was independently verified, according to the server.
- Which exact assertion the evidence supports.
- Whether multiple items derive from one common source.
- What the item does **not** establish, where that limit is important.

Show assertion states distinctly: `SUBSTANTIATED`, `INTERNAL_ONLY`, `GAP`, `INCONSISTENT`, and `IMPOSSIBLE` only where returned by the validated engine. Do not reduce all assertions to a single unconditional "sale proven" label. Treat `IMPOSSIBLE` as reserved for the validated hard-constraint case defined in `MASTER.md`; heuristics should not be upgraded to that state in the UI.

**Findings and human review**

A finding detail should show, when provided by the service:

- Finding ID and test/rule ID and version.
- Assertion affected.
- Plain-language reason and references to evidence IDs.
- Known facts separated from inference or risk indicators.
- Financial impact only when supported by calculated backend data.
- Proposed adjustment as a proposal, not a posted journal or automatic conclusion.
- Human review outcome and reviewer metadata.

Only the authorized human-review workflow may finalize `EXCEPTION_CONFIRMED`, `EXPLAINED`, or `DATA_ERROR`. AI-generated narration must be validated against actual evidence IDs before it is displayed as grounded output.

**Workpapers and integrity**

Show download links only after the server reports that the artifact is ready. Display the receipt/version metadata returned by the service, including applicable snapshot/ruleset/sampler/export information. In the integrity area, distinguish a verified chain, a broken chain, an unavailable/degraded anchor, and unverified state according to actual service results. Never claim tamper-proofness.

## 6. Visual system integration with `design.md`

This document is intentionally visual-system-neutral. The implementation must follow `design.md` for:

- brand/logo usage and product naming;
- color palette and semantic color tokens;
- typography and text hierarchy;
- spacing, sizing, radius, border, elevation and layout grid;
- icon style;
- light/dark mode if specified;
- buttons, links, inputs, tables, tabs, dialogs, tooltips and navigation;
- responsive breakpoints;
- motion, loading animations and reduced-motion behaviour.

Implementation rules:

1. Translate the design tokens into shared frontend variables or theme configuration once; use those tokens throughout.
2. Map semantic states to the tokens defined by the design system. A color must not be the only way to convey a status; include text and, where appropriate, an icon.
3. Keep dense audit data readable. Do not sacrifice column labels, transaction IDs, evidence IDs, reasons or provenance details for visual minimalism.
4. Use tables for dense tabular audit data and responsive alternatives only when the design supports them without losing critical details.
5. Use animation only for feedback or orientation. Animation must never suggest that a background audit has completed before the server says it has.
6. Respect keyboard navigation, visible focus, screen-reader labels, contrast, and reduced-motion preferences.
7. Do not add a competing component library or redesign existing primitives without checking `design.md` and the repository's installed stack.

## 7. Frontend architecture and code organization

The planned stack in `MASTER.md` is **React + Vite**. Follow the actual repository and existing package choices rather than introducing a framework migration. If the repository uses JavaScript, do not convert it to TypeScript solely because this example contains typed naming.

Suggested organization; adapt to the real repository without moving backend or audit-engine responsibilities into the browser:

```text
web/
├── src/
│   ├── app/
│   │   ├── router/              # route definitions and guarded layouts
│   │   └── providers/           # session/theme/query providers as actually needed
│   ├── layouts/                 # shared shell, client layout, auditor layout
│   ├── components/              # reusable design-system-aligned components
│   │   ├── data-table/
│   │   ├── status/
│   │   ├── evidence/
│   │   └── feedback/            # loading, empty, error, confirmation
│   ├── features/
│   │   ├── auth/
│   │   ├── client-portal/
│   │   ├── register-import/
│   │   ├── evidence-requests/
│   │   ├── audit-runs/
│   │   ├── samples/
│   │   ├── sale-investigation/
│   │   ├── findings/
│   │   ├── workpapers/
│   │   └── integrity/
│   ├── lib/
│   │   ├── api-client/           # shared HTTP client and typed API adapters
│   │   ├── permissions/          # UI route/action hints only; not security
│   │   └── formatters/           # presentation-only formatting
│   ├── mocks/                    # synthetic/demo fixtures only
│   ├── styles/                   # design.md tokens mapped to implementation
│   └── main.jsx or main.tsx
├── .env.example
└── package.json
```

Do not create every folder just to match this tree. Add modules when their screen or integration is needed. Keep mocks separate from production API adapters so mock responses cannot accidentally be treated as verified evidence.

### Frontend responsibility boundaries

The frontend may handle:

- rendering, navigation and form input;
- local interaction state and pagination/filter state;
- display formatting and validation for usability;
- invoking the API, displaying server errors and tracking job status;
- confirmation dialogs for human actions.

The frontend must not be the authority for:

- role authorization or tenant isolation;
- sample selection, seeds, probabilities, audit tests or threshold decisions;
- accounting/tax calculations or journal posting;
- provenance/verification status, assertion-state calculation or findings generation;
- integrity hashes, chain verification or snapshot impact analysis;
- final audit conclusions.

## 8. API integration contract

The website communicates with the FastAPI backend using a shared API client. UI requests must hit the same backend policy/domain services used by MCP. Do not call PostgreSQL, the file store, the audit engine, or the MCP server directly from browser code.

### API rules

1. Use the endpoints and request/response schemas actually exposed by the backend/OpenAPI specification. This document deliberately does not invent definitive API paths or payloads.
2. Keep base URL configuration in environment configuration (for example, a Vite public API base URL). Never put a database password, LLM key, signing private key, privileged server token or other secret in a `VITE_*` browser-exposed variable.
3. Every API request must be authorized by the backend using the resolved identity and role. Client-side route guards and hidden buttons are only usability features.
4. Do not let the client send its own trusted provenance state, final finding state, sampling seed/version as if validated, reviewer identity, or security role. The server validates and stores authoritative fields.
5. Follow the authentication/session design already chosen by the backend. Do not invent role-switching controls or rely on a client-supplied role name.
6. Parse and display structured validation errors. Never silently convert a failed request into a successful-looking state.
7. Long-running imports, tests, graph operations, exports and anchoring may return a `job_id`. Display pending/running/succeeded/failed states using the real status API/event mechanism. Add retry only where the action is safe and the backend supports it.
8. Use pagination for large lists. Keep filters/sorts presentation-oriented unless the API supports server-side filtering; do not download the entire audit database to filter in the browser.
9. Treat uploaded files and extracted document text as untrusted data. Do not render uploaded HTML or execute content from evidence files.
10. Log or show correlation IDs when provided so failures can be diagnosed without exposing tokens or sensitive evidence in console logs.

### Error and loading behaviour

Every data-backed screen needs intentional handling for:

- initial loading;
- empty result;
- validation error;
- unauthenticated/expired session;
- forbidden action;
- network/API unavailable;
- asynchronous job still running;
- job failure with a safe retry/recovery path;
- stale data or a record changed after the snapshot;
- partial/degraded integrity verification where applicable.

Keep the user's entered form data after recoverable errors when safe. Disable double submission while a request is in flight; do not treat a button spinner alone as proof of server completion.

## 9. Data and status presentation rules

Use the backend response as the source of truth for domain states. Centralize labels and visual mappings rather than re-creating business logic in each component.

- Preserve the exact raw sales-register values in the designated original-register representation. The UI can show a preview but must not rewrite the imported source values.
- Show original/source values separately from normalized comparison fields where comparison is necessary.
- Distinguish missing evidence (`GAP`) from conflicting evidence (`INCONSISTENT`) and company-controlled evidence (`INTERNAL_ONLY`). None alone means fraud.
- A risk signal is not the same as a confirmed exception.
- An IRN/IRP acknowledgement date after the transaction is a risk indicator, not proof of backdating.
- Demo/synthetic data must be visibly labelled as demo data. A demo signature/key must not be styled or described as real government verification.
- Use server-calculated currency amounts and totals. Apply locale/currency formatting only for display; do not recalculate the authoritative value in the UI.
- Do not claim byte-identical workpaper exports unless the backend/test suite has proved it; show the reproducibility receipt that is actually available.
- Do not expose hidden ground truth, `truth.csv`, private test keys or planted-case metadata to the auditor/operator flow.

## 10. Mock-data and parallel-design mode

Website design can start immediately without waiting for backend completion, provided it does not change phase order.

1. Build the app shell and reusable components using fixtures in `src/mocks/`.
2. Mark mock-only screens and records clearly in development/demo mode.
3. Keep mock types/schema as close as possible to the agreed API response schema. Do not invent fields that imply a backend feature exists.
4. Keep data fetching behind feature-level service functions so mocks can be swapped for real API calls without rewriting components.
5. Do not put mock audit logic in components. A mock finding should be fixed fixture data, not a browser implementation of T00–T15.
6. Use the first vertical slice as the first real integration target. If P1 falls behind schedule, follow `PHASES.md` and defer the UI rather than weakening the P1 gate.
7. Remove or explicitly isolate mock toggles before final demo. The demo must never accidentally present mock results as real engine output.

## 11. Phase-aligned implementation map

This section maps web tasks to the existing plan; it does **not** modify the plan or its gates.

| Existing phase | Website work allowed in parallel | What must still pass before the phase is called complete |
|---|---|---|
| P0 — Preparation | Read `design.md`; establish tokens/components; build static shell and route placeholders; prepare mock fixtures; agree API contract with backend owner | All P0 tasks and the P0 gate in `PHASES.md`; a polished shell does not satisfy data/MCP gates |
| P1 — One-sale vertical slice | Minimal sale page, evidence reference display, simple import/reproduce status and one-sheet workpaper link where useful | P1 flow, mutation-after-snapshot detection, evidence references and logical reproducibility pass. If late, defer UI and use API/JSON viewer as specified in `PHASES.md` |
| P2 — Business system and register | Register upload, import feedback, client business records and reconciliation presentation | Business lifecycle, journals, original-register preservation and T00 reconciliation gate pass |
| P3 — Audit tests, sampling and evidence requests | Sample table/reasons/coverage, evidence-request inbox, evidence upload status, findings list/detail | Required test coverage, innocence traps, reproducible sampling metadata and evidence-request loop gate pass |
| P4 — MCP, identity and post-test integrity | Role-aware navigation, denied-action feedback, integrity view and change-impact display | MCP permissions, API/DB denials, logging, injection fixtures and snapshot change mapping gate pass |
| P5 — Workpapers and demo flow | Workbook/memo downloads, provenance chips, final findings presentation, receipt and integrity views | Required workpapers/memo reconcile; source worksheet unchanged; UI claims match actual features; P5 gate passes |
| P6 — Freeze and rehearsal | Correctness fixes, responsive/accessibility fixes, demo reset/rehearsal checks | Freeze rules and final gate in `PHASES.md`; no new features |

The website team can design future screens while a phase is in progress, but should only integrate or advertise functionality once the corresponding server capability and acceptance criteria are real.

## 12. Quality and acceptance checklist

### Visual and usability

- [ ] All typography, spacing, colors, components and responsive rules follow `design.md`.
- [ ] Layout is usable at agreed desktop, tablet and mobile widths.
- [ ] Focus states, labels, contrast, keyboard access and reduced-motion behaviour are supported.
- [ ] Loading, empty, error, forbidden, pending and success states exist for data-backed flows.
- [ ] Critical statuses are not communicated by color alone.
- [ ] Dense tables retain column meaning, row identity, evidence references and selection reasons.

### Product behaviour

- [ ] Client and auditor workspaces share the same application and backend while exposing only the relevant navigation.
- [ ] A client employee cannot finalize an audit finding.
- [ ] An auditor cannot mutate business records through the UI or API.
- [ ] UI state reflects authoritative server responses and never pretends a long-running job succeeded early.
- [ ] Every finding shown in the live flow can navigate to its rule/test and evidence references when supported.
- [ ] Original register source content is preserved; normalized values and hashes remain separate metadata.
- [ ] Mock/synthetic records are clearly labelled and ground truth is inaccessible to the audit user flow.
- [ ] Unverified or unsupported capabilities are not presented as official verification or production-ready behaviour.

### Integration and security

- [ ] No browser code connects directly to the database, file store, worker or MCP server.
- [ ] No server secret is shipped in frontend assets or public environment variables.
- [ ] Backend authorization is tested independently of UI visibility.
- [ ] Tenant isolation is enforced by the server and data layer, not just frontend filtering.
- [ ] API errors and correlation IDs are surfaced safely; raw tokens and sensitive evidence are not logged to the console.
- [ ] Long-running jobs use actual job status responses and recoverable error states.

### Phase discipline

- [ ] No phase gate in `PHASES.md` has been weakened or marked complete because a screen exists.
- [ ] UI polish has not displaced core audit correctness, evidence provenance, reproducibility or security work.
- [ ] The P1 vertical slice can be completed without depending on the full website.
- [ ] P6 includes only bug fixes and rehearsal work, not new features.

## 13. Recommended build order for the website team

1. Read `MASTER.md`, `design.md`, and `PHASES.md` before implementation. Confirm with the integration owner which backend contracts exist.
2. Build the shared shell, route guards, responsive navigation and basic reusable loading/error/empty components.
3. Use mock data to design the client register-upload flow and auditor sale-investigation flow. Keep the mock layer replaceable.
4. Integrate the smallest working vertical slice first when backend P1 is ready. Do not block P1 on complete navigation, a polished dashboard or advanced visualizations.
5. Add the remaining routes incrementally as their related backend capabilities pass their phase gates.
6. Before the demo, remove accidental mock usage, verify each displayed capability against the actual backend, run the role-denial scenarios, and rehearse the whole flow twice according to `PHASES.md`.

## 14. Definition of done for a website feature

A website feature is done only when:

- it follows `design.md`;
- it uses the shared API contract and existing backend authorization;
- it displays loading, empty, error, forbidden and success states appropriate to the flow;
- it does not duplicate business or audit rules in the browser;
- it is labelled as mock/demo if it is not backed by a real capability;
- it has basic route/component tests or a documented manual test;
- its completion does not imply a `PHASES.md` gate has passed unless that phase's full acceptance criteria also pass.
