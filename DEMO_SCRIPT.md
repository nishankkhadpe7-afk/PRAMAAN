# Pramaan — Demo Script

## Opening

> “An invoice can show that a sale was recorded. It does not by itself prove that the sale happened. Pramaan gives an auditor a traceable path from the company register to the source records, audit tests, evidence gaps, and a human conclusion.”

## What Pramaan does

> “The client preserves original sales-register files, records business transactions, and responds to evidence requests. The auditor reconciles the register with the recorded books, runs a reproducible audit snapshot, and investigates deterministic findings. A human reviewer—not the system or AI—records the final outcome.”

## Demo flow

1. **Sign in as the client.**

   > “The client workspace is the system-of-record side: customers, sales lifecycles, original registers, and evidence submissions.”

   Show **Business records** and **Registers & disclosures**.

   > “A register upload preserves its original bytes and SHA-256 identity. A later correction is a new preserved source; it does not overwrite the original.”

2. **Sign in as the auditor and open an audit engagement.**

   > “This audit run is an immutable snapshot. It stores the period, rule version, sampling seed, source state, and snapshot hash. Rerunning creates a new version rather than changing history.”

   Show the summary metrics and the **Audit activity** chart.

   > “The chart shows automated observations and selected workpaper items. These are review signals, not confirmed exceptions or fraud conclusions.”

3. **Open the Findings tab.**

   > “Every row answers a specific audit question and gives a plain-language reason for review.”

   Explain the categories shown in the current synthetic demo:

   - **T00 — Register reconciliation:** a register row has no matching system invoice, or comparison data is missing or invalid.
   - **T01/T02 — Related-party leads:** a disclosed relationship or a candidate circular pattern needs human corroboration.
   - **T03/T04 — Evidence gaps:** control-date information or expected movement documents are unavailable; a gap is not proof that a sale is false.
   - **T05/T06 — Book-record inconsistencies:** a revenue journal lacks an invoice reference, or invoice and dispatch data differ.
   - **T09/T10/T11 — Review patterns:** late credit notes, threshold patterns, and movement inconsistencies such as overlapping vehicle use or impossible event order.
   - **T13/T15 — Demo verification and return comparison:** signature checks use a labelled demo key only; supplied synthetic return rows can differ from books but do not prove filing or tax error.

4. **Open one finding.**

   > “This page separates the automated observation from the human conclusion. It shows the reason, known facts, unresolved questions, rules, samples, and linked evidence.”

   Show **Evidence & provenance**.

   > “Hashes establish content identity. They do not prove authenticity. Company-supplied documents stay marked as unverified.”

5. **Show the authorization boundary.**

   Go to **Integrity** and use **Attempt forbidden auditor write**.

   > “An auditor can investigate but cannot edit business records. The API returns 403 and logs the denied action in the append-only local audit log.”

6. **Show human review and export.**

   > “An ordinary auditor can store a review proposal. A separately provisioned human-review identity can append a final decision with a reason and, where applicable, supported impact evidence.”

   Show **Workpapers**.

   > “A frozen package binds the snapshot, selected register, review revisions, and exported Excel, PDF, and ZIP artifacts. Later changes require a new package.”

7. **Show the Audit assistant.**

   > “The assistant uses the current auditor identity and a read-only MCP findings tool. It can summarize an audit run, but cannot create records, rerun an audit, change a finding, export a package, or record a conclusion.”

   > “Its availability depends on the configured LLM provider. The audit engine and the authorization rules remain deterministic and server-side.”

## Close

> “Pramaan does not label a transaction fraudulent. It preserves what the company supplied, makes missing evidence and inconsistencies visible, records how each sample was chosen, and gives a human reviewer a defensible path from source to conclusion.”

## Current scope and limits

- Local, single-company SQLite prototype using synthetic demonstration data.
- Official GST/IRP verification, external log anchoring, tenant isolation, production deployment, and general lifecycle editing are not implemented.
- T13 uses a demo signature path, not an official government key or registration check.
- AI provides read-only guidance only; it does not make audit conclusions.
