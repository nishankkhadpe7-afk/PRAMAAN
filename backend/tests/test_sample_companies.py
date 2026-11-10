"""The two sample companies (docs/sample-companies): rebuilt files match the committed ones, the honest
company comes out clean, and every problem planted in the hiding company is found by its check.
SYNTHETIC data only."""
import filecmp
import json
import shutil
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from Pramaan.backend import app as p1, demo, proof, sample_companies

PACKS = sample_companies.OUT


def _load(slug: str):
    name = f"test-sample-{slug}"
    saved = (p1.ROOT, p1.DB_PATH, p1.VAULT)
    try:
        state = demo.company(slug, name)
        root = demo.data_path(name)
        db = sqlite3.connect(root / "p1.sqlite3")
        result = json.loads(db.execute("SELECT result_json FROM p3_audit_runs WHERE run_id=?", (state["run_id"],)).fetchone()[0])
        proofs = {f["finding_id"]: proof.proof(db, state["run_id"], f["finding_id"]) for f in result["findings"]
                  if f["test_id"] in ("T08", "T09", "T10", "T11", "T13", "T14", "T15", "T05") and f["state"] != "GOVERNMENT_REGISTERED_DEMO"}
        result["_proofs"] = proofs
        sample_ok = next((f for f in result["findings"] if f["test_id"] == "T13" and f["state"] == "GOVERNMENT_REGISTERED_DEMO"), None)
        result["_clean_chain"] = proof.proof(db, state["run_id"], sample_ok["finding_id"]) if sample_ok else None
        registers = {}
        for upload_id, period in db.execute("SELECT upload_id, period FROM p2_register_uploads"):
            findings = json.loads(db.execute("SELECT findings_json FROM p2_reconciliations WHERE upload_id=?", (upload_id,)).fetchone()[0])
            registers[period] = findings
        bills = dict(db.execute("SELECT invoice_id, bill_no FROM p2_invoices"))
        names = dict(db.execute("SELECT customer_id, name FROM p2_customers"))
        db.close()
        return result, registers, bills, names
    finally:
        p1.ROOT, p1.DB_PATH, p1.VAULT = saved
        shutil.rmtree(demo.data_path(name), ignore_errors=True)


class SampleCompanyFilesTests(unittest.TestCase):
    def test_rebuild_matches_committed_files(self):
        out = Path(tempfile.mkdtemp(prefix="pramaan-samples-"))
        try:
            sample_companies.build(out)
            for slug in ("honest", "hiding"):
                cmp = filecmp.dircmp(out / slug, PACKS / slug)
                stack, diffs = [cmp], []
                while stack:
                    c = stack.pop()
                    diffs += [f"{c.left}/{f}" for f in c.diff_files + c.left_only + c.right_only]
                    stack += c.subdirs.values()
                self.assertEqual(diffs, [], f"{slug}: regenerate with python -m Pramaan.backend.sample_companies")
        finally:
            shutil.rmtree(out, ignore_errors=True)


class SampleCompanyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.honest = _load("honest")
        cls.hiding = _load("hiding")

    def test_honest_company_records_agree(self):
        result, registers, _, names = self.honest
        self.assertEqual(len(registers), 4)  # register + three monthly GSTR-1 returns
        self.assertEqual({period: f for period, f in registers.items() if f}, {})
        serious = Counter((f["test_id"], f["state"]) for f in result["findings"] if f["state"] in ("REVIEW", "INCONSISTENT", "IMPOSSIBLE"))
        # One genuine review signal from the source trading pattern: a customer's busy last week of March.
        self.assertEqual(serious, Counter({("T08", "REVIEW"): 1}))
        self.assertEqual([names[f["object_ref"]] for f in result["findings"] if f["test_id"] == "T08"], ["Kesari Collections"])

    def test_every_planted_problem_is_found(self):
        result, registers, bills, names = self.hiding
        planted = {p["what"]: p for p in json.loads((PACKS / "hiding" / "planted.json").read_text())}
        by_test = {}
        for f in result["findings"]:
            by_test.setdefault(f["test_id"], []).append(f)

        def refs(test, state=None):
            out = set()
            for f in by_test.get(test, []):
                if state and f["state"] != state:
                    continue
                out.add(bills.get(f["object_ref"], f["object_ref"]))
                out.update(bills.get(i, i) for i in f.get("invoice_ids", []))
            return out

        shell = planted["Year-end sales to a related shell customer"]["refs"]
        self.assertEqual([names[f["object_ref"]] for f in by_test["T08"]], ["Vardhan Distributors"])
        self.assertEqual(refs("T06", "GAP"), set(shell))  # no transport documents for the shell sales
        self.assertEqual(refs("T09"), set(planted["Year-end sales reversed after the year closed"]["refs"]))
        self.assertTrue(set(planted["One order split into two bills under the approval limit"]["refs"]) <= refs("T10"))
        self.assertEqual(refs("T05"), {"NLP-JV-ADJ-01"})
        self.assertEqual(refs("T15"), set(planted["Sales under-reported in GSTR-1"]["refs"]))
        self.assertEqual(refs("T14"), set(planted["Contract customer billed below the agreed price"]["refs"]))
        transport = planted["Transport records that cannot be true"]["refs"]
        t11 = {f.get("subcheck") for f in by_test["T11"]}
        self.assertEqual(t11, {"P1_route_time", "P2_vehicle_overlap", "P3_load_estimate", "P5_pin_consignee"})
        self.assertTrue({transport[0], transport[2], transport[3]} <= refs("T11"))
        einv = planted["E-invoice problems"]["refs"]
        self.assertEqual(refs("T13", "INCONSISTENT"), {einv[0]})
        self.assertEqual(refs("T13", "UNAVAILABLE"), set(einv[2:]))
        self.assertEqual([bills[f["object_ref"]] for f in by_test["T13"] if f.get("registration_timing_risk")], [einv[1]])
        self.assertTrue(any(f["object_ref"].startswith("CYCLE:") for f in by_test["T02"]))
        # Register and GSTR-1 reconciliations show exactly the planted differences.
        cats = {period: Counter((x["category"], x["bill_no"]) for x in f) for period, f in registers.items()}
        register = cats["FY 2025-26 sales register"]
        hidden = planted["Sales to a connected party hidden from the auditor's register"]["refs"]
        self.assertEqual(register, Counter({("SYSTEM_ONLY", b): 1 for b in hidden} | {("FIELD_DIFF", planted["Amount changed in the register"]["refs"][0]): 1}))
        self.assertEqual(cats["GSTR-1 03/2026"], Counter({("SYSTEM_ONLY", b): 1 for b in shell}))
        self.assertEqual(cats["GSTR-1 02/2026"], Counter({("FIELD_DIFF", b): 1 for b in planted["Sales under-reported in GSTR-1"]["refs"]}))
        self.assertEqual(cats["GSTR-1 01/2026"], Counter())


    # Proof chain and "How we know": the engine's inputs restated with real numbers (no AI).
    def test_every_review_finding_has_a_calculation_and_sources(self):
        for result, *_ in (self.hiding, self.honest):
            for fid, p in result["_proofs"].items():
                self.assertTrue(p["how"]["calculation"] and p["how"]["rule"], fid)
                self.assertIn("no AI", p["how"]["computed_by"])

    def test_shell_sale_chain_shows_what_is_missing(self):
        result, _, bills, _ = self.hiding
        t09 = next(p for p in result["_proofs"].values() if p["test_id"] == "T09")
        status = {l["stage"]: l["status"] for l in t09["chains"][0]["links"]}
        self.assertEqual(status["Sales register"], "match")
        self.assertEqual(status["GST return (GSTR-1)"], "missing")
        self.assertEqual(status["Dispatch & e-way bill"], "missing")
        self.assertEqual(status["Credit note"], "differs")
        t08 = next(p for p in result["_proofs"].values() if p["test_id"] == "T08")
        self.assertIn("127.5×", " ".join(t08["how"]["calculation"]))
        self.assertEqual(len(t08["chains"]), 6)  # the shell customer's year-end invoices (capped at six)

    def test_clean_invoice_chain_agrees_everywhere(self):
        result, *_ = self.honest
        chain = result["_clean_chain"]["chains"][0]
        self.assertFalse([l for l in chain["links"] if l["status"] in ("differs", "missing")], chain["links"])
        self.assertEqual(chain["summary"], "Every record holding this sale agrees with the books.")


if __name__ == "__main__":
    unittest.main()
