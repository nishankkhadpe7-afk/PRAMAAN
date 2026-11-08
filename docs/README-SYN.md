# Pramaan - Synthetic data generator & detection checker

> **Why synthetic?** We cannot use a real company's books in a public hackathon. Synthetic data gives us a known test oracle: we know which conditions were planted and can measure what Pramaan catches and what a baseline misses. This validates the tested mechanism on the generated distribution; it does **not** prove real-world audit accuracy.
> All entities and identifiers are fictional demo data. Never use generated identifiers as proof of a real registration or query them as if they belonged to a real party.

---

## 1. What it produces

```
data/<seed>/
├── company.json                 fictional company profile
├── masters/                     customers, directors, relatives' firms, transporters, vehicles, items, price list, schemes
├── sor/                         system-of-record tables (CSV) — loaded into the biz schema
├── exports/
│   ├── sales_register.xlsx      client export in the PS reference column format (may DIFFER from SoR on purpose)
│   └── related_parties.xlsx     disclosed RP list (deliberately incomplete)
├── evidence/                    PDFs/images: invoices (with signed QR), e-way bills, LRs, PODs, bank advices, CN docs
├── gst/                         synthetic GSTR-1 (and GSTR-3B summary)
├── keys/                        test-only demo signing key pair; private key is generator-only and never loaded by Pramaan
├── truth.csv                    HIDDEN answer key — never read by Pramaan
└── manifest.json                seed, generator version, SHA-256 of every file
```

---

## 2. The fictional company (mirrors the PS reference shape)

| Attribute | Value |
| --- | --- |
| Name | **Neelsagar Marine Electricals Pvt Ltd** (fictional) |
| Units | Goa (state code 30), Mumbai (27) |
| Business units | Marine Goa · Industry Goa · Marine Electronics & Automation |
| Customers | ~60 fictional shipyards, dockyards, naval-repair-style yards, industrial and data-centre firms |
| Sale types | goods (panels, switchboards, cables), service (installation, AMC), project/job (milestone billing) |
| Volume | 6,000–8,000 invoices / year (configurable; 1,200 for fast demo) |
| Period | FY 2025-26 (1 Apr 2025 – 31 Mar 2026); half-year mode ends 30 Sep 2025 |
| Seasonality | Diwali bump, March year-end push |
| Taxes | IGST for inter-state, CGST+SGST intra-state (by state code), TCS where applicable |

### Register columns (match PS Fig. 1)
`Bill No · Date · Job No · Customer · Ledger Acc · State Code · GST No · Total Cost · Discount · Packing · Freight · Insurance · IGST · CGST · SGST · TCS Collection · Round · Gross Amt · Tax · BU · E-Invoice`

Bill number pattern: `<UnitPrefix>/<seq 4-digit>/<YY>` (e.g. `G/0412/26`), service bills `GS/…`.

### Realism sources
- **Names/addresses:** Python `Faker` (`en_IN`).
- **GSTIN-like identifiers:** generated to exercise parsing/format checks with fictional values. A syntactically valid pattern does not establish that an identifier is unused or belongs to a real entity; mark fixtures as synthetic and never claim live GST registration from this generator.
- **Geography:** real PIN-code lat/long dataset (India Post all-India PIN directory, data.gov.in — verify current version) → great-circle × road factor (≈1.3) for distances.
- **Vehicles:** Indian plate format, fictional; capacity classes 9 t / 16 t / 25 t.
- **Documents:** HTML templates → PDF via WeasyPrint; optional "scanned" look (rotation + noise).

---

## 3. How generation works

1. **Masters** — customers, directors, relatives' firms, transporters, vehicles, items, price list, schemes.
2. **True business** — simulate enquiries → quotes → orders → dispatch → EWB → POD → invoice (+ mock e-invoice: IRN, ack date, signed QR) → journals → receipts → occasional genuine CNs.
3. **Plant irregularities** — modify a chosen subset per the catalogue below; record each in `truth.csv`.
4. **Innocent traps** — realistic noise that must *not* be flagged as fraud.
5. **Export** — sales register (with planted register-only differences), disclosed RP list (incomplete), GSTR-1, evidence files.
6. **Manifest** — source hashes, seed, generator version and dependency/version metadata. Use fixed timestamps, stable sorting and seeded randomness. Verify byte-identical generation in a test; some PDF/XLSX libraries may embed timestamps or environment-dependent metadata. If exact byte identity is not achieved, report a canonical content digest and disclose the limitation.

```bash
python -m synth.generate --seed 2026 --invoices 1200 --period annual --out data/
python -m synth.generate --seed 2026 --invoices 7000 --period annual --out data/    # full-scale
python -m synth.generate --seed 2026 --period half --out data/                      # period ends 30 Sep
python -m synth.load data/2026                                                      # load SoR into Postgres
```

---

## 4. Planted irregularity catalogue

Each class planted 3–5 times with variation (amount, customer, month, unit). Codes appear in `truth.csv`.

| Code | Class | How it's planted | Expected Pramaan signal |
| --- | --- | --- | --- |
| REG-PHANTOM | Register row with no SoR sale | extra row in exported register | T00 |
| REG-SUPPRESS | SoR sale missing from register | row dropped from export | T00 |
| REG-FIELD | Register field differs (amount/GSTIN/date/customer) | edit export only | T00 |
| RP-UNDISC | Undisclosed related party via shared bank account / DIN / phone | customer attr = director's relative's firm attr; omitted from RP list | T02 |
| RP-MIDPERIOD | Becomes related partway through the year | relationship `valid_from` mid-year | T01/T02 (dated) |
| RP-CYCLE | Circular flow A→B→C→A | goods/money edges forming a cycle | T02 cycles |
| CUT-DAP | Delivered after period end, booked before (DAP/DDP) | POD in April, posting in March | T03 |
| CUT-NOPOD | Year-end sale with no POD | POD removed | T03 GAP |
| NOMOVE | Turnover with no physical movement | invoice + journal, no dispatch/EWB/LR | T04 |
| NOMOVE-FAKEEWB | Invoice + EWB + LR present but the fixture contains contradictory movement evidence and no independent receipt | Plant a specific, reliable vehicle overlap or hard travel-time contradiction; make the source assumptions explicit | T11 if the physical contradiction is planted; T12 may yield INTERNAL_ONLY for occurrence. Do not infer “goods never moved” from absence of independent receipt alone |
| REV-NOSALE | Revenue entry not from a sale | manual journal Cr Sales | T05 |
| DOC-MISMATCH | Invoice vs EWB/dispatch value, qty, GSTIN, PIN differ | perturb one document | T06 |
| DOC-REUSED | Evidence belonging to another transaction | same POD/LR file linked to 2 sales | T07 |
| PE-SPIKE | Period-end concentration of sales and discounts | extra March sales + deep discounts | T08 → sampler |
| CN-POST | Full credit note after period end | CN in April reversing March invoice | T09 |
| SPLIT | Threshold splitting | 3 invoices same customer same day each just under threshold | T10 |
| PHYS-SPEED | Travel-time plausibility concern | POD time conflicts with route/time bounds under explicit distance and timestamp assumptions | T11 P1: INCONSISTENT/review by default; `IMPOSSIBLE` only if validated inputs prove a hard constraint violation |
| PHYS-OVERLAP | Strong vehicle-time conflict | Same reliably identified vehicle has incompatible, overlapping trips at separated origins, after accounting for multi-drop and timing tolerance | T11 P2; use `IMPOSSIBLE` only where identity, times and locations are reliable and the overlap cannot be reconciled |
| PHYS-LOAD | Estimated load exceeds capacity | Quantity × documented unit-weight estimate exceeds the recorded vehicle capacity, including unit and tolerance checks | T11 P3: INCONSISTENT/review unless both the load and capacity data are sufficiently reliable for a hard conclusion |
| WIT-WIRECARD | All available evidence is company-supplied, including an unverified “bank advice”; no independently verified receipt exists | Mark the acquisition channel as company upload; no physical contradiction is planted | T12: INTERNAL_ONLY for the relevant assertion; **T11 must not fire** unless a separate physical contradiction is planted |
| EINV-LATE-ACK | Invoice dated March, demo IRN acknowledgement in April | acknowledgement timestamp follows period end | T13: timing-risk finding requiring investigation; do not label backdating as established solely from this date |
| EINV-FORGED | QR signature invalid / fields ≠ books | sign with wrong key or edit payload | T13 |
| PRICE-OFFLIST | Price below list beyond allowed discount / scheme misuse | override price | T14 |
| GST-MISMATCH | Books differ from GSTR-1 or invoice tax fields | Change a synthetic GSTR-1 line or tax split | T15; evaluate applicable tax treatment and mark unresolved cases for review |
| INJECT | Prompt-injection text inside an invoice PDF | Include hidden/visible untrusted instructions in extracted document text | extraction/input-safety finding; no tool privilege change and no business/audit state change |

### Innocent traps (must NOT become exceptions)

| Code | Trap | Correct behaviour |
| --- | --- | --- |
| OK-TYPO | EWB invoice number has two digits transposed | Candidate mismatch may be raised, then resolved as DATA_ERROR only when the reviewer verifies the correction. It must not remain counted as a confirmed irregularity after resolution |
| OK-CASH | Small cash/walk-in sale, no external witness | INTERNAL_ONLY, not exception |
| OK-MULTIDROP | Same vehicle, multi-drop same origin | no P2 flag |
| OK-EXW | Year-end sale on EXW terms, dispatched 31 Mar | cut-off PASS |
| OK-ESTATE | Customers sharing an industrial-estate address only | Weak relationship lead only; don't classify the customers as related based on address alone. Reviewer may mark EXPLAINED with a reason |
| OK-REPEAT | Daily repeat orders from one customer | no SPLIT unless threshold pattern |
| OK-QUALITYCN | Small post-period quality credit note (<10%) with plausible supporting facts | Contextual review signal only; do not flag as an exception solely due to timing or percentage |

---

## 5. `truth.csv` format

```
case_id,code,class,object_type,object_ref,period_side,expected_tests,expected_state,notes
C001,CUT-DAP,cutoff,invoice,G/0981/26,pre,"T03",INCONSISTENT,"DAP; POD 2026-04-03"
C002,WIT-WIRECARD,witness,invoice,G/0412/26,pre,"T12",INTERNAL_ONLY,"bank advice uploaded by company; no physical conflict planted"
C014,OK-EXW,trap,invoice,M/0877/26,pre,"",PASS,"must not flag"
```

Pramaan **never** reads this file. Only the checker does.

---

## 6. Detection checker

```bash
python -m synth.check --truth data/2026/truth.csv --pramaan-export out/findings.json
python -m synth.check --truth data/2026/truth.csv --baseline        # naive "invoice ↔ order only" checker
```

### Outputs
- Per class: planted · detected · missed · precision · recall; state which generator seeds and ruleset versions were tested.
- False-positive rate on clean sales and on innocent traps; distinguish initial discrepancy candidates from human-resolved DATA_ERROR/EXPLAINED outcomes.
- Evidence-trace completeness (every cited evidence ID resolves to a stored content hash, source reference and link).
- Sampling reproducibility (same snapshot + persisted sampling seed + ruleset/sampler versions → identical sample IDs and reasons).
- Workpaper logical reproducibility. Claim byte-identical files only if XLSX/PDF metadata normalization is implemented and an automated test verifies it.
- **Pramaan vs baseline** side-by-side table, with baseline definition and identical test population — the comparison slide for judges.

### Matching rule
A planted case counts as detected if a finding references the expected `object_ref` or a documented linked lifecycle object **and** an expected test ID fired with the expected state/category. A candidate mismatch resolved as a verified data-entry error is not a confirmed fraud/irregularity detection. Extra unresolved findings on clean objects and on innocent traps count toward the stated false-positive metric. Evaluate matching logic without exposing `truth.csv` to the audit engine.

---

## 7. Test-only e-invoice signing (not production IRP verification)

- The generator creates a **test-only Demo IRP key pair** and signs a documented synthetic payload so valid/tampered signature tests can be exercised. The demo format is not claimed to duplicate the official NIC/IRP cryptographic format or protocol.
- The demo verifier uses only the Demo IRP public key, which is clearly labelled as test-only. The private demo key is used only by the generator and must never be loaded by Pramaan's audit service.
- Keep production verification behind a separate adapter and implement it only after confirming the current official NIC/IRP QR format, signature algorithm, trust/key distribution and verification requirements. Do not label a demo-key pass as “government verified”.
- If a genuine e-invoice is tested with the owner's permission, document the official source and validation procedure. Do not assume a public key or generic JWT procedure is sufficient without validating the current official process.
- **Disclose the demo-versus-production boundary to judges.** A valid registered invoice supports registration and signed payload fields, not proof of physical delivery or correct revenue recognition.

---

## 8. Hostile-judge practice mode

```bash
python -m synth.generate --seed $RANDOM --surprise --out data/
```
Plants a random subset of classes with randomized parameters and **does not print which** — a teammate runs the audit blind, then checks against `truth.csv`. This is the closest rehearsal to judges planting undisclosed irregularities through their own agent.

---

## 9. Rules for the team

- Never tune detection thresholds to one seed — tune on development seeds and evaluate on separate held-out seeds.
- Never load `truth.csv` or `keys/private.*` into Pramaan or expose them to the agent console.
- Report numbers only from an executed checker run, with dataset seed, generator version, ruleset version and command.
- Keep generation deterministic using a seeded RNG, fixed timestamps, sorted outputs and pinned dependencies; test output hashes rather than assuming determinism.
- Every physical “impossible” case must specify its trusted input fields, units, tolerances and why ordinary alternatives (multi-drop, time-zone error, stale data, wrong vehicle identity) are excluded.
- Generated GSTIN-like IDs, bank refs, people, addresses and vehicles are synthetic fixtures; never present them as real records or evidence of live registration.
