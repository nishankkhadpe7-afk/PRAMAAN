"""Plain-language explanations, per-run integrity checks and shared evidence requests."""
import base64
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from Pramaan.backend import app as p1, explain, p3, security


class ExplainIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / ".runtime" / ("explain-" + uuid.uuid4().hex)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("ex-client", "client_employee"), "auditor": security.issue("ex-auditor", "auditor")}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        self.request("POST", "/p2/customers", "client", {"customer_id": "EX-CO", "name": "Explain synthetic company"})
        self.request("POST", "/p2/sales", "client", {"order_id": "EX-O", "dispatch_id": "EX-D", "invoice_id": "EX-I", "journal_id": "EX-J", "customer_id": "EX-CO", "bill_no": "EX-B",
                                                     "order_date": "2026-03-30", "dispatch_date": "2026-03-30", "invoice_date": "2026-03-30", "net_amount": "100.00"})
        self.source = b"Bill No,Date,Customer,Gross Amt,GST No\r\nEX-B,2026-03-30,Explain synthetic company,150.00,\r\n"
        self.upload = self.request("POST", "/p2/registers", "client", {"period": "FY26", "source_base64": base64.b64encode(self.source).decode()}).json()["upload_id"]
        self.request("POST", f"/p2/registers/{self.upload}/reconcile")
        self.run = self.request("POST", "/p3/audit-runs", body={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "explain-integration-seed-2026"}).json()

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, role="auditor", body=None):
        return self.client.request(method, path, headers={"Authorization": "Bearer " + self.tokens[role]}, **({} if body is None else {"json": body}))

    def test_context_explains_every_finding_and_sample_without_changing_the_result(self):
        context = self.request("GET", f"/ui/runs/{self.run['run_id']}/context").json()
        self.assertEqual(context["result"], self.run)
        for finding in context["findings"]:
            self.assertTrue(finding["observation"].strip(), finding["finding_id"])
        diff = next(f for f in context["findings"] if f["test_id"] == "T00" and f["category"] == "FIELD_DIFF")
        self.assertIn("₹150.00", diff["observation"])
        self.assertIn("₹100.00", diff["observation"])
        items = context["result"]["sample_items"]
        self.assertEqual(set(context["sample_explanations"]), {f"{s['sheet']}:{s['object_ref']}" for s in items})
        for item in items:
            info = context["sample_explanations"][f"{item['sheet']}:{item['object_ref']}"]
            self.assertTrue(info["explanation"] and info["why"] and info["inclusion_label"])
            if item["stratum"] in {"certainty", "post_period_census", "high_value"} or item["sheet"] == "cutoff_tod":
                self.assertEqual(info["inclusion_value"], 1.0)
            elif item["stratum"] == "probability":
                self.assertEqual(info["inclusion_value"], item["inclusion_probability"])
        self.assertTrue(self.request("POST", f"/p3/audit-runs/{self.run['run_id']}/reproduce").json()["identical"])

    def test_indian_amount_grouping_and_financial_year_quarters(self):
        from Pramaan.backend.p5_exports import fy_quarter
        self.assertEqual(explain.inr("295000"), "₹2,95,000.00")
        self.assertEqual(explain.inr("12345678.5"), "₹1,23,45,678.50")
        self.assertEqual(explain.inr("-500"), "-₹500.00")
        self.assertEqual([fy_quarter(f"2026-{m:02}-01") for m in (4, 7, 10, 1, 3)], ["Q1", "Q2", "Q3", "Q4", "Q4"])

    def test_run_integrity_recomputes_and_detects_tampered_sources(self):
        url = f"/ui/runs/{self.run['run_id']}/integrity"
        self.assertEqual(self.request("GET", url, "client").status_code, 403)
        report = self.request("GET", url).json()
        self.assertTrue(report["all_passed"])
        self.assertEqual({c["key"] for c in report["checks"]}, {"snapshot", "rules", "reproduce", "sources", "packages", "chain"})
        (p1.VAULT / p1.digest(self.source)).write_bytes(b"tampered register")
        report = self.request("GET", url).json()
        self.assertFalse(report["all_passed"])
        failed = [c["key"] for c in report["checks"] if c["status"] == "fail"]
        self.assertEqual(failed, ["sources"])

    def test_one_upload_satisfies_the_same_request_in_every_run(self):
        second = self.request("POST", "/p3/audit-runs", body={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "explain-second-seed-2026"}).json()
        requests = [r for r in self.request("GET", "/ui/inbox", "client").json()["requests"] if r["sample_ref"] == "EX-I"]
        self.assertEqual({r["run_id"] for r in requests}, {self.run["run_id"], second["run_id"]})
        document = requests[0]["required_docs"][0]
        result = self.request("POST", f"/p3/evidence-requests/{requests[0]['request_id']}/evidence", "client", {"evidence_id": "EX-EV", "document_type": document,
                              "content_base64": base64.b64encode(b"synthetic").decode(), "content_type": "text/plain", "controller": "company", "acquisition_channel": "company_upload"})
        self.assertEqual(result.status_code, 200, result.text)
        # The invoice is sampled on more than one sheet in each run; every other request asking for this document is satisfied.
        expected = {r["request_id"] for r in requests if document in r["required_docs"]} - {requests[0]["request_id"]}
        self.assertEqual(set(result.json()["also_satisfied_requests"]), expected)
        for request in [r for r in self.request("GET", "/ui/inbox", "client").json()["requests"] if r["sample_ref"] == "EX-I" and document in r["required_docs"]]:
            self.assertIn(document, request["uploaded_docs"])
            self.assertEqual([e["evidence_id"] for e in request["evidence"]], ["EX-EV"])
        listed = self.request("GET", f"/p3/audit-runs/{second['run_id']}/evidence-requests").json()["requests"]
        evidence = next(r for r in listed if r["sample_ref"] == "EX-I")["evidence"]
        self.assertEqual(evidence[0]["in_snapshot"], False)
        download = self.request("GET", "/ui/evidence/EX-EV/content")
        self.assertIn(f'filename="{document}_EX-I.txt"', download.headers["content-disposition"])


    def test_flagged_amounts_and_data_checks_follow_this_audits_data(self):
        # The setUp register says 150.00 where the books say 100.00: a 50.00 difference.
        context = self.request("GET", f"/ui/runs/{self.run['run_id']}/context?upload_id={self.upload}").json()
        # The imported synthetic dataset adds its own differences, so the 50.00 is part of a larger total.
        groups = {g["key"]: g for g in context["exposure"]["groups"]}
        self.assertGreaterEqual(float(groups["differences"]["amount"]), 50.0)
        self.assertGreaterEqual(float(context["exposure"]["potential_misstatement_inr"]), float(groups["differences"]["amount"]))
        report = self.request("GET", f"/ui/runs/{self.run['run_id']}/integrity?upload_id={self.upload}").json()
        self.assertTrue(report["all_passed"])
        statuses = {c["key"]: c["status"] for c in report["data_checks"]}
        self.assertEqual(statuses["reconcile"], "fail")
        self.assertEqual(statuses["money"], "fail")
        self.assertEqual(statuses["evidence"], "warn")
        self.assertEqual(report["overall"], "fail")
        package = self.request("POST", f"/p5/runs/{self.run['run_id']}/packages", body={"upload_id": self.upload}).json()
        self.assertEqual(self.request("GET", "/p5/packages/" + package["package_id"]).json()["exposure"]["potential_misstatement_inr"], context["exposure"]["potential_misstatement_inr"])


if __name__ == "__main__":
    unittest.main()
