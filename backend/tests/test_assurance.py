"""Statistical assurance: monetary-unit sampling (Stringer bound) and the conformal anomaly screen."""
import random
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, assurance as a, p3, security


class MusMathTests(unittest.TestCase):
    def test_poisson_factors_match_published_tables(self):
        # AICPA / standard MUS tables: 95% -> 3.00, 4.75, 6.30; 90% -> 2.31, 3.89; 99% -> 4.61
        for errors, confidence, expected in ((0, .95, 3.00), (1, .95, 4.75), (2, .95, 6.30), (0, .90, 2.31), (1, .90, 3.89), (0, .99, 4.61)):
            self.assertAlmostEqual(a.poisson_upper(errors, confidence), expected, delta=0.01)

    def test_plan_is_reproducible_pps_and_takes_every_large_item(self):
        rng = random.Random(7)
        items = [(f"I{n:04}", rng.randint(1_000_00, 90_000_00)) for n in range(400)] + [("BIG1", 9_000_000_00), ("BIG2", 4_000_000_00), ("ZERO", 0)]
        plan = a.mus_plan(items, "seed-1", 95, 3_000_000_00)
        self.assertEqual(plan, a.mus_plan(list(reversed(items)), "seed-1", 95, 3_000_000_00))
        self.assertNotEqual(plan["selected"], a.mus_plan(items, "seed-2", 95, 3_000_000_00)["selected"])
        book = sum(c for _, c in items)
        self.assertEqual(plan["population_book_cents"], book)
        self.assertEqual(plan["planned_sample_size"], -(-book * a.poisson_upper(0, .95) // 3_000_000_00))
        chosen = {s["invoice_id"]: s for s in plan["selected"]}
        self.assertEqual(chosen["BIG1"]["stratum"], "individually_significant")
        self.assertEqual(chosen["BIG2"]["stratum"], "individually_significant")
        self.assertNotIn("ZERO", chosen)
        self.assertLessEqual(len(chosen), plan["planned_sample_size"] + 2)
        # Bigger invoices are picked more often: selection rate rises with size.
        small = [r for r, c in items if 0 < c < 30_000_00]; large = [r for r, c in items if 60_000_00 <= c < 100_000_00]
        self.assertLess(sum(r in chosen for r in small) / len(small), sum(r in chosen for r in large) / len(large))
        with self.assertRaises(ValueError):
            a.mus_plan(items, "s", 95, 1_000_00, expected_cents=1_000_00)

    def test_stringer_bound_worked_example(self):
        # Interval Rs 10,000; one sampled item overstated by 40%, one by 10%; one top-stratum item overstated by Rs 500.
        plan = {"confidence": 95, "sampling_interval_cents": 10_000_00, "tolerable_cents": 60_000_00, "selected": [
            {"invoice_id": "A", "book_cents": 5_000_00, "stratum": "sampled"}, {"invoice_id": "B", "book_cents": 2_000_00, "stratum": "sampled"},
            {"invoice_id": "C", "book_cents": 8_000_00, "stratum": "sampled"}, {"invoice_id": "TOP", "book_cents": 25_000_00, "stratum": "individually_significant"}]}
        partial = a.mus_evaluate(plan, {"A": 3_000_00})
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["untested_invoice_ids"], ["B", "C", "TOP"])
        self.assertTrue(partial["result"].startswith("incomplete"))
        done = a.mus_evaluate(plan, {"A": 3_000_00, "B": 1_800_00, "C": 8_000_00, "TOP": 24_500_00})
        self.assertEqual(done["taintings"], [0.4, 0.1])
        self.assertEqual(done["known_misstatement_cents"], 500_00)
        self.assertEqual(done["projected_misstatement_cents"], 500_00 + 5_000_00)          # 0.5 x interval + known
        self.assertAlmostEqual(done["basic_precision_cents"], 29_957_00, delta=100)        # 2.9957 x interval
        # allowance = (4.7439-2.9957-1) x 0.4 x 10,000 + (6.2958-4.7439-1) x 0.1 x 10,000
        self.assertAlmostEqual(done["incremental_allowance_cents"], 2_993_00 + 552_00, delta=300)
        self.assertAlmostEqual(done["upper_misstatement_limit_cents"], 500_00 + 5_000_00 + 29_957_00 + 3_545_00, delta=400)
        self.assertEqual(done["result"], "upper limit is within tolerable misstatement")
        clean = a.mus_evaluate(plan, {"A": 5_000_00, "B": 2_000_00, "C": 8_000_00, "TOP": 25_000_00})
        self.assertEqual((clean["projected_misstatement_cents"], clean["upper_misstatement_limit_cents"]), (0, clean["basic_precision_cents"]))
        under = a.mus_evaluate(plan, {"A": 6_000_00, "B": 2_000_00, "C": 8_000_00, "TOP": 25_000_00})
        self.assertEqual(under["understated_invoice_ids"], ["A"])


def invoices(prefix, n, rng, customers=12, outliers=0):
    out = []
    for k in range(n):
        customer = f"{prefix}-C{k % customers}"
        amount = int(rng.lognormvariate(11 + (k % customers) * 0.15, 0.35) * 100)
        out.append({"invoice_id": f"{prefix}-{k:05}", "bill_no": f"{prefix}/{k}", "customer_id": customer, "invoice_date": f"2025-{1 + k * 12 // n:02}-{1 + k % 28:02}", "gross_cents": amount, "net_cents": amount})
    for k in rng.sample(range(n // 2, n), outliers):
        out[k]["gross_cents"] *= 60
        out[k]["planted"] = True
    return out


class ConformalScreenTests(unittest.TestCase):
    def test_false_alarm_share_is_controlled_and_planted_outliers_are_found(self):
        alpha, false_shares, found, clean_flags = 0.1, [], 0, 0
        for trial in range(30):
            rng = random.Random(trial)
            reference, audited = invoices("R", 900, rng), invoices("T", 600, rng, outliers=20)
            result = a.conformal_screen(reference, audited, alpha)
            planted = {i["invoice_id"] for i in audited if i.get("planted")}
            flagged = {f["invoice_id"] for f in result["flagged"]}
            false_shares.append(len(flagged - planted) / max(1, len(flagged)))
            found += len(flagged & planted)
            clean_flags += a.conformal_screen(reference, invoices("T", 600, rng), alpha)["flagged_count"]
        self.assertLessEqual(sum(false_shares) / len(false_shares), alpha)          # FDR control (average false-alarm share)
        self.assertGreaterEqual(found / (30 * 20), 0.8)                              # power on clear outliers
        self.assertLessEqual(clean_flags, 30)                                        # nothing much flagged when nothing is planted

    def test_result_explains_itself_and_small_reference_cannot_flag(self):
        rng = random.Random(1)
        result = a.conformal_screen(invoices("R", 900, rng), invoices("T", 300, rng, outliers=12), 0.1)
        self.assertTrue(all(f["why"].startswith("unusual ") and 0 < f["p_value"] <= 0.1 for f in result["flagged"]))
        self.assertEqual(result["expected_false_alarms_at_most"], round(0.1 * result["flagged_count"], 2))
        tiny = a.conformal_screen(invoices("R", 60, rng), invoices("T", 600, rng, outliers=3), 0.1)
        self.assertEqual(tiny["flagged_count"], 0)
        self.assertGreater(tiny["minimum_flags_for_any_detection"], 3)


class AssuranceApiTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("assure-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("agent-auditor", "auditor"), "human": security.issue("human-reviewer", "auditor", human=True)}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        run = self.request("POST", "/p3/audit-runs", json={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "assurance-seed-2026"})
        self.assertEqual(run.status_code, 200, run.text)
        self.run_id = run.json()["run_id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, role="auditor", **kwargs):
        return self.client.request(method, path, headers={"Authorization": "Bearer " + self.tokens[role], **kwargs.pop("headers", {})}, **kwargs)

    def test_mus_plan_results_and_evaluation_workflow(self):
        path = f"/assurance/runs/{self.run_id}/mus-plans"
        self.assertEqual(self.request("POST", path, "client", json={"tolerable_misstatement": "1000"}).status_code, 403)
        self.assertEqual(self.request("POST", path, json={"tolerable_misstatement": "-5"}).status_code, 422)
        self.assertEqual(self.request("POST", "/assurance/runs/NOPE/mus-plans", json={"tolerable_misstatement": "1000"}).status_code, 404)
        created = self.request("POST", path, json={"confidence": 95, "tolerable_misstatement": "50000.00"})
        self.assertEqual(created.status_code, 200, created.text)
        plan = created.json()
        self.assertEqual(self.request("POST", path, json={"confidence": 95, "tolerable_misstatement": "50000.00"}).json()["plan_id"], plan["plan_id"])  # idempotent
        self.assertTrue(plan["selected"])
        self.assertFalse(plan["evaluation"]["complete"])
        results = f"/assurance/mus-plans/{plan['plan_id']}/results"
        body = {"items": [{"invoice_id": s["invoice_id"], "audited_amount": s["book_inr"]} for s in plan["selected"]], "note": "Agreed to invoice, dispatch and receipt."}
        self.assertEqual(self.request("POST", results, json=body).status_code, 403)                                         # not a human reviewer
        self.assertEqual(self.request("POST", results, "human", json=body, headers={"X-Pramaan-Channel": "mcp"}).status_code, 403)
        self.assertEqual(self.request("POST", results, "human", json={**body, "items": [{"invoice_id": "NOT-SAMPLED", "audited_amount": "1"}]}).status_code, 422)
        done = self.request("POST", results, "human", json=body)
        self.assertEqual(done.status_code, 200, done.text)
        evaluation = done.json()["evaluation"]
        self.assertTrue(evaluation["complete"])
        self.assertEqual(evaluation["projected_misstatement_inr"], "0.00")
        self.assertEqual(evaluation["upper_misstatement_limit_inr"], evaluation["basic_precision_inr"])
        # A corrected amount supersedes; the earlier entry stays in the history.
        first = plan["selected"][0]
        lower = format(float(first["book_inr"]) / 2, ".2f")
        revised = self.request("POST", results, "human", json={"items": [{"invoice_id": first["invoice_id"], "audited_amount": lower}], "note": "Half the amount was not supported."}).json()
        self.assertEqual(revised["evaluation"]["overstatements_found"], 1)
        self.assertGreater(float(revised["evaluation"]["upper_misstatement_limit_inr"]), float(evaluation["upper_misstatement_limit_inr"]))
        listed = self.request("GET", path).json()["plans"]
        self.assertEqual(listed[0]["selected"][0]["audited_inr"], lower)

    def test_anomaly_screen_needs_a_separate_reference(self):
        screen = f"/assurance/runs/{self.run_id}/anomaly-screen"
        self.assertEqual(self.request("GET", screen + f"?reference_run_id={self.run_id}").status_code, 422)   # a run cannot be its own reference
        self.assertEqual(self.request("GET", screen + "?reference_run_id=NOPE").status_code, 404)
        self.assertEqual(self.request("GET", screen + f"?reference_run_id={self.run_id}&alpha=0.9").status_code, 422)
        self.assertEqual(self.request("GET", screen + f"?reference_run_id={self.run_id}", "client").status_code, 403)


if __name__ == "__main__":
    unittest.main()
