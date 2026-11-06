import base64
import csv
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import unittest
import uuid
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from openpyxl import load_workbook  # Independent reader only; never authors backend exports.
from pypdf import PdfReader

from Pramaan.backend import app as p1, p3, p5, security
from Pramaan.backend.p5_checks import demo_signature, capacity_screen


class P5AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("p5-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault"), patch.dict("os.environ", {"PRAMAAN_DEMO_IRP_PUBLIC_KEY": ""})]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("agent-auditor", "auditor"), "human": security.issue("human-reviewer", "auditor", human=True)}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        self.assertEqual(self.request("POST", "/p2/customers", "client", json={"customer_id": "P5-C", "name": "Synthetic Client"}).status_code, 200)
        for number, date in ((1, "2026-03-30"), (2, "2026-04-02")):
            sale = {"order_id": f"P5-O{number}", "dispatch_id": f"P5-D{number}", "invoice_id": f"P5-I{number}", "journal_id": f"P5-J{number}", "customer_id": "P5-C", "order_date": date, "dispatch_date": date, "invoice_date": date, "bill_no": f"P5-B{number}", "net_amount": "100.00"}
            if number == 1:
                sale["credit_note"] = {"credit_note_id": "P5-CN", "credit_date": "2026-04-10", "amount": "2.50", "reason": "Subsequent quality adjustment"}
            self.assertEqual(self.request("POST", "/p2/sales", "client", json=sale).status_code, 200)
        self.legacy = self.new_run("legacy-p5-seed-2026")
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        self.source_rows = [["Bill No", "Date", "Customer", "Gross Amt", "GST No", "Code", "Notes", "Notes", "Empty"],
                            ["P5-B1", "2026-03-30", "Synthetic Client", "99.99", "", "0007", "=SUM(1,2)", "quoted\nline", ""], [],
                            ["REGISTER-ONLY", "2026-03-31", "  Space preserved  ", "1.00", "", "0010", "+CMD", "embedded , comma", ""]]
        writer.writerows(self.source_rows)
        self.source = b"\xef\xbb\xbf" + stream.getvalue().encode()
        upload = self.request("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": base64.b64encode(self.source).decode()})
        self.assertEqual(upload.status_code, 200)
        self.upload = upload.json()["upload_id"]
        self.assertEqual(self.request("POST", f"/p2/registers/{self.upload}/reconcile").status_code, 200)
        self.run = self.new_run()

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, role="auditor", **kwargs):
        extra_headers = kwargs.pop("headers", {})
        return self.client.request(method, path, headers={"Authorization": "Bearer " + self.tokens[role], **extra_headers}, **kwargs)

    def new_run(self, seed="p5-export-seed-2026"):
        response = self.request("POST", "/p3/audit-runs", json={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": seed})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def package(self):
        response = self.request("POST", f"/p5/runs/{self.run['run_id']}/packages", json={"upload_id": self.upload})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def report(self, package):
        return self.request("GET", f"/p5/packages/{package['package_id']}").json()

    def review(self, finding, outcome="EXCEPTION_CONFIRMED", **extra):
        return self.request("POST", f"/p5/runs/{self.run['run_id']}/findings/{finding}/review", "human", json={"outcome": outcome, "reason": "Human assessed the snapshotted source references; conclusion is not automatic.", "expected_revision": 0, **extra})

    def test_workbook_opens_source_fidelity_provenance_and_links(self):
        package = self.package()
        report = self.report(package)
        raw = self.request("GET", f"/p5/packages/{package['package_id']}/workpaper.xlsx").content
        (self.root / "workpaper.xlsx").write_bytes(raw)
        book = load_workbook(io.BytesIO(raw), data_only=False)
        self.assertTrue({"Sales Register", "Sales TOD", "Sales Cut-off TOD", "Credit Note TOD", "Findings", "Provenance", "Receipt", "Coverage", "Tickmarks"} <= set(book.sheetnames))
        source_sheet = book["Sales Register"]
        actual = [[cell.value if cell.value is not None else "" for cell in row] for row in source_sheet.iter_rows()]
        self.assertEqual(actual[0], self.source_rows[0])
        self.assertEqual(actual[1], self.source_rows[1])
        self.assertEqual(actual[2], [""] * 9)
        self.assertEqual(actual[3], self.source_rows[3])
        self.assertTrue(all(c.data_type != "f" and not c.has_style for row in source_sheet for c in row))
        self.assertEqual(base64.b64decode(report["register"]["source_base64"]), self.source)
        self.assertEqual(p1.digest(self.source), report["receipt"]["source_sha256"])
        for finding in report["findings"]:
            for key in ("run_id", "snapshot_hash", "ruleset_hash", "ruleset_version", "test_id", "assertion", "reason", "sample_scope"):
                self.assertTrue(finding[key], key)
            self.assertTrue(finding["evidence_ids"])
            self.assertTrue(set(finding["evidence_ids"]) <= report["evidence_index"].keys())
            self.assertFalse(finding["confirmed_exception"])
            self.assertEqual(finding["exception_status"], "OPEN_REVIEW")
        self.assertTrue(any(f["test_id"] == "T00" and f["category"] == "FIELD_DIFF" for f in report["findings"]))
        self.assertTrue(any(f["test_id"] == "T00" and f["category"] == "REGISTER_ONLY" for f in report["findings"]))
        for name, count in (("Sales TOD", "sales_tod"), ("Sales Cut-off TOD", "cutoff_tod"), ("Credit Note TOD", "credit_note_tod")):
            self.assertEqual(book[name].max_row - 3, len([s for s in report["result"]["sample_items"] if s["sheet"] == count]))
            self.assertTrue(any(cell.hyperlink for row in book[name] for cell in row))
        self.assertEqual(report["totals"]["confirmed_exceptions"], 0)
        self.assertGreater(report["totals"]["unquantified_findings"], 0)
        self.assertEqual(report["result"]["rule_coverage"]["T12"]["status"], "not_evaluable")
        self.assertEqual(report["result"]["rule_coverage"]["T13"]["status"], "demo_signed_qr_adapter_evaluated")
        book.close()

    def test_reviewer_permissions_proposals_and_immutable_history(self):
        initial = self.package()
        finding = self.run["findings"][0]["finding_id"]
        path = f"/p5/runs/{self.run['run_id']}/findings/{finding}/review"
        body = {"outcome": "EXCEPTION_CONFIRMED", "reason": "proposed only", "expected_revision": 0}
        for role in ("client", "auditor"):
            self.assertEqual(self.request("POST", path, role, json=body, headers={"X-Pramaan-Human": "true"}).status_code, 403)
        self.assertEqual(self.request("POST", path, "human", json=body, headers={"X-Pramaan-Channel": "mcp"}).status_code, 403)
        self.assertEqual(self.request("POST", path.replace("/review", "/proposal"), json=body).status_code, 200)
        self.assertEqual(self.report(initial)["totals"]["confirmed_exceptions"], 0)
        self.assertEqual(self.review(finding).status_code, 200)
        later = self.package()
        self.assertNotEqual(initial["package_id"], later["package_id"])
        self.assertEqual(self.report(initial)["totals"]["confirmed_exceptions"], 0)
        self.assertEqual(self.report(later)["totals"]["confirmed_exceptions"], 1)
        self.assertEqual(self.review(finding).status_code, 409)
        self.assertEqual(self.review(finding, "EXPLAINED", expected_revision=1).status_code, 200)
        queue = self.request("GET", f"/p5/runs/{self.run['run_id']}/reviews").json()
        item = next(i for i in queue["items"] if i["finding_id"] == finding)
        self.assertEqual(item["human_decision"]["revision"], 2)
        self.assertEqual(item["exception_status"], "REVIEWED")
        for path in (f"/p5/packages/{later['package_id']}", f"/p5/packages/{later['package_id']}/workpaper.xlsx", f"/p5/runs/{self.run['run_id']}/reviews"):
            self.assertEqual(self.request("GET", path, "client").status_code, 403)
        with sqlite3.connect(p1.DB_PATH) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM p5_reviews").fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE p5_reviews SET decision_json='{}'")
        marker = security.identity.set({"subject": "agent", "role": "auditor", "human": False})
        db = p3.db_open()
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("INSERT INTO p5_reviews VALUES('x','x',1,'{}')")
        finally:
            db.close(); security.identity.reset(marker)
        marker = security.identity.set({"subject": "employee", "role": "client_employee"})
        db = p3.db_open()
        try:
            for statement in ("INSERT INTO p5_packages VALUES('x','x','{}','x')", "SELECT * FROM p5_reviews", "DELETE FROM p5_proposals"):
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(statement)
        finally:
            db.close(); security.identity.reset(marker)

    def test_reproduction_exports_ignore_live_changes_and_later_review(self):
        package = self.package()
        self.assertEqual(self.package()["package_id"], package["package_id"])
        exports = {ext: self.request("GET", f"/p5/packages/{package['package_id']}/{name}").content for ext, name in (("xlsx", "workpaper.xlsx"), ("pdf", "memo.pdf"), ("zip", "defensibility.zip"))}
        with sqlite3.connect(p1.DB_PATH) as db:
            db.execute("UPDATE p2_customers SET name='Modified after test' WHERE customer_id='P5-C'")
        (p1.VAULT / p1.digest(self.source)).write_bytes(b"modified raw source")
        for ext, name in (("xlsx", "workpaper.xlsx"), ("pdf", "memo.pdf"), ("zip", "defensibility.zip")):
            self.assertEqual(self.request("GET", f"/p5/packages/{package['package_id']}/{name}").content, exports[ext])
        changes = self.request("GET", f"/p4/audit-runs/{self.run['run_id']}/changes").json()
        self.assertTrue(changes["changed"])
        self.assertEqual(len(changes["affected_samples"]), len(self.run["sample_items"]))
        self.assertTrue(self.request("POST", f"/p3/audit-runs/{self.run['run_id']}/reproduce").json()["identical"])
        self.assertEqual(self.request("POST", f"/p5/runs/{self.run['run_id']}/packages", json={"upload_id": self.upload}).status_code, 409)

    def test_pdf_pack_totals_and_human_supported_impact(self):
        initial = self.package()
        report = self.report(initial)
        findings = [f for f in report["findings"] if f["object_ref"] == "INV-003" and f["test_id"] in {"T06", "T15"}]
        self.assertEqual(len(findings), 2)
        for finding in findings:
            response = self.review(finding["finding_id"], impact_inr="100.00", impact_group="INV-003-ADJ", impact_basis_evidence_ids=[finding["evidence_ids"][0]], proposed_adjustment="Human-proposed correction; not posted to the ledger.")
            self.assertEqual(response.status_code, 200, response.text)
        package = self.package()
        report = self.report(package)
        self.assertEqual(report["totals"]["supported_confirmed_impact_inr"], "100.00")
        self.assertEqual(report["totals"]["confirmed_exceptions"], 2)
        pdf = self.request("GET", f"/p5/packages/{package['package_id']}/memo.pdf").content
        (self.root / "memo.pdf").write_bytes(pdf)
        reader = PdfReader(io.BytesIO(pdf))
        document = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("Supported confirmed impact (INR): 100.00", document)
        self.assertIn("no official IRP verification", document)
        for finding in report["findings"]:
            self.assertIn(finding["finding_id"], document)
            self.assertIn(finding["assertion"], document)
        archive_bytes = self.request("GET", f"/p5/packages/{package['package_id']}/defensibility.zip").content
        with ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(archive.read("original_register.csv"), self.source)
            self.assertEqual(json.loads(archive.read("report.json"))["totals"], report["totals"])
            self.assertEqual(json.loads(archive.read("receipt.json"))["output_content_digest"], package["content_digest"])
            self.assertTrue(json.loads(archive.read("audit_log_verification.json"))["valid"])
            self.assertIn("sample_evidence_index.json", archive.namelist())
        book = load_workbook(io.BytesIO(self.request("GET", f"/p5/packages/{package['package_id']}/workpaper.xlsx").content), data_only=True)
        summary = dict(book["Summary"].values)
        self.assertEqual(summary["supported_confirmed_impact_inr"], 100)
        self.assertEqual(sum(row[1] for row in list(book["Impact Groups"].values)[1:]), 100)
        book.close()
        lifecycle = self.request("GET", f"/p5/packages/{package['package_id']}/sales/INV-003").json()
        self.assertIsNone(lifecycle["control_date"])
        self.assertTrue(lifecycle["timeline"])
        self.assertTrue(lifecycle["findings"])

    def test_legacy_missing_register_and_package_tamper_fail_closed(self):
        self.assertEqual(self.request("POST", f"/p5/runs/{self.legacy['run_id']}/packages", json={"upload_id": self.upload}).status_code, 409)
        package = self.package()
        with sqlite3.connect(p1.DB_PATH) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE p5_packages SET report_json='{}'")
            # Administrator bypass deliberately used to verify independent digest checks.
            db.execute("DROP TRIGGER p5_packages_no_update")
            db.execute("UPDATE p5_packages SET report_json='{}'")
        self.assertEqual(self.request("GET", f"/p5/packages/{package['package_id']}/memo.pdf").status_code, 409)

    def test_test_only_signature_capacity_and_evidence_chips(self):
        private = Ed25519PrivateKey.generate()
        public = base64.b64encode(private.public_key().public_bytes_raw()).decode()
        with closing(p3.db_open()) as db:
            invoice = next(i for i in p3.build_snapshot(db)["invoices"] if i["invoice_id"] == "INV-003")
        payload = {key: invoice[key] for key in ("invoice_id", "bill_no", "gross_cents")}
        envelope = {"payload": payload, "signature_base64": base64.b64encode(private.sign(p1.canonical(payload))).decode()}
        raw = p1.canonical(envelope)
        verified = demo_signature(raw, public, invoice)
        self.assertEqual(verified["state"], "DEMO_SIGNATURE_VALID")
        self.assertFalse(verified["government_registered"])
        self.assertEqual(demo_signature(raw, "", invoice)["state"], "UNAVAILABLE")
        envelope["payload"]["gross_cents"] += 1
        self.assertEqual(demo_signature(p1.canonical(envelope), public, invoice)["state"], "INCONSISTENT")
        self.assertEqual(capacity_screen({"quantity_units": 11, "vehicle_capacity_units": 10})["state"], "REVIEW")
        self.assertEqual(capacity_screen({"quantity_units": 1, "vehicle_capacity_units": "NaN"})["state"], "GAP")
        request = next(r for r in self.request("GET", f"/p3/audit-runs/{self.run['run_id']}/evidence-requests").json()["requests"] if r["sample_ref"] == "INV-003" and r["sheet"] == "sales_tod")
        self.assertEqual(self.request("POST", f"/p3/evidence-requests/{request['request_id']}/evidence", "client", json={"evidence_id": "DEMO-SIGNED", "document_type": "invoice", "content_base64": base64.b64encode(raw).decode(), "content_type": "application/vnd.pramaan.demo-irp+json", "controller": "Demo IRP", "acquisition_channel": "company_upload"}).status_code, 200)
        self.run = self.request("POST", f"/p3/audit-runs/{self.run['run_id']}/rerun").json()
        with patch.dict("os.environ", {"PRAMAAN_DEMO_IRP_PUBLIC_KEY": public}):
            package = self.package()
        report = self.report(package)
        self.assertTrue(any(c["state"] == "DEMO_SIGNATURE_VALID" and c["classification"] == "DEMO_IRP_TEST_ONLY" for c in report["differentiated_checks"]))
        sale = self.request("GET", f"/p5/packages/{package['package_id']}/sales/INV-003").json()
        self.assertEqual(sale["evidence_chips"][0]["provenance"], "COMPANY_SUPPLIED_UNVERIFIED")
        self.assertFalse(sale["evidence_chips"][0]["independently_verified"])
        self.assertEqual(report["totals"]["confirmed_exceptions"], 0)


if __name__ == "__main__":
    unittest.main()
