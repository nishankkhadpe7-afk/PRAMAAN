# Document import pipeline: gap analysis and remediation tracker

Two review rounds: **round 1** (P0/P1, items 1–24) and **round 2** (P2/P3, items R2-1 to R2-10, [below](#round-2-p2p3-remediation)). Round 2 re-checked round 1 before building on it and corrected one claim (item 19).

This review covers how PRAMAAN reads real-world source files: Tally XML exports, bank statements (PDF and CSV) and invoice PDFs. It records what was already in place, what was missing, what was fixed, and what is still not done. Code: [backend/document_import.py](../backend/document_import.py), [backend/p2.py](../backend/p2.py) (registers), [backend/p6_agent.py](../backend/p6_agent.py) (bank statements), [backend/p3.py](../backend/p3.py) (evidence and invoice readings). Tests: [backend/tests/test_document_import.py](../backend/tests/test_document_import.py), [web/src/imports.test.tsx](../web/src/imports.test.tsx).

**Principles kept throughout**
- **Deterministic.** No AI is used in any reader or check. The same file always gives the same result.
- **Nothing guessed, nothing corrected.** A value that can't be read safely is reported as unread or ambiguous, and a check that fails is reported, not fixed.
- **Originals preserved.** The uploaded bytes stay the source of record (SHA-256 in the vault). Readings are stored separately and append-only.
- **Company-supplied stays company-supplied.** A PDF that matches the books is still not independent verification.
- **Backward compatible.** CSV registers and CSV bank statements work as before. New response fields are additions only, and no tables were changed. The one behaviour change, refusing the same bank statement file twice, only blocks a case that used to double-count.

Priority key: **P0** can produce a wrong audit result or lose evidence. **P1** is a real-world format or check an auditor would expect. **P2** is useful but not blocking. **P3** is a nice-to-have.

## Remediation tracker

| # | Pri | Area | Finding (before) | Status | What changed | Test |
|---|---|---|---|---|---|---|
| 1 | P0 | Tally | The DOCTYPE/ENTITY check only looked at the first 4 KB, so a declaration later in the file reached the XML parser. | **Fixed** | The whole file is scanned, after UTF-16 conversion. | `test_a_declaration_hidden_deep_in_the_file_is_still_refused` |
| 2 | P0 | Invoice | Only expected reader errors were caught. An unexpected parser fault would have failed the evidence upload. | **Fixed** | Any reader failure is recorded as an `error` reading. The upload and the file are kept. | `test_a_reader_crash_never_loses_the_upload` |
| 3 | P0 | Bank | Uploading the same statement twice stored it twice, and the agent then counted every receipt twice. | **Fixed** | Same SHA-256 → HTTP 409 naming the earlier statement. | `test_the_same_statement_twice_is_refused_and_overlaps_are_counted_once` |
| 4 | P0 | Bank | Overlapping statements (for example a monthly PDF and a quarterly CSV) double-counted shared transactions. | **Fixed** | The overlap is reported at upload. The agent uses the first-imported copy of each transaction across statements (by date, amount, direction and reference, or narration when there's no reference). Rows inside one statement are never merged. | same test |
| 5 | P0 | Bank | No balance check, so a statement with a missing, altered or misread line went unnoticed. | **Fixed** | Running balance recomputed from the opening balance (or between rows), oldest- or newest-first. Every printed balance that doesn't add up is listed. A single wrong figure is reported once, not twice. | `test_a_wrong_printed_balance_is_reported_not_corrected`, `test_newest_first_statements_and_repeated_rows` |
| 6 | P1 | Bank | `Dr` and negative balances lost their sign. | **Fixed** | `parse_signed_cents`: `-`, `( )` and `Dr` are negative, including a separate `Dr`/`Cr` word after the balance. | `test_wrapped_narration_value_dates_and_overdrawn_balances` |
| 7 | P1 | Bank | Narration that wrapped onto a second line was dropped. | **Fixed** | A date-less, amount-less line to the left of the money columns, directly under a transaction on the same page, is joined to it. | same test |
| 8 | P1 | Bank | A Value Date column became part of the narration. | **Fixed** | A second date is stored as `value_date`. | same test |
| 9 | P1 | Bank | Identical rows inside a statement weren't mentioned. | **Fixed** | Listed as *repeated rows* for review and kept, because banks do post identical transactions. | `test_newest_first_statements_and_repeated_rows` |
| 10 | P1 | Tally | Malformed sales vouchers and non-sales vouchers were reported together as "skipped". | **Fixed** | Separate `skipped` (not a sale, cancelled, optional) and `rejected` (unreadable date, missing number/party/amount, unreadable ledger amount) lists. | `test_malformed_sales_are_rejected_not_skipped_and_doubtful_ones_warned` |
| 11 | P1 | Tally | No warnings for imported rows. | **Fixed** | Warnings for: GSTIN format or check digit; repeated voucher number; ledger entries that don't sum to zero; customer ledger credited instead of debited. | same test, `test_gstin_check_digit` |
| 12 | P1 | Invoice | Only number, date, GSTINs and total were read. | **Fixed** | Taxable value, CGST, SGST/UTGST, IGST and round-off are also read, each with its page number. | `test_gst_components_round_off_and_arithmetic` |
| 13 | P1 | Invoice | No GST arithmetic check. | **Fixed** | Checks taxable value + taxes + round-off = total. The difference must be exact when a round-off line is printed, and up to 50 paise when it isn't. IGST charged together with CGST/SGST, unequal CGST and SGST, and only one of CGST/SGST are all flagged. | same test |
| 14 | P1 | Invoice | When a label appeared twice with different values, the reader picked one. | **Fixed** | The field is marked `ambiguous`, left empty, and shows both candidates. The comparison result is *incomplete*, never a match. | `test_conflicting_values_are_ambiguous_and_left_unread` |
| 15 | P1 | Invoice | The same invoice uploaded for two different sales wasn't noticed. | **Fixed** | An identical file, or the same invoice number on another sale, is recorded with the reading as a possible duplicate. Nothing is blocked. | covered by API tests through the evidence listing |
| 16 | P1 | Invoice | The auditor comparison didn't cover tax. | **Fixed** | Taxable value is compared with the books' net amount, and total tax with the books' tax amount, when both exist. | `test_gst_components_round_off_and_arithmetic`, API test |
| 17 | P1 | UI | The client saw a flat list of facts after an import. | **Fixed** | Count chips (imported / skipped / rejected / warnings, or for a bank statement: imported / not read / repeated / already imported), a balance note, an overlap note, and expandable reasons. | `imports.test.tsx` |
| 18 | P1 | UI | The auditor saw only a *PDF matches/differs* badge. | **Fixed** | A *What the invoice PDFs say* section: a field-by-field table (PDF value with page, books value, result), the arithmetic result, warnings and duplicates. | browser check + axe |
| 19 | P1 | History | Import reports needed a durable record. | **Corrected in round 2** | Round 1 said the event log held each import report. On re-checking, the event log stores only a **hash** of each payload, not the payload. Reports are now kept in full in the append-only `import_reports` table; each row's `report_hash` equals the event's `payload_hash`, so the stored report is provably the one in the hash chain. | `test_replacement_keeps_history_and_frozen_runs_reproduce`, `test_tally_rows_trace_to_vouchers` |
| 20 | P2 | Bank | Statements with a single *Amount* column plus a *Dr/Cr* marker weren't read. | **Fixed in round 2** | See R2-1. | — |
| 21 | P2 | Evidence | A wrongly uploaded document couldn't be replaced. | **Fixed in round 2** | See R2-2. | — |
| 22 | P2 | Tally | No live connection to a running Tally, SAP or other ERPs. | **Partly done in round 2** | Tally HTTP/XML client built and tested against a stand-in server only; SAP not built. See R2-7. | — |
| 23 | P2 | PDF | Scanned PDFs (no text layer). | **Fixed in round 2 (optional)** | Local OCR when Tesseract is installed; see R2-3. | — |
| 24 | P3 | Readers | No per-field confidence score. | **Done differently in round 2** | A fixed six-state field-quality model, with no percentages; see R2-6. | — |

**Already in place before this review:** original bytes preserved and hashed; PDF magic-byte check, password-protected PDF refusal, and a 200-page limit; header-based bank columns (no position guessing); `unread` lines with reasons; append-only invoice readings; the client never sees the audit comparison; an unread field never counts as a match; Tally UTF-16 and control-character handling.

## Round 1 checks

Round 1 (P0/P1): 166 backend tests, 33 UI tests, the build, 8 browser journeys and an accessibility scan passed at the time; round 2's totals are below.

## Round 2: P2/P3 remediation

### Verification of round 1 before building on it

Each round-1 item was re-checked against the code and by running its test, not taken from the report. All held, except item 19 (corrected above): the event log stores only payload hashes, so "the report is in the event log" was true only of the hash. Two smaller gaps also surfaced and were fixed:
- Running-balance continuity was only checked inside one statement, never between consecutive statements (R2-4).
- Bank rows kept no link to the page and line they came from (R2-4).

### Priority order used

Items were ordered by audit risk, then dependency:
1. Replacing evidence without breaking frozen audits (R2-2), because a wrong document is an integrity risk.
2. Amount + Dr/Cr statements (R2-1), because they were refused outright.
3. Validation and traceability (R2-4), which needs R2-1's rows.
4. OCR (R2-3) and the field-quality model (R2-5, R2-6), which depend on the readers above.
5. Connectors (R2-7), which are independent of the rest.

### Round 2 tracker

| # | Pri | Item | Status | What was built | Evidence (tests) |
|---|---|---|---|---|---|
| R2-1 | P2 | Bank statements with one **Amount** column and a **Dr/Cr** indicator | **Done** | The header row decides the layout: *split* (Debit/Credit columns) or *amount* (Amount plus a Dr/Cr column, a Dr/Cr suffix, and/or Balance). Any column order works. Each row's direction comes, in order of preference, from: a Dr/Cr marker, a negative sign, or the printed running balance moving by exactly ± the amount. It is recorded per row as `direction_source`. A negative amount marked Cr is refused as a contradiction. A row nothing settles is `unread`. A layout with no marker, sign or balance at all is refused. Overdrawn (Dr) balances, Indian digit grouping, `/-` amounts and trailing minus signs are handled. The CSV reader also accepts bank header names (Dr/Cr, Particulars, Txn Date, Closing Balance) and Cr/Dr values. | `AmountDrCrLayoutTests` (6 tests, 4 styles × oldest/newest-first, 3 column orders, 95-row 3-page statement), `test_csv_with_bank_header_names_and_drcr_column`, `test_amount_drcr_pdf_and_csv_through_the_api` |
| R2-2 | P2 | **Replacing a wrong document**, with versions | **Done** | `POST /p3/evidence/{id}/replace` (client role) with the corrected file and a reason (5–500 characters). The corrected file becomes a **new** evidence row. The original row, file and SHA-256 are never changed. New append-only table `p3_evidence_versions` records the link, who, when and why. Each version can be replaced once, so the history is a single chain: replacing an older version gets a 409, and an identical file gets a 422. An `evidence_replaced` event goes to the hash chain, and the full report to `import_reports`. **Frozen audit runs are untouched:** their stored snapshot and result are byte-identical afterwards and reproduce exactly. New runs use the current version, and their snapshot lists the version links. Change detection flags a replaced document's sale. | `test_replacement_keeps_history_and_frozen_runs_reproduce`, `test_concurrent_replacements_and_statement_uploads_admit_one` |
| R2-3 | P2 | **Scanned PDFs (OCR)** | **Done, optional** | New `backend/ocr.py`: local Tesseract via subprocess (no shell, no network). A page with no text layer is OCR'd at 300 dpi, or lower if the page is very large. Limits: 20 pages, 30 s per page, 120 s per document, plus the existing upload size limit. Each word keeps Tesseract's confidence. A bank row with any date or amount word below 80 is **not imported** ("needs human review"). An invoice value containing such a word is set aside as `uncertain`. Every OCR value is marked `ocr`, and a match against the books is reported as *needs review* until a person verifies the field. Provenance (engine, version, dpi, pages) is stored with the reading. Without Tesseract, or with `PRAMAAN_OCR=off`, scans are refused with a message saying how to enable OCR. No new Python dependency. | `OcrTests` (4), `test_without_ocr_a_scan_is_refused_with_a_clear_message` |
| R2-4 | P2 | **Validation and traceability** | **Done** | **Normalisation:** more date formats (`12-Apr-25`, `12 Sept 2025`, `2025/04/12`, Unicode dashes), with day-first assumed for numeric dates and impossible dates refused; amounts with misplaced separators (`1,00,0.00`) refused as misreads. **Statement continuity:** each new statement's opening balance is compared with the closing balance of the previous imported statement; a gap reports the unexplained difference (missing transactions). **Cross-document check:** the invoice PDF total is compared with the sales-register row(s) for the same bill, and a bill missing from or repeated in the register is reported. **Traceability:** the new `p6_bank_row_sources` table links each bank row to its page, line, extraction (native/OCR/CSV) and direction source; Tally register rows are mapped to voucher number, position and REMOTEID in the import report. **Recovery:** a PDF page OCR can't read is listed and the other pages are still read. **Durable reports:** `import_reports` (item 19). GST arithmetic, duplicate invoices and duplicate transactions were already done in round 1 and were re-verified. | `NormalisationTests`, `test_statement_continuity_gaps_and_row_sources`, `test_tally_rows_trace_to_vouchers`, `test_malformed_pdfs` |
| R2-5 | P3 | **Human verification** of fields | **Done** | `POST /p3/evidence/{id}/field-verifications`: human-review credential only (an auditor without it, or the client, gets 403). The reviewer types the value printed on the document and how they checked. It is normalised and validated (GSTIN check digit, real dates, amounts). New append-only table `p3_field_verifications` stores it; the latest per field applies, and earlier ones stay. Logged as `document_field_verified`. The reading itself is never edited. | `test_field_verification_is_human_only_and_changes_quality` |
| R2-6 | P3 | **Field-quality model** (instead of confidence percentages) | **Done** | Six states, each decided by a fixed rule, with its evidence shown next to it (table below). The auditor's PDF table has a Quality column. | `FieldQualityTests` |
| R2-7 | P3 | **Live accounting connectors** | **Partly done** | **Tally:** `backend/tally_connector.py` sends Tally's documented XML export request (Day Book, date range, optional company) to a Tally HTTP server, checks the reply with the same Tally reader, and saves the XML for normal upload. It is a command-line tool, not a server endpoint, so the PRAMAAN server never connects to a user-supplied address. It is tested against a local stand-in server only, **not against a real TallyPrime**, so this is **not** a verified live integration. **SAP:** not built. It needs an SAP system, credentials and a chosen interface (OData services or RFC/BAPI), none of which are available here. File imports keep working on their own. | `TallyConnectorTests` (2) |
| R2-8 | — | **Concurrent imports** | **Done** | The bank-statement duplicate check and insert run in one `BEGIN IMMEDIATE` transaction. Evidence replacement relies on the UNIQUE link. With 4 simultaneous requests each time, exactly one succeeds and the rest get 409. | `test_concurrent_replacements_and_statement_uploads_admit_one` |
| R2-9 | — | **UI** | **Done** | **Client:** *Uploaded the wrong file? Replace it* on each current file; version and *replaced* tags with the reason; continuity-gap and OCR notes on imports. **Auditor:** version history on each PDF; Quality column; OCR provenance; a *Confirm field* form for human reviewers on OCR, ambiguous or unreadable core fields; register cross-check notes. | `imports.test.tsx` (5), browser walkthrough, axe |
| R2-10 | — | **CI** | **Done** | The CI workflow installs `tesseract-ocr`, so the OCR tests run there instead of skipping. | workflow file |

### Field-quality states

| State | Rule (decided in this order) | Evidence shown |
|---|---|---|
| `human_verified` | A reviewer with the human-review credential recorded a value for this field. | Who, when, note, verification id |
| `ambiguous` | The best-ranked label printed two or more different values. None is used. | The candidate values |
| `unreadable` | No value under a recognised label, or OCR read it with low confidence. | The reason (including OCR's uncertain text) |
| `ocr` | Read by OCR from a scanned page. | Page, engine; must be human-verified before it counts as a match |
| `validated` | Read from the text layer and confirmed by an independent check: GST arithmetic for amounts, or the check digit for GSTINs. | Page and the check used |
| `exact` | Read from the text layer under its label, with one value. | Page |

### Database migrations (round 2)

All additive, created with `CREATE TABLE IF NOT EXISTS` when the server starts. No existing table, column or row is altered, so existing databases upgrade in place and older code ignores the new tables. Every new table has triggers that block UPDATE and DELETE.
- `p3_evidence_versions(new_evidence_id, replaces_evidence_id UNIQUE, reason, replaced_by, replaced_at)`
- `p3_field_verifications(verification_id, evidence_id, field, value_json, note, verified_by, verified_at)`
- `p6_bank_row_sources(statement_id, row_no, page, line, extraction, direction_source, value_date)`
- `import_reports(report_id, entry_hash, action, object_ref, report_json, report_hash)`

**Snapshot behaviour:** new snapshots leave out superseded evidence and gain a `p3_evidence_versions` key only when at least one replacement exists. A database with no replacements produces exactly the same snapshot as before. Stored snapshots are never rebuilt; reproduction uses the stored copy.

### Checks run for round 2

- **Backend, Python 3.13 (this container), Tesseract 5.3.4 installed:** 191 tests passed (`python -m pytest backend/tests`), run twice on the final code. These include the 25 new pipeline tests and the 22 import tests.
- **Backend, Python 3.11 (the CI version):** 191 passed.
- **Without OCR** (`PRAMAAN_OCR=off`, or a Tesseract path that doesn't exist): 187 passed and 4 OCR tests skipped with a stated reason. Every non-OCR test passes without Tesseract.
- **UI:** type check, 35 unit tests and the production build passed. 8 browser journeys passed, with video off because this container has no ffmpeg.
- **Accessibility (axe):** 0 violations on the core pages, and 0 on the new replace form and the auditor's PDF details with the verify form open.
- **Browser walkthrough on the seeded demo:** scanned statement uploaded (OCR; one row held back for review because a date was read with low confidence); scanned invoice uploaded and replaced with the text PDF (version 2, reason shown, original kept); a human reviewer confirmed a field.
- **CI steps:** the demo rehearsal, release verification and agent evaluation all exited successfully.

### OCR integration check (round 3)

Prompted by Tesseract 5.5.3 being installed on the Windows development machine.

**Found and fixed:**
- A `PRAMAAN_TESSERACT` value wrapped in quotes (common when copying a Windows path) was treated as "not installed". Quotes are now stripped.
- A wrong path gave the same message as no Tesseract at all. It now says the path doesn't exist.
- There was no check for the English language data. A missing `eng.traineddata` would have surfaced as a vague per-page failure; it now gets its own message.
- Tesseract's error text was discarded. It is now included.
- On Windows, each OCR call could open a console window. It now runs with `CREATE_NO_WINDOW`.
- The Docker image had no Tesseract, so OCR was always off in containers. It is now installed by default (`WITH_OCR=1`).

**Added:**
- `python -m Pramaan.backend.ocr_check`, with 12 PASS/FAIL checks: executable found, version, English data, invoice values, page references, quality labels, the needs-review rule, statement rows and balance, a poor scan, an unreadable statement, the time limit and the page limit.
- 6 tests on the real engine: a poor (60 dpi) scan, a real timeout, version and languages, the self-check, a quoted or wrong path, and missing English data.

On a 60-dpi scan, Tesseract misread the total as 116,000.00 (it is 118,000.00), with low confidence. PRAMAAN set that value aside, and the field is *unreadable*, not matched.

**Verified, in this Linux container (Tesseract 5.3.4):**
- the self-check: 12/12;
- the backend suite: 197 passed, or 188 passed and 9 skipped with OCR off;
- the import tests on Python 3.11.

**Verified on Windows 11** (Python 3.13.14, Tesseract v5.5.3.20260724, language data `eng` and `osd`), run by the developer on 2026-11-08:
- the self-check: 12/12;
- `pytest backend/tests/test_document_pipeline.py -k Ocr`: 12 passed.

This confirms that `PRAMAAN_TESSERACT` is picked up, the program can be given page images through stdin on Windows, and the time and page limits work.

One difference from Linux: on the 60-dpi scan, Tesseract 5.5.3 was also unsure of the invoice date, so the date was set aside too. That is the intended behaviour, and the check still passed.

**Not yet verified: Docker.** The image build couldn't run because this session's network blocks the base-image registry (Docker Hub and its mirrors). The Dockerfile change follows Debian's package definition, but it is untested.

Commands used:

```powershell
# Windows, from the PRAMAAN folder
$env:PRAMAAN_TESSERACT = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:PYTHONPATH = "$PWD\launcher"
.\.venv-p4\Scripts\python.exe -m Pramaan.backend.ocr_check
.\.venv-p4\Scripts\python.exe -m pytest backend/tests/test_document_pipeline.py -k "Ocr" -v

# Docker (where Docker can reach Docker Hub)
docker compose build app
docker compose run --rm app python -m Pramaan.backend.ocr_check
```

## Real-data validation (Kaggle datasets supplied by the developer, 2026-11-09)

The first test on data PRAMAAN didn't generate itself. The files aren't committed to the repository (the licence isn't recorded); the tests below use made-up rows in the same layout.

| Dataset | Contents | Result |
|---|---|---|
| `MyTransaction.csv` | One bank account, 2023: 1,469 rows with Withdrawal, Deposit and Balance columns | All **1,469 rows imported**. Running balance **consistent on all 1,468 rows it could check**. 5 rows flagged for review. The same file uploaded twice is refused (409). |
| UCI Online Retail II (`online_retail_II.csv`) | 1,067,371 real invoice lines from a UK online retailer, 2009–2011 | One financial year (Apr 2010–Mar 2011): 26,306 invoices; 19,647 positive sales loaded into the books; the register uploaded exactly as the data has it. Upload took 0.4 s, reconciliation 0.5 s, the audit run 25 s; reproducing the run gave an **identical** result. T00 flagged **exactly the 6,659 rows with no matching sale** (4,231 cancellations, 2,425 zero-total invoices and 3 bad-debt adjustments). |

**Problems the real data exposed, and fixes:**
1. **Bank CSVs with separate Withdrawal/Deposit columns were refused.** Most net-banking exports use them; only the PDF reader handled them. The CSV reader now accepts them, plus a repeated Date column (the value date), Category as the description, and blank spacer rows.
2. **Excel had destroyed the reference numbers** (`3.00E+11`): 1,453 of the 1,469 collapsed into 83 values. These are now discarded and counted (`references_damaged_by_excel`) instead of being used to match or de-duplicate transactions.
3. **The repeat check flagged 102 genuine payments** (for example two "Food ₹56" on the same day). It now also compares the running balance, because each real payment moves it while a duplicated line repeats it. 102 → 5, and the 5 are real same-day payment–refund–payment patterns worth a look.
4. **T00 flagged every matched row (19,647) because GST No was blank on both sides.** That would also happen with Indian B2C sales, which have no buyer GSTIN, so real problems would be buried. Rule **`p2-t00-v3`**: GST No blank on *both* sides is not applicable (counted as `gstin_not_applicable_rows`). Blank on one side still needs review. Required fields are unchanged. Older reconciliations keep their stored v2 rule.
5. **The run page sent 85.7 MB.** The whole evidence index (46,028 entries) went to the browser although findings cite a median of one. It now sends only cited evidence (and a sale's own evidence on the sale page): 25.7 MB, loading in 2.5 s. The API also compresses responses (gzip): this payload is 1.7 MB on the wire, and on the demo 502 KB becomes 40 KB.

**Follow-up fixes (same day):**
- **Run page at this size:** the run's frozen parts (findings, invoices, comparisons, registers) are now built once and cached per run and engine version; review decisions are added fresh on each request, and the response is encoded once. On the real retail year the context wait went from 4.4 s to 0.64 s; the findings tab now opens in 2.4 s (was 6.8 s) and the summary in 4.6 s cold (was 9.6 s). This is **not true server-side paging**: the screens' totals use every finding, so paging would need those totals moved to the server. Tables already render only a page of rows.
- **Date order (rule `p2-t00-v4`):** the register check now reads the order from the file itself (a first part above 12 means day-first, a second part above 12 means month-first). The auditor can also state it (Detect / Day first / Month first, on the dashboard). If the file can't settle it and nobody states it, ambiguous dates go to review with that reason; nothing is guessed. A file whose dates contradict each other is treated as undetermined. Older reconciliations keep their stored rule.
- **Repeated bill numbers** in a register used to pass silently: only the first row was compared. Each repeat is now a `DUPLICATE_ROW` finding.
- **Indian GST register, synthetic:** `backend/fixtures_gst_register.py` builds an **invented** Maharashtra company's FY 2025-26 register: 26 B2B buyers with check-digit-valid GSTINs, 14 B2C buyers with none, CGST/SGST and IGST states, day-first dates, Indian digit grouping (1,18,000.00), credit notes, stray spaces. It plants one amount difference, one date difference, one wrong GSTIN, one invoice missing from the books, one sale missing from the register and one repeated bill. In `backend/tests/test_gst_register.py` all six are found, the order is detected as day-first, and there are **no other findings**. At 300 sales the run gave the same result. **It is synthetic, not a real register.** It shows the format handling, not behaviour on a real company's data.

- **Credit notes:** a register row whose bill number is a credit note in the books is now compared on date and amount (the books amount counts as negative). A credit note the books don't have is still reported as "register entry with no sale". Credit notes in the books but missing from the register are not flagged yet.
- **GST split:** when the register has CGST/SGST/IGST columns, they must add up to the books tax, CGST must equal SGST, and the two types are never both charged. If the auditor enters the company's state code (dashboard field, or `company_state=27`), a buyer in the same state must carry CGST/SGST and a buyer elsewhere only IGST. Registers without these columns are not affected. The synthetic GST test plants one wrong split (IGST inside Maharashtra), one credit note with a wrong amount and one unknown credit note; all are found and nothing else is.

- **Tally Sales Register (Excel):** new upload type *Tally Sales Register (Excel .xlsx)* (`backend/tally_register.py`, API `source_format: "tally_xlsx"`). It finds the header itself (merged and two-row headers, company and period lines above it) and reads Particulars, voucher type and number, GSTIN, taxable value, CGST/SGST/IGST/Cess and total, Indian digit grouping and Dr/Cr. Credit notes and sales returns get a negative gross. Repeated headers, subtotals, grand totals and cancelled vouchers are skipped and listed, and every subtotal and grand total is checked against its rows. A line it can't read safely is rejected with its sheet and row, never guessed. Hidden sheets are not read and are reported. `.xls` is refused (no extra library). Tested on a **synthetic** workbook built to copy Tally's layout (`fixtures_tally_register.py`); **not yet on a real Tally export**.
- **Local anonymiser** (`python -m backend.anonymise_tally --register R.xlsx --vouchers V.xml --out <shared folder> --key <private file>`): see the file's docstring. It writes new files from cell values and XML text, so hidden sheets, comments and file properties are never copied. Names are replaced consistently across both files and inside narration, and GSTINs keep their state code. A pseudonymised GSTIN keeps a valid check digit only if the original had one, and uses PAN holder type `X`, which no real PAN has. Addresses, contacts, bank fields and narration are removed. Then it re-reads both outputs with PRAMAAN's own readers and refuses to write if any figure changed or any original name, GSTIN, phone or e-mail remains. It also refuses to write inside a git repository, and the originals are hash-checked as unchanged. The audit server never imports it.

**Still open:**
- True server-side paging (see above).
- An audit run on a year of real data takes 25 s.
- No real Indian register has been tested. The reader and anonymiser are ready for one; the reader's header matching may need adjusting on the first real export.
- PRAMAAN reads Tally voucher XML as a *register*, not as the books. A real register-vs-books test needs the books loaded through `/p2/sales` (or a Tally-to-books importer, not built).

## Remaining limitations

- **No real documents.** All tests use synthetic files generated by `backend/fixtures_documents.py`. The readers haven't been measured on real bank or vendor documents; that would need representative files shared with permission and with personal data removed.
- **OCR** depends on scan quality. Clean 200–300 dpi scans read well in the tests; skewed, handwritten or low-resolution scans will often leave rows *not read* (by design) rather than produce wrong numbers. OCR text can still split a reference number (seen once in testing: `IMPS5091 123456`); such rows are marked OCR, and the balance check is the main safeguard.
- **Direction from the running balance** needs a balance on the row before (or after, for newest-first statements). The first row of a newest-first statement with no opening balance stays unread.
- **Wrapped narration** is joined only within a page, and only when the continuation line has no amounts.
- **Invoice labels** follow common Indian GST invoice wording. Other wording leaves fields unread or ambiguous, never wrong.
- **Cross-statement de-duplication** uses date, amount, direction and reference. Two different receipts sharing all four are counted once by the agent, and the overlap is always reported at upload.
- **Replacement** is per document; there is no bulk replacement. A replaced file stays visible and downloadable by design.
- **Tally connector** is not verified against a real TallyPrime. SAP is not built.

## Needs external infrastructure or credentials

| Feature | What it needs |
|---|---|
| OCR for scanned PDFs | The Tesseract program on the server machine (Windows: the UB-Mannheim installer, or `PRAMAAN_TESSERACT=C:\path\tesseract.exe`; Linux: `apt install tesseract-ocr`). Without it, scans are refused with a clear message. |
| Tally live fetch | A running TallyPrime / Tally.ERP 9 with its HTTP server enabled (port 9000 by default), reachable from the machine running the command. Tally's XML interface has no login of its own, so it should only be reachable on a trusted machine or LAN. |
| SAP | An SAP system, a technical user with authorisation for the sales and billing documents, and a chosen interface (OData services or RFC/BAPI). Not built. |
| Real-document validation | Representative bank statements and invoices, shared with permission and with personal data removed. |
