"""P0 regression tests: input validation (C1, B1, B2, B4), unpredictable sampling seeds (H1),
source-derived related parties (H5) and the client-safe error contract (H4)."""
import base64
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1
from Pramaan.backend import p3, security


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class P0RegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("p0-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()
        self.client = TestClient(p1.app, raise_server_exceptions=False)
        self.client_headers = {"Authorization": "Bearer " + security.issue("p0-client", "client_employee")}
        self.auditor_headers = {"Authorization": "Bearer " + security.issue("p0-auditor", "auditor")}
        response = self.client.post("/p2/customers", headers=self.client_headers, json={"customer_id": "C-1", "name": "Synthetic Customer"})
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def sale(self, number, **overrides):
        payload = {"order_id": f"SO-{number}", "dispatch_id": f"DSP-{number}", "invoice_id": f"INV-{number}", "journal_id": f"JRN-{number}",
                   "customer_id": "C-1", "order_date": "2026-03-01", "dispatch_date": "2026-03-02", "invoice_date": "2026-03-02",
                   "bill_no": f"BILL-{number}", "net_amount": "100.00", "tax_amount": "18.00"}
        payload.update(overrides)
        return self.client.post("/p2/sales", headers=self.client_headers, json=payload)

    def run_audit(self, **overrides):
        body = {"period_start": "2025-04-01", "period_end": "2026-03-31"}
        body.update(overrides)
        return self.client.post("/p3/audit-runs", headers=self.auditor_headers, json=body)

    # --- C1 -------------------------------------------------------------------------------
    def test_malformed_dates_are_rejected_with_field_errors(self):
        for field in ("invoice_date", "order_date", "dispatch_date"):
            response = self.sale(1, **{field: "31/13/2025"})
            self.assertEqual(response.status_code, 422, field)
            body = response.json()
            self.assertEqual(body["code"], "invalid_input")
            self.assertIn(field, [f["field"] for f in body["fields"]])
            self.assertNotIn("31/13/2025", response.text, "submitted values must not be reflected")
        self.assertEqual(self.sale(1, invoice_date="2026-02-30").status_code, 422, "calendar-invalid dates are rejected")
        self.assertEqual(self.sale(1, receipt={"receipt_id": "R-1", "amount": "1.00", "value_date": "tomorrow"}).status_code, 422)
        self.assertEqual(self.sale(1, credit_note={"credit_note_id": "CN-1", "credit_date": "2026-13-01", "amount": "1.00", "reason": "x"}).status_code, 422)

    def test_legacy_unreadable_date_no_longer_blocks_audits(self):
        for number in range(3):
            self.assertEqual(self.sale(number).status_code, 200)
        # Simulate a record written before validation existed (journals are immutable, so it cannot be fixed in place).
        db = sqlite3.connect(p1.DB_PATH)
        db.execute("UPDATE p2_invoices SET invoice_date='31/13/2025' WHERE invoice_id='INV-2'")
        db.commit()
        db.close()
        response = self.run_audit()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        flagged = [f for f in result["findings"] if f.get("category") == "UNREADABLE_DATE"]
        self.assertEqual([(f["object_ref"], f["state"]) for f in flagged], [("INV-2", "INCONSISTENT")])
        sampled = {s["object_ref"] for s in result["sample_items"]}
        self.assertNotIn("INV-2", sampled)
        reproduced = self.client.post(f"/p3/audit-runs/{result['run_id']}/reproduce", headers=self.auditor_headers)
        self.assertTrue(reproduced.json()["identical"])
        rerun = self.client.post(f"/p3/audit-runs/{result['run_id']}/rerun", headers=self.auditor_headers)
        self.assertEqual(rerun.status_code, 200, rerun.text)
        context = self.client.get(f"/ui/runs/{result['run_id']}/context", headers=self.auditor_headers)
        self.assertEqual(context.status_code, 200, context.text)
        setup = self.client.get("/ui/audit-setup", headers=self.auditor_headers).json()
        self.assertEqual(setup["invoice_date_end"], "2026-03-02", "B4: unreadable text must not sort as the latest date")
        self.assertEqual(setup["unreadable_date_count"], 1)

    def test_clean_snapshot_results_are_unchanged_by_date_sanitizer(self):
        for number in range(3):
            self.sale(number)
        db = p3.db_open()
        try:
            snapshot = p3.build_snapshot(db)
        finally:
            db.close()
        clean, findings = p3.sanitize_dates(snapshot)
        self.assertIs(clean, snapshot)
        self.assertEqual(findings, [])

    # --- B1 / B2 ---------------------------------------------------------------------------
    def test_invalid_amounts_return_422_not_500(self):
        for overrides in ({"receipt": {"receipt_id": "R-1", "amount": "abc", "value_date": "2026-03-03"}},
                          {"credit_note": {"credit_note_id": "CN-1", "credit_date": "2026-03-03", "amount": "-5", "reason": "x"}},
                          {"net_amount": "1.001"}, {"tax_amount": "NaN"}):
            response = self.sale(9, **overrides)
            self.assertEqual(response.status_code, 422, (overrides, response.text))

    def test_duplicate_evidence_ids_are_conflicts_and_leave_no_orphans(self):
        evidence = {"evidence_id": "EV-1", "content_type": "text/plain", "content_base64": b64(b"first"), "controller": "client", "acquisition_channel": "upload", "assertions": ["occurrence"]}
        sale = {"sale_id": "S-1", "register_source_base64": b64(b"row"), "register_row": {}, "party": {"party_id": "P-1"}, "invoice": {}, "dispatch": {}, "evidence": [evidence]}
        self.assertEqual(self.client.post("/sales", headers=self.client_headers, json=sale).status_code, 200)
        duplicate = {**sale, "sale_id": "S-2", "party": {"party_id": "P-2"}, "evidence": [{**evidence, "content_base64": b64(b"second-unique-bytes")}]}
        response = self.client.post("/sales", headers=self.client_headers, json=duplicate)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse((p1.VAULT / p1.digest(b"second-unique-bytes")).exists(), "rejected uploads must not reach the vault")
        same_request = {**sale, "sale_id": "S-3", "party": {"party_id": "P-3"}, "evidence": [{**evidence, "evidence_id": "EV-9"}, {**evidence, "evidence_id": "EV-9"}]}
        self.assertEqual(self.client.post("/sales", headers=self.client_headers, json=same_request).status_code, 422)
        missing_party = {**sale, "sale_id": "S-4", "party": {}}
        self.assertEqual(self.client.post("/sales", headers=self.client_headers, json=missing_party).status_code, 422)

    # --- H1 --------------------------------------------------------------------------------
    def test_server_generates_unpredictable_seed_when_omitted(self):
        for number in range(3):
            self.sale(number)
        first, second = self.run_audit().json(), self.run_audit().json()
        self.assertTrue(first["sampling_seed"].startswith("srv-"))
        self.assertGreaterEqual(len(first["sampling_seed"]), 36)
        self.assertNotEqual(first["sampling_seed"], second["sampling_seed"])
        explicit = self.run_audit(sampling_seed="documented-reperformance-seed")
        self.assertEqual(explicit.json()["sampling_seed"], "documented-reperformance-seed")
        self.assertEqual(self.run_audit(sampling_seed="short").status_code, 422)

    # --- H5 --------------------------------------------------------------------------------
    def test_related_parties_are_parsed_from_the_source(self):
        source = b"Customer ID,Related Party,Valid From\r\nC-1,yes,2025-04-01\r\nC-2,no,\r\n"
        response = self.client.post("/p2/related-parties", headers=self.client_headers, json={"period": "FY26", "source_base64": b64(source)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["parser"], "rp-source-parser-v1")
        stored = self.client.get("/ui/registers", headers=self.auditor_headers).json()["related_parties"][0]["parsed_json"]
        self.assertEqual(stored, [{"customer_id": "C-1", "related_party": True, "valid_from": "2025-04-01"}, {"customer_id": "C-2", "related_party": False, "valid_from": None}])
        mismatched = self.client.post("/p2/related-parties", headers=self.client_headers, json={"period": "FY26", "source_base64": b64(source), "records": [{"customer_id": "C-9", "related_party": True}]})
        self.assertEqual(mismatched.status_code, 422)
        self.assertIn("do not match", mismatched.json()["detail"])
        for bad in (b"customer_id,related_party,valid_from\r\nC-1,maybe,2025-04-01\r\n", b"customer_id,valid_from\r\nC-1,01-04-2025\r\n", b"", b"[1, 2]"):
            self.assertEqual(self.client.post("/p2/related-parties", headers=self.client_headers, json={"period": "FY26", "source_base64": b64(bad)}).status_code, 422, bad)

    # --- H4 --------------------------------------------------------------------------------
    def test_error_contract_explains_rejections_without_leaking_internals(self):
        missing = self.client.get("/p4/audit-runs/P3-missing", headers=self.auditor_headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"code": "not_found", "detail": "run not found"})
        self.sale(1)
        duplicate = self.sale(1)
        self.assertEqual(duplicate.json()["code"], "conflict")
        self.assertIn("duplicate", duplicate.json()["detail"])
        denied = self.client.get("/ui/runs", headers=self.client_headers)
        self.assertEqual(denied.status_code, 403)

    def test_unhandled_errors_return_generic_500(self):
        with patch.object(p3, "build_snapshot", side_effect=RuntimeError("secret internal detail")):
            response = self.client.post("/p3/audit-runs", headers=self.auditor_headers, json={"period_start": "2025-04-01", "period_end": "2026-03-31"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.text)
        self.assertEqual(response.json()["code"], "error")


if __name__ == "__main__":
    unittest.main()
