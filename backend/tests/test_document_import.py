"""Tally XML, PDF bank statement and PDF invoice reading: parser behaviour and the API paths that use them."""
import base64
import json
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, document_import as di, fixtures_documents as fx, p3, security
from Pramaan.backend.evaluate_agent import build_instance


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class TallyParserTests(unittest.TestCase):
    def test_sales_vouchers_become_register_rows_and_the_rest_is_reported(self):
        read = di.parse_tally_sales(fx.tally_xml())
        self.assertEqual([r["Bill No"] for r in read["rows"]], ["TLY/25-26/001", "TLY/25-26/002", "TLY/25-26/003"])
        self.assertEqual(read["rows"][0], {"Bill No": "TLY/25-26/001", "Date": "2025-04-12", "Customer": "Sharma Traders (synthetic)",
                                           "Gross Amt": "118000.00", "GST No": "27AAAPS1234C1Z5"})
        self.assertEqual(read["vouchers_seen"], 5)
        self.assertEqual({s["reason"].split(" (")[0] for s in read["skipped"]}, {"not a sales voucher", "cancelled or optional voucher"})

    def test_sales_returns_and_orders_are_not_sales(self):
        xml = fx.tally_xml().replace(b'VCHTYPE="Receipt"', b'VCHTYPE="Sales Return"').replace(b"<VOUCHERTYPENAME>Receipt</VOUCHERTYPENAME>", b"<VOUCHERTYPENAME>Sales Return</VOUCHERTYPENAME>")
        read = di.parse_tally_sales(xml)
        self.assertEqual(len(read["rows"]), 3)
        self.assertIn("Sales Return", " ".join(s["reason"] for s in read["skipped"]))

    def test_utf16_exports_and_control_characters_are_read(self):
        self.assertEqual(len(di.parse_tally_sales(fx.tally_xml(utf16=True))["rows"]), 3)

    def test_entity_declarations_and_non_tally_files_are_refused(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>'
        with self.assertRaises(di.DocumentReadError):
            di.parse_tally_sales(bomb)
        with self.assertRaises(di.DocumentReadError):
            di.parse_tally_sales(b"<ENVELOPE><BODY/></ENVELOPE>")
        with self.assertRaises(di.DocumentReadError):
            di.parse_tally_sales(b"Bill No,Date\n1,2025-01-01\n")


class BankPdfParserTests(unittest.TestCase):
    def test_columns_decide_debit_and_credit(self):
        read = di.parse_bank_pdf(fx.bank_statement_pdf())
        rows = read["rows"]
        self.assertEqual([(r["txn_date"], r["direction"], r["amount_cents"]) for r in rows],
                         [("2025-04-14", "credit", 11800000), ("2025-04-18", "debit", 4500000), ("2025-05-09", "credit", 5900000), ("2025-06-02", "debit", 825050)])
        self.assertEqual(rows[0]["reference"], "N104250001234")
        self.assertEqual(rows[3]["balance_cents"], 37374950)
        self.assertEqual(read["unread_lines"], [])

    def test_no_guessing_without_a_column_header(self):
        with self.assertRaises(di.DocumentReadError):
            di.parse_bank_pdf(fx.bank_statement_pdf(with_header=False))
        with self.assertRaises(di.DocumentReadError):
            di.parse_bank_pdf(b"not a pdf")


class InvoicePdfTests(unittest.TestCase):
    def test_fields_are_read_and_compared(self):
        bill, when, buyer, gstin, total = fx.SALES[0]
        read = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total))
        self.assertEqual((read["invoice_number"], read["invoice_date"], read["total_cents"]), ("TLY/25-26/001", "2025-04-12", 11800000))
        self.assertIn(gstin, read["gstins"])
        books = {"bill_no": "TLY/25-26/001", "invoice_date": "2025-04-12", "gross_cents": 11800000, "gstin": gstin}
        self.assertEqual(di.compare_invoice(read, books)["status"], "matches")
        changed = di.compare_invoice(read, {**books, "gross_cents": 11700000})
        self.assertEqual(changed["status"], "differs")
        self.assertEqual([f["field"] for f in changed["fields"] if f["result"] == "differs"], ["total"])
        self.assertEqual(di.compare_invoice(read, None)["status"], "no_invoice_in_snapshot")

    def test_an_unread_field_is_never_a_match(self):
        read = {"invoice_number": None, "invoice_date": None, "gstins": [], "total_cents": None}
        self.assertEqual(di.compare_invoice(read, {"bill_no": "X", "invoice_date": "2025-01-01", "gross_cents": 100})["status"], "incomplete")


class DocumentImportApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent / ".runtime" / ("docs-" + uuid.uuid4().hex)
        cls.root.mkdir(parents=True)
        cls.patches = [patch.object(p1, "ROOT", cls.root), patch.object(p1, "DB_PATH", cls.root / "p1.sqlite3"),
                       patch.object(p1, "VAULT", cls.root / "vault"), patch.dict("os.environ", {"PRAMAAN_DATA": str(cls.root)})]
        for item in cls.patches:
            item.start()
        cls.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("auditor", "auditor")}
        cls.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        cls.data = build_instance(cls.request)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        for item in reversed(cls.patches):
            item.stop()

    @classmethod
    def request(cls, method, path, role="auditor", **kwargs):
        return cls.client.request(method, path, headers={"Authorization": "Bearer " + cls.tokens[role]}, **kwargs)

    def test_tally_xml_register_is_preserved_and_reconcilable(self):
        source = fx.tally_xml()
        response = self.request("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": b64(source), "source_format": "tally_xml"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["row_count"], body["source_format"], body["vouchers_seen"], body["skipped_vouchers"]), (3, "tally_xml", 5, 2))
        self.assertEqual(body["sha256"], p1.digest(source))  # the XML itself is the preserved source
        reconciled = self.request("POST", f"/p2/registers/{body['upload_id']}/reconcile")
        self.assertEqual(reconciled.status_code, 200, reconciled.text)
        bad = self.request("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": b64(b"<ENVELOPE/>"), "source_format": "tally_xml"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("Tally import", bad.json()["detail"])

    def test_pdf_bank_statement_feeds_the_same_rows(self):
        response = self.request("POST", "/p6/bank-statements", "client", json={"period": "FY26", "source_base64": b64(fx.bank_statement_pdf())})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["row_count"], body["source_format"], body["unread_lines"], body["independently_verified"]), (4, "pdf", 0, False))
        scanned = self.request("POST", "/p6/bank-statements", "client", json={"period": "FY26", "source_base64": b64(fx.bank_statement_pdf(with_header=False))})
        self.assertEqual(scanned.status_code, 422)

    def test_invoice_pdf_is_read_on_arrival_and_compared_for_auditors_only(self):
        run_id = self.data["run_id"]
        requests = self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests").json()["requests"]
        snapshot = {i["invoice_id"]: i for i in json.loads(self._snapshot(run_id))["invoices"]}
        open_requests = [r for r in requests if "invoice" in r["required_docs"] and r["sample_ref"] in snapshot][:2]
        self.assertEqual(len(open_requests), 2)
        results = []
        for req, offset in zip(open_requests, (0, 100)):
            inv = snapshot[req["sample_ref"]]
            pdf = fx.invoice_pdf(inv["bill_no"], date.fromisoformat(inv["invoice_date"]), inv["customer_name"], inv.get("gstin") or "",
                                 f"{(inv['gross_cents'] + offset * 100) / 100:.2f}")
            upload = self.request("POST", f"/p3/evidence-requests/{req['request_id']}/evidence", "client",
                                  json={"evidence_id": "EV-" + uuid.uuid4().hex, "document_type": "invoice", "content_base64": b64(pdf),
                                        "content_type": "application/pdf", "controller": "company", "acquisition_channel": "company_upload"})
            self.assertEqual(upload.status_code, 200, upload.text)
            read = upload.json()["document_read"]
            self.assertEqual(read["invoice_number"], inv["bill_no"])
            self.assertNotIn("document_comparison", upload.json())  # the client sees what was read, not the audit comparison
            results.append(req["sample_ref"])
        listed = {r["sample_ref"]: r for r in self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests").json()["requests"]}
        statuses = [next(e for e in listed[ref]["evidence"] if e["document_type"] == "invoice")["document_comparison"]["status"] for ref in results]
        self.assertEqual(statuses, ["matches", "differs"])
        client_view = self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests", "client")
        if client_view.status_code == 200:
            ev = next(e for e in {r["sample_ref"]: r for r in client_view.json()["requests"]}[results[0]]["evidence"] if e["document_type"] == "invoice")
            self.assertIn("document_read", ev)
            self.assertNotIn("document_comparison", ev)

    def _snapshot(self, run_id):
        import sqlite3
        with sqlite3.connect(p1.DB_PATH) as db:
            return db.execute("SELECT snapshot_json FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()[0]
