"""Reader for a Tally Sales Register exported to Excel (.xlsx).

Tally's layout depends on its settings (columnar or not, which tax columns show), so the reader looks for the
header instead of assuming fixed positions: it handles merged and two-row headers, company/period lines above the
header, repeated headers, subtotal and grand-total rows, blank rows, Indian digit grouping and Dr/Cr suffixes.

Every non-blank row ends up in exactly one list:
  rows      sales invoices and credit notes in PRAMAAN's register schema (Bill No, Date, Customer, Gross Amt,
            GST No, plus Taxable/CGST/SGST/IGST/Cess when the register has them). Credit notes and sales returns
            are written with a negative gross.
  skipped   lines that are not vouchers: repeated headers, totals, cancelled vouchers. Totals are checked
            against the rows above them and a mismatch is a warning.
  rejected  voucher lines that could not be read safely (no voucher number, unreadable date or amount).
Nothing is invented: a value that cannot be read is never guessed.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .document_import import DocumentReadError, gstin_check

PARSER = "pramaan-tally-register-xlsx-v1"
MAX_ROWS = 200_000

# Header label (lowercase, spaces collapsed) -> field. The first match wins, so order matters.
_LABELS = [
    ("date", ("date", "voucher date", "invoice date", "vch date", "bill date")),
    ("bill", ("vch no.", "vch no", "voucher no.", "voucher no", "voucher number", "bill no.", "bill no", "invoice no.", "invoice no", "invoice number", "inv no")),
    ("vtype", ("vch type", "voucher type", "type")),
    ("party", ("particulars", "party name", "party", "customer", "customer name", "buyer", "name of party", "ledger")),
    ("gstin", ("gstin/uin", "gstin", "gst no", "gst no.", "party gstin", "gstin of party", "buyer gstin")),
    ("taxable", ("taxable value", "taxable amount", "assessable value", "value", "sales", "net amount")),
    ("cgst", ("cgst", "central tax", "cgst amount", "output cgst")),
    ("sgst", ("sgst", "state tax", "sgst/utgst", "utgst", "sgst amount", "output sgst")),
    ("igst", ("igst", "integrated tax", "igst amount", "output igst")),
    ("cess", ("cess", "cess amount")),
    ("total", ("gross total", "total", "invoice value", "invoice amount", "total amount", "debit", "amount")),
]
_TOTAL_WORDS = re.compile(r"(?i)^\s*(grand\s*total|sub[\s-]*total|total|opening balance|closing balance|carried over|brought forward|c/f|b/f)\b")
_CREDIT_TYPES = re.compile(r"(?i)credit\s*note|sales\s*return|return")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _field_for(text: str) -> str | None:
    if not text:
        return None
    for field in ("cgst", "sgst", "igst", "cess"):  # e.g. "Output CGST @9%", "CGST 9%"
        if re.search(rf"\b{field}\b", text) or (field == "sgst" and "utgst" in text):
            return field
    for field, names in _LABELS:
        for name in names:
            # One-word labels ("amount", "value", "type") must match exactly: "Tax Amount" is not the total.
            if text == name or (" " in name and text.endswith(" " + name)):
                return field
    return None


def _grid(sheet) -> list[list[Any]]:
    """Cell values with merged ranges filled in, so a header merged across columns labels each of them."""
    rows = [list(r) for r in sheet.iter_rows(values_only=True, max_row=min(sheet.max_row or 0, MAX_ROWS))]
    for merged in sheet.merged_cells.ranges:
        value = sheet.cell(merged.min_row, merged.min_col).value
        for r in range(merged.min_row, min(merged.max_row, len(rows)) + 1):
            for c in range(merged.min_col, merged.max_col + 1):
                while len(rows[r - 1]) < c:
                    rows[r - 1].append(None)
                rows[r - 1][c - 1] = value
    return rows


def _find_header(grid: list[list[Any]]) -> tuple[int, int, dict[int, str]] | None:
    """(first header row, rows the header spans, column -> field) for the first row naming a date and a voucher number."""
    for r in range(min(len(grid), 40)):
        best = None
        if all(v in (None, "") for v in grid[r]):
            continue  # a header never starts on a blank line
        for span in (1, 2):
            if r + span > len(grid):
                continue
            width = max(len(grid[r + k]) for k in range(span))
            columns: dict[int, str] = {}
            for c in range(width):
                parts = [_label(grid[r + k][c]) if c < len(grid[r + k]) else "" for k in range(span)]
                # Try the lower line, then the two lines joined ("Tax Amount" over "CGST").
                field = _field_for(parts[-1]) or _field_for(" ".join(p for p in parts if p))
                if field and field not in columns.values():
                    columns[c] = field
            if {"date", "bill"} <= set(columns.values()) and ({"total", "taxable"} & set(columns.values())):
                if best is None or len(columns) > len(best[2]):  # a second header line that adds tax columns wins
                    best = (r, span, columns)
        if best:
            return best
    return None


def _date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d{1,2})[-/. ]([A-Za-z]{3})[A-Za-z]*[-/. ](\d{2}|\d{4})", text)  # Tally style: 1-Apr-25
    try:
        if m:
            year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
            return date(year, _MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)  # Tally exports are day-first
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text).isoformat()
    except (ValueError, KeyError):
        return None
    return None


def _cents(value: Any) -> int | None:
    """Exact cents from a number cell or text like '1,18,000.00', '(500.00)', '1,180.00 Dr'. None if unreadable."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        amount = Decimal(str(value))
    else:
        text = str(value).strip().replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
        negative = text.startswith("(") and text.endswith(")") or text.startswith("-")
        text = re.sub(r"(?i)\s*(dr|cr)\.?$", "", text.strip("()").lstrip("-").strip())
        if not re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{2})*(?:,[0-9]{3})|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+", text.split(".")[0]) or text.count(".") > 1:
            return None
        try:
            amount = Decimal(text.replace(",", "")) * (-1 if negative else 1)
        except InvalidOperation:
            return None
    cents = amount * 100
    return int(cents) if cents == cents.to_integral_value() else None


def _money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}{Decimal(abs(cents)) / 100:.2f}"


_TAX_LEDGER = re.compile(r"(?i)\b(cgst|sgst|utgst|igst|cess)\b")
_ROUND_LEDGER = re.compile(r"(?i)round(ing)?[\s-]*off")


def _voucher_template(grid: list[list[Any]]) -> dict[str, int] | None:
    """Tally's official Excel voucher format ("Accounting Voucher" sheet): one voucher spans several rows, one per
    ledger line. Returns the needed column positions if row 1 is that header."""
    if not grid:
        return None
    labels = {_label(v): i for i, v in enumerate(grid[0]) if v not in (None, "")}
    need = {"date": "voucher date", "type": "voucher type name", "number": "voucher number", "ledger": "ledger name",
            "amount": "ledger amount", "drcr": "ledger amount dr/cr"}
    if not all(v in labels for v in need.values()):
        return None
    cols = {k: labels[v] for k, v in need.items()}
    gst = next((i for t, i in labels.items() if "gstin" in t), None)
    if gst is not None:
        cols["gstin"] = gst
    if "item amount" in labels:
        cols["item_amount"] = labels["item amount"]
    return cols


def _parse_voucher_template(sheet_title: str, grid: list[list[Any]], cols: dict[str, int], out: dict[str, list]) -> None:
    cell = lambda row, key: row[cols[key]] if key in cols and cols[key] < len(row) else None
    vouchers: list[dict[str, Any]] = []
    for index in range(1, len(grid)):
        row = grid[index]
        if all(v in (None, "") for v in row):
            continue
        if cell(row, "date") not in (None, "") or cell(row, "number") not in (None, ""):
            vouchers.append({"start": index + 1, "date": cell(row, "date"), "type": str(cell(row, "type") or ""), "number": str(cell(row, "number") or "").strip(),
                             "gstin": re.sub(r"\s+", "", str(cell(row, "gstin") or "")).upper(), "lines": [], "items": 0, "bad": []})
        if not vouchers:
            out["rejected"].append({"sheet": sheet_title, "source_row": index + 1, "reason": "ledger line before any voucher header row"})
            continue
        v = vouchers[-1]
        name = str(cell(row, "ledger") or "").strip()
        if name:
            amount, side = _cents(cell(row, "amount")), str(cell(row, "drcr") or "").strip().lower()
            if amount is None or side not in ("dr", "cr"):
                v["bad"].append(f"row {index + 1}: unreadable ledger amount or Dr/Cr for {name}")
            else:
                v["lines"].append((name, abs(amount), side))
        item = _cents(cell(row, "item_amount")) if "item_amount" in cols else 0
        if item is None:
            v["bad"].append(f"row {index + 1}: unreadable item amount")
        elif item:
            v["items"] += abs(item)
    for v in vouchers:
        where = {"sheet": sheet_title, "source_row": v["start"]}
        label = v["number"] or f"row {v['start']}"
        vtype = v["type"].lower()
        if "sales" not in vtype and "credit" not in vtype:
            out["skipped"].append({**where, "voucher": label, "reason": f"not a sales voucher ({v['type'] or 'type missing'})"})
            continue
        if not v["number"]:
            out["rejected"].append({**where, "reason": "voucher number missing"})
            continue
        iso = _date(v["date"])
        if iso is None:
            out["rejected"].append({**where, "voucher": label, "reason": f"unreadable date {v['date']!r}"})
            continue
        if v["bad"] or not v["lines"]:
            out["rejected"].append({**where, "voucher": label, "reason": "; ".join(v["bad"]) or "no ledger lines"})
            continue
        credit_note = "credit" in vtype or "return" in vtype
        party_side = "cr" if credit_note else "dr"
        party = next(((n, a) for n, a, s in v["lines"] if s == party_side), None)
        if party is None:
            out["rejected"].append({**where, "voucher": label, "reason": f"no {party_side.title()} party line"})
            continue
        other = [(n, a, s) for n, a, s in v["lines"] if (n, a, s) != (party[0], party[1], party_side)]
        tax = {k: sum(a for n, a, s in other if re.search(rf"(?i)\b{k}\b", n) or (k == "sgst" and "utgst" in n.lower())) for k in ("cgst", "sgst", "igst", "cess")}
        taxable = sum(a for n, a, s in other if not _TAX_LEDGER.search(n) and not _ROUND_LEDGER.search(n))
        dr = sum(a for n, a, s in v["lines"] if s == "dr")
        cr = sum(a for n, a, s in v["lines"] if s == "cr")
        if dr != cr:
            out["warnings"].append({**where, "voucher": label, "reason": f"Dr {_money(dr)} and Cr {_money(cr)} do not balance"})
        if v["items"] and v["items"] != taxable:
            out["warnings"].append({**where, "voucher": label, "reason": f"item amounts ({_money(v['items'])}) do not equal the sales ledger ({_money(taxable)})"})
        if v["gstin"] and (problem := gstin_check(v["gstin"])):
            out["warnings"].append({**where, "voucher": label, "reason": f"buyer GSTIN: {problem}"})
        sign = -1 if credit_note else 1
        row = {"Bill No": v["number"], "Date": iso, "Customer": party[0], "Gross Amt": _money(sign * party[1]), "GST No": v["gstin"], "Taxable": _money(sign * taxable),
               "CGST": _money(sign * tax["cgst"]), "SGST": _money(sign * tax["sgst"]), "IGST": _money(sign * tax["igst"])}
        if tax["cess"]:
            row["Cess"] = _money(sign * tax["cess"])
        out["rows"].append(row)
        out["sources"].append({"row_no": len(out["rows"]), **where, "voucher": v["number"], "voucher_type": v["type"], "status": "credit_note" if credit_note else "sale", "layout": "tally-voucher-template"})


def parse_tally_register(source: bytes) -> dict[str, Any]:
    if not source.startswith(b"PK"):
        raise DocumentReadError("not an .xlsx file; in Tally choose Export > Excel (.xlsx). Old .xls files are not supported")
    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(source), data_only=True)
    except Exception as exc:  # openpyxl raises many types for damaged files
        raise DocumentReadError("the Excel file could not be opened") from exc
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
    numbers: dict[str, str] = {}
    for sheet in book.worksheets:
        if sheet.sheet_state != "visible":
            # Hidden sheets are not read as register data, but they are reported.
            warnings.append({"sheet": sheet.title, "reason": f"{sheet.sheet_state} sheet not read"})
            continue
        grid = _grid(sheet)
        if (template := _voucher_template(grid)) is not None:
            _parse_voucher_template(sheet.title, grid, template, {"rows": rows, "skipped": skipped, "rejected": rejected, "warnings": warnings, "sources": sources})
            sheets.append({"sheet": sheet.title, "header_row": 1, "header_rows": 1, "layout": "tally-voucher-template", "columns": sorted(template)})
            continue
        header = _find_header(grid)
        if header is None:
            sheets.append({"sheet": sheet.title, "header": None, "rows": 0})
            if any(any(v not in (None, "") for v in r) for r in grid):
                warnings.append({"sheet": sheet.title, "reason": "no register header found (needs Date, voucher number and an amount column)"})
            continue
        start, span, columns = header
        header_labels = [_label(v) for v in grid[start + span - 1]]
        found = sorted(set(columns.values()))
        sheets.append({"sheet": sheet.title, "header_row": start + 1, "header_rows": span, "columns": found})
        tax_fields = [f for f in ("taxable", "cgst", "sgst", "igst", "cess") if f in found]
        sheet_sum = since = 0  # to check grand totals and subtotals against the rows they cover
        for index in range(start + span, len(grid)):
            raw = grid[index]
            excel_row = index + 1
            cells = {field: (raw[c] if c < len(raw) else None) for c, field in columns.items()}
            if all(v in (None, "") for v in raw):
                continue
            where = {"sheet": sheet.title, "source_row": excel_row}
            if [_label(v) for v in raw[:len(header_labels)]] == header_labels or sum(_field_for(_label(v)) is not None for v in raw) >= 3:
                skipped.append({**where, "reason": "repeated header"})
                continue
            party = str(cells.get("party") or "").strip()
            bill = str(cells.get("bill") or "").strip()
            if _TOTAL_WORDS.match(party) or _TOTAL_WORDS.match(bill) or (not bill and not cells.get("date") and not party):
                skipped.append({**where, "reason": "total or balance line"})
                label = party or bill
                stated = _cents(cells.get("total"))
                if stated and re.match(r"(?i)\s*(grand\s*total|sub[\s-]*total|total)", label):
                    grand = bool(re.match(r"(?i)\s*grand", label))
                    expected = sheet_sum if grand else since
                    if abs(stated) != abs(expected):
                        warnings.append({**where, "reason": f"{'grand total' if grand else 'subtotal'} {_money(stated)} does not equal the rows it covers ({_money(expected)})"})
                    since = 0
                continue
            if "(cancelled)" in party.lower() or party.lower() == "cancelled":
                skipped.append({**where, "voucher": bill, "reason": "cancelled voucher"})
                continue
            if not bill:
                rejected.append({**where, "reason": "voucher number missing"})
                continue
            iso = _date(cells.get("date"))
            if iso is None:
                rejected.append({**where, "voucher": bill, "reason": f"unreadable date {cells.get('date')!r}"})
                continue
            amounts = {f: _cents(cells.get(f)) for f in tax_fields + (["total"] if "total" in found else [])}
            bad = [f for f, v in amounts.items() if v is None]
            if bad:
                rejected.append({**where, "voucher": bill, "reason": "unreadable amount in " + ", ".join(bad)})
                continue
            parts = sum(abs(amounts[f]) for f in tax_fields)
            gross = abs(amounts["total"]) if "total" in found and amounts["total"] else parts
            if not gross:
                rejected.append({**where, "voucher": bill, "reason": "no amount on the voucher line"})
                continue
            if "total" in found and amounts["total"] and tax_fields and "taxable" in tax_fields and parts != gross:
                warnings.append({**where, "voucher": bill, "reason": f"taxable value plus taxes ({_money(parts)}) does not equal the total ({_money(gross)})"})
            credit = bool(_CREDIT_TYPES.search(str(cells.get("vtype") or ""))) or (amounts.get("total") or 0) < 0
            sign = -1 if credit else 1
            gstin = re.sub(r"\s+", "", str(cells.get("gstin") or "")).upper()
            if gstin and (problem := gstin_check(gstin)):
                warnings.append({**where, "voucher": bill, "reason": f"buyer GSTIN: {problem}"})
            key = re.sub(r"\s+", "", bill.upper())
            if key in numbers:
                warnings.append({**where, "voucher": bill, "reason": f"voucher number repeats (also {numbers[key]})"})
            else:
                numbers[key] = f"{sheet.title} row {excel_row}"
            row = {"Bill No": bill, "Date": iso, "Customer": party, "Gross Amt": _money(sign * gross), "GST No": gstin}
            for f in tax_fields:
                row[{"taxable": "Taxable", "cgst": "CGST", "sgst": "SGST", "igst": "IGST", "cess": "Cess"}[f]] = _money(sign * abs(amounts[f]))
            sheet_sum += sign * gross
            since += sign * gross
            rows.append(row)
            sources.append({"row_no": len(rows), **where, "voucher": bill, "voucher_type": str(cells.get("vtype") or "") or None, "status": "credit_note" if credit else "sale"})
    if not sheets or all(s.get("header_row") is None for s in sheets):
        raise DocumentReadError("no sales register found; the sheet needs a header with Date, a voucher/bill number and an amount column")
    return {"rows": rows, "skipped": skipped, "rejected": rejected, "warnings": warnings, "sources": sources, "sheets": sheets, "parser": PARSER}
