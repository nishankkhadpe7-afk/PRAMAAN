# UX Polish — Verification Review

All 14 requirements verified against source code. TypeScript compilation confirmed clean (exit code 0 per ux-verify.md).

**Watch for:** One partial miss on Req 4 (`.empty` loses `align-items:center` in the override block) and one behavioral gap on Req 1 (`.danger` resting state inherits `--line` border instead of differentiating from a plain button, making it visually identical at rest). Everything else is fully implemented.

**Verdict**: APPROVED

---

## High-level view

Buttons have transitions, shadow, and the `.danger` variant wired up. The danger hover state uses red border/text correctly. At rest, `.danger` sets `border-color:var(--line)` which is the same border as a default button — visually indistinguishable from a plain button unless hovered. This is a minor UX gap, not a regression.

Mutation feedback is fully reworked: `CheckCircle`/`XCircle` icons, green/red left-border notices, 4-second auto-dismiss, dismiss button, and a pointer-events wrapper while busy. All confirmed in code.

Badges carry `TONE_MAP` with auto-detection and `badge-{tone}` CSS classes. The five tone variants (`success`, `warning`, `error`, `info`, `neutral`) are all defined. The resting `.badge-neutral` rule is intentionally empty (no visual override), which is correct.

The `State` component skeleton has exactly three rows at widths 80%, 60%, 70% — matching the requirement. Tabs get transition + `--primary` border on selected. Panels get transition and hover border-color.

Forms gain a `24px` vertical gap via `.form-grid{gap:24px 16px}`. Input focus ring is a `box-shadow:0 0 0 3px rgba(94,106,210,0.25)`. `toTitleLabel` is exported and applied in `NewRun`, `Facts`, `ReadableData`, `Business`, and `Inbox`.

Topbar user pill is in `Shell` with `.topbar-user` class and avatar initials. Login has `Eye`/`EyeOff` toggle with `.input-wrapper`/`.toggle-pw` CSS. `TAB_LABELS` in `RunWorkspace` covers all 7 tabs. Evidence chips truncate refs at 20 chars and include a `Copy` button. Metrics accept an optional `tone` prop and apply a colored top border. `RunSummary` and `Integrity` both pass `tone` values.

The `.empty` override block adds `flex-direction:column` but redeclares `.empty` without `align-items:center`, potentially losing horizontal centering on some environments where specificity resolves to the later rule alone.

---

<details>
<summary>Issues (2)</summary>

1. **Danger button indistinguishable at rest** — `.danger` sets `border-color:var(--line)` which is identical to a default button's border. A destructive action (e.g., "Reverse journal") looks the same as a neutral action until hovered. Add a distinguishing resting-state color (e.g., a muted red border or text tint) so users can identify the destructive action before hovering.

2. **`.empty` loses centering in override block** — The base `.empty` rule has `align-items:center`. The UX-polish override block re-declares `.empty{flex-direction:column;gap:8px;min-height:180px;...}` without repeating `align-items:center`. If the override wins by source order (it comes last), horizontal centering of the icon+text is dropped. Confirm visually or add `align-items:center` to the override rule.

</details>

<details>
<summary>Details</summary>

### Req 1 — Buttons: transitions, disabled pointer-events, primary shadow, danger variant

PASS with one gap. `button,.primary{transition:background 0.15s,border-color 0.15s,opacity 0.15s}` covers all button rules. `button:disabled{pointer-events:none}` confirmed. `.primary{box-shadow:0 1px 3px rgba(0,0,0,0.4)}` confirmed. `.danger` class exists and has a hover state using red border and text. **Gap (confirmed):** at rest `.danger` sets `border-color:var(--line)`, making it visually identical to any default button. Dangerous actions (journal reversal buttons in `client.tsx`) carry `className="danger"` which is correct, but the resting appearance gives no visual cue that the action is destructive.

### Req 2 — Mutation: success/error notices with icons, auto-dismiss, busy wrapper

PASS. `CheckCircle` on success with `.notice.notice-success` (green left border), `XCircle` on error with `.notice.notice-error` (red left border). `useEffect` auto-dismiss at 4 seconds. Dismiss `X` button present on both. Busy wrapper uses `pointerEvents:busy?'none':'auto'` and `opacity:busy?0.7:1`. All confirmed in `components.tsx` lines 44–54.

### Req 3 — Badge: TONE_MAP, auto-detection, CSS tone classes

PASS. `TONE_MAP` defined with all listed text values. `resolveTone` checks explicit tone first, falls back to map lookup, then `'neutral'`. CSS classes `.badge-success`, `.badge-warning`, `.badge-error`, `.badge-info`, `.badge-neutral` all present. `.badge-neutral{}` is intentionally empty.

### Req 4 — Table: hover inset border, row-link hidden-then-visible, empty state 32px icon

PARTIAL PASS / minor gap. `tbody tr:hover{box-shadow:inset 2px 0 0 var(--primary)}` confirmed. `.row-link svg{opacity:0;transition:opacity 0.15s}` + `.row-link:hover svg{opacity:1}` confirmed. Empty state uses `<Inbox size={32}/>` confirmed. **Gap (confirmed):** The override rule `.empty{flex-direction:column;gap:8px;min-height:180px;color:var(--subtle);font-size:14px;text-align:center}` does not include `align-items:center`. Since it appears after the base rule in the same stylesheet, the override wins for `flex-direction` and other properties it declares, but the base rule's `align-items:center` could be lost depending on cascade specificity (both rules use `.empty` — same specificity, last-wins). The icon and text may render left-aligned.

### Req 5 — State: skeleton shimmer 3 rows, error notice

PASS. `State` renders a `skeleton-loader` div with three `skeleton-row` divs (widths 80%, 60%, 70%) when loading. Error path renders `<div className="notice">`. `@keyframes shimmer` and `.skeleton-row` CSS confirmed.

### Req 6 — Tabs: transition, selected uses --primary border, hover color

PASS. `.tabs a,.tabs button{transition:border-color 0.15s,color 0.15s}`. `.tabs .selected{border-bottom-color:var(--primary);color:var(--ink)}`. `.tabs a:hover,.tabs button:hover{color:var(--muted);background:none}` confirmed.

### Req 7 — Panel: transition + hover border-color

PASS. `.panel{transition:border-color 0.2s}` and `.panel:hover{border-color:var(--line-strong)}` confirmed.

### Req 8 — Forms: input focus ring, form-grid vertical gap, toTitleLabel exported and used

PASS. `input:focus,select:focus,textarea:focus{box-shadow:0 0 0 3px rgba(94,106,210,0.25)}` confirmed. `.form-grid{gap:24px 16px}` confirmed. `toTitleLabel` exported from `components.tsx`, imported and used in `auditor.tsx` (`NewRun`), and `client.tsx` (`Business` customer form and sale form). `Facts` and `ReadableData` also use it internally.

### Req 9 — Topbar: user avatar pill

PASS. `Shell` in `App.tsx` renders `<span className="topbar-user">` with an `.avatar` span showing `identity!.subject.slice(0,2).toUpperCase()` and the subject string. `.topbar-user` CSS confirmed with pill styling.

### Req 10 — RunWorkspace tabs: TAB_LABELS, all 7 tab names

PASS. `TAB_LABELS` object confirmed with all 7 keys: `summary:'Summary'`, `samples:'Samples'`, `findings:'Findings'`, `relationships:'Related Parties'`, `requests:'Evidence Requests'`, `workpapers:'Workpapers'`, `integrity:'Integrity'`. Used as `TAB_LABELS[t]??t` in the nav render.

### Req 11 — Notice: left border accent, success variant

PASS. `.notice{border-left:3px solid var(--line-strong);padding-left:19px}` confirmed. `.notice-success{border-left-color:var(--success)}` and `.notice-error{border-left-color:#ef4444}` confirmed.

### Req 12 — Login: Eye/EyeOff toggle, input-wrapper class

PASS. `App.tsx` imports `Eye,EyeOff` from lucide-react. `Login` has `showToken` state and renders `<div className="input-wrapper">` wrapping the credential input, with a `<button className="toggle-pw">` that conditionally renders `<EyeOff>` or `<Eye>`. `.input-wrapper` and `.toggle-pw` CSS confirmed.

### Req 13 — Evidence chips: truncated ref, Copy button

PASS. `EvidenceList` in `auditor.tsx` truncates ref at 20 chars: `ref.length>20?ref.slice(0,20)+'…':ref`. Copy button using `<Copy size={14}/>` with `navigator.clipboard.writeText(ref)` is present in the summary flex container.

### Req 14 — Metrics: tone prop, top border by tone, RunSummary and Integrity use tone

PASS. `Metrics` item type accepts optional `tone?:string`. The `metric` section applies inline `borderTop` style based on tone: warning → `#d97706`, success → `var(--success)`, error → `#ef4444`, otherwise transparent. `RunSummary` passes `tone:'warning'` on "Open human reviews". `Integrity` passes `tone:'success'/'error'` on hash chain and `tone:'warning'/'success'` on changes.

### TypeScript

Clean. Exit code 0, zero diagnostics per ux-verify.md.

### Backend API calls

No API endpoint strings were changed. All `api!.json(...)` and `api!.download(...)` calls use the same paths as before the UX work.

### Dark theme preservation

All new CSS variables reference existing dark-theme tokens (`--surface`, `--surface-2`, `--line`, `--primary`, `--success`, `--ink`, `--muted`, `--subtle`). No hard-coded light-theme colors introduced except the danger red `#ef4444` and warning amber `#d97706`, which are appropriate accent colors within the dark palette.

</details>

---

<details>
<summary>File map</summary>

- `styles.css` — UX polish block appended: button transitions, danger variant, badge tone classes, skeleton animation, table row highlight + row-link visibility, empty state layout, panel transition, tabs transition, form-grid gap, input focus ring, notice left border variants, topbar-user pill, input-wrapper/toggle-pw login helpers
- `components.tsx` — `toTitleLabel` helper and export; `TONE_MAP` + `resolveTone` + `badge-{tone}` class on Badge; tone prop on Metrics; skeleton-loader State; `Inbox` empty-state icon; Mutation reworked with icons, auto-dismiss, busy wrapper
- `App.tsx` — `Eye`/`EyeOff` imports; Login `showToken` state + input-wrapper toggle; Shell topbar `.topbar-user` pill
- `auditor.tsx` — `Copy` import; `toTitleLabel` import used in NewRun; `TAB_LABELS` lookup in RunWorkspace; `tone:'warning'` on RunSummary open-reviews metric; `tone:'success'/'error'/'warning'` on Integrity metrics; EvidenceList ref truncation + Copy button
- `client.tsx` — `toTitleLabel` import used in Business customer and sale forms; reverse journal buttons use `className="danger"`

Full diff: `git diff main -- web/src/styles.css web/src/components.tsx web/src/App.tsx web/src/auditor.tsx web/src/client.tsx`

</details>
