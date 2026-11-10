"""Versioned comparison contract; never mutates original register cells."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

RULE = {"version": "p2-t00-v5", "implementation": "field-aware calendar/exact-cents comparison",
        "fields": ["Bill No", "Date", "Customer", "Gross Amt", "GST No"],
        "dates": "YYYY-MM-DD, or D/M/YYYY or M/D/YYYY (separator /, - or ., the same one twice; 01-04-2025 is common in Indian exports) with the order stated by the user or detected from the file (a first part above 12 means day-first, a second part above 12 means month-first); a slash date the order cannot settle, or one that contradicts it, needs review; calendar validation",
        "money": "signed decimal INR; optional validated western/Indian comma groups; exact cents, no rounding/exponents/symbols",
        "customer": "collapse whitespace only; case sensitive",
        "identifiers": "exact text, including whitespace/case/punctuation/leading zeros",
        "unavailable": "missing/invalid values produce PARSE_REVIEW, never equal",
        "optional": "GST No blank on BOTH sides is NOT_APPLICABLE (B2C sales and non-GST registers carry no buyer GSTIN); blank or invalid on one side is PARSE_REVIEW",
        "duplicates": "a bill number on more than one register row: the first row is compared, each repeat is DUPLICATE_ROW",
        "credit_notes": "a register row whose Bill No is a credit note in the books is compared on Date and Gross Amt (books amount shown negative); once the register lists any credit note, a books credit note dated inside the register's period that it omits is SYSTEM_ONLY",
        "tax_split": "only when the register has CGST/SGST/IGST columns: their total must equal the books tax; CGST must equal SGST; CGST/SGST and IGST are not both charged; with company_state given, a buyer GSTIN in the same state must not carry IGST and one in another state must carry only IGST; a Taxable column must equal the books net amount; tax that is not a standard GST rate of the taxable value goes to review (mixed-rate invoices can cause it)",
        "gstr1_scope": "a GSTR-1 upload (one return period) is compared only with books invoices dated in that month; a books invoice or credit note is missing from it only if the buyer has a GSTIN; B2C bills are counted, not matched, because whether they belong in B2CL or the B2CS totals depends on the buyer's state, which the books do not record",
        "delta": "register minus system; cents/INR for money, calendar days for dates"}


OPTIONAL_FIELDS = {"GST No"}


_SLASH_DATE = re.compile(r"([0-9]{1,2})([/.-])([0-9]{1,2})\2([0-9]{4})")


def detect_date_order(values) -> dict:
    """Which slash-date order a register uses, from its own values. A first part above 12 can only be a day
    (day-first, DMY); a second part above 12 can only be a day (month-first, MDY). Both kinds of evidence in
    one file is a conflict; no evidence means the order is undetermined. Nothing is assumed from locale."""
    dmy = mdy = 0
    for value in values:
        match = _SLASH_DATE.fullmatch(value.strip()) if isinstance(value, str) else None
        if match:
            first, second = int(match.group(1)), int(match.group(3))
            dmy += first > 12
            mdy += second > 12
    order = "DMY" if dmy and not mdy else "MDY" if mdy and not dmy else "CONFLICT" if dmy and mdy else None
    return {"order": order, "day_first_evidence": dmy, "month_first_evidence": mdy}


def normalize(field, value, date_order="MDY"):
    """date_order: "MDY" (default, the original rule for direct callers), "DMY", or None when the register's
    order could not be determined; then only slash dates whose parts settle the order themselves are read."""
    if value is None or not isinstance(value, str) or not value.strip():
        return {"status": "MISSING", "value": None}
    text = value.strip()
    try:
        if field == "Date":
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
                parsed = date.fromisoformat(text)
            elif match := _SLASH_DATE.fullmatch(text):
                first, second, year = int(match.group(1)), int(match.group(3)), int(match.group(4))
                order = date_order if date_order in ("DMY", "MDY") else ("DMY" if first > 12 else "MDY" if second > 12 else None)
                if order is None:
                    raise ValueError("date order cannot be settled")
                day, month = (first, second) if order == "DMY" else (second, first)
                parsed = date(year, month, day)
            else:
                raise ValueError("unsupported date")
            normalized = parsed.isoformat()
        elif field == "Gross Amt":
            if len(text) > 100 or not re.fullmatch(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})+,[0-9]{3})(?:\.[0-9]+)?", text):
                raise ValueError("unsupported money")
            with localcontext() as ctx:
                ctx.prec = 110
                cents = Decimal(text.replace(",", "")) * 100
                if cents != cents.to_integral_value():
                    raise ValueError("fractional cent")
                normalized = int(cents)
        elif field == "Customer":
            normalized = " ".join(value.split())
        else:
            normalized = value
        return {"status": "VALID", "value": normalized}
    except (ValueError, InvalidOperation):
        return {"status": "INVALID", "value": None}


def compare(field, register_value, system_value, date_order="MDY"):
    # Only the register side follows the register's date order; system dates are ISO.
    left, right = normalize(field, register_value, date_order), normalize(field, system_value)
    if field in OPTIONAL_FIELDS and left["status"] == right["status"] == "MISSING":
        return {"field": field, "register_value": register_value, "system_value": system_value, "register_normalized": left,
                "system_normalized": right, "comparison": "NOT_APPLICABLE", "normalized_difference": None}
    status = "PARSE_REVIEW" if left["status"] != "VALID" or right["status"] != "VALID" else ("EQUAL" if left["value"] == right["value"] else "DIFFERENT")
    delta = None
    if status == "DIFFERENT" and field == "Gross Amt":
        cents = left["value"] - right["value"]
        delta = {"cents": cents, "inr": money_text(cents)}
    elif status == "DIFFERENT" and field == "Date":
        delta = {"days": (date.fromisoformat(left["value"]) - date.fromisoformat(right["value"])).days}
    return {"field": field, "register_value": register_value, "system_value": system_value,
            "register_normalized": left, "system_normalized": right, "comparison": status,
            "normalized_difference": delta}


def money_text(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"
