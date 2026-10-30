# Pramaan — synthetic evaluation (measured)

Regenerate with: `python -m Pramaan.backend.evaluate`  (JSON: `--json`).
Ground truth lives in `backend/evaluation_truth.json` and is read **only** by the
evaluator, never by the audit engine — detection is by general rules, not by
knowledge of which rows are planted.

## Headline numbers

- Dataset version: **1.2** · seed `pramaan-eval-seed-2026-0001` · period 2025-04-01 → 2025-06-30
- Planted irregularities (**X**): **8**
- Caught by Pramaan (**A**): **8** — recall **1.00**
- Caught by a document-matching baseline (invoice vs order/dispatch) (**B**): **3** — recall **0.375**
- Hard-conflict false alarms on innocent sales (**C**): **0**
- Review-only risk flags on innocent sales: INV-001, INV-008 (threshold-splitting *pattern* review; not confirmed exceptions, by design)

## Per-class breakdown

| Planted entity | Class | Caught | By tests | Baseline catches? |
|---|---|---|---|---|
| INV-003 | document mismatch + consignee | yes | T06, T11, T15 | yes |
| INV-004 | forged signed e-invoice payload | yes | T13 | no |
| INV-005 | vehicle overload + quantity mismatch | yes | T06, T11 | yes |
| INV-006 | impossible event order | yes | T11 | no |
| INV-007 | impossible route speed | yes | T11 | no |
| INV-009 | related-party fabricated sale (hero) | yes | T01, T06, T11, T13, T15 | yes |
| JRN-MAN-001 | revenue without a sale | yes | T05 | no |
| CYCLE | counterparty ownership cycle | yes | T02 | no |

## What this shows

The document-matching baseline catches only the 3 cases whose paperwork visibly
disagrees. It misses every irregularity whose documents *agree* but whose physics
(T11), evidence provenance, registration timing (T13), independent revenue source
(T05) or counterparty graph (T02) is wrong — 5 of 8 here. That gap is the entire
thesis: matching documents is not the same as proving a sale happened.

## Honest limits

- Synthetic dataset; numbers describe these planted cases, not real-world accuracy.
- Innocent-trap coverage is thin in the pure P3 import path (no genuine-return
  credit note or shared-PO trap). Adding those would make the false-positive
  measurement more adversarial; recommended next step.
- The signed-QR path uses a labelled DEMO key, not the official NIC/IRP key.
