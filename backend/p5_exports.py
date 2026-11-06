"""Deterministic exports of immutable P5 report models; no database reads.

OOXML extends the existing backend's standard-library XLSX approach. Every
export is rebuilt from the frozen package only, so repeated downloads are
byte-identical. Plain-language explanations come from `explain`, which reads
the same frozen data.
"""
import base64
import io
import json
import zipfile
from collections import Counter
from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.sax.saxutils import escape

from . import app as p1
from . import explain

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"

TEST_NAMES = {"T00": "Register reconciliation", "T01": "Disclosed related party", "T02": "Related-party network", "T03": "Revenue cut-off timing",
              "T04": "Missing movement documents", "T05": "Unlinked revenue journals", "T06": "Invoice vs dispatch mismatch", "T07": "Reused evidence",
              "T08": "Period-end concentration", "T09": "Post-period credit notes", "T10": "Transaction splitting", "T11": "Movement plausibility",
              "T12": "Requested evidence", "T13": "E-invoice QR signature", "T14": "Pricing and promotions", "T15": "GSTR-1 vs books"}
SIGNAL = {"IMPOSSIBLE": "Inconsistent", "INCONSISTENT": "Inconsistent", "GAP": "Evidence gap", "UNAVAILABLE": "Evidence gap", "UNVERIFIED": "Evidence gap",
          "REVIEW": "Needs review", "DISCLOSED_RELATED_PARTY": "Context", "GOVERNMENT_REGISTERED_DEMO": "Context"}
CLEAR_STATES = {"SCREEN_CLEAR", "PASS", "VALID", "CLEAR"}
CHECK_STATES = {"SCREEN_CLEAR": "No conflict", "REVIEW": "Needs review", "SIGNATURE_INVALID": "Signature invalid", "SIGNATURE_VALID_DEMO": "Demo signature valid",
                "UNAVAILABLE": "Not available", "NOT_PERFORMED": "Not performed"}
OUTCOMES = {"EXPLAINED": "Explained", "EXCEPTION_CONFIRMED": "Exception confirmed", "DATA_ERROR": "Data error"}
TOD_SHEETS = {"Sales TOD", "Sales Cut-off TOD", "Credit Note TOD"}

# Cell style indexes in styles.xml (see _styles).
S_BODY, S_HEADER, S_TITLE, S_NOTE, S_MONEY, S_DATE, S_GOOD, S_GAP, S_ALERT, S_LINK, S_PERCENT, S_LABEL, S_INT = range(1, 14)


class Cell:
    """A value with an explicit style."""
    __slots__ = ("value", "style")

    def __init__(self, value, style):
        self.value, self.style = value, style


def column(index):
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def text(value):
    """Convert a value to a readable Excel cell string.

    Lists are rendered as comma-separated items (nested dicts get key=value pairs).
    Dicts are rendered as key: value lines separated by semicolons.
    Primitive values are plain strings.
    """
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append("; ".join(f"{k}: {v}" for k, v in item.items()))
            else:
                parts.append("" if item is None else str(item))
        return ", ".join(parts) if parts else ""
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    return "" if value is None else str(value)


def as_date(value):
    try:
        return Cell(date.fromisoformat(str(value)[:10]), S_DATE)
    except (TypeError, ValueError):
        return value or "—"


def fy_quarter(iso):
    """Indian financial-year quarter: Apr–Jun is Q1."""
    try:
        month = int(str(iso)[5:7])
    except ValueError:
        return "—"
    return "Q" + str((month - 4) % 12 // 3 + 1)


def month_name(iso):
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%b %Y")
    except ValueError:
        return "—"


def status(value):
    good = {"PRESENT_UNVERIFIED", "RECORDED", "Yes", "Explained", "Fulfilled"}
    gap = {"GAP", "REVIEW_REQUIRED", "Evidence gap", "Needs review", "Open review", "Not provided"}
    alert = {"Inconsistent", "Exception confirmed", "Data error", "No"}
    return Cell(value, S_GOOD if value in good else S_GAP if value in gap else S_ALERT if value in alert else S_BODY)


def short(value, limit=600):
    value = text(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def tables(report, content_hash):
    snapshot, result, findings = report["snapshot"], report["result"], report["findings"]
    ctx = explain.Context(snapshot, result, report.get("register"))
    receipt = report["receipt"]
    invoice_by_id = {i["invoice_id"]: i for i in snapshot["invoices"]}
    note_by_id = {n["credit_note_id"]: n for n in snapshot["credit_notes"]}
    source_invoices = {i["invoice_id"]: i for i in snapshot.get("source_data", {}).get("invoices.csv", [])}
    source_dispatch = {i["invoice_id"]: i for i in snapshot.get("source_data", {}).get("dispatches.csv", [])}
    audit_name = report.get("audit_name", report["client_name"])
    period = f"{explain.nice_date(result['period_start'])} to {explain.nice_date(result['period_end'])}"
    observations = {f["finding_id"]: explain.explain_finding(f, ctx) for f in findings}
    totals = report["totals"]
    flagged = explain.exposure(findings, ctx)

    def title(sheet):
        return [Cell(f"{audit_name} — {sheet}", S_TITLE), Cell(f"Client: {report['client_name']}   ·   Period: {period}   ·   Run {report['run_id']}   ·   Rules {receipt['ruleset_version']}   ·   Seed {receipt['sampling_seed']}", S_NOTE)]

    def note(message):
        return [Cell(message, S_NOTE)]

    sheets = {}
    # Overview first, so the workbook opens on a readable summary.
    signals = Counter(SIGNAL.get(f["state"], "Needs review") for f in findings)
    by_test = Counter(f["test_id"] for f in findings)
    reviewed = sum(1 for f in findings if f["human_decision"])
    sample_counts = Counter(s["sheet"] for s in result["sample_items"])
    overview = [[Cell(audit_name, S_TITLE)], note(f"Client: {report['client_name']}   ·   Period: {period}"), [],
                [Cell("Headline", S_HEADER), Cell("Value", S_HEADER), Cell("What it means", S_HEADER)],
                [Cell("Supported confirmed impact", S_LABEL), Cell(Decimal(totals["supported_confirmed_impact_inr"]), S_MONEY), "Adjustments a human reviewer confirmed with supporting evidence; each impact group is counted once."],
                [Cell("Potential misstatement (unconfirmed)", S_LABEL), Cell(Decimal(flagged["potential_misstatement_inr"]), S_MONEY), "Amount differences flagged by automated tests: " + ("; ".join(f"{g['label']} {explain.inr(g['amount'])}" for g in flagged["groups"] if g["key"] in {"differences", "unrecorded", "unregistered", "credits"}) or "none") + "."],
                *[[Cell("  " + g["label"], S_LABEL), Cell(Decimal(g["amount"]), S_MONEY), f"{g['items']} record(s). {g['hint']}."] for g in flagged["groups"] if g["key"] not in {"differences", "unrecorded", "unregistered", "credits"}],
                [Cell("Confirmed exceptions", S_LABEL), totals["confirmed_exceptions"], "Findings a human reviewer confirmed as exceptions."],
                [Cell("Open reviews", S_LABEL), totals["open_reviews"], "Automated findings still awaiting a human conclusion."],
                [Cell("Unquantified findings", S_LABEL), totals["unquantified_findings"], "Findings without a supported amount. Unquantified does not mean zero."],
                [Cell("Automated observations", S_LABEL), len(findings), f"{reviewed} reviewed by a human so far."],
                [Cell("Invoices in population", S_LABEL), len(snapshot["invoices"]), "Sales frozen in this snapshot."],
                [Cell("Workpaper items", S_LABEL), len(result["sample_items"]), f"Sales TOD {sample_counts['sales_tod']} · Cut-off {sample_counts['cutoff_tod']} · Credit notes {sample_counts['credit_note_tod']}."], [],
                [Cell("Signal type", S_HEADER), Cell("Findings", S_HEADER), Cell("Meaning", S_HEADER)],
                *[[status(name), signals.get(name, 0), meaning] for name, meaning in (("Inconsistent", "Records contradict each other."), ("Evidence gap", "Expected support is missing or cannot be verified."),
                                                                                       ("Needs review", "A pattern worth a human look."), ("Context", "Disclosed or classified for awareness."))], [],
                [Cell("Test", S_HEADER), Cell("Findings", S_HEADER), Cell("What the test looks for", S_HEADER)],
                *[[f"{test} · {TEST_NAMES.get(test, test)}", count, short(report["result"]["rule_coverage"].get(test, {}).get("reason") or "; ".join(report["result"]["rule_coverage"].get(test, {}).get("limitations", [])) or "See Coverage sheet.", 300)]
                  for test, count in sorted(by_test.items())], [],
                [Cell("How to read this workbook", S_HEADER), Cell("", S_HEADER), Cell("", S_HEADER)],
                ["Sales TOD / Cut-off / Credit Note", "", "One row per selected item: why it was chosen, its chance of selection, document status and linked findings (click the finding ID)."],
                ["Findings", "", "Every automated observation in plain language, with the human decision recorded so far."],
                ["Sales Register", "", "The client's original register, cell for cell, without any formatting."],
                ["Provenance / Receipt", "", "Source hashes and identifiers that let anyone reproduce this package."],
                [Cell("Important", S_LABEL), "", "Automated observations are signals, not conclusions. Sources are company-supplied and unverified; no official GST/IRP verification was performed."]]
    sheets["Overview"] = overview
    sheets["Sales Register"] = report["register"]["cells"]

    sales_headers = ["#", "Quarter (FY)", "Month", "Bill no", "Invoice date", "Customer", "Related party?", "Taxable value (₹)", "Gross value (₹)", "Selection basis",
                     "Chance of selection", "Why this item was selected", "Invoice copy", "E-way bill", "Lorry receipt", "Proof of delivery", "Journal", "Findings",
                     "Finding refs", "What the findings say", "Object ID", "Evidence refs"]
    cutoff_headers = ["#", "Quarter (FY)", "Month", "Bill no", "Invoice date", "Side of period end", "Days from period end", "Customer", "GST No", "Taxable value (₹)",
                      "Dispatch date", "Proof of delivery", "Control date", "Journal posting date", "In correct period?", "Why this item was selected", "Findings",
                      "Finding refs", "What the findings say", "Object ID", "Evidence refs"]
    cn_headers = ["Credit note", "Credit date", "Days after period end", "Original invoice", "Invoice date", "Amount (₹)", "Reason given", "Post-period?",
                  "Goods returned?", "Selection basis", "Chance of selection", "Why this item was selected", "Findings", "Finding refs", "What the findings say", "Evidence refs"]
    sheets["Sales TOD"] = [title("Sales test of details"), note("Objective: accuracy and occurrence of recorded sales. Work done: frozen sample selection, source tracing and deterministic tests. Conclusions require human review."), sales_headers]
    sheets["Sales Cut-off TOD"] = [title("Sales cut-off test"), note("Objective: cut-off. Sales either side of the period end are traced to dispatch and posting dates. The transfer-of-control date stays a GAP without contract facts and an approved policy."), cutoff_headers]
    sheets["Credit Note TOD"] = [title("Credit-note test"), note("Objective: subsequent credits and cut-off. Credit notes after the period end may reverse revenue booked before it. Timing alone is not an error."), cn_headers]
    links = {name: {} for name in sheets}
    finding_rows = {f["finding_id"]: index + 2 for index, f in enumerate(findings)}

    def finding_refs(ref):
        from .p5 import related_invoices
        return [f for f in findings if ref == f["object_ref"] or ref in related_invoices(f, snapshot)]

    def says(related):
        return short(" | ".join(dict.fromkeys(observations[f["finding_id"]] for f in related)), 900) or "No findings"

    for sample in result["sample_items"]:
        ref = sample["object_ref"]
        inv = invoice_by_id.get(ref, {})
        src = source_invoices.get(ref, {})
        related = finding_refs(ref)
        finding_ids = [f["finding_id"] for f in related]
        evidence_ids = sorted({e for f in related for e in f["evidence_ids"]})
        info = explain.explain_sample(sample, ctx)
        chance = Cell(info["inclusion_value"], S_PERCENT) if isinstance(info["inclusion_value"], (int, float)) else "n/a"
        inv_date = inv.get("invoice_date") or src.get("invoice_date", "")
        customer = inv.get("customer_name") or src.get("customer_name") or "—"
        bill = inv.get("bill_no") or src.get("bill_no") or ref
        taxable = Decimal(inv["net_cents"]) / 100 if "net_cents" in inv else Decimal(src["taxable_amount"]) if src.get("taxable_amount") else "—"
        gross = Decimal(inv["gross_cents"]) / 100 if "gross_cents" in inv else Decimal(src["gross_amount"]) if src.get("gross_amount") else "—"
        dispatch = source_dispatch.get(ref, {})
        refs_cell = Cell(", ".join(finding_ids), S_LINK) if finding_ids else "—"
        if sample["sheet"] == "sales_tod":
            name = "Sales TOD"
            link_col = sales_headers.index("Finding refs") + 1
            uploaded = {e["document_type"] for e in snapshot["p3_evidence"] if e["object_id"] == ref}
            if dispatch.get("eway_bill_no"):
                uploaded.add("e_way_bill")
            if dispatch.get("document_no"):
                uploaded.add("lorry_receipt")
            if dispatch.get("proof_of_delivery"):
                uploaded.add("proof_of_delivery")
            def doc(kind):
                return status("PRESENT_UNVERIFIED" if kind in uploaded else "GAP")
            row = [len(sheets[name]) - 2, fy_quarter(inv_date), month_name(inv_date), bill, as_date(inv_date), customer,
                   status("Yes") if any(f["test_id"] == "T01" for f in related) else "Not identified",
                   Cell(taxable, S_MONEY) if isinstance(taxable, Decimal) else taxable, Cell(gross, S_MONEY) if isinstance(gross, Decimal) else gross,
                   info["selection_basis"], chance, info["explanation"], doc("invoice"), doc("e_way_bill"), doc("lorry_receipt"), doc("proof_of_delivery"),
                   status("RECORDED" if inv.get("journal_lines") else "GAP"), len(finding_ids), refs_cell, says(related), ref, ", ".join(evidence_ids) or "—"]
        elif sample["sheet"] == "cutoff_tod":
            name = "Sales Cut-off TOD"
            link_col = cutoff_headers.index("Finding refs") + 1
            postings = sorted({j.get("posting_date") for j in inv.get("journal_lines", []) if j.get("posting_date")})
            gap_days = explain._days(inv_date, result["period_end"])
            row = [len(sheets[name]) - 2, fy_quarter(inv_date), month_name(inv_date), bill, as_date(inv_date),
                   "Before period end" if "before" in (sample.get("stratum") or "") else "After period end", gap_days if gap_days is not None else "—", customer,
                   inv.get("gstin") or src.get("buyer_gstin") or "—", Cell(taxable, S_MONEY) if isinstance(taxable, Decimal) else taxable,
                   as_date(inv.get("dispatch_date") or dispatch.get("dispatch_date")), dispatch.get("proof_of_delivery") or status("Not provided"),
                   status("GAP"), ", ".join(postings) if postings else "Not recorded", status("REVIEW_REQUIRED"), info["explanation"], len(finding_ids), refs_cell,
                   says(related), ref, ", ".join(evidence_ids) or "—"]
        else:
            name = "Credit Note TOD"
            link_col = cn_headers.index("Finding refs") + 1
            note_row = note_by_id.get(ref)
            if not note_row:
                continue
            original = ctx.invoice(note_row["invoice_id"]) or {}
            row = [ref, as_date(note_row["credit_date"]), explain._days(note_row["credit_date"], result["period_end"]), original.get("bill_no") or note_row["invoice_id"],
                   as_date(original.get("date") or note_row.get("invoice_date")), Cell(Decimal(note_row["amount_cents"]) / 100, S_MONEY), note_row.get("reason") or "—",
                   status("Yes" if note_row["credit_date"] > result["period_end"] else "No"), status("Not provided"), info["selection_basis"], chance,
                   info["explanation"], len(finding_ids), refs_cell, says(related), ", ".join(evidence_ids) or "—"]
        sheets[name].append(row)
        if finding_ids:
            links[name][(len(sheets[name]), link_col)] = "'Findings'!A" + str(finding_rows[finding_ids[0]])

    sheets["Findings"] = [["Finding ID", "Test", "Test name", "Signal type", "Assertion", "Record", "What was observed", "Rule note", "Automated state",
                           "Human outcome", "Reviewer", "Reviewer's reason", "Impact (₹)", "Impact group", "Proposed adjustment", "Exception status",
                           "Evidence refs", "Selected samples", "Standard / policy", "Unresolved questions", "Ruleset", "Rule hash", "Snapshot", "Run"]]
    for f in findings:
        review = f["human_decision"] or {}
        samples = ", ".join(f"{s['sheet']}:{s['object_ref']}" for s in f["samples"]) if f["samples"] else f["sample_scope"]
        standard = f["standard"].get("candidate_standard", text(f["standard"])) if isinstance(f["standard"], dict) else text(f["standard"])
        sheets["Findings"].append([f["finding_id"], f["test_id"], TEST_NAMES.get(f["test_id"], f["test_id"]), status(SIGNAL.get(f["state"], "Needs review")),
                                   f["assertion"].capitalize(), f["object_ref"], observations[f["finding_id"]], f["reason"], f["state"],
                                   status(OUTCOMES.get(review.get("outcome"), "Open review")), review.get("decided_by") or "—", review.get("reason") or "—",
                                   Cell(Decimal(f["impact_inr"]), S_MONEY) if f["impact_inr"] is not None else "Unquantified", review.get("impact_group") or "—",
                                   f["proposed_adjustment"], f["exception_status"], ", ".join(f["evidence_ids"]), samples, standard, f["unresolved_questions"],
                                   f["ruleset_version"], f["ruleset_hash"], f["snapshot_hash"], f["run_id"]])
    if report["reconciliation_rule"]["version"] == "p2-t00-v2":
        sheets["Findings"][0].append("Register comparison (original, normalized, difference)")
        for cells, finding in zip(sheets["Findings"][1:], findings):
            cells.append("; ".join(f"{d.get('field')}: register {d.get('register_value')!r} vs system {d.get('system_value')!r}" for d in finding.get("field_differences", [])) or "—")
    sheets["Summary"] = [["Metric", "Value"], *[[key, Decimal(value) if key == "supported_confirmed_impact_inr" else value if not isinstance(value, dict) else text(value) or "None"] for key, value in totals.items()],
                         ["Impact basis", "Confirmed human-reviewed impact groups counted once. Unquantified does not mean zero."], ["Limitations", " | ".join(report["limitations"])]]
    sheets["Impact Groups"] = [["Confirmed adjustment group", "Counted impact (₹)"], *[[key, Decimal(value)] for key, value in sorted(totals["impact_groups"].items())]]
    sheets["Import Metadata"] = [["Key", "Value"], *[[key, report["register"].get(key)] for key in ("upload_id", "sha256", "source_integrity", "parsing_warnings", "metadata_source_rows")],
                                 ["Preservation", "Raw original CSV bytes are included in the defensibility pack; the Sales Register sheet contains only the parsed original cells."]]
    sheets["Receipt"] = [["Key", "Value"], *[[key, value] for key, value in receipt.items()], ["output_content_digest", content_hash], ["package_id", "P5-" + content_hash],
                         ["review_digest", p1.digest(p1.canonical([f["human_decision"] for f in findings]))]]
    sheets["Provenance"] = [["Evidence ID", "Source file", "Source row", "Source SHA-256", "Row hash", "Provenance", "Independently verified?", "Record"]]
    for ref, item in sorted(report["evidence_index"].items()):
        record = item.get("record", item)
        sheets["Provenance"].append([ref, item["file_name"], item.get("source_row") or "—", item.get("sha256") or "—", item.get("row_hash") or "—",
                                     item["provenance"].replace("_", " ").capitalize(), "No", short(json.dumps(record, sort_keys=True, default=str) if isinstance(record, (dict, list)) else record, 2000)])
    sheets["Coverage"] = [["Test / sample design", "Status", "Limitations and notes"]]
    for key, value in result["rule_coverage"].items():
        sheets["Coverage"].append([f"{key} · {TEST_NAMES.get(key, key)}", str(value.get("status", "")).replace("_", " "), value.get("reason") or " ".join(value.get("limitations", [])) or "—"])
    for key, value in result["coverage"].items():
        sheets["Coverage"].append([key.replace("_", " ").capitalize(), "Sample coverage", short({k: v for k, v in value.items() if not isinstance(v, list)} if isinstance(value, dict) else value, 2000)])
    sheets["Demonstration Checks"] = [["Object", "Test", "State", "Classification", "Reason", "Official verification?"]]
    for check in report["differentiated_checks"]:
        sheets["Demonstration Checks"].append([check["object_ref"], check["test_id"], check["state"], check["classification"], check["reason"], "NOT PERFORMED"])
    sheets["Tickmarks"] = [["Mark", "Meaning"], [status("PRESENT_UNVERIFIED"), "Company-supplied document stored; it does not by itself substantiate an assertion"],
                           [status("RECORDED"), "Ledger record in the snapshot; not independently verified"], [status("GAP"), "Expected evidence unavailable; not a confirmed exception"],
                           [status("REVIEW_REQUIRED"), "Human assessment needed"], ["DEMO_SIGNATURE_VALID", "TEST ONLY; no government registration or delivery conclusion"],
                           ["SCREEN_CLEAR", "No conflict screened; no movement assurance"]]
    # UI-12: a linked contents list on the Overview sheet, so every sheet is one click away.
    purposes = {"Sales Register": "Client's original register, cell for cell (unformatted)", "Sales TOD": "Sales test of details: one row per selected sale",
                "Sales Cut-off TOD": "Cut-off test: items either side of the period end", "Credit Note TOD": "Credit notes after the period end",
                "Findings": "Every automated observation and its human decision", "Summary": "Headline totals", "Impact Groups": "Confirmed impact by group",
                "Import Metadata": "Source register details", "Receipt": "Identifiers needed to reproduce this package", "Provenance": "Evidence references and hashes",
                "Coverage": "What each test could and could not evaluate", "Demonstration Checks": "Synthetic demonstration checks", "Tickmarks": "Tickmark legend"}
    overview = sheets["Overview"]
    overview += [[], [Cell("Contents", S_HEADER), Cell("Rows", S_HEADER), Cell("What the sheet holds (click a name to open it)", S_HEADER)]]
    for name, rows in sheets.items():
        if name == "Overview":
            continue
        overview.append([name, max(len(rows) - (3 if name in TOD_SHEETS else 1), 0), purposes.get(name, "")])
        links.setdefault("Overview", {})[(len(overview), 1)] = f"'{name}'!A1"
    return sheets, links


def deterministic_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()


def _styles():
    s = Element("{" + NS + "}styleSheet")
    numfmts = SubElement(s, "{" + NS + "}numFmts", count="2")
    SubElement(numfmts, "{" + NS + "}numFmt", numFmtId="164", formatCode="dd-mmm-yyyy")
    SubElement(numfmts, "{" + NS + "}numFmt", numFmtId="165", formatCode='"₹"#,##0.00')
    font_specs = [("Calibri", "11", None, False, False, False), ("Calibri", "11", "FFFFFFFF", True, False, False), ("Calibri", "14", "FF1F3A5F", True, False, False),
                  ("Calibri", "10", "FF5B6472", False, True, False), ("Calibri", "11", "FF1D4ED8", False, False, True), ("Calibri", "11", "FF14532D", True, False, False),
                  ("Calibri", "11", "FF7C4A03", True, False, False), ("Calibri", "11", "FF7F1D1D", True, False, False), ("Calibri", "11", "FF1F2937", True, False, False)]
    fonts = SubElement(s, "{" + NS + "}fonts", count=str(len(font_specs)))
    for name, size, colour, bold, italic, underline in font_specs:
        font = SubElement(fonts, "{" + NS + "}font")
        if bold:
            SubElement(font, "{" + NS + "}b")
        if italic:
            SubElement(font, "{" + NS + "}i")
        if underline:
            SubElement(font, "{" + NS + "}u")
        SubElement(font, "{" + NS + "}sz", val=size)
        if colour:
            SubElement(font, "{" + NS + "}color", rgb=colour)
        SubElement(font, "{" + NS + "}name", val=name)
    fill_colours = [None, None, "FF1F3A5F", "FFE3F4E8", "FFFFF1D6", "FFFDE3E3", "FFF2F4F7"]
    fills = SubElement(s, "{" + NS + "}fills", count=str(len(fill_colours)))
    for index, colour in enumerate(fill_colours):
        pattern = SubElement(SubElement(fills, "{" + NS + "}fill"), "{" + NS + "}patternFill", patternType="none" if index == 0 else "gray125" if index == 1 else "solid")
        if colour:
            SubElement(pattern, "{" + NS + "}fgColor", rgb=colour)
    borders = SubElement(s, "{" + NS + "}borders", count="2")
    SubElement(borders, "{" + NS + "}border")
    thin = SubElement(borders, "{" + NS + "}border")
    for side in ("left", "right", "top", "bottom"):
        SubElement(SubElement(thin, "{" + NS + "}" + side, style="thin"), "{" + NS + "}color", rgb="FFD7DCE3")
    SubElement(SubElement(s, "{" + NS + "}cellStyleXfs", count="1"), "{" + NS + "}xf", numFmtId="0", fontId="0", fillId="0", borderId="0")
    # (numFmt, font, fill, border, horizontal)
    specs = [(0, 0, 0, 0, None), (0, 0, 0, 1, None), (0, 1, 2, 1, "center"), (0, 2, 0, 0, None), (0, 3, 0, 0, None), (165, 0, 0, 1, None), (164, 0, 0, 1, "center"),
             (0, 5, 3, 1, "center"), (0, 6, 4, 1, "center"), (0, 7, 5, 1, "center"), (0, 4, 0, 1, None), (10, 0, 0, 1, "center"), (0, 8, 6, 1, None), (1, 0, 0, 1, "center")]
    xfs = SubElement(s, "{" + NS + "}cellXfs", count=str(len(specs)))
    for index, (numfmt, font, fill, border, horizontal) in enumerate(specs):
        xf = SubElement(xfs, "{" + NS + "}xf", numFmtId=str(numfmt), fontId=str(font), fillId=str(fill), borderId=str(border), xfId="0",
                        **({"applyNumberFormat": "1"} if numfmt else {}), **({"applyFont": "1"} if font else {}), **({"applyFill": "1"} if fill else {}),
                        **({"applyBorder": "1"} if border else {}), **({"applyAlignment": "1"} if index else {}))
        if index:
            SubElement(xf, "{" + NS + "}alignment", wrapText="0" if index in (S_TITLE, S_NOTE) else "1", vertical="center" if index == S_HEADER else "top",
                       **({"horizontal": horizontal} if horizontal else {}))
    SubElement(SubElement(s, "{" + NS + "}cellStyles", count="1"), "{" + NS + "}cellStyle", name="Normal", xfId="0", builtinId="0")
    return s


def _width(values):
    longest = max((len(text(v.value if isinstance(v, Cell) else v)) for v in values), default=8)
    return max(9, min(60, longest * 0.95 + 2))


def workbook_bytes(report, content_hash):
    sheets, links = tables(report, content_hash)
    workbook = Element("{" + NS + "}workbook")
    sheet_list = SubElement(workbook, "{" + NS + "}sheets")
    rels = Element("{" + PKG + "}Relationships")
    types = Element("{" + CT + "}Types")
    for extension, kind in (("rels", "application/vnd.openxmlformats-package.relationships+xml"), ("xml", "application/xml")):
        SubElement(types, "{" + CT + "}Default", Extension=extension, ContentType=kind)
    SubElement(types, "{" + CT + "}Override", PartName="/xl/workbook.xml", ContentType=XLSX_TYPE)
    files = {}
    for sheet_id, (name, rows) in enumerate(sheets.items(), 1):
        SubElement(sheet_list, "{" + NS + "}sheet", {"name": name, "sheetId": str(sheet_id), "{" + REL + "}id": "rId" + str(sheet_id)})
        SubElement(rels, "{" + PKG + "}Relationship", Id="rId" + str(sheet_id), Type=REL + "/worksheet", Target=f"worksheets/sheet{sheet_id}.xml")
        SubElement(types, "{" + CT + "}Override", PartName=f"/xl/worksheets/sheet{sheet_id}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
        styled = name != "Sales Register"
        header_row = 3 if name in TOD_SHEETS else 4 if name == "Overview" else 1
        sheet = Element("{" + NS + "}worksheet")
        if not styled and rows:
            views = SubElement(sheet, "{" + NS + "}sheetViews")
            view = SubElement(views, "{" + NS + "}sheetView", workbookViewId="0")
            SubElement(view, "{" + NS + "}pane", ySplit="1", state="frozen", topLeftCell="A2")
            cols = SubElement(sheet, "{" + NS + "}cols")
            for index in range(1, max(map(len, rows), default=1) + 1):
                SubElement(cols, "{" + NS + "}col", min=str(index), max=str(index), width=f"{_width([r[index - 1] for r in rows if len(r) >= index]):.1f}", customWidth="1")
        if styled:
            SubElement(SubElement(sheet, "{" + NS + "}sheetPr"), "{" + NS + "}pageSetUpPr", fitToPage="1")
            views = SubElement(sheet, "{" + NS + "}sheetViews")
            view = SubElement(views, "{" + NS + "}sheetView", workbookViewId="0", **({"tabSelected": "1"} if sheet_id == 1 else {}), **({"showGridLines": "0"} if name == "Overview" else {}))
            if name != "Overview":
                SubElement(view, "{" + NS + "}pane", ySplit=str(header_row), state="frozen", topLeftCell=f"A{header_row + 1}")
            SubElement(sheet, "{" + NS + "}sheetFormatPr", defaultRowHeight="15")
            cols = SubElement(sheet, "{" + NS + "}cols")
            width_rows = rows[header_row - 1:] if name != "Overview" else rows[3:]
            for index in range(1, max(map(len, rows), default=1) + 1):
                values = [r[index - 1] for r in width_rows if len(r) >= index]
                width = 34 if name == "Overview" and index == 1 else 14 if name == "Overview" and index == 2 else 90 if name == "Overview" else _width(values)
                SubElement(cols, "{" + NS + "}col", min=str(index), max=str(index), width=f"{width:.1f}", customWidth="1")
        data = SubElement(sheet, "{" + NS + "}sheetData")
        for row_no, values in enumerate(rows, 1):
            row = SubElement(data, "{" + NS + "}row", r=str(row_no), **({"ht": "22", "customHeight": "1"} if styled and row_no == 1 else {}))
            for col_no, raw in enumerate(values, 1):
                value, style = (raw.value, raw.style) if isinstance(raw, Cell) else (raw, None)
                attrs = {"r": column(col_no) + str(row_no)}
                if styled:
                    if style is None:
                        style = S_HEADER if row_no == header_row and name != "Overview" else S_INT if isinstance(value, int) and not isinstance(value, bool) else S_MONEY if isinstance(value, Decimal) else S_BODY
                    attrs["s"] = str(style)
                if isinstance(value, date):
                    SubElement(SubElement(row, "{" + NS + "}c", attrs), "{" + NS + "}v").text = str((value - date(1899, 12, 30)).days)
                    continue
                numeric = isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and styled
                cell = SubElement(row, "{" + NS + "}c", {**attrs, **({} if numeric else {"t": "inlineStr"})})
                if numeric:
                    SubElement(cell, "{" + NS + "}v").text = str(value)
                else:
                    value_text = text(value)
                    if len(value_text) > 32767:
                        raise ValueError("Excel cell exceeds 32767 characters; use JSON package")
                    if any(ord(char) < 32 and char not in "\t\n\r" for char in value_text):
                        raise ValueError("Source contains characters unsupported by Excel XML; use JSON package")
                    SubElement(SubElement(cell, "{" + NS + "}is"), "{" + NS + "}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = value_text
        if styled and name not in {"Overview"} and len(rows) > header_row:
            SubElement(sheet, "{" + NS + "}autoFilter", ref=f"A{header_row}:{column(len(rows[header_row - 1]))}{len(rows)}")
        if links.get(name):
            hyperlinks = SubElement(sheet, "{" + NS + "}hyperlinks")
            for (row_no, col_no), location in links[name].items():
                SubElement(hyperlinks, "{" + NS + "}hyperlink", ref=column(col_no) + str(row_no), location=location)
        if styled:
            SubElement(sheet, "{" + NS + "}pageMargins", left="0.4", right="0.4", top="0.5", bottom="0.5", header="0.3", footer="0.3")
            SubElement(sheet, "{" + NS + "}pageSetup", orientation="landscape", fitToWidth="1", fitToHeight="0")
        files[f"xl/worksheets/sheet{sheet_id}.xml"] = tostring(sheet, encoding="utf-8", xml_declaration=True)
    # The Sales Register worksheet carries no styles, formulas or metadata; every other sheet is formatted for reading.
    SubElement(rels, "{" + PKG + "}Relationship", Id="rStyles", Type=REL + "/styles", Target="styles.xml")
    SubElement(types, "{" + CT + "}Override", PartName="/xl/styles.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")
    root_rels = Element("{" + PKG + "}Relationships")
    SubElement(root_rels, "{" + PKG + "}Relationship", Id="rId1", Type=REL + "/officeDocument", Target="xl/workbook.xml")
    files.update({"[Content_Types].xml": tostring(types, encoding="utf-8", xml_declaration=True), "_rels/.rels": tostring(root_rels, encoding="utf-8", xml_declaration=True),
                  "xl/workbook.xml": tostring(workbook, encoding="utf-8", xml_declaration=True), "xl/_rels/workbook.xml.rels": tostring(rels, encoding="utf-8", xml_declaration=True),
                  "xl/styles.xml": tostring(_styles(), encoding="utf-8", xml_declaration=True)})
    return deterministic_zip(files)


def memo_bytes(report, content_hash):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import CondPageBreak, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from pathlib import Path
    import reportlab
    # Bundled fonts handle international customer names without platform font lookup.
    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, file in (("PramaanVera", "Vera.ttf"), ("PramaanVeraBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / file)))
    navy, ink, muted, line = colors.HexColor("#1F3A5F"), colors.HexColor("#1F2937"), colors.HexColor("#5B6472"), colors.HexColor("#D7DCE3")
    tint = {"Inconsistent": colors.HexColor("#FDE3E3"), "Evidence gap": colors.HexColor("#FFF1D6"), "Needs review": colors.HexColor("#FFF7E0"), "Context": colors.HexColor("#E6EEFB")}
    base = getSampleStyleSheet()
    styles = {"title": ParagraphStyle("t", parent=base["Title"], fontName="PramaanVeraBold", fontSize=20, leading=24, textColor=navy, alignment=TA_LEFT, spaceAfter=4),
              "subtitle": ParagraphStyle("s", parent=base["BodyText"], fontName="PramaanVera", fontSize=11, leading=15, textColor=muted, spaceAfter=10),
              "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="PramaanVeraBold", fontSize=14, leading=18, textColor=navy, spaceBefore=10, spaceAfter=6),
              "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="PramaanVeraBold", fontSize=11, leading=14, textColor=ink, spaceBefore=8, spaceAfter=3),
              "body": ParagraphStyle("b", parent=base["BodyText"], fontName="PramaanVera", fontSize=9, leading=12.5, textColor=ink),
              "small": ParagraphStyle("sm", parent=base["BodyText"], fontName="PramaanVera", fontSize=7.5, leading=10, textColor=muted),
              "cell": ParagraphStyle("c", parent=base["BodyText"], fontName="PramaanVera", fontSize=8, leading=10.5, textColor=ink),
              "cellb": ParagraphStyle("cb", parent=base["BodyText"], fontName="PramaanVeraBold", fontSize=8, leading=10.5, textColor=ink),
              "head": ParagraphStyle("hd", parent=base["BodyText"], fontName="PramaanVeraBold", fontSize=8, leading=10.5, textColor=colors.white),
              "kpi": ParagraphStyle("k", parent=base["BodyText"], fontName="PramaanVeraBold", fontSize=13, leading=16, textColor=navy),
              "kpil": ParagraphStyle("kl", parent=base["BodyText"], fontName="PramaanVera", fontSize=7.5, leading=9.5, textColor=muted)}

    def p(value, style="body"):
        # The bundled font has no rupee glyph, so amounts read "INR" in the memo.
        return Paragraph(escape(text(value)).replace("₹", "INR "), styles[style])

    def grid(rows, widths, header=True, shade=None):
        table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        commands = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, line),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if header:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), navy))
        commands.extend(shade or [])
        table.setStyle(TableStyle(commands))
        return table

    snapshot, result, findings, totals = report["snapshot"], report["result"], report["findings"], report["totals"]
    ctx = explain.Context(snapshot, result, report.get("register"))
    width = A4[0] - 36 * mm
    audit_name = report.get("audit_name", report["client_name"])
    period = f"{explain.nice_date(result['period_start'])} to {explain.nice_date(result['period_end'])}"
    signals = Counter(SIGNAL.get(f["state"], "Needs review") for f in findings)
    reviewed = sum(1 for f in findings if f["human_decision"])

    story = [p("Findings memo", "title"), p(audit_name, "subtitle")]
    # UI-12: identifiers people read stay here; full hashes move to the reproducibility appendix.
    meta = [["Client", report["client_name"]], ["Audit period", period], ["Audit run", report["run_id"]],
            ["Export package", ("P5-" + content_hash)[:22] + "…  (full digest in the appendix)"], ["Rules", f"{report['receipt']['ruleset_version']} · sampler {report['receipt']['sampler_version']}"]]
    story.append(grid([[p(k, "cellb"), p(v, "cell")] for k, v in meta], [32 * mm, width - 32 * mm], header=False))
    story.append(Spacer(1, 8))
    flagged = explain.exposure(findings, ctx)
    kpis = [(f"{Decimal(flagged['potential_misstatement_inr']):,.2f}", "Potential misstatement, INR (unconfirmed)"),
            (f"{Decimal(totals['supported_confirmed_impact_inr']):,.2f}", "Supported confirmed impact, INR"), (str(totals["confirmed_exceptions"]), "Confirmed exceptions"),
            (str(totals["open_reviews"]), "Open reviews"), (f"{reviewed}/{len(findings)}", "Reviewed by a human")]
    # Money columns are wider so totals never wrap mid-number.
    shares = (0.27, 0.23, 0.16, 0.16, 0.18)
    kpi_table = Table([[p(v, "kpi") for v, _ in kpis], [p(label, "kpil") for _, label in kpis]], colWidths=[width * share for share in shares])
    kpi_table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, line), ("INNERGRID", (0, 0), (-1, -1), 0.4, line), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F9FC")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, 1), (-1, 1), 7)]))
    story += [kpi_table, Spacer(1, 6),
              p("Supported confirmed impact (INR): " + totals["supported_confirmed_impact_inr"]),
              p(f"Confirmed human exceptions: {totals['confirmed_exceptions']}; open reviews: {totals['open_reviews']}; unquantified findings: {totals['unquantified_findings']}. "
                "Impact groups are counted once. Unquantified amounts are not zero. No statistical population projection is made.", "small")]

    if flagged["groups"]:
        story.append(p("Amounts flagged (unconfirmed)", "h1"))
        story.append(grid([[p("Group", "head"), p("Amount", "head"), p("Records", "head"), p("Meaning", "head")]] +
                          [[p(g["label"], "cell"), p(f"INR {Decimal(g['amount']):,.2f}", "cell"), p(g["items"], "cell"), p(g["hint"], "cell")] for g in flagged["groups"]],
                          [50 * mm, 32 * mm, 18 * mm, width - 100 * mm]))
    story.append(p("What the tests found", "h1"))
    story.append(grid([[p("Signal type", "head"), p("Findings", "head"), p("Meaning", "head")]] +
                      [[p(name, "cellb"), p(signals.get(name, 0), "cell"), p(meaning, "cell")] for name, meaning in
                       (("Inconsistent", "Records contradict each other."), ("Evidence gap", "Expected support is missing or cannot be verified."),
                        ("Needs review", "A pattern worth a human look."), ("Context", "Disclosed or classified for awareness."))],
                      [35 * mm, 20 * mm, width - 55 * mm], shade=[("BACKGROUND", (0, i + 1), (0, i + 1), tint[n]) for i, n in enumerate(("Inconsistent", "Evidence gap", "Needs review", "Context"))]))
    story.append(Spacer(1, 8))
    by_test = Counter(f["test_id"] for f in findings)
    story.append(grid([[p("Test", "head"), p("Findings", "head"), p("Open", "head"), p("Coverage note", "head")]] +
                      [[p(f"{t} · {TEST_NAMES.get(t, t)}", "cell"), p(n, "cell"), p(sum(1 for f in findings if f["test_id"] == t and not f["human_decision"]), "cell"),
                        p(short(result["rule_coverage"].get(t, {}).get("reason") or " ".join(result["rule_coverage"].get(t, {}).get("limitations", [])) or "Evaluated.", 220), "cell")]
                       for t, n in sorted(by_test.items())], [52 * mm, 18 * mm, 14 * mm, width - 84 * mm]))

    sample_counts = Counter(s["sheet"] for s in result["sample_items"])
    bases = Counter(explain.explain_sample(s, ctx)["selection_basis"] for s in result["sample_items"])
    story.append(p("How items were selected", "h1"))
    story.append(p(f"{len(result['sample_items'])} workpaper items were selected from {len(snapshot['invoices'])} invoices: {sample_counts['sales_tod']} for the sales test of details, "
                   f"{sample_counts['cutoff_tod']} for cut-off and {sample_counts['credit_note_tod']} credit notes. Selection basis: "
                   + ", ".join(f"{name} {count}" for name, count in sorted(bases.items())) + ". Random selections use a reproducible seeded draw, so anyone can re-create the same sample."))

    story.append(p("Limitations", "h1"))
    story.extend(p("• " + item) for item in report["limitations"])
    if report["differentiated_checks"]:
        checks = report["differentiated_checks"]
        attention = [c for c in checks if c.get("state") not in CLEAR_STATES]
        story.append(p("Demonstration checks", "h2"))
        story.append(p(f"{len(checks)} demonstration check(s) ran on synthetic, unverified inputs; {len(checks) - len(attention)} found no conflict." + (" These need attention:" if attention else ""), "small"))
        story.extend(p(f"• {c.get('object_ref')} · {c.get('test_id')} · {CHECK_STATES.get(c.get('state'), str(c.get('state')).replace('_', ' ').capitalize())}: {c.get('reason')}", "small") for c in attention)

    # Start the detail section on a new page only when little room is left (no near-empty pages).
    story.append(CondPageBreak(90 * mm))
    story.append(p("Findings in detail", "h1"))
    story.append(p("Each finding below is an automated signal for human review. “What was observed” is written from the frozen records; the rule note states the limits of the test.", "small"))
    for test in sorted(by_test):
        story.append(p(f"{test} · {TEST_NAMES.get(test, test)} ({by_test[test]})", "h2"))
        for f in (x for x in findings if x["test_id"] == test):
            review = f["human_decision"] or {}
            signal = SIGNAL.get(f["state"], "Needs review")
            outcome = OUTCOMES.get(review.get("outcome"), "Open review")
            evidence = f["evidence_ids"]
            rows = [[p(f["finding_id"], "cellb"), p(signal, "cellb")],
                    [p("Assertion: " + f["assertion"] + " · Record: " + str(f["object_ref"]), "cell"), p("Human outcome: " + outcome + (f" by {review['decided_by']}" if review.get("decided_by") else ""), "cell")],
                    [p("What was observed: " + explain.explain_finding(f, ctx), "cell"), ""],
                    [p("Rule note: " + f["reason"], "small"), ""],
                    [p(f"Evidence: {len(evidence)} reference(s)" + (": " + ", ".join(evidence[:3]) + (" …" if len(evidence) > 3 else "") if evidence else ""), "small"),
                     p("Impact: " + (f"INR {f['impact_inr']}" if f["impact_inr"] is not None else "Unquantified") + (" · Reviewer note: " + review["reason"] if review.get("reason") else ""), "small")]]
            block = Table(rows, colWidths=[width * 0.6, width * 0.4])
            block.setStyle(TableStyle([("SPAN", (0, 2), (1, 2)), ("SPAN", (0, 3), (1, 3)), ("BOX", (0, 0), (-1, -1), 0.6, line), ("BACKGROUND", (0, 0), (-1, 0), tint[signal]),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                       ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story += [KeepTogether([block]), Spacer(1, 5)]

    receipt = report["receipt"]
    story += [CondPageBreak(70 * mm), p("Appendix: reproducibility", "h1"),
              p("Anyone holding the same snapshot, rules and seed can re-create this package exactly. These values identify it.", "small"), Spacer(1, 4),
              grid([[p(k, "cellb"), p(v, "small")] for k, v in (("Export package", "P5-" + content_hash), ("Snapshot root", receipt["snapshot_root"]),
                    ("Ruleset", f"{receipt['ruleset_version']} · hash {receipt['ruleset_hash']}"), ("Sampler", receipt["sampler_version"]), ("Sampling seed", receipt["sampling_seed"]),
                    ("Selection digest", receipt["selection_digest"]), ("Register source SHA-256", receipt["source_sha256"]), ("Canonicalization", receipt["canonicalization_version"]),
                    ("Export version", receipt["export_version"]))], [42 * mm, width - 42 * mm], header=False)]

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"Findings memo - {audit_name}", author="Pramaan")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(line)
        canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
        canvas.setFont("PramaanVera", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, "DEMO: no official IRP verification or external anchor · " + audit_name[:70])
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, "Page " + str(document.page))
        canvas.restoreState()

    def stable_canvas(*args, **kwargs):
        kwargs["invariant"] = True
        return Canvas(*args, **kwargs)
    doc.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=stable_canvas)
    return output.getvalue()


README = """Pramaan defensibility pack
==========================

workpaper.xlsx              Formatted workpapers. Open the Overview sheet first.
findings_memo.pdf           Readable findings memo with headline totals and every finding.
original_register.csv       The client's register exactly as uploaded (byte-for-byte).
report.json                 The complete frozen export package.
receipt.json                Identifiers and hashes needed to reproduce this package.
evidence_index.json         Every evidence reference with provenance and hashes.
sample_evidence_index.json  Evidence references grouped by selected sample.
standards.json              Candidate auditing-standard mapping per test.
audit_log_verification.json Hash-chain verification captured when the package was frozen.

All sources are company-supplied or synthetic and unverified. Automated
observations are signals for human review, not audit conclusions.
"""


def original_register(report):
    from .p5 import register_bytes
    return register_bytes(report["register"])


def pack_bytes(report, content_hash):
    # Log verification is captured in the package model, not re-read at export.
    return deterministic_zip({"README.txt": README.encode("utf-8"), "workpaper.xlsx": workbook_bytes(report, content_hash), "findings_memo.pdf": memo_bytes(report, content_hash),
                              "original_register.csv": original_register(report),
                              "evidence_index.json": p1.canonical(report["evidence_index"]), "standards.json": p1.canonical(report["standards"]),
                              "receipt.json": p1.canonical({**report["receipt"], "output_content_digest": content_hash}),
                              "sample_evidence_index.json": p1.canonical([{"sample": s, "evidence_ids": sorted({e for f in report["findings"] for e in f["evidence_ids"] if any(item["sheet"] == s["sheet"] and item["object_ref"] == s["object_ref"] for item in f["samples"])})} for s in report["result"]["sample_items"]]),
                              "audit_log_verification.json": p1.canonical(report["audit_log_verification"]), "report.json": p1.canonical(report)})
