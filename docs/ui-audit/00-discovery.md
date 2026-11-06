# 00 — Discovery (UI/UX audit, Nov 2026)

## Stack
- React 19 + TypeScript 5.9, Vite 7, react-router-dom 7 (`BrowserRouter`), lucide-react icons. No component library, no Tailwind: four global CSS files (`styles.css` 46 KB, `charts.css`, `workflow.css`, `theme.css`).
- Data layer: `useData(path, refresh)` hook over `makeApi()` (fetch, bearer token from `session.tsx`); mutations through the `Mutation` render-prop. No cache library.
- Tests: Vitest + Testing Library (jsdom), Playwright (`web/e2e`, Chrome channel). API: FastAPI on :8000; Vite dev proxy `/api` → API.
- Run: `PYTHONPATH=<repo>/launcher python -m Pramaan.backend.demo reset --name <instance>` seeds synthetic data through the real API and prints nothing secret (tokens in `.demo/<instance>/session-credentials.json`); then uvicorn + `npm run dev`.

## Already fixed (remediation, 5 Nov) — do not redo or regress
Inline field errors on New run (U2), mobile sign-in order (U3), plain copy on sign-in/landing (U4), mobile tab fade (U5), `nowrap` IDs (U6), self-hosted fonts (U7), "Frozen snapshot" pill (U8), wrapped chart labels (U9), findings sorted by severity (U1 partial), tab-scoped session (F5), drawer focus trap (F7), lazy routes (F8), row double-click (F3), server error messages (F4/H4), no polling on frozen views (F1).

## Routes → screens → key components
| Role | Route | Screen | Key components |
| --- | --- | --- | --- |
| public | `/` | Landing | `Landing`, print ornaments |
| public | `/login` | Sign in | `Login`, `Mutation` |
| client | `/client` | Dashboard | `Metrics`, `Table`, `Panel` |
| client | `/client/business` | Business records (create customer/sale, reversal) | forms, `Table` |
| client | `/client/registers` | Register / disclosure upload | file form |
| client | `/client/evidence-requests[/:id]` | Evidence inbox | `Inbox`, upload form |
| auditor | `/auditor` | Overview | `Metrics`, `TransactionNetwork3D`, `HBars`, runs table |
| auditor | `/auditor/runs/new` | New run | `NewRunForm` |
| auditor | `/auditor/runs/:id/{summary,samples,findings,workpapers,integrity}` | Run workspace | `RunSummary`, `FindingsView`, `Requests`, `Integrity`, `CryptographicChainView` |
| auditor | `/auditor/findings/:id?run=` | Finding detail + review form | `EvidenceList`, review form |
| auditor | `/auditor/sales/:id` | Sale lifecycle | `Facts` |
| auditor | `/auditor/assistant` | MCP assistant | `AuditGuide` |
No admin role exists (credentials are issued by CLI).

## Design-system inventory
- Tokens (`styles.css :root`): colour (`--ink/--muted/--subtle/--tertiary`, 4 surfaces, `--success/--warning/--error`, gold primary), spacing scale `--space-1…10`, radius ×3, one shadow, three font families.
- Drift: **26 distinct font sizes** (11–58 px, incl. 12.5/13.5/14.5/15.5), **14 border radii**, 29 gradient/glow rules, 17 inline `style={{}}` uses, 18 hard-coded hex colours in TSX.
- Shared components: `Header, Panel, Table, Metrics, Facts, ReadableData, Badge, Field, Mutation, Drawer, State` (components.tsx); charts in charts.tsx. Missing: ConfirmDialog, EmptyState (inline text only), Toast/live-region primitive (per-Mutation notices), ProvenanceTag, sortable/selectable DataTable.
- Bypasses: `visualizations.tsx` (44 KB) renders its own cards, colours and a canvas "3D network" with random particles; `theme.css` is a second visual language for Landing.

## Core journeys (as built)
1. **Auditor audit:** New run → (reconcile on Overview) → Findings tab (filter chips, severity order) → open finding → record decision (human credential) → Integrity tab → Workpapers (package + downloads). *No bulk triage; evidence requests are auto-created by the sampler (no "request evidence" action exists in the backend).*
2. **Client evidence:** sign in → Dashboard counts → Evidence inbox (one row per run request) → upload document → status chip.
3. **Assistant:** pick run → ask / demo prompts → answer with tools used. *Answers are guidance only; there is no "act on recommendation" action.*
4. **Agent proposal → human decision:** proposals stored via MCP (`/p5/.../proposal`) and listed in run context; human records decision on finding page.
5. **Client books:** create customer → create sale → upload register → disclosure upload.
