# Pramaan — MASTER design specification

> Single source of truth for the team. If code and this file disagree, fix one of them the same day.
> PS: Elevate 1.0 · Problem Statement 04 — AI-Run Statutory Revenue Audit.

---

## 0. Principles (non-negotiable)

1. **Rules decide, AI assists, humans conclude.** No finding comes from an LLM. Only a human auditor sets a final outcome.
2. **Assess evidence by assertion and provenance.** Record who controls or supplied each item, how it was obtained, whether the source was independently verified, and which claim it can support. Different files do not automatically represent independent witnesses.
3. **Nothing is silently altered.** Raw files immutable by hash; ledger append-only; business-record edits versioned; audit log hash-chained and anchored.
4. **Same rules for every caller.** UI and MCP use the same API policy. The caller's identity and role are enforced server-side and mapped to constrained database privileges; a shared, broadly privileged DB connection must not bypass role boundaries.
5. **Reproducible by specification.** The same snapshot, persisted sampling seed, ruleset version, sampler version, canonicalization version, and export implementation must reproduce the same logical selections and results. Claim byte-identical XLSX/PDF output only after container metadata is normalized and a test proves it.
6. **Honest limits.** Tamper-evident ≠ tamper-proof. Registration ≠ delivery. Synthetic ≠ real-world accuracy.

---

## 1. Requirements (official PS)

| ID | Requirement | Component |
| --- | --- | --- |
| R1 | Client uploads sales ledger + related-party details via client interface; system notified | Client portal, import vault, notifications |
| R2 | Ledger carried into a new file = audit workpaper; data pasted **exactly as provided** | Workbook "Sales Register" sheet (verbatim) |
| R3 | Each customer marked Related / Non-related by tracing RP details | T01/T02 |
| R4 | Sales TOD 25–35 samples; random but risk-aware (esp. RPs); cover different customers, high amounts, RP & non-RP | Stratified sampler |
| R5 | Sales Cut-off TOD: ~last 10 invoices before period end, first 10–15 after; verify dispatch/delivery dates & accounting entries | Cut-off sampler + T03 |
| R6 | Samples sent to client automatically; client uploads invoice, e-way bill, LR | Evidence-request loop |
| R7 | System of record behind the register: first interaction, commitment & pricing, physical movement, revenue & tax recognition, cash settlement, promotions | Lifecycle domain model |
| R8 | Double-entry ledger that cannot be silently altered | Append-only journal, reversal-only corrections |
| R9 | Whole system as MCP server; agent with only an identity can run the business (client employee) or audit it (auditor) with exactly that identity's permissions | MCP server, two toolsets |
| R10 | Auditor identity never changes business data | Policy + DB grants |
| R11 | Client changes after testing begins detected and traced to affected samples | Snapshot diff + impact map |
| R12 | Every register ↔ system-of-record difference is a finding | T00 |
| R13 | Catch: undisclosed RPs (incl. mid-period, shared identifiers); period allocation by transfer of control; turnover without physical movement; period-end concentration of sales & discounts; statutory-document / tax-filing inconsistencies; revenue not from a sale; forged or misassociated evidence; credit notes esp. post period end | T01–T15 |
| R14 | Sample selection reproducible and carries its reasoning | Seeded sampler, reason column |
| R15 | Judges use their own agent live, no code changes; planted irregularities undisclosed | MCP + generic detection |
| R16 | Workpaper (Sales Register, Sales TOD, Sales Cut-off TOD, Credit Note TOD), findings memo with impact & proposed adjustments, tamper-evident audit trail | Workbook, memo, log |
| R17 | Grounded in SAs + accounting + indirect-tax framework; human confirms every conclusion | Standards map, review decisions |

**Brownie points targeted:** plain-language justification, continuous auditing, counterparty graph with cycles, on-premise mode, (stretch) regional-language documents.

---

## 2. Our additions beyond the PS

| # | Feature | Where |
| --- | --- | --- |
| A1 | Witness model (evidence provenance → assertion states) | §5 |
| A2 | Witness chips UI | §11 |
| A3 | Physical plausibility P1–P5 | T11 |
| A4 | Signed e-invoice payload verification adapter + registration-timing risk checks | T13 |
| A5 | Five verdicts instead of a risk score | §5.3 |
| A6 | Pramaan Evidence Integrity Layer (citation validation, number cross-check, receipts) | §9 |
| A7 | Deterministic workpapers and reproducibility receipts (byte identity is a tested stretch acceptance criterion) | §10 |
| A8 | Related-party evidence-independence assessment | §5.2 |
| A9 | Cycle detection in counterparty graph | T02 |
| A10 | Event-triggered reruns for supported evidence/business changes; full continuous auditing is a stretch | §7.4 |
| A11 | Prompt-injection resistance through untrusted-input isolation, schema validation and denied side effects | §8.5 |
| A12 | MCP-compatible client support validated against named clients + agent console fallback | §8 |
| A13 | NFRA defensibility pack | §10.4 |
| A14 | Plain-language reason per finding | §9 |
| A15 | On-premise mode (Ollama, local storage) | §12 |
| A16 | Tally-first import | §4.4 |

---

## 3. Architecture

```
 Judge agent / ChatGPT / Claude / Gemini / Groq / agent_console
                 │ MCP (Streamable HTTP, token → identity)
                 ▼
           mcp_server  ── no privileges of its own; calls API as caller
                 │
 Web UI ──────► FastAPI ──► policy (role × action × object)
                 │      ──► domain services (business lifecycle → auto journals)
                 │      ──► engine (T00–T15, assertion-specific evidence states, sampler)
                 │      ──► workpapers / memo / receipts
                 ▼
            PostgreSQL  (biz | audit | log schemas, separate DB roles)
            File store  (SHA-256 addressed)
            Worker      (parsing, extraction, test runs, exports, anchoring)
            LLM         (extraction + drafting only)
```

**Synchronous:** reads, authZ, business actions + their journal postings, review decisions, log appends (same transaction).
**Asynchronous:** file parsing, LLM extraction, full test runs, graph build, workbook/memo export, anchoring. Long jobs return `job_id`.

---

## 4. Data model

### 4.1 Schemas and DB roles

| Schema | Holds | Allowed writes | Read policy |
| --- | --- | --- | --- |
| `biz` | Company business records and immutable journal entries | Only authorized business-domain operations through a constrained `business_writer` role/connection | Auditor role is read-only; client access is tenant-scoped |
| `audit` | Runs, snapshots, samples, evidence requests, states, findings and review decisions | Restricted audit services; final review/sign-off is human-only | Auditor can read; client sees only its permitted evidence requests and submissions |
| `log` | Hash-chained audit/security events and external anchor receipts | A controlled append function/service; no ordinary UPDATE/DELETE | Authorized parties may verify, with payload access filtered by role |

**Connection rule:** the ordinary API login must not have broad direct write rights across all schemas. Use distinct constrained DB roles/connection pools or an equally strong transaction-scoped role design after server-side authorization. `auditor` has no `INSERT`, `UPDATE` or `DELETE` on `biz`; client/employee operations cannot write audit conclusions. Test direct SQL privileges as well as API/MCP denials. Enforce tenant isolation independently of UI filtering.

### 4.2 `biz` entities (abridged)

```
party(party_id PK, name, kind, gstin, pan, address_norm, pin, state_code)
party_attr(party_id, attr_type[address|phone|email|bank_acct|director_din|pan], value_norm)   -- shared identifiers
relationship(rel_id PK, party_a, party_b, rel_type, valid_from, valid_to, source[disclosed|discovered])
unit(unit_id PK, name, state_code)           -- e.g. Goa, Mumbai
business_unit(bu_id PK, name)                -- e.g. Marine, Industry, Electronics & Automation
item(item_id PK, name, hsn, unit_weight_kg, uom)
price_list(item_id, valid_from, valid_to, list_price)
scheme(scheme_id PK, name, valid_from, valid_to, max_discount_pct, eligible_customers JSONB)

enquiry(enq_id PK, customer_id, received_at, channel)
quotation(quote_id PK, enq_id, quoted_at, valid_until)
quotation_line(quote_id, line_no, item_id, qty, quoted_price, discount_pct, scheme_id NULL)
job(job_no PK, customer_id, bu_id, unit_id, contract_type[goods|service|project], incoterm, opened_at)
sales_order(so_id PK, quote_id NULL, job_no, customer_id, so_date, incoterm, sale_type)
so_line(so_id, line_no, item_id, qty, unit_price, discount, packing, freight, insurance)
dispatch(dispatch_id PK, so_id, dispatch_ts, vehicle_no_norm, transporter_id, lr_no)
dispatch_line(dispatch_id, so_id, line_no, qty)
ewaybill(ewb_no PK, invoice_id NULL, generated_at, valid_from, valid_to, vehicle_no_norm, distance_km, from_pin, to_pin)
delivery(delivery_id PK, dispatch_id, pod_ts, received_by)
invoice(invoice_id PK, bill_no UNIQUE, unit_id, bu_id, job_no, customer_id, invoice_date,
        total_cost, discount, packing, freight, insurance, igst, cgst, sgst, tcs, round_off, gross_amt,
        tax_desc, ledger_account, irn NULL, irn_ack_date NULL, signed_qr NULL, einv_status)
journal(journal_id PK, posting_date, source_type, source_id, created_by, created_at, reverses NULL)
journal_line(journal_id, line_no, account_code, debit, credit,
            CHECK (debit >= 0 AND credit >= 0 AND
                   ((debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0))))
receipt(receipt_id PK, customer_id, amount, value_date, bank_ref, payer_account)
receipt_alloc(receipt_id, invoice_id, amount)
credit_note(cn_id PK, cn_no UNIQUE, invoice_id, cn_date, amount, reason, irn NULL)
gst_return(ret_id PK, form[GSTR1|GSTR3B], period, filed_at)
gst_return_line(ret_id, doc_type, doc_no, doc_date, ctin, taxable, igst, cgst, sgst)
evidence(evidence_id PK, sha256, doc_type, claimed_controller, acquisition_channel, uploaded_by, uploaded_at,
         source_verified BOOL, source_verification_method, source_ref, origin_ref, meta JSONB)
evidence_link(evidence_id, object_type, object_id, link_basis[key|candidate_fuzzy|fuzzy_confirmed|manual], confirmed_by)
record_version(tbl, pk, version, row_json, row_hash, actor, changed_at)   -- every edit kept
register_upload(upload_id PK, sha256, uploaded_by, uploaded_at, period, row_count)
register_row(upload_id, row_no, raw JSONB, row_hash)                     -- verbatim
```

### 4.3 `audit` and `log`

```
audit_run(run_id PK, period_start, period_end, materiality, sampling_seed, ruleset_version,
          sampler_version, canonicalization_version, snapshot_root, snapshot_created_at, status)
snapshot_row(run_id, tbl, pk, row_hash, row_json)
sample_item(run_id, sheet[TOD|CUTOFF|CN], item_no, invoice_id|cn_id, stratum, selection_reason,
            sample_design, seed_draw, inclusion_probability NULL)
evidence_request(req_id PK, run_id, sample_ref, required_docs TEXT[], status, created_at, fulfilled_at)
assertion_state(run_id, invoice_id, assertion[occurrence|accuracy|cutoff|classification], state, reasons JSONB)
finding(finding_id PK, run_id, ref, test_ids TEXT[], evidence_ids TEXT[], impact_inr, proposed_adj JSONB,
        plain_reason, narrative, narrative_model)
review_decision(finding_id, decided_by, outcome[EXCEPTION_CONFIRMED|EXPLAINED|DATA_ERROR], reason, decided_at)
post_test_change(run_id, tbl, pk, old_hash, new_hash, actor, detected_at, affected_samples TEXT[], logged BOOL)

log.event(seq PK, ts, actor, role, channel[ui|mcp|system], action, object_ref, payload_hash, decision, prev_hash, entry_hash)
log.anchor(seq, entry_hash, method[tsa|git|public], token, anchored_at)
```

### 4.4 Integrity rules

- **Double entry:** use a deferred constraint trigger to enforce Σdebit = Σcredit per journal at commit. Also constrain debit/credit values to be non-negative and require each line to post to exactly one side. Validate that an entire journal has at least two lines.
- **Append-only ledger:** ordinary roles cannot UPDATE/DELETE `journal` or `journal_line`; corrections use a new, linked reversing/adjusting journal. Privileged database tampering remains a threat to mitigate, not a capability to claim impossible.
- **Auto-posting:** domain services post journals from validated business events. Manual revenue journals are allowed only through a restricted workflow and tagged as manual for review; example entries in this design are illustrative and must be reviewed by a CA mentor.
- **Versioning:** every business-record change writes an immutable version record and actor/time metadata through controlled writes and/or database triggers.
- **Post-test change:** snapshot the selected population and linked evidence at audit-run start. Triggers emit change events; a separate comparison re-hashes relevant current records against the snapshot so unlogged changes can be detected. Record the precise changed field and downstream samples/findings affected.
- **Log chain:** hash canonical event content with a predecessor hash. Anchor chain heads externally on a documented schedule and at run close. An anchor only supports claims about data covered by that anchor; it does not make the database tamper-proof.
- **Raw imports:** keep the original uploaded file content-addressed by SHA-256. Preserve source rows/cells in the original representation; place row hashes and normalized/reconciliation metadata in a separate provenance sheet/table. Never append a hidden hash column to the verbatim source worksheet.
- **Reproducibility:** store the sampling seed and all rule/export versions with the run. Reproduction means identical selections, tests, evidence references and calculated outputs for the same snapshot and versions. Byte-identical export files are a separate acceptance test and must not be claimed until achieved.

---

## 5. Evidence provenance model (core differentiator)

The witness model is a **provenance and assertion-support model**, not a single score for whether an entire sale is “real”. Store the evidence source, acquisition channel, verification method, integrity status, relationship to the counterparty, and the exact assertion it supports.

### 5.1 Initial provenance classes

| Situation | Default treatment | What it can establish |
| --- | --- | --- |
| Company-created or company-supplied document with no independent source verification | `COMPANY_CONTROLLED` | What the company recorded or asserted; not independent corroboration |
| A bank/customer/transporter document uploaded by the company but not independently authenticated | `COMPANY_SUPPLIED_UNVERIFIED` | Candidate evidence requiring validation; don't elevate it merely from its logo or claimed issuer |
| Counterparty response obtained through a verified, auditor-controlled channel | `COUNTERPARTY_VERIFIED` | Only the facts the response actually confirms; assess related-party and collusion risk separately |
| Government e-invoice registration/signature validated against the appropriate trusted key and current official process | `GOVERNMENT_REGISTERED` | Registration/authenticity of the covered payload and associated registration timing; not physical delivery by itself |
| Bank/transporter/other third-party record obtained and verified via a documented independent channel | `THIRD_PARTY_VERIFIED` | The specific facts reliably established by that source, subject to its scope and limitations |

The uploader must not be allowed to self-declare a document as independent or government-verified. The application records acquisition channel and verification results server-side. A company-uploaded document remains unverified until an independent verification process justifies a different status. Copies derived from one original source share provenance; five copies are not five witnesses.

### 5.2 Independence and related parties

- Different file types or different nominal issuers do **not** by themselves establish independence. Compare origin, controller, acquisition channel and common-source relationships.
- Evidence obtained directly from a counterparty may still be weak for independence if the counterparty is related to the client, under common control, or otherwise conflicted. Record that relationship and the reason for the downgrade; do not mechanically label it as company-created.
- Weak shared attributes such as a common industrial-estate address create a relationship lead, not a related-party conclusion. Stronger identifiers and multiple sources increase relevance but still require a dated, explainable assessment.
- `GOVERNMENT_REGISTERED` supports invoice registration, specified payload fields and registration time. It does not alone substantiate occurrence, physical movement, delivery or transfer of control.
- A source only counts as corroboration for an assertion the source is capable of supporting. Evidence for cash settlement is not automatically evidence of delivery; transport evidence is not automatically evidence of revenue recognition.

### 5.3 Assertion states

Compute state per assertion (`occurrence`, `accuracy`, `cutoff`, `classification`, and where implemented, `completeness`), not as a universal verdict on the whole sale.

| State | Meaning |
| --- | --- |
| `SUBSTANTIATED` | The specified assertion meets its versioned evidence criteria, including required source reliability and consistency. It does not prove every other assertion or the entire sale. |
| `INTERNAL_ONLY` | Available evidence for that assertion is controlled by, or supplied without independent verification from, the company. This is a limitation, not fraud. |
| `GAP` | Expected event/evidence is missing or unavailable and there is no known contradiction. |
| `INCONSISTENT` | Relevant records disagree beyond a documented tolerance, or a check identifies an unresolved conflict. |
| `IMPOSSIBLE` | A hard physical/temporal constraint is contradicted by reliable, validated inputs and the rule's assumptions are met. Heuristic distance, PIN, capacity or timing concerns should normally be `INCONSISTENT`/`GAP` pending review. |
| Human outcome | `EXCEPTION_CONFIRMED`, `EXPLAINED`, or `DATA_ERROR`, set only by an authorized human auditor. |

The UI may summarize the highest-priority issues for an invoice, but must not turn one `SUBSTANTIATED` assertion into an unqualified “sale proven” badge. Missing independent evidence alone is not a fraud finding; it is a limitation or request for further evidence.
---

## 6. Audit tests

All thresholds live in versioned `ruleset.yaml`; the version is printed on every workpaper.

| ID | Test | Default rule | Typical output |
| --- | --- | --- | --- |
| T00 | Register ↔ SoR reconciliation | First match on stable identifiers; use date+customer+amount only to generate candidate matches, resolve ambiguity explicitly, and compare every required column | phantom / suppressed / field-diff findings |
| T01 | RP tracing (disclosed) | Customer relationship is effective on the relevant transaction date; retain relationship source and date range | Related-party classification / review |
| T02 | RP discovery + cycles | Dated candidate links from configured identifiers and evidence provenance; cycles in the goods/money graph are relationship patterns for review. Weak identifiers alone do not establish a related party. | RP candidate / relationship lead / cycle finding; not automatic fraud |
| T03 | Cut-off by transfer of control | Derive the candidate control date from contract facts, applicable terms and the approved accounting policy; mappings require CA review. If facts are insufficient, require review rather than applying a universal Incoterm shortcut | PASS / INCONSISTENT / GAP / human review |
| T04 | Missing physical movement | For a goods sale, check expected lifecycle evidence (dispatch and, where required, EWB/POD) under a documented rule; missing records alone do not prove no movement | GAP / evidence request |
| T05 | Revenue not from a sale | revenue credit without invoice/SO link; manual journals to revenue | INCONSISTENT |
| T06 | Cross-document mismatch | Invoice vs EWB/dispatch/order: compare value and quantity using versioned tolerances, GSTIN, PIN and vehicle; fuzzy matches remain candidates until confirmed | INCONSISTENT / needs review |
| T07 | Duplicate / misassociated evidence | Same file hash or unique document reference linked to multiple transactions; allow legitimate shared/supporting documents where the business context explains the reuse | INCONSISTENT / review |
| T08 | Period-end concentration | Configured period-end window and threshold compared with an appropriate historical baseline; require sufficient comparable history and version the parameters | Risk signal → sampler |
| T09 | Credit notes | CN after period end against pre-period invoice; unusual ratio/reason or missing return evidence where return is expected by the case facts | review finding + reassess cut-off; not automatic error solely because CN is post-period |
| T10 | Threshold splitting | Same customer and close dates, multiple invoices clustered below a configured, applicable threshold; threshold source/version must be recorded | Risk pattern for review; does not prove intent |
| T11 | Physical plausibility | P1 route/time bounds · P2 vehicle overlap · P3 load estimate · P4 event order · P5 PIN/consignee mismatch. Use verified source timestamps, explicit distance/capacity assumptions and tolerances | `IMPOSSIBLE` only for a hard constraint with reliable validated inputs; otherwise `INCONSISTENT`/`GAP` and review |
| T12 | Evidence provenance / assertion support | §5; evaluate each assertion separately | `SUBSTANTIATED` / `INTERNAL_ONLY` / `GAP` / `INCONSISTENT` |
| T13 | E-invoice signature and registration timing | Verify signed QR/IRN using the applicable documented official procedure and trusted keys; compare signed fields with books. A later acknowledgement date is a backdating-risk indicator to investigate, not proof of backdating. Demo keys must be labelled separately. | Signature/field mismatch or timing-risk finding; never `IMPOSSIBLE` solely due to later acknowledgement |
| T14 | Pricing & promotions | Compare price/discount with the effective price list and scheme terms for the transaction date; exceptions may be authorized and require context | INCONSISTENT / review |
| T15 | GST consistency | Compare books ↔ signed/registered invoice data ↔ GSTR-1 ↔ register (document, date, GSTIN, taxable value and tax split). Evaluate place-of-supply and applicable tax rules; state code alone may not resolve every case. | INCONSISTENT / review |

**Standards mapping (confirm paragraph numbers with a CA mentor before printing):** SA 500 (evidence reliability → T12), SA 530 (sampling), SA 550 (related parties → T01/T02), SA 560 (subsequent events → T09), SA 240 (fraud risk in revenue), Ind AS 115 (control transfer → T03, bill-and-hold), CGST Act e-invoice / e-way bill rules (T13, T15, T04).

---

## 7. Sampling & evidence requests

### 7.1 Seed
Generate or accept an explicit high-entropy `sampling_seed` at run creation and persist it; do not silently regenerate it on rerun. Fingerprint the design as `SHA256(snapshot_root ‖ sampling_seed ‖ ruleset_version ‖ sampler_version)`. A new run may use a new seed; reproduction reuses the stored seed and exact versions. Store each random draw and tie-break rule.

### 7.2 Sales TOD (25–35)
Design a 25–35-item Sales TOD with configurable, documented strata and each item carrying a `selection_reason`:
1. **Related-party exposure** — include RP and non-RP transactions where population size permits. Do not promise that every RP customer is individually represented when the RP population exceeds the sample budget; report coverage and omissions explicitly.
2. **High value** — transactions selected under a documented, versioned threshold or certainty-selection rule.
3. **Risk signals** — `INTERNAL_ONLY`, `IMPOSSIBLE`, `INCONSISTENT`, period-end concentration, unusual credit notes and other ruleset hits.
4. **Probability sample** — separately identify the random population sample and record inclusion probabilities when the selected design supports them.

Handle duplicates across strata without inflating sample counts. Record selected/eligible population sizes, selection policy, seed, rule/sampler versions and exclusions. Risk-targeted and certainty selections are reported separately. **Do not make population-projection claims** unless a qualified reviewer confirms the probability design and inclusion probabilities support them. A per-customer cap or convenience selection can invalidate a naive projection.

### 7.3 Cut-off TOD
Order invoices by date; select approximately the last 10 before and first 10–15 after `period_end` (configurable for the audit period). If fewer transactions exist on either side, document the population and the reduced coverage. Test dispatch/POD dates and journal posting date against a control date determined from contract facts and the accounting policy approved for the engagement. Unresolved contract terms produce a review state, not a guessed control date.

### 7.4 Credit Note TOD
All CNs in the 90 days after period end + random/high-value CNs in period.

### 7.5 Evidence-request loop
Selection → `evidence_request` per sample (invoice, EWB, LR; POD for cut-off; CN + return docs for CN TOD) → client portal + MCP `list_evidence_requests` → upload → provenance tagging → affected tests are rerun against a new version/snapshot. Event-triggered reruns are in scope where supported; always-on continuous auditing is a stretch capability.

---

## 8. MCP

### 8.1 Server
- Official MCP Python SDK, Streamable HTTP at `/mcp`.
- Holds no privileges; resolves token → `{user, role, expiry}` → calls API as that user.
- `tools/list` may be filtered by role for usability, but **every call is authorized server-side**; hiding a tool is not a security boundary.
- MCP server has no database privileges and cannot manufacture a role. It maps a validated, expiring credential to an identity and forwards that identity to the API.
- Every call is logged: agent_id, user, tool, arguments hash, decision and correlation ID. Do not log secrets, raw tokens or tokenized URLs.

### 8.2 Authentication (all resolve to the same identity row)
1. Prefer `Authorization: Bearer <token>` when the client supports custom headers.
2. A path-token URL may be used only as a documented compatibility fallback for a client that requires it. Treat the full URL as a bearer secret: use short-lived, high-entropy, per-judge, revocable tokens and redact the URL from logs, analytics, screenshots and shell history.
3. OAuth 2.1 may be added if the selected client/server combination supports it and time allows.

Do not assume all named AI clients expose identical MCP authentication or connector settings. Test the exact clients used for judging before promising compatibility.

### 8.3 Client-employee tools
`create_customer` · `disclose_related_party` · `create_enquiry` · `create_quotation` · `create_sales_order` · `record_dispatch` · `generate_eway_bill` · `record_delivery` · `raise_invoice` · `record_receipt` · `issue_credit_note` · `post_manual_journal` · `update_business_record` (versioned) · `upload_evidence` · `upload_sales_register` · `upload_related_parties` · `export_sales_register` · `list_evidence_requests` · `respond_to_evidence_request`

### 8.4 Auditor tools
`create_audit_run` · `import_register_to_workpaper` · `trace_related_parties` · `select_sales_tod` · `select_cutoff_tod` · `select_credit_note_tod` · `send_evidence_requests` · `run_tests` · `get_sale_lifecycle` · `get_witnesses` · `get_assertion_states` · `get_relationship_paths` · `find_cycles` · `get_findings` · `draft_narrative` · `propose_review_decision` · `get_post_test_changes` · `verify_audit_log` · `reproduce_workpaper` · `export_workpaper` · `export_memo` · `get_job_status`

**Human-only (web UI):** final `record_review_decision`, partner sign-off.

### 8.5 Tool design rules
Flat schemas, enums, `limit` (default 20) + pagination, compact JSON + one-line summary, clear error strings (`DENIED: role 'auditor' cannot modify business records`), long jobs → `job_id`. Document text only inside `untrusted_document_content`. Server `instructions` field explains the workflow.

### 8.6 Agent console
Model-agnostic MCP client: lists tools → converts to OpenAI function schemas → runs loop against any OpenAI-compatible endpoint (Groq, Gemini, OpenRouter, Ollama) with a model dropdown. Demo + offline backup.

---

## 9. Pramaan Evidence Integrity Layer (AI usage)

| AI does | Guard |
| --- | --- |
| Extract fields from invoices / EWB / LR / POD (incl. regional language, stretch) | JSON schema; cross-check with ledger + signed QR; low confidence → human |
| Propose fuzzy links | Auditor/rule confirms; stored as `fuzzy_confirmed` |
| Draft narrative + plain-language reason | Every sentence must cite a valid evidence ID; validator rejects otherwise; model name stored |
| Operate via MCP | Same permissions as a human of that role |

AI never: computes totals, sets states, selects samples, confirms exceptions.

---

## 10. Outputs

### 10.1 Workbook (`Pramaan_<client>_<period>.xlsx`)
- **Sales Register** — original uploaded columns and values preserved verbatim in a separate worksheet. Do not add hidden columns, formulas, formatting edits or hashes to this source sheet. Store row hashes, normalized values and reconciliation metadata in a separate `Provenance`/`Import Metadata` sheet or structured metadata table; reference original row numbers and hashes from audit workpapers.
- **Sales TOD** — header (client, period, area, objective: accuracy & occurrence), work-done steps, columns: Sr No · Unit · Quarter · Month · Bill no · Date · Job No · Customer · BU · Related/Non-Related · Total Taxable value · Selection reason · Invoice ✓ · EWB ✓ · LR ✓ · POD ✓ · Journal ✓ · Witness state · Finding ref.
- **Sales Cut-off TOD** — Sr No · Unit · Quarter · Month · Bill no · Date · Job No · Customer · Ledger Account · State Code · GST No · Total Cost · Discount · Packing · Freight · Insurance · Dispatch date · POD date · Control date · Posting date · Correct period? · Finding ref.
- **Credit Note TOD** — CN no · date · original invoice · amount · reason · post-period? · goods returned? · Finding ref.
- **Findings** — ID, test, plain reason, ₹ impact, proposed adjustment, reviewer outcome.
- **Receipt** — snapshot root, ruleset version, sampler version, canonicalization/export version, persisted sampling seed, selection digest and output content digest.
- **Provenance / Import Metadata** — source file hash, import ID, original worksheet/row references, row hashes, canonicalized comparison fields and parsing warnings.

Tickmarks legend sheet. All exception cells link to Findings rows. Byte-identical XLSX/PDF reproduction requires normalized file metadata and pinned dependencies; otherwise report a canonical content digest and disclose that container bytes may differ.

### 10.2 Findings memo (PDF)
Per finding: what, evidence IDs and provenance, assertion affected, relevant test/rule version, standard/policy reference subject to CA review, known facts vs inference, ₹ impact only where supported, proposed adjustment for auditor consideration, reviewer decision and unresolved questions. Any journal examples are illustrative; the correct entry depends on the facts and approved accounting policy. Summary totals must reconcile to the findings table.

### 10.3 Audit trail
`verify_audit_log` report: chain OK/broken at seq, last anchor, unlogged changes.

### 10.4 NFRA defensibility pack
Zip: workbook + memo + per-sample evidence index + standards mapping + log verification + receipts.

---

## 11. UI (minimum)

- **Client portal:** upload register + RP list, evidence-request inbox, business screens (or rely on MCP).
- **Auditor workspace:** run setup → samples with reasons → sale view (lifecycle timeline, **witness chips**, failing tests, graph snippet) → findings review → exports → log verification → post-test change alerts with affected rows.

The detailed route map, screen behaviour, mock-data approach and phase-safe frontend integration contract live in [`website.md`](website.md). Apply the team's existing `design.md` for visual tokens and component styling; it is not replaced by the website specification.

---

## 12. Security & deployment

- Threat actors: client insider (alter after testing, fabricate evidence), rogue/confused agent, auditor overreach, DB admin (partial mitigation via anchoring).
- AuthN tokens with expiry; per-judge revocable; secrets in `.env` (git-ignored).
- Rate limits per token; upload size cap; file-type allow-list (PDF, PNG, JPG, XLSX, CSV, XML).
- **On-premise mode (stretch):** `LLM_PROVIDER=ollama`, local file store, and explicit network-egress policy. Do not promise “no data leaves the laptop” until telemetry, dependencies, model pulls, anchoring and all outbound network paths have been verified or blocked.
- Backups: `pg_dump` + file store; anchors kept separately.
- Failure modes: LLM down → deterministic tests still run; anchor service down → git-published head; fuzzy link wrong → needs confirmation.

---

## 13. Evaluation

Synthetic generator writes `truth.csv`, which the production audit code must never read (see `synth/README-SYN.md`). Measure precision/recall per planted class, false-positive rate on clean sales and innocent traps, evidence-trace completeness, selection reproducibility, logical workpaper reproducibility, permission-matrix denials and logging, and comparison against a stated baseline. Byte-identical files are a separate test requiring normalized output metadata. Report only measured values with dataset seed, generator version, ruleset version, sampler version and test command.

---

## 14. Glossary

TOD — test of details · RP — related party · SoR — system of record · EWB — e-way bill · LR — lorry receipt · POD — proof of delivery · IRN/IRP — invoice reference number / invoice registration portal · MUS — monetary unit sampling · MCP — Model Context Protocol · SA — Standard on Auditing (ICAI) · NFRA — National Financial Reporting Authority.
