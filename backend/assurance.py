"""Statistical assurance: monetary-unit sampling with a projected upper limit, and an anomaly screen
whose false-alarm rate is controlled.

Both are additions beside the deterministic rule engine. Neither changes a frozen run, its samples
or its findings, and neither states a conclusion: a person records the audited amounts and decides.

Monetary-unit sampling (MUS)
    Every rupee of recorded sales is a sampling unit, so large invoices are more likely to be picked
    and any invoice at least as large as the sampling interval is always picked. After the auditor
    records the audited amount of each selected invoice, the Stringer bound gives "with C% confidence
    the overstatement in the population is at most Rs X". Understatement is not measured by MUS.

Conformal anomaly screen
    Each invoice gets a score for how unusual it is. Scores are compared with a reference set the
    auditor accepts as ordinary (for example last year's audited sales). That turns each score into
    a p-value that is valid without assuming any distribution, and the Benjamini-Hochberg step then
    keeps the expected share of false alarms among the flagged invoices at or below alpha
    (Bates, Candes, Lei, Romano, Sesia 2023, doi:10.1214/22-AOS2244). The guarantee holds when
    ordinary invoices in the audited period behave like the reference set; it says nothing about
    problems that do not show in the scored features.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import app as p1, p3

router = APIRouter(prefix="/assurance", tags=["Statistical assurance"])

# ---------------------------------------------------------------- monetary-unit sampling (pure)

EXPANSION = {90: 1.5, 95: 1.6, 99: 1.9}  # AICPA audit sampling guide, expected-misstatement expansion factors


def poisson_upper(errors: int, confidence: float) -> float:
    """Upper confidence limit for a Poisson mean after observing `errors` events (3.00 for 0 at 95%)."""
    target = 1 - confidence

    def cdf(lam: float) -> float:
        term = total = math.exp(-lam)
        for k in range(1, errors + 1):
            term *= lam / k
            total += term
        return total
    low, high = 0.0, 10.0 + 4 * errors
    while cdf(high) > target:
        high *= 2
    for _ in range(80):
        mid = (low + high) / 2
        low, high = (mid, high) if cdf(mid) > target else (low, mid)
    return (low + high) / 2


def mus_plan(items: list[tuple[str, int]], seed: str, confidence: int, tolerable_cents: int, expected_cents: int = 0) -> dict[str, Any]:
    """Systematic probability-proportional-to-size selection, reproducible from the seed."""
    population = sorted((ref, cents) for ref, cents in items if cents > 0)
    book = sum(cents for _, cents in population)
    net = tolerable_cents - expected_cents * EXPANSION[confidence]
    if book <= 0 or net <= 0:
        raise ValueError("tolerable misstatement must exceed expected misstatement x expansion factor, and the population must have value")
    factor = poisson_upper(0, confidence / 100)
    size = max(1, math.ceil(book * factor / net))
    interval = max(1, book // size)
    start = int(hashlib.sha256(f"mus|{seed}|{book}|{interval}".encode()).hexdigest(), 16) % interval
    selected, cumulative, next_hit = [], 0, start
    for ref, cents in population:
        lower, cumulative = cumulative, cumulative + cents
        hits = 0
        while next_hit < cumulative:
            hits += 1
            next_hit += interval
        if hits or cents >= interval:
            selected.append({"invoice_id": ref, "book_cents": cents, "stratum": "individually_significant" if cents >= interval else "sampled",
                             "first_selected_rupee": None if not hits else (next_hit - hits * interval - lower) // 100 + 1})
    return {"method": "monetary-unit sampling, systematic selection", "confidence": confidence, "confidence_factor": round(factor, 4),
            "expansion_factor": EXPANSION[confidence], "tolerable_cents": tolerable_cents, "expected_cents": expected_cents,
            "population_items": len(population), "population_book_cents": book, "planned_sample_size": size,
            "sampling_interval_cents": interval, "random_start_cents": start, "selected": selected}


def mus_evaluate(plan: dict[str, Any], audited: dict[str, int]) -> dict[str, Any]:
    """Stringer bound on overstatement. `audited` maps invoice_id to the audited amount in cents."""
    confidence, interval = plan["confidence"] / 100, plan["sampling_interval_cents"]
    tested = [s for s in plan["selected"] if s["invoice_id"] in audited]
    untested = [s["invoice_id"] for s in plan["selected"] if s["invoice_id"] not in audited]
    known_top, taints, understated = 0, [], []
    for item in tested:
        over = item["book_cents"] - audited[item["invoice_id"]]
        if over < 0:
            understated.append(item["invoice_id"])
            continue
        if item["stratum"] == "individually_significant":
            known_top += over  # examined in full: the actual difference, nothing to project
        elif over:
            taints.append(min(1.0, over / item["book_cents"]))
    taints.sort(reverse=True)
    basic = poisson_upper(0, confidence) * interval
    projected = sum(taints) * interval
    allowance = sum((poisson_upper(i + 1, confidence) - poisson_upper(i, confidence) - 1) * t * interval for i, t in enumerate(taints))
    upper = known_top + projected + basic + allowance
    complete = not untested
    return {"complete": complete, "items_selected": len(plan["selected"]), "items_tested": len(tested), "untested_invoice_ids": untested,
            "overstatements_found": len(taints) + (1 if known_top else 0), "taintings": [round(t, 6) for t in taints],
            "known_misstatement_cents": known_top, "projected_misstatement_cents": round(known_top + projected),
            "basic_precision_cents": round(basic), "incremental_allowance_cents": round(allowance),
            "upper_misstatement_limit_cents": round(upper), "tolerable_cents": plan["tolerable_cents"],
            "understated_invoice_ids": understated,
            "result": ("incomplete: record the audited amount of every selected invoice" if not complete else
                       "upper limit is within tolerable misstatement" if upper <= plan["tolerable_cents"] else "upper limit exceeds tolerable misstatement"),
            "limits": "Stringer bound on overstatement only; understatements are listed, not projected. A statistical result supports, and does not replace, the auditor's conclusion."}


# ---------------------------------------------------------------- conformal anomaly screen (pure)

FEATURES = {"customer_amount": "amount compared with this customer's other invoices", "amount": "invoice amount", "unit_price": "price per unit for this HSN code", "quantity": "quantity", "dispatch_lag": "days between dispatch and invoice"}


# Scored by default. Unit price and quantity by HSN code were tried and left out: an HSN code covers
# products with very different prices, so those scores were noise that hid the real outliers.
SCORED = ("customer_amount", "amount")


def _days(a: Any, b: Any) -> int | None:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except (TypeError, ValueError):
        return None


def invoice_features(inv: dict[str, Any]) -> dict[str, Any]:
    gross, net = int(inv.get("gross_cents") or 0), int(inv.get("net_cents") or 0)
    try:
        qty = float(inv.get("quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    out: dict[str, Any] = {"hsn": str(inv.get("hsn_code") or ""), "customer": str(inv.get("customer_id") or ""),
                           "date": str(inv.get("invoice_date") or ""), "id": str(inv.get("invoice_id") or "")}
    if gross > 0:
        out["amount"] = math.log(gross)
    if qty > 0:
        out["quantity"] = math.log(qty)
        if net > 0:
            out["unit_price"] = math.log(net / qty)
    lag = _days(inv.get("invoice_date"), inv.get("dispatch_date")) if inv.get("dispatch_date") else None
    if lag is not None:
        out["dispatch_lag"] = float(lag)
    return out


def add_customer_baseline(rows: list[dict[str, Any]], minimum: int = 4) -> None:
    """How far each invoice is from the same customer's earlier invoices in the same set (median of
    log amount of the invoices dated before it). Fewer than `minimum` earlier invoices: no baseline."""
    history: dict[str, list[float]] = {}
    for r in sorted((r for r in rows if r["customer"] and "amount" in r), key=lambda r: (r["date"], r["id"])):
        earlier = history.setdefault(r["customer"], [])
        if len(earlier) >= minimum:
            r["customer_amount"] = r["amount"] - median(earlier)
        earlier.append(r["amount"])


def _center_scale(values: list[float]) -> tuple[float, float]:
    mid = median(values)
    mad = median(abs(v - mid) for v in values) * 1.4826
    spread = (max(values) - min(values)) / 20 if len(values) > 1 else 0.0
    return mid, max(mad, spread, 1e-9)


def fit_scorer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Robust centre and spread of each feature over the pooled invoices (reference + audited period).
    Pooling treats every invoice alike, which is what keeps the p-values valid."""
    model: dict[str, Any] = {"global": {}, "unit_price_by_hsn": {}}
    for name in SCORED:
        values = [r[name] for r in rows if name in r]
        # A feature that is the same for almost every invoice (zero spread) cannot rank anything.
        if len(values) >= 5 and median(abs(v - median(values)) for v in values) > 0:
            model["global"][name] = _center_scale(values)
    by_hsn: dict[str, list[float]] = {}
    for r in rows:
        if "unit_price" in r and r["hsn"]:
            by_hsn.setdefault(r["hsn"], []).append(r["unit_price"])
    model["unit_price_by_hsn"] = {hsn: _center_scale(v) for hsn, v in by_hsn.items() if len(v) >= 8}
    return model


def score(row: dict[str, Any], model: dict[str, Any]) -> tuple[float, str | None]:
    best, driver = 0.0, None
    for name, (mid, spread) in model["global"].items():
        if name not in row:
            continue
        if name == "unit_price" and row["hsn"] in model["unit_price_by_hsn"]:
            mid, spread = model["unit_price_by_hsn"][row["hsn"]]
        z = abs(row[name] - mid) / spread
        if z > best:
            best, driver = z, name
    return best, driver


def conformal_screen(reference: list[dict[str, Any]], audited: list[dict[str, Any]], alpha: float = 0.1) -> dict[str, Any]:
    """reference / audited: invoice dicts with invoice_id. Returns the invoices flagged at FDR alpha."""
    ref_rows = [invoice_features(i) for i in reference]
    test_rows = [invoice_features(i) for i in audited]
    add_customer_baseline(ref_rows)
    add_customer_baseline(test_rows)
    model = fit_scorer(ref_rows + test_rows)
    calibration = sorted(score(r, model)[0] for r in ref_rows)
    n, m = len(calibration), len(test_rows)
    scored = []
    for inv, row in zip(audited, test_rows):
        s, driver = score(row, model)
        # number of reference scores >= s, by binary search
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            lo, hi = (mid + 1, hi) if calibration[mid] < s else (lo, mid)
        scored.append({"invoice_id": inv["invoice_id"], "bill_no": inv.get("bill_no"), "score": round(s, 3), "driver": driver,
                       "p_value": (1 + n - lo) / (n + 1)})
    scored.sort(key=lambda r: (r["p_value"], -r["score"], r["invoice_id"]))
    cutoff = 0
    for k, r in enumerate(scored, 1):
        if r["p_value"] <= k * alpha / m:
            cutoff = k
    flagged = [{**r, "p_value": round(r["p_value"], 6), "why": f"unusual {FEATURES.get(r['driver'], 'pattern')}"} for r in scored[:cutoff]]
    smallest = 1 / (n + 1)
    return {"alpha": alpha, "reference_invoices": n, "audited_invoices": m, "flagged": flagged, "flagged_count": cutoff,
            "expected_false_alarms_at_most": round(alpha * cutoff, 2),
            "minimum_flags_for_any_detection": max(1, math.ceil(smallest * m / alpha)) if m else 0,
            "features": sorted(model["global"]),
            "guarantee": f"If ordinary invoices in this period behave like the reference set, at most {round(alpha * 100)}% of the flagged invoices are expected to be false alarms.",
            "limits": "Screens only the listed features. An unflagged invoice is not cleared. A small reference set cannot flag a small number of anomalies (see minimum_flags_for_any_detection)."}


# ---------------------------------------------------------------- storage and API

def init_assurance(db) -> None:
    db.executescript("""
      CREATE TABLE IF NOT EXISTS assurance_mus_plans(plan_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES p3_audit_runs(run_id), plan_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS assurance_mus_results(plan_id TEXT NOT NULL REFERENCES assurance_mus_plans(plan_id), invoice_id TEXT NOT NULL, revision INTEGER NOT NULL, audited_cents INTEGER NOT NULL, note TEXT NOT NULL, recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY(plan_id, invoice_id, revision));
      CREATE TRIGGER IF NOT EXISTS assurance_mus_plans_no_update BEFORE UPDATE ON assurance_mus_plans BEGIN SELECT RAISE(ABORT,'sampling plans are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS assurance_mus_plans_no_delete BEFORE DELETE ON assurance_mus_plans BEGIN SELECT RAISE(ABORT,'sampling plans are immutable'); END;
      CREATE TRIGGER IF NOT EXISTS assurance_mus_results_no_update BEFORE UPDATE ON assurance_mus_results BEGIN SELECT RAISE(ABORT,'audited amounts are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS assurance_mus_results_no_delete BEFORE DELETE ON assurance_mus_results BEGIN SELECT RAISE(ABORT,'audited amounts are append-only'); END;
    """)


def _caller() -> dict[str, Any]:
    from .security import identity
    return identity.get() or {"subject": "offline-admin", "role": "auditor", "human": False}


def _cents(value: str, label: str) -> int:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
        if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f"{label} must be a non-negative amount in rupees with at most two decimals")
    return int(amount * 100)


def _rupees(cents: int) -> str:
    return format(Decimal(cents) / 100, ".2f")


def _run(db, run_id: str):
    run = db.execute("SELECT run_id, snapshot_json, result_json, sampling_seed, period_start, period_end FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "audit run not found")
    return run


def _period_invoices(run) -> list[dict[str, Any]]:
    return [i for i in json.loads(run["snapshot_json"]).get("invoices", [])
            if p3.readable_date(i.get("invoice_date")) and run["period_start"] <= str(i["invoice_date"])[:10] <= run["period_end"]]


def _plan_view(db, row) -> dict[str, Any]:
    plan = json.loads(row["plan_json"])
    latest: dict[str, Any] = {}
    for r in db.execute("SELECT * FROM assurance_mus_results WHERE plan_id=? ORDER BY revision", (row["plan_id"],)):
        latest[r["invoice_id"]] = r
    evaluation = mus_evaluate(plan, {k: v["audited_cents"] for k, v in latest.items()})
    money = ("tolerable_cents", "expected_cents", "population_book_cents", "sampling_interval_cents")
    return {"plan_id": row["plan_id"], "run_id": row["run_id"], "created_by": row["created_by"], "created_at": row["created_at"],
            **{k: v for k, v in plan.items() if k not in money + ("selected", "random_start_cents")},
            **{k.replace("_cents", "_inr"): _rupees(plan[k]) for k in money},
            "selected": [{"invoice_id": s["invoice_id"], "book_inr": _rupees(s["book_cents"]), "stratum": s["stratum"],
                          "audited_inr": _rupees(latest[s["invoice_id"]]["audited_cents"]) if s["invoice_id"] in latest else None,
                          "note": latest[s["invoice_id"]]["note"] if s["invoice_id"] in latest else None,
                          "recorded_by": latest[s["invoice_id"]]["recorded_by"] if s["invoice_id"] in latest else None} for s in plan["selected"]],
            "evaluation": {**{k: v for k, v in evaluation.items() if not k.endswith("_cents")},
                           **{k.replace("_cents", "_inr"): _rupees(v) for k, v in evaluation.items() if k.endswith("_cents")}}}


class MusPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confidence: Literal[90, 95, 99] = 95
    tolerable_misstatement: str = Field(min_length=1, max_length=24)
    expected_misstatement: str = Field(default="0", max_length=24)


@router.post("/runs/{run_id}/mus-plans")
def create_mus_plan(run_id: str, payload: MusPlanIn) -> dict[str, Any]:
    """Draw a monetary-unit sample from the run's frozen invoices. The same inputs always give the same sample."""
    tolerable, expected = _cents(payload.tolerable_misstatement, "tolerable_misstatement"), _cents(payload.expected_misstatement, "expected_misstatement")
    db = p3.db_open()
    try:
        run = _run(db, run_id)
        try:
            plan = mus_plan([(i["invoice_id"], int(i.get("gross_cents") or 0)) for i in _period_invoices(run)], run["sampling_seed"], payload.confidence, tolerable, expected)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        plan_json = p1.canonical(plan).decode()
        plan_id = "MUS-" + p1.digest(p1.canonical([run_id, plan_json]))[:16]
        if db.execute("INSERT OR IGNORE INTO assurance_mus_plans VALUES(?,?,?,?,?)", (plan_id, run_id, plan_json, _caller()["subject"], datetime.now(timezone.utc).isoformat())).rowcount:
            p1.log_event(db, _caller()["subject"], "mus_plan_created", plan_id, {"run_id": run_id, "plan_sha256": p1.digest(plan_json.encode()), "confidence": payload.confidence, "selected": len(plan["selected"])})
        db.commit()
        return _plan_view(db, db.execute("SELECT * FROM assurance_mus_plans WHERE plan_id=?", (plan_id,)).fetchone())
    finally:
        db.close()


@router.get("/runs/{run_id}/mus-plans")
def list_mus_plans(run_id: str) -> dict[str, Any]:
    db = p3.db_open()
    try:
        _run(db, run_id)
        return {"run_id": run_id, "plans": [_plan_view(db, r) for r in db.execute("SELECT * FROM assurance_mus_plans WHERE run_id=? ORDER BY created_at, plan_id", (run_id,))]}
    finally:
        db.close()


class MusResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: str = Field(min_length=1, max_length=120)
    audited_amount: str = Field(min_length=1, max_length=24)


class MusResultsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[MusResultItem] = Field(min_length=1, max_length=1000)
    note: str = Field(min_length=3, max_length=1000)


@router.post("/mus-plans/{plan_id}/results")
def record_mus_results(plan_id: str, payload: MusResultsIn) -> dict[str, Any]:
    """A human reviewer records the audited amount of selected invoices. A later entry supersedes; history is kept."""
    caller = _caller()
    if caller.get("role") != "auditor" or not caller.get("human") or caller.get("channel") == "mcp":
        raise HTTPException(403, "human review capability required")
    db = p3.db_open()
    try:
        row = db.execute("SELECT * FROM assurance_mus_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            raise HTTPException(404, "sampling plan not found")
        selected = {s["invoice_id"] for s in json.loads(row["plan_json"])["selected"]}
        ids = [i.invoice_id for i in payload.items]
        outside = [i for i in ids if i not in selected]
        if outside or len(set(ids)) != len(ids):
            raise HTTPException(422, "every invoice must be in this sample and listed once" + (": " + ", ".join(outside[:5]) if outside else ""))
        amounts = {i.invoice_id: _cents(i.audited_amount, "audited_amount") for i in payload.items}
        now = datetime.now(timezone.utc).isoformat()
        db.execute("BEGIN IMMEDIATE")
        for invoice_id, cents in amounts.items():
            revision = db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM assurance_mus_results WHERE plan_id=? AND invoice_id=?", (plan_id, invoice_id)).fetchone()[0]
            db.execute("INSERT INTO assurance_mus_results VALUES(?,?,?,?,?,?,?)", (plan_id, invoice_id, revision, cents, payload.note.strip(), caller["subject"], now))
        p1.log_event(db, caller["subject"], "mus_results_recorded", plan_id, {"invoices": sorted(amounts), "audited_cents": amounts, "note": payload.note.strip()})
        db.commit()
        return _plan_view(db, row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/runs/{run_id}/anomaly-screen")
def anomaly_screen(run_id: str, reference_run_id: str, alpha: float = 0.1) -> dict[str, Any]:
    """Experimental. Flags invoices that are unusual compared with a reference run the auditor accepts
    as ordinary, with the expected share of false alarms held at or below alpha."""
    if not 0.01 <= alpha <= 0.5:
        raise HTTPException(422, "alpha must be between 0.01 and 0.5")
    db = p3.db_open()
    try:
        run, reference = _run(db, run_id), _run(db, reference_run_id)
        latest: dict[str, str] = {}
        for r in db.execute("SELECT finding_id, decision_json FROM p5_reviews WHERE run_id=? ORDER BY revision", (reference_run_id,)):
            latest[r["finding_id"]] = json.loads(r["decision_json"]).get("outcome")
        confirmed = {k for k, outcome in latest.items() if outcome == "EXCEPTION_CONFIRMED"}
        excluded = set()
        for finding in json.loads(reference["result_json"]).get("findings", []):
            if finding.get("finding_id") in confirmed:
                excluded |= {finding.get("object_ref"), finding.get("invoice_id"), *(finding.get("invoice_ids") or [])}
        audited_ids = {i["invoice_id"] for i in _period_invoices(run)}
        # The reference must not contain the invoices being screened, or anything a person confirmed as an exception.
        ref_invoices = [i for i in _period_invoices(reference) if i["invoice_id"] not in audited_ids and i["invoice_id"] not in excluded and i.get("bill_no") not in excluded]
        if len(ref_invoices) < 50:
            raise HTTPException(422, "the reference run needs at least 50 invoices that are not in the audited period")
        return {"run_id": run_id, "reference_run_id": reference_run_id, "status": "experimental", **conformal_screen(ref_invoices, _period_invoices(run), alpha)}
    finally:
        db.close()
