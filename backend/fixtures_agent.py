"""Seeded synthetic fixtures for the investigation agent (AgentX F5/F6).

Everything here is synthetic and labelled as such. The planted-case labels are written to a
separate file that only the evaluator reads; the agent and its tools never import this module's
labels (same separation as backend/evaluation_truth.json).

Usage (for a local demo instance, after `demo reset`):
    python -m Pramaan.backend.fixtures_agent --data .demo/runtime --out .demo/runtime/agent_fixtures
Then upload bank_statement.csv as the client (Registers & disclosures -> Bank statement),
optionally upload register_with_variance.csv, rerun the audit, and investigate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date, timedelta
from pathlib import Path

SEED = "pramaan-agentx-fixture-2026"
CLASSIFICATION = "synthetic - generated for agent evaluation; not real bank data"

# Planted case kinds and the outcome class a correct investigation should reach.
EXPECTED = {
    "exact": "explained",
    "near_date": "explained",
    "split": "explained",
    "partial": "not_explained",
    "missing": "not_explained",
    "duplicate": "conflict",
    "possible_party": "conflict",
    "register_variance": "not_explained",
}
DISTRIBUTION = [("exact", 4), ("near_date", 3), ("split", 3), ("partial", 3), ("missing", 4),
                ("duplicate", 3), ("possible_party", 3), ("register_variance", 3)]


def _rank(invoice_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{invoice_id}".encode()).hexdigest()


def plan_cases(invoice_ids: list[str]) -> dict[str, str]:
    """Deterministically assign planted kinds to invoices (seeded hash order)."""
    ordered = sorted(invoice_ids, key=_rank)
    kinds = [kind for kind, count in DISTRIBUTION for _ in range(count)]
    return {invoice_id: kinds[i] for i, invoice_id in enumerate(ordered[:len(kinds)])}


def _abbreviate(name: str) -> str:
    """A realistic bank-narration spelling of the same party (e.g. 'M/s Fictional Mfg')."""
    swaps = {"manufacturing": "Mfg", "traders": "Trdrs", "private": "Pvt", "limited": "Ltd", "retail": "Retl", "enterprises": "Ent"}
    words = [swaps.get(w.lower(), w) for w in name.replace("(synthetic)", "").split()]
    return "M/s " + " ".join(words).upper()


def _lookalike(name: str) -> str:
    """A different party with a similar name: another family name, same trade words (e.g. Verma Traders)."""
    words = name.replace("(synthetic)", "").split()
    others = ["Verma", "Mehta", "Kapoor", "Rao"]
    replacement = next(o for o in others if o.lower() != (words[0].lower() if words else ""))
    return " ".join([replacement] + words[1:])


def _rupees(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def build(invoices: list[dict]) -> tuple[bytes, dict[str, int], dict]:
    """Return (bank CSV bytes, register overrides {bill_no: register_cents}, labels)."""
    plan = plan_cases([inv["invoice_id"] for inv in invoices])
    by_id = {inv["invoice_id"]: inv for inv in invoices}
    rows, overrides, labels = [], {}, {}
    for invoice_id, kind in sorted(plan.items()):
        inv = by_id[invoice_id]
        gross, bill, name = int(inv["gross_cents"]), inv["bill_no"], inv.get("customer_name") or "Synthetic Customer"
        when = date.fromisoformat(inv["invoice_date"])
        ref = "NEFT/" + bill
        if kind in {"exact", "register_variance"}:
            rows.append((when + timedelta(days=5), gross, "NEFT credit " + bill, ref, _abbreviate(name)))
        elif kind == "near_date":
            rows.append((when + timedelta(days=21), gross, "IMPS credit", "IMPS/" + _rank(invoice_id)[:10].upper(), _abbreviate(name)))
        elif kind == "split":
            first = (gross * 2 // 5) // 100 * 100
            rows.append((when + timedelta(days=3), first, "NEFT part payment " + bill, ref + "/1", _abbreviate(name)))
            rows.append((when + timedelta(days=12), gross - first, "NEFT balance " + bill, ref + "/2", _abbreviate(name)))
        elif kind == "partial":
            part = (gross * 3 // 5) // 100 * 100
            rows.append((when + timedelta(days=7), part, "NEFT credit " + bill, ref, _abbreviate(name)))
        elif kind == "duplicate":
            rows.append((when + timedelta(days=4), gross, "NEFT credit " + bill, ref, _abbreviate(name)))
            rows.append((when + timedelta(days=4), gross, "NEFT credit " + bill, ref, _abbreviate(name)))
        elif kind == "possible_party":
            rows.append((when + timedelta(days=6), gross, "RTGS credit", "RTGS/" + _rank(invoice_id)[:10].upper(), _lookalike(name)))
        if kind == "register_variance":
            overrides[bill] = gross + max(100, (gross * 3 // 4) // 100 * 100)
        labels[invoice_id] = {"bill_no": bill, "kind": kind, "expected_outcome": EXPECTED[kind]}
    rows.sort(key=lambda r: (r[0], r[3]))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["date", "amount", "direction", "narration", "reference", "counterparty", "balance"])
    balance = 50_000_000
    for when, cents, narration, reference, counterparty in rows:
        balance += cents
        writer.writerow([when.isoformat(), _rupees(cents), "credit", narration, reference, counterparty, _rupees(balance)])
    source = stream.getvalue().encode()
    meta = {"classification": CLASSIFICATION, "seed": SEED, "bank_statement_sha256": hashlib.sha256(source).hexdigest(),
            "cases": labels, "register_overrides": {b: _rupees(c) for b, c in overrides.items()}}
    return source, overrides, meta


def register_with_overrides(cells: list[list[str]], overrides: dict[str, int]) -> bytes:
    """Copy a register (header + rows) and change only the gross amount of the overridden bills."""
    header = [h.strip().lower() for h in cells[0]]
    bill_i = next(i for i, h in enumerate(header) if h in {"bill no", "bill_no", "invoice no"})
    amt_i = next(i for i, h in enumerate(header) if h in {"gross amt", "gross amount", "gross_amount", "amount"})
    out = [cells[0]]
    for row in cells[1:]:
        row = list(row)
        if row and len(row) > max(bill_i, amt_i) and row[bill_i].strip() in overrides:
            row[amt_i] = _rupees(overrides[row[bill_i].strip()])
        out.append(row)
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(out)
    return stream.getvalue().encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True, help="PRAMAAN data directory of a demo instance (contains p1.sqlite3)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import sqlite3
    db = sqlite3.connect(Path(args.data) / "p1.sqlite3")
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT snapshot_json FROM p3_audit_runs ORDER BY rowid DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("no audit run found; create one first")
    snapshot = json.loads(row["snapshot_json"])
    source, overrides, meta = build(snapshot["invoices"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bank_statement.csv").write_bytes(source)
    if snapshot.get("register_uploads"):
        (out / "register_with_variance.csv").write_bytes(register_with_overrides(snapshot["register_uploads"][-1]["cells"], overrides))
    (out / "fixture_labels.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({"out": str(out), "bank_rows": source.count(b"\n") - 1, "cases": len(meta["cases"]), "sha256": meta["bank_statement_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
