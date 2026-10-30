import asyncio
import base64
import hashlib
import json
import sqlite3
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from Pramaan.backend import app as p1


class P2ApiGateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("p2-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, payload=None):
        body = json.dumps(payload or {}).encode()
        messages = [{"type": "http.request", "body": body, "more_body": False}]
        sent = []

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        raw_path, _, query = path.partition("?")
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": method, "scheme": "http", "path": raw_path, "raw_path": raw_path.encode(), "query_string": query.encode(), "root_path": "", "headers": [(b"content-type", b"application/json")], "client": ("test", 1234), "server": ("test", 80)}
        from Pramaan.backend.tests.auth_support import headers
        scope["headers"].extend(headers(scope))
        asyncio.run(p1.app(scope, receive, send))
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        response_body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return status, json.loads(response_body or b"{}")

    def test_api_batch_balances_journals_and_preserves_posted_line_immutability(self):
        status, customer = self.request("POST", "/p2/customers", {"customer_id": "C-1", "name": "Synthetic Customer", "gstin": "29ABCDE1234F1Z5"})
        self.assertEqual(status, 200, customer)
        for number in range(1, 3):
            status, sale = self.request("POST", "/p2/sales", {
                "order_id": f"SO-{number}", "dispatch_id": f"DSP-{number}", "invoice_id": f"INV-{number}", "journal_id": f"JRN-{number}",
                "customer_id": "C-1", "order_date": "2026-03-01", "dispatch_date": "2026-03-02", "invoice_date": "2026-03-03",
                "bill_no": f"B-{number:03}", "net_amount": "100.00", "tax_amount": "5.00",
                "receipt": ({"receipt_id": "RCT-1", "amount": "25.00", "value_date": "2026-03-05", "bank_ref": "DEMO-REF"} if number == 1 else None),
                "credit_note": ({"credit_note_id": "CN-2", "credit_date": "2026-03-10", "amount": "2.50", "reason": "demo adjustment"} if number == 2 else None),
                "evidence": ([{"evidence_id": "EV-1", "content_base64": base64.b64encode(b"synthetic dispatch evidence").decode(), "content_type": "text/plain"}] if number == 1 else []),
            })
            self.assertEqual(status, 200, sale)
            journal_status, journal = self.request("GET", f"/p2/journals/JRN-{number}")
            self.assertEqual(journal_status, 200)
            self.assertTrue(journal["balanced"])
            self.assertEqual(sum(line["debit_cents"] for line in journal["lines"]), sum(line["credit_cents"] for line in journal["lines"]))
            self.assertGreaterEqual(len(journal["lines"]), 2)

        db = sqlite3.connect(p1.DB_PATH)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE p2_journal_lines SET debit_cents=1 WHERE journal_id='JRN-1' AND line_no=1")
        db.rollback()
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM p2_journal_lines WHERE journal_id='JRN-1' AND line_no=1")
        db.rollback()
        db.close()
        status, reversal = self.request("POST", "/p2/journals/JRN-1/reverse?reversal_id=JRN-1-REV")
        self.assertEqual(status, 200, reversal)
        self.assertEqual(reversal["reverses"], "JRN-1")
        reverse_status, reverse_journal = self.request("GET", "/p2/journals/JRN-1-REV")
        self.assertEqual(reverse_status, 200)
        self.assertTrue(reverse_journal["balanced"])

    def test_register_preservation_and_t00_detects_planted_row_and_field_difference(self):
        status, _ = self.request("POST", "/p2/customers", {"customer_id": "C-2", "name": "Match Customer", "gstin": "27AAAAA1111A1Z1"})
        self.assertEqual(status, 200)
        for n, bill in ((1, "B-001"), (2, "B-002")):
            status, sale = self.request("POST", "/p2/sales", {"order_id": f"SO-{n}", "dispatch_id": f"DSP-{n}", "invoice_id": f"INV-{n}", "journal_id": f"JRN-{n}", "customer_id": "C-2", "order_date": "2026-03-01", "dispatch_date": "2026-03-02", "invoice_date": "2026-03-03", "bill_no": bill, "net_amount": "100.00", "tax_amount": "5.00"})
            self.assertEqual(status, 200, sale)
        source = b"Bill No,Date,Customer,Gross Amt\r\nB-001,2026-03-03,Match Customer,104.00\r\nB-ONLY,2026-03-04,Phantom,1.00\r\n"
        status, uploaded = self.request("POST", "/p2/registers", {"period": "FY26", "source_base64": base64.b64encode(source).decode()})
        self.assertEqual(status, 200, uploaded)
        self.assertEqual(uploaded["sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual((p1.VAULT / uploaded["sha256"]).read_bytes(), source)
        status, reconciled = self.request("POST", f"/p2/registers/{uploaded['upload_id']}/reconcile")
        self.assertEqual(status, 200, reconciled)
        categories = {finding["category"] for finding in reconciled["findings"]}
        self.assertIn("REGISTER_ONLY", categories)
        self.assertIn("FIELD_DIFF", categories)
        self.assertIn("SYSTEM_ONLY", categories)
        field_diff = next(f for f in reconciled["findings"] if f["category"] == "FIELD_DIFF")
        difference = field_diff["field_differences"][0]
        self.assertEqual({k: difference[k] for k in ("field", "register_value", "system_value")}, {"field": "Gross Amt", "register_value": "104.00", "system_value": "105.00"})
        self.assertEqual(difference["normalized_difference"], {"cents": -100, "inr": "-1.00"})

        rp_source = b"Party,Relationship\r\nC-2,disclosed\r\n"
        status, rp_upload = self.request("POST", "/p2/related-parties", {"period": "FY26", "source_base64": base64.b64encode(rp_source).decode(), "records": [{"party": "C-2", "relationship": "disclosed"}]})
        self.assertEqual(status, 200, rp_upload)
        self.assertEqual((p1.VAULT / rp_upload["content_sha256"]).read_bytes(), rp_source)
        self.assertEqual(rp_upload["parsed_row_count"], 1)


if __name__ == "__main__":
    unittest.main()
