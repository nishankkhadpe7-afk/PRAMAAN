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
                                           "Gross Amt": "118000.00", "GST No": "27AAAPS1234C1Z7"})
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


    def test_a_declaration_hidden_deep_in_the_file_is_still_refused(self):
        padded = fx.tally_xml().replace(b"<BODY>", b"<BODY>" + b" " * 10000 + b"<!DOCTYPE x [<!ENTITY a 'b'>]>", 1)
        with self.assertRaisesRegex(di.DocumentReadError, "DOCTYPE"):
            di.parse_tally_sales(padded)
        with self.assertRaisesRegex(di.DocumentReadError, "DOCTYPE"):
            di.parse_tally_sales(fx.tally_xml(utf16=True).replace("<BODY>".encode("utf-16-le"), ("<BODY>" + " " * 5000 + "<!ENTITY a 'b'>").encode("utf-16-le")))

    def test_malformed_sales_are_rejected_not_skipped_and_doubtful_ones_warned(self):
        sales = list(fx.SALES) + [("TLY/25-26/001", fx.date(2025, 7, 1), "Repeat Buyer (synthetic)", "27AAAPS1234C1Z5", "1180.00")]
        xml = fx.tally_xml(sales)
        xml = xml.replace(b"<DATE>20250503</DATE>", b"<DATE>2025-05-03</DATE>")          # unreadable date on voucher 002
        xml = xml.replace(b"<AMOUNT>-236000.00</AMOUNT>", b"<AMOUNT>-236100.00</AMOUNT>")  # voucher 003 no longer balances
        read = di.parse_tally_sales(xml)
        self.assertEqual([r["Bill No"] for r in read["rows"]], ["TLY/25-26/001", "TLY/25-26/003", "TLY/25-26/001"])
        self.assertEqual([(r["voucher"], r["reason"].split(" ")[0]) for r in read["rejected"]], [("TLY/25-26/002", "unreadable")])
        self.assertEqual(len(read["skipped"]), 2)
        reasons = " | ".join(f"{w['voucher']}: {w['reason']}" for w in read["warnings"])
        self.assertIn("TLY/25-26/003: ledger entries do not balance (difference -100.00)", reasons)
        self.assertIn("check digit does not match", reasons)
        self.assertIn("voucher number repeats", reasons)

    def test_gstin_check_digit(self):
        self.assertIsNone(di.gstin_check("27AAPFU0939F1ZV"))
        self.assertIn("check digit", di.gstin_check("27AAPFU0939F1ZA"))
        self.assertIn("format", di.gstin_check("27AAPFU0939"))


class BankPdfParserTests(unittest.TestCase):
    def test_wrapped_narration_value_dates_and_overdrawn_balances(self):
        rows = list(fx.BANK_ROWS) + [(fx.date(2025, 6, 9), "Loan EMI", "EMI0001234", "4,00,000.00", None)]
        read = di.parse_bank_pdf(fx.bank_statement_pdf(rows=rows, wrap={0: "INV TLY/25-26/001 PART PAYMENT"}, value_dates=True, dr_suffix=True))
        self.assertEqual(len(read["rows"]), 5)
        self.assertEqual(read["unread_lines"], [])
        first = read["rows"][0]
        self.assertTrue(first["narration"].endswith("INV TLY/25-26/001 PART PAYMENT"))
        self.assertEqual((first["value_date"], first["reference"]), ("2025-04-14", "N104250001234"))
        self.assertEqual(read["rows"][-1]["balance_cents"], -2625050)  # '26,250.50 Dr' is an overdraft
        self.assertEqual(di.check_balances(read["rows"], read["opening_balance_cents"])["status"], "consistent")

    def test_a_wrong_printed_balance_is_reported_not_corrected(self):
        read = di.parse_bank_pdf(fx.bank_statement_pdf(tamper_balance=1))
        check = di.check_balances(read["rows"], read["opening_balance_cents"])
        self.assertEqual(check["status"], "inconsistent")
        self.assertEqual(check["mismatches"], [{"row_no": 2, "expected": "323000.00", "printed": "324000.00"}])  # row 3 is right again
        self.assertEqual(read["rows"][1]["amount_cents"], 4500000)  # the transaction itself is unchanged
        # A transaction missing from the statement breaks the chain once; later rows line up again.
        clean = di.parse_bank_pdf(fx.bank_statement_pdf())
        missing = di.check_balances([r for r in clean["rows"] if r["row_no"] != 2], clean["opening_balance_cents"])
        self.assertEqual([m["row_no"] for m in missing["mismatches"]], [3])

    def test_newest_first_statements_and_repeated_rows(self):
        read = di.parse_bank_pdf(fx.bank_statement_pdf())
        newest_first = list(reversed(read["rows"]))
        self.assertEqual(di.check_balances(newest_first)["status"], "consistent")
        self.assertEqual(di.check_balances([])["status"], "not_available")
        twice = read["rows"] + [{**read["rows"][0], "row_no": 5}]
        self.assertEqual(di.duplicate_rows(twice), [{"row_no": 5, "same_as_row": 1}])


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

    def test_gst_components_round_off_and_arithmetic(self):
        bill, when, buyer, gstin, total = fx.SALES[0]
        read = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total, tax="cgst_sgst", round_off="0.40"))
        self.assertEqual((read["cgst_cents"], read["sgst_cents"], read["igst_cents"], read["round_off_cents"]), (899997, 899997, None, 40))
        self.assertEqual(read["arithmetic"]["status"], "consistent")
        self.assertEqual(read["pages"]["total_cents"], 1)
        both = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total, tax="both"))
        self.assertEqual(both["arithmetic"]["status"], "inconsistent")
        self.assertIn("IGST and CGST/SGST", both["warnings"][0])
        books = {"bill_no": bill, "invoice_date": "2025-04-12", "gross_cents": 11800000, "gstin": gstin, "net_cents": 10000000, "tax_cents": 1800000}
        fields = {f["field"]: f["result"] for f in di.compare_invoice(read, books)["fields"]}
        self.assertEqual(fields["taxable_value"], "differs")  # 99,999.66 printed vs 1,00,000.00 in the books

    def test_conflicting_values_are_ambiguous_and_left_unread(self):
        bill, when, buyer, gstin, total = fx.SALES[0]
        read = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total, extra_lines=("Invoice No: TLY/25-26/777",)))
        self.assertIsNone(read["invoice_number"])
        self.assertEqual(read["ambiguous"]["invoice_number"], ["TLY/25-26/001", "TLY/25-26/777"])
        books = {"bill_no": bill, "invoice_date": "2025-04-12", "gross_cents": 11800000, "gstin": gstin}
        compared = di.compare_invoice(read, books)
        self.assertEqual(compared["status"], "incomplete")
        self.assertEqual(next(f for f in compared["fields"] if f["field"] == "invoice_number")["result"], "ambiguous")
        two_pages = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total, second_page=("Grand Total Rs. 1,00,000.00",)))
        self.assertIsNone(two_pages["total_cents"])
        self.assertEqual((two_pages["page_count"], two_pages["arithmetic"]["status"]), (2, "not_checked"))

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
        self.assertEqual(body["balance_check"]["status"], "consistent")
        scanned = self.request("POST", "/p6/bank-statements", "client", json={"period": "FY26", "source_base64": b64(fx.bank_statement_pdf(with_header=False))})
        self.assertEqual(scanned.status_code, 422)

    def test_the_same_statement_twice_is_refused_and_overlaps_are_counted_once(self):
        from Pramaan.backend import p6_agent
        rows = [(fx.date(2024, 1, 5), "NEFT CR OVERLAP TEST", "OVLP00000001", None, "7,777.00"), (fx.date(2024, 1, 9), "Bank charges", "CHG000000009", "10.00", None)]
        first = fx.bank_statement_pdf(rows=rows)
        self.assertEqual(self.request("POST", "/p6/bank-statements", "client", json={"period": "JAN24", "source_base64": b64(first)}).status_code, 200)
        again = self.request("POST", "/p6/bank-statements", "client", json={"period": "JAN24", "source_base64": b64(first)})
        self.assertEqual(again.status_code, 409)
        self.assertIn("already imported", again.json()["detail"])
        # A different file (here: the quarterly CSV) that repeats the same receipt is accepted, reported, and counted once.
        csv_text = "date,amount,direction,narration,reference,counterparty,balance\n2024-01-05,7777.00,credit,NEFT CR OVERLAP TEST,OVLP00000001,,\n2024-02-01,5.00,credit,Interest,INT0000002,,\n"
        overlap = self.request("POST", "/p6/bank-statements", "client", json={"period": "Q4", "source_base64": b64(csv_text.encode())})
        self.assertEqual(overlap.status_code, 200, overlap.text)
        self.assertEqual(overlap.json()["overlapping_rows"], 1)
        db = p3.db_open()
        try:
            counted = [r for r in p6_agent._bank_rows(db) if r["reference"] == "OVLP00000001"]
        finally:
            db.close()
        self.assertEqual(len(counted), 1)

    def test_tally_report_separates_rejected_and_warnings(self):
        xml = fx.tally_xml().replace(b"<DATE>20250503</DATE>", b"<DATE>bad</DATE>").replace(b"27AAAPS1234C1Z7", b"27AAAPS1234C1Z5")
        body = self.request("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": b64(xml), "source_format": "tally_xml"}).json()
        self.assertEqual((body["row_count"], body["skipped_vouchers"], body["rejected_vouchers"], body["warning_count"]), (2, 2, 1, 1))

    def test_a_reader_crash_never_loses_the_upload(self):
        run_id = self.data["run_id"]
        snapshot = {i["invoice_id"]: i for i in json.loads(self._snapshot(run_id))["invoices"]}
        requests = self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests").json()["requests"]
        req = [r for r in requests if "invoice" in r["required_docs"] and "invoice" not in r["uploaded_docs"] and r["sample_ref"] in snapshot][-1]
        with patch.object(di, "read_invoice_pdf", side_effect=RuntimeError("boom")):
            upload = self.request("POST", f"/p3/evidence-requests/{req['request_id']}/evidence", "client",
                                  json={"evidence_id": "EV-" + uuid.uuid4().hex, "document_type": "invoice", "content_base64": b64(b"%PDF-1.4 broken"),
                                        "content_type": "application/pdf", "controller": "company", "acquisition_channel": "company_upload"})
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(upload.json()["document_read"]["error"], "the PDF could not be read (RuntimeError)")

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
                                 f"{(inv['gross_cents'] + offset * 100) / 100:.2f}", tax="none" if not inv.get("tax_cents") else "igst")
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
