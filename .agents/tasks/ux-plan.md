# Implementation Plan — Pramaan UX Polish

**Typecheck command (run after every item):**
```
cd C:\Users\Harish\OneDrive\Desktop\Pramaan\ELEV19\Pramaan\web && npx tsc --noEmit
```

**Dependency order rule:** Items 1–3 all touch `components.tsx`. Items 4–6 touch `styles.css`. Items 7–9 touch `auditor.tsx`. Item 10 touches `App.tsx`. Item 11 touches `client.tsx`. Items 7–11 must come after items 1–6 because they import things defined in step 2 and rely on CSS classes added in steps 4–6.

---

- [ ] 1. Add `toTitleLabel` helper + update `Facts`, `ReadableData`, `NewRun` field labels in `components.tsx`

  Define and export `toTitleLabel(key: string): string` in `components.tsx`. It splits on `_`, joins with a space, and capitalises only the first character of the entire string (e.g. `period_start` → `Period start`). Replace every `k.replaceAll('_',' ')` in `Facts` and `ReadableData` with `toTitleLabel(k)`. The `client.tsx` `Business` and `Registers` components also use `k.replaceAll('_',' ')` inside `Field label=…` — but those are in `client.tsx`, not `components.tsx`; handle them in step 11 after this helper is exported.

  Files: `web/src/components.tsx`

  Verify: `npx tsc --noEmit` — zero errors.

---

- [ ] 2. Extend `Badge`, `Metrics`, and `Mutation` components in `components.tsx`

  **Badge** — add tone auto-detection and per-tone CSS classes:
  - Accept `tone?: string` prop (default `'neutral'`).
  - Add an internal `resolveTone(text: string, tone: string): string` function that maps badge text to tones using the lookup table in the requirements. The function receives `String(children)` and returns the resolved tone string.
  - Render `<span className={'badge badge-'+resolvedTone}>…</span>`. Do NOT use a plain `tone` string as the class name directly (prevents collisions with existing `.success` class); use prefixed form `badge-success`, `badge-warning`, etc.

  **Metrics** — update item type and add per-metric `tone` styling:
  - Change the `items` prop type to `{label: string; value: ReactNode; note: string; tone?: string}[]`.
  - Inside the `<section className="metric">` element, add an inline style: `style={{ borderTop: item.tone==='warning' ? '3px solid #d97706' : item.tone==='success' ? '3px solid var(--success)' : item.tone==='error' ? '3px solid #ef4444' : '3px solid transparent' }}`.

  **Mutation** — improve feedback:
  - Add `useEffect` import (already imported in the file — check and keep).
  - On `setMessage(success)`, also schedule `setTimeout(() => setMessage(''), 4000)` inside a `useEffect` that watches `message` — or more cleanly, call `setTimeout` directly in the `run` function after `setMessage`, clearing the timeout ref on the next call.
  - Wrap the success notice in `<div className="notice notice-success" role="status">` with a `<CheckCircle size={15}/>` icon from lucide-react and a dismiss `<button className="icon-button" onClick={()=>setMessage('')}><X size={14}/></button>` on the right side.
  - Wrap the error notice in `<div className="notice notice-error" role="alert">` with a `<XCircle size={15}/>` icon and a dismiss button.
  - While `busy`, wrap `children(run, busy)` output in `<div style={{pointerEvents:'none',opacity:0.7}}>…</div>`.
  - Add imports: `CheckCircle, XCircle, X` from `lucide-react`. `X` is already in `App.tsx` but NOT in `components.tsx` — add it here.
  - Keep the children render function signature `(run, busy)` unchanged.

  Files: `web/src/components.tsx`

  Verify: `npx tsc --noEmit` — zero errors.

---

- [ ] 3. Add skeleton `State` loading in `components.tsx`

  Replace the `loading` branch of `State` from the current single spinner line to render a `<div className="skeleton-loader">` containing three `<div className="skeleton-row"/>` elements. Keep the `role="status"` on the outer wrapper. Remove the `RefreshCw` spinner and "Loading authoritative records…" text from the loading branch (keep the error branch unchanged).

  Files: `web/src/components.tsx`

  Verify: `npx tsc --noEmit` — zero errors.

---

- [ ] 4. Add all new CSS rules to `styles.css`

  Append the following blocks to the end of the existing CSS (before the `@media(prefers-reduced-motion:reduce)` block — insert just before that final media query so reduced-motion overrides still apply):

  **Buttons — transitions, pointer-events, shadow, danger variant:**
  ```css
  button,.primary{transition:background 0.15s,border-color 0.15s,opacity 0.15s}
  button:disabled,.primary:disabled{pointer-events:none}
  .primary{box-shadow:0 1px 3px rgba(0,0,0,0.4)}
  .primary:hover{box-shadow:0 1px 6px rgba(94,106,210,0.5)}
  .danger{border-color:var(--line)}
  .danger:hover{border-color:#ef4444;color:#ef4444}
  ```

  **Badge tone variants:**
  ```css
  .badge-success{border-color:var(--success);color:var(--success)}
  .badge-warning{border-color:#d97706;color:#d97706}
  .badge-error{border-color:#ef4444;color:#ef4444}
  .badge-info{border-color:var(--primary);color:var(--primary)}
  .badge-neutral{}
  ```

  **Skeleton loader:**
  ```css
  @keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
  .skeleton-loader{display:grid;gap:12px;padding:16px 0}
  .skeleton-row{height:40px;border-radius:6px;background:linear-gradient(90deg,var(--surface-2) 25%,var(--surface-3) 50%,var(--surface-2) 75%);background-size:200% 100%;animation:shimmer 1.5s infinite}
  ```

  **Table row highlight + row-link arrow visibility:**
  ```css
  tbody tr:hover{background:var(--surface-2);box-shadow:inset 2px 0 0 var(--primary)}
  .row-link svg{opacity:0;transition:opacity 0.15s}
  .row-link:hover svg{opacity:1}
  ```

  **Empty state:**
  ```css
  .empty{flex-direction:column;gap:8px;min-height:180px;color:var(--subtle);font-size:14px;text-align:center}
  .empty svg{color:var(--subtle)}
  ```

  **Panel hover:**
  ```css
  .panel{transition:border-color 0.2s}
  .panel:hover{border-color:var(--line-strong)}
  ```

  **Tabs transition:**
  ```css
  .tabs a,.tabs button{transition:border-color 0.15s,color 0.15s}
  .tabs .selected{border-bottom-color:var(--primary);color:var(--ink)}
  ```

  **Form grid vertical gap:**
  ```css
  .form-grid{gap:24px 16px}
  ```

  **Input focus ring:**
  ```css
  input:focus,select:focus,textarea:focus{box-shadow:0 0 0 3px rgba(94,106,210,0.25)}
  ```

  **Notice variants:**
  ```css
  .notice{border-left:3px solid var(--line-strong);padding-left:19px}
  .notice-success{border-left-color:var(--success)}
  .notice-error{border-left-color:#ef4444}
  ```

  **Mutation notice layout (icon + dismiss button):**
  ```css
  .notice-inner{display:flex;align-items:flex-start;gap:10px}
  .notice-inner>svg{flex-shrink:0;margin-top:1px}
  .notice-inner-body{flex:1}
  .notice-dismiss{margin-left:auto;padding:2px;min-height:unset;border:0;background:transparent;color:var(--subtle)}
  ```

  **Topbar user pill:**
  ```css
  .topbar-user{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:9999px;padding:4px 10px 4px 4px}
  .topbar-user .avatar{width:24px;height:24px;font-size:10px}
  ```

  **Input wrapper (login show/hide):**
  ```css
  .input-wrapper{position:relative;display:block}
  .input-wrapper input{padding-right:44px}
  .input-wrapper .toggle-pw{position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:none;padding:4px;min-height:unset;color:var(--subtle);cursor:pointer}
  ```

  Files: `web/src/styles.css`

  Verify: `npx tsc --noEmit` — zero errors (CSS has no TS impact; this verify confirms the prior TS state is intact after saving styles).

---

- [ ] 5. (No separate item — CSS-only changes are all in step 4.)

  This slot is intentionally skipped to preserve numbering alignment with the requirement sections. Steps 1–4 complete the `components.tsx` and `styles.css` foundation. Steps 6+ build on them.

---

- [ ] 6. Update `auditor.tsx` — tab labels, Badge tones, Metrics tones, EvidenceList chips

  **Tab labels (RunWorkspace nav):**
  - Replace the inline ternary `t==='relationships'?'Related parties':t[0].toUpperCase()+t.slice(1)` with a lookup:
    ```tsx
    const TAB_LABELS: Record<string,string> = {
      summary:'Summary', samples:'Samples', findings:'Findings',
      relationships:'Related Parties', requests:'Evidence Requests',
      workpapers:'Workpapers', integrity:'Integrity'
    }
    ```
    Render `{TAB_LABELS[t] ?? t}` in the NavLink.

  **Badge tones in findings table (RunWorkspace):**
  - The `<Badge>` for `r.state` and `r.human_decision?.outcome||'OPEN_REVIEW'` will now auto-detect tones from the text via the `resolveTone` logic added in step 2. No prop changes needed — just verify the strings match the lookup table (they do: `OPEN_REVIEW`, `EXCEPTION_CONFIRMED`, `EXPLAINED` are all in the map).

  **RunSummary Metrics tones:**
  - Add `tone:'warning'` to the "Open human reviews" metric item (index 1 in the array).

  **Integrity Metrics tones:**
  - For "Local hash chain": `tone: log.data.valid ? 'success' : 'error'`
  - For "Post-test changes": `tone: changes.data.changed ? 'warning' : 'success'`

  **EvidenceList — ref truncation + copy button:**
  - Add `Copy` to the lucide-react import at the top of `auditor.tsx`.
  - In `EvidenceList`, change the `<details>` summary JSX:
    - Make `<summary>` use `style={{display:'flex',alignItems:'center',gap:'8px',flexWrap:'wrap'}}`.
    - Render the ref as `{ref.length > 20 ? ref.slice(0, 20) + '…' : ref}` inside `<strong>`.
    - After the `<Badge>`, add:
      ```tsx
      <button
        className="icon-button"
        title="Copy reference"
        onClick={e => { e.preventDefault(); void navigator.clipboard.writeText(ref) }}
      >
        <Copy size={16}/>
      </button>
      ```

  **Requests tab — add Badge tones:**
  - The `<Badge>` in `Requests` already renders `'Awaiting client upload'` and `'Fulfilled'` — these will auto-resolve to `warning` and `success` via the tone detection from step 2. No extra changes needed.

  **Danger class on reverse journal buttons (auditor.tsx `Business` detail panel):**
  - Note: Reverse journal buttons are in `client.tsx`, not `auditor.tsx`. Handle in step 8.

  Files: `web/src/auditor.tsx`

  Verify: `npx tsc --noEmit` — zero errors.

---

- [ ] 7. Update `App.tsx` — topbar user pill + login show/hide password

  **Topbar user pill (Shell component):**
  - `identity` is already destructured from `useSession()` in `Shell`. It has `.subject: string`.
  - Inside the topbar `<div>` (the second div in the topbar, currently empty / just breadcrumb), add a second sibling div after the breadcrumb div:
    ```tsx
    <span className="topbar-user">
      <span className="avatar">{identity!.subject.slice(0,2).toUpperCase()}</span>
      {identity!.subject}
    </span>
    ```
  - The topbar currently has `<div className="topbar"><div>…breadcrumb…</div></div>`. Wrap both parts properly so the pill floats right: the topbar already has `justify-content:space-between` in CSS, so just add the pill as a second child of the topbar's outer div. Current structure is `<div className="topbar"><div>…</div></div>` — change to `<div className="topbar"><div>…</div><span className="topbar-user">…</span></div>`.

  **Login — show/hide credential toggle:**
  - In `App.tsx` `Login` component, add `const [showToken, setShowToken] = useState(false)` alongside the existing `const [token, setToken] = useState('')`.
  - Add `Eye, EyeOff` to the lucide-react import at the top of `App.tsx`.
  - Replace the `<Field label="Access credential"><input type="password" …/></Field>` block with a raw field (no `Field` wrapper, since `Field` uses `cloneElement` and the toggle button is a sibling of the input inside the wrapper, which would confuse cloneElement):
    ```tsx
    <div className="field">
      <label htmlFor="credential-input"><span>Access credential</span></label>
      <div className="input-wrapper">
        <input
          id="credential-input"
          type={showToken ? 'text' : 'password'}
          name="credential"
          autoComplete="off"
          value={token}
          onChange={e => setToken(e.target.value)}
          required
          placeholder="Paste your provisioned credential"
        />
        <button
          type="button"
          className="toggle-pw"
          aria-label={showToken ? 'Hide credential' : 'Show credential'}
          onClick={() => setShowToken(v => !v)}
        >
          {showToken ? <EyeOff size={16}/> : <Eye size={16}/>}
        </button>
      </div>
    </div>
    ```

  Files: `web/src/App.tsx`

  Verify: `npx tsc --noEmit` — zero errors.

---

- [ ] 8. Update `client.tsx` — toTitleLabel for field labels + danger class on reverse buttons

  **Field label helper:**
  - Import `toTitleLabel` from `./components` at the top of `client.tsx`.
  - In `Business`, replace all `k.replaceAll('_',' ')` used inside `<Field label={k.replaceAll('_',' ')}>` with `toTitleLabel(k)`. There are two such loops: the customer form and the sale form fields.
  - In `Registers`, the `<Field label="Period">` and `<Field label="Source type">` are already plain strings — no change. No `replaceAll` loops in `Registers`.

  **Danger class on reverse journal buttons:**
  - In `Business`, the `detail.journals` reverse button currently renders as a plain `<button>`. Add `className="danger"` to each reverse button so it picks up the red-on-hover border from step 4.

  Files: `web/src/client.tsx`

  Verify: `npx tsc --noEmit` — zero errors.

---

- [ ] 9. Final typecheck pass + fix any remaining errors

  Run `npx tsc --noEmit` from inside `web/`. If any errors remain from the previous steps (e.g. unused imports, wrong prop shapes, missing keys), fix them in the relevant file. Common things to watch for:
  - `Metrics` items in `auditor.tsx` must now accept the optional `tone?` field — TypeScript should accept optional props without errors, but verify.
  - `Badge` receives `tone?` as an optional prop — verify the default `'neutral'` value is correctly typed.
  - `CheckCircle`, `XCircle`, `X`, `Copy`, `Eye`, `EyeOff` all exist in `lucide-react@0.545.0` — verify the import names are correct (`X` is the close/cross icon in lucide-react).
  - The `Mutation` busy-wrapper `div` wrapping `children(run, busy)` — since `children` already returns `ReactNode`, wrapping it in a `div` is valid. No type issue expected.

  Files: whichever file has the remaining error.

  Verify: `npx tsc --noEmit` exits with code 0 and prints no diagnostics.

---

## Dependency Graph Summary

```
Step 1  ──► components.tsx  (toTitleLabel helper)
Step 2  ──► components.tsx  (Badge tones, Metrics tone prop, Mutation feedback)  [depends on step 1 being in same file]
Step 3  ──► components.tsx  (State skeleton)                                    [independent of 1&2, same file edit]
Step 4  ──► styles.css      (all new CSS classes)                               [independent — pure CSS]
Step 6  ──► auditor.tsx     (uses Badge auto-tone from step 2, CSS from step 4) [must come after steps 1–4]
Step 7  ──► App.tsx         (topbar pill CSS from step 4, Eye/EyeOff icons)     [must come after step 4]
Step 8  ──► client.tsx      (toTitleLabel from step 1, danger class from step 4)[must come after steps 1&4]
Step 9  ──► any file        (cleanup pass)                                      [must come last]
```

Steps 1, 2, and 3 all edit `components.tsx` — they should be done as a single editing session on that file to avoid save conflicts. The implementer should apply all three sets of changes to `components.tsx` before moving to `styles.css`.

---

## What NOT to change

- No backend API calls, route paths, or data-fetching logic
- No light mode, no color-scheme switch
- No `any` regressions in TypeScript types
- `Field` component interface stays unchanged (cloneElement pattern preserved; Login bypasses Field intentionally)
- `Mutation` children render signature `(run, busy)` stays unchanged
