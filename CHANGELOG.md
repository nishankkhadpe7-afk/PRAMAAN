# Changelog

Notable changes to PRAMAAN, newest first. Dates are when the change landed on `main`. The project has no numbered releases yet.

## Unreleased

### Added
- **Import checks (from the import-pipeline audit, [docs/IMPORT_AUDIT.md](docs/IMPORT_AUDIT.md)):**
  - Tally: the report now separates *skipped* (not a sale) from *rejected* (a sale that couldn't be read safely) and lists *warnings*: GSTIN check digit, repeated voucher numbers, unbalanced ledger entries, customer ledger credited.
  - Bank statements: running-balance check against the opening balance (PDF and CSV, oldest- or newest-first); value-date column; wrapped narration joined; `Dr`/negative balances keep their sign; repeated rows flagged.
  - The same bank statement file can't be imported twice (409). Overlapping statements are reported and the investigation agent counts each transaction once.
  - Invoice PDFs: taxable value, CGST/SGST/IGST and round-off are read with page numbers; GST arithmetic is checked; IGST with CGST/SGST is flagged; conflicting values are marked ambiguous instead of picked; duplicate invoices across sales are flagged.
  - The client sees counts (imported / skipped / rejected / warnings) and the reasons; the auditor gets a field-by-field PDF-versus-books table.
  - 11 more backend tests and 3 UI tests, all on synthetic files.
- **Tally import:** a Tally XML export (Day Book or sales vouchers, UTF-8 or UTF-16) can be uploaded as the sales register. Sales vouchers become register rows; other, cancelled and optional vouchers are skipped and listed with the reason; the XML is the preserved source.
- **PDF bank statements:** text PDFs from net banking are read using their Debit/Credit/Balance column headers, and lines that can't be placed are reported instead of guessed.
- **Invoice PDF reading:** invoice copies uploaded as PDFs are read (number, date, GSTINs, total) and stored append-only. Auditors see *PDF matches / differs / partly read* against the frozen snapshot; clients see what was read.
- Synthetic Tally XML, bank-statement PDF and invoice PDF samples (`sample_uploads/documents`, `python -m Pramaan.backend.fixtures_documents`) and 11 new backend tests.
- **Plain-language help in the app:** a **?** next to audit terms (assertion, cut-off, snapshot, seed, potential misstatement and others) that explains the word on hover or tap. All definitions live in one glossary (`web/src/glossary.tsx`).
- **Help button** in the top bar, with next steps for your role and the full glossary.
- **Getting-started card** on the client and auditor overviews. It can be dismissed and brought back from Help.
- **Empty states that say what to do next** on the main tables, instead of “No records yet.”
- **Repeat-run consistency** in the agent evaluation (`--repeats N`): it rebuilds the data for each run and reports whether every case reaches the same outcome and the same detailed status.
- **Secret scanning:** gitleaks over the full git history (`.gitleaks.toml`, `.github/workflows/secret-scan.yml`), with extra rules for inline command-line passwords.
- **CI workflow** (`.github/workflows/ci.yml`) running the backend tests, rehearsal, release verification, UI unit tests, build and browser journeys.
- Docs: [Getting started](docs/GETTING_STARTED.md) with screenshots, an animated agent walkthrough, [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), this changelog, and a [docs index](docs/README.md).

### Changed
- Dashboard cards follow the landing page's card design: one set of card tokens (`--card-*` in `styles.css`) for panels, metric and KPI cards, charts, integrity checks, findings, samples, the agent panel, guides, notices and empty/loading states. They share dark gradient surfaces, thin borders, 16 px corners, small orange accent icons, bold headings with muted descriptions, large low-contrast step numerals and subtle hover lifts (disabled for reduced motion). `Panel` and `Metrics` take an optional `icon`; the evidence inbox counters now use `Metrics`.
- Sample tabs read **Sales sample / Year-end cut-off / Credit notes** instead of “Sales TOD / Cut-off TOD / Credit Note TOD”. The term “test of details” is explained in place.
- The client activity trail shows plain events (“Sales register uploaded”) instead of codes (`register_imported`). Test-coverage statuses and test names are shown as readable text.
- Design, phase and report documents moved from the repository root into `docs/`, with links updated.
- AI coding-tool folders (`.claude/`, `.cursor/`, `.gemini/`, `.specstory/`) are now git-ignored.

### Fixed
- A DOCTYPE or entity declaration is refused anywhere in a Tally XML file, not only in its first 4 KB.
- If the invoice reader fails unexpectedly, the evidence upload still succeeds and the failure is recorded with the file.
- The privacy filter no longer mistakes PRAMAAN's own IDs for bank account numbers. About 1 in 280 register IDs (like `REG-123456789012`) has an all-digit tail, and that withheld the assistant's run summary and agent tool results. It was also the cause of an occasional CI failure.
- CI uses the Node 24 versions of the GitHub actions (checkout, setup-python, setup-node, upload-artifact v6), which removes the deprecation warnings.
- The investigation agent survives a dropped connection or timeout from the model provider: it retries, then moves to the next fallback model, instead of crashing the run.

## 2026-11-08
- **Security:** upgraded FastAPI to 0.162.2 and Starlette to 1.10.0, with route-to-permission lookup that works on both old and new routing internals. Upgraded vitest to 5.
- **License:** AGPL-3.0-only.
- **Agent:** all model text (plans, questions, next steps, summary) is screened for invented amounts, and payer-matching limits are documented.

## 2026-11-07
- **UI:** 4px spacing scale. A single “Needs your decision” block leads the dashboard.
- **MCP inspector:** no longer shows made-up event timestamps.
- **Tests:** more time allowed for the findings page on slower machines.

## 2026-11-06
- **UI:** one logo everywhere (landing, sign-in, sidebar), standard typography in Outfit, spacing fixes.
- **Launcher:** checks and installs web dependencies on every start, fixing `Failed to resolve import "@fontsource/..."` after pulls.

## 2026-11-05
- **Full-stack remediation:** critical, high and medium findings from the audit (security, backend, frontend, tests).
- **UI/UX audit:** design tokens and shared components, labels showing whether text comes from the AI, a proposal or a human, keyboard-only bulk review, workpaper packages, a drawer that no longer steals focus, accessible names, a neater PDF memo and XLSX workpapers.
- **Tests:** keyboard-only browser journeys and a 360 px horizontal-overflow check.

## 2026-10-31 – 2026-11-02
- Initial project: sale lifecycle records, register reconciliation, audit engine (T00–T15), sampling, content-addressed evidence vault, hash-chained audit log, role-based access, MCP tool server, client and auditor workspaces, and the investigation agent.
