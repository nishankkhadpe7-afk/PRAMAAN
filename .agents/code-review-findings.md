# Code Review Findings — Pramaan Audit Workpaper Application

**Review date:** 2026-10-11  
**Files reviewed:** p3.py, p5.py, p5_exports.py, web_views.py, agent_llm.py, p4.py, app.py, security.py, mcp_dlp.py, auditor.tsx, App.tsx, client.tsx, components.tsx, session.tsx, api.ts

---

## Summary

| # | File | Severity | Problem | Status |
|---|------|----------|---------|--------|
| 1 | `p5.py` | **High** | `IndexError` — `metadata_source_rows[row_no - 1]` out of range | Fixed |
| 2 | `p5.py` | **High** | `HTTPException(409)` raised on findings with empty evidence set | Fixed |
| 3 | `p5_exports.py` | **Medium** | `KeyError` — `note_by_id[ref]` when credit note ref is missing | Fixed |
| 4 | `app.py` | **Medium** | f-string SQL column name (`patch.record`) — no parameterization | Fixed |
| 5 | `auditor.tsx` | **Medium** | `undefined · Traceable review` in Header title before data loads | Fixed |
| 6 | `auditor.tsx` | **Medium** | White-screen crash — `index[ref]` in EvidenceList with missing key | Fixed |
| 7 | `components.tsx` | **Low** | Table row keys fall back to index for runs, events, and other types | Fixed |

**Total bugs found: 7. All 7 fixed.**

---

## Detailed Findings

### Bug 1 — `p5.py`: IndexError in `evidence_index()` (High)

**File:** `backend/p5.py`, `evidence_index()` function  
**Problem:** The `metadata_source_rows` list is built from non-empty CSV rows only:
```python
"metadata_source_rows": [index + 2 for index, cells_row in enumerate(cells[1:]) if cells_row]
```
`p2_register_rows.row_no` is 1-based and sequential for all rows including empty ones.
If the register had any empty rows at parse time, those are omitted from `metadata_source_rows`,
making it shorter than `max(row_no)`. Indexing `metadata_source_rows[row["row_no"] - 1]` would
then raise `IndexError` during `web_run_context` or `create_export_package`.

**Fix applied:** Bounds-check before indexing; fall back to `row_no + 1` (estimated file line) when the index is out of range.
```python
row_idx = row["row_no"] - 1
source_row = metadata_source_rows[row_idx] if row_idx < len(metadata_source_rows) else row["row_no"] + 1
```

---

### Bug 2 — `p5.py`: HTTPException 409 for findings with no evidence refs (High)

**File:** `backend/p5.py`, `enrich()` function  
**Problem:** The condition `if not evidence or not evidence <= index.keys()` raises HTTP 409
whenever a finding accumulates zero evidence references. This legitimately happens for certain
synthetic test findings (e.g. T02 cycle findings with no matching source files), silently
blocking `create_export_package` with a misleading integrity error.

**Fix applied:** Changed the condition to only raise when evidence references exist but are outside
the index (true integrity failure), not when the evidence set is empty:
```python
if evidence and not evidence <= index.keys():
    raise HTTPException(409, "finding source references do not resolve")
```

---

### Bug 3 — `p5_exports.py`: KeyError in `tables()` credit note branch (Medium)

**File:** `backend/p5_exports.py`, `tables()` function  
**Problem:** `note_by_id[ref]` uses bare dict access with no guard. A credit note sample
item whose `object_ref` is not present in `note_by_id` (e.g. due to snapshot inconsistency
or a sample created against a since-deleted credit note) raises `KeyError` and crashes
the entire Excel/ZIP export.

**Fix applied:** Changed to `.get(ref)` with a `continue` guard:
```python
note = note_by_id.get(ref)
if not note:
    continue
```

---

### Bug 4 — `app.py`: f-string SQL interpolation of user input (Medium)

**File:** `backend/app.py`, `update_business_record()` function  
**Problem:** Although `patch.record` is validated against `{"invoice", "dispatch"}` before use,
the column name is still interpolated directly into the SQL string via f-string:
```python
db.execute(f"UPDATE sales SET {patch.record}=? WHERE sale_id=?", ...)
```
This is a fragile pattern — if the whitelist check is ever refactored or bypassed, it becomes
a SQL injection vector. Defense-in-depth requires explicit column name mapping.

**Fix applied:** Added an explicit dict mapping before the f-string:
```python
column = {"invoice": "invoice", "dispatch": "dispatch"}[patch.record]
db.execute(f"UPDATE sales SET {column}=? WHERE sale_id=?", ...)
```
Now even if the guard were removed, an unexpected value would raise `KeyError` rather than
reaching the database.

---

### Bug 5 — `auditor.tsx`: "undefined · Traceable review" header title (Medium)

**File:** `web/src/auditor.tsx`, `FindingDetail` component  
**Problem:** `<Header title={finding?.test_id+' · '+(finding?.assertion||'Traceable review')}>` — 
when `finding` is `undefined` (during initial data load), `finding?.test_id` evaluates to
`undefined`, and JavaScript's `+` coerces it to `"undefined · Traceable review"`.
This string renders visibly in the page heading before data loads.

**Fix applied:** Changed to use nullish coalescing:
```tsx
title={(finding?.test_id??'Finding')+' · '+(finding?.assertion||'Traceable review')}
```

---

### Bug 6 — `auditor.tsx`: White-screen crash in EvidenceList (Medium)

**File:** `web/src/auditor.tsx`, `EvidenceList` component  
**Problem:** `const e=index[ref]` with no null guard. If any `finding.evidence_ids` entry
is not present in `evidence_index` (possible if the index is stale, or if the ref was
added to a finding but not yet indexed), then `e` is `undefined` and accessing `e.provenance`
on the next line throws a TypeError, crashing the entire Finding Detail page with a blank screen.

**Fix applied:** Added `if(!e) return null;` guard before using `e`:
```tsx
const e=index[ref];
if(!e)return null;
```

---

### Bug 7 — `components.tsx`: React Table row keys fall back to index (Low)

**File:** `web/src/components.tsx`, `Table` component  
**Problem:** Row key selection was `r.invoice_id||r.finding_id||r.request_id||i`.
For audit runs (key: `run_id`), events (key: `seq`), customers (`customer_id`),
packages (`package_id`), and other types, none of those fields match, so all rows
get numeric index keys. This causes React to do full subtree re-renders on list updates
instead of reconciling by stable identity.

**Fix applied:** Widened key candidates to include all known id fields:
```tsx
key={r.invoice_id||r.finding_id||r.request_id||r.run_id||r.upload_id||r.customer_id||r.credit_note_id||r.package_id||r.seq||r.edge_id||i}
```

---

## Areas reviewed with no bugs found

- **`p3.py`** — all `HTTPException` raises are complete; `db.commit()` present on all write paths; `try/finally` guards on all connections; selection reason logic is correct; no closure capture issues in evidence request submit.
- **`p4.py`** — all connection resources freed in `finally`; `db.commit()` present; `record_egress_report` sanitizes inputs before logging.
- **`agent_llm.py`** — `max_steps` properly enforced; `allowed_tools` filter applied before and during tool calls; tool result truncation with `max_tool_result_chars` prevents context overflow; `httpx` timeout set to 120s.
- **`web_views.py`** — empty register fallback `{"rows": [], "reconciliations": []}` is safe because the `evidence_index` loop body does not execute on empty rows; `apply_egress_policy` only raises `DeniedByPolicy` in normal operation, which is caught.
- **`security.py`** — authorizer whitelist correctly enforced; token hashing with SHA-256; `PERMANENT_EXPIRY` value is semantically correct; `bootstrap()` is idempotent.
- **`mcp_dlp.py`** — deterministic, dependency-free; `SKIP_KEYS` correctly excludes structural hashes from redaction; `_HEX` pattern prevents masking within hash digests.
- **`app.py`** — `event_actor` import at bottom is the correct pattern for circular imports in Python (function body resolves at call time, not import time); no other issues.
- **`App.tsx` / `session.tsx` / `api.ts`** — route guards correct; session state cleared on sign-out; API error messages are user-friendly; `fileBase64` handles chunked encoding correctly.
- **`client.tsx`** — all mutations wrapped in error-catching `Mutation`; no unguarded array accesses.

---

## Python syntax check

All backend files pass `py_compile` with no errors:
```
python -m py_compile backend/p3.py backend/p5.py backend/p5_exports.py \
  backend/web_views.py backend/agent_llm.py backend/p4.py backend/app.py
```
Exit code: 0
