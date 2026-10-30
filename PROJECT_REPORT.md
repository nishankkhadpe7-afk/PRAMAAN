# Pramaan — Project Report

*AI-Run Statutory Revenue Audit · Elevate 1.0, Problem Statement 04 · synthetic/local prototype*

---

## 1. The problem and why it matters

Fake sales are a national-scale fraud. One recent case "sold" ₹397 crore of goods from a
desk — no warehouse, no trucks — with complete paperwork, used to claim ₹60 crore in tax
credit. Last financial year, CGST officers detected ₹74,782 crore of fake input-tax credit
across 30,162 cases — roughly ₹200 crore every day.

These fake sales land in the selling company's books as **revenue**, and a statutory auditor
has to sign off on that revenue. But the audit is thin by design: a mid-size firm makes
~7,000 sales a year and the auditor tests about **30** of them (0.43%) — against a
spreadsheet the company exported and documents the company emailed. **If the company is the
one cheating, it controls everything the auditor sees.**

## 2. What Pramaan is — the thesis

Existing tools (MindBridge, DataSnipper, process-mining) are powerful but share one starting
assumption: **the company's own records are the source of truth**, and the check is internal
consistency — does the invoice match the order, the order match the dispatch. A fraudster who
controls the company's system can make all those documents agree.

Pramaan asks a different question for every sale: **"Who, outside the company, can prove this
happened?"** Matching documents is not the same as proving a sale. That reframing is the core
innovation; everything else serves it.

## 3. Architecture — how it works

Two doors into one backend, enforcing identical rules:
- **Web UI** → REST API → for the **human auditor** and the **client employee**.
- **MCP server** → same API → for an **AI agent** (ChatGPT/Claude/Groq/local), identity-scoped.

```
 Judge's AI agent / console ──MCP (token→identity)──┐
                                                    ▼
 Web UI ───────────────► FastAPI ──► authorization (role × action × object)
                            │     ──► domain services (business lifecycle → auto journals)
                            │     ──► engine (T00–T15, provenance, sampling)
                            │     ──► workpapers / memo / receipts
                            ▼
                   SQLite (biz | audit | log)   ·   content-addressed file vault
                   append-only journal   ·   hash-chained audit log
```

**The audit flow, end to end:**
1. **Client uploads** the sales register, the related-party list, and (on request) evidence.
2. **Auditor creates a run** → the data is **snapshotted** (hashed) for reproducibility.
3. **Risk-aware sampling** picks 25–35 sales plus the year-end cut-off and credit-note sets,
   each with a **written reason** and a persisted seed.
4. **Tests T00–T15 run deterministically** and produce findings with states and evidence refs.
5. **Evidence-request loop**: the system asks the client for invoice/e-way-bill/LR/POD; each
   upload is tagged by who controls it.
6. **Human review**: only a human auditor records a final outcome — never the AI.
7. **Exports**: the workpaper (XLSX), findings memo (PDF) and a defensibility ZIP, all carrying
   a receipt (snapshot root, ruleset version, seed, hashes) so the result is recomputable.

## 4. What the tests catch (T00–T15)

- **T00** Register ↔ system-of-record reconciliation → phantom rows / suppressed sales / field diffs.
- **T01/T02** Related parties: disclosed, and **directed-graph ownership cycles** (real cycle detection).
- **T03** Cut-off by transfer of control (escalates to review when contract facts are missing).
- **T04** Missing expected movement evidence.
- **T05** Revenue without a sale (unlinked revenue credits).
- **T06** Cross-document mismatch (invoice vs dispatch, value/qty/GSTIN).
- **T07** Duplicate / misassociated evidence.
- **T08** Period-end concentration vs historical baseline.
- **T09** Credit notes after period end against pre-period invoices.
- **T10** Threshold-splitting patterns.
- **T11** Physical plausibility **P1–P5**: route/time speed, vehicle overlap (one truck, two trips),
  load vs capacity, event order, PIN/consignee mismatch. `IMPOSSIBLE` only for a hard speed
  violation on a verified-channel timestamp; everything else is review/inconsistent.
- **T12** Assertion-specific evidence provenance (the witness model).
- **T13** Signed e-invoice verification: real Ed25519 signature check + field cross-check +
  registration-timing (backdating) risk. Ships with a clearly labelled **DEMO** key; a real
  NIC/IRP public key drops into the ruleset with no code change.
- **T14** Pricing & promotions vs the effective price list.
- **T15** GST consistency (books vs GSTR-1 vs register).

## 5. The two ideas that make it unique

**(a) The witness / provenance model.** Every document is tagged by who controls it — company,
customer, transporter, bank, government. **Five copies from one source are one witness, not
five.** A sale's occurrence is only "proven" when something independent agrees. And Pramaan adds
checks the company **can't fabricate from its own system**: the e-invoice's government signature
and *when it was registered*, and physics (a truck can't be two places at once; 300 km/h is
impossible). Those signals come from outside the company's control.

**(b) The AI-trust boundary.** The obvious objection to "AI in audit" is: why trust it not to leak
or fabricate? Pramaan answers three ways that compose:
- **Rules decide, AI assists, humans conclude** — no finding originates from a model; a human sets every outcome.
- **The AI only sees redacted data** — the MCP egress-DLP layer masks GSTINs/PAN/accounts before any
  tool result reaches the model, hard-denies financial-account numbers, and **logs what it withheld**.
- **Every AI sentence must cite real evidence** — a citation validator drops any sentence that cites
  nothing or an unresolved id.

## 6. Why MCP matters

MCP is **required** by the problem statement (judges must drive the system with their own AI
agent, no code changes, on irregularities you were never told about). But it's also the right
design: it gives any model a **standard, identity-scoped tool interface**, so the AI operates the
audit while the backend — not the AI — stays in control. The token decides which tools exist,
writes are denied and logged, and the egress layer governs what leaves. That's what makes "let an
AI run a statutory audit" safe instead of reckless, and it's model-agnostic (Claude, ChatGPT,
Groq, or a fully-local Ollama for zero-egress on-prem).

## 7. Why it's trustworthy (and defensible to a regulator)

- **Reproducible**: same snapshot + seed + ruleset → identical findings; recomputable by hand.
- **Tamper-evident**: raw files hashed, ledger append-only, audit log hash-chained; edits after
  testing starts are detected and mapped to the affected tested sales.
- **Identity-bound**: an auditor identity can read everything and write nothing; enforced server-side.
- **Honest states**: SUBSTANTIATED / INTERNAL_ONLY / GAP / INCONSISTENT / IMPOSSIBLE — missing
  independent evidence is a *limitation*, not an accusation.

## 8. Measured results

On a synthetic company with planted fraud the system had never been told about
(`python -m Pramaan.backend.evaluate`):

| Metric | Value |
|---|---|
| Planted irregularities (X) | 8 |
| Caught by Pramaan (A) | **8** (recall 1.00) |
| Caught by document-matching baseline (B) | **3** (recall 0.375) |
| Hard-conflict false alarms on innocent sales (C) | **0** |

The baseline misses every case whose documents agree but whose physics, provenance, registration
timing, or counterparty graph is wrong — exactly the gap Pramaan closes.

## 9. Why it deserves to win

- **A thesis judges haven't heard twenty times.** Most entries will be "LLM flags anomalies in the
  company's data." Pramaan checks independent corroboration — a conceptual difference, not a better
  version of the same thing.
- **It answers the trust objection head-on** with a real, auditable AI-safety boundary, not hand-waving.
- **It's adversarially falsifiable, live**: bring your own agent, plant your own fraud, watch — backed
  by general rules (no hardcoded IDs), reproducibility, and a tamper-evident log.
- **It's honest.** It distinguishes what it proves from what it can't, labels demo keys, and discloses
  limits — which reads as credibility, not weakness.

## 10. Honest limitations (disclosed, not hidden)

- Synthetic data; numbers describe planted cases, not real-world accuracy.
- SQLite prototype — role isolation is app-enforced, not DB-grant-enforced; no external log anchoring.
- T13 uses a labelled DEMO signature, not the live NIC/IRP key.
- T11 distance is the *recorded route distance*, not geocoded from PIN coordinates.
- Hosted-client interop needs a public HTTPS deploy (or local desktop app); loopback-only on localhost.

## 11. How to run / demo

- **Local:** `py -m Pramaan.backend.demo reset` → `./start-local.ps1` → `cd web && npm run dev`.
- **Agent/MCP:** `agent_llm` console (Groq), or Claude/ChatGPT desktop via the MCP connector.
- **Metrics:** `python -m Pramaan.backend.evaluate`.
- See `DEMO_SCRIPT.md`, `CLIENT_DEMO.md`, and `EVALUATION.md` for details.

## 12. Tech & status

Python/FastAPI backend, React/Vite frontend, official MCP SDK, Ed25519 (cryptography),
SQLite + content-addressed vault, Groq/OpenAI-compatible agent console. **54 backend tests passing.**
