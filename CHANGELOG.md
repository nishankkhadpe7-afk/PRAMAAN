# Changelog

Notable changes to PRAMAAN, newest first. Dates are when the change landed on `main`. The project has no numbered releases yet.

## Unreleased

### Added
- Tested on Kirana Invoice Training Data (50 synthetic Indian invoices) and Tally's official sample Excel: smoother OCR of small scans (dates read 29 to 47 of 50, totals 24 to 42, wrong totals 2 to 0), Subtotal and single-GST lines for the arithmetic check, apostrophe-for-slash fix in invoice numbers, and Tally's multi-row voucher template in the Excel reader. New optional dependency: Pillow.
- Tested against a public MIT-licensed Tally practice company: invoice-view vouchers no longer report a false imbalance, the no-voucher-number rejection explains itself, and bank CSVs with an opening-balance line import instead of failing.
- Register check: **Taxable value vs books**, **non-standard GST rate goes to review**, and **books credit notes missing from a register** that lists credit notes. UI: integrity cards, fact labels, assistant trail and file picker restyled; unused frontend code removed. Walkthrough PDF and deck screenshots re-captured with the current UI.
- **Tally Sales Register (Excel) import** with header detection, subtotal/grand-total checks and credit notes; **local anonymiser** for Tally register and voucher exports (consistent pseudonyms, state code kept, figures proven identical, refuses to write inside a git repo).
- **Register credit notes** are matched against the books' credit notes (date and amount). **GST split check** (CGST = SGST, total = books tax, one tax type, and same-state vs other-state when the company state code is given).
- **Register date order** detected per file or stated by the auditor (rule `p2-t00-v4`); undetermined dates go to review. **Repeated bill numbers** are now `DUPLICATE_ROW` findings. A **synthetic Indian GST register** test covers GSTINs, B2B/B2C, day-first dates, Indian digit grouping and credit notes. The run page builds once per run and caches the result (context wait 4.4 s → 0.64 s on a real year).
- **Round 2 of the import audit (P2/P3, [docs/IMPORT_AUDIT.md](docs/IMPORT_AUDIT.md)):**
  - Bank statements with one **Amount** column and a **Dr/Cr** column or suffix, a minus sign, or only a running balance; any column order; multi-page. Each row records how its direction was decided; rows nothing settles are listed, never guessed.
  - **Replace a wrong document:** the corrected file becomes version 2 with a reason. The original stays unchanged, frozen audits reproduce exactly, and the next run uses the new version.
  - **OCR for scanned PDFs** with local Tesseract (optional, bounded). OCR values are marked as such and need human confirmation; uncertain words are never imported.
  - **Field-quality states** (exact, validated, OCR, ambiguous, unreadable, human-verified) and a **Confirm field** form for human reviewers.
  - **Statement continuity:** a gap between one statement's closing and the next one's opening balance is reported.
  - **Cross-check** of each invoice PDF's total against the sales-register row; page and line traceability for bank rows; Tally rows mapped to vouchers.
  - Full import reports kept in `import_reports`.
  - Tally HTTP/XML fetch command (tested against a stand-in server only).
  - Database: 4 new append-only tables, added automatically at start-up; no existing table changed.
  - 25 more backend tests and 2 UI tests. CI installs Tesseract so the OCR tests run.
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
- **Real-data fixes (Kaggle bank export and UCI Online Retail II; details in docs/IMPORT_AUDIT.md):**
  - Bank CSVs with Withdrawal/Deposit columns, value dates and blank rows are accepted.
  - Excel-damaged references (`3.00E+11`) are discarded and counted.
  - The repeat check compares running balances: 102 false repeats → 5.
  - The register check is now rule `p2-t00-v3`: GST No blank on both sides is not applicable. On the retail data that removed 19,647 false findings, leaving exactly the 6,659 unmatched rows.
  - The run page sends only cited evidence (85.7 MB → 25.7 MB), and the API compresses responses (27 MB → 1.7 MB on the wire).
- **Opening an audit run is about 10× faster on large data:** 8.5 s down to 0.84 s at 3,000 sales, and time now grows in proportion to the data. `p5.enrich` matched every finding against every evidence row and invoice; it now uses lookup tables built once per request. The output is byte-identical, checked against the old code on a 1,000-sale dataset.
- An upload over the server's limit is refused before sending, with the file size and the limit. It used to show "The service could not complete this request." The identity response now includes `max_upload_bytes`.
- Opening an audit run that doesn't exist shows "Audit run not available" with a link back, instead of a stuck "Loading audit…" title and a Rerun button.
- A credential that isn't accepted at sign-in now says it may be mistyped, expired or revoked, instead of always "expired".
- OCR set-up on Windows:
  - a `PRAMAAN_TESSERACT` path in quotes now works;
  - a wrong path, or missing English language data, gets its own clear message;
  - Tesseract's own error text is kept;
  - no console window flashes per page.
- Added `python -m Pramaan.backend.ocr_check`, an end-to-end OCR self-check.
- The Docker image now installs Tesseract (optional build argument `WITH_OCR`).
- The round-1 tracker said import reports were kept in the event log; the log keeps only a hash of each report. Reports are now stored in full (`import_reports`) with that hash.
- Bank imports no longer allow two uploads of the same file at the same moment.
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
