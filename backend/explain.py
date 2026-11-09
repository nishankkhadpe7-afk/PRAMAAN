"""Plain-language explanations for findings and sample selections.

Presentation only: explanations are derived from data already frozen in a run
snapshot or export package and are never written back into stored results, so
reproducibility checks and finding identifiers are unaffected.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

DOC_LABELS = {"e_way_bill": "e-way bill", "lorry_receipt": "lorry receipt", "proof_of_delivery": "proof of delivery",
              "invoice": "invoice copy", "credit_note": "credit note", "return_support": "goods-return support"}
SHEET_LABELS = {"sales_tod": "the sales test of details", "cutoff_tod": "the cut-off test", "credit_note_tod": "the credit-note test"}
FIELD_LABELS = {"taxable_amount": "taxable amount", "gross_amount": "gross amount", "cgst": "CGST", "sgst": "SGST", "igst": "IGST",
                "quantity": "quantity", "gstin": "GSTIN", "invoice_date": "invoice date", "seller_gstin": "seller GSTIN", "buyer_gstin": "buyer GSTIN"}
MONEY_FIELDS = {"taxable_amount", "gross_amount", "cgst", "sgst", "igst", "Gross Amt", "taxable_value", "gross_value"}


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def inr(value: Any) -> str:
    """Indian-grouped rupee amount, e.g. ₹2,95,000.00."""
    amount = _dec(value)
    if amount is None:
        return str(value)
    sign, amount = ("-" if amount < 0 else ""), abs(amount).quantize(Decimal("0.01"))
    whole, paise = f"{amount:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    return f"{sign}₹{whole}.{paise}"


def cents(value: Any) -> str:
    amount = _dec(value)
    return inr(amount / 100) if amount is not None else str(value)


def nice_date(value: Any) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(value) if value else "an unrecorded date"


def _days(a: Any, b: Any) -> int | None:
    try:
        return (date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days
    except ValueError:
        return None


def _list(items: list[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


class Context:
    """Lookup tables built once per run or package."""

    def __init__(self, snapshot: dict[str, Any], result: dict[str, Any], register: dict[str, Any] | None = None):
        self.result = result
        self.period_end = result.get("period_end")
        self.period_start = result.get("period_start")
        self.invoices: dict[str, dict[str, Any]] = {}
        for row in snapshot.get("source_data", {}).get("invoices.csv", []):
            self.invoices[row["invoice_id"]] = {"bill_no": row.get("bill_no"), "customer": row.get("customer_name"), "customer_id": row.get("customer_id"),
                                                "gross": _dec(row.get("gross_amount")), "date": row.get("invoice_date"), "dispatch": None}
        for row in snapshot.get("invoices", []):
            self.invoices[row["invoice_id"]] = {"bill_no": row.get("bill_no"), "customer": row.get("customer_name"), "customer_id": row.get("customer_id"),
                                                "gross": _dec(row.get("gross_cents", 0)) / 100, "date": row.get("invoice_date"), "dispatch": row.get("dispatch_date")}
        self.by_bill = {v["bill_no"]: {**v, "invoice_id": k} for k, v in self.invoices.items() if v.get("bill_no")}
        self.customers = {v["customer_id"]: v["customer"] for v in self.invoices.values() if v.get("customer_id")}
        self.credit_notes = {n["credit_note_id"]: n for n in snapshot.get("credit_notes", [])}
        self.register_rows = {}
        for row in (register or {}).get("rows", []):
            try:
                self.register_rows[row["row_no"]] = json.loads(row["raw_json"])
            except (KeyError, ValueError):
                pass

    def invoice(self, ref: Any) -> dict[str, Any] | None:
        return self.invoices.get(ref) or self.by_bill.get(ref)

    def describe(self, ref: Any) -> str:
        inv = self.invoice(ref)
        if not inv:
            return str(ref)
        parts = [f"Invoice {inv['bill_no'] or ref}"]
        if inv.get("customer"):
            parts.append(f"to {inv['customer']}")
        if inv.get("gross") is not None:
            parts.append(f"for {inr(inv['gross'])}")
        if inv.get("date"):
            parts.append(f"dated {nice_date(inv['date'])}")
        return " ".join(parts)

    def relative_to_period_end(self, value: Any) -> str:
        delta = _days(value, self.period_end)
        if delta is None:
            return ""
        if delta == 0:
            return "on the period-end date"
        return f"{_plural(abs(delta), 'day')} {'after' if delta > 0 else 'before'} the period end ({nice_date(self.period_end)})"


# ---------------------------------------------------------------- findings

def _diff_sentence(field: str, left_label: str, left: Any, right_label: str, right: Any) -> str:
    label = FIELD_LABELS.get(field, field.replace("_", " "))
    if field in MONEY_FIELDS and _dec(left) is not None and _dec(right) is not None:
        gap = _dec(left) - _dec(right)
        return f"{label} is {inr(left)} in the {left_label} but {inr(right)} in the {right_label} (difference {inr(gap)})"
    return f"{label} is “{left}” in the {left_label} but “{right}” in the {right_label}"


def _t00(f: dict[str, Any], ctx: Context) -> str:
    bill, row_no, category = f.get("bill_no") or "an unnamed bill", f.get("row_no"), f.get("category")
    row_text = f"Register row {row_no}" if row_no else "The register"
    if category == "FIELD_DIFF":
        parts = []
        for d in f.get("field_differences", []):
            field, reg, sys = d.get("field"), d.get("register_value"), d.get("system_value")
            if field == "Gross Amt":
                parts.append(_diff_sentence(field, "register", reg, "system", sys).replace("Gross Amt", "the gross amount"))
            elif field == "Tax split":
                parts.append(f"the GST split is wrong ({d.get('normalized_difference') or 'unreadable tax columns'})")
            elif field == "Date":
                parts.append(f"the date is {nice_date(reg)} in the register but {nice_date(sys)} in the system")
            else:
                parts.append(f"{field} is “{reg}” in the register but “{sys}” in the system")
        return f"{row_text} matches sale {bill}, but " + "; and ".join(p.replace(" but ", ", whereas ", 1) for p in parts) + "."
    if category == "REGISTER_ONLY":
        raw = ctx.register_rows.get(row_no, {})
        detail = ", ".join(x for x in [raw.get("Customer"), inr(raw["Gross Amt"]) if raw.get("Gross Amt") else None, nice_date(raw["Date"]) if raw.get("Date") else None] if x)
        return f"{row_text} records bill {bill}{f' ({detail})' if detail else ''}, but no matching sale exists in the company's system. The entry may be fictitious, duplicated or not yet recorded."
    if category == "DUPLICATE_ROW":
        return f"{row_text} repeats bill {bill}, which already appears earlier in the register, so the sale may be counted twice."
    if category == "SYSTEM_ONLY":
        return f"{ctx.describe(bill)} is recorded in the system but is missing from the uploaded register, so the register may be incomplete."
    if category == "PARSE_REVIEW":
        fields = _list([str(d.get("field")) for d in f.get("field_differences", [])]) or "a required field"
        return f"{row_text} for bill {bill} could not be compared because {fields} is missing or unreadable."
    return f.get("reason", "")


def _t11(f: dict[str, Any], ctx: Context) -> str:
    sub, ref = f.get("subcheck"), f.get("object_ref")
    if sub == "P1_route_time":
        return f"The delivery for {ctx.describe(ref)} covers {f.get('distance_km')} km at an implied {f.get('implied_speed_kmph')} km/h — above the {f.get('max_road_speed_kmph')} km/h maximum road speed."
    if sub == "P4_event_order":
        return f"The movement for {ctx.describe(ref)} records arrival at {f.get('arrive_ts', '').replace('T', ' ')} — before its departure at {f.get('depart_ts', '').replace('T', ' ')}."
    if sub == "P3_load_estimate":
        return f"The shipment for {ctx.describe(ref)} carries {f.get('quantity_units')} units, more than the vehicle's {f.get('vehicle_capacity_units')}-unit capacity."
    if sub == "P5_pin_consignee":
        return f"Goods for {ctx.describe(ref)} were consigned to GST state {f.get('consignee_gstin_state')} (PIN {f.get('to_pin')}), but the buyer is billed in GST state {f.get('buyer_gstin_state')} — delivery and billing disagree."
    if sub == "P2_vehicle_overlap":
        invoices = [ctx.invoice(i)["bill_no"] if ctx.invoice(i) else i for i in f.get("invoice_ids", [])]
        return f"Vehicle {f.get('vehicle_no')} is recorded on two trips at the same time ({_list(invoices)}); one vehicle cannot be in two places at once."
    return f.get("reason", "")


def explain_finding(f: dict[str, Any], ctx: Context) -> str:
    test, ref, state = f.get("test_id"), f.get("object_ref"), f.get("state")
    try:
        if f.get("category") == "UNREADABLE_DATE":
            label = f.get("bill_no") or ref
            recorded = f" (recorded as \"{f['recorded_value']}\")" if f.get("recorded_value") else ""
            return f"{label}{recorded}: {f.get('reason', '')}"
        if test == "T00":
            return _t00(f, ctx)
        if test == "T01":
            since = f" since {nice_date(f['valid_from'])}" if f.get("valid_from") else ""
            return f"{ctx.describe(ref)} was made to a disclosed related party ({f.get('relationship_type') or 'relationship not described'}{since}). Related-party sales need disclosure and an arm's-length pricing review."
        if test == "T02":
            path = f.get("cycle_path")
            if path:
                names = [ctx.customers.get(p, p) for p in path]
                return f"Customers form a closed loop of relationships: {' → '.join(names)} ({_plural(f.get('cycle_length', len(path) - 1), 'link')}). Circular counterparties can be used to round-trip or inflate revenue."
            return f"A possible relationship between {f.get('subject_id', ref)} and {f.get('counterparty_id', 'another party')} was found in the counterparty data and needs corroboration."
        if test == "T03":
            inv = ctx.invoice(ref) or {}
            when = ctx.relative_to_period_end(f.get("invoice_date") or inv.get("date"))
            dispatch = f", dispatched {nice_date(f['dispatch_date'])}" if f.get("dispatch_date") else ""
            return f"{ctx.describe(ref)}{dispatch}, falls {when}. No contract or transfer-of-control date is on record, so the correct revenue period cannot be confirmed."
        if test == "T04":
            missing = _list([DOC_LABELS.get(d, d) for d in f.get("missing_documents", [])])
            return f"{ctx.describe(ref)} was selected for {SHEET_LABELS.get(f.get('sample_sheet'), 'testing')}, but its {missing} {'has' if len(f.get('missing_documents', [])) == 1 else 'have'} not been provided, so delivery cannot yet be supported."
        if test == "T05":
            return f"Journal {ref} credits {inr(f.get('revenue_credit'))} to revenue without referencing any invoice, so the entry cannot be traced to a sale."
        if test == "T06":
            parts = [_diff_sentence(k, "invoice", v.get("invoice"), "dispatch record", v.get("dispatch")) for k, v in (f.get("differences") or {}).items()]
            return f"{ctx.describe(ref)} disagrees with its dispatch record: " + "; ".join(parts) + "." if parts else f"{ctx.describe(ref)} has no dispatch record to compare against."
        if test == "T07":
            invoices = [ctx.invoice(i)["bill_no"] if ctx.invoice(i) else i for i in f.get("invoice_ids", [])]
            target = f" ({_list(invoices)})" if invoices else ""
            return f"The same supporting document (identical file contents) is attached to {_plural(len(invoices) or 2, 'different invoice')}{target}. One document cannot normally support separate sales."
        if test == "T09":
            note = ctx.credit_notes.get(ref, {})
            amount = cents(f.get("amount_cents", note.get("amount_cents", 0)))
            invoice = ctx.describe(f.get("invoice_id") or note.get("invoice_id"))
            return f"Credit note {ref} for {amount} was issued on {nice_date(f.get('credit_date') or note.get('credit_date'))}, {ctx.relative_to_period_end(f.get('credit_date') or note.get('credit_date'))}, against {invoice}. Revenue recorded before year-end may have been reversed afterwards."
        if test == "T10":
            invoices = [ctx.describe(i) for i in f.get("invoice_ids", [])]
            customer = ctx.customers.get(f.get("customer_id"), f.get("customer_id"))
            return f"{customer} received {_list(invoices)}. Each is below the {inr(f.get('threshold_inr'))} approval threshold, but together they exceed it within {f.get('window_days')} days — a possible split to avoid approval."
        if test == "T11":
            return _t11(f, ctx)
        if test == "T13":
            if state == "UNVERIFIED":
                return f"{ctx.describe(ref)} has an IRN, but no signed e-invoice QR was supplied, so its registration cannot be checked."
            if state == "UNAVAILABLE":
                return f"{ctx.describe(ref)} has neither an IRN nor a signed QR code, so e-invoice registration cannot be checked."
            if state == "INCONSISTENT":
                fields = _list([FIELD_LABELS.get(m.replace("_cents", "_amount"), m.replace("_cents", "").replace("_", " ")) for m in f.get("field_mismatches", [])]) or "some fields"
                return f"The signed e-invoice QR for {ctx.describe(ref)} has a valid demo signature, but its {fields} differ from the books."
            if state == "GOVERNMENT_REGISTERED_DEMO":
                return f"The signed e-invoice QR for {ctx.describe(ref)} has a valid signature under the demo key and matches the books (demo key only — not an official IRP check)."
        if test == "T14":
            if f.get("observed_unit_value"):
                return f"{ctx.describe(ref)} was billed at {inr(f['observed_unit_value'])} per unit against a list price of {inr(f.get('listed_unit_price'))}."
            customer = ctx.customers.get(f.get("customer_id"), f.get("customer_id"))
            return f"Promotion {ref} for {customer} on {f.get('item_code')} ({nice_date(f.get('valid_from'))} – {nice_date(f.get('valid_to'))}) has no approval reference."
        if test == "T15":
            parts = [_diff_sentence(k, "books", v.get("books"), "GSTR-1 return", v.get("synthetic_return_row")) for k, v in (f.get("differences") or {}).items()]
            return f"{ctx.describe(ref)} differs from the GSTR-1 row for {f.get('return_period')}: " + "; ".join(parts) + "."
    except (KeyError, TypeError, AttributeError):
        pass
    return f.get("reason", "")


# ---------------------------------------------------------------- samples

def _rank(reason: str) -> int | None:
    marker = "draw rank "
    if marker in reason:
        try:
            return int(reason.split(marker, 1)[1].split()[0])
        except (ValueError, IndexError):
            return None
    return None


def _certainty_points(reason: str) -> list[str]:
    points = []
    for part in [p.strip() for p in reason.split(";") if p.strip()]:
        low = part.lower()
        if "related-party" in low:
            points.append("the customer is a disclosed related party")
        elif "high-value" in low:
            points.append("its value is at or above the high-value threshold")
        elif "duplicate document" in low or "t07" in low:
            points.append("its supporting document is shared with another invoice")
        elif "credit note" in low or "t09" in low:
            points.append("it was credited after the period end")
        else:
            points.append(part[0].lower() + part[1:])
    return points


def explain_sample(sample: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Full explanation plus `why`, the same text without the leading record description."""
    info = _explain_sample(sample, ctx)
    prefixes = [ctx.describe(sample.get("object_ref"))]
    note = ctx.credit_notes.get(sample.get("object_ref"))
    if note:
        prefixes.append(f"Credit note {sample.get('object_ref')}")
    why = info["explanation"]
    for prefix in prefixes:
        if why.startswith(prefix):
            why = why[len(prefix):].lstrip(" .,")
            break
    return {**info, "why": why[:1].upper() + why[1:]}


def _explain_sample(sample: dict[str, Any], ctx: Context) -> dict[str, Any]:
    sheet, stratum, reason = sample.get("sheet"), sample.get("stratum") or "", sample.get("selection_reason") or ""
    ref, probability = sample.get("object_ref"), sample.get("inclusion_probability")
    coverage = ctx.result.get("coverage", {})
    if sheet == "sales_tod" and stratum == "certainty":
        points = _certainty_points(reason)
        text = f"{ctx.describe(ref)}. Always tested because {_list(points)}. Certainty items are chosen on risk, not chance, and are kept out of the random draw."
        return {"explanation": text, "selection_basis": "Certainty (risk-based)", "inclusion_value": 1.0, "inclusion_label": "100% · certainty"}
    if sheet == "sales_tod" and stratum == "probability":
        cov = coverage.get("sales_tod", {})
        population, chosen, rank = cov.get("probability_population"), cov.get("probability_selected"), _rank(reason)
        certain = cov.get("certainty_count", 0)
        rank_text = f" This invoice ranked {rank} of {population}." if rank and population else ""
        odds = f" Each had a {probability * 100:.1f}% chance of selection." if isinstance(probability, (int, float)) else ""
        text = (f"{ctx.describe(ref)}. Picked at random: after {_plural(certain, 'certainty item')} were set aside, the remaining {population} invoices were ranked by a "
                f"reproducible seeded draw and the first {chosen} were taken.{rank_text}{odds}")
        label = f"{probability * 100:.1f}% · random" if isinstance(probability, (int, float)) else "random"
        return {"explanation": text, "selection_basis": "Random (seeded)", "inclusion_value": probability, "inclusion_label": label}
    if sheet == "cutoff_tod":
        inv = ctx.invoice(ref) or {}
        cov = coverage.get("cutoff_tod", {})
        before = "before" in stratum
        side_pop, side_sel = (cov.get("before_population"), cov.get("before_selected")) if before else (cov.get("after_population"), cov.get("after_selected"))
        group = f"the last {side_sel} invoices before" if before else f"the first {side_sel} invoices after"
        purpose = "to confirm revenue booked before year-end really belongs to the period" if before else "to catch sales that belong to the earlier period but were booked late"
        census = side_pop is not None and side_pop == side_sel
        text = (f"{ctx.describe(ref)}, {ctx.relative_to_period_end(inv.get('date'))}. Cut-off testing always examines {group} the period end "
                f"({side_sel} of {side_pop}) {purpose}.")
        return {"explanation": text, "selection_basis": "Cut-off census" if census else "Cut-off (date-based)", "inclusion_value": 1.0,
                "inclusion_label": "100% · deterministic"}
    if sheet == "credit_note_tod":
        note = ctx.credit_notes.get(ref, {})
        what = f"Credit note {ref}" + (f" for {cents(note['amount_cents'])}" if note.get("amount_cents") is not None else "") + (f" dated {nice_date(note['credit_date'])}" if note.get("credit_date") else "")
        against = f" against {ctx.describe(note['invoice_id'])}" if note.get("invoice_id") else ""
        if stratum == "post_period_census":
            days = coverage.get("credit_note_tod", {}).get("post_period_window_days", 90)
            text = f"{what}{against}, {ctx.relative_to_period_end(note.get('credit_date'))}. Every credit note issued within {days} days after the period end is tested, because it may reverse revenue booked before year-end."
            return {"explanation": text, "selection_basis": "Post-period census", "inclusion_value": 1.0, "inclusion_label": "100% · census"}
        if stratum == "high_value":
            text = f"{what}{against}. Always tested because it is at or above the high-value credit-note threshold."
            return {"explanation": text, "selection_basis": "Certainty (high value)", "inclusion_value": 1.0, "inclusion_label": "100% · certainty"}
        label = f"{probability * 100:.1f}% · random" if isinstance(probability, (int, float)) else "random"
        cov = coverage.get("credit_note_tod", {})
        if isinstance(probability, (int, float)) and probability >= 1:
            detail = f"All {cov.get('in_period_population', 'the')} eligible in-period credit notes were needed to meet the sample target, so this one was certain to be included."
        else:
            detail = f"Picked at random from the in-period credit notes using the reproducible seeded draw (rank {_rank(reason) or '—'})."
        return {"explanation": f"{what}{against}. {detail}", "selection_basis": "Random (seeded)",
                "inclusion_value": probability, "inclusion_label": label}
    return {"explanation": reason, "selection_basis": stratum.replace("_", " ").capitalize() or "Selected", "inclusion_value": probability,
            "inclusion_label": f"{probability * 100:.1f}%" if isinstance(probability, (int, float)) else "not applicable"}


# ---------------------------------------------------------------- monetary exposure

def _money(value: Any) -> Decimal:
    amount = _dec(value)
    return abs(amount) if amount is not None else Decimal(0)


def exposure(findings: list[dict[str, Any]], ctx: Context) -> dict[str, Any]:
    """Rupee value behind the automated findings, grouped so nothing is counted twice.

    These are unconfirmed amounts flagged for review, not adjustments; only a human reviewer
    turns them into confirmed impact.
    """
    groups = {
        "differences": {"label": "Amount differences", "hint": "Register vs books, invoice vs dispatch, books vs GSTR-1, unlinked revenue journals", "refs": {}},
        "unrecorded": {"label": "Register entries with no matching sale", "hint": "Rows in the uploaded register that the company never recorded", "refs": {}},
        "unregistered": {"label": "Recorded sales missing from register", "hint": "Sales in the books that the register leaves out", "refs": {}},
        "credits": {"label": "Post-period credit notes", "hint": "Credits after year-end against revenue booked before it", "refs": {}},
        "evidence": {"label": "Sales lacking delivery evidence", "hint": "Sampled sales whose movement documents are still missing", "refs": {}},
        "cutoff": {"label": "Sales near period end without control date", "hint": "Revenue whose correct period cannot yet be confirmed", "refs": {}},
        "reused": {"label": "Sales sharing one supporting document", "hint": "Invoices backed by identical document files", "refs": {}},
        "related": {"label": "Related-party sales", "hint": "Sales to disclosed related parties needing disclosure and pricing review", "refs": {}},
    }

    quantified: set[str] = set()

    def add(group: str, key: str, amount: Decimal) -> None:
        if amount:
            groups[group]["refs"][key] = max(groups[group]["refs"].get(key, Decimal(0)), amount)
            if group in {"differences", "unrecorded", "unregistered", "credits"}:
                quantified.add(current)

    def gross(ref: Any) -> Decimal:
        inv = ctx.invoice(ref) or {}
        return _money(inv.get("gross"))

    for f in findings:
        test, ref = f.get("test_id"), f.get("object_ref")
        current = f.get("finding_id")
        if test == "T00":
            if f.get("category") == "FIELD_DIFF":
                for d in f.get("field_differences", []):
                    if d.get("field") == "Gross Amt":
                        add("differences", f"T00:{ref}", _money(_dec(d.get("register_value")) - _dec(d.get("system_value")) if _dec(d.get("register_value")) is not None and _dec(d.get("system_value")) is not None else 0))
            elif f.get("category") == "REGISTER_ONLY":
                add("unrecorded", f"REG:{f.get('row_no')}", _money(ctx.register_rows.get(f.get("row_no"), {}).get("Gross Amt")))
            elif f.get("category") == "SYSTEM_ONLY":
                add("unregistered", str(ref), gross(ref))
        elif test == "T06":
            for v in (f.get("differences") or {}).values():
                if _dec(v.get("invoice")) is not None and _dec(v.get("dispatch")) is not None:
                    add("differences", f"T06:{ref}", _money(_dec(v["invoice"]) - _dec(v["dispatch"])))
        elif test == "T15":
            gross_diff = (f.get("differences") or {}).get("gross_amount") or {}
            if _dec(gross_diff.get("books")) is not None and _dec(gross_diff.get("synthetic_return_row")) is not None:
                add("differences", f"T15:{ref}", _money(_dec(gross_diff["books"]) - _dec(gross_diff["synthetic_return_row"])))
        elif test == "T05":
            add("differences", f"T05:{ref}", _money(f.get("revenue_credit")))
        elif test == "T09":
            note = ctx.credit_notes.get(ref, {})
            add("credits", str(ref), _money(f.get("amount_cents", note.get("amount_cents", 0))) / 100)
        elif test == "T04":
            add("evidence", str(ref), gross(ref))
        elif test == "T03":
            add("cutoff", str(ref), gross(ref))
        elif test == "T07":
            for invoice_id in f.get("invoice_ids", []):
                add("reused", str(invoice_id), gross(invoice_id))
        elif test == "T01":
            add("related", str(ref), gross(ref))
    rows = []
    for key, group in groups.items():
        total = sum(group["refs"].values(), Decimal(0))
        if total:
            rows.append({"key": key, "label": group["label"], "hint": group["hint"], "amount": f"{total:.2f}", "items": len(group["refs"])})
    misstatement = sum((Decimal(r["amount"]) for r in rows if r["key"] in {"differences", "unrecorded", "unregistered", "credits"}), Decimal(0))
    population = sum((_money(i.get("gross")) for i in ctx.invoices.values()), Decimal(0))
    return {"potential_misstatement_inr": f"{misstatement:.2f}", "population_value_inr": f"{population:.2f}",
            "quantified_findings": len(quantified), "finding_count": len(findings),
            "groups": rows, "basis": "Unconfirmed amounts flagged by automated tests. Each group counts a record once; groups can overlap. Only human review confirms impact."}
