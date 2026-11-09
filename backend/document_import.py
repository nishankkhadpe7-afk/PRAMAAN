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
DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d/%b/%Y", "%d %b %Y", "%d %b, %Y", "%d-%m-%y", "%d/%m/%y",
                "%d.%m.%y", "%d-%b-%y", "%d/%b/%y", "%d %b %y", "%d %B %Y", "%d %B, %Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y")


class DocumentReadError(ValueError):
    """The file is not in a format this reader supports; the message says what was expected."""


# --------------------------------------------------------------------------- shared helpers

_DASHES = str.maketrans({"–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-", " ": " "})
_MONTH_FIXES = ((re.compile(r"(?i)\bsept\b"), "Sep"),)


def _clean(text: str) -> str:
    return " ".join(text.translate(_DASHES).split())


def parse_date(text: str) -> str | None:
    """A calendar date in any common Indian statement/invoice format -> ISO. Day-first is assumed for
    numeric dates (Indian convention); impossible dates return None rather than a guess."""
    text = _clean(text).strip().rstrip(",.")
    for pattern, replacement in _MONTH_FIXES:
        text = pattern.sub(replacement, text)
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if not 1990 <= parsed.year <= 2100:
            return None
        return parsed.isoformat()
    return None


def parse_amount_cents(text: str) -> int | None:
    """'1,18,000.00' / '₹ 4,500' / '(250.00)' / '1200.50 Cr' / '1,000/-' -> cents (sign dropped; callers decide direction)."""
    cleaned = re.sub(r"(?i)(₹|rs\.?|inr|cr\.?|dr\.?|/-|\s)", "", _clean(text)).strip("()-+")
    if not cleaned or not re.fullmatch(r"\d[\d,]*(?:\.\d{1,2})?", cleaned):
        return None
    if "," in cleaned and not re.fullmatch(r"\d{1,3}(?:,\d{2})*,\d{3}(?:\.\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", cleaned):
        return None  # misplaced separators ('1,00,0.00') are a misread, not a number
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
    raw = _clean(text).strip()
    negative = raw.startswith("-") or raw.endswith("-") and not raw.endswith("/-") or (raw.startswith("(") and raw.endswith(")")) or bool(re.search(r"(?i)\bdr\.?$", raw))
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
    sources: list[dict[str, Any]] = []
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
        if not number:
            # Never invented: without the number the voucher can't be matched to a register line.
            rejected.append({"voucher": label, "reason": "no voucher number (an import file can leave it to Tally to assign; export the Day Book from Tally to get the numbers)"})
            continue
        if not party or not party_amounts:
            rejected.append({"voucher": label, "reason": "no party ledger, or no amount on the party ledger"})
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
        # Invoice-view vouchers carry the sales/income line inside each inventory entry (ACCOUNTINGALLOCATIONS.LIST).
        allocations = [parse_signed_cents(_text(a, "AMOUNT")) for a in voucher.iter("ACCOUNTINGALLOCATIONS.LIST")]
        balance = sum(amount for _, amount in signed if amount is not None) + sum(a for a in allocations if a is not None)
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
        sources.append({"row_no": len(rows), "voucher": number, "voucher_index": seen, "remote_id": voucher.get("REMOTEID") or _text(voucher, "GUID") or None})
    if seen == 0:
        raise DocumentReadError("no VOUCHER elements found; export the Day Book or sales vouchers from Tally in XML format")
    return {"rows": rows, "skipped": skipped, "rejected": rejected, "warnings": warnings, "vouchers_seen": seen, "parser": TALLY_PARSER, "sources": sources}


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


Word = tuple  # (x0, y0, x1, y1, text, confidence 0-100; native text is 100)


class PdfText:
    """Words of each page from the PDF's own text layer, or from local OCR when a page is a scan.
    Records which pages needed OCR so every value can say where it came from."""

    def __init__(self, source: bytes):
        self.doc = _open_pdf(source)
        self.ocr_pages: list[int] = []
        self.failed_pages: list[dict[str, Any]] = []
        self._deadline: float | None = None

    def words(self, page_no: int, page) -> list[Word]:
        native = [w for w in page.get_text("words") if w[4].strip()]
        if native:
            return [(w[0], w[1], w[2], w[3], w[4], 100.0) for w in native]
        from . import ocr
        import time
        if self._deadline is None:
            ocr.check_page_budget(self.doc.page_count)
            self._deadline = time.monotonic() + ocr.TOTAL_TIMEOUT_SECONDS
        words = ocr.ocr_page_words(page, self._deadline)
        self.ocr_pages.append(page_no)
        return words

    def pages(self):
        """(page_no, words) for every page; a page OCR could not read is recorded and skipped."""
        from .ocr import OcrFailed, OcrUnavailable
        for page_no, page in enumerate(self.doc, 1):
            try:
                yield page_no, self.words(page_no, page)
            except (OcrUnavailable, OcrFailed) as exc:
                self.failed_pages.append({"page": page_no, "reason": str(exc)})
                if isinstance(exc, OcrFailed) and ("limit" in str(exc) or "up to" in str(exc)):
                    break  # the document-wide budget is spent; later pages would fail the same way

    @property
    def extraction(self) -> str:
        if not self.ocr_pages:
            return "native"
        return "ocr" if len(self.ocr_pages) == self.doc.page_count else "mixed"

    def provenance(self) -> dict[str, Any]:
        info: dict[str, Any] = {"extraction": self.extraction}
        if self.ocr_pages:
            from .ocr import provenance
            info["ocr"] = {**provenance(), "pages": self.ocr_pages}
        return info


def _lines(words: list[Word]) -> list[list[tuple[float, float, str, float]]]:
    """Words grouped into visual lines: [(x0, x1, text, confidence), ...] sorted left to right."""
    lines: list[list[tuple[float, float, str, float]]] = []
    current_y: float | None = None
    for x0, y0, x1, y1, text, conf in sorted(words, key=lambda w: (round((w[1] + w[3]) / 2, 0), w[0])):
        mid = (y0 + y1) / 2
        if current_y is None or abs(mid - current_y) > max(3, (y1 - y0) * 0.45):
            lines.append([])
            current_y = mid
        lines[-1].append((x0, x1, text, conf))
    return [sorted(line) for line in lines]


def pdf_text(source: bytes) -> str:
    doc = _open_pdf(source)
    return "\n".join(page.get_text() for page in doc)


# --------------------------------------------------------------------------- bank statement PDF

_HEADERS = {
    "debit": ("debit", "debits", "withdrawal", "withdrawals", "dr", "paid", "out"),
    "credit": ("credit", "credits", "deposit", "deposits", "cr", "received", "in"),
    "balance": ("balance", "bal"),
    "reference": ("ref", "reference", "chq", "cheque", "utr", "ref.", "chq/ref"),
    "indicator": ("dr/cr", "cr/dr", "d/c", "c/d", "drcr", "type", "txn-type"),
}
_DRCR_WORDS = {"dr": "debit", "cr": "credit", "debit": "debit", "credit": "credit", "d": "debit", "c": "credit",
               "withdrawal": "debit", "deposit": "credit"}


def _header_columns(line: list[tuple[float, float, str, float]]) -> dict[str, Any] | None:
    """Two layouts are recognised from the header row:
    - split:  separate Debit/Withdrawal and Credit/Deposit columns (an amount's column is its direction);
    - amount: one Amount column plus a Dr/Cr indicator (column or suffix) and/or a Balance column.
    Anything else is not treated as a header, so no column is ever assumed."""
    cols: dict[str, float] = {}
    has_date = False
    for x0, x1, text, _ in line:
        word = text.lower().strip(".:()")
        centre = (x0 + x1) / 2
        has_date |= "date" in word
        if word.startswith("amount") or word in ("amt", "amt."):
            cols.setdefault("amount", centre)
            continue
        for key, names in _HEADERS.items():
            if word in names and key not in cols:
                cols[key] = centre
                break
    if {"debit", "credit"} <= cols.keys() and abs(cols["debit"] - cols["credit"]) < 45:
        # 'Dr / Cr' printed as words in one column header is an indicator, not two money columns.
        cols["indicator"] = (cols.pop("debit") + cols.pop("credit")) / 2
    if {"debit", "credit"} <= cols.keys():
        cols.pop("amount", None)  # 'Withdrawal Amt' / 'Deposit Amt' headers
        cols.pop("indicator", None)
        return {"mode": "split", **cols}
    if "amount" in cols and has_date and ({"indicator", "balance"} & cols.keys()):
        cols.pop("debit", None)
        cols.pop("credit", None)
        return {"mode": "amount", **cols}
    return None


def _is_amount(text: str) -> bool:
    return parse_amount_cents(text) is not None and any(c.isdigit() for c in text) and not parse_date(text)


def _drcr_suffix(text: str) -> str | None:
    found = re.search(r"(?i)(dr|cr)\.?$", text.strip())
    return _DRCR_WORDS[found.group(1).lower()] if found and any(c.isdigit() for c in text) else None


def parse_bank_pdf(source: bytes) -> dict[str, Any]:
    """Transactions from a bank statement PDF (text layer, or local OCR for scanned pages).

    Lines that start with a date are transactions. A line without a date that sits under a
    transaction and has no amounts is a wrapped narration and is joined to it. An "Opening balance"
    line is kept so the running balance can be checked from the first transaction.

    Direction of each row comes, in order of preference, from: its column (split layout), a Dr/Cr
    indicator, the sign of the amount, or the change in the printed running balance. A row none of
    these settles is reported as unread, never guessed. OCR words below the confidence threshold
    make a row unread ("needs human review").
    """
    from .ocr import MIN_CONFIDENCE
    text = PdfText(source)
    rows: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    columns: dict[str, Any] | None = None
    layouts: set[str] = set()
    opening: int | None = None
    text_found = False
    last_row: dict[str, Any] | None = None
    for page_no, words in text.pages():
        last_row = None  # narration never continues across pages
        extraction = "ocr" if page_no in text.ocr_pages else "native"
        for line_no, line in enumerate(_lines(words), 1):
            if not line:
                continue
            text_found = True
            joined = " ".join(t for _, _, t, _ in line)
            header = None if parse_date(line[0][2]) else _header_columns(line)
            if header:
                columns = header
                layouts.add(header["mode"])
                last_row = None
                continue
            first = line[0][2]
            when = parse_date(first) or (parse_date(" ".join(t for _, _, t, _ in line[:3])) if len(line) >= 3 else None)
            money_keys = ("debit", "credit", "amount", "balance")
            if not when:
                if columns and re.search(r"(?i)\bopening\s+balance\b", joined) and opening is None and not rows:
                    amounts = [(t, i) for i, (_, _, t, _) in enumerate(line) if _is_amount(t)]
                    if amounts:
                        value_text, index = amounts[-1]
                        after = line[index + 1][2].lower().rstrip(".") if index + 1 < len(line) else ""
                        opening = parse_signed_cents(value_text)
                        if opening is not None and after in ("dr", "cr"):
                            opening = -abs(opening) if after == "dr" else abs(opening)
                    continue
                if columns and last_row is not None and not any(_is_amount(t) for _, _, t, _ in line):
                    left_of_money = min(v for k, v in columns.items() if k in money_keys) - 40
                    if all(x1 < left_of_money for _, x1, _, _ in line) and len(last_row["narration"]) < 300:
                        last_row["narration"] = (last_row["narration"] + " " + joined).strip()[:300]
                        last_row["wrapped_lines"] = last_row.get("wrapped_lines", 0) + 1
                        continue
                last_row = None
                continue
            if columns is None:
                unread.append({"page": page_no, "line": line_no, "text": joined[:200], "reason": "no Debit/Credit or Amount/Dr-Cr header found above this line"})
                continue
            date_words = 1 if parse_date(first) else 3
            tokens = line[date_words:]
            value_date = None
            if tokens and parse_date(tokens[0][2]):  # a second date is the value date, not narration
                value_date = parse_date(tokens[0][2])
                tokens = tokens[1:]
            narration, reference = [], ""
            found: dict[str, int] = {}
            signed_amount: int | None = None
            indicator: str | None = None
            last_money: str | None = None
            low_conf = [t for _, _, t, c in line[:date_words] if c < MIN_CONFIDENCE]
            money_cols = {k: v for k, v in columns.items() if k in money_keys}
            for x0, x1, word, conf in tokens:
                centre = (x0 + x1) / 2
                bare = word.lower().rstrip(".")
                if bare in _DRCR_WORDS and not any(c.isdigit() for c in word):
                    near_indicator = "indicator" in columns and abs(columns["indicator"] - centre) < 45
                    if near_indicator or (last_money in ("amount", "debit", "credit") and len(bare) <= 2):
                        if columns["mode"] == "amount" and (near_indicator or last_money == "amount"):
                            indicator = _DRCR_WORDS[bare]
                            continue
                    if last_money == "balance" and bare in ("dr", "cr"):
                        found["balance"] = -abs(found["balance"]) if bare == "dr" else abs(found["balance"])
                        continue
                cents = parse_amount_cents(word) if _is_amount(word) else None
                nearest = min(money_cols, key=lambda k: abs(money_cols[k] - centre))
                if cents is not None and abs(money_cols[nearest] - centre) < 60 and ("." in word or "," in word or nearest == "balance"):
                    if conf < MIN_CONFIDENCE:
                        low_conf.append(word)
                    if nearest == "balance":
                        found["balance"] = parse_signed_cents(word)
                        if _drcr_suffix(word) == "debit":
                            found["balance"] = -abs(found["balance"])
                    else:
                        found[nearest] = cents
                        if nearest == "amount":
                            signed_amount = parse_signed_cents(word)
                            indicator = _drcr_suffix(word) or indicator
                    last_money = nearest
                elif "reference" in columns and abs(columns["reference"] - centre) < 45 and not reference:
                    reference = word
                else:
                    narration.append(word)
            base = {"page": page_no, "line": line_no, "text": joined[:200]}
            if low_conf:
                unread.append({**base, "reason": f"OCR could not read {', '.join(low_conf[:3])} with confidence; needs human review"})
                last_row = None
                continue
            direction, amount, source_of_direction = None, None, None
            if columns["mode"] == "split":
                if ("debit" in found) == ("credit" in found):
                    unread.append({**base, "reason": "could not tell whether this is a debit or a credit" if found.get("debit") and found.get("credit") else "no amount in a Debit or Credit column"})
                    last_row = None
                    continue
                direction = "debit" if "debit" in found else "credit"
                amount, source_of_direction = found[direction], "column"
            else:
                amount = found.get("amount")
                if not amount:
                    unread.append({**base, "reason": "no amount in the Amount column"})
                    last_row = None
                    continue
                negative = signed_amount is not None and signed_amount < 0
                if indicator and negative and indicator == "credit":
                    unread.append({**base, "reason": "the amount is negative but marked Cr; the two disagree"})
                    last_row = None
                    continue
                if indicator:
                    direction, source_of_direction = indicator, "indicator"
                elif negative:
                    direction, source_of_direction = "debit", "sign"
                else:
                    source_of_direction = "pending"
            narration_text = " ".join(narration)
            last_row = {"row_no": len(rows) + 1, "txn_date": when, "amount_cents": amount, "direction": direction,
                        "narration": narration_text[:300], "reference": reference[:120], "counterparty": "", "balance_cents": found.get("balance"),
                        "page": page_no, "line": line_no, "extraction": extraction, "direction_source": source_of_direction,
                        **({"value_date": value_date} if value_date else {})}
            rows.append(last_row)
    if not text_found:
        if text.failed_pages:
            raise DocumentReadError(text.failed_pages[0]["reason"])
        raise DocumentReadError("the PDF has no readable text; export a text PDF or CSV from net banking")
    rows, unread = _settle_by_balance(rows, unread, opening)
    unread += [{**f, "reason": "page not read: " + f["reason"]} for f in text.failed_pages]
    if not rows:
        reasons = {u["reason"] for u in unread}
        if any("Dr/Cr" in r or "credit" in r for r in reasons) and "amount" in layouts:
            raise DocumentReadError("the statement has one Amount column but no Dr/Cr indicator, sign or running balance to tell debits from credits")
        if text.failed_pages:
            raise DocumentReadError(text.failed_pages[0]["reason"])
        raise DocumentReadError("no transactions found; the statement needs a header with Debit/Credit columns, or an Amount column with Dr/Cr or Balance")
    for index, row in enumerate(rows, 1):
        row["row_no"] = index
        if not row["reference"]:
            found_ref = re.search(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{8,22}\b", row["narration"])
            row["reference"] = found_ref.group(0)[:120] if found_ref else ""
    return {"rows": rows, "unread_lines": unread, "opening_balance_cents": opening, "parser": BANK_PDF_PARSER,
            "layout": "+".join(sorted(layouts)) or None, **text.provenance()}


def _settle_by_balance(rows: list[dict[str, Any]], unread: list[dict[str, Any]], opening: int | None) -> tuple[list, list]:
    """An unsigned amount with no Dr/Cr marker gets its direction only if the printed running balance
    proves it: the balance moved by exactly +amount (credit) or -amount (debit). Otherwise unread."""
    if not any(r["direction_source"] == "pending" for r in rows):
        return rows, unread
    newest_first = len(rows) > 1 and rows[0]["txn_date"] > rows[-1]["txn_date"]
    settled = []
    for index, row in enumerate(rows):
        if row["direction_source"] != "pending":
            settled.append(row)
            continue
        if newest_first:
            before = rows[index + 1]["balance_cents"] if index + 1 < len(rows) else None
        else:
            before = rows[index - 1]["balance_cents"] if index > 0 else opening
        after = row["balance_cents"]
        delta = None if before is None or after is None else after - before
        if delta == row["amount_cents"]:
            row.update(direction="credit", direction_source="balance")
        elif delta == -row["amount_cents"]:
            row.update(direction="debit", direction_source="balance")
        else:
            unread.append({"page": row["page"], "line": row["line"], "text": f"{row['txn_date']} {row['narration']} {_rupees(row['amount_cents'])}"[:200],
                           "reason": "no Dr/Cr marker or sign, and the running balance does not show the direction"})
            continue
        settled.append(row)
    return settled, unread


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
    """Rows that repeat an earlier row exactly (date, amount, direction, reference, narration, and the
    running balance when printed). Two same-day "Food 56" payments that each move the balance are two real
    payments; a line printed twice repeats its balance too. Flagged for review, never removed."""
    seen: dict[tuple, int] = {}
    repeats = []
    for row in rows:
        key = (row["txn_date"], row["amount_cents"], row["direction"], row.get("reference", ""), " ".join(row.get("narration", "").lower().split()),
               row.get("balance_cents"))
        if key in seen:
            repeats.append({"row_no": row["row_no"], "same_as_row": seen[key]})
        else:
            seen[key] = row["row_no"]
    return repeats


# --------------------------------------------------------------------------- invoice PDF

_INV_NO = re.compile(r"(?i)\b(?:invoice|inv|bill)\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-'’]{1,39}[A-Z0-9])")
_INV_DATE = re.compile(r"(?i)\b(invoice\s*date|inv\.?\s*date|bill\s*date|date\s*of\s*invoice|dated|date)\s*[:\-]?\s*([0-9]{1,2}[-/. ][A-Za-z0-9]{1,9}[-/. ][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})")
_DATE_RANK = {"invoice date": 0, "inv date": 0, "inv. date": 0, "bill date": 0, "date of invoice": 0, "dated": 1, "date": 2}
_TOTAL = re.compile(r"(?i)\b(grand\s*total|invoice\s*total|total\s*invoice\s*value|total\s*amount(?:\s*payable)?|amount\s*payable|net\s*payable|(?<!sub\s)(?<!sub)total(?!\s*(?:tax|gst|qty|quantity|taxable)))\b[^0-9₹\n]{0,25}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_TOTAL_RANK = {"grand total": 0, "invoice total": 1, "total invoice value": 1, "total amount payable": 2, "amount payable": 2, "net payable": 2, "total amount": 3, "total": 4}
_TAXABLE = re.compile(r"(?i)\b(?:total\s*)?(?:taxable\s*(?:value|amount)|assessable\s*value)\b[^0-9\n]{0,25}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.[0-9]{2})")
# Weaker labels, used only when the stronger ones are absent: "Subtotal" for the taxable value, and a single combined
# GST line (small-trader bills often print "GST" / "Total GST" with no CGST/SGST/IGST split). Never "GSTIN".
_SUBTOTAL = re.compile(r"(?i)\bsub\s*-?\s*total\b(?:\s*\((?:before|excl\.?|excluding)\s*(?:gst|tax)\))?[^0-9\n]{0,20}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.[0-9]{2})")
_GST_TOTAL = re.compile(r"(?i)(?<![A-Z])(?:total\s*)?gst(?:\s*amount)?(?![A-Z])(?:[^0-9\n]{0,15}\d{1,2}(?:\.\d{1,2})?\s*%\)?)?[^0-9\n]{0,15}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.[0-9]{2})")
_TAX = re.compile(r"(?i)\b(CGST|SGST|UTGST|IGST)\b(?:[^0-9\n]{0,15}\d{1,2}(?:\.\d{1,2})?\s*%\)?)?[^0-9\n]{0,15}(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*\.[0-9]{2})")
_ROUND = re.compile(r"(?i)\bround(?:ing|ed)?\s*off\b[^0-9\n\-(]{0,15}(\(?-?\s*[0-9][0-9,]*\.[0-9]{2}\)?)")


def _pages_text(text: PdfText) -> list[tuple[int, str, set[str]]]:
    """(page_no, visual-line text, words OCR read with low confidence) per page, so a label and its
    amount on the same row stay together."""
    from .ocr import MIN_CONFIDENCE
    pages = []
    for page_no, words in text.pages():
        lines = _lines(words)
        pages.append((page_no, "\n".join(" ".join(t for _, _, t, _ in line) for line in lines),
                      {t for line in lines for _, _, t, c in line if c < MIN_CONFIDENCE}))
    return pages


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
    text = PdfText(source)
    pages = _pages_text(text)
    if not any(p.strip() for _, p, _ in pages):
        if text.failed_pages:
            raise DocumentReadError(text.failed_pages[0]["reason"])
        raise DocumentReadError("the PDF has no readable text")
    found: dict[str, list[tuple[int, Any, int]]] = {k: [] for k in ("invoice_number", "invoice_date", "total", "taxable", "CGST", "SGST", "IGST", "round_off", "GST_TOTAL")}
    uncertain: dict[str, list[str]] = {}
    gstins: dict[str, int] = {}

    def keep(key: str, match: re.Match, low: set[str]) -> bool:
        """An OCR match that contains a low-confidence word is set aside for human review."""
        doubtful = [w for w in match.group(0).split() if w in low]
        if doubtful:
            uncertain.setdefault(key, []).append(match.group(0)[:80])
        return not doubtful

    for page_no, page_text, low in pages:
        for m in _INV_NO.finditer(page_text):
            if keep("invoice_number", m, low):
                found["invoice_number"].append((0, re.sub(r"['’]", "/", m.group(1).strip()), page_no))  # OCR often reads "/" as an apostrophe
        for m in _INV_DATE.finditer(page_text):
            iso = parse_date(m.group(2))
            if iso and keep("invoice_date", m, low):
                found["invoice_date"].append((_DATE_RANK.get(re.sub(r"\s+", " ", m.group(1).lower()), 2), iso, page_no))
        for m in _TOTAL.finditer(page_text):
            cents = parse_amount_cents(m.group(2))
            if cents and keep("total", m, low):
                found["total"].append((_TOTAL_RANK.get(re.sub(r"\s+", " ", m.group(1).lower()), 5), cents, page_no))
        for m in _TAXABLE.finditer(page_text):
            if keep("taxable", m, low):
                found["taxable"].append((0, parse_amount_cents(m.group(1)), page_no))
        for m in _SUBTOTAL.finditer(page_text):
            if keep("taxable", m, low):
                found["taxable"].append((1, parse_amount_cents(m.group(1)), page_no))  # rank 1: an explicit taxable value wins
        for m in _GST_TOTAL.finditer(page_text):
            if keep("GST_TOTAL", m, low):
                found["GST_TOTAL"].append((0, parse_amount_cents(m.group(1)), page_no))
        for m in _TAX.finditer(page_text):
            kind = "SGST" if m.group(1).upper() == "UTGST" else m.group(1).upper()
            if keep(kind, m, low):
                found[kind].append((0, parse_amount_cents(m.group(2)), page_no))
        for m in _ROUND.finditer(page_text):
            if keep("round_off", m, low):
                found["round_off"].append((0, parse_signed_cents(m.group(1).replace(" ", "")), page_no))
        for g in GSTIN.findall(page_text):
            if g not in low:
                gstins.setdefault(g, page_no)
    read: dict[str, Any] = {"parser": INVOICE_PDF_PARSER}
    pages_of: dict[str, int] = {}
    ambiguous: dict[str, list[Any]] = {}
    names = {"invoice_number": "invoice_number", "invoice_date": "invoice_date", "total": "total_cents", "taxable": "taxable_cents",
             "CGST": "cgst_cents", "SGST": "sgst_cents", "IGST": "igst_cents", "round_off": "round_off_cents", "GST_TOTAL": "gst_total_cents"}
    for key, out in names.items():
        value, page, alternatives = _pick(found[key])
        read[out] = value
        if page:
            pages_of[out] = page
        if alternatives:
            ambiguous[out] = [_rupees(v) if isinstance(v, int) else v for v in alternatives[:5]]
    read["gstins"] = sorted(gstins)
    read["pages"] = pages_of
    read["page_count"] = text.doc.page_count
    read.update(text.provenance())
    if uncertain:
        names_out = {"total": "total_cents", "taxable": "taxable_cents", "CGST": "cgst_cents", "SGST": "sgst_cents", "IGST": "igst_cents", "round_off": "round_off_cents", "GST_TOTAL": "gst_total_cents"}
        read["uncertain"] = {names_out.get(k, k): v[:3] for k, v in uncertain.items()}
    if text.failed_pages:
        read["unread_pages"] = text.failed_pages
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
    if not taxes and read.get("gst_total_cents") is not None:
        taxes = [read["gst_total_cents"]]  # a single combined GST line, only when no split is printed
    if total is None or taxable is None or not taxes:
        return {"status": "not_checked", "reason": "total, taxable value or tax amounts were not all read"}
    expected = taxable + sum(taxes) + (read.get("round_off_cents") or 0)
    difference = total - expected
    allowed = 0 if read.get("round_off_cents") is not None else 50
    return {"status": "consistent" if abs(difference) <= allowed else "inconsistent",
            "expected_total": _rupees(expected), "difference": _rupees(difference)}


def _norm_bill(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


# --------------------------------------------------------------------------- field quality

READ_FIELDS = ("invoice_number", "invoice_date", "total_cents", "taxable_cents", "cgst_cents", "sgst_cents", "igst_cents", "gst_total_cents", "round_off_cents", "gstins")
MONEY_FIELDS = {"total_cents", "taxable_cents", "cgst_cents", "sgst_cents", "igst_cents", "gst_total_cents", "round_off_cents"}

# Every state is decided by a fixed rule from recorded evidence; there are no percentages.
FIELD_STATES = {
    "human_verified": "A person with the human-review credential looked at the document and recorded this value (who, when, note).",
    "ambiguous": "The same label printed two or more different values; none was chosen.",
    "unreadable": "No value was found under a recognised label, or OCR read it with low confidence. Needs a person.",
    "ocr": "Read by local OCR from a scanned page. Must be checked by a person before it is relied on.",
    "validated": "Read exactly from the PDF's text layer and confirmed by an independent check (GST arithmetic for amounts, the GSTIN check digit for GSTINs).",
    "exact": "Read from the PDF's text layer under a recognised label, with a single value, on the page shown.",
}


def field_value(read: dict[str, Any], field: str, verifications: dict[str, dict[str, Any]] | None = None) -> Any:
    verified = (verifications or {}).get(field)
    return verified["value"] if verified else read.get(field)


def field_quality(read: dict[str, Any], verifications: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """State and evidence for each invoice field. Precedence: human_verified > ambiguous > unreadable >
    ocr > validated > exact."""
    verifications = verifications or {}
    ocr_pages = set((read.get("ocr") or {}).get("pages") or [])
    arithmetic_ok = (read.get("arithmetic") or {}).get("status") == "consistent"
    out: dict[str, dict[str, Any]] = {}
    for field in READ_FIELDS:
        page = (read.get("pages") or {}).get(field)
        value = read.get(field)
        if field in verifications:
            v = verifications[field]
            out[field] = {"state": "human_verified", "evidence": {k: v[k] for k in ("verified_by", "verified_at", "note", "verification_id") if k in v}}
        elif "error" in read:
            out[field] = {"state": "unreadable", "evidence": {"reason": read["error"]}}
        elif field in (read.get("ambiguous") or {}):
            out[field] = {"state": "ambiguous", "evidence": {"candidates": read["ambiguous"][field]}}
        elif value in (None, [], ""):
            reason = "OCR read it with low confidence: " + "; ".join(read["uncertain"][field]) if field in (read.get("uncertain") or {}) else "not printed under a recognised label"
            out[field] = {"state": "unreadable", "evidence": {"reason": reason}}
        elif field == "gstins":
            pages_used = ocr_pages if read.get("extraction") == "ocr" else set()
            if pages_used:
                out[field] = {"state": "ocr", "evidence": {"engine": (read.get("ocr") or {}).get("engine")}}
            elif all(gstin_check(g) is None for g in value):
                out[field] = {"state": "validated", "evidence": {"check": "GSTIN format and check digit"}}
            else:
                out[field] = {"state": "exact", "evidence": {"note": "a GSTIN on the document fails the check digit"}}
        elif page in ocr_pages or field in (read.get("uncertain") or {}):
            out[field] = {"state": "ocr", "evidence": {"page": page, "engine": (read.get("ocr") or {}).get("engine"),
                                                       **({"also_uncertain": read["uncertain"][field]} if field in (read.get("uncertain") or {}) else {})}}
        elif field in MONEY_FIELDS and arithmetic_ok:
            out[field] = {"state": "validated", "evidence": {"page": page, "check": "taxable value + tax + round-off = total"}}
        else:
            out[field] = {"state": "exact", "evidence": {"page": page}}
    return out


def parse_verified_value(field: str, value: str) -> Any:
    """Normalise a value a reviewer typed, so it compares like a read value."""
    if field not in READ_FIELDS:
        raise ValueError("unknown field")
    if field in MONEY_FIELDS:
        cents = parse_signed_cents(value) if field == "round_off_cents" else parse_amount_cents(value)
        if cents is None:
            raise ValueError("amount must be a number such as 1,18,000.00")
        return cents
    if field == "invoice_date":
        iso = parse_date(value)
        if not iso:
            raise ValueError("date must be a valid date such as 12-04-2025")
        return iso
    if field == "gstins":
        items = sorted({g.strip().upper() for g in re.split(r"[,\s]+", value) if g.strip()})
        bad = [g for g in items if gstin_check(g)]
        if not items or bad:
            raise ValueError("GSTIN is not valid: " + ", ".join(bad or ["empty"]))
        return items
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 40:
        raise ValueError("invoice number must be 1-40 characters")
    return cleaned


def compare_invoice(read: dict[str, Any], invoice: dict[str, Any] | None, verifications: dict[str, dict[str, Any]] | None = None,
                    register_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Field-by-field comparison with the invoice in the frozen snapshot (and, when given, the sales
    register rows for the same bill). 'not_read' and 'ambiguous' never count as a match, and an
    OCR-read match is reported as needing review until a person verifies the field."""
    quality = field_quality(read, verifications)
    if not invoice:
        return {"status": "no_invoice_in_snapshot", "fields": [], "quality": quality}
    fields = []
    value = lambda f: field_value(read, f, verifications)  # noqa: E731

    def add(name: str, source_field: str, document_value: Any, book_value: Any, same: bool | None) -> None:
        state = quality[source_field]["state"]
        result = ("ambiguous" if state == "ambiguous" else "not_in_books" if book_value in (None, "") else
                  "not_read" if document_value in (None, [], "") else "match" if same else "differs")
        entry = {"field": name, "document": document_value, "books": book_value, "result": result, "quality": state}
        if state == "ambiguous":
            entry["candidates"] = quality[source_field]["evidence"]["candidates"]
        page = (read.get("pages") or {}).get(source_field)
        if page:
            entry["page"] = page
        fields.append(entry)

    add("invoice_number", "invoice_number", value("invoice_number"), invoice.get("bill_no"), _norm_bill(value("invoice_number")) == _norm_bill(invoice.get("bill_no")))
    add("invoice_date", "invoice_date", value("invoice_date"), invoice.get("invoice_date"), value("invoice_date") == invoice.get("invoice_date"))
    gross, total = invoice.get("gross_cents"), value("total_cents")
    add("total", "total_cents", _rupees(total) if total else None, _rupees(gross) if gross is not None else None, total == gross)
    buyer = invoice.get("gstin") or invoice.get("buyer_gstin")
    add("buyer_gstin", "gstins", ", ".join(value("gstins") or []) or None, buyer, buyer in (value("gstins") or []))
    if value("taxable_cents") is not None and invoice.get("net_cents") is not None:
        add("taxable_value", "taxable_cents", _rupees(value("taxable_cents")), _rupees(invoice["net_cents"]), value("taxable_cents") == invoice["net_cents"])
    taxes = [value(k) for k in ("cgst_cents", "sgst_cents", "igst_cents") if value(k) is not None]
    tax_field = next((k for k in ("igst_cents", "cgst_cents", "sgst_cents") if value(k) is not None), "igst_cents")
    if not taxes and value("gst_total_cents") is not None:
        taxes, tax_field = [value("gst_total_cents")], "gst_total_cents"
    if taxes and invoice.get("tax_cents") is not None:
        add("total_tax", tax_field, _rupees(sum(taxes)), _rupees(invoice["tax_cents"]), sum(taxes) == invoice["tax_cents"])
    cross: dict[str, Any] = {}
    if register_rows is not None:
        amounts = sorted({r["amount_cents"] for r in register_rows if r.get("amount_cents") is not None})
        if len(register_rows) > 1:
            cross["register_duplicates"] = len(register_rows)
        if register_rows:
            add("register_amount", "total_cents", _rupees(total) if total else None, ", ".join(_rupees(a) for a in amounts) or None,
                total is not None and amounts == [total])
            cross["register_rows"] = [{k: r.get(k) for k in ("upload_id", "row_no", "row_hash")} for r in register_rows[:5]]
        else:
            cross["register"] = "this bill number is not in the selected sales register"
    results = {f["result"] for f in fields}
    needs_review = any(f["result"] == "match" and f["quality"] == "ocr" for f in fields)
    if "differs" in results:
        status = "differs"
    elif results <= {"match", "not_in_books"} and "match" in results:
        status = "needs_review" if needs_review else "matches"
    else:
        status = "incomplete"
    return {"status": status, "fields": fields, "quality": quality, **({"cross_checks": cross} if cross else {})}
