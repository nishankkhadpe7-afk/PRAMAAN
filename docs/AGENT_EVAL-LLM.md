# Investigation agent — measured evaluation

Generated 2026-11-07T20:50:17.664998+00:00 by `python -m Pramaan.backend.evaluate_agent`.
Planner: **llm** (model `gemini-3.1-flash-lite-preview, gemini-3.7-flash`); prompt `investigate-v2`; fixture seed `pramaan-agentx-fixture-2026`.
Dataset: 26 synthetic sale lifecycles, 26 planted cases. synthetic - generated for agent evaluation; not real bank data.

| Metric | Result |
|---|---|
| Traced to source | 26/26 |
| Invented amounts | 0 |
| Correct outcome (explained / not explained / conflict) | 25/26 |
| Planted conflicts escalated | 5/6 |
| False escalations | 0 |
| Median machine seconds per exception | 7.085 |
| Median tool calls per exception | 3.0 |
| Model summaries rejected by the amount check | 0 |
| Other model texts withheld (plans, questions, next step) | 0 |

## By planted case

| Case | Correct |
|---|---|
| exact | 4/4 |
| near_date | 3/3 |
| split | 3/3 |
| partial | 3/3 |
| missing | 4/4 |
| duplicate | 3/3 |
| possible_party | 2/3 |
| register_variance | 3/3 |

## Misses

- `AGX-I022` (possible_party): expected conflict, got not explained (status `needs_confirmation`).

## Limitations

- Synthetic data only; no real bank statements or client books were used.
- Seconds per exception measure the agent's machine time, not auditor time saved; no manual baseline was timed.
- The deterministic-baseline planner follows a fixed policy; LLM results depend on the model and provider and should be re-measured per model.
- The test data's bank narrations use abbreviations the party matcher already knows (Mfg, Trdrs, Retl...), so payer matching here is easier than on real statements. On unseen spellings the matcher mostly falls to 'possible match' (escalates), but can miss ('FICTIONAL MFRS') or over-match ('Astra' vs 'Aster Components').
- Planted 'possible party' payers swap the customer's first name (e.g. 'Sharma Traders' -> 'Verma Traders'). When the swap leaves little in common ('Banyan Retail' -> 'Verma Retail'), the matcher scores it as an unrelated payer, so the agent treats the invoice as unpaid and proposes an evidence request instead of escalating a conflict.
