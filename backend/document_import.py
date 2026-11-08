"""Reading real-world source formats: Tally XML exports, PDF bank statements and PDF invoices.

Every reader is deterministic and conservative. It returns what it could read *and* what it could
not, and it never guesses a value. The original bytes are always preserved by the caller, so a
reading can be repeated or challenged later.

- Tally: the XML that TallyPrime / Tally.ERP 9 writes from "Export → Day Book / Vouchers" (XML format).
  Sales vouchers become sales-register rows with the same columns as a CSV register.
- Bank statement PDF: text-based (not scanned) statements. Columns are found from the header words
  (Debit/Withdrawal, Credit/Deposit, Balance), so amounts are never assigned by guesswork.
- Invoice PDF: invoice number, date, GSTINs and total are read from the text and compared with the
  invoice in the frozen audit snapshot. A reading is company-supplied evidence, never verification.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

TALLY_PARSER = "pramaan-tally-xml-v1"
BANK_PDF_PARSER = "pramaan-bank-pdf-v1"
INVOICE_PDF_PARSER = "pramaan-invoice-pdf-v1"
MAX_PDF_PAGES = 200

GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
AMOUNT = re.compile(r"^-?(?:₹|Rs\.?|INR)?\s*\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?\)?(?:\s*(?:Cr|Dr|CR|DR))?$|^-?\d+(?:\.\d{1,2})?$")
DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d-%m-%y", "%d/%m/%y", "%d-%b-%y", "%d %B %Y", "%b %d, %Y")


class DocumentReadError(ValueError):
    """The file is not in a format this reader supports; the message says what was expected."""


# --------------------------------------------------------------------------- shared helpers

def parse_date(text: str) -> str | None:
    text = text.strip().rstrip(",")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_amount_cents(text: str) -> int | None:
    """'1,18,000.00' / '₹ 4,500' / '(250.00)' / '1200.50 Cr' -> cents (sign dropped; callers decide direction)."""
    cleaned = re.sub(r"(?i)(₹|rs\.?|inr|cr|dr|\s)", "", text).strip("()-+")
    if not cleaned or not re.fullmatch(r"\d[\d,]*(?:\.\d{1,2})?", cleaned):
        return None
    try:
        value = Decimal(cleaned.replace(",", ""))
    except InvalidOperation:
        return None
    return int((value * 100).to_integral_value())


def _rupees(cents: int) -> str:
    return f"{Decimal(cents) / Decimal(100):.2f}"


# --------------------------------------------------------------------------- Tally XML

_CONTROL_REFS = re.compile(rb"&#(?:x0*[0-8bBcCeEfF]|x0*1[0-9a-fA-F]|0*(?:[0-8]|1[1-2]|1[4-9]|2[0-9]|3[01]));")


def _tally_root(source: bytes) -> ET.Element:
    head = source[:4096]
    probe = head.decode("utf-16") if head[:2] in (b"\xff\xfe", b"\xfe\xff") else head.decode("utf-8", "ignore")
    if "<!DOCTYPE" in probe.upper() or "<!ENTITY" in probe.upper():
        raise DocumentReadError("Tally XML must not contain a DOCTYPE or entity declarations")
    if source[:2] in (b"\xff\xfe", b"\xfe\xff"):
        source = source.decode("utf-16").encode("utf-8")
        source = re.sub(rb"<\?xml[^>]*\?>", b"", source, count=1)
    # Tally writes control characters such as &#4; that strict XML rejects; they carry no data.
    source = _CONTROL_REFS.sub(b"", source)
    try:
        return ET.fromstring(source)
    except ET.ParseError as exc:
        raise DocumentReadError(f"not a readable Tally XML export ({exc})") from exc


def _text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_tally_sales(source: bytes) -> dict[str, Any]:
    """Return sales-register rows from a Tally XML export, plus a report of everything skipped."""
    root = _tally_root(source)
    vouchers = root.iter("VOUCHER")
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen = 0
    for voucher in vouchers:
        seen += 1
        vtype = _text(voucher, "VOUCHERTYPENAME") or voucher.get("VCHTYPE", "")
        number = _text(voucher, "VOUCHERNUMBER")
        label = number or voucher.get("REMOTEID", f"voucher {seen}")
        if "sales" not in vtype.lower() or any(word in vtype.lower() for word in ("order", "return")):
            skipped.append({"voucher": label, "reason": f"not a sales voucher ({vtype or 'type missing'})"})
            continue
        if _text(voucher, "ISCANCELLED").lower() == "yes" or _text(voucher, "ISOPTIONAL").lower() == "yes":
            skipped.append({"voucher": label, "reason": "cancelled or optional voucher"})
            continue
        when = _text(voucher, "DATE")
        try:
            iso = datetime.strptime(when, "%Y%m%d").date().isoformat()
        except ValueError:
            skipped.append({"voucher": label, "reason": f"unreadable date {when!r}"})
            continue
        party = _text(voucher, "PARTYLEDGERNAME") or _text(voucher, "PARTYNAME")
        entries = list(voucher.iter("ALLLEDGERENTRIES.LIST")) + list(voucher.iter("LEDGERENTRIES.LIST"))
        party_amounts = [parse_amount_cents(_text(e, "AMOUNT")) for e in entries if _text(e, "LEDGERNAME") == party and party]
        party_amounts = [a for a in party_amounts if a is not None]
        if not number or not party or not party_amounts:
            skipped.append({"voucher": label, "reason": "missing voucher number, party ledger or party amount"})
            continue
        gstin = _text(voucher, "PARTYGSTIN") or _text(voucher, "BASICBUYERGSTIN") or ""
        if not gstin:
            for addr in voucher.iter("GSTREGISTRATIONNUMBER"):
                gstin = (addr.text or "").strip()
                break
        rows.append({"Bill No": number, "Date": iso, "Customer": party, "Gross Amt": _rupees(sum(party_amounts)), "GST No": gstin})
    if seen == 0:
        raise DocumentReadError("no VOUCHER elements found; export the Day Book or sales vouchers from Tally in XML format")
    return {"rows": rows, "skipped": skipped, "vouchers_seen": seen, "parser": TALLY_PARSER}


def register_csv(rows: list[dict[str, str]]) -> bytes:
    """The normalized register rows as CSV (for display/download only; the XML stays the source)."""
    import csv
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["Bill No", "Date", "Customer", "Gross Amt", "GST No"])
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


# --------------------------------------------------------------------------- PDF text access

def _open_pdf(source: bytes):
    if not source.startswith(b"%PDF"):
        raise DocumentReadError("not a PDF file")
    import pymupdf
    try:
        doc = pymupdf.open(stream=source, filetype="pdf")
    except Exception as exc:  # pymupdf raises its own error types for damaged files
        raise DocumentReadError("the PDF could not be opened") from exc
    if doc.needs_pass:
        raise DocumentReadError("the PDF is password-protected; upload an unlocked copy")
    if doc.page_count > MAX_PDF_PAGES:
        raise DocumentReadError(f"the PDF has more than {MAX_PDF_PAGES} pages")
    return doc


def _lines(page) -> list[list[tuple[float, float, str]]]:
    """Words grouped into visual lines: [(x0, x1, text), ...] sorted left to right."""
    words = page.get_text("words")
    lines: list[list[tuple[float, float, str]]] = []
    current_y: float | None = None
    for x0, y0, x1, y1, text, *_ in sorted(words, key=lambda w: (round((w[1] + w[3]) / 2, 0), w[0])):
        mid = (y0 + y1) / 2
        if current_y is None or abs(mid - current_y) > 3:
            lines.append([])
            current_y = mid
        lines[-1].append((x0, x1, text))
    return [sorted(line) for line in lines]


def pdf_text(source: bytes) -> str:
    doc = _open_pdf(source)
    return "\n".join(page.get_text() for page in doc)


# --------------------------------------------------------------------------- bank statement PDF

_HEADERS = {
    "debit": ("debit", "withdrawal", "withdrawals", "dr", "paid", "out"),
    "credit": ("credit", "deposit", "deposits", "cr", "received", "in"),
    "balance": ("balance",),
    "reference": ("ref", "reference", "chq", "cheque", "utr", "ref."),
}


def _header_columns(line: list[tuple[float, float, str]]) -> dict[str, float] | None:
    cols: dict[str, float] = {}
    for x0, x1, text in line:
        word = text.lower().strip(".:/()")
        for key, names in _HEADERS.items():
            if word in names and key not in cols:
                cols[key] = (x0 + x1) / 2
    return cols if {"debit", "credit"} <= cols.keys() else None


def parse_bank_pdf(source: bytes) -> dict[str, Any]:
    """Transactions from a text-based bank statement PDF, in the same shape as the CSV parser."""
    doc = _open_pdf(source)
    rows: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    columns: dict[str, float] | None = None
    text_found = False
    for page_no, page in enumerate(doc, 1):
        for line in _lines(page):
            if not line:
                continue
            text_found = True
            header = None if parse_date(line[0][2]) else _header_columns(line)
            if header:
                columns = header
                continue
            first = line[0][2]
            when = parse_date(first) or (parse_date(" ".join(t for _, _, t in line[:3])) if len(line) >= 3 else None)
            if not when:
                continue
            # A date-led line is a candidate transaction. Amount-looking words are assigned to the
            # nearest money column; everything else is narration.
            if columns is None:
                unread.append({"page": page_no, "text": " ".join(t for _, _, t in line)[:200], "reason": "no Debit/Credit/Balance header found above this line"})
                continue
            date_words = 1 if parse_date(first) else 3
            narration, reference, debit, credit, balance = [], "", None, None, None
            money_cols = {k: v for k, v in columns.items() if k in ("debit", "credit", "balance")}
            for x0, x1, text in line[date_words:]:
                centre = (x0 + x1) / 2
                cents = parse_amount_cents(text) if AMOUNT.match(text.replace(" ", "")) and any(c.isdigit() for c in text) else None
                nearest = min(money_cols, key=lambda k: abs(money_cols[k] - centre))
                if cents is not None and abs(money_cols[nearest] - centre) < 60 and ("." in text or "," in text or nearest == "balance"):
                    if nearest == "debit":
                        debit = cents
                    elif nearest == "credit":
                        credit = cents
                    else:
                        balance = cents
                elif "reference" in columns and abs(columns["reference"] - centre) < 45 and not reference:
                    reference = text
                else:
                    narration.append(text)
            if (debit is None) == (credit is None):
                unread.append({"page": page_no, "text": " ".join(t for _, _, t in line)[:200],
                               "reason": "could not tell whether this is a debit or a credit" if debit and credit else "no amount in a Debit or Credit column"})
                continue
            narration_text = " ".join(narration)
            if not reference:
                found = re.search(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{8,22}\b", narration_text)
                reference = found.group(0) if found else ""
            rows.append({"row_no": len(rows) + 1, "txn_date": when, "amount_cents": debit or credit, "direction": "debit" if debit else "credit",
                         "narration": narration_text[:300], "reference": reference[:120], "counterparty": "", "balance_cents": balance})
    if not text_found:
        raise DocumentReadError("the PDF has no text layer (it looks scanned); export a text PDF or CSV from net banking")
    if not rows:
        raise DocumentReadError("no transactions found; the statement needs a header with Debit/Withdrawal and Credit/Deposit columns")
    return {"rows": rows, "unread_lines": unread, "parser": BANK_PDF_PARSER}


# --------------------------------------------------------------------------- invoice PDF

_INV_NO = re.compile(r"(?i)\b(?:invoice|inv|bill)\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,39})")
_INV_DATE = re.compile(r"(?i)\b(?:invoice\s*date|inv\.?\s*date|bill\s*date|date\s*of\s*invoice|dated|date)\s*[:\-]?\s*([0-9]{1,2}[-/. ][A-Za-z0-9]{1,9}[-/. ][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})")
_TOTAL = re.compile(r"(?i)\b(grand\s*total|invoice\s*total|total\s*invoice\s*value|total\s*amount(?:\s*payable)?|amount\s*payable|net\s*payable|total)\b[^0-9₹]{0,25}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_TOTAL_RANK = {"grand total": 0, "invoice total": 1, "total invoice value": 1, "total amount payable": 2, "amount payable": 2, "net payable": 2, "total amount": 3, "total": 4}


def read_invoice_pdf(source: bytes) -> dict[str, Any]:
    text = pdf_text(source)
    if not text.strip():
        raise DocumentReadError("the PDF has no text layer (it looks scanned)")
    number = _INV_NO.search(text)
    when = _INV_DATE.search(text)
    totals = [( _TOTAL_RANK.get(re.sub(r"\s+", " ", m.group(1).lower()), 5), parse_amount_cents(m.group(2))) for m in _TOTAL.finditer(text)]
    totals = [t for t in totals if t[1]]
    total = min(totals, key=lambda t: (t[0], -t[1]))[1] if totals else None
    return {"invoice_number": number.group(1).strip() if number else None,
            "invoice_date": parse_date(when.group(1)) if when else None,
            "gstins": sorted(set(GSTIN.findall(text))),
            "total_cents": total, "parser": INVOICE_PDF_PARSER}


def _norm_bill(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def compare_invoice(read: dict[str, Any], invoice: dict[str, Any] | None) -> dict[str, Any]:
    """Field-by-field comparison with the invoice in the frozen snapshot. 'not_read' never counts as a match."""
    if not invoice:
        return {"status": "no_invoice_in_snapshot", "fields": []}
    fields = []

    def add(name: str, document_value: Any, book_value: Any, same: bool | None) -> None:
        fields.append({"field": name, "document": document_value, "books": book_value,
                       "result": "not_read" if document_value in (None, [], "") else ("not_in_books" if book_value in (None, "") else ("match" if same else "differs"))})

    add("invoice_number", read.get("invoice_number"), invoice.get("bill_no"), _norm_bill(read.get("invoice_number")) == _norm_bill(invoice.get("bill_no")))
    add("invoice_date", read.get("invoice_date"), invoice.get("invoice_date"), read.get("invoice_date") == invoice.get("invoice_date"))
    gross = invoice.get("gross_cents")
    add("total", _rupees(read["total_cents"]) if read.get("total_cents") else None, _rupees(gross) if gross is not None else None, read.get("total_cents") == gross)
    add("buyer_gstin", ", ".join(read.get("gstins") or []) or None, invoice.get("gstin") or invoice.get("buyer_gstin"),
        (invoice.get("gstin") or invoice.get("buyer_gstin")) in (read.get("gstins") or []))
    results = {f["result"] for f in fields}
    status = "differs" if "differs" in results else ("matches" if results <= {"match", "not_in_books"} and "match" in results else "incomplete")
    return {"status": status, "fields": fields}
