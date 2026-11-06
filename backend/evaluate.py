"""Synthetic-dataset evaluation harness.

Runs a full audit over the checked-in synthetic dataset, compares the findings
against a labelled ground-truth file, and reports measured detection numbers plus
a document-matching baseline. This is the evidence behind the pitch's claims.

Honesty / separation: this evaluator is the ONLY module that reads the ground
truth (evaluation_truth.json). The audit engine (p3.py et al.) never imports it,
so detection is by general rules, not by knowledge of which rows are planted.

Run:  python -m Pramaan.backend.evaluate            # prints a Markdown report
      python -m Pramaan.backend.evaluate --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from . import app as p1, p3, p3_dataset

HARD_STATES = {"INCONSISTENT", "IMPOSSIBLE"}            # a hard conflict the engine asserts
FLAG_STATES = HARD_STATES | {"REVIEW", "DISCLOSED_RELATED_PARTY", "GOVERNMENT_REGISTERED_DEMO", "GAP"}
TRUTH_PATH = Path(__file__).with_name("evaluation_truth.json")


def _matches(finding: dict, entity: str) -> bool:
    ref = finding.get("object_ref", "")
    if ref == entity or entity in ref.split(":"):
        return True
    if entity in (finding.get("invoice_ids") or []):
        return True
    if entity == "CYCLE" and finding.get("test_id") == "T02" and ref.startswith("CYCLE:"):
        return True
    return False


def _timing_flag(finding: dict) -> bool:
    # A valid DEMO registration only counts as a signal when it carries timing risk.
    if finding.get("test_id") == "T13" and finding.get("state") == "GOVERNMENT_REGISTERED_DEMO":
        return bool(finding.get("registration_timing_risk"))
    return finding.get("state") in FLAG_STATES


def run_evaluation(period_start: str = "2025-04-01", period_end: str = "2025-06-30",
                   seed: str = "pramaan-eval-seed-2026-0001") -> dict:
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    root = Path(tempfile.mkdtemp(prefix="pramaan-eval-"))
    with patch.object(p1, "ROOT", root), patch.object(p1, "DB_PATH", root / "p1.sqlite3"), patch.object(p1, "VAULT", root / "vault"):
        db = p3.db_open()
        p3_dataset.import_dataset(p3_dataset.DATA_DIR, db, p1.VAULT)
        db.commit()
        db.close()
        ruleset = p3.load_ruleset()
        db = p3.db_open()
        result, _, _ = p3.calculate(p3.build_snapshot(db), period_start, period_end, seed, ruleset, "EVAL")
        db.close()
    findings = result["findings"]

    per_class, pramaan_caught, baseline_caught = [], 0, 0
    for item in truth["planted"]:
        entity, expected = item["entity"], set(item["expected_tests"])
        hits = [f for f in findings if _matches(f, entity) and f["test_id"] in expected and _timing_flag(f)]
        caught = bool(hits)
        baseline = item["document_matchable"] and any(f["test_id"] == "T06" and _matches(f, entity) for f in findings)
        pramaan_caught += caught
        baseline_caught += baseline
        per_class.append({"entity": entity, "class": item["class"], "caught": caught,
                          "by_tests": sorted({f["test_id"] for f in hits}),
                          "baseline_caught": bool(baseline)})

    innocent = truth["innocent"]
    innocent_hard = sorted({e for e in innocent for f in findings if _matches(f, e) and f.get("state") in HARD_STATES})
    innocent_reviews = sorted({e for e in innocent for f in findings if _matches(f, e) and f.get("state") == "REVIEW"})

    x = len(truth["planted"])
    report = {
        "dataset_version": truth["dataset_version"], "seed": seed, "period": [period_start, period_end],
        "planted_total_X": x,
        "pramaan_caught_A": pramaan_caught,
        "baseline_doc_match_caught_B": baseline_caught,
        "false_alarms_on_innocent_C": len(innocent_hard),
        "innocent_hard_conflict_entities": innocent_hard,
        "innocent_review_only_entities": innocent_reviews,
        "pramaan_recall": round(pramaan_caught / x, 3) if x else None,
        "baseline_recall": round(baseline_caught / x, 3) if x else None,
        "per_class": per_class,
        "total_findings": len(findings),
    }
    return report


def to_markdown(r: dict) -> str:
    lines = [
        "# Pramaan — synthetic evaluation", "",
        f"- Dataset version: {r['dataset_version']}  ·  seed: `{r['seed']}`  ·  period: {r['period'][0]} to {r['period'][1]}",
        f"- Planted irregularities (X): **{r['planted_total_X']}**",
        f"- Caught by Pramaan (A): **{r['pramaan_caught_A']}**  (recall {r['pramaan_recall']})",
        f"- Caught by document-matching baseline (B): **{r['baseline_doc_match_caught_B']}**  (recall {r['baseline_recall']})",
        f"- Hard-conflict false alarms on innocent cases (C): **{r['false_alarms_on_innocent_C']}**",
        f"- Review-only flags on innocent cases: {r['innocent_review_only_entities'] or 'none'}",
        "", "| Planted entity | Class | Caught | By tests | Baseline catches? |",
        "|---|---|---|---|---|",
    ]
    for c in r["per_class"]:
        lines.append(f"| {c['entity']} | {c['class']} | {'yes' if c['caught'] else 'NO'} | {', '.join(c['by_tests']) or '-'} | {'yes' if c['baseline_caught'] else 'no'} |")
    lines += ["", "Document-matching (invoice vs order/dispatch) misses every irregularity whose documents agree "
              "but whose physics, provenance, registration timing, or counterparty graph is wrong - exactly the gap Pramaan closes.",
              "All numbers are on a synthetic dataset; detectors use general rules, not planted-row IDs."]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_evaluation()
    print(json.dumps(report, indent=2) if args.json else to_markdown(report))
