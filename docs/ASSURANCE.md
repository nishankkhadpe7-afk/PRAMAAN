# Statistical assurance and the verifiable log

Three additions beside the rule engine. None of them changes a frozen run, and none states a conclusion.
API only for now: there is no screen for them yet.

## 1. Verifiable event log (`backend/transparency.py`)

The event log was already a hash chain. It now also has a Merkle tree (RFC 6962 / RFC 9162 hashing, the
scheme used by Certificate Transparency), so one entry can be proven without replaying the whole log.

| Call | What you get |
|---|---|
| `GET /log/checkpoint` | Tree size, Merkle root, time, Ed25519 signature |
| `GET /log/proof?seq=N` | The entry, its inclusion path and a checkpoint |
| `GET /log/consistency?first=SIZE` | Proof that today's log still contains the log of an earlier checkpoint unchanged |

Check a proof offline, with no access to PRAMAAN:

```
python scripts/verify_log_proof.py inclusion proof.json --public-key <key from the audit firm>
python scripts/verify_log_proof.py consistency consistency.json --earlier old_checkpoint.json
```

**What makes rewriting detectable** is a checkpoint held by someone else: save one at each milestone and
give it to the client. PRAMAAN cannot do that step for you, and it does not yet submit checkpoints to an
outside timestamping service. The signing key is `PRAMAAN_LOG_SIGNING_KEY` (base64, 32 bytes) or a
per-instance key created beside the database (`log-signing.key`, git-ignored). Back it up with the data.

## 2. Monetary-unit sampling (`backend/assurance.py`)

1. `POST /assurance/runs/{run}/mus-plans` with `confidence` (90, 95 or 99), `tolerable_misstatement` and
   optionally `expected_misstatement`. The sample is drawn from the run's frozen invoices; the same inputs
   always give the same sample. Any invoice at least as large as the sampling interval is always selected.
2. A human reviewer records the audited amount of each selected invoice:
   `POST /assurance/mus-plans/{plan}/results`. Entries are append-only; a later entry supersedes.
3. `GET /assurance/runs/{run}/mus-plans` returns the evaluation: projected misstatement, basic precision,
   incremental allowance and the upper misstatement limit (Stringer bound), compared with tolerable.

Sample size = book value x confidence factor / (tolerable - expected x expansion factor). Confidence
factors are exact Poisson limits (3.00 at 95% with no errors). Limits: overstatement only; understated
items are listed, not projected. The result supports the auditor's conclusion and does not replace it.

## 3. Anomaly screen with a controlled false-alarm rate (experimental)

`GET /assurance/runs/{run}/anomaly-screen?reference_run_id=...&alpha=0.1`

Each invoice is scored on its amount and on its amount compared with the same customer's earlier
invoices. Scores are turned into conformal p-values against a reference run the auditor accepts as
ordinary, then the Benjamini-Hochberg step keeps the expected share of false alarms among flagged
invoices at or below `alpha`. Invoices that a person confirmed as exceptions are removed from the reference.

**Measured, and the honest result:**

| Test | Result |
|---|---|
| Simulated data, 30 trials, 20 planted 60x amounts in 600 invoices, alpha 0.1 | Average false-alarm share within 0.1; at least 80% of planted found |
| Kesar (honest) as reference, Neelgiri (hiding) screened | **0 flagged.** The planted invoices are not unusual in amount: ordinary retail orders vary just as much |
| Kesar split in two, one half screened against the other | 0 flagged |

So on the sample companies the screen adds nothing to the rules: what Neelgiri hides is relational
(a shared director, a missing GST return row, goods that did not move), not an odd amount. The screen
is kept as an experimental tool for populations where amounts are stable; it does not clear an invoice
it does not flag. Unit price and quantity by HSN code were tried and dropped as noise.

A reference set of n invoices cannot flag fewer than about m / (n x alpha) invoices out of m screened;
the response reports this as `minimum_flags_for_any_detection`.

## Reading

- Bates, Candes, Lei, Romano, Sesia. Testing for outliers with conformal p-values. doi:10.1214/22-AOS2244
- Cross-conformal anomaly detection. doi:10.48550/arXiv.2402.16388
- Laurie, Langley, Kasper. Certificate Transparency (RFC 6962); Laurie et al., version 2 (RFC 9162)
- Stringer (1963) bound; AICPA Audit Guide: Audit Sampling (confidence and expansion factors)
