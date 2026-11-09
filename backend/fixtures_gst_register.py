"""A synthetic Indian GST sales register with known, planted problems, for end-to-end checks.

Fictional company in Maharashtra (state code 27), FY 2025-26. Shaped like a real Tally/Excel register export:
B2B rows with valid GSTINs (check digit computed), B2C rows with no GSTIN, CGST+SGST for sales inside the state
and IGST for sales to other states, day-first dates (12/04/2025), Indian digit grouping (1,18,000.00),
credit notes listed in the same register, and stray spaces. Everything is invented; no real taxpayer data.

Planted problems (the expected result of reconciling the register against the books):
  AMOUNT    one register amount is Rs 1,000 higher than the books
  DATE      one register date is a day later than the books
  GSTIN     one B2B buyer GSTIN differs from the books (wrong state code)
  REG_ONLY  one invoice is in the register but not in the books
  SYS_ONLY  one sale is in the books but missing from the register
  DUP       one bill number appears twice in the register (DUPLICATE_ROW)
  TAX_SPLIT IGST charged on a sale inside the state (needs company_state=27)
  CREDIT_*  credit note 001 matches the books, 002 has a different amount, 004 is not in the books
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .document_import import _GSTIN_CHARS

STATES = ("27", "27", "27", "29", "24", "33", "07")  # mostly Maharashtra (intra-state), some other states


def gstin(state: str, n: int) -> str:
    pan = "AAB" + "CDEFGHJKLM"[n % 10] + "P" + f"{1000 + n:04d}" + "ABCDEFGHJK"[(n * 7) % 10]
    body = f"{state}{pan}1Z"
    total = 0
    for position, char in enumerate(body):
        product = _GSTIN_CHARS.index(char) * (2 if position % 2 else 1)
        total += product // 36 + product % 36
    return body + _GSTIN_CHARS[(36 - total % 36) % 36]


def indian(amount: Decimal) -> str:
    whole, paise = f"{amount:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail]) + "." + paise


def build(count: int = 300):
    """Returns (customers, sales, register_rows, planted). Sales are what the books hold; register_rows are the
    exported register as strings; planted maps each planted problem to its bill number."""
    customers, sales, register = [], [], []
    for c in range(40):
        b2b = c % 3 != 0
        state = STATES[c % len(STATES)]
        customers.append({"customer_id": f"IN-C{c:03d}", "name": f"{'Synthetic' if b2b else 'Walk-in'} Buyer {c:03d} {'Pvt Ltd' if b2b else ''}".strip(),
                          "gstin": gstin(state, c) if b2b else None, "state": state if b2b else "27"})
    start = date(2025, 4, 1)
    for n in range(1, count + 1):
        customer = customers[(n * 7) % len(customers)]
        when = start + timedelta(days=(n * 11) % 360)
        net = Decimal(5_000 + (n * 7_919) % 4_95_000)
        tax = (net * Decimal("0.18")).quantize(Decimal("0.01"))
        bill = f"MH/25-26/{n:04d}"
        sales.append({"order_id": f"IN-O{n}", "dispatch_id": f"IN-D{n}", "invoice_id": f"IN-I{n}", "journal_id": f"IN-J{n}",
                      "customer_id": customer["customer_id"], "order_date": when.isoformat(), "dispatch_date": when.isoformat(),
                      "invoice_date": when.isoformat(), "bill_no": bill, "net_amount": f"{net:.2f}", "tax_amount": f"{tax:.2f}"})
        register.append({"Bill No": bill, "Date": f"{when.day:02d}/{when.month:02d}/{when.year}", "Customer": customer["name"] + ("  " if n % 17 == 0 else ""),
                         "Gross Amt": indian(net + tax), "GST No": customer["gstin"] or "",
                         **({"CGST": indian(tax / 2), "SGST": indian(tax - tax / 2), "IGST": "0.00"} if customer["state"] == "27" else {"CGST": "0.00", "SGST": "0.00", "IGST": indian(tax)})})
    by_bill = {r["Bill No"]: r for r in register}
    planted = {}
    b2b_bills = [s["bill_no"] for s in sales if next(c for c in customers if c["customer_id"] == s["customer_id"])["gstin"]]
    planted["AMOUNT"] = b2b_bills[3]
    row = by_bill[planted["AMOUNT"]]
    row["Gross Amt"] = indian(Decimal(row["Gross Amt"].replace(",", "")) + 1000)
    planted["DATE"] = b2b_bills[5]
    row = by_bill[planted["DATE"]]
    d, m, y = map(int, row["Date"].split("/"))
    later = date(y, m, d) + timedelta(days=1)
    row["Date"] = f"{later.day:02d}/{later.month:02d}/{later.year}"
    planted["GSTIN"] = b2b_bills[8]
    row = by_bill[planted["GSTIN"]]
    row["GST No"] = ("29" if row["GST No"].startswith("24") else "24") + row["GST No"][2:]  # another state, so it differs from the books
    planted["TAX_SPLIT"] = next(b for b in b2b_bills[9:] if by_bill[b]["GST No"].startswith("27"))  # IGST wrongly charged inside Maharashtra
    row = by_bill[planted["TAX_SPLIT"]]
    row["IGST"], row["CGST"], row["SGST"] = indian(Decimal(row["CGST"].replace(",", "")) + Decimal(row["SGST"].replace(",", ""))), "0.00", "0.00"
    planted["SYS_ONLY"] = sales[20]["bill_no"]
    register = [r for r in register if r["Bill No"] != planted["SYS_ONLY"]]
    planted["REG_ONLY"] = f"MH/25-26/{count + 1:04d}"
    register.append({"Bill No": planted["REG_ONLY"], "Date": "15/03/2026", "Customer": customers[1]["name"], "Gross Amt": indian(Decimal("59000")), "GST No": customers[1]["gstin"]})
    planted["DUP"] = sales[30]["bill_no"]
    register.append(dict(by_bill[planted["DUP"]]))
    # Credit notes: the books hold CN/25-26/001-003 against sales 41-43. The register lists 001 correctly, 002 with a
    # different amount, and 004, which the books don't have.
    for k in range(1, 4):
        sales[40 + k]["credit_note"] = {"credit_note_id": f"CN/25-26/{k:03d}", "credit_date": f"2026-02-{10 + k}", "amount": f"{1180 * k}.00", "reason": "Synthetic goods return"}
    planted["CREDIT_OK"], planted["CREDIT_DIFF"], planted["CREDIT_UNKNOWN"] = "CN/25-26/001", "CN/25-26/002", "CN/25-26/004"
    for k, amount in ((1, 1180), (2, 2400), (4, 4720)):
        register.append({"Bill No": f"CN/25-26/{k:03d}", "Date": f"{10 + k}/02/2026", "Customer": customers[k * 2]["name"], "Gross Amt": "-" + indian(Decimal(amount)), "GST No": customers[k * 2]["gstin"] or ""})
    return customers, sales, register, planted


def register_csv(rows) -> bytes:
    import csv
    import io
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["Bill No", "Date", "Customer", "Gross Amt", "GST No", "CGST", "SGST", "IGST"], restval="", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")
