# Pramaan local demonstration

Use [README.md](README.md) to reset/start backend, frontend and MCP. The dataset is fictional; none of its GST/IRP fields is official verification. Freeze code before rehearsing. Keep private credentials out of screenshots, source control and agent environments.

## Complete live walkthrough

1. Provision a **client** credential and sign in at `/login`. The overview shows actual P2 records; imported P3 fixtures are separately identified audit inputs.
2. Open **Business records**. Inspect a sale's order/dispatch/invoice, journals, receipts, credits and supporting references. Optionally add a customer and sale; backend creates a balanced journal. Posted entries have no ordinary edit/delete control.
3. Open **Registers & disclosures**. Upload `.demo/runtime/sales_register.csv`, or a prepared UTF-8 CSV with Bill No/Date/Customer/Gross Amt/GST No. Upload related-party JSON only with actual supported fields: `customer_id`, `related_party`, optional `valid_from`, `valid_to`, `relationship_type`. Source files/hashes are preserved separately from parsed metadata.
4. Sign out. Provision an **auditor** credential, sign in, and click **Reconcile** for the chosen register. Create a **New audit run**, using period `2025-04-01` to `2026-03-31` and an explicit seed of at least 16 characters. Reconciliation precedes snapshot creation.
5. Inspect **Samples**: Sales TOD, Cut-off TOD and Credit Note TOD, strata, reasons, probabilities and coverage/exclusions. Counts are workpaper items; overlaps are disclosed. No population projection is claimed.
6. Inspect **Findings** and **Related parties**. Open a finding to see its test, rule/hash, assertion, facts versus inference, source references and review state. Expand evidence chips for source rows, hashes, controller/acquisition metadata where supplied. Download an original uploaded document where available; its content is untrusted data.
7. Open **Requests**. The sampler has already created requests in the client's inbox. Ad-hoc requests, due-date scheduling and external messaging are unavailable; do not simulate them.
8. Sign in as the client and open **Evidence inbox**. Choose a request/document type and submit a synthetic file. Check company-supplied/unverified status and SHA256. Sign in as the auditor, reopen the run and **Rerun with new snapshot**. The new run captures the submission; the old snapshot stays intact.
9. An ordinary auditor may **Store review proposal**. Then sign out and separately provision/sign in with a **human** credential. Open the finding and **Record human decision**, with an actual reason. Quantified impact needs resolving basis IDs and an adjustment group; repeated references to one adjustment must use one group. Do not invent supported amounts or post proposed entries.
10. In **Workpapers**, create a frozen export package using a register present in that snapshot. Download Excel workpapers, PDF memo and ZIP. Receipt, source hashes, sample seed, versions and human revisions are persisted. Future reviews require another package.
11. Client: upload a **revised register as a new preserved source** after testing. Do not overwrite originals. Auditor: open the old run's **Integrity** view. Confirm changed source fields and conservative impact mapping to affected samples. Download the old package again; it still reflects its saved snapshot. General P2 field edits are not implemented.
12. In auditor **Integrity**, click **Attempt forbidden auditor write**. The actual API request must return 403; inspect a `security_denied` event and unchanged client records. The API/SQLite boundary enforces this independently of navigation visibility.

An optional P1-only demonstration uses `/auditor/sales/DEMO-SALE-001`: snapshot/run checks, client versioned invoice/dispatch change, and P1 post-test comparison. P1 findings belong to that sale's audit; do not present their impact as P3 sampling results.

## Two automated clean-reset rehearsals

```powershell
$env:PYTHONPATH = (Split-Path -Parent $PWD.Path)
.\.venv-p4\Scripts\python.exe -m Pramaan.backend.demo rehearse --name rehearsal
```

No code edits between rounds. Each round launches real loopback HTTP, picks a randomized held-out bill and amount, confirms a resolving T00 observation, processes a sample evidence submission, creates a new run, checks ordinary reviewer denials, records a human-capability decision, downloads all artifacts, detects a subsequent source revision, and verifies write denial/logging, reproducibility and unchanged export bytes. Metrics and artifacts are saved under `.demo/rehearsal-1` and `-2`. Local IDs/log events can differ across resets because provisioning and imports append actual records; source bytes, fixed dataset manifest, seed and rule/sampler versions remain reproducible.

## Independent-person blind rehearsal — completion reported, evidence pending

The user reports this exercise completed. Its participant/scenario record and supporting artifacts have not yet been supplied or located; see the evidence review in `backend/P6_VERIFICATION_REPORT.md`. The checklist below describes the required exercise, not proof it occurred. Automated random cases do not demonstrate it.

- Stop/reset the dedicated demo, restart it, and freeze the code. A teammate privately copies the register, changes a supported comparison field on a randomly chosen valid bill, and retains a private expected-case note outside the web/MCP flow. Do not edit checked-in fixtures or the original preserved source.
- The auditor operator receives the source file without the chosen bill/field/expected outcome, reconciles it, runs the audit and identifies the discrepancy by test/source references. The teammate then reveals the expected case.
- Complete evidence/review/export/change/denial steps and record observed finding IDs, seed/versions, source hash, affected samples, denied event sequence and downloaded artifact hashes. Report missed/false observations honestly.
- Record the independent person's role, date, outcome and evidence in `backend/P6_VERIFICATION_REPORT.md`. Only then reassess overall P6 completion. Do not call this performed merely because instructions exist.

## Backup and offline narrative

A real Chrome walkthrough recording was captured at `.demo/backup/demo.webm`, with login/workpaper screenshots alongside it. It includes synthetic data and masked credential fields; HTTP tracing is disabled. Play the video locally if live services are unavailable. Recreate it with the browser regression command in README if generated files are unavailable. Preserve the backup before rerunning tests, which replace `web/test-results`.

Offline narrative: “This sale is represented by original source bytes, a snapshot, a sample reason and a deterministic observation. These hashes establish content identity, not authenticity. Missing documents and unavailable checks remain gaps. An agent may propose an explanation; a separately authorized human decides. A frozen package binds the sources and review revisions. A later source revision produces a change alert without rewriting earlier workpapers. An auditor business write is denied and recorded.”

No official GST/IRP verification, independent delivery assurance, external anchor, tenant isolation, statistical projection or production certification is demonstrated. The MCP console is the tested fallback; hosted judging clients remain unverified.
