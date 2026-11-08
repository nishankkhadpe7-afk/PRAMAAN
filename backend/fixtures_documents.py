"""Synthetic real-format documents for testing the Tally, bank-PDF and invoice-PDF readers.

Everything here is fictional and labelled as such. The files imitate the *layout* of common Indian
formats (a Tally XML Day Book export, a net-banking PDF statement, a GST tax invoice); they are not
copies of any bank's or vendor's documents.

Run:  python -m Pramaan.backend.fixtures_documents --out sample_uploads/documents
"""
from __future__ import annotations

import argparse
import io
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

SALES = [  # bill_no, date, party, gstin, gross_rupees
    ("TLY/25-26/001", date(2025, 4, 12), "Sharma Traders (synthetic)", "27AAAPS1234C1Z5", "118000.00"),
    ("TLY/25-26/002", date(2025, 5, 3), "Banyan Retail (synthetic)", "29AABCB5678D1Z2", "59000.00"),
    ("TLY/25-26/003", date(2025, 6, 21), "Aster Components (synthetic)", "", "236000.00"),
]


def tally_xml(sales=SALES, extra_vouchers: bool = True, utf16: bool = False) -> bytes:
    """A Tally-style Day Book export: sales vouchers plus a receipt and a cancelled sale that must be skipped."""
    def voucher(vtype, number, when, party, gstin, gross, cancelled="No"):
        gst = f"<PARTYGSTIN>{gstin}</PARTYGSTIN>" if gstin else ""
        net = f"{float(gross) / 1.18:.2f}"
        tax = f"{float(gross) - float(net):.2f}"
        return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID="synthetic-{escape(number)}" VCHTYPE="{vtype}" ACTION="Create">'
                f"<DATE>{when:%Y%m%d}</DATE><VOUCHERTYPENAME>{vtype}</VOUCHERTYPENAME><VOUCHERNUMBER>{escape(number)}</VOUCHERNUMBER>"
                f"<PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME>{gst}<ISCANCELLED>{cancelled}</ISCANCELLED><ISOPTIONAL>No</ISOPTIONAL>"
                f"<NARRATION>Synthetic test voucher&#4;</NARRATION>"
                f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(party)}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-{gross}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>Sales Account</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>{net}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>Output IGST 18%</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>{tax}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                "</VOUCHER></TALLYMESSAGE>")
    body = "".join(voucher("Sales", n, d, p, g, a) for n, d, p, g, a in sales)
    if extra_vouchers:
        body += voucher("Receipt", "RCPT/001", date(2025, 4, 20), "Sharma Traders (synthetic)", "", "118000.00")
        body += voucher("Sales", "TLY/25-26/099", date(2025, 6, 30), "Cancelled Buyer (synthetic)", "", "10000.00", cancelled="Yes")
    text = ('<?xml version="1.0" encoding="utf-8"?><ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>'
            f"<BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC><REQUESTDATA>{body}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return ("﻿" + text.replace('encoding="utf-8"', 'encoding="utf-16"')).encode("utf-16-le") if utf16 else text.encode()


BANK_ROWS = [  # date, narration, ref, withdrawal, deposit
    (date(2025, 4, 14), "NEFT CR SHARMA TRDRS TLY/25-26/001", "N104250001234", None, "1,18,000.00"),
    (date(2025, 4, 18), "Office rent April", "CHQ000451", "45,000.00", None),
    (date(2025, 5, 9), "IMPS BANYAN RETL 59000", "IMPS5091123456", None, "59,000.00"),
    (date(2025, 6, 2), "Electricity bill", "BILLPAY88812", "8,250.50", None),
]


def bank_statement_pdf(rows=BANK_ROWS, opening: float = 250000.00, with_header: bool = True) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, height - 50, "Fictional Bank of India (synthetic) - Account Statement")
    c.setFont("Helvetica", 9)
    c.drawString(40, height - 66, "Account: SYNTHETIC-ACCOUNT  Period: 01-04-2025 to 30-06-2025  (test data, not a real statement)")
    cols = {"date": 40, "narr": 100, "ref": 290, "wd": 430, "dep": 500, "bal": 570}
    y = height - 100
    if with_header:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(cols["date"], y, "Date")
        c.drawString(cols["narr"], y, "Narration")
        c.drawString(cols["ref"], y, "Ref No")
        c.drawRightString(cols["wd"], y, "Withdrawal")
        c.drawRightString(cols["dep"], y, "Deposit")
        c.drawRightString(cols["bal"], y, "Balance")
        y -= 16
    c.setFont("Helvetica", 9)
    c.drawString(cols["narr"], y, "Opening balance")
    c.drawRightString(cols["bal"], y, f"{opening:,.2f}")
    balance = opening
    for when, narration, ref, wd, dep in rows:
        y -= 15
        balance += float((dep or "0").replace(",", "")) - float((wd or "0").replace(",", ""))
        c.drawString(cols["date"], y, when.strftime("%d-%m-%Y"))
        c.drawString(cols["narr"], y, narration)
        c.drawString(cols["ref"], y, ref)
        if wd:
            c.drawRightString(cols["wd"], y, wd)
        if dep:
            c.drawRightString(cols["dep"], y, dep)
        c.drawRightString(cols["bal"], y, f"{balance:,.2f}")
    c.showPage()
    c.save()
    return buf.getvalue()


def invoice_pdf(bill_no: str, when: date, buyer: str, buyer_gstin: str, total: str, seller_gstin: str = "27AAACF0000F1Z5") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, height - 50, "TAX INVOICE")
    c.setFont("Helvetica", 10)
    lines = ["Fictional Manufacturing Pvt Ltd (synthetic seller)", f"GSTIN: {seller_gstin}", "",
             f"Invoice No: {bill_no}", f"Invoice Date: {when:%d-%m-%Y}", "", f"Bill to: {buyer}"]
    if buyer_gstin:
        lines.append(f"Buyer GSTIN: {buyer_gstin}")
    y = height - 75
    for line in lines:
        c.drawString(40, y, line)
        y -= 15
    gross = float(total.replace(",", ""))
    net = gross / 1.18
    y -= 10
    for label, value in (("Taxable value", net), ("IGST @ 18%", gross - net)):
        c.drawString(40, y, label)
        c.drawRightString(540, y, f"{value:,.2f}")
        y -= 15
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y - 5, "Grand Total")
    c.drawRightString(540, y - 5, f"Rs. {gross:,.2f}")
    c.setFont("Helvetica", 8)
    c.drawString(40, 40, "Synthetic test document generated by PRAMAAN; not a real invoice.")
    c.showPage()
    c.save()
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Write synthetic Tally XML, bank-statement PDF and invoice PDF samples.")
    parser.add_argument("--out", default="sample_uploads/documents")
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tally_daybook_synthetic.xml").write_bytes(tally_xml())
    (out / "bank_statement_synthetic.pdf").write_bytes(bank_statement_pdf())
    bill, when, buyer, gstin, total = SALES[0]
    (out / "invoice_TLY-25-26-001_synthetic.pdf").write_bytes(invoice_pdf(bill, when, buyer, gstin, total))
    print(f"wrote 3 synthetic documents to {out}")


if __name__ == "__main__":
    main()
