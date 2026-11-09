"""Read a GSTR-1 return (the JSON the GST portal or the offline tool produces) as a sales register.

This reads a file the user downloaded themselves; there is no portal login or live GSTN connection.
Invoice-level sections (B2B, B2CL, exports, credit/debit notes) become register rows so T00 can
reconcile what was *reported to GST* against the books. B2CS is filed as monthly totals, not
invoices, so it is summarised and reported instead of being turned into rows.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .document_import import DocumentReadError, gstin_check

PARSER = "gstr1-json-v1"
# Rounding the portal itself allows between an invoice value and its taxable value plus taxes.
ROUNDING_CENTS = 100
TAX_KEYS = (("txval", "Taxable"), ("camt", "CGST"), ("samt", "SGST"), ("iamt", "IGST"), ("csamt", "Cess"))
NOT_READ = {"b2ba": "amended B2B invoices", "b2cla": "amended B2CL invoices", "cdnra": "amended credit/debit notes",
            "cdnura": "amended unregistered credit/debit notes", "expa": "amended exports", "b2csa": "amended B2CS totals",
            "at": "advances received", "txpd": "advances adjusted", "ata": "amended advances", "txpda": "amended advance adjustments"}


def _cents(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}{Decimal(abs(cents)) / 100:.2f}"


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _period(fp: Any) -> tuple[date, date] | None:
    text = str(fp or "").strip()
    if not re.fullmatch(r"(0[1-9]|1[0-2])[0-9]{4}", text):
        return None
    month, year = int(text[:2]), int(text[2:])
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def _item_totals(items: Any) -> dict[str, int] | None:
    totals = {label: 0 for _, label in TAX_KEYS}
    for item in items or []:
        if not isinstance(item, dict):
            return None
        detail = item.get("itm_det", item)  # export items carry their figures directly
        if not isinstance(detail, dict):
            return None
        for key, label in TAX_KEYS:
            if key in detail:
                cents = _cents(detail[key])
                if cents is None:
                    return None
                totals[label] += cents
    return totals


def _load(source: bytes) -> dict[str, Any]:
    try:
        data = json.loads(source.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentReadError("the file is not valid JSON; download the GSTR-1 JSON from the GST portal or the offline tool") from exc
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict) or not any(k in data for k in ("b2b", "b2cl", "b2cs", "exp", "cdnr", "cdnur")):
        raise DocumentReadError("no GSTR-1 sections found (expected b2b, b2cl, b2cs, exp, cdnr or cdnur)")
    return data


def parse_gstr1(source: bytes) -> dict[str, Any]:
    data = _load(source)
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    numbers: dict[str, str] = {}
    seen = 0
    filer = str(data.get("gstin") or "").strip().upper()
    if filer and (problem := gstin_check(filer)):
        warnings.append({"section": "header", "reason": f"filer GSTIN: {problem}"})
    period = _period(data.get("fp"))
    if data.get("fp") and period is None:
        warnings.append({"section": "header", "reason": f"unreadable return period {data.get('fp')!r} (expected MMYYYY)"})

    def add(section: str, document: dict, buyer: str, number_key: str, date_key: str, credit: bool | None, kind: str) -> None:
        nonlocal seen
        seen += 1
        number = str(document.get(number_key) or "").strip()
        where = {"section": section, "document": number or None}
        if not number:
            rejected.append({**where, "reason": "document number missing"})
            return
        iso = _date(document.get(date_key))
        if iso is None:
            rejected.append({**where, "reason": f"unreadable date {document.get(date_key)!r}"})
            return
        value = _cents(document.get("val"))
        totals = _item_totals(document.get("itms"))
        if value is None or totals is None:
            rejected.append({**where, "reason": "unreadable value or item amounts"})
            return
        parts = sum(totals.values())
        if not value and not parts:
            rejected.append({**where, "reason": "no amount on the document"})
            return
        if parts and abs(abs(value) - parts) > ROUNDING_CENTS:
            warnings.append({**where, "reason": f"taxable value plus taxes ({_money(parts)}) does not match the document value ({_money(abs(value))})"})
        if period and not period[0] <= date.fromisoformat(iso) <= period[1]:
            warnings.append({**where, "reason": f"dated {iso}, outside the return period {data.get('fp')}"})
        if buyer and (problem := gstin_check(buyer)):
            warnings.append({**where, "reason": f"buyer GSTIN: {problem}"})
        key = re.sub(r"\s+", "", number.upper())
        if key in numbers:
            warnings.append({**where, "reason": f"document number repeats (also in {numbers[key]})"})
        else:
            numbers[key] = section
        sign = -1 if credit else 1
        row = {"Bill No": number, "Date": iso, "Customer": "", "Gross Amt": _money(sign * abs(value)), "GST No": buyer, "Return": "GSTR-1"}
        for _, label in TAX_KEYS:
            if totals[label]:
                row[label] = _money(sign * abs(totals[label]))
        rows.append(row)
        sources.append({"row_no": len(rows), **where, "status": "credit_note" if credit else kind})

    for party in data.get("b2b") or []:
        buyer = str(party.get("ctin") or "").strip().upper() if isinstance(party, dict) else ""
        for inv in (party.get("inv") or []) if isinstance(party, dict) else []:
            if isinstance(inv, dict):
                add("B2B", inv, buyer, "inum", "idt", False, "sale")
    for group in data.get("b2cl") or []:
        for inv in (group.get("inv") or []) if isinstance(group, dict) else []:
            if isinstance(inv, dict):
                add("B2CL", inv, "", "inum", "idt", False, "sale")
    for group in data.get("exp") or []:
        for inv in (group.get("inv") or []) if isinstance(group, dict) else []:
            if isinstance(inv, dict):
                add("Export", inv, "", "inum", "idt", False, "sale")
    for party in data.get("cdnr") or []:
        buyer = str(party.get("ctin") or "").strip().upper() if isinstance(party, dict) else ""
        for note in (party.get("nt") or []) if isinstance(party, dict) else []:
            if isinstance(note, dict):
                add("CDNR", note, buyer, "nt_num", "nt_dt", str(note.get("ntty", "C")).upper() != "D", "debit_note")
    for note in data.get("cdnur") or []:
        if isinstance(note, dict):
            add("CDNUR", note, "", "nt_num", "nt_dt", str(note.get("ntty", "C")).upper() != "D", "debit_note")

    b2cs = {"lines": 0, "taxable": 0, "tax": 0}
    for line in data.get("b2cs") or []:
        if isinstance(line, dict):
            b2cs["lines"] += 1
            b2cs["taxable"] += _cents(line.get("txval")) or 0
            b2cs["tax"] += sum(_cents(line.get(k)) or 0 for k in ("iamt", "camt", "samt", "csamt"))
    if b2cs["lines"]:
        skipped.append({"section": "B2CS", "reason": f"{b2cs['lines']} small B2C summary lines (taxable {_money(b2cs['taxable'])}, tax {_money(b2cs['tax'])}) are filed as totals, not invoices, so they cannot be matched one by one"})
    for key, label in NOT_READ.items():
        if data.get(key):
            skipped.append({"section": key.upper(), "reason": f"{label} are not read yet; check them by hand"})
    if not seen and not b2cs["lines"]:
        raise DocumentReadError("the return lists no invoices or notes")
    summary = {"filer_gstin": filer or None, "return_period": data.get("fp"), "documents": seen,
               "b2cs_taxable": _money(b2cs["taxable"]), "b2cs_tax": _money(b2cs["tax"]),
               "note": "Read from a downloaded GSTR-1 file; not fetched from or verified with the GST portal."}
    return {"rows": rows, "skipped": skipped, "rejected": rejected, "warnings": warnings, "sources": sources,
            "parser": PARSER, "vouchers_seen": seen, "summary": summary}
