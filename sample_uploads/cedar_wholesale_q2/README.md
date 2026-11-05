# Cedar Wholesale — synthetic Q2 FY 2026–27

This population is independent of the original `sales_register.csv` demo. Every customer, identifier, transaction and document is synthetic; none is independently verified.

`business_lifecycles.json` contains four customers and 40 sale lifecycles with distinct order, dispatch and invoice dates, balanced journals, one receipt, two credit notes and duplicate supporting-document bytes for a review scenario. There are 36 invoices in July–September 2026 and four in the October cutoff window. A dated affiliate disclosure supplies a related-party classification input.

- `cedar_q2_ledger_clean.csv`: all 40 business invoices, with matching dates, customer names, gross amounts and GST identifiers.
- `cedar_q2_ledger_difference_checks.csv`: one gross amount increased by INR 500, one business invoice omitted and one unmatched ledger row. Exactly three reconciliation observations are expected.
- `cedar_q2_ledger_excel_formatted.csv`: the clean population using M/D/YYYY dates and comma-grouped amounts. Formatting alone should produce no reconciliation observations.
- `related_party_disclosures.json`: the synthetic affiliate disclosure.
- `test_results.json`: measured counts and reproducibility results from the local API run, created after successful verification.

Generate files with `python -m Pramaan.backend.alternate_demo --fixtures-only`. To load and verify them, set `PYTHONPATH` and `PRAMAAN_DATA` to the same local instance as the running backend, then run `python -m Pramaan.backend.alternate_demo`. This appends data and named snapshots, preserves prior uploads and credentials, and refuses to mix the scenario with unrelated business invoices. Temporary loader credentials are revoked after use. No LLM/provider request is made.
