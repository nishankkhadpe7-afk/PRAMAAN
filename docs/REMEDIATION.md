# PRAMAAN remediation tracker (November 2026)

Scope: fixes for the full-stack audit of 5 Nov 2026 (IDs C1, H1–H8, B1–B10, F1–F9, U1–U10, S1–S7, T1–T10).
Constraint honoured: PRAMAAN stays a single-company, single-auditor local application (SQLite); no multi-tenant or Postgres migration.

## Verification summary

| Check | Before | After |
| --- | --- | --- |
| Backend pytest | 92 passed | 114 passed, 24 subtests (22 new regression tests) |
| Frontend `tsc -b` | clean | clean |
| Vitest | 20 passed | 27 passed |
| `vite build` | 1 chunk, 407 KB | initial 296 KB + lazy `auditor` 100 KB + `client` 18 KB |
| Playwright e2e | 0/3 (expired tokens, stale selectors) | 3/3 |
| `demo rehearse` (real HTTP) | n/a | reproduced = true, writes denied and logged |
| `release_verify --require-quality` | n/a | exit 0; synthetic benchmark unchanged: 8/8 planted, 0 false alarms |
| Clean checkout named `PRAMAAN-main`, `PYTHONPATH=launcher` | failed without generated shim | 114 passed |

## Issue tracker

| ID | Original problem | Fix implemented | Verification | Status |
| --- | --- | --- | --- | --- |
| C1 | One malformed sale date blocked every audit run permanently | ISO date validators on all P2 sale/receipt/credit-note dates; `calculate()` turns unreadable legacy dates into INCONSISTENT `UNREADABLE_DATE` findings and excludes them from date tests/sampling; clean snapshots untouched (reproducibility preserved) | `test_p0_regressions` (rejection with field errors, legacy bad date no longer blocks run/rerun/context, sanitizer is identity on clean data) | Resolved |
| H1 | Sampling seed predictable from the audit name | Seed optional in API; server draws `srv-` + 128-bit random seed; fixed seed only via "Advanced" for documented re-performance | Backend test (unique, unpredictable, explicit seed honoured, short seed 422); Vitest (no seed posted by default); e2e uses server seed | Resolved |
| H2 | Every request appended to the hash chain | Access decisions go to append-only `access_log` (own triggers, no chain lock); chain keeps business/audit actions; `/ui/access-log`, `/ui/events.access_denials` | Reads leave `events` count unchanged; access_log immutable; tests updated | Resolved |
| H3 | Write-lock contention, sync SQLite in async middleware | WAL + 15 s busy timeout; middleware DB work in threadpool; reviews and packages verify before `BEGIN IMMEDIATE` and re-check under the lock | Concurrency test (12 reads + 4 writes in parallel, all 200; journal_mode=wal) | Resolved |
| H4 | Errors masked to generic text | Error contract `{code, detail, fields?}`; authored 4xx details returned; validation errors list fields without echoing values; 5xx and provider errors stay generic; catch-all 500 handler | Backend contract tests; Vitest for API error parsing | Resolved |
| H5 | Related-party records not tied to the uploaded file | Server parses records from source bytes (CSV or JSON, normalised headers, yes/no booleans, ISO dates); client `records` optional and must match | Backend tests (parsed shape, mismatch 422, bad inputs 422) | Resolved |
| H6 | MCP channel was a client-declared header | `credentials.channel` ('any' or 'mcp'); `--agent` tokens are always the MCP channel, cannot be human, and stay restricted whatever headers are sent | Backend test (reversal/books write/human review denied without header; proposal allowed) | Resolved |
| H7 | Multi-MB snapshots; full recomputation on every read | New snapshots reference register bytes by SHA-256 (vault, verified on use); packages embed verified bytes (self-contained); reproduction verdict cached per run, result bytes and engine-code fingerprint; Integrity tab still recomputes live; legacy inline snapshots compared in their own shape | Tests: no inline bytes, package export survives vault tampering, cache hit/invalidation, legacy run not falsely "changed" | Resolved |
| H8 | E2E broken by expired tokens | Playwright resets the dedicated `.demo/browser` instance (fresh tokens) before starting the API; stale selectors updated; retries off | 3/3 e2e | Resolved |
| B1 | Bad amounts caused 500 | Amount validators; receipt/credit amounts parsed before DB work | Test: four bad-amount cases → 422 | Resolved |
| B2 | Vault written before validation; duplicate IDs → 500 | Validate and decode first; atomic content-addressed writes after rows accepted; IntegrityError → 409 | Test: 409, no orphan file, duplicate IDs in request 422 | Resolved |
| B3 | GET change detection wrote to the DB | GET is read-only; new `POST /p4/audit-runs/{id}/changes` records | Test: repeated GETs write nothing; POST records once | Resolved |
| B4 | Lexicographic date sort | Only calendar-valid dates define default period; `unreadable_date_count` surfaced in UI | Test + screenshot | Resolved |
| B5 | Duplicate run rewrote samples; no triggers | Identical run returns early; no-update/no-delete triggers on samples and draws, no-delete on requests, immutable received evidence | Test | Resolved |
| B6 | Evidence requests duplicated per run | `/ui/inbox` adds `work_items` grouped by sale and document, plus deduplicated counts used on the client dashboard | Backend suite; dashboard metric | Partially resolved: the inbox list still shows one row per run's request |
| B7 | MCP child got full environment incl. LLM keys; spawned per question | Child receives an allow-list of variables only | Test: no key reaches child env | Partially resolved: one subprocess per question remains |
| B8 | Absolute Windows path shim; no portable import | Tracked `launcher/Pramaan/__init__.py` resolves the repo root at run time; all launchers/CI use it | Clean renamed checkout passes | Resolved (no pip-installable package; see deferred) |
| B9 | `jsonschema` unpinned; fake `/p4/denied-tool` route | Pinned; real `POST /p4/tool-denials` | Backend suite (MCP stdio + HTTP test) | Resolved |
| B10 | Mid-module router imports; three DB layers | Not changed | — | Deferred: refactor risk outweighs benefit now |
| F1 | Polling frozen data every 10–15 s | No polling on run, finding and integrity views (on demand); dashboard 60 s, evidence requests 30 s | e2e; manual | Resolved |
| F2 | 60 KB single-line TSX files | `NewRunForm` rewritten readably; no file split | — | Deferred: large mechanical refactor; should come with ESLint/Prettier |
| F3 | Row click fired twice | `stopPropagation` on the row button | Vitest | Resolved |
| F4 | Error body ignored | `ApiError` carries `code`, `detail`, `fields` | Vitest | Resolved |
| F5 | Reload logged the user out | Credential kept in `sessionStorage` (tab-scoped), re-validated on load, cleared on sign-out/401 | Vitest + e2e | Resolved |
| F6 | Retry timer outlived component | Timers tracked and cleared on unmount | tsc | Resolved |
| F7 | Drawer lacked focus management | Focus trap, Escape, focus returns to opener | Vitest | Resolved |
| F8 | One 407 KB bundle | Lazy workspace routes | Build output | Resolved |
| F9 | Canvas errors flooded test output | `getContext` stub in test setup | Clean Vitest output | Resolved |
| U1 | Findings noisy, no triage | Findings sorted most serious first, open before reviewed | Manual | Partially resolved: no bulk review actions |
| U2 | Errors below the fold; editable predictable seed | Inline field errors; seed behind "Advanced"; unreadable-date notice | Vitest + screenshot | Resolved |
| U3 | Mobile sign-in below marketing cards | Form first on ≤1024 px; principles hidden on mobile | Screenshot 390 px | Resolved |
| U4 | Jargon and unlabelled benchmark claims | Plain-language sign-in copy; benchmark labelled synthetic | Screenshot | Resolved |
| U5 | Mobile tab overflow, cramped heading | Fade edge + scroll snap; heading padding/size; 2-column metrics | Screenshot 390 px | Resolved |
| U6 | Truncated headers, wrapped IDs | `nowrap` on headers and ID cells | Manual | Resolved |
| U7 | Four Google-hosted fonts, two visual languages | Fonts self-hosted (Outfit, JetBrains Mono, Cinzel; Anek Latin dropped) | Build includes woff2; no CDN references | Partially resolved: landing keeps its own theme |
| U8 | "Live" pill on immutable snapshots | "Frozen snapshot" pill | Screenshot | Resolved |
| U9 | Truncated chart labels | Two-line wrap, title and aria-label | tsc | Resolved |
| U10 | Eyebrow labels on panels | Reviewed: eyebrows appear on page headers only | — | Won't fix (by design) |
| S1 | Live and dead API keys in local `.env` | `.env` left untouched; `.env.example` rewritten to warn | — | Manual action required |
| S2 | Client SQL role could update/delete business tables | Client is INSERT-only except versioned P1 edits and request status; triggers on registers, disclosures, evidence and reconciliations | Test | Resolved |
| S3 | Unauthenticated requests flooded the chain | Unauthenticated denials rate-limited (120/min) into `access_log` with suppressed count | Test | Resolved |
| S4 | No request-size cap before parsing | Outermost ASGI middleware enforces declared and streamed size (413); nginx `client_max_body_size` | Test (declared, chunked, unauthenticated) | Resolved |
| S5 | Font CDN, no security headers | Self-hosted fonts; CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy in nginx | Build verified; nginx unverified (no Docker daemon) | Resolved (nginx unverified) |
| S6 | Long-lived tokens, no housekeeping | Human tokens ≤ 7 days, never permanent or agent; `list` and `revoke-subject` CLI | Test | Resolved |
| S7 | DLP skips numbers and over-blocks long digit runs | Not changed (scanning numbers would block legitimate cent amounts) | — | Open risk (documented) |
| T1 | e2e not runnable | See H8 | 3/3 | Resolved |
| T2 | No CI | `.github/workflows/ci.yml`: pytest, tsc, Vitest, build, Playwright | Same commands pass locally | Implemented (not yet run on GitHub) |
| T3 | No negative-input tests | `test_p0_regressions.py`, `test_p1_regressions.py` | 22 new tests | Resolved |
| T4 | Untyped API contract | Error type only | — | Deferred |
| T5 | Orphan Dockerfile, no backend image | `backend/Dockerfile`, `compose.yaml`, root `.dockerignore`; web image type-checks | Not built (no Docker daemon here) | Implemented, unverified |
| T6 | Windows-only launcher and e2e paths | `run-local.sh`; portable Python detection; `launcher` shim | Linux run of e2e and tests | Resolved |
| T7 | No assistant contract test | Not changed | — | Deferred |
| T8 | 100+ leftover test directories | Session fixture removes `tests/.runtime` | Directory absent after run | Resolved |
| T9 | Tracked server logs; doc sprawl | `.gitignore` extended | — | Manual action: `git rm --cached .server-logs/*.log`; doc consolidation deferred |
| T10 | Outdated `.env.example` | Rewritten for Gemini/Groq/OpenAI, `--agent` tokens, body limit | — | Resolved |

## Schema migrations (additive, applied automatically on first start)

| Change | Reverse |
| --- | --- |
| `credentials.channel TEXT DEFAULT 'any'`, `credentials.issued_at REAL` | `ALTER TABLE credentials DROP COLUMN …` (SQLite ≥ 3.35); old code ignores them |
| `access_log` table, index and triggers | `DROP TABLE access_log` |
| `p3_run_verifications` cache table | `DROP TABLE p3_run_verifications` (cache only) |
| Immutability triggers on samples, draws, requests (delete), evidence, registers, disclosures, reconciliations | `DROP TRIGGER …` |
| SQLite WAL journal mode | `PRAGMA journal_mode=DELETE` |

Existing rows are never rewritten. Security events already in the hash chain stay there; new ones go to `access_log`. Runs frozen before this change keep reproducing, and post-test change detection compares them in their original snapshot format.

## API contract changes

- Errors: `{code, detail, fields?}` (previously `{detail}` with generic text).
- `POST /p3/audit-runs`: `sampling_seed` optional (server-generated when omitted).
- `POST /p2/related-parties`: `records` optional; stored records are parsed from `source_base64`; supplied records must match.
- `GET /p4/audit-runs/{id}/changes` is read-only; `POST` to the same path records the report.
- New: `GET /ui/access-log`, `POST /p4/tool-denials`; `/ui/events` adds `access_denials`; `/ui/inbox` adds `work_items`, `outstanding_documents`, `outstanding_items`; `/ui/audit-setup` adds `unreadable_date_count`.
- Request bodies larger than the upload limit (as base64) plus 1 MiB return 413.

## Hosted-deployment considerations (not implemented)

Multi-tenant hosting would need: Postgres with row-level security (the SQLite authorizer is not a security boundary), session login instead of pasted bearer tokens, an external anchor for the hash chain, centralised log shipping for `access_log`, and secrets in a vault rather than `.env`.
