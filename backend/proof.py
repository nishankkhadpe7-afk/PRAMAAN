"""Proof chain and "How we know" for a finding, built only from the frozen audit run.

* The proof chain follows each invoice a finding touches through every record PRAMAAN holds: books,
  the sales register, GSTR-1, dispatch and e-way bill, transport, e-invoice, credit notes and the bank.
  Each link says whether that record agrees with the books, differs, is missing, or does not apply.
* "How we know" restates the check's own inputs as a calculation with the real numbers, lists the
  source files (with their SHA-256) the numbers came from, and what would still be needed to close it.

Everything is computed by code from the run's frozen snapshot and result; no AI is involved. The bank
statement is the one exception: it is read as currently stored and labelled as not part of the run.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

STATE_STATUS = {"GOVERNMENT_REGISTERED_DEMO": "match", "INCONSISTENT": "differs", "UNAVAILABLE": "missing", "UNVERIFIED": "missing"}
FIELD_NAMES = {"taxable_amount": "Taxable value", "gross_amount": "Invoice value", "cgst": "CGST", "sgst": "SGST", "igst": "IGST",
               "invoice_date": "Invoice date", "buyer_gstin": "Buyer GSTIN", "seller_gstin": "Seller GSTIN"}


def _inr(cents: int | float | Decimal | None) -> str:
    if cents is None:
        return "—"
    value = Decimal(str(cents)) / 100
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join(groups + [tail]) if groups else tail}.{frac}"


def _rupees(value: Any) -> str:
    return _inr(int(Decimal(str(value)) * 100)) if value not in (None, "") else "—"


def _d(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


class Run:
    def __init__(self, db: sqlite3.Connection, run_id: str):
        row = db.execute("SELECT snapshot_json, result_json, ruleset_json, period_start, period_end FROM p3_audit_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "audit run not found")
        self.db, self.run_id = db, run_id
        self.snapshot, self.result, self.ruleset = json.loads(row[0]), json.loads(row[1]), json.loads(row[2])
        self.period_start, self.period_end = _d(row[3]), _d(row[4])
        snap = self.snapshot
        self.invoices = {i["invoice_id"]: i for i in snap["invoices"]}
        self.by_bill = {i["bill_no"]: i for i in snap["invoices"]}
        src = snap.get("source_data") or {}
        self.detail = {r["invoice_id"]: r for r in src.get("invoices.csv", [])}
        self.dispatch = {r["invoice_id"]: r for r in src.get("dispatches.csv", [])}
        self.route = {r["invoice_id"]: r for r in src.get("movement_routes.csv", [])}
        self.gstr_row = {r["invoice_no"]: r for r in src.get("gstr1_rows.csv", [])}
        self.verification = {r["invoice_id"]: r for r in src.get("invoice_verification_status.csv", [])}
        self.journals = src.get("journal_entries.csv", [])
        self.prices = src.get("price_lists.csv", [])
        self.item_for_hsn = (self.ruleset.get("pricing") or {}).get("hsn_to_item_code", {})
        self.history = src.get("historical_sales.csv", [])
        self.files = {f["file_name"]: f["sha256"] for f in (snap.get("dataset_manifest") or {}).get("files", [])}
        self.credits: dict[str, list[dict]] = {}
        for note in snap["credit_notes"]:
            self.credits.setdefault(note["invoice_id"], []).append(note)
        self.findings = self.result["findings"]
        self.registers = []
        for upload in snap.get("register_uploads") or []:
            rows = {}
            for r in upload.get("rows", []):
                raw = json.loads(r["raw_json"])
                if raw.get("Bill No"):
                    rows.setdefault(str(raw["Bill No"]).strip(), raw)
            recon = upload["reconciliations"][-1] if upload.get("reconciliations") else None
            found = {}
            if recon:
                for f in json.loads(recon["findings_json"]):
                    found.setdefault(f.get("bill_no"), f)
            gstr1 = bool(rows) and all(v.get("Return") == "GSTR-1" for v in rows.values())
            months = {v.get("Return Period") for v in rows.values()} if gstr1 else set()
            self.registers.append({"upload_id": upload["upload_id"], "period": upload["period"], "sha256": upload["sha256"], "rows": rows,
                                   "findings": found, "reconciled": recon is not None, "gstr1": gstr1,
                                   "month": next(iter(months)) if len(months) == 1 else None})

    def finding(self, finding_id: str) -> dict[str, Any]:
        for f in self.findings:
            if f["finding_id"] == finding_id:
                return f
        for reg in self.registers:
            for f in reg["findings"].values():
                if f.get("finding_id") == finding_id:
                    return {**f, "upload_id": reg["upload_id"], "register_period": reg["period"]}
        raise HTTPException(404, "finding not found in this run")

    def invoice_refs(self, f: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for ref in [f.get("object_ref"), *f.get("invoice_ids", []), f.get("invoice_id")]:
            if ref in self.invoices and ref not in refs:
                refs.append(ref)
        if f.get("object_ref", "").count(":") == 1 and not refs:
            refs += [r for r in f["object_ref"].split(":") if r in self.invoices]
        if f.get("test_id") == "T08" and f.get("window_start"):
            start = _d(f["window_start"])
            refs += [i["invoice_id"] for i in self.snapshot["invoices"] if i["customer_id"] == f["object_ref"] and start <= _d(i["invoice_date"]) <= self.period_end]
        bill = f.get("bill_no")
        if bill in self.by_bill and self.by_bill[bill]["invoice_id"] not in refs:
            refs.append(self.by_bill[bill]["invoice_id"])
        for note in self.snapshot["credit_notes"]:
            if note["credit_note_id"] in (f.get("object_ref"), bill) and note["invoice_id"] not in refs:
                refs.append(note["invoice_id"])
        return refs[:6]

    # ------------------------------------------------------------------ proof chain
    def chain(self, invoice_id: str) -> dict[str, Any]:
        inv = self.invoices[invoice_id]
        gross, bill, when = inv["gross_cents"], inv["bill_no"], _d(inv["invoice_date"])
        links = [{"stage": "Books", "status": "recorded", "title": f"{bill} · {inv['customer_name']}",
                  "detail": f"{_inr(gross)} on {when:%d %b %Y}" + (f" · buyer GSTIN {inv['gstin']}" if inv.get("gstin") else " · B2C (no buyer GSTIN)"),
                  "source": "Books entered in PRAMAAN (frozen in this run)"}]
        for reg in (r for r in self.registers if not r["gstr1"]):
            links.append(self._register_link(reg, bill, "Sales register"))
        months = [r for r in self.registers if r["gstr1"] and r["month"] == f"{when:%Y-%m}"]
        if not inv.get("gstin"):
            links.append({"stage": "GST return (GSTR-1)", "status": "not_applicable", "title": "B2C sale",
                          "detail": "Filed in GSTR-1 as part of the B2C totals, not invoice by invoice.", "source": None})
        elif months:
            links.append(self._register_link(months[0], bill, "GST return (GSTR-1)"))
        elif bill in self.gstr_row:
            row = self.gstr_row[bill]
            diff = int(Decimal(row["gross_value"]) * 100) - gross
            links.append({"stage": "GST return (GSTR-1)", "status": "match" if diff == 0 else "differs",
                          "title": f"GSTR-1 row, period {row['return_period']}",
                          "detail": f"Return shows {_rupees(row['gross_value'])}" + ("" if diff == 0 else f", books {_inr(gross)} (difference {_inr(diff)})"),
                          "source": self._file("gstr1_rows.csv")})
        else:
            links.append({"stage": "GST return (GSTR-1)", "status": "missing" if when <= self.period_end else "not_applicable",
                          "title": "No GSTR-1 for this month supplied" if when <= self.period_end else "After the audit period",
                          "detail": "Upload that month's GSTR-1 JSON to check it." if when <= self.period_end else "", "source": None})
        price = self._price_link(inv)
        if price:
            links.append(price)
        links.append(self._dispatch_link(inv))
        links.append(self._route_link(inv))
        links.append(self._einvoice_link(inv))
        for note in self.credits.get(invoice_id, []):
            after = _d(note["credit_date"]) > self.period_end
            share = Decimal(note["amount_cents"]) / gross * 100 if gross else Decimal(0)
            links.append({"stage": "Credit note", "status": "differs" if after and when <= self.period_end else "info",
                          "title": f"{note['credit_note_id']} on {_d(note['credit_date']):%d %b %Y}",
                          "detail": f"{_inr(note['amount_cents'])} ({share:.0f}% of the invoice) · {note.get('reason') or ''}"
                                    + (f" · issued {(_d(note['credit_date']) - self.period_end).days} days after the year closed" if after and when <= self.period_end else ""),
                          "source": "Books (frozen in this run)"})
        links.append(self._bank_link(inv))
        problems = sum(1 for l in links if l["status"] in ("differs", "missing"))
        return {"invoice_id": invoice_id, "bill_no": bill, "customer": inv["customer_name"], "links": links,
                "summary": "Every record holding this sale agrees with the books." if not problems else
                           f"{problems} of {sum(1 for l in links if l['status'] not in ('not_applicable', 'recorded', 'info'))} checked records disagree with the books or are missing."}

    def _file(self, name: str) -> dict[str, str] | None:
        return {"file": name, "sha256": self.files[name]} if name in self.files else None

    def _register_link(self, reg: dict, bill: str, stage: str) -> dict[str, Any]:
        source = {"file": reg["period"], "sha256": reg["sha256"]}
        row, finding = reg["rows"].get(bill), reg["findings"].get(bill)
        if row is None:
            return {"stage": stage, "status": "missing", "title": f"Not in {reg['period']}",
                    "detail": "The books have this invoice; the uploaded file does not.", "source": source}
        if finding and finding.get("category") == "FIELD_DIFF":
            parts = [f"{d['field']}: file {d.get('register_value')} vs books {d.get('system_value')}" for d in finding.get("field_differences", []) if d.get("comparison") == "DIFFERENT"]
            return {"stage": stage, "status": "differs", "title": f"In {reg['period']}, but different", "detail": "; ".join(parts), "source": source}
        if finding and finding.get("category") in ("PARSE_REVIEW", "DUPLICATE_ROW"):
            return {"stage": stage, "status": "differs", "title": f"In {reg['period']}, needs review", "detail": finding.get("reason", ""), "source": source}
        amount = row.get("Gross Amt")
        return {"stage": stage, "status": "match" if reg["reconciled"] else "info", "title": f"In {reg['period']}",
                "detail": f"Shows {_rupees(amount)}, same as the books" if reg["reconciled"] else "Not reconciled yet", "source": source}

    def _price_link(self, inv: dict) -> dict[str, Any] | None:
        det = self.detail.get(inv["invoice_id"])
        item = self.item_for_hsn.get(str(det["hsn_code"])) if det else None
        if not item:
            return None
        when = _d(inv["invoice_date"])
        listed = next((p for p in self.prices if p["item_code"] == item and p["customer_id"] == inv["customer_id"] and _d(p["valid_from"]) <= when
                       and (not p.get("valid_to") or _d(p["valid_to"]) >= when)), None)
        if not listed:
            return None
        unit = Decimal(det["taxable_amount"]) / Decimal(det["quantity"])
        agreed = Decimal(listed["unit_price"])
        same = abs(unit - agreed) <= Decimal(str((self.ruleset.get("pricing") or {}).get("unit_price_tolerance_inr", "0")))
        return {"stage": "Agreed price", "status": "match" if same else "differs", "title": f"Rate contract {listed['price_list_id']}",
                "detail": f"Billed {_rupees(unit)} per unit; agreed {_rupees(agreed)}" + ("" if same else f" ({(unit - agreed) / agreed * 100:+.1f}%)"),
                "source": self._file("price_lists.csv")}

    def _dispatch_link(self, inv: dict) -> dict[str, Any]:
        d = self.dispatch.get(inv["invoice_id"])
        if inv["invoice_id"] not in self.detail:
            return {"stage": "Dispatch & e-way bill", "status": "not_applicable" if not inv.get("gstin") else "missing",
                    "title": "No transport documents in the files", "detail": "Only B2B sales carry dispatch detail in this data." if not inv.get("gstin") else "", "source": None}
        if not d:
            return {"stage": "Dispatch & e-way bill", "status": "missing", "title": "No dispatch record",
                    "detail": "No lorry receipt, e-way bill or proof of delivery: nothing shows the goods left the warehouse.", "source": self._file("dispatches.csv")}
        det = self.detail[inv["invoice_id"]]
        limit = int(Decimal(str(self.ruleset.get("movement_documents", {}).get("e_way_bill_min_value_inr", "50000"))) * 100)
        problems = []
        if Decimal(d["taxable_value"]) != Decimal(det["taxable_amount"]):
            problems.append(f"value {_rupees(d['taxable_value'])} vs invoice {_rupees(det['taxable_amount'])}")
        if Decimal(d["quantity"]) != Decimal(det["quantity"]):
            problems.append(f"quantity {d['quantity']} vs invoice {det['quantity']}")
        if inv["gross_cents"] > limit and not d.get("eway_bill_no"):
            problems.append(f"no e-way bill for a consignment above {_inr(limit)}")
        docs = [x for x in (f"LR {d['document_no']}" if d.get("document_no") else "", f"e-way bill {d['eway_bill_no']}" if d.get("eway_bill_no") else "",
                            f"POD {d['proof_of_delivery']}" if d.get("proof_of_delivery") else "") if x]
        return {"stage": "Dispatch & e-way bill", "status": "differs" if problems else "match", "title": f"Dispatched {_d(d['dispatch_date']):%d %b %Y}",
                "detail": "; ".join(problems) if problems else ", ".join(docs), "source": self._file("dispatches.csv")}

    def _route_link(self, inv: dict) -> dict[str, Any]:
        r = self.route.get(inv["invoice_id"])
        if not r:
            return {"stage": "Transport", "status": "not_applicable" if not inv.get("gstin") or inv["invoice_id"] not in self.detail else "missing",
                    "title": "No trip record", "detail": "", "source": None}
        hours = (datetime.fromisoformat(r["arrive_ts"]) - datetime.fromisoformat(r["depart_ts"])).total_seconds() / 3600
        speed = Decimal(r["distance_km"]) / Decimal(str(hours)) if hours > 0 else None
        t11 = self.ruleset.get("t11", {})
        limit = Decimal(str(t11.get("max_road_speed_kmph", "120"))) + Decimal(str(t11.get("speed_tolerance_kmph", "10")))
        problems = [f["subcheck"].split("_", 1)[1].replace("_", " ") for f in self.findings
                    if f["test_id"] == "T11" and (f["object_ref"] == inv["invoice_id"] or inv["invoice_id"] in str(f["object_ref"]).split(":"))]
        detail = f"{r['route_origin']} → {r['route_destination']}, {r['distance_km']} km in {hours:.0f} h"
        if speed is not None:
            detail += f" ({speed:.0f} km/h; limit {limit:.0f})"
        detail += f" · vehicle {r['vehicle_no']}, load {r['quantity_units']} of {r['vehicle_capacity_units']} units"
        return {"stage": "Transport", "status": "differs" if problems else "match",
                "title": "Trip cannot be true: " + ", ".join(problems) if problems else "Trip is physically possible", "detail": detail, "source": self._file("movement_routes.csv")}

    def _einvoice_link(self, inv: dict) -> dict[str, Any]:
        v = self.verification.get(inv["invoice_id"])
        if not inv.get("gstin"):
            return {"stage": "E-invoice (IRN + signed QR)", "status": "not_applicable", "title": "B2C sale", "detail": "E-invoicing applies to B2B sales.", "source": None}
        if not v:
            return {"stage": "E-invoice (IRN + signed QR)", "status": "missing", "title": "No e-invoice record", "detail": "", "source": None}
        f = next((x for x in self.findings if x["test_id"] == "T13" and x["object_ref"] == inv["invoice_id"]), {})
        state = f.get("state", "UNVERIFIED")
        detail = {"GOVERNMENT_REGISTERED_DEMO": "Signature verifies against the demo key and the signed fields match the books",
                  "INCONSISTENT": "Signature verifies, but the signed " + ", ".join(m.replace("_cents", "").replace("_", " ") for m in f.get("field_mismatches", [])) + " differ from the books",
                  "UNAVAILABLE": "No IRN and no signed QR: registration cannot be checked",
                  "UNVERIFIED": "IRN present but no signed QR supplied"}.get(state, f.get("reason", ""))
        if f.get("registration_timing_risk"):
            detail += f" · registered {f.get('registration_timing_days')} days after the invoice date"
        return {"stage": "E-invoice (IRN + signed QR)", "status": "differs" if f.get("registration_timing_risk") and state == "GOVERNMENT_REGISTERED_DEMO" else STATE_STATUS.get(state, "info"),
                "title": state.replace("_", " ").title().replace("Demo", "(demo key)"), "detail": detail, "source": self._file("invoice_verification_status.csv")}

    def _bank_link(self, inv: dict) -> dict[str, Any]:
        due = inv["gross_cents"] - sum(n["amount_cents"] for n in self.credits.get(inv["invoice_id"], []))
        try:
            rows = self.db.execute("SELECT txn_date, amount_cents, narration FROM p6_bank_rows WHERE direction='credit' AND narration LIKE ? ORDER BY txn_date",
                                   (f"%{inv['bill_no']}%",)).fetchall()
            has_statement = self.db.execute("SELECT COUNT(*) FROM p6_bank_statements").fetchone()[0] > 0
        except sqlite3.OperationalError:
            rows, has_statement = [], False
        note = "Bank statement as currently stored (not part of the frozen run)"
        if not has_statement:
            return {"stage": "Payment received", "status": "not_applicable", "title": "No bank statement uploaded", "detail": "", "source": None}
        if due <= 0:
            return {"stage": "Payment received", "status": "not_applicable", "title": "Nothing due", "detail": "Fully reversed by credit notes.", "source": note}
        if not rows:
            return {"stage": "Payment received", "status": "missing", "title": "No receipt naming this bill",
                    "detail": f"{_inr(due)} due; no bank credit mentions {inv['bill_no']}.", "source": note}
        paid = sum(r[1] for r in rows)
        return {"stage": "Payment received", "status": "match" if paid == due else "differs", "title": f"Received {_d(rows[0][0]):%d %b %Y}",
                "detail": f"{_inr(paid)} received against {_inr(due)} due" + ("" if paid == due else f" (difference {_inr(paid - due)})"), "source": note}

    # ------------------------------------------------------------------ how we know
    def how(self, f: dict[str, Any]) -> dict[str, Any]:
        test = f.get("test_id")
        calc: list[str] = []
        files: list[str] = []
        missing: list[str] = []
        rule = f.get("reason", "")
        bill = lambda ref: self.invoices[ref]["bill_no"] if ref in self.invoices else ref
        if test == "T00":
            rule = f"The register row must match the books exactly (rule {f.get('ruleset_version', 'T00')})."
            for d in f.get("field_differences", []):
                if d.get("comparison") == "DIFFERENT":
                    nd = d.get("normalized_difference")
                    diff = f"₹{nd['inr']}" if isinstance(nd, dict) and nd.get("inr") else (f"{nd['days']} days" if isinstance(nd, dict) and "days" in nd else (str(nd) if nd else ""))
                    calc.append(f"{d['field']}: file says {d.get('register_value')}, books say {d.get('system_value')}" + (f" → difference {diff}" if diff else ""))
            if f.get("category") == "SYSTEM_ONLY":
                inv = self.by_bill.get(f.get("bill_no"))
                calc.append(f"{f.get('bill_no')} is in the books" + (f" ({_inr(inv['gross_cents'])} on {_d(inv['invoice_date']):%d %b %Y})" if inv else "") + f" but not in {f.get('register_period', 'the uploaded file')}.")
                missing.append("An explanation from the company of why this sale is missing from the file, or a corrected file.")
            if f.get("category") == "REGISTER_ONLY":
                calc.append(f"{f.get('bill_no')} is in the uploaded file but not in the books.")
            files.append(f"Uploaded file: {f.get('register_period', 'register')}")
        elif test == "T08":
            mult = Decimal(str(self.ruleset["period_end_concentration"]["multiple_threshold"]))
            days = self.ruleset["period_end_concentration"]["window_days"]
            cur, avg = Decimal(f["current_gross"]), Decimal(f["historical_monthly_average"])
            rule = f"Sales to one customer in the last {days} days of the year should not exceed {mult}× that customer's usual month."
            calc += [f"Sales in the last {days} days: {_rupees(cur)}", f"Usual month (average of {f.get('historical_months')} prior months): {_rupees(avg)}",
                     f"{_rupees(cur)} ÷ {_rupees(avg)} = {cur / avg:.1f}× (limit {mult}×)"]
            files += ["invoices.csv", "historical_sales.csv"]
            missing.append("Orders, delivery proof and payment for these year-end sales, or the business reason for the spike.")
        elif test == "T09":
            note = next((n for n in self.snapshot["credit_notes"] if n["credit_note_id"] == f["object_ref"]), None)
            if note:
                inv = self.invoices.get(note["invoice_id"], {})
                late = (_d(note["credit_date"]) - self.period_end).days
                share = Decimal(note["amount_cents"]) / inv["gross_cents"] * 100 if inv.get("gross_cents") else Decimal(0)
                rule = "A credit note issued after the year end against a sale inside the year may mean that revenue was recorded and then reversed."
                calc += [f"Invoice {note['bill_no']} on {_d(note['invoice_date']):%d %b %Y}: {_inr(inv.get('gross_cents'))}",
                         f"Credit note {note['credit_note_id']} on {_d(note['credit_date']):%d %b %Y}: {_inr(note['amount_cents'])} ({share:.0f}% reversed)",
                         f"Issued {late} days after the year closed on {self.period_end:%d %b %Y}"]
            missing.append("Goods-return evidence (return note, inward stock entry) supporting the credit note.")
        elif test == "T10":
            ids = f.get("invoice_ids", [])
            amounts = [Decimal(self.detail[i]["gross_amount"]) if i in self.detail else Decimal(self.invoices[i]["gross_cents"]) / 100 for i in ids if i in self.invoices]
            thr = Decimal(f["threshold_inr"])
            rule = f"One order must not be split into bills that each stay under the {_rupees(thr)} approval limit."
            for i, a in zip(ids, amounts):
                calc.append(f"{bill(i)} on {_d(self.invoices[i]['invoice_date']):%d %b %Y}: {_rupees(a)} (under the limit, at least half of it)")
            if len(amounts) == 2:
                gap = abs((_d(self.invoices[ids[1]]['invoice_date']) - _d(self.invoices[ids[0]]['invoice_date'])).days)
                calc.append(f"Together {_rupees(sum(amounts))} ≥ {_rupees(thr)}, same buyer and product, {gap} day{'s' if gap != 1 else ''} apart (window {f.get('window_days')} days)")
            files += ["invoices.csv", "threshold_policies.csv"]
            missing.append("The purchase order(s) behind both bills, and whether the approval was obtained.")
        elif test == "T11":
            sub = f.get("subcheck", "")
            route = self.route.get(str(f["object_ref"]).split(":")[0], {})
            rule = "Transport records must be physically possible."
            if sub == "P1_route_time" and route:
                hours = (datetime.fromisoformat(route["arrive_ts"]) - datetime.fromisoformat(route["depart_ts"])).total_seconds() / 3600
                calc += [f"{route['route_origin']} → {route['route_destination']}: {route['distance_km']} km", f"Departed {route['depart_ts'].replace('T', ' ')}, arrived {route['arrive_ts'].replace('T', ' ')}: {hours:.0f} hours",
                         f"{route['distance_km']} km ÷ {hours:.0f} h = {f.get('implied_speed_kmph')} km/h, above the {f.get('max_road_speed_kmph')} km/h road limit"]
            elif sub == "P2_vehicle_overlap":
                calc.append(f"Vehicle {f.get('vehicle_no', route.get('vehicle_no', ''))} is recorded on two trips at the same time: {', '.join(bill(i) for i in str(f['object_ref']).split(':'))}")
            elif sub == "P3_load_estimate" and route:
                calc.append(f"Load {route['quantity_units']} units on a vehicle that carries {route['vehicle_capacity_units']}: {Decimal(route['quantity_units']) / Decimal(route['vehicle_capacity_units']) * 100:.0f}% of capacity")
            elif sub == "P5_pin_consignee" and route:
                inv = self.invoices.get(f["object_ref"], {})
                calc.append(f"Buyer GSTIN state {str(inv.get('gstin', ''))[:2]}, but the goods were delivered to GSTIN state {route['consignee_gstin'][:2]} ({route['to_pin']})")
            else:
                calc.append(f.get("reason", ""))
            files.append("movement_routes.csv")
            missing.append("GPS / FASTag trip logs or the transporter's records for this trip.")
        elif test == "T13":
            inv = self.invoices.get(f["object_ref"], {})
            rule = "A signed e-invoice QR must verify against the trusted key and match the books on the signed fields."
            if f.get("state") == "GOVERNMENT_REGISTERED_DEMO":
                calc.append("Signature: valid. Every signed field (IRN, bill number, buyer and seller GSTIN, amount, HSN, date) matches the books.")
            if f.get("state") == "INCONSISTENT":
                calc.append("Signature: valid. Fields that differ from the books: " + ", ".join(m.replace("_cents", "").replace("_", " ") for m in f.get("field_mismatches", [])))
                calc.append(f"Books amount {_inr(inv.get('gross_cents'))}: the invoice was changed after it was signed and registered.")
            elif f.get("state") in ("UNAVAILABLE", "UNVERIFIED"):
                calc.append("No signed QR code supplied, so registration on the invoice portal cannot be checked.")
                missing.append("The e-invoice IRN and signed QR from the invoice registration portal.")
            if f.get("registration_timing_risk"):
                calc.append(f"Registered on {f.get('ack_date')}, {f.get('registration_timing_days')} days after the invoice date {f.get('invoice_date')}: possible backdating.")
            calc.append("Key used: PRAMAAN demo key (not a government key).")
            files.append("invoice_verification_status.csv")
        elif test == "T14":
            if f.get("observed_unit_value"):
                seen, listed = Decimal(f["observed_unit_value"]), Decimal(f["listed_unit_price"])
                rule = "A contract customer must be billed at the agreed price unless an approved scheme applies."
                calc += [f"Billed {_rupees(seen)} per unit; agreed price {_rupees(listed)} ({f.get('price_list_id')})",
                         f"{(seen - listed) / listed * 100:+.1f}% against the price list, with no approved scheme covering it"]
                files += ["invoices.csv", "price_lists.csv", "promotions.csv"]
                missing.append("An approved discount or a revised price agreement.")
            else:
                rule = "A discount scheme needs an approval reference."
                calc.append(f"Scheme {f['object_ref']} has no approval reference.")
                files.append("promotions.csv")
                missing.append("The approval for the scheme.")
        elif test == "T15":
            rule = "Each invoice must be reported in GSTR-1 exactly as in the books."
            for field, v in (f.get("differences") or {}).items():
                books, ret = Decimal(str(v["books"])), Decimal(str(v["synthetic_return_row"]))
                pct = f" ({ret / books * 100:.0f}% of the books)" if books else ""
                calc.append(f"{FIELD_NAMES.get(field, field.replace('_', ' '))}: books {_rupees(books)}, return {_rupees(ret)}{pct}")
            files += ["invoices.csv", "gstr1_rows.csv"]
            missing.append("An amended return or the company's reconciliation of GSTR-1 to the books.")
        elif test == "T05":
            lines = [l for l in self.journals if l["journal_id"] == f["object_ref"]]
            rule = "Revenue must come from an invoice; a revenue credit with no invoice cannot be traced to a sale."
            for l in lines:
                side = f"Dr {_rupees(l['debit'])}" if Decimal(l["debit"]) else f"Cr {_rupees(l['credit'])}"
                calc.append(f"{l['posting_date']} · {l['account']} · {side} · \"{l['description']}\"")
            files.append("journal_entries.csv")
            missing.append("Who passed this entry, who approved it, and the sale it represents.")
        elif test == "T06":
            ref = f["object_ref"]
            if f.get("state") == "GAP":
                rule = "Every B2B sale should have a dispatch record (lorry receipt, e-way bill, proof of delivery)."
                inv = self.invoices.get(ref, {})
                calc.append(f"{bill(ref)} ({_inr(inv.get('gross_cents'))}) has no dispatch record in dispatches.csv.")
                missing.append("Lorry receipt, e-way bill and proof of delivery for this sale.")
            else:
                for field, v in (f.get("differences") or {}).items():
                    calc.append(f"{field}: invoice {v.get('invoice')}, dispatch {v.get('dispatch')}")
            files += ["invoices.csv", "dispatches.csv"]
        elif test == "T04":
            rule = "Sampled sales need their movement documents; an e-way bill only above the configured value."
            calc.append("Missing: " + ", ".join(f.get("missing_documents", [])))
            missing.append("Upload the missing documents through the evidence request.")
        elif test == "T03":
            rule = "Around the year end, the revenue period depends on when control passed to the buyer."
            calc.append(f"Invoice {f.get('invoice_date')}, dispatch {f.get('dispatch_date')}, {f.get('period_side', '').replace('-', ' ')} the year end; no contract or delivery-terms date is on record.")
            missing.append("Delivery terms (Incoterms) or proof of delivery date.")
        elif test == "T02":
            rule = "Relationships that are not disclosed, or that form a loop, need corroboration."
            path = f.get("cycle_path")
            if path:
                calc.append("Loop: " + " → ".join(str(p) for p in path))
            else:
                calc.append(f"{f.get('subject_id', f['object_ref'])} → {f.get('object_id', '')} ({f.get('relationship_type', '').replace('_', ' ')}), source {f.get('source_type', '')}")
            files.append("related_party_edges.csv")
            missing.append("MCA director records and the company's related-party register.")
        elif test == "T01":
            rule = "Sales to a disclosed related party are allowed but need disclosure and an arm's-length price."
            calc.append(f"Relationship: {f.get('relationship_type', '')} (disclosed in {f.get('source_ref', 'the related-party register')}).")
            files.append("related_party_edges.csv")
        if not calc:
            calc.append(f.get("reason", ""))
        sources = [{"file": n, "sha256": self.files.get(n)} for n in files if n in self.files] + [{"file": n, "sha256": None} for n in files if n not in self.files]
        return {"rule": rule, "calculation": [c for c in calc if c], "sources": sources, "still_needed": missing,
                "computed_by": "PRAMAAN's rule engine from the frozen audit run; no AI involved."}


def proof(db: sqlite3.Connection, run_id: str, finding_id: str) -> dict[str, Any]:
    run = Run(db, run_id)
    finding = run.finding(finding_id)
    return {"run_id": run_id, "finding_id": finding_id, "test_id": finding.get("test_id"), "how": run.how(finding),
            "chains": [run.chain(ref) for ref in run.invoice_refs(finding)]}
