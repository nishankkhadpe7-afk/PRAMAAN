"""Formats found while testing public data (all inputs here are rebuilt by hand; no third-party files are committed):
Tally's official Excel voucher template, small-trader invoices that print "Subtotal" and a single "GST" line, OCR that
reads "/" as an apostrophe, and small low-resolution scans."""
import io
import unittest
from datetime import datetime

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from Pramaan.backend.document_import import _invoice_arithmetic, read_invoice_pdf
from Pramaan.backend.tally_register import parse_tally_register


def tally_template(rows) -> bytes:
    """Same columns as Tally's 'Sales Voucher in Default Template with GST' sample (subset)."""
    book = Workbook()
    ws = book.active
    ws.title = "Accounting Voucher"
    ws.append(["Voucher Date", "Voucher Type Name", "Voucher Number", "Buyer/Supplier - GSTIN/UIN", "Ledger Name", "Ledger Amount", "Ledger Amount Dr/Cr", "Item Name", "Item Amount"])
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


SAMPLE = [
    [datetime(2023, 4, 1), "Sales", 101, "27AABCP1000A1Z5", "Synthetic Traders", 3540, "Dr", None, None],
    [None, None, None, None, "Sales", 3000, "Cr", "Marker", 1000],
    [None, None, None, None, None, None, None, "Pen", 2000],
    [None, None, None, None, "Tax - CGST @ 9 %", 270, "Cr", None, None],
    [None, None, None, None, "Tax - SGST @ 9 %", 270, "Cr", None, None],
    [datetime(2023, 4, 3), "Sales", 102, "29AABCP1000A1Z1", "Other State Buyer", 11800, "Dr", None, None],
    [None, None, None, None, "Sales", 10000, "Cr", "Folder", 10000],
    [None, None, None, None, "Tax - IGST @ 18%", 1800, "Cr", None, None],
    [datetime(2023, 4, 5), "Purchase", 7, None, "A Supplier", 500, "Cr", None, None],
    [None, None, None, None, "Purchases", 500, "Dr", None, None],
]


class TallyVoucherTemplateTests(unittest.TestCase):
    def test_multi_row_vouchers_are_grouped_and_split_by_tax(self):
        read = parse_tally_register(tally_template(SAMPLE))
        self.assertEqual([(r["Bill No"], r["Gross Amt"], r["Taxable"], r["CGST"], r["SGST"], r["IGST"]) for r in read["rows"]],
                         [("101", "3540.00", "3000.00", "270.00", "270.00", "0.00"), ("102", "11800.00", "10000.00", "0.00", "0.00", "1800.00")])
        self.assertEqual([s["reason"] for s in read["skipped"]], ["not a sales voucher (Purchase)"])
        self.assertEqual(read["rejected"], [])

    def test_unbalanced_voucher_and_item_mismatch_are_warned(self):
        rows = [list(r) for r in SAMPLE[:5]]
        rows[3][5] = 300  # CGST no longer balances the party line
        rows[2][8] = 1500  # items now add to 2,500, not 3,000
        reasons = " | ".join(w["reason"] for w in parse_tally_register(tally_template(rows))["warnings"])
        self.assertIn("do not balance", reasons)
        self.assertIn("item amounts", reasons)

    def test_unreadable_ledger_amount_rejects_the_voucher(self):
        rows = [list(r) for r in SAMPLE[:5]]
        rows[1][5] = "3,0x0"
        read = parse_tally_register(tally_template(rows))
        self.assertEqual(read["rows"], [])
        self.assertIn("unreadable ledger amount", read["rejected"][0]["reason"])


def small_invoice(lines) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    y = 800
    for text in lines:
        c.drawString(40, y, text)
        y -= 16
    c.save()
    return out.getvalue()


class SmallTraderInvoiceTests(unittest.TestCase):
    def test_subtotal_and_single_gst_line_enable_the_cross_check(self):
        read = read_invoice_pdf(small_invoice(["PURCHASE BILL (synthetic)", "Invoice No: GST/2024-25/43509  Date: 2024-08-21",
                                               "Subtotal Rs.24,287.33", "GST Rs.5,426.16", "TOTAL Rs.29,713.49"]))
        self.assertEqual((read["taxable_cents"], read["gst_total_cents"], read["total_cents"]), (2428733, 542616, 2971349))
        self.assertEqual(read["arithmetic"]["status"], "consistent")

    def test_explicit_taxable_value_beats_subtotal_and_split_beats_single_gst(self):
        read = read_invoice_pdf(small_invoice(["Invoice No: INV-9  Date: 2024-08-21", "Subtotal 1,100.00", "Taxable Value 1,000.00",
                                               "CGST @ 9% 90.00", "SGST @ 9% 90.00", "Grand Total 1,180.00"]))
        self.assertEqual(read["taxable_cents"], 100000)
        self.assertEqual(read["arithmetic"]["status"], "consistent")

    def test_gstin_is_never_read_as_a_gst_amount(self):
        read = read_invoice_pdf(small_invoice(["Invoice No: INV-10  Date: 2024-08-21", "GSTIN: 27AABCP1000A1Z5", "Grand Total 500.00"]))
        self.assertIsNone(read["gst_total_cents"])

    def test_wrong_total_is_caught_by_the_cross_check(self):
        self.assertEqual(_invoice_arithmetic({"total_cents": 426466, "taxable_cents": 3633867, "gst_total_cents": 629599})["status"], "inconsistent")


class OcrReadingTests(unittest.TestCase):
    def test_apostrophe_read_for_slash_is_restored_in_the_invoice_number(self):
        read = read_invoice_pdf(small_invoice(["Invoice No: GST/2024-25'54223  Date: 2024-10-15", "Grand Total 100.00"]))
        self.assertEqual(read["invoice_number"], "GST/2024-25/54223")

    @unittest.skipUnless(__import__('importlib').util.find_spec('PIL'), 'Pillow not installed')
    def test_small_page_is_enlarged_before_ocr_and_large_page_is_not(self):
        import pymupdf
        from Pramaan.backend.ocr import MIN_PAGE_PIXELS, _upscale_small
        small = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 600, 800), False)
        png, factor = _upscale_small(small)
        self.assertAlmostEqual(factor, MIN_PAGE_PIXELS / 800)
        self.assertTrue(png.startswith(b"\x89PNG"))
        big = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 2000, MIN_PAGE_PIXELS + 10), False)
        self.assertEqual(_upscale_small(big)[1], 1.0)


if __name__ == "__main__":
    unittest.main()
