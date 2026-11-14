# PRAMAAN — UI/UX Audit & Implementation

Branch `ui-ux-audit`. Evidence lives in `docs/ui-audit/`. Every visual claim below has a matching screenshot in `screenshots/before` and `screenshots/after`, both captured from the same 232-finding fixture (`web/e2e/ui-audit/seed_large.py`).

## 1. Summary

The app was functionally sound, but the most important screens had serious usability and accessibility problems:

- Provenance was unclear. A reviewer could not tell an automated signal from an agent proposal or a human decision.
- 232 findings had to be reviewed one by one, with no keyboard path.
- A decorative 3D "network" took the top of the overview page.
- axe reported 106 serious violation nodes.
- The run summary overflowed horizontally on phones.

All five P0 issues and all P1/P2 issues are fixed or logged as backend gaps, as are the P3 issue and one extra bug found during verification (UI-18). Nothing was faked: where the API cannot support an action, the UI does not offer it.

## 2. Method

- **Phase 0 (`00-discovery.md`):** discovery of routes, roles, components and CSS debt.
- **Phase 1 (`01-baseline.json`, 94 screenshots):** baseline capture of 15 screens at 360/390/768/1024/1440/1920, with axe (WCAG 2.2 AA tags), console errors, failed requests, overflow and sub-24px targets.
- **Phase 2 (`02-issues.md`):** prioritised issues UI-01 to UI-17.
- **Phase 3 (`design-system.md`):** tokens and primitives.
- **Phase 4:** fixes.
- **Phase 5:** recapture into `05-after.json`, keyboard-only E2E and the full test gate.

## 3. Measured results

| Metric (15 screens × 6 widths) | Before | After |
|---|---|---|
| axe serious/critical nodes (360 + 1440) | 106 | **0** |
| Console errors | 1 (favicon 404) | **0** |
| Screens with horizontal overflow | 2 (run summary @360, @390) | **0** |
| Interactive elements under 24 px | 162 | 36* |

\* The remaining 36 are the same inline text link counted once per screen per width. Inline links in a sentence are exempt under WCAG 2.5.8, and axe reports none of them.

## 4. Changes by issue

| ID | Pri | Change | Trade-off |
|---|---|---|---|
| UI-01 | P0 | `ProvenanceTag` (Automated / Agent proposal / Human decision / AI) with actor and time; `DecisionCard` replaces the key/value dump; the table shows decision vs proposal | Adds a tag on every row; it costs some density but removes the ambiguity |
| UI-02 | P0 | Removed the decorative 3D network and replaced it with a factual per-run `ReviewProgress` table | Less visual "wow"; the overview now states facts a reviewer acts on |
| UI-03 | P0 | The copy now scopes the figure to "this run's requests" | **Backend gap:** a rerun does not link evidence already received; the UI only explains this and does not fix it |
| UI-04 | P0 | Copy buttons moved out of `<summary>`; 28 px icon targets | Copy action now sits beside, not inside, the disclosure |
| UI-05 | P0 | Row selection, select-all-matching, j/k/x keyboard triage, "Showing N of M", bulk review drawer (compose → confirm → per-item progress → retry failed) | **Backend gap:** no bulk endpoint; the UI issues one signed request per finding, so 200 decisions are 200 calls (with progress and retry shown) |
| UI-06 | P1 | Removed aria-labels that contradicted visible text | None |
| UI-07 | P1 | Chart sub-labels moved to a ≥4.5:1 token | Slightly less tonal hierarchy |
| UI-08 | P1 | Scrollable tables focusable (`tabIndex=0`, labelled region) | One extra Tab stop per table |
| UI-09 | P1 | Responsive `.hbar`, `insight-grid`, hash wrapping, MCP step cards; 360 px overflow now asserted in E2E | Long hashes wrap mid-string on phones |
| UI-10 | P1 | Record and observation lead; finding ID secondary and muted | The ID is still in the table but no longer the first column |
| UI-11 | P1 | No action added | **Backend gap:** no API to create ad-hoc evidence requests, so "bulk evidence request" is not possible |
| UI-12 | P1 | Workpapers: "Each package contains" list and a Saved packages table. PDF memo: no raw state codes, KPIs fit, hashes moved to a reproducibility appendix, no near-empty pages. XLSX: Contents sheet with hyperlinks, frozen header and widths on the Sales Register | Layout only; every number and hash is unchanged |
| UI-13 | P1 | Progress strip on run summary (decided / open / proposals / documents outstanding) | Built only from existing context data |
| UI-14 | P2 | `system.css` tokens (type scale, radii, semantic colours, focus ring); glow removed from primary buttons | Legacy rules in `styles.css` are left in place (minimal diff); new code uses only tokens |
| UI-15 | P2 | AI answers tagged with the model, or "computed from the run, no AI" | None |
| UI-16 | P2 | Register selector leads with period and row count | Longer option label |
| UI-17 | P3 | SVG favicon | None |
| UI-18 | P0 (new) | `Drawer` re-ran its focus effect on every parent render, so after the first keystroke focus jumped back to the opener (typing a reason was impossible). Fixed by keeping `onClose` in a ref | Found by the keyboard E2E, not by screenshots |

## 5. Backend gaps (logged, not faked)

All three were closed after this audit (see `CHANGELOG.md`, tests in `backend/tests/test_workflow_gaps.py`):

1. **UI-03 (closed):** new and repeated runs start each evidence request with the documents already received.
2. **UI-11 (closed):** `POST /p3/audit-runs/{run}/evidence-requests` (human reviewer only); *Request documents…* on selected findings.
3. **Bulk review (closed):** `POST /p5/runs/{run}/reviews/bulk` and `/proposals/bulk`; the drawer sends 100 findings per call.

## 6. Design system

See `docs/ui-audit/design-system.md`. It defines:

- tokens `--text-xs..xl`, `--r-sm/md/pill`, `--c-ai/human/proposal/automated` and `--focus-ring`;
- primitives `ProvenanceTag`, `EmptyState`, `ProgressBar`, `DecisionCard`, `Drawer` and `Table` (selection, label).

There are no gradients, glow or motion beyond the existing reduced-motion-aware drawer slide.

## 7. Responsive matrix (after)

| Screen | 360 | 390 | 768 | 1024 | 1440 | 1920 |
|---|---|---|---|---|---|---|
| All 15 captured screens | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

✓ = no horizontal overflow and no console errors (from `05-after.json`). The before matrix failed run summary at 360 and 390.

## 8. Accessibility assessment

- axe at 360 and 1440 shows zero violations at any impact level after the changes.
- The keyboard-only E2E (`web/e2e/journeys.spec.mjs`) completes:
  - findings triage: j/k/x selection, then the bulk review drawer;
  - recording two human decisions;
  - export package creation and XLSX download;
  - checking that AI answers carry a distinct label.
- The drawer traps focus, Escape closes it and focus returns to the opener.
- Not verified: screen-reader output (no AT in the sandbox) and colour-blind simulation.

## 9. Ratings (harsh, 1–10)

| Area | Before | After | Why it is not higher |
|---|---|---|---|
| Information clarity / provenance | 3 | 7 | Tags are clear, but provenance history is not yet a timeline |
| Review throughput | 2 | 6 | Bulk works but is N requests; no saved filters |
| Accessibility | 4 | 8 | No AT testing; legacy CSS still has low-contrast decorative text |
| Responsive | 5 | 8 | Wide tables still scroll horizontally inside their region on phones (by design) |
| Visual consistency | 4 | 6 | Legacy `styles.css` still has 26 font sizes; only new and touched code uses tokens |
| Exports (PDF/XLSX) | 4 | 7 | The register sheet is plain; no cover summary chart |

## 10. Verification gate

All checks run on the branch:

- `tsc -b`: clean.
- vitest: 27/27.
- `vite build`: OK.
- pytest: 114 passed.
- Playwright: 7/7, comprising:
  - the workflow tests;
  - the keyboard journeys;
  - the 360 px overflow gate.
- UI-audit capture: 2/2.
