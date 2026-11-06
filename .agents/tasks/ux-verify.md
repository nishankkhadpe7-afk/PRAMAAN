# UX Polish — Verification

## TypeScript check

Command: `npx tsc --noEmit` (run from `web/`)

Result: **Exit code 0 — zero diagnostics.**

## Changes implemented

### components.tsx
- Added `toTitleLabel` helper (split on `_`, capitalise first char)
- Badge: added `TONE_MAP` + `resolveTone` auto-detection, `badge-{tone}` class names
- Metrics: added optional `tone?` prop with inline `borderTop` style
- Facts / ReadableData: switched from `replaceAll('_',' ')` to `toTitleLabel`
- Mutation: added `useEffect` auto-dismiss (4s), `CheckCircle`/`XCircle`/`X` icons, dismiss button, pointer-events wrapper div, `notice-success`/`notice-error` classes
- State: replaced spinner with skeleton-loader (3 skeleton rows)
- Table: replaced `FileText` with `Inbox` icon, empty state paragraph
- Exported `toTitleLabel`

### styles.css
- Button transitions + `pointer-events:none` on disabled + shadow on `.primary`
- `.danger` class (hover red border/text)
- `.badge-success/warning/error/info/neutral` variants
- Skeleton loader (`@keyframes shimmer`, `.skeleton-loader`, `.skeleton-row`)
- `tbody tr:hover` inset left border (`box-shadow: inset 2px 0 0 var(--primary)`)
- `.row-link svg` opacity transition
- `.empty` flex-column with gap
- `.panel` transition + `:hover` border
- `.tabs` transition, `.selected` uses `var(--primary)`, hover no background
- `.form-grid` vertical gap `24px`
- `input/select/textarea:focus` ring
- `.notice` left border, `.notice-success`/`.notice-error` variants
- `.notice-inner` / `.notice-dismiss` layout helpers
- `.topbar-user` pill
- `.input-wrapper` + `.toggle-pw` for login show/hide

### auditor.tsx
- Imports: added `Copy`, added `toTitleLabel` from components
- `NewRun`: `toTitleLabel(k)` for field labels
- `RunWorkspace`: `TAB_LABELS` lookup object for tab names
- `RunSummary`: `tone:'warning'` on "Open human reviews"
- `Integrity`: `tone:'success'/'error'` on hash chain, `tone:'warning'/'success'` on changes
- `EvidenceList`: ref truncation at 20 chars, flex summary, Copy button

### App.tsx
- Imports: added `Eye, EyeOff`
- `Login`: `showToken` state, inline `.input-wrapper` + `.toggle-pw` show/hide field
- `Shell` topbar: added `.topbar-user` pill with avatar initials + subject

### client.tsx
- Imports: added `toTitleLabel` from components
- `Business`: customer form + sale form field labels use `toTitleLabel(k)`
- Reverse journal buttons: added `className="danger"`
