# Frontend/backend integration review — 11 October 2026

The frontend uses authenticated FastAPI endpoints through Vite's `/api` proxy. Operational counts and statuses come from saved snapshots or live service responses. Descriptive labels, help text, and limitations remain ordinary interface copy.

| Feature | Backend integration |
| --- | --- |
| Login and role access | `/p4/identity`; server validates credentials and permissions |
| Client business records | `/ui/business`, `/p2/customers`, `/p2/sales`, journal reversal and P1 version APIs |
| Registers and disclosures | `/ui/registers`, `/p2/registers`, `/p2/related-parties` |
| Evidence inbox | `/ui/inbox`, requested-evidence submission API |
| Audit overview | `/ui/runs`; saved observation counts include the selected register's frozen reconciliation |
| New audit run | `/ui/audit-setup` supplies current coverage and date defaults; `/p3/audit-runs` freezes the run |
| Summary and samples | Saved run context, sampler coverage and reproducibility API |
| Findings | Saved context includes audit and selected-register findings; related parties are available through a category filter |
| Evidence requests | Live evidence-request API, displayed as a Samples sub-section |
| Human review and proposals | P5 review/proposal APIs; final-review permission stays server enforced |
| Workpapers | P5 immutable package creation, package loading and XLSX/PDF/ZIP download APIs |
| Integrity | Local hash-chain verification, post-test changes and audit-event APIs |
| MCP assistant | Backend configuration, saved run summary and read-only MCP tools; external provider response awaits separate approval |

## Corrections

- Simplified the main engagement navigation to Summary, Samples, Findings, Workpapers and Integrity. Old related-party and request URLs redirect into the corresponding sub-sections.
- Preserved register selection in URLs across tabs and detail pages. Packages are scoped to their actual run and register.
- Removed stale package details during loading, errors and deselection. Cancelled requests cannot overwrite newer results.
- Kept save feedback visible during background refreshes.
- Removed the demo-only forbidden-write control and hard-coded operational status cards. Sale dates are entered separately; default dates and seeds are no longer fixed demo values.
- Displayed complete saved coverage, rules and evidence data instead of truncating nested information.
- Made reconciliation state and assistant configuration visible from backend responses.

## Verification

- Production build and TypeScript checks passed.
- All 12 frontend tests passed, including navigation, register persistence, export selection, audit defaults, session boundaries and API handling.
- All 62 backend tests passed. Two subprocess checks initially hit sandbox restrictions and passed when rerun with local subprocess permissions.
- Chrome tests passed for the complete upload/audit/evidence/review/export workflow, mobile navigation, expired sessions and an actual register amount difference.
- Running-instance API checks confirmed dashboard counts match saved context: 3 observations and 0 samples. Current invoice population is 0; this is source data, not a disconnected counter.
- The live database was not reset. Permanent auditor/client credentials remain intact.
- No external LLM request was made. Automatic approval review rejected transmitting private audit snapshot data to Groq without approval for that payload and destination. Local assistant API/MCP behavior is tested; a successful live provider response is not claimed.
