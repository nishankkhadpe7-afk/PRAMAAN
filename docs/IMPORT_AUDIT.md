# Document import pipeline: gap analysis and remediation tracker

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
| 19 | P1 | History | Import reports needed a durable record. | **Already in place** | Every import writes its report (counts, warnings, balance check, overlap) to the hash-chained, append-only event log (`register_imported`, `bank_statement_imported`). A separate table would duplicate it. | existing event-log tests |
| 20 | P2 | Bank | Statements with a single *Amount* column plus a *Dr/Cr* marker aren't read. | **Open** | Refused with "no Debit/Credit header" rather than guessed. | — |
| 21 | P2 | Evidence | A wrongly uploaded document can't be replaced. Evidence is append-only. | **Open** | Needs a supersession record (new append-only table) so the old file stays visible. Not done, to avoid a schema change without a design review. | — |
| 22 | P2 | Tally | No live connection to a running Tally (XML over port 9000), SAP or other ERPs. | **Open** | File export only. | — |
| 23 | P2 | PDF | Scanned PDFs (no text layer). | **Open** | Refused with a clear message. OCR isn't used, because OCR misreads would break the "nothing guessed" rule for amounts. | existing test |
| 24 | P3 | Readers | No per-field confidence score. | **Not planned** | A field is either read exactly, ambiguous, or not read. A numeric confidence would imply a probability these readers don't compute. | — |

**Already in place before this review:** original bytes preserved and hashed; PDF magic-byte check, password-protected PDF refusal, and a 200-page limit; header-based bank columns (no position guessing); `unread` lines with reasons; append-only invoice readings; the client never sees the audit comparison; an unread field never counts as a match; Tally UTF-16 and control-character handling.

## Checks run for this change

- Backend: 166 tests passed (`python -m pytest backend/tests`), including 22 import tests on synthetic files.
- UI: type check, 33 unit tests and the production build passed. 8 browser journeys passed (run with video recording off, because the container had no ffmpeg). Accessibility scan (axe) found 0 violations on the checked pages.
- CI steps: the demo rehearsal, release verification and agent evaluation all exited successfully.

## Remaining limitations

- Readers handle **text PDFs**. Scanned images are refused.
- Bank PDFs need a header row with Debit/Withdrawal and Credit/Deposit words. Unusual layouts can still leave lines `unread`, and those are always listed.
- Wrapped narration is joined only within a page and only when the continuation line has no amounts.
- Invoice reading uses label patterns common on Indian GST invoices (*Invoice No*, *Invoice Date*, *Taxable value*, *CGST/SGST/IGST*, *Grand Total*). Other labels leave fields unread or ambiguous, never wrong.
- Duplicate-transaction detection across statements uses date, amount, direction and reference. If two genuinely different receipts share all of these, the later statement's copy is not used by the agent. The overlap is always reported at upload, so a person can see it.
- All test files are synthetic. The readers haven't been measured on a corpus of real bank or vendor documents.
