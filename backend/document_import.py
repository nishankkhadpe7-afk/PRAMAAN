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


def parse_signed_cents(text: str) -> int | None:
    """Like parse_amount_cents but keeps the sign: '-250.00', '(250.00)' and '250.00 Dr' are negative.
    Used for running balances, where 'Dr' means the account is overdrawn."""
    cents = parse_amount_cents(text)
    if cents is None:
        return None
    raw = text.strip()
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")")) or bool(re.search(r"(?i)\bdr\.?$", raw))
    return -cents if negative else cents


def _rupees(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{Decimal(abs(cents)) / Decimal(100):.2f}"


_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check(value: str) -> str | None:
    """None if the GSTIN is well formed with a correct check digit, otherwise the reason it is not."""
    value = value.strip().upper()
    if not GSTIN.fullmatch(value):
        return "not in GSTIN format (15 characters: state code, PAN, entity, Z, check digit)"
    total = 0
    for position, char in enumerate(value[:14]):
        product = _GSTIN_CHARS.index(char) * (2 if position % 2 else 1)
        total += product // 36 + product % 36
    if _GSTIN_CHARS[(36 - total % 36) % 36] != value[14]:
        return "check digit does not match (possible typing error)"
    return None


# --------------------------------------------------------------------------- Tally XML

_CONTROL_REFS = re.compile(rb"&#(?:x0*[0-8bBcCeEfF]|x0*1[0-9a-fA-F]|0*(?:[0-8]|1[1-2]|1[4-9]|2[0-9]|3[01]));")


_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def _tally_root(source: bytes) -> ET.Element:
    if source[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            source = source.decode("utf-16").encode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentReadError("the UTF-16 Tally export is damaged") from exc
        source = re.sub(rb"<\?xml[^>]*\?>", b"", source, count=1)
    # The whole file is checked, not only its start: a declaration anywhere could expand entities.
    if _DECLARATION.search(source):
        raise DocumentReadError("Tally XML must not contain a DOCTYPE or entity declarations")
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
    """Sales-register rows from a Tally XML export, with a report of everything not imported.

    - skipped:  vouchers that are not sales (receipts, orders, returns) or are cancelled/optional.
    - rejected: sales vouchers that could not be read safely (bad date, missing number/party/amount).
    - warnings: imported rows that need a human look (bad GSTIN, repeated voucher number,
                ledger entries that do not balance, party ledger credited instead of debited).
    Nothing is corrected automatically; warnings travel with the import report.
    """
    root = _tally_root(source)
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    numbers: dict[str, int] = {}
    seen = 0
    for voucher in root.iter("VOUCHER"):
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
            rejected.append({"voucher": label, "reason": f"unreadable date {when!r}"})
            continue
        party = _text(voucher, "PARTYLEDGERNAME") or _text(voucher, "PARTYNAME")
        entries = list(voucher.iter("ALLLEDGERENTRIES.LIST")) + list(voucher.iter("LEDGERENTRIES.LIST"))
        signed = [(_text(e, "LEDGERNAME"), parse_signed_cents(_text(e, "AMOUNT"))) for e in entries]
        unreadable = [name or "unnamed ledger" for name, amount in signed if amount is None]
        party_amounts = [amount for name, amount in signed if party and name == party and amount is not None]
        if not number or not party or not party_amounts:
            rejected.append({"voucher": label, "reason": "missing voucher number, party ledger or party amount"})
            continue
        if unreadable:
            rejected.append({"voucher": label, "reason": "unreadable amount on ledger " + ", ".join(unreadable[:3])})
            continue
        gstin = _text(voucher, "PARTYGSTIN") or _text(voucher, "BASICBUYERGSTIN") or ""
        if not gstin:
            for addr in voucher.iter("GSTREGISTRATIONNUMBER"):
                gstin = (addr.text or "").strip()
                break
        if gstin and (problem := gstin_check(gstin)):
            warnings.append({"voucher": number, "reason": f"buyer GSTIN {gstin}: {problem}"})
        balance = sum(amount for _, amount in signed if amount is not None)
        if balance != 0:
            warnings.append({"voucher": number, "reason": f"ledger entries do not balance (difference {_rupees(balance)})"})
        if sum(party_amounts) > 0:
            # In Tally XML a debit is written as a negative amount; a sale debits the customer.
            warnings.append({"voucher": number, "reason": "the customer ledger is credited, not debited; check the voucher type"})
        key = re.sub(r"\s+", "", number.upper())
        if key in numbers:
            warnings.append({"voucher": number, "reason": f"voucher number repeats (also voucher {numbers[key]} in this file)"})
        else:
            numbers[key] = seen
        rows.append({"Bill No": number, "Date": iso, "Customer": party, "Gross Amt": _rupees(abs(sum(party_amounts))), "GST No": gstin})
    if seen == 0:
        raise DocumentReadError("no VOUCHER elements found; export the Day Book or sales vouchers from Tally in XML format")
    return {"rows": rows, "skipped": skipped, "rejected": rejected, "warnings": warnings, "vouchers_seen": seen, "parser": TALLY_PARSER}


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


def _is_amount(text: str) -> bool:
    return bool(AMOUNT.match(text.replace(" ", ""))) and any(c.isdigit() for c in text)


def parse_bank_pdf(source: bytes) -> dict[str, Any]:
    """Transactions from a text-based bank statement PDF, in the same shape as the CSV parser.

    Lines that start with a date are transactions. A line without a date that sits under a
    transaction and has no amounts is a wrapped narration and is joined to it. An "Opening balance"
    line is kept so the running balance can be checked from the first transaction.
    """
    doc = _open_pdf(source)
    rows: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    columns: dict[str, float] | None = None
    opening: int | None = None
    text_found = False
    last_row: dict[str, Any] | None = None
    for page_no, page in enumerate(doc, 1):
        last_row = None  # narration never continues across pages
        for line in _lines(page):
            if not line:
                continue
            text_found = True
            joined = " ".join(t for _, _, t in line)
            header = None if parse_date(line[0][2]) else _header_columns(line)
            if header:
                columns = header
                last_row = None
                continue
            first = line[0][2]
            when = parse_date(first) or (parse_date(" ".join(t for _, _, t in line[:3])) if len(line) >= 3 else None)
            if not when:
                if columns and re.search(r"(?i)\bopening\s+balance\b", joined) and opening is None and not rows:
                    amounts = [t for _, _, t in line if _is_amount(t)]
                    opening = parse_signed_cents(amounts[-1]) if amounts else None
                    continue
                if columns and last_row is not None and not any(_is_amount(t) for _, _, t in line):
                    left_of_money = min(v for k, v in columns.items() if k in ("debit", "credit", "balance")) - 40
                    if all(x1 < left_of_money for _, x1, _ in line) and len(last_row["narration"]) < 300:
                        last_row["narration"] = (last_row["narration"] + " " + joined).strip()[:300]
                        last_row["wrapped_lines"] = last_row.get("wrapped_lines", 0) + 1
                        continue
                last_row = None
                continue
            # A date-led line is a candidate transaction. Amount-looking words are assigned to the
            # nearest money column; everything else is narration.
            if columns is None:
                unread.append({"page": page_no, "text": joined[:200], "reason": "no Debit/Credit/Balance header found above this line"})
                continue
            date_words = 1 if parse_date(first) else 3
            words = line[date_words:]
            value_date = None
            if words and parse_date(words[0][2]):  # a second date is the value date, not narration
                value_date = parse_date(words[0][2])
                words = words[1:]
            narration, reference, debit, credit, balance = [], "", None, None, None
            money_cols = {k: v for k, v in columns.items() if k in ("debit", "credit", "balance")}
            for x0, x1, text in words:
                centre = (x0 + x1) / 2
                cents = parse_amount_cents(text) if _is_amount(text) else None
                nearest = min(money_cols, key=lambda k: abs(money_cols[k] - centre))
                if cents is not None and abs(money_cols[nearest] - centre) < 60 and ("." in text or "," in text or nearest == "balance"):
                    if nearest == "debit":
                        debit = cents
                    elif nearest == "credit":
                        credit = cents
                    else:
                        balance = parse_signed_cents(text)
                elif text.lower().rstrip(".") in ("dr", "cr") and balance is not None and "balance" in money_cols and abs(money_cols["balance"] - centre) < 80:
                    balance = -abs(balance) if text.lower().startswith("dr") else abs(balance)
                elif "reference" in columns and abs(columns["reference"] - centre) < 45 and not reference:
                    reference = text
                else:
                    narration.append(text)
            if (debit is None) == (credit is None):
                unread.append({"page": page_no, "text": joined[:200],
                               "reason": "could not tell whether this is a debit or a credit" if debit and credit else "no amount in a Debit or Credit column"})
                last_row = None
                continue
            narration_text = " ".join(narration)
            if not reference:
                found = re.search(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{8,22}\b", narration_text)
                reference = found.group(0) if found else ""
            last_row = {"row_no": len(rows) + 1, "txn_date": when, "amount_cents": debit or credit, "direction": "debit" if debit else "credit",
                        "narration": narration_text[:300], "reference": reference[:120], "counterparty": "", "balance_cents": balance,
                        "page": page_no, **({"value_date": value_date} if value_date else {})}
            rows.append(last_row)
    if not text_found:
        raise DocumentReadError("the PDF has no text layer (it looks scanned); export a text PDF or CSV from net banking")
    if not rows:
        raise DocumentReadError("no transactions found; the statement needs a header with Debit/Withdrawal and Credit/Deposit columns")
    for row in rows:
        if not row["reference"]:
            found = re.search(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{8,22}\b", row["narration"])
            row["reference"] = found.group(0)[:120] if found else ""
    return {"rows": rows, "unread_lines": unread, "opening_balance_cents": opening, "parser": BANK_PDF_PARSER}


def check_balances(rows: list[dict[str, Any]], opening: int | None = None) -> dict[str, Any]:
    """Recompute the running balance and compare it with the balance printed on each row.

    Statements are listed oldest-first or newest-first; both orders are tried and the one that
    explains more rows is reported. A mismatch is reported, never corrected.
    """
    with_balance = [r for r in rows if r.get("balance_cents") is not None]
    if len(with_balance) < 1 or (len(with_balance) < 2 and opening is None):
        return {"status": "not_available", "checked": 0, "mismatches": []}

    def walk(ordered: list[dict[str, Any]], start: int | None) -> tuple[int, list[dict[str, Any]]]:
        # Each row is checked against the balance printed on the row before it. When a row fails,
        # the recomputed figure is kept too: if the next row agrees with that figure, the earlier
        # printed balance was the odd one out and the next row is not reported a second time.
        checked, mismatches, previous, recomputed = 0, [], start, None
        for row in ordered:
            signed = row["amount_cents"] if row["direction"] == "credit" else -row["amount_cents"]
            if row.get("balance_cents") is None:
                previous = None if previous is None else previous + signed
                recomputed = None if recomputed is None else recomputed + signed
                continue
            if previous is not None:
                checked += 1
                expected = previous + signed
                if expected != row["balance_cents"] and not (recomputed is not None and recomputed + signed == row["balance_cents"]):
                    mismatches.append({"row_no": row["row_no"], "expected": _rupees(expected), "printed": _rupees(row["balance_cents"])})
                    recomputed = expected
                else:
                    recomputed = None
            previous = row["balance_cents"]
        return checked, mismatches

    forward = walk(rows, opening)
    backward = walk(list(reversed(rows)), None)
    checked, mismatches = forward if len(forward[1]) <= len(backward[1]) or opening is not None else backward
    return {"status": "consistent" if not mismatches else "inconsistent", "checked": checked,
            "mismatches": mismatches[:50], "opening_balance": _rupees(opening) if opening is not None else None}


def duplicate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that repeat an earlier row exactly (date, amount, direction, reference, narration).
    Banks do post identical transactions, so these are flagged for review, not removed."""
    seen: dict[tuple, int] = {}
    repeats = []
    for row in rows:
        key = (row["txn_date"], row["amount_cents"], row["direction"], row.get("reference", ""), " ".join(row.get("narration", "").lower().split()))
        if key in seen:
            repeats.append({"row_no": row["row_no"], "same_as_row": seen[key]})
        else:
            seen[key] = row["row_no"]
    return repeats


# --------------------------------------------------------------------------- invoice PDF

_INV_NO = re.compile(r"(?i)\b(?:invoice|inv|bill)\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,39})")
_INV_DATE = re.compile(r"(?i)\b(invoice\s*date|inv\.?\s*date|bill\s*date|date\s*of\s*invoice|dated|date)\s*[:\-]?\s*([0-9]{1,2}[-/. ][A-Za-z0-9]{1,9}[-/. ][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})")
_DATE_RANK = {"invoice date": 0, "inv date": 0, "inv. date": 0, "bill date": 0, "date of invoice": 0, "dated": 1, "date": 2}
_TOTAL = re.compile(r"(?i)\b(grand\s*total|invoice\s*total|total\s*invoice\s*value|total\s*amount(?:\s*payable)?|amount\s*payable|net\s*payable|(?<!sub\s)(?<!sub)total(?!\s*(?:tax|gst|qty|quantity|taxable)))\b[^0-9₹\n]{0,25}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_TOTAL_RANK = {"grand total": 0, "invoice total": 1, "total invoice value": 1, "total amount payable": 2, "amount payable": 2, "net payable": 2, "total amount": 3, "total": 4}
_TAXABLE = re.compile(r"(?i)\b(?:total\s*)?(?:taxable\s*(?:value|amount)|assessable\s*value)\b[^0-9\n]{0,25}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.[0-9]{2})")
_TAX = re.compile(r"(?i)\b(CGST|SGST|UTGST|IGST)\b(?:[^0-9\n]{0,15}\d{1,2}(?:\.\d{1,2})?\s*%\)?)?[^0-9\n]{0,15}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.[0-9]{2})")
_ROUND = re.compile(r"(?i)\bround(?:ing|ed)?\s*off\b[^0-9\n\-(]{0,15}(\(?-?\s*[0-9][0-9,]*\.[0-9]{2}\)?)")


def _pages_text(source: bytes) -> list[str]:
    """Each page as visual lines, so a label and its amount on the same row stay together."""
    doc = _open_pdf(source)
    return ["\n".join(" ".join(t for _, _, t in line) for line in _lines(page)) for page in doc]


def _pick(candidates: list[tuple[int, Any, int]]) -> tuple[Any, int | None, list[Any]]:
    """(rank, value, page) candidates -> (value, page, ambiguous values). Only the best-ranked
    label counts; if it carries different values the field is ambiguous and left unread."""
    if not candidates:
        return None, None, []
    best = min(rank for rank, _, _ in candidates)
    top = [(value, page) for rank, value, page in candidates if rank == best]
    values = list(dict.fromkeys(value for value, _ in top))
    if len(values) > 1:
        return None, None, values
    return values[0], top[0][1], []


def read_invoice_pdf(source: bytes) -> dict[str, Any]:
    """Fields printed on a text invoice PDF, with the page each came from and a GST arithmetic check.

    A field with two different candidate values under the same label is reported as ambiguous and
    left empty; nothing is chosen by guesswork. The reading is company-supplied, never verification.
    """
    pages = _pages_text(source)
    if not any(p.strip() for p in pages):
        raise DocumentReadError("the PDF has no text layer (it looks scanned)")
    found: dict[str, list[tuple[int, Any, int]]] = {k: [] for k in ("invoice_number", "invoice_date", "total", "taxable", "CGST", "SGST", "IGST", "round_off")}
    gstins: dict[str, int] = {}
    for page_no, text in enumerate(pages, 1):
        for m in _INV_NO.finditer(text):
            found["invoice_number"].append((0, m.group(1).strip(), page_no))
        for m in _INV_DATE.finditer(text):
            iso = parse_date(m.group(2))
            if iso:
                found["invoice_date"].append((_DATE_RANK.get(re.sub(r"\s+", " ", m.group(1).lower()), 2), iso, page_no))
        for m in _TOTAL.finditer(text):
            cents = parse_amount_cents(m.group(2))
            if cents:
                found["total"].append((_TOTAL_RANK.get(re.sub(r"\s+", " ", m.group(1).lower()), 5), cents, page_no))
        for m in _TAXABLE.finditer(text):
            found["taxable"].append((0, parse_amount_cents(m.group(1)), page_no))
        for m in _TAX.finditer(text):
            kind = "SGST" if m.group(1).upper() == "UTGST" else m.group(1).upper()
            found[kind].append((0, parse_amount_cents(m.group(2)), page_no))
        for m in _ROUND.finditer(text):
            found["round_off"].append((0, parse_signed_cents(m.group(1).replace(" ", "")), page_no))
        for g in GSTIN.findall(text):
            gstins.setdefault(g, page_no)
    read: dict[str, Any] = {"parser": INVOICE_PDF_PARSER}
    pages_of: dict[str, int] = {}
    ambiguous: dict[str, list[Any]] = {}
    names = {"invoice_number": "invoice_number", "invoice_date": "invoice_date", "total": "total_cents", "taxable": "taxable_cents",
             "CGST": "cgst_cents", "SGST": "sgst_cents", "IGST": "igst_cents", "round_off": "round_off_cents"}
    for key, out in names.items():
        value, page, alternatives = _pick(found[key])
        read[out] = value
        if page:
            pages_of[out] = page
        if alternatives:
            ambiguous[out] = [_rupees(v) if isinstance(v, int) else v for v in alternatives[:5]]
    read["gstins"] = sorted(gstins)
    read["pages"] = pages_of
    read["page_count"] = len(pages)
    if ambiguous:
        read["ambiguous"] = ambiguous
    read["warnings"] = _invoice_warnings(read)
    read["arithmetic"] = _invoice_arithmetic(read)
    return read


def _invoice_warnings(read: dict[str, Any]) -> list[str]:
    warnings = []
    if read.get("igst_cents") and (read.get("cgst_cents") or read.get("sgst_cents")):
        warnings.append("IGST and CGST/SGST are both charged; one supply is either inter-state (IGST) or intra-state (CGST+SGST)")
    if read.get("cgst_cents") is not None and read.get("sgst_cents") is not None and read["cgst_cents"] != read["sgst_cents"]:
        warnings.append("CGST and SGST differ; they are normally equal halves of the same rate")
    if (read.get("cgst_cents") is None) != (read.get("sgst_cents") is None) and not read.get("igst_cents"):
        warnings.append("only one of CGST/SGST was found on the invoice")
    return warnings


def _invoice_arithmetic(read: dict[str, Any]) -> dict[str, Any]:
    """Taxable value + taxes (+ printed round-off) should equal the total. Without a printed
    round-off line, a difference of up to 50 paise is accepted as rounding to the rupee."""
    total, taxable = read.get("total_cents"), read.get("taxable_cents")
    taxes = [read.get(k) for k in ("cgst_cents", "sgst_cents", "igst_cents") if read.get(k) is not None]
    if total is None or taxable is None or not taxes:
        return {"status": "not_checked", "reason": "total, taxable value or tax amounts were not all read"}
    expected = taxable + sum(taxes) + (read.get("round_off_cents") or 0)
    difference = total - expected
    allowed = 0 if read.get("round_off_cents") is not None else 50
    return {"status": "consistent" if abs(difference) <= allowed else "inconsistent",
            "expected_total": _rupees(expected), "difference": _rupees(difference)}


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
    if read.get("taxable_cents") is not None and invoice.get("net_cents") is not None:
        add("taxable_value", _rupees(read["taxable_cents"]), _rupees(invoice["net_cents"]), read["taxable_cents"] == invoice["net_cents"])
    taxes = [read.get(k) for k in ("cgst_cents", "sgst_cents", "igst_cents") if read.get(k) is not None]
    if taxes and invoice.get("tax_cents") is not None:
        add("total_tax", _rupees(sum(taxes)), _rupees(invoice["tax_cents"]), sum(taxes) == invoice["tax_cents"])
    for name in (read.get("ambiguous") or {}):
        label = {"total_cents": "total", "invoice_number": "invoice_number", "invoice_date": "invoice_date"}.get(name)
        if label:
            for f in fields:
                if f["field"] == label:
                    f["result"] = "ambiguous"
                    f["candidates"] = read["ambiguous"][name]
    for f in fields:
        page = (read.get("pages") or {}).get({"total": "total_cents", "taxable_value": "taxable_cents"}.get(f["field"], f["field"]))
        if page:
            f["page"] = page
    results = {f["result"] for f in fields}
    status = "differs" if "differs" in results else ("matches" if results <= {"match", "not_in_books"} and "match" in results else "incomplete")
    return {"status": status, "fields": fields}
