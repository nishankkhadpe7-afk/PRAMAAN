# P1 Verification Report

**Date:** 2026-10-10  
**Verdict: PASS — PHASES.md P1 acceptance gate only.** The one-sale slice preserves its source, produces evidence-linked findings, detects a post-snapshot change, and reproduces findings using the run's stored ruleset. This is not a claim that the broader Pramaan requirements or later phase gates are complete.

## Verification performed

- Existing and new suite: `py -m unittest discover -s Pramaan/backend/tests -v` — **7 passed**. Python compilation also passed.
- Shipped `ruleset.yaml` loaded as version `p1-2026-02` — **PASS**.
- Original register — **PASS**: regression test compares the exact uploaded CRLF bytes in the vault and independently checks their SHA-256.
- T06 — **PASS for this P1 invoice/dispatch slice**: the inclusive value tolerance is `1.00`; differences `0.99` and `1.00` do not fire, `1.01` fires T06 and makes accuracy `INCONSISTENT`. Configured GSTIN/PIN/vehicle fields compare exactly after case/space normalization; a GSTIN mismatch test fires. Quantity tolerance is configured as zero.
- T12 provenance — **PASS**: an import request claiming `independently_verified: true` is stored and returned as unverified; linked occurrence/accuracy evidence is `INTERNAL_ONLY`, unsupported cutoff/classification are `GAP`.
- T12 coverage — **PASS**: with no evidence and no conflicting facts, all four required assertions return `GAP`. Accuracy becomes `INCONSISTENT` when T06 finds a beyond-tolerance conflict.
- Evidence references — **PASS**: tests verify each finding evidence ID resolves to the imported evidence and its content-addressed vault file.
- Post-snapshot change and replay — **PASS**: dispatch mutation is detected and mapped to the sale, run, and findings. Replay remains identical after the on-disk ruleset is changed because the run stores the configuration snapshot, version, and hash.
- Integrity and outputs — **PASS**: intact chain verifies; a deliberately altered predecessor link is detected after bypassing the SQLite update trigger. JSON findings are returned, and XLSX ZIP/XML checks confirm one `P1 Findings` sheet with finding and evidence references.

## Remaining gaps and limits

- P1 has no independent-source verification adapter. Uploaded evidence can no longer self-certify, but this slice cannot establish independent verification; imported items therefore remain `INTERNAL_ONLY` (or `GAP` when absent).
- T06 compares the P1 invoice and dispatch objects for configured value, quantity, GSTIN, PIN, and vehicle fields when present in both. Order/e-way-bill joins and broader reconciliation coverage are not demonstrated here.
- Runs created before ruleset snapshots were added cannot be safely reproduced and now return `409`; new runs persist the full configuration.
- The local demo still lacks authentication, tenant isolation, constrained database roles, and external log anchoring. Authorization and DB-boundary work is specified for P4.
- XLSX was checked as ZIP/XML, not opened in a spreadsheet application. Byte-identical XLSX output is not claimed.
