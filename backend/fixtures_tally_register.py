"""SYNTHETIC Tally exports for tests: a Sales Register workbook and the matching voucher XML.

Built from fixtures_gst_register's invented company. The workbook copies the awkward parts of a real Tally Excel
export: company name, address and period lines above a merged two-row header, Indian digit grouping as text, a
repeated header on a new "page", monthly subtotals, a grand total, a credit note, a cancelled voucher, a blank row,
a hidden sheet and a cell comment. The XML carries addresses, phone numbers, e-mails, bank details and narration
so the anonymiser has something to remove. All names, numbers and addresses are invented.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from . import fixtures_gst_register as g

COMPANY = "Synthetic Traders Pvt Ltd"
COMPANY_GSTIN = g.gstin("27", 99)


def _rows(count: int):
    customers, sales, _, _ = g.build(count)
    by_id = {c["customer_id"]: c for c in customers}
    out = []
    for s in sales:
        c = by_id[s["customer_id"]]
        net, tax = Decimal(s["net_amount"]), Decimal(s["tax_amount"])
        intra = c["state"] == "27"
        out.append({"date": date.fromisoformat(s["invoice_date"]), "bill": s["bill_no"], "party": c["name"], "gstin": c["gstin"] or "",
                    "taxable": net, "cgst": tax / 2 if intra else Decimal(0), "sgst": tax - tax / 2 if intra else Decimal(0),
                    "igst": Decimal(0) if intra else tax, "total": net + tax, "type": "Sales", "state": c["state"]})
    out.sort(key=lambda r: (r["date"], r["bill"]))
    return out


def register_xlsx(count: int = 60) -> tuple[bytes, list[dict]]:
    """Returns (workbook bytes, the voucher rows it holds in order, credit note included, cancelled excluded)."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    rows = _rows(count)
    credit = {**rows[5], "bill": "CN/25-26/001", "type": "Credit Note", "date": rows[5]["date"],
              "taxable": Decimal("1000.00"), "cgst": Decimal("90.00"), "sgst": Decimal("90.00"), "igst": Decimal(0), "total": Decimal("1180.00")}
    rows.insert(6, credit)
    book = Workbook()
    ws = book.active
    ws.title = "Sales Register"
    ws.append([COMPANY])
    ws.merge_cells("A1:J1")
    ws.append(["Plot 12, Synthetic Industrial Estate, Pune 411001 | Ph: 020-12345678 | accounts@synthetic-traders.example"])
    ws.append(["Sales Register", None, None, None, None, None, None, None, None, None])
    ws.append(["1-Apr-2025 to 31-Mar-2026"])
    ws.append([None])
    header_top = ["Date", "Particulars", "Vch Type", "Vch No.", "GSTIN/UIN", "Taxable Value", "Tax Amount", None, None, "Gross Total"]
    header_low = [None, None, None, None, None, None, "CGST", "SGST", "IGST", None]
    ws.append(header_top)
    ws.append(header_low)
    ws.merge_cells("G6:I6")
    for col in "ABCDEFJ":
        ws.merge_cells(f"{col}6:{col}7")
    ws["B8"].comment = Comment("Checked by Ramesh, 98200 12345", "Synthetic")
    held: list[dict] = []
    month = None
    since = Decimal(0)
    for i, r in enumerate(rows):
        if month is not None and r["date"].month != month:
            ws.append([None, "Sub Total", None, None, None, None, None, None, None, g.indian(since)])
            since = Decimal(0)
        month = r["date"].month
        if i == 15:  # a new printed page repeats the header
            ws.append(header_low)
            ws.append([None])
        sign = -1 if r["type"] == "Credit Note" else 1
        ws.append([r["date"] if i % 2 else r["date"].strftime("%-d-%b-%Y"), r["party"], r["type"], r["bill"], r["gstin"],
                   float(r["taxable"]) if i % 3 else g.indian(r["taxable"]), g.indian(r["cgst"]), g.indian(r["sgst"]), g.indian(r["igst"]),
                   g.indian(r["total"]) + (" Cr" if sign < 0 else " Dr")])
        since += sign * r["total"]
        held.append(r)
        if i == 9:
            ws.append([r["date"], "(cancelled)", "Sales", "MH/25-26/9999", None, None, None, None, None, None])
    ws.append([None, "Sub Total", None, None, None, None, None, None, None, g.indian(since)])
    grand = sum((-1 if r["type"] == "Credit Note" else 1) * r["total"] for r in held)
    ws.append([None, "Grand Total", None, None, None, None, None, None, None, g.indian(grand)])
    hidden = book.create_sheet("Party Master")
    hidden.append(["Party", "Phone", "Bank A/c"])
    hidden.append([rows[0]["party"], "9820012345", "50100123456789"])
    hidden.sheet_state = "hidden"
    book.properties.creator = "Synthetic Accountant"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue(), held


def vouchers_xml(rows: list[dict]) -> bytes:
    def amount(value: Decimal, debit: bool) -> str:
        return f"{'-' if debit else ''}{value:.2f}"
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>",
             f"<REQUESTDESC><STATICVARIABLES><SVCURRENTCOMPANY>{escape(COMPANY)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>"]
    for n, r in enumerate(rows):
        credit = r["type"] == "Credit Note"
        party = escape(r["party"])
        lines = [(r["party"], r["total"], not credit), ("Sales @18%", r["taxable"], credit)]
        lines += [(name, r[key], credit) for name, key in (("Output CGST", "cgst"), ("Output SGST", "sgst"), ("Output IGST", "igst")) if r[key]]
        ledgers = "".join(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(name)}</LEDGERNAME><AMOUNT>{amount(v, debit)}</AMOUNT></ALLLEDGERENTRIES.LIST>" for name, v, debit in lines)
        parts.append(
            f'<TALLYMESSAGE><VOUCHER REMOTEID="synthetic-guid-{n:05d}" VCHTYPE="{r["type"]}" ACTION="Create">'
            f"<DATE>{r['date']:%Y%m%d}</DATE><GUID>synthetic-guid-{n:05d}</GUID><VOUCHERTYPENAME>{r['type']}</VOUCHERTYPENAME>"
            f"<VOUCHERNUMBER>{escape(r['bill'])}</VOUCHERNUMBER><PARTYLEDGERNAME>{party}</PARTYLEDGERNAME><PARTYNAME>{party}</PARTYNAME>"
            f"<PARTYGSTIN>{r['gstin']}</PARTYGSTIN><CMPGSTIN>{COMPANY_GSTIN}</CMPGSTIN>"
            f"<ADDRESS.LIST><ADDRESS>Shop {n}, Synthetic Market Road</ADDRESS><ADDRESS>Mumbai 4000{n % 90:02d}</ADDRESS></ADDRESS.LIST>"
            f"<BASICBUYERNAME>{party}</BASICBUYERNAME><PARTYMAILINGNAME>{party}</PARTYMAILINGNAME>"
            f"<NARRATION>Goods sold to {party}; contact 98{n:08d}, buyer{n}@example.com, paid to A/c 5010012345{n:04d}</NARRATION>"
            f"<BANKNAME>Synthetic Bank</BANKNAME><IFSCODE>SYNB0001234</IFSCODE>"
            f"{ledgers}</VOUCHER></TALLYMESSAGE>")
    parts.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return "".join(parts).encode()
