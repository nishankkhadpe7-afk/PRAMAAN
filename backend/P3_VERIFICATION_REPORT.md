# P3 Verification Report

**PHASES.md P3 acceptance gate: PASS for the demonstrated synthetic/local scope.** This is not a claim that every T00–T15 check is operational or that synthetic rows are verified taxpayer evidence. Blocked checks and source limitations are listed below.

## Source pack validation

- Read `Pramaan/data/README.md` and `source_manifest.json`. The pack labels itself fictional synthetic data and explicitly warns that GSTIN-like identifiers, IRNs, e-way bills, and verification statuses are not genuine or independently verified.
- All 11 manifest-listed CSV files were present. Their SHA-256, byte counts, and row counts matched the manifest. `README.md` and the manifest were also preserved in the vault; the import persisted 13 source files and 50 normalized rows.
- No supplied file was edited. Test corruption cases use disposable copies under temporary test directories.
- Manifest SHA-256: `32d81c6e60e31f504295ad732da1e14c1e5702e88a5a562c5f7f0ee392f039a3`.

## Acceptance gate evidence

| PHASES.md criterion | Status | Actual evidence |
|---|---|---|
| Representative planted classes are detected | PASS | Dataset-backed test runs through import → persisted rows → snapshot → rules → findings. It detects T02 candidate edges, T05 `JRN-MAN-001`, T06 `INV-003` value and `INV-005` quantity differences, T04 missing movement documents on `INV-004`, T08 configured concentration signal, T10 threshold-pattern pairs, T11 capacity review, and T15 synthetic GSTR row difference. Existing P3 test also detects duplicate evidence (T07) and post-period credit-note review (T09). Matching controls are asserted for T01, T04, T05, T06, T08, T10, T11, T14 and T15. |
| Innocent traps are not left as confirmed exceptions | PASS | Dataset-backed test asserts every result has `confirmed_exception == false`; the post-period credit note remains a T09 review candidate, not a confirmed error. Findings that arise from synthetic or incomplete inputs remain review/inconsistent/unverified states. |
| Same snapshot, stored seed and versions reproduce identical selections/reasons | PASS | Both the existing P3 workflow and imported-fixture run call the reproduce route. The saved snapshot/ruleset/seed regenerate an identical logical result; the imported run also compares the reproduced findings. Seed, ruleset/sampler versions, draws and reasons are persisted. |
| Sampling limitations are shown for incomplete populations | PASS | Existing P3 fixture selects 30 of 32 sales and verifies 10 before/12 after cutoff coverage and exclusions. The supplied pack has only 8 invoices; its result reports reduced Sales TOD population (8 selected), 0 post-period cutoff population, and no population projection. Credit Note TOD tests cover the post-period census and in-period selection. |
| Client evidence-request loop | PASS | Existing P3 workflow lists a Sales TOD request, uploads each required document, observes partial/fulfilled states, confirms uploads cannot self-certify, then reruns against a changed snapshot. Imported dispatch documents also satisfy only the corresponding movement-document presence checks. |

## Check-by-check status

| Check | Status | Demonstrated behavior and limitation |
|---|---|---|
| T01 disclosed related-party tracing | PASS | Dated disclosed fixture edge `REL-001` classifies `INV-001` and retains its source reference. Synthetic source only. |
| T02 discovery candidates | PASS | Candidate edges `REL-002`/`REL-003` create review-only findings; disclosed `REL-001` is not misreported as a candidate. Candidate identity is not independently corroborated. |
| T02 graph cycles | NOT TESTED | The supplied fixture graph contains no cycle. |
| T03 transfer-of-control cutoff | BLOCKED | Cutoff sample is selected and unresolved control facts are reported as GAP. No contract/incoterm/control policy data exists, so a control date cannot be derived. |
| T04 missing movement | PASS | `INV-004` has no e-way bill/POD and is flagged; complete fixture movement refs such as `INV-001` do not receive that gap. Fixture document refs are placeholders, not source documents or independently verified movement evidence; missing records do not assert non-movement. |
| T05 revenue without sale | PASS | Balanced standalone `JRN-MAN-001` revenue credit is detected; linked `JRN-001` is not. Candidate is not a human-confirmed conclusion. P2 journal tables remain unchanged and still require invoice links. |
| T06 document mismatch | PASS | Invoice/dispatch taxable value, quantity and buyer GSTIN use versioned exact/decimal tolerances. `INV-003` value and `INV-005` quantity differences are detected; `INV-001` matches. No invoice-side vehicle field exists, so vehicle comparison is unavailable. |
| T07 duplicate/misassociated evidence | PASS | Existing regression detects identical file content across invoices as review, not confirmed error. |
| T08 period-end concentration | PASS | Historical customer-month rows and a seven-day, 2.00× gross-sales rule detect the configured `CUST-003` fixture signal; `CUST-001` control period is not flagged. These parameters are synthetic test settings, not audit/statutory policy. |
| T09 credit notes | PASS | Existing regression verifies the post-period credit note is review-only and part of the census; it is not treated as an error solely due to timing. |
| T10 threshold splitting | PASS, test-only | `POL-THR-002` and a configured 90-day window detect pairs for CUST-001/CUST-003; single-invoice CUST-002 is not flagged. Threshold/window are synthetic review parameters; no intent is inferred. |
| T11 physical plausibility | PASS | Capacity-only screen flags `INV-005` as REVIEW and does not flag `INV-001`. No `IMPOSSIBLE` state is asserted from unverified fixture inputs. Route/time, overlap, load and consignee checks remain unavailable. |
| T12 assertion support/provenance | BLOCKED | The pack provides verification-status placeholders, not assertion-linked evidence. P3 uploaded documents remain unverified; no independent verifier or full P3 assertion-evidence model is present. |
| T13 signature/IRN/registration | BLOCKED | `NOT_PERFORMED` becomes `UNVERIFIED`; `UNAVAILABLE` remains `UNAVAILABLE`. No signature, QR, IRN, GST registration, or timing verification is performed. |
| T14 pricing/promotions | BLOCKED, partial screen | Effective unit prices are compared only through the explicit test-only HSN→item mapping in the ruleset; the supplied invoice prices match. `PROMO-002` is a review candidate for missing approval, but the data does not say whether that promotion was applied to a sale. No violation is concluded. |
| T15 GST consistency | PASS | Provided synthetic GSTR rows are compared for date, seller/buyer GSTIN, taxable value, tax split and gross. `INV-001`/`INV-005` match; `INV-003` differs. No return filing/acceptance, dataset completeness, or place-of-supply conclusion is claimed. |

## Import and validation safeguards

- Additive SQLite tables: `p3_dataset_imports`, `p3_dataset_files`, and `p3_dataset_rows`, created with `IF NOT EXISTS`; P1/P2 schema and route implementations were not changed.
- Import validates manifest hash/size/row counts, exact required CSV columns, numeric/date/boolean types, invoice tax arithmetic, journal line shape and balance, and cross-file invoice/customer/bill references where the pack supplies reference keys.
- Raw bytes for every CSV, `source_manifest.json`, and `README.md` are retained in the SHA-256 vault. Normalized rows are stored separately. Import metadata and hashes are appended to the existing integrity log in the same DB transaction as the import.
- Validation regressions reject stale hashes, missing files, malformed dates, invalid references, bad tax arithmetic, and an unbalanced journal. A forced DB failure during row insertion leaves no partial dataset rows/files/import record.
- Versioned `p3-2026-02` rules label concentration/split thresholds and the HSN/item mapping as `synthetic_test_only`.

## Actual verification results

- `py -m unittest discover -s Pramaan/backend/tests -v` — **12 passed**, 0 failed (7 P1, 2 P2, 3 P3).
- `py -m py_compile Pramaan/backend/app.py Pramaan/backend/p2.py Pramaan/backend/p3.py Pramaan/backend/p3_dataset.py Pramaan/backend/tests/test_p1.py Pramaan/backend/tests/test_p2.py Pramaan/backend/tests/test_p3.py` — **passed**.
- Direct dataset/ruleset validation — **passed**: 13 source files, 50 normalized rows, ruleset `p3-2026-02`.

T03, T12, T13, and full T14 conclusions remain blocked by missing contract/evidence/verification/application data. T02 cycle, vehicle comparison, and extended T11 checks were not demonstrated by this fixture. No external verification integration was added. The PASS verdict applies only to the PHASES.md gate criteria demonstrated above and the supported synthetic/local slice.
