"""Measured evaluation of the investigation agent (AgentX F6).

Builds a fresh, self-contained synthetic instance through the real HTTP API (customers, 26 sale
lifecycles, a sales register with planted variances, an audit run, and a seeded bank statement),
then investigates every planted case and measures:

- traced to source: the report links at least one source record for each claim it makes
- invented amounts: amounts in the model's summary that no tool returned (target 0)
- correct outcome: explained / not explained / conflict, against the planted label
- conflicts escalated: every planted conflict stopped the run with status "conflict"
- median seconds and tool calls per exception

Only this module reads the planted labels. The agent and its tools never see them.

Run:
    python -m Pramaan.backend.evaluate_agent                 # deterministic baseline planner (offline)
    python -m Pramaan.backend.evaluate_agent --planner llm   # uses the configured LLM (.env)
    python -m Pramaan.backend.evaluate_agent --write-docs    # also writes docs/agent-eval.json + AGENT_EVAL.md
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import io
import json
import statistics
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from . import app as p1, fixtures_agent, p6_agent, security

CUSTOMERS = [("AGX-C1", "Sharma Traders (synthetic)"), ("AGX-C2", "Fictional Manufacturing Pvt Ltd (synthetic)"),
             ("AGX-C3", "Banyan Retail (synthetic)"), ("AGX-C4", "Aster Components (synthetic)")]
SALE_COUNT = 26
OUTCOME_CLASS = {"explained": "explained", "unexplained": "not_explained", "needs_confirmation": "not_explained",
                 "conflict": "conflict", "budget_exhausted": "budget_exhausted"}


def build_instance(request) -> dict:
    """Create the synthetic dataset with `request(method, path, role, json=...)` and return ids."""
    for customer_id, name in CUSTOMERS:
        assert request("POST", "/p2/customers", "client", json={"customer_id": customer_id, "name": name}).status_code == 200
    start = date(2025, 5, 2)
    invoices = []
    for n in range(1, SALE_COUNT + 1):
        when = (start + timedelta(days=11 * n)).isoformat()
        net = 12_000 + (n * 7_919) % 90_000          # deterministic spread of amounts, whole rupees
        customer_id, name = CUSTOMERS[n % len(CUSTOMERS)]
        sale = {"order_id": f"AGX-O{n:03}", "dispatch_id": f"AGX-D{n:03}", "invoice_id": f"AGX-I{n:03}", "journal_id": f"AGX-J{n:03}",
                "customer_id": customer_id, "order_date": when, "dispatch_date": when, "invoice_date": when,
                "bill_no": f"AGX/25-26/{n:03}", "net_amount": f"{net}.00"}
        response = request("POST", "/p2/sales", "client", json=sale)
        assert response.status_code == 200, response.text
        invoices.append({"invoice_id": sale["invoice_id"], "bill_no": sale["bill_no"], "invoice_date": when,
                         "gross_cents": net * 100, "customer_name": name})
    bank_csv, overrides, meta = fixtures_agent.build(invoices)
    cells = [["Bill No", "Date", "Customer", "Gross Amt"]] + [[i["bill_no"], i["invoice_date"], i["customer_name"], f"{i['gross_cents'] // 100}.00"] for i in invoices]
    register = fixtures_agent.register_with_overrides(cells, overrides)
    upload = request("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": base64.b64encode(register).decode()})
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["upload_id"]
    assert request("POST", f"/p2/registers/{upload_id}/reconcile", "auditor").status_code == 200
    run = request("POST", "/p3/audit-runs", "auditor", json={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "agentx-eval-seed-2026"})
    assert run.status_code == 200, run.text
    bank = request("POST", "/p6/bank-statements", "client", json={"period": "FY26", "source_base64": base64.b64encode(bank_csv).decode()})
    assert bank.status_code == 200, bank.text
    return {"run_id": run.json()["run_id"], "upload_id": upload_id, "statement_id": bank.json()["statement_id"],
            "invoices": invoices, "labels": meta["cases"], "fixture": {k: v for k, v in meta.items() if k != "cases"}}


def seed_instance(directory: Path) -> dict:
    """Build the evaluation dataset into a persistent demo folder for screenshots and the demo video."""
    from fastapi.testclient import TestClient
    directory = directory.resolve()
    if (directory / "p1.sqlite3").exists():
        raise SystemExit(f"{directory} already holds an instance; choose an empty folder (nothing was changed)")
    directory.mkdir(parents=True, exist_ok=True)
    patches = [patch.object(p1, "ROOT", directory), patch.object(p1, "DB_PATH", directory / "p1.sqlite3"), patch.object(p1, "VAULT", directory / "vault"),
               patch.dict("os.environ", {"PRAMAAN_DATA": str(directory)})]
    for item in patches:
        item.start()
    try:
        tokens = {"client": security.issue("demo-client", "client_employee", ttl=security.MAX_TTL),
                  "auditor": security.issue("demo-auditor", "auditor", ttl=security.MAX_TTL),
                  "human": security.issue("demo-human-reviewer", "auditor", ttl=security.HUMAN_MAX_TTL, human=True)}
        client = TestClient(p1.app)
        def request(method, path, role="auditor", **kwargs):
            return client.request(method, path, headers={"Authorization": "Bearer " + tokens[role]}, **kwargs)
        from . import p3
        p3.import_fixture_dataset()
        data = build_instance(request)
        client.close()
    finally:
        for item in reversed(patches):
            item.stop()
    (directory / "session-credentials.json").write_text(json.dumps(tokens, indent=2))
    (directory / "agent-demo-state.json").write_text(json.dumps({k: data[k] for k in ("run_id", "upload_id", "statement_id", "labels")}, indent=2))
    return data


def score_report(report: dict, label: dict) -> dict:
    claims = [s for s in report["steps"] if s["kind"] == "tool"]
    traced = bool(report["source_links"]) and all(s["source_refs"] or s["tool"] == "list_evidence_requests" for s in claims)
    outcome = OUTCOME_CLASS[report["status"]]
    return {"invoice_id": report["goal"]["invoice_id"], "kind": label["kind"], "expected": label["expected_outcome"], "got": outcome,
            "status": report["status"], "correct": outcome == label["expected_outcome"], "traced_to_source": traced,
            "invented_amounts": len(report["narrative_check"]["invented_amounts"]),
            "model_summary_rejected": report["narrative_check"]["model_summary_rejected"],
            "model_texts_withheld": report["narrative_check"].get("model_texts_withheld", 0),
            "conflict_expected": label["expected_outcome"] == "conflict", "escalated": report["status"] == "conflict",
            "tool_calls": report["tool_calls"], "seconds": report["elapsed_seconds"], "summary_source": report["summary_source"], "models": report["model"]}


def evaluate(planner: str = "baseline", poster=None, cfg=None, pace: float = 0.0, retries: int = 0, max_wait: float = 90.0) -> dict:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory(prefix="pramaan-agent-eval-") as tmp:
        root = Path(tmp)
        patches = [patch.object(p1, "ROOT", root), patch.object(p1, "DB_PATH", root / "p1.sqlite3"), patch.object(p1, "VAULT", root / "vault"),
                   patch.dict("os.environ", {"PRAMAAN_DATA": str(root)})]
        for item in patches:
            item.start()
        try:
            tokens = {"client": security.issue("eval-client", "client_employee"), "auditor": security.issue("eval-auditor", "auditor")}
            client = TestClient(p1.app)
            def request(method, path, role="auditor", **kwargs):
                return client.request(method, path, headers={"Authorization": "Bearer " + tokens[role]}, **kwargs)
            from . import p3
            p3.import_fixture_dataset()
            data = build_instance(request)
            rows = []
            for index, (invoice_id, label) in enumerate(sorted(data["labels"].items())):
                if planner == "llm" and index and pace:
                    time.sleep(pace)  # stay under free-tier per-minute quotas
                async def one():
                    from .security import identity
                    marker = identity.set({"subject": "eval-auditor", "role": "auditor", "human": False, "channel": "api"})
                    try:
                        return await p6_agent.run_investigation(data["run_id"], None, planner, poster=poster, cfg=cfg, invoice_id=invoice_id)
                    finally:
                        identity.reset(marker)
                for attempt in range(retries + 1):
                    try:
                        rows.append(score_report(asyncio.run(one()), label))
                        break
                    except HTTPException as exc:
                        if exc.status_code != 429 or attempt == retries:
                            raise
                        wait = min(max_wait, 5 + 15 * (attempt + 1))
                        print(f"[eval] rate-limited on {invoice_id}; waiting {wait}s (attempt {attempt + 1}/{retries})", flush=True)
                        time.sleep(wait)
                print(f"[eval] {len(rows)}/{len(data['labels'])} {invoice_id}: {rows[-1]['status']}", flush=True)
            client.close()
        finally:
            for item in reversed(patches):
                item.stop()
    n = len(rows)
    conflicts = [r for r in rows if r["conflict_expected"]]
    model = ", ".join(sorted({m for r in rows for m in (r.get("models") or "").split(", ") if m})) or None if planner == "llm" else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "planner": "llm" if planner == "llm" else "deterministic-baseline",
        "model": model, "prompt_version": p6_agent.PROMPT_VERSION, "fixture_seed": fixtures_agent.SEED,
        "dataset": {"sale_lifecycles": SALE_COUNT, "planted_cases": n, "classification": fixtures_agent.CLASSIFICATION,
                    "distribution": dict(fixtures_agent.DISTRIBUTION), "bank_statement_sha256": data["fixture"]["bank_statement_sha256"]},
        "metrics": {
            "traced_to_source": sum(r["traced_to_source"] for r in rows), "cases": n,
            "invented_amounts": sum(r["invented_amounts"] for r in rows),
            "correct_outcome": sum(r["correct"] for r in rows),
            "conflicts_escalated": sum(r["escalated"] for r in conflicts), "conflicts_planted": len(conflicts),
            "false_escalations": sum(r["escalated"] for r in rows if not r["conflict_expected"]),
            "median_seconds_per_exception": round(statistics.median(r["seconds"] for r in rows), 3),
            "median_tool_calls_per_exception": statistics.median(r["tool_calls"] for r in rows),
            "model_summaries_rejected": sum(r["model_summary_rejected"] for r in rows),
            "model_texts_withheld": sum(r["model_texts_withheld"] for r in rows),
        },
        "by_kind": {kind: {"cases": sum(r["kind"] == kind for r in rows), "correct": sum(r["correct"] for r in rows if r["kind"] == kind)}
                    for kind, _ in fixtures_agent.DISTRIBUTION},
        "cases": rows,
        "limitations": [
            "Synthetic data only; no real bank statements or client books were used.",
            "Seconds per exception measure the agent's machine time, not auditor time saved; no manual baseline was timed.",
            "The deterministic-baseline planner follows a fixed policy; LLM results depend on the model and provider and should be re-measured per model.",
            "The test data's bank narrations use abbreviations the party matcher already knows (Mfg, Trdrs, Retl...), so payer matching here is easier than on real statements. On unseen spellings the matcher mostly falls to 'possible match' (escalates), but can miss ('FICTIONAL MFRS') or over-match ('Astra' vs 'Aster Components').",
            "Planted 'possible party' payers swap the customer's first name (e.g. 'Sharma Traders' -> 'Verma Traders'). When the swap leaves little in common ('Banyan Retail' -> 'Verma Retail'), the matcher scores it as an unrelated payer, so the agent treats the invoice as unpaid and proposes an evidence request instead of escalating a conflict.",
        ],
    }


def markdown(result: dict) -> str:
    m = result["metrics"]
    lines = [
        "# Investigation agent — measured evaluation",
        "",
        f"Generated {result['generated_at']} by `python -m Pramaan.backend.evaluate_agent`.",
        f"Planner: **{result['planner']}**" + (f" (model `{result['model']}`)" if result["model"] else "") + f"; prompt `{result['prompt_version']}`; fixture seed `{result['fixture_seed']}`.",
        f"Dataset: {result['dataset']['sale_lifecycles']} synthetic sale lifecycles, {m['cases']} planted cases. {result['dataset']['classification']}.",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Traced to source | {m['traced_to_source']}/{m['cases']} |",
        f"| Invented amounts | {m['invented_amounts']} |",
        f"| Correct outcome (explained / not explained / conflict) | {m['correct_outcome']}/{m['cases']} |",
        f"| Planted conflicts escalated | {m['conflicts_escalated']}/{m['conflicts_planted']} |",
        f"| False escalations | {m['false_escalations']} |",
        f"| Median machine seconds per exception | {m['median_seconds_per_exception']} |",
        f"| Median tool calls per exception | {m['median_tool_calls_per_exception']} |",
        f"| Model summaries rejected by the amount check | {m['model_summaries_rejected']} |",
        f"| Other model texts withheld (plans, questions, next step) | {m['model_texts_withheld']} |",
        "",
        "## By planted case",
        "",
        "| Case | Correct |",
        "|---|---|",
    ] + [f"| {k} | {v['correct']}/{v['cases']} |" for k, v in result["by_kind"].items()] + [
        "",
        "## Misses",
        "",
    ] + ([f"- `{r['invoice_id']}` ({r['kind']}): expected {r['expected'].replace('_', ' ')}, got {r['got'].replace('_', ' ')} (status `{r['status']}`)." for r in result["cases"] if not r["correct"]] or ["- None."]) + [
        "",
        "## Limitations",
        "",
    ] + [f"- {item}" for item in result["limitations"]] + [""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure the PRAMAAN investigation agent on synthetic planted cases.")
    parser.add_argument("--planner", choices=["baseline", "llm"], default="baseline")
    parser.add_argument("--write-docs", action="store_true")
    parser.add_argument("--pace", type=float, default=6.0, help="seconds between LLM investigations (free-tier quotas)")
    parser.add_argument("--retries", type=int, default=4, help="retries per case when every model is rate-limited")
    parser.add_argument("--seed-instance", metavar="DIR", help="instead of evaluating, build the dataset into an empty folder for a demo")
    args = parser.parse_args()
    if args.seed_instance:
        data = seed_instance(Path(args.seed_instance))
        print(json.dumps({"instance": args.seed_instance, "run_id": data["run_id"], "cases": len(data["labels"])}, indent=2))
        return
    cfg = None
    if args.planner == "llm":
        from .agent_llm import config
        cfg = config()
        if not cfg["api_key"]:
            raise SystemExit("No LLM API key configured; run with --planner baseline or set a key in .env")
    result = evaluate(args.planner, cfg=cfg, pace=args.pace if args.planner == "llm" else 0.0, retries=args.retries if args.planner == "llm" else 0)
    print(markdown(result))
    if args.write_docs:
        docs = Path(__file__).resolve().parents[1] / "docs"
        suffix = "" if args.planner == "baseline" else "-llm"
        (docs / f"agent-eval{suffix}.json").write_text(json.dumps(result, indent=2) + "\n")
        (docs / f"AGENT_EVAL{suffix.upper()}.md").write_text(markdown(result))


if __name__ == "__main__":
    main()
