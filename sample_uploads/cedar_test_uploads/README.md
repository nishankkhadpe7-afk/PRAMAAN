# Cedar Wholesale — manual test uploads

Synthetic files for testing the upload → reconcile → audit-run flow by hand. They build on the
Cedar Wholesale Q2 FY 2026-27 population (40 sales, 4 customers) already loaded by
`python -m Pramaan.backend.alternate_demo`. Every name, amount and GSTIN is fictional.

Expected results below were measured against a copy of the loaded instance.

## Registers (client → Registers & disclosures → Sales register)

Upload as **Sales register**, then as the auditor click **Reconcile** on the Overview page and
create a new audit run with that register selected.

| File | What is different | Expected reconciliation observations |
|---|---|---|
| `1_cedar_q2_ledger_month_end_review.csv` | CEDAR/Q2/004 gross +₹1,180 · CEDAR/Q2/021 gross −₹250 · CEDAR/Q2/036 dated 1 Oct instead of 30 Sep · CEDAR/Q2/012 wrong GSTIN · CEDAR/Q2/017 missing · extra row CEDAR/Q2/MANUAL-01 | **6** — 4 field differences, 1 register-only, 1 system-only |
| `2_cedar_q2_ledger_rounded_amounts.csv` | Every amount rounded to whole rupees | **19** field differences (each 50 paise) — rounding is not tolerated |
| `3_cedar_october_cutoff_ledger.csv` | Only the 4 October invoices plus 2 new bills (CEDAR/Q3/041, 042) with no business record | **38** — 2 register-only and 36 system-only, because a partial ledger leaves the other Q2 invoices unmatched |

Suggested audit names when creating runs:

- `Cedar Wholesale - Q2 FY 2026-27 - Month-end Review`
- `Cedar Wholesale - Q2 FY 2026-27 - Rounded Ledger`
- `Cedar Wholesale - October 2026 Cut-off`

Use period **2026-07-01 → 2026-09-30** (or **2026-10-01 → 2026-10-31** for the cut-off ledger).
The sampling seed is filled in automatically from the audit name.

## Related-party disclosure (Source type → Related-party disclosure)

`4_cedar_related_parties_update.json` keeps the existing CEDAR-CUSTOMER-1 affiliate and adds
CEDAR-CUSTOMER-3 as a common-director relationship from 2026-08-01. Upload it, then create a new
audit run; T01 classifications should now include Cedar Retail 3 invoices dated from August.

## Evidence documents (client → Evidence inbox)

`evidence/` holds one synthetic file per document type the inbox asks for:
`invoice`, `e_way_bill`, `lorry_receipt`, `proof_of_delivery`, `credit_note`, `return_support`.
Open a request, choose the matching outstanding document type and upload the file with that name.
A request becomes *partially fulfilled* after one document and *fulfilled* once all are supplied.
Uploaded evidence is recorded as company-supplied and unverified; rerun the audit to include it.

## A sale to enter by hand (client → Business records → Create a sale)

| Field | Value |
|---|---|
| Customer | Cedar Retail 1 (synthetic) |
| Invoice id | `CEDAR-INVOICE-041` |
| Bill no | `CEDAR/Q3/041` |
| Order / dispatch / invoice date | 2026-10-04 / 2026-10-05 / 2026-10-06 |
| Net amount | `11175.00` |
| Tax amount | `2011.50` |

After saving, reconcile `3_cedar_october_cutoff_ledger.csv` again: CEDAR/Q3/041 should no longer
be register-only, because its date, customer and gross amount (₹13,186.50) match the ledger row.
