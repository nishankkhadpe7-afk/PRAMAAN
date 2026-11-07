# Pramaan P3 Data Pack — Synthetic Test Fixtures

## Purpose
This pack is a local, fictional dataset to develop and test Pramaan's P3 audit checks and source-data contracts. It is not real taxpayer data, not a filing, not evidence of legal compliance, and not a substitute for independent source verification.

All company/customer names and document references are fictional. GSTIN-like strings are placeholders and must not be treated as real validated registrations. Any IRN/e-way-bill identifiers beginning with `SYN` or `SYNTH` are synthetic placeholders.

## Files
- `invoices.csv`: invoice header, customer, amount, tax, quantity, HSN and signature/IRN availability fields.
- `dispatches.csv`: invoice-linked movement records with taxable value, quantity, GSTIN, vehicle, e-way-bill and POD fields. Includes deliberate mismatches and missing documents.
- `journal_entries.csv`: balanced sample postings plus a standalone manual revenue credit without an invoice link for T05 testing.
- `related_party_edges.csv`: dated disclosed relationship and candidate shared-identifier edges. Candidate relationships require review; they are not fraud findings.
- `historical_sales.csv`: synthetic prior-period sales baseline for concentration checks.
- `threshold_policies.csv`: test-only configurable thresholds. These are NOT legal/statutory thresholds.
- `gstr1_rows.csv`: synthetic return rows, including one deliberate invoice mismatch.
- `price_lists.csv`: effective-dated synthetic customer/item prices.
- `promotions.csv`: effective-dated approved and unapproved-candidate promotions.
- `movement_routes.csv`: synthetic route and capacity facts, including one deliberate capacity conflict.
- `invoice_verification_status.csv`: explicit NOT_PERFORMED/UNAVAILABLE placeholders. These do not represent successful signature, QR, IRN or GST registration validation.
- `source_manifest.json`: provenance labels, public schema references and SHA-256 checksums of this pack's CSV files.

## Designed test cases
1. `INV-003`: invoice taxable value is 200,000 but dispatch value is 199,000; related GSTR-1 row uses 199,000.
2. `INV-004`: dispatch lacks e-way bill and proof of delivery.
3. `JRN-MAN-001`: balanced standalone revenue journal with no invoice reference.
4. `CUST-001` and `CUST-003`: shared synthetic person identifier over overlapping dates; candidate edge requires human review.
5. Historical monthly values allow a baseline computation for selected customers.
6. `POL-THR-001` and `POL-THR-002` are deliberately labelled testing-only; do not treat them as statutory rules.
7. `PROMO-002` has no approval reference and is a review candidate, not a confirmed violation.
8. `INV-005` has a route quantity exceeding the synthetic vehicle capacity.
9. Signature and registration checks remain NOT_PERFORMED or UNAVAILABLE until a genuine verification adapter is implemented.

## Public references used for field-shape inspiration
- GSTN FAQ — e-invoice schema/JSON background: https://www.gstn.org.in/faqs-category-details
- IRIS IRP — notified e-invoice schema: https://einvoice6.gst.gov.in/content/notified-e-invoice-schema/
- GSTN E-Way Bill API developer portal (schemas, sample JSON, data structures, validations): https://docs.ewaybillgst.gov.in/apidocs/
- MCA rules/disclosure material (related-party disclosure fields): https://www.mca.gov.in/Ministry/pdf/Rules_31012020.pdf

These references describe formats and workflows; this pack does not contain downloaded real taxpayer transactions from those portals.
