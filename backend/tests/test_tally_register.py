"""Tally Sales Register reader and the local anonymiser, on SYNTHETIC exports (fixtures_tally_register)."""
import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from Pramaan.backend import anonymise_tally as anon
from Pramaan.backend import fixtures_tally_register as fx
from Pramaan.backend.document_import import DocumentReadError, gstin_check, parse_tally_sales
from Pramaan.backend.tally_register import parse_tally_register


def _edit(source: bytes, change) -> bytes:
    book = load_workbook(io.BytesIO(source))
    change(book["Sales Register"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


class TallyRegisterReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.held = fx.register_xlsx()
        cls.read = parse_tally_register(cls.source)

    def test_every_voucher_is_read_exactly(self):
        rows = self.read["rows"]
        self.assertEqual(len(rows), len(self.held))
        for row, held in zip(rows, self.held):
            sign = -1 if held["type"] == "Credit Note" else 1
            self.assertEqual((row["Bill No"], row["Date"], row["Customer"], row["GST No"]), (held["bill"], held["date"].isoformat(), held["party"], held["gstin"]))
            self.assertEqual(row["Gross Amt"], f"{sign * held['total']:.2f}")
            self.assertEqual((row["CGST"], row["SGST"], row["IGST"]), tuple(f"{sign * held[k]:.2f}" if held[k] else "0.00" for k in ("cgst", "sgst", "igst")))
        self.assertEqual(self.read["sheets"][0]["header_rows"], 2)

    def test_non_voucher_lines_are_accounted_for_and_totals_checked(self):
        reasons = [s["reason"] for s in self.read["skipped"]]
        self.assertEqual(reasons.count("cancelled voucher"), 1)
        self.assertEqual(reasons.count("repeated header"), 1)
        self.assertGreater(reasons.count("total or balance line"), 2)
        self.assertEqual(self.read["rejected"], [])
        self.assertEqual([w["reason"] for w in self.read["warnings"]], ["hidden sheet not read"])  # totals agree
        credit = [s for s in self.read["sources"] if s["status"] == "credit_note"]
        self.assertEqual([c["voucher"] for c in credit], ["CN/25-26/001"])
        self.assertTrue(all({"sheet", "source_row"} <= set(s) for s in self.read["sources"]))

    def test_wrong_subtotal_is_a_warning(self):
        def change(ws):
            for row in ws.iter_rows():
                if row[1].value == "Sub Total":
                    row[9].value = "1.00"
                    return
        read = parse_tally_register(_edit(self.source, change))
        self.assertTrue(any("subtotal 1.00 does not equal" in w["reason"] for w in read["warnings"]))

    def test_unreadable_lines_are_rejected_never_dropped_or_guessed(self):
        def change(ws):
            ws["J10"].value = "12,34,5x.00"
            ws["D11"].value = None
            ws["A12"].value = "31-Feb-2025"
        read = parse_tally_register(_edit(self.source, change))
        self.assertEqual(len(read["rows"]) + len(read["rejected"]), len(self.held))
        reasons = sorted(r["reason"] for r in read["rejected"])
        self.assertEqual(len(reasons), 3)
        self.assertTrue(any("unreadable amount" in r for r in reasons) and any("voucher number missing" in r for r in reasons) and any("unreadable date" in r for r in reasons))

    def test_duplicate_voucher_number_warns(self):
        read = parse_tally_register(_edit(self.source, lambda ws: setattr(ws["D11"], "value", ws["D10"].value)))
        self.assertTrue(any("repeats" in w["reason"] for w in read["warnings"]))

    def test_bad_files_are_refused(self):
        with self.assertRaises(DocumentReadError):
            parse_tally_register(b"\xd0\xcf\x11\xe0 old xls")
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(["just", "some", "text"])
        out = io.BytesIO()
        book.save(out)
        with self.assertRaises(DocumentReadError):
            parse_tally_register(out.getvalue())

    def test_upload_as_register_and_reconcile(self):
        from fastapi.testclient import TestClient
        from Pramaan.backend import app as p1, security
        root = Path(tempfile.mkdtemp(prefix="pramaan-tallyx-"))
        with patch.object(p1, "ROOT", root), patch.object(p1, "DB_PATH", root / "p1.sqlite3"), patch.object(p1, "VAULT", root / "vault"), patch.dict("os.environ", {"PRAMAAN_DATA": str(root)}):
            client = TestClient(p1.app)
            hdr = lambda role: {"Authorization": "Bearer " + security.issue("u", role, ttl=600)}
            up = client.post("/p2/registers", headers=hdr("client_employee"), json={"period": "FY26", "source_format": "tally_xlsx", "source_base64": base64.b64encode(self.source).decode()})
            self.assertEqual(up.status_code, 200, up.text)
            self.assertEqual((up.json()["row_count"], up.json()["parser"]), (len(self.held), "pramaan-tally-register-xlsx-v1"))
            rc = client.post(f"/p2/registers/{up.json()['upload_id']}/reconcile", headers=hdr("auditor")).json()
            # The reader writes ISO dates, so no date needs the day/month order and none goes to review.
            self.assertFalse([f for f in rc["findings"] if f["category"] == "PARSE_REVIEW" and any(d["field"] == "Date" for d in f["field_differences"])])
            self.assertTrue(rc["findings"])


class AnonymiserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pramaan-anon-"))
        (self.tmp / "src").mkdir()
        source, held = fx.register_xlsx()
        self.reg, self.xml = self.tmp / "src" / "register.xlsx", self.tmp / "src" / "vouchers.xml"
        self.reg.write_bytes(source)
        self.xml.write_bytes(fx.vouchers_xml(held))
        self.out, self.key = self.tmp / "shared", self.tmp / "private" / "anon.key"

    def run_tool(self, **kw):
        return anon.run(self.reg, self.xml, kw.pop("out", self.out), kw.pop("key", self.key), **kw)

    def test_figures_identical_names_consistent_originals_unchanged(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.reg, self.xml)}
        report = self.run_tool()
        self.assertEqual(report["result"], "written", report)
        self.assertTrue(report["figures_identical"] and report["originals_unchanged"])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.reg, self.xml)})
        reg = parse_tally_register((self.out / "sales_register_anonymised.xlsx").read_bytes())
        vch = parse_tally_sales((self.out / "vouchers_anonymised.xml").read_bytes())
        # The same bill has the same pseudonymous party and GSTIN in both files.
        by_bill = {r["Bill No"]: r for r in vch["rows"]}
        for row in reg["rows"]:
            if row["Bill No"] in by_bill:
                self.assertEqual((row["Customer"], row["GST No"]), (by_bill[row["Bill No"]]["Customer"], by_bill[row["Bill No"]]["GST No"]))
            self.assertTrue(row["Customer"].startswith("Party "))
            if row["GST No"]:
                self.assertEqual(row["GST No"][5], "X")  # no real PAN has holder type X
                self.assertIsNone(gstin_check(row["GST No"]))

    def test_nothing_sensitive_survives(self):
        self.run_tool()
        xml = (self.out / "vouchers_anonymised.xml").read_text()
        book = load_workbook(self.out / "sales_register_anonymised.xlsx")
        cells = " ".join(str(v) for ws in book.worksheets for row in ws.iter_rows(values_only=True) for v in row if v is not None)
        for text in (xml, cells):
            for secret in ("Synthetic Buyer", "Walk-in Buyer", fx.COMPANY, "@example", "9820012345", "Shop 1,", "SYNB0001234", "Ramesh"):
                self.assertNotIn(secret, text)
        self.assertEqual(book.sheetnames, ["Sales Register"])  # hidden sheet not copied
        self.assertIsNone(book["Sales Register"]["B8"].comment)
        self.assertNotEqual(book.properties.creator, "Synthetic Accountant")
        key = json.loads(self.key.read_text())
        self.assertIn(fx.COMPANY.upper(), key["table"]["company"])
        report = json.loads((self.out / "anonymise_report.json").read_text())
        self.assertNotIn("Synthetic", json.dumps(report))

    def test_rerun_with_same_key_gives_identical_output_and_dry_run_writes_nothing(self):
        self.run_tool()
        first = (self.out / "vouchers_anonymised.xml").read_bytes()
        second_out = self.tmp / "shared2"
        self.assertEqual(self.run_tool(out=second_out)["result"], "written")
        self.assertEqual(first, (second_out / "vouchers_anonymised.xml").read_bytes())
        dry = self.tmp / "dry"
        self.assertEqual(self.run_tool(out=dry, dry_run=True)["result"], "dry run: nothing written")
        self.assertFalse(dry.exists())

    def test_keep_narration_still_scrubs_contacts(self):
        self.run_tool(keep_narration=True)
        xml = (self.out / "vouchers_anonymised.xml").read_text()
        self.assertIn("Goods sold to Party ", xml)
        self.assertNotIn("@example", xml)
        self.assertIn("[removed]", xml)

    def test_bad_check_digit_stays_bad(self):
        names = anon.Pseudonyms(b"k" * 32)
        good = fx.COMPANY_GSTIN
        bad = good[:-1] + ("0" if good[-1] != "0" else "1")
        self.assertIsNone(gstin_check(names.gstin(good)))
        self.assertIsNotNone(gstin_check(names.gstin(bad)))
        self.assertEqual(names.gstin(good)[:2], good[:2])
        self.assertTrue(names.gstin("not-a-gstin").startswith("NOTGSTIN"))

    def test_unsafe_destinations_are_refused(self):
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        for kw in ({"out": repo / "out"}, {"key": repo / "anon.key"}, {"key": self.out / "anon.key"}, {"out": self.tmp / "src"}):
            with self.assertRaises(anon.AnonymiseError):
                self.run_tool(**kw)
        self.assertFalse((repo / "out").exists())

    def test_cli_exit_codes(self):
        self.assertEqual(anon.main(["--register", str(self.reg), "--out", str(self.out), "--key", str(self.key), "--dry-run"]), 0)
        self.assertEqual(anon.main(["--register", str(self.tmp / "missing.xlsx"), "--out", str(self.out), "--key", str(self.key)]), 2)


if __name__ == "__main__":
    unittest.main()
