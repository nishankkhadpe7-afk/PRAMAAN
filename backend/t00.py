"""Versioned comparison contract; never mutates original register cells."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

RULE = {"version": "p2-t00-v2", "implementation": "field-aware calendar/exact-cents comparison",
        "fields": ["Bill No", "Date", "Customer", "Gross Amt", "GST No"],
        "dates": "YYYY-MM-DD or explicit M/D/YYYY (US month/day, never infer locale); calendar validation",
        "money": "signed decimal INR; optional validated western/Indian comma groups; exact cents, no rounding/exponents/symbols",
        "customer": "collapse whitespace only; case sensitive",
        "identifiers": "exact text, including whitespace/case/punctuation/leading zeros",
        "unavailable": "missing/invalid values produce PARSE_REVIEW, never equal",
        "delta": "register minus system; cents/INR for money, calendar days for dates"}


def normalize(field, value):
    if value is None or not isinstance(value, str) or not value.strip():
        return {"status": "MISSING", "value": None}
    text = value.strip()
    try:
        if field == "Date":
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
                parsed = date.fromisoformat(text)
            elif re.fullmatch(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}", text):
                month, day, year = map(int, text.split("/"))
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


def compare(field, register_value, system_value):
    left, right = normalize(field, register_value), normalize(field, system_value)
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
