# Sample companies: one honest, one hiding something

Two fictional Indian companies with a full year of records (FY 2025-26), built so you can see what PRAMAAN finds when records agree and when they don't.

| | **Kesar Home Decor Pvt Ltd** (`honest/`) | **Neelgiri Lifestyle Pvt Ltd** (`hiding/`) |
|---|---|---|
| Where | Bhiwandi, Maharashtra (GST state 27) | Surat, Gujarat (GST state 24) |
| Sells | Home decor and gifts to shops across India | Same trade |
| Invoices in the year | 1,331 (₹16.1 crore) + 38 in early April 2026 | 1,275 (₹12.6 crore) + 45 in early April 2026 |
| Customers | 25 (a few B2C buyers without a GSTIN) | 27 |
| Story | Its books, register, GST returns, transport and e-invoices agree | Inflates year-end sales through a related shell customer and hides other things |

Both companies are **fictional**. GSTINs have valid check digits but are not real registrations. E-invoice QR codes are signed with PRAMAAN's labelled **demo** key, never a government key. GST is charged at one illustrative 18% rate; real rates depend on the HSN code and the current notification.

## Load one

On Windows, from the project folder (PowerShell; drop the `.\` in Command Prompt):

```powershell
.\START_PRAMAAN.bat company honest    # Kesar Home Decor
.\START_PRAMAAN.bat company hiding    # Neelgiri Lifestyle
.\START_PRAMAAN.bat clean             # an empty workspace for your own company
.\START_PRAMAAN.bat demo              # the original small synthetic demo
```

Each option **replaces** the current workspace (`.demo\runtime`) and asks first. Accounts you created there are removed too, so add them again afterwards. Loading a company takes about 15 seconds; then sign in as usual.

On macOS/Linux: `PYTHONPATH=launcher PRAMAAN_DATA=.demo/runtime python -m Pramaan.backend.demo company --company hiding`.

## What gets loaded

| Folder | What it is | How PRAMAAN gets it |
|---|---|---|
| `books/` | Customers and sales (with credit notes): the company's own books | Entered into the books automatically |
| `dataset/` | Detail behind each B2B sale: quantity and HSN, dispatches and e-way bills, transport routes, journals, GSTR-1 rows, price lists, schemes, related parties, e-invoice QR codes | Imported automatically |
| `uploads/sales_register.csv` | The sales register the company hands the auditor | Uploaded and reconciled automatically |
| `uploads/gstr1/*.json` | GSTR-1 returns for Jan, Feb and Mar 2026, in the GST portal's JSON layout | Uploaded and reconciled automatically |
| `uploads/bank_statement.csv` | The bank statement | Uploaded for reading; PRAMAAN has no automatic bank check yet |

The `uploads/` files are ordinary files. You can also start from `clean` and upload them yourself on the Registers page to see each step.

## What to expect

**Kesar Home Decor (honest):**
- Register and all three GSTR-1 returns: **no differences**.
- **One review signal:** Kesari Collections bought ₹1.31 lakh in the last week of March against a usual ₹54,000 a month (T08). That's a genuine busy week from the source trading data, and a good example of what a review signal means: something to look at, not proof of anything.
- **Information gaps, not problems:**
  - Cut-off items around 31 March have no contract dates (T03).
  - Two sampled B2C sales have no transport documents in the files (T04).
  - Sales to a disclosed related party are marked as disclosed (T01).
- Every B2B e-invoice signature verifies against the demo key (T13).

**Neelgiri Lifestyle (hiding):** 12 planted problems, each found by the check meant for it. Try to find them yourself first: start from the findings summary, the Registers page and the AI assistant. Open any finding to see **How we know** (the calculation) and the **Proof chain** (the sale across every record): the shell-company sales are the clearest example. Then check [ANSWER_KEY.md](ANSWER_KEY.md).

## Where the data comes from

The trading patterns (which customer buys which product, how much, how often, and what comes back as returns) come from **UCI Online Retail II**: real transactions of a UK online gift wholesaler, 2009–2011.

> Chen, D. (2019). *Online Retail II* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D — licensed **CC BY 4.0**.

`source/online_retail_ii_extract.csv` keeps one financial year (Apr 2010 – Mar 2011), the 50 busiest repeat customers (IDs replaced by `K001`…), and each invoice's highest-value line. `scripts/derive_retail_extract.py` makes it from the original file.

`backend/sample_companies.py` turns those patterns into the two Indian companies:
- **Dates:** moved to FY 2025-26.
- **Amounts:** quantities ×4 and prices at ₹110 per £.
- **Generated in India's format:** names, cities and GST states, GSTINs, HSN codes, the CGST/SGST or IGST split, vehicles and routes, e-way bills above ₹50,000, signed e-invoice QR codes and GSTR-1 JSON.
- **Hiding company only:** the planted problems.

It's deterministic. Rebuild with `python -m Pramaan.backend.sample_companies`; `tests/test_sample_companies.py` checks that the rebuilt files match these, that the honest company stays clean, and that every planted problem is found.
