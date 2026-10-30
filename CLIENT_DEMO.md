# Client-side demo — what to upload and what it proves

As the **client employee** you provide three kinds of input. Sample files are in
`sample_uploads/`. Upload via the client portal in the UI, or the API endpoints below.

## 1. The sales register (the spreadsheet the company hands the auditor)
- `sample_uploads/sales_register_clean.csv` — matches the books exactly → T00 finds nothing.
- `sample_uploads/sales_register_tampered.csv` — what a cheating client might hand over:
  - `DEMO/26/005` gross amount altered (29,500 → 29,000) → **T00 field-difference finding**
  - a phantom row `DEMO/26/099` for 500,000 that isn't in the books → **T00 phantom/register-only finding**

Upload it, then reconcile against the system of record:
```
POST /p2/registers            {"period":"FY26","source_base64":"<base64 of the csv>"}
POST /p2/registers/{upload_id}/reconcile
```
This is the pitch's "a row that exists only in the spreadsheet, or a real sale missing
from it, is a finding."

## 2. The related-party list
- `sample_uploads/related_parties.csv` — which customers are related and how.
```
POST /p2/related-parties  {"period":"FY26","source_base64":"<base64>",
  "records":[{"customer_id":"CUST-002","related_party":true,"valid_from":"2024-01-01","relationship_type":"common director"}]}
```
Feeds T01 (disclosed related parties) and sharpens T02 (undisclosed links / cycles).

## 3. Evidence, in response to the auditor's requests
When the auditor selects a sample, the system raises evidence requests (invoice, e-way
bill, LR, POD). The client uploads documents against them:
- `sample_uploads/evidence_invoice_INV-009.txt`
```
POST /p3/evidence-requests/{request_id}/evidence
  {"evidence_id":"UP-1","document_type":"invoice","content_base64":"<base64>",
   "controller":"company","acquisition_channel":"company_upload"}
```
Note: a company-uploaded document is tagged **company-controlled** — it supports what the
company recorded, not independent corroboration. That tagging is the "witness" model.

## Tip for the demo
Upload the **tampered** register first — it gives the auditor an immediate T00 hit to open
the story with, before moving to the physics/registration/provenance findings on INV-009.
