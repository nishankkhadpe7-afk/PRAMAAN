"""P2/P3 document pipeline: Amount + Dr/Cr statements, OCR, field quality, document versions,
human field verification, statement continuity, traceability, concurrency and the Tally connector.
All documents are synthetic (backend/fixtures_documents.py)."""
import base64
import http.server
import json
import os
import sqlite3
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, document_import as di, fixtures_documents as fx, ocr, p3, security, tally_connector
from Pramaan.backend.evaluate_agent import build_instance

HAS_TESSERACT = ocr.tesseract_path() is not None


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def directions(read):
    return [(r["direction"], r["amount_cents"]) for r in read["rows"]]


EXPECTED = [("credit", 11800000), ("debit", 4500000), ("credit", 5900000), ("debit", 825050)]


class AmountDrCrLayoutTests(unittest.TestCase):
    def test_every_single_amount_style_reads_the_same_transactions(self):
        for style in fx.AMOUNT_STYLES:
            with self.subTest(style=style):
                read = di.parse_bank_pdf(fx.bank_amount_pdf(style=style, balance_drcr=style == "suffix"))
                self.assertEqual(read["layout"], "amount")
                self.assertEqual(directions(read), EXPECTED)
                self.assertEqual(read["unread_lines"], [])
                self.assertEqual(di.check_balances(read["rows"], read["opening_balance_cents"])["status"], "consistent")
        signed = di.parse_bank_pdf(fx.bank_amount_pdf(style="signed"))
        self.assertEqual([r["direction_source"] for r in signed["rows"]], ["balance", "sign", "balance", "sign"])

    def test_column_order_does_not_matter(self):
        for order in [("amount", "ind", "ref", "bal"), ("bal", "ind", "amount", "ref"), ("ind", "amount", "bal", "ref")]:
            with self.subTest(order=order):
                read = di.parse_bank_pdf(fx.bank_amount_pdf(style="indicator", order=order))
                self.assertEqual(directions(read), EXPECTED)
                self.assertEqual(read["rows"][1]["reference"], "CHQ000451")

    def test_newest_first_and_overdrawn_balances(self):
        rows = list(fx.BANK_ROWS) + [(date(2025, 6, 9), "Loan EMI", "EMI0001234", "4,00,000.00", None)]
        read = di.parse_bank_pdf(fx.bank_amount_pdf(rows=rows, style="suffix", newest_first=True, balance_drcr=True))
        self.assertEqual(directions(read), list(reversed(EXPECTED + [("debit", 40000000)])))
        self.assertEqual(read["rows"][0]["balance_cents"], -2625050)
        self.assertEqual(di.check_balances(read["rows"])["status"], "consistent")

    def test_unprovable_rows_are_unread_and_unprovable_layouts_refused(self):
        # Newest first, no opening balance: the oldest unmarked row has nothing to prove its direction.
        read = di.parse_bank_pdf(fx.bank_amount_pdf(style="balance_only", newest_first=True))
        self.assertEqual(len(read["rows"]), 3)
        self.assertIn("running balance does not show the direction", read["unread_lines"][0]["reason"])
        with self.assertRaises(di.DocumentReadError):  # Amount column with no Dr/Cr, sign or balance at all
            di.parse_bank_pdf(fx.bank_amount_pdf(style="balance_only", order=("ref", "amount")))

    def test_a_negative_amount_marked_cr_is_a_contradiction(self):
        pdf = fx.bank_amount_pdf(style="indicator")
        import pymupdf
        doc = pymupdf.open(stream=pdf, filetype="pdf")
        page = doc[0]
        hit = page.search_for("45,000.00")[0]
        page.add_redact_annot(hit, text="-45,000.00", fontsize=9, align=2)
        page.apply_redactions()
        for rect in page.search_for("Dr"):
            if abs(rect.y0 - hit.y0) < 3:
                page.add_redact_annot(rect, text="Cr", fontsize=9)
        page.apply_redactions()
        read = di.parse_bank_pdf(doc.tobytes())
        self.assertEqual(len(read["rows"]), 3)
        self.assertIn("negative but marked Cr", read["unread_lines"][0]["reason"])

    def test_multi_page_statement_keeps_page_and_line(self):
        rows = fx.many_rows(95)
        read = di.parse_bank_pdf(fx.bank_amount_pdf(rows=rows, style="suffix", rows_per_page=40))
        self.assertEqual(len(read["rows"]), 95)
        self.assertEqual(sorted({r["page"] for r in read["rows"]}), [1, 2, 3])
        self.assertTrue(all(r["line"] > 0 for r in read["rows"]))
        self.assertEqual(di.check_balances(read["rows"], read["opening_balance_cents"])["status"], "consistent")


class NormalisationTests(unittest.TestCase):
    def test_amounts(self):
        cases = {"1,18,000.00": 11800000, "₹ 4,500": 450000, "1,000/-": 100000, "Rs.250.5": 25050, "1,00,0.00": None, "12-04-2025": None}
        for text, cents in cases.items():
            with self.subTest(text=text):
                self.assertEqual(di.parse_amount_cents(text) if text != "12-04-2025" else (None if not di._is_amount(text) else 1), cents)
        self.assertEqual([di.parse_signed_cents(t) for t in ("(250.00)", "250.00 Dr", "250.00-", "−250.00", "250.00 Cr")], [-25000, -25000, -25000, -25000, 25000])

    def test_dates(self):
        cases = {"12-Apr-2025": "2025-04-12", "12 Sept 2025": "2025-09-12", "12.04.25": "2025-04-12", "2025/04/12": "2025-04-12",
                 "12–04–2025": "2025-04-12", "12 April, 2025": "2025-04-12", "31/02/2025": None, "12/04/1890": None}
        for text, iso in cases.items():
            with self.subTest(text=text):
                self.assertEqual(di.parse_date(text), iso)

    def test_csv_with_bank_header_names_and_drcr_column(self):
        from Pramaan.backend.p6_agent import parse_bank_csv
        csv_text = ("Txn Date,Particulars,Ref No,Amount,Dr/Cr,Closing Balance\n"
                    "14-04-2025,NEFT CR SHARMA,N104250001234,118000.00,Cr,\"3,68,000.00 Cr\"\n"
                    "18-04-2025,Rent,CHQ000451,45000.00,Dr,\"3,23,000.00\"\n")
        rows = parse_bank_csv(csv_text.encode())
        self.assertEqual([(r["txn_date"], r["direction"], r["balance_cents"]) for r in rows], [("2025-04-14", "credit", 36800000), ("2025-04-18", "debit", 32300000)])
        with self.assertRaisesRegex(ValueError, "direction"):
            parse_bank_csv(csv_text.replace(",Cr,", ",?,").encode())


class SplitColumnCsvTests(unittest.TestCase):
    """Layout of a real net-banking export (Kaggle 'MyTransaction.csv'): Withdrawal/Deposit columns, a repeated
    Date column (value date), Category as description, Excel-damaged references, mixed date styles, blank rows."""
    SAMPLE = ("Date,Category,RefNo,Date,Withdrawal,Deposit,Balance\n,,,,,,\n"
              "1/1/2023,Rent,3.00E+11,1/1/2023,3950,0,1837.23\n"
              "13/01/23,Food,3.00E+11,13/01/23,56,0,1781.23\n"
              "13/01/23,Food,3.00E+11,13/01/23,56,0,1725.23\n"
              "13/01/23,Misc,REF1234567,14/01/23,0,55,1780.23\n")

    def test_split_columns_value_dates_and_damaged_references(self):
        from Pramaan.backend.p6_agent import parse_bank_csv
        report = {}
        rows = parse_bank_csv(self.SAMPLE.encode(), report)
        self.assertEqual([(r["txn_date"], r["direction"], r["amount_cents"]) for r in rows],
                         [("2023-01-01", "debit", 395000), ("2023-01-13", "debit", 5600), ("2023-01-13", "debit", 5600), ("2023-01-13", "credit", 5500)])
        self.assertEqual(report, {"layout": "split", "references_damaged_by_excel": 3})
        self.assertEqual([r["reference"] for r in rows], ["", "", "", "REF1234567"])
        self.assertEqual(rows[3]["value_date"], "2023-01-14")
        self.assertEqual(rows[0]["narration"], "Rent")
        self.assertEqual(di.check_balances(rows)["status"], "consistent")
        # Two same-day Food 56 payments move the balance, so they are two payments, not a repeated line.
        self.assertEqual(di.duplicate_rows(rows), [])
        self.assertEqual(di.duplicate_rows(rows + [{**rows[1], "row_no": 5}]), [{"row_no": 5, "same_as_row": 2}])

    def test_a_row_with_both_or_neither_amount_is_refused(self):
        from Pramaan.backend.p6_agent import parse_bank_csv
        with self.assertRaisesRegex(ValueError, "exactly one of Withdrawal or Deposit"):
            parse_bank_csv(self.SAMPLE.replace("3950,0,", "3950,10,").encode())
        with self.assertRaisesRegex(ValueError, "exactly one of Withdrawal or Deposit"):
            parse_bank_csv(self.SAMPLE.replace("3950,0,", "0,0,").encode())


@unittest.skipUnless(HAS_TESSERACT, "Tesseract is not installed; OCR tests need it (apt install tesseract-ocr)")
class OcrTests(unittest.TestCase):
    def test_scanned_statement_is_read_and_marked_as_ocr(self):
        read = di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf()))
        self.assertEqual(read["extraction"], "ocr")
        self.assertEqual(read["ocr"]["engine"], "tesseract")
        self.assertEqual(directions(read), EXPECTED)
        self.assertTrue(all(r["extraction"] == "ocr" for r in read["rows"]))
        self.assertEqual(di.check_balances(read["rows"], read["opening_balance_cents"])["status"], "consistent")

    def test_scanned_invoice_fields_are_ocr_and_need_review(self):
        bill, when, buyer, gstin, total = fx.SALES[0]
        read = di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(bill, when, buyer, gstin, total, tax="cgst_sgst")))
        self.assertEqual((read["invoice_number"], read["total_cents"], read["extraction"]), (bill, 11800000, "ocr"))
        quality = di.field_quality(read)
        self.assertEqual(quality["total_cents"]["state"], "ocr")
        books = {"bill_no": bill, "invoice_date": "2025-04-12", "gross_cents": 11800000, "gstin": None}
        self.assertEqual(di.compare_invoice(read, books)["status"], "needs_review")
        verified = {"total_cents": {"value": 11800000, "verified_by": "reviewer", "verified_at": "now", "note": "checked"},
                    "invoice_number": {"value": bill, "verified_by": "reviewer", "verified_at": "now", "note": "checked"},
                    "invoice_date": {"value": "2025-04-12", "verified_by": "reviewer", "verified_at": "now", "note": "checked"}}
        self.assertEqual(di.compare_invoice(read, books, verified)["status"], "matches")

    def test_low_confidence_words_are_never_imported(self):
        with patch.object(ocr, "MIN_CONFIDENCE", 101):
            with self.assertRaises(di.DocumentReadError):
                di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf()))

    def test_limits(self):
        with patch.object(ocr, "MAX_OCR_PAGES", 0), self.assertRaisesRegex(di.DocumentReadError, "up to 0 pages"):
            di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf()))
        import subprocess
        with patch.object(ocr.subprocess, "run", side_effect=subprocess.TimeoutExpired("tesseract", 1)), self.assertRaisesRegex(di.DocumentReadError, "longer than"):
            di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))


    def test_a_poor_scan_never_yields_a_match_or_a_verified_field(self):
        bill, when, buyer, gstin, total = fx.SALES[0]
        read = di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(bill, when, buyer, gstin, total), dpi=60))
        states = {v["state"] for v in di.field_quality(read).values()}
        self.assertFalse(states & {"exact", "validated", "human_verified"})
        self.assertIsNone(read["total_cents"])  # Tesseract's low-confidence reading of the total is set aside
        books = {"bill_no": bill, "invoice_date": "2025-04-12", "gross_cents": 11800000, "gstin": gstin}
        self.assertNotIn(di.compare_invoice(read, books)["status"], ("matches", "needs_review"))
        with self.assertRaises(di.DocumentReadError):
            di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf(), dpi=45))

    def test_the_real_engine_is_stopped_at_the_time_limit(self):
        with patch.object(ocr, "PAGE_TIMEOUT_SECONDS", 0.001), self.assertRaisesRegex(di.DocumentReadError, "longer than"):
            di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))

    def test_engine_version_and_languages_are_reported(self):
        self.assertIn("tesseract", ocr.engine_version().lower())
        self.assertIn("eng", ocr.languages())
        read = di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))
        self.assertEqual((read["ocr"]["language"], read["ocr"]["pages"]), ("eng", [1]))

    def test_installation_self_check_passes(self):
        from Pramaan.backend import ocr_check
        ocr_check.results.clear()
        self.assertEqual(ocr_check.main(), 0, [r for r in ocr_check.results if not r[1]])


class OcrConfigurationTests(unittest.TestCase):
    def test_quoted_and_wrong_paths(self):
        real = ocr.tesseract_path() or os.path.abspath(__file__)  # any existing file stands in when Tesseract is absent
        with patch.dict(os.environ, {"PRAMAAN_TESSERACT": f'  "{real}"  ', "PRAMAAN_OCR": ""}):
            self.assertEqual(ocr.tesseract_path(), real)
        with patch.dict(os.environ, {"PRAMAAN_TESSERACT": r"C:\Missing\tesseract.exe", "PRAMAAN_OCR": ""}):
            self.assertIsNone(ocr.tesseract_path())
            self.assertIn("no file exists there", ocr.unavailable_reason())
            with self.assertRaisesRegex(di.DocumentReadError, "no file exists there"):
                di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))

    @unittest.skipUnless(HAS_TESSERACT, "needs Tesseract")
    def test_missing_english_data_is_explained(self):
        with patch.object(ocr, "languages", return_value={"deu", "osd"}), self.assertRaisesRegex(di.DocumentReadError, "eng.traineddata"):
            di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))


class OcrUnavailableTests(unittest.TestCase):
    def test_without_ocr_a_scan_is_refused_with_a_clear_message(self):
        with patch.dict(os.environ, {"PRAMAAN_OCR": "off"}):
            with self.assertRaisesRegex(di.DocumentReadError, "OCR is (not installed|switched off)"):
                di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf()))
            with self.assertRaisesRegex(di.DocumentReadError, "OCR is (not installed|switched off)"):
                di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))

    def test_malformed_pdfs(self):
        for bad in (b"%PDF-1.7\n" + os.urandom(2000), fx.bank_statement_pdf()[:300], b"%PDF"):
            with self.assertRaises(di.DocumentReadError):
                di.parse_bank_pdf(bad)
        with patch.object(di, "MAX_PDF_PAGES", 0), self.assertRaisesRegex(di.DocumentReadError, "more than 0 pages"):
            di.read_invoice_pdf(fx.invoice_pdf(*fx.SALES[0]))


class FieldQualityTests(unittest.TestCase):
    def test_states_follow_fixed_rules(self):
        bill, when, buyer, gstin, total = fx.SALES[0]
        read = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total))
        q = di.field_quality(read)
        self.assertEqual((q["total_cents"]["state"], q["gstins"]["state"], q["invoice_number"]["state"], q["round_off_cents"]["state"]),
                         ("validated", "validated", "exact", "unreadable"))
        self.assertEqual(q["invoice_number"]["evidence"]["page"], 1)
        ambiguous = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total, extra_lines=("Invoice No: TLY/25-26/777",)))
        self.assertEqual(di.field_quality(ambiguous)["invoice_number"]["state"], "ambiguous")
        broken = di.read_invoice_pdf(fx.invoice_pdf(bill, when, buyer, gstin, total, tax="both"))
        self.assertEqual(di.field_quality(broken)["total_cents"]["state"], "exact")  # arithmetic fails, so not 'validated'
        human = di.field_quality(ambiguous, {"invoice_number": {"value": bill, "verified_by": "r", "verified_at": "t", "note": "n"}})
        self.assertEqual(human["invoice_number"]["state"], "human_verified")
        self.assertEqual(set(di.FIELD_STATES), {"exact", "validated", "ocr", "ambiguous", "unreadable", "human_verified"})

    def test_reviewer_values_are_normalised_and_checked(self):
        self.assertEqual(di.parse_verified_value("total_cents", "1,18,000.00"), 11800000)
        self.assertEqual(di.parse_verified_value("invoice_date", "12-04-2025"), "2025-04-12")
        with self.assertRaises(ValueError):
            di.parse_verified_value("gstins", "27AAPFU0939F1ZA")
        with self.assertRaises(ValueError):
            di.parse_verified_value("unknown", "x")


class TallyConnectorTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                outer.received.append(self.rfile.read(int(self.headers["Content-Length"])))
                body = outer.reply
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_daybook_request_and_validated_reply(self):
        self.reply = fx.tally_xml()
        body, report = tally_connector.fetch_daybook(self.url, date(2025, 4, 1), date(2026, 3, 31), "Fictional & Co")
        self.assertEqual(body, self.reply)
        self.assertEqual(len(report["rows"]), 3)
        sent = self.received[0].decode()
        self.assertIn("<ID>Day Book</ID>", sent)
        self.assertIn("<SVFROMDATE>20250401</SVFROMDATE><SVTODATE>20260331</SVTODATE>", sent)
        self.assertIn("<SVCURRENTCOMPANY>Fictional &amp; Co</SVCURRENTCOMPANY>", sent)

    def test_errors_are_explained(self):
        self.reply = b"<ENVELOPE><LINEERROR>Could not find Company</LINEERROR></ENVELOPE>"
        with self.assertRaisesRegex(tally_connector.TallyConnectionError, "Could not find Company"):
            tally_connector.fetch_daybook(self.url, date(2025, 4, 1), date(2025, 4, 30))
        self.reply = b"<html>not tally</html>"
        with self.assertRaisesRegex(tally_connector.TallyConnectionError, "not with a usable Day Book"):
            tally_connector.fetch_daybook(self.url, date(2025, 4, 1), date(2025, 4, 30))
        with self.assertRaisesRegex(tally_connector.TallyConnectionError, "look like"):
            tally_connector.fetch_daybook("file:///etc/passwd", date(2025, 4, 1), date(2025, 4, 30))
        with self.assertRaisesRegex(tally_connector.TallyConnectionError, "could not reach"):
            tally_connector.fetch_daybook("http://127.0.0.1:9", date(2025, 4, 1), date(2025, 4, 30))


class PipelineApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent / ".runtime" / ("pipe-" + uuid.uuid4().hex)
        cls.root.mkdir(parents=True)
        cls.patches = [patch.object(p1, "ROOT", cls.root), patch.object(p1, "DB_PATH", cls.root / "p1.sqlite3"),
                       patch.object(p1, "VAULT", cls.root / "vault"), patch.dict("os.environ", {"PRAMAAN_DATA": str(cls.root)})]
        for item in cls.patches:
            item.start()
        cls.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("auditor", "auditor"),
                      "human": security.issue("reviewer", "auditor", human=True)}
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

    def _db(self):
        db = sqlite3.connect(p1.DB_PATH)
        db.row_factory = sqlite3.Row
        return db

    def _upload_invoice(self, run_id, offset=0, tax="none"):
        requests = self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests").json()["requests"]
        with self._db() as db:
            snap = {i["invoice_id"]: i for i in json.loads(db.execute("SELECT snapshot_json FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()[0])["invoices"]}
        req = next(r for r in requests if "invoice" in r["required_docs"] and "invoice" not in r["uploaded_docs"] and r["sample_ref"] in snap and r["sample_ref"] not in self.used)
        self.used.add(req["sample_ref"])
        inv = snap[req["sample_ref"]]
        pdf = lambda off: fx.invoice_pdf(inv["bill_no"], date.fromisoformat(inv["invoice_date"]), inv["customer_name"], "", f"{(inv['gross_cents'] + off * 100) / 100:.2f}", tax=tax)  # noqa: E731
        evidence_id = "EV-" + uuid.uuid4().hex
        response = self.request("POST", f"/p3/evidence-requests/{req['request_id']}/evidence", "client",
                                json={"evidence_id": evidence_id, "document_type": "invoice", "content_base64": b64(pdf(offset)),
                                      "content_type": "application/pdf", "controller": "company", "acquisition_channel": "company_upload"})
        self.assertEqual(response.status_code, 200, response.text)
        return req, inv, evidence_id, pdf

    used: set = set()

    def test_replacement_keeps_history_and_frozen_runs_reproduce(self):
        run_id = self.data["run_id"]
        req, inv, old_id, pdf = self._upload_invoice(run_id, offset=500)  # wrong total uploaded first
        frozen = self.request("POST", "/p3/audit-runs", json={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "replacement-seed"}).json()
        with self._db() as db:
            before = db.execute("SELECT snapshot_hash, result_json FROM p3_audit_runs WHERE run_id=?", (frozen["run_id"],)).fetchone()
            old_row = dict(db.execute("SELECT * FROM p3_evidence WHERE evidence_id=?", (old_id,)).fetchone())
        new_id = "EV-" + uuid.uuid4().hex
        corrected = pdf(0)
        replaced = self.request("POST", f"/p3/evidence/{old_id}/replace", "client",
                                json={"new_evidence_id": new_id, "content_base64": b64(corrected), "content_type": "application/pdf", "reason": "uploaded the draft by mistake"})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        body = replaced.json()
        self.assertEqual((body["version"], body["replaces_evidence_id"], body["previous_sha256"], body["replaced_by"]), (2, old_id, old_row["sha256"], "employee"))
        with self._db() as db:
            self.assertEqual(dict(db.execute("SELECT * FROM p3_evidence WHERE evidence_id=?", (old_id,)).fetchone()), old_row)  # original untouched
            self.assertTrue((p1.VAULT / old_row["sha256"]).is_file())
            after = db.execute("SELECT snapshot_hash, result_json FROM p3_audit_runs WHERE run_id=?", (frozen["run_id"],)).fetchone()
            event = db.execute("SELECT report_json, report_hash, entry_hash FROM import_reports WHERE action='evidence_replaced' ORDER BY report_id DESC LIMIT 1").fetchone()
            logged = json.loads(db.execute("SELECT event_json FROM events WHERE entry_hash=?", (event["entry_hash"],)).fetchone()[0])
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM p3_evidence_versions")
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(json.loads(event["report_json"])["reason"], "uploaded the draft by mistake")
        self.assertEqual(logged["payload_hash"], event["report_hash"])  # the stored report is the one in the hash chain
        self.assertTrue(self.request("POST", f"/p3/audit-runs/{frozen['run_id']}/reproduce").json()["identical"])
        self.assertTrue(self.request("GET", "/verify-log").json().get("valid", True))
        # Old versions cannot be replaced again; identical files are refused.
        self.assertEqual(self.request("POST", f"/p3/evidence/{old_id}/replace", "client", json={"new_evidence_id": "EV-x" + uuid.uuid4().hex, "content_base64": b64(pdf(1)), "reason": "again please"}).status_code, 409)
        self.assertEqual(self.request("POST", f"/p3/evidence/{new_id}/replace", "client", json={"new_evidence_id": "EV-y" + uuid.uuid4().hex, "content_base64": b64(corrected), "reason": "same file"}).status_code, 422)
        self.assertEqual(self.request("POST", f"/p3/evidence/{new_id}/replace", "auditor", json={"new_evidence_id": "EV-z" + uuid.uuid4().hex, "content_base64": b64(pdf(2)), "reason": "auditor cannot"}).status_code, 403)
        # A new run sees only the current version; the listing shows the chain.
        rerun = self.request("POST", "/p3/audit-runs", json={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "replacement-seed-2"}).json()
        with self._db() as db:
            snap = json.loads(db.execute("SELECT snapshot_json FROM p3_audit_runs WHERE run_id=?", (rerun["run_id"],)).fetchone()[0])
        ids = {e["evidence_id"] for e in snap["p3_evidence"]}
        self.assertIn(new_id, ids)
        self.assertNotIn(old_id, ids)
        self.assertEqual(next(v for v in snap["p3_evidence_versions"] if v["new_evidence_id"] == new_id)["replaces_evidence_id"], old_id)
        listed = {r["sample_ref"]: r for r in self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests").json()["requests"]}[req["sample_ref"]]["evidence"]
        by_id = {e["evidence_id"]: e for e in listed}
        self.assertEqual((by_id[old_id]["superseded_by"], by_id[old_id]["current"], by_id[new_id]["version"]), (new_id, False, 2))
        fields = {f["field"]: f for f in by_id[new_id]["document_comparison"]["fields"]}
        self.assertEqual({k: fields[k]["result"] for k in ("invoice_number", "invoice_date", "total")}, dict.fromkeys(("invoice_number", "invoice_date", "total"), "match"))
        self.assertIn("register_amount", fields)  # cross-document check against the sales register row for the bill
        old_fields = {f["field"]: f["result"] for f in by_id[old_id]["document_comparison"]["fields"]}
        self.assertEqual(old_fields["total"], "differs")

    def test_concurrent_replacements_and_statement_uploads_admit_one(self):
        run_id = self.data["run_id"]
        _, _, old_id, pdf = self._upload_invoice(run_id)

        def replace(n):
            return self.request("POST", f"/p3/evidence/{old_id}/replace", "client",
                                json={"new_evidence_id": f"EV-c{n}-" + uuid.uuid4().hex, "content_base64": b64(pdf(10 + n)), "reason": "concurrent fix"}).status_code
        with ThreadPoolExecutor(4) as pool:
            codes = sorted(pool.map(replace, range(4)))
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(set(codes) - {200}, {409})
        statement = fx.bank_amount_pdf(rows=fx.many_rows(12, date(2023, 1, 2)), style="indicator")

        def upload(_):
            return self.request("POST", "/p6/bank-statements", "client", json={"period": "CONC", "source_base64": b64(statement)}).status_code
        with ThreadPoolExecutor(4) as pool:
            codes = sorted(pool.map(upload, range(4)))
        self.assertEqual(codes, [200, 409, 409, 409])

    def test_field_verification_is_human_only_and_changes_quality(self):
        run_id = self.data["run_id"]
        req, inv, evidence_id, _ = self._upload_invoice(run_id)
        payload = {"field": "invoice_number", "value": inv["bill_no"], "note": "checked against the paper copy"}
        self.assertEqual(self.request("POST", f"/p3/evidence/{evidence_id}/field-verifications", "auditor", json=payload).status_code, 403)
        self.assertEqual(self.request("POST", f"/p3/evidence/{evidence_id}/field-verifications", "client", json=payload).status_code, 403)
        self.assertEqual(self.request("POST", f"/p3/evidence/{evidence_id}/field-verifications", "human", json={**payload, "field": "total_cents", "value": "abc"}).status_code, 422)
        ok = self.request("POST", f"/p3/evidence/{evidence_id}/field-verifications", "human", json=payload)
        self.assertEqual(ok.status_code, 200, ok.text)
        listed = {r["sample_ref"]: r for r in self.request("GET", f"/p3/audit-runs/{run_id}/evidence-requests").json()["requests"]}[req["sample_ref"]]["evidence"]
        comparison = next(e for e in listed if e["evidence_id"] == evidence_id)["document_comparison"]
        self.assertEqual(comparison["quality"]["invoice_number"]["state"], "human_verified")
        self.assertEqual(comparison["quality"]["invoice_number"]["evidence"]["verified_by"], "reviewer")

    def test_statement_continuity_gaps_and_row_sources(self):
        rows = fx.many_rows(9, date(2012, 1, 3))
        first = fx.bank_amount_pdf(rows=rows[:5], style="indicator", opening=100000.00)
        one = self.request("POST", "/p6/bank-statements", "client", json={"period": "JAN22", "source_base64": b64(first)}).json()
        self.assertEqual(one["continuity"]["status"], "first_statement")
        closing = 100000.00 + sum((-1 if wd else 1) * float((wd or dep).replace(",", "")) for _, _, _, wd, dep in rows[:5])
        second = self.request("POST", "/p6/bank-statements", "client", json={"period": "FEB22", "source_base64": b64(fx.bank_amount_pdf(rows=rows[5:7], style="indicator", opening=closing))}).json()
        self.assertEqual(second["continuity"]["status"], "continuous", second["continuity"])
        closing += sum((-1 if wd else 1) * float((wd or dep).replace(",", "")) for _, _, _, wd, dep in rows[5:7])
        gap_open = closing + 5000
        third = self.request("POST", "/p6/bank-statements", "client", json={"period": "MAR22", "source_base64": b64(fx.bank_amount_pdf(rows=rows[7:], style="indicator", opening=gap_open))}).json()
        self.assertEqual(third["continuity"]["status"], "gap")
        self.assertEqual(third["continuity"]["unexplained_difference"], "5000.00")
        with self._db() as db:
            sources = [dict(r) for r in db.execute("SELECT * FROM p6_bank_row_sources WHERE statement_id=? ORDER BY row_no", (one["statement_id"],))]
        self.assertEqual(len(sources), 5)
        self.assertTrue(all(s["page"] == 1 and s["line"] and s["extraction"] == "native" and s["direction_source"] == "indicator" for s in sources))

    def test_amount_drcr_pdf_and_csv_through_the_api(self):
        response = self.request("POST", "/p6/bank-statements", "client", json={"period": "AMT", "source_base64": b64(fx.bank_amount_pdf(rows=fx.many_rows(6, date(2021, 5, 3)), style="suffix"))})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["layout"], response.json()["balance_check"]["status"]), ("amount", "consistent"))
        ambiguous = self.request("POST", "/p6/bank-statements", "client", json={"period": "AMB", "source_base64": b64(fx.bank_amount_pdf(rows=fx.many_rows(4, date(2021, 1, 4)), style="balance_only", order=("ref", "amount")))})
        self.assertEqual(ambiguous.status_code, 422)

    def test_tally_rows_trace_to_vouchers(self):
        response = self.request("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": b64(fx.tally_xml()), "source_format": "tally_xml"})
        self.assertEqual(response.status_code, 200, response.text)
        with self._db() as db:
            event = json.loads(db.execute("SELECT report_json FROM import_reports WHERE action='register_imported' ORDER BY report_id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(event["row_sources"][0], {"row_no": 1, "voucher": "TLY/25-26/001", "voucher_index": 1, "remote_id": "synthetic-TLY/25-26/001"})


if __name__ == "__main__":
    unittest.main()
