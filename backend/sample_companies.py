"""Two fictional Indian companies for trying PRAMAAN end to end. SYNTHETIC data only.

Trading patterns (which customer buys what, how much, how often, and returns) come from a small
extract of UCI Online Retail II (CC BY 4.0, see docs/sample-companies/README.md). Everything Indian
is generated here: company and customer names, GSTINs (valid check digits, not real registrations),
states, HSN codes, an illustrative 18% GST rate, vehicles, routes, e-invoice QR codes signed with
PRAMAAN's labelled DEMO key, and FY 2025-26 dates.

  * Kesar Home Decor Pvt Ltd (Bhiwandi, MH) - "honest": its records agree with each other.
  * Neelgiri Lifestyle Pvt Ltd (Surat, GJ)  - "hiding": inflates year-end sales through a related
    shell customer and hides other things; the answer key is docs/sample-companies/ANSWER_KEY.md.

    python -m Pramaan.backend.sample_companies            # rebuild docs/sample-companies/
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from . import p3_crypto

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "sample-companies"
EXTRACT = OUT / "source" / "online_retail_ii_extract.csv"
PERIOD_START, PERIOD_END = date(2025, 4, 1), date(2026, 3, 31)
GST_RATE = Decimal("0.18")  # one illustrative rate; real rates depend on the HSN and the current notification
QTY_SCALE, INR_PER_GBP = 4, Decimal("110")  # bulk B2B quantities; fixed conversion to rupees
EWAY_LIMIT = Decimal("50000")  # e-way bill needed above Rs 50,000 consignment value (interstate rule of thumb)

CITIES = {  # name: (GST state code, PIN, lat, lon)
    "Bhiwandi": ("27", "421302", 19.30, 73.06), "Mumbai": ("27", "400001", 18.94, 72.83), "Pune": ("27", "411001", 18.52, 73.86),
    "Nashik": ("27", "422001", 20.00, 73.79), "Nagpur": ("27", "440001", 21.15, 79.09), "Surat": ("24", "395003", 21.17, 72.83),
    "Ahmedabad": ("24", "380001", 23.03, 72.58), "Vadodara": ("24", "390001", 22.31, 73.18), "Rajkot": ("24", "360001", 22.30, 70.80),
    "Bengaluru": ("29", "560001", 12.97, 77.59), "Hyderabad": ("36", "500001", 17.39, 78.49), "Chennai": ("33", "600001", 13.08, 80.27),
    "Delhi": ("07", "110001", 28.63, 77.22), "Jaipur": ("08", "302001", 26.91, 75.79), "Indore": ("23", "452001", 22.72, 75.86),
    "Kolkata": ("19", "700001", 22.57, 88.36), "Panaji": ("30", "403001", 15.50, 73.83), "Lucknow": ("09", "226001", 26.85, 80.95),
    "Kochi": ("32", "682001", 9.93, 76.27),
}
HSN_RULES = [  # first keyword match wins
    (("HOLDER",), "7013"), (("LIGHT", "LANTERN", "LAMP"), "9405"), (("CANDLE",), "3406"), (("BAG",), "4202"),
    (("MUG", "CUP", "PLATE", "BOWL", "TEAPOT", "CAKE STAND", "JUG"), "6912"), (("CARD", "WRAP", "PAPER", "NOTEBOOK", "BOOK"), "4817"),
    (("TIN", "STEEL"), "7323"), (("FRAME",), "4414"), (("CUSHION",), "9404"), (("DOLL", "TOY", "GAME"), "9503"),
    (("CHALKBOARD", "SIGN", "BOARD"), "9610"), (("GLOVE", "APRON", "TOWEL", "TEA COSY"), "6302"), (("CLOCK",), "9105"),
]
DEFAULT_HSN = "9505"  # festive and decorative articles
NAMES = ["Shree Ganesh Traders", "Mahalaxmi Home Store", "Om Sai Retail", "Navkar Gift House", "Sagar Decor Mart", "Annapurna Kitchenware",
         "Rang Mahal Furnishings", "Vrindavan Handicrafts", "Kaveri Lifestyle", "Sahyadri Stores", "Marigold Gifting Co", "Peacock Home Centre",
         "Tulsi Enterprises", "Jyoti Party Supplies", "Ganga Bazaar", "Narmada Home Needs", "Kesari Collections", "Amrit Gift Gallery",
         "Shubh Labh Traders", "Deccan Decor House", "Chandan Craft Emporium", "Malabar Home Store", "Rajhans Retail", "Prakash Novelty Store",
         "Indraprastha Gifts", "Gulmohar Interiors", "Sitara Home Accents", "Konark Kitchen World", "Bodhi Lifestyle", "Saraswati Stationers",
         "Neem Tree Retail", "Mehendi Gift Corner", "Lotus Home Mart", "Panchavati Traders", "Anand Novelties", "Hampi Handicraft House",
         "Swastik Distributors", "Sangam Home Decor", "Vaibhav Gift Shop", "Arihant Housewares", "Dhanlaxmi Stores", "Kanchan Gift World",
         "Shivam Party Store", "Mangal Murti Traders", "Pooja Enterprises", "Rohini Crafts", "Ujjwal Retail", "Yamuna Home Store", "Chetak Traders", "Devika Lifestyle"]
CUSTOMER_CITIES = ["Mumbai", "Pune", "Nashik", "Nagpur", "Ahmedabad", "Vadodara", "Rajkot", "Bengaluru", "Hyderabad", "Chennai", "Delhi",
                   "Jaipur", "Indore", "Kolkata", "Panaji", "Lucknow", "Kochi", "Surat"]
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin(state: str, rng: random.Random, valid: bool = True) -> str:
    """A GSTIN-shaped identifier with a correct check digit. Synthetic: not a real registration."""
    pan = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(3)) + "C" + rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") \
        + f"{rng.randrange(1000, 9999)}" + rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ")
    body = state + pan + "1Z"
    total = 0
    for i, ch in enumerate(body):
        product = CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    check = CHARS[(36 - total % 36) % 36]
    if not valid:
        check = CHARS[(CHARS.index(check) + 7) % 36]
    return body + check


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def road_km(a: str, b: str) -> int:
    (_, _, la1, lo1), (_, _, la2, lo2) = CITIES[a], CITIES[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return max(25, round(2 * 6371 * math.asin(math.sqrt(h)) * 1.25))  # straight line x1.25 ~ road distance


def hsn_for(description: str) -> str:
    text = description.upper()
    return next((code for words, code in HSN_RULES if any(w in text for w in words)), DEFAULT_HSN)


def read_extract() -> list[dict[str, str]]:
    with EXTRACT.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def shift(d: str, years: int = 15) -> date:
    y, m, dd = map(int, d.split("-"))
    return date(y + years, m, dd)


class Company:
    def __init__(self, slug: str, name: str, city: str, keys: list[str], seed: str, hiding: bool):
        self.slug, self.name, self.city, self.hiding = slug, name, city, hiding
        self.rng = random.Random(seed)
        self.state = CITIES[city][0]
        self.gstin = gstin(self.state, self.rng)
        self.prefix = "KHD" if slug == "honest" else "NLP"
        self.customers: dict[str, dict[str, Any]] = {}
        self.invoices: list[dict[str, Any]] = []
        self.credit_notes: list[dict[str, Any]] = []
        self.planted: list[dict[str, Any]] = []
        names = list(NAMES)
        self.rng.shuffle(names)
        for i, key in enumerate(keys):
            city_name = CUSTOMER_CITIES[(i * 7 + (3 if hiding else 0)) % len(CUSTOMER_CITIES)]
            b2c = i % 9 == 8  # a few retail (B2C) buyers without a GSTIN
            self.customers[key] = {"customer_id": f"{self.prefix}-C{i + 1:03d}", "name": names[i], "city": city_name,
                                   "state": CITIES[city_name][0], "gstin": "" if b2c else gstin(CITIES[city_name][0], self.rng),
                                   "contract": i < 4}

    # ----- books -----------------------------------------------------------------------------
    def add_invoice(self, when: date, customer: dict, description: str, qty: int, unit: Decimal, **extra) -> dict:
        n = len(self.invoices) + 1
        taxable = (unit * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        intra = customer["state"] == self.state
        half = (taxable * GST_RATE / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cgst = sgst = half if intra else Decimal("0")
        igst = Decimal("0") if intra else (taxable * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fy = "25-26" if when <= PERIOD_END else "26-27"
        inv = {"invoice_id": f"{self.prefix}-I{n:04d}", "bill_no": f"{self.prefix}/{fy}/{n:04d}", "date": when, "customer": customer,
               "description": description, "hsn": hsn_for(description), "qty": qty, "unit": unit, "taxable": taxable,
               "cgst": cgst, "sgst": sgst, "igst": igst, "gross": taxable + cgst + sgst + igst, **extra}
        self.invoices.append(inv)
        return inv

    def build_books(self, rows: list[dict[str, str]]) -> None:
        contract_price: dict[tuple[str, str], Decimal] = {}
        by_key = defaultdict(list)
        for r in rows:
            by_key[r["customer_key"]].append(r)
        sales = [r for r in rows if r["kind"] == "sale" and r["customer_key"] in self.customers]
        for r in sales:
            c = self.customers[r["customer_key"]]
            unit = (Decimal(r["unit_price_gbp"]) * INR_PER_GBP).quantize(Decimal("0.01"))
            hsn = hsn_for(r["description"])
            if c["contract"]:  # contract customers buy at a fixed list price per item
                unit = contract_price.setdefault((c["customer_id"], hsn), unit)
            self.add_invoice(shift(r["date"]), c, r["description"].title(), int(r["quantity"]) * QTY_SCALE, unit)
        # A fortnight after year end (cut-off testing): the same customers' early-April pattern, next year.
        for r in sales:
            d = shift(r["date"], 16)
            if d <= date(2026, 4, 15):
                c = self.customers[r["customer_key"]]
                unit = contract_price.get((c["customer_id"], hsn_for(r["description"])), (Decimal(r["unit_price_gbp"]) * INR_PER_GBP).quantize(Decimal("0.01")))
                self.add_invoice(d, c, r["description"].title(), int(r["quantity"]) * QTY_SCALE, unit)
        self.contract_price = contract_price
        # Genuine returns become credit notes on that customer's most recent earlier sale.
        used = set()
        for r in rows:
            if r["kind"] != "return" or r["customer_key"] not in self.customers:
                continue
            c, when = self.customers[r["customer_key"]], shift(r["date"])
            earlier = [i for i in self.invoices if i["customer"] is c and i["date"] <= when and i["invoice_id"] not in used and i["date"] >= when - timedelta(days=60)]
            if not earlier or when > PERIOD_END:
                continue
            inv = max(earlier, key=lambda i: i["date"])
            amount = min(inv["gross"], (Decimal(r["unit_price_gbp"]) * INR_PER_GBP * int(r["quantity"]) * QTY_SCALE * (1 + GST_RATE)).quantize(Decimal("0.01")))
            used.add(inv["invoice_id"])
            self.credit_notes.append({"invoice": inv, "id": f"{self.prefix}-CN{len(self.credit_notes) + 1:03d}", "date": max(when, inv["date"]),
                                      "amount": amount, "reason": "Goods returned by customer (damaged or excess stock)"})

    # ----- what the hiding company does ------------------------------------------------------
    def plant(self) -> None:
        rng = self.rng
        shell = {"customer_id": f"{self.prefix}-C900", "name": "Vardhan Distributors", "city": "Ahmedabad", "state": "24",
                 "gstin": gstin("24", rng), "contract": False, "shell": True}
        partner = {"customer_id": f"{self.prefix}-C901", "name": "Om Sai Trading Company", "city": "Rajkot", "state": "24",
                   "gstin": gstin("24", rng, valid=False), "contract": False}
        self.customers["SHELL"], self.customers["PARTNER"] = shell, partner
        # Small, ordinary history for the shell so the year-end spike stands out against it.
        for month in (4, 6, 8, 10, 12):
            self.add_invoice(date(2025, month, 12), shell, "Assorted Festive Decor", 120, Decimal("410.00"), dispatch_ok=True)
        shell_bills = []
        for k, day in enumerate((24, 25, 26, 27, 28, 29, 30, 31, 31)):
            inv = self.add_invoice(date(2026, 3, day), shell, "Assorted Festive Decor", 1400 + 100 * k, Decimal("410.00"), no_dispatch=True, not_in_gstr1=True)
            shell_bills.append(inv)
        self.planted.append({"what": "Year-end sales to a related shell customer", "how": "9 large invoices to Vardhan Distributors in the last 8 days of March",
                             "refs": [i["bill_no"] for i in shell_bills], "checks": ["T08", "T06", "T02"]})
        self.planted.append({"what": "Shell sales left out of the GST return", "how": "The 9 shell invoices are in the books but not in March GSTR-1",
                             "refs": [i["bill_no"] for i in shell_bills], "checks": ["GSTR-1 import + T00 (SYSTEM_ONLY)"]})
        for k, inv in enumerate(shell_bills[:7]):
            self.credit_notes.append({"invoice": inv, "id": f"{self.prefix}-CN9{k + 1:02d}", "date": date(2026, 4, 8 + 3 * k),
                                      "amount": inv["gross"], "reason": "Sales return - goods not required"})
        self.planted.append({"what": "Year-end sales reversed after the year closed", "how": "7 of the 9 shell invoices fully reversed by credit notes in April 2026",
                             "refs": [f"{self.prefix}-CN9{k + 1:02d}" for k in range(7)], "checks": ["T09"]})
        # Related-party sales hidden from the register given to the auditor.
        partner_bills = [self.add_invoice(date(2026, m, d), partner, "Glass Tealight Holder", 900, Decimal("96.00"), hide_from_register=True)
                         for m, d in ((1, 9), (2, 6), (3, 5))]
        self.planted.append({"what": "Sales to a connected party hidden from the auditor's register", "how": "3 invoices to Om Sai Trading Company are in the books but missing from the register; its GSTIN check digit is also wrong",
                             "refs": [i["bill_no"] for i in partner_bills], "checks": ["T00 (SYSTEM_ONLY)", "GSTR-1 import (GSTIN warning)"]})
        regular = [i for i in self.invoices if not i["customer"].get("shell") and i["customer"] is not partner and PERIOD_START <= i["date"] <= PERIOD_END and i["customer"]["gstin"]]
        altered = max((i for i in regular if i["date"].month == 11), key=lambda i: i["gross"])
        altered["register_gross"] = altered["gross"] - Decimal("25000")
        self.planted.append({"what": "Amount changed in the register", "how": "One November invoice shows Rs 25,000 less in the register than in the books",
                             "refs": [altered["bill_no"]], "checks": ["T00 (FIELD_DIFF)"]})
        for inv in sorted((i for i in regular if i["date"].month == 2), key=lambda i: -i["gross"])[:2]:
            inv["gstr1_taxable"] = (inv["taxable"] * Decimal("0.6")).quantize(Decimal("0.01"))
        self.planted.append({"what": "Sales under-reported in GSTR-1", "how": "Two February invoices filed at 60% of their taxable value",
                             "refs": [i["bill_no"] for i in regular if "gstr1_taxable" in i], "checks": ["T15", "GSTR-1 import (FIELD_DIFF)"]})
        # Splitting one order into two bills just below the approval limit.
        buyer = next(c for c in self.customers.values() if c.get("gstin") and not c["contract"] and not c.get("shell") and c is not partner)
        split = [self.add_invoice(date(2026, 1, d), buyer, "Wooden Photo Frame Set", 3200, Decimal("210.00")) for d in (12, 14)]
        self.planted.append({"what": "One order split into two bills under the approval limit", "how": f"Two invoices to {buyer['name']} two days apart, each about Rs 7.9 lakh, together over the Rs 15 lakh approval limit",
                             "refs": [i["bill_no"] for i in split], "checks": ["T10"]})
        # Impossible or inconsistent transport.
        trip = max((i for i in regular if i["date"].month == 10 and i["customer"]["city"] in ("Delhi", "Lucknow", "Jaipur", "Kolkata")), key=lambda i: i["gross"], default=regular[0])
        trip["route_hours"] = 7
        twin = next(i for i in regular if i["date"] == trip["date"] and i is not trip) if any(i["date"] == trip["date"] and i is not trip for i in regular) else regular[1]
        twin["same_vehicle_as"] = trip
        overload = max((i for i in regular if i["date"].month == 9), key=lambda i: i["qty"])
        overload["over_capacity"] = True
        elsewhere = max((i for i in regular if i["date"].month == 12), key=lambda i: i["gross"])
        elsewhere["deliver_to_other_state"] = True
        self.planted.append({"what": "Transport records that cannot be true", "how": "A truck covering Surat to a far city in 7 hours; the same truck on two trips at once; a load above the truck's capacity; goods delivered in a different state than the buyer's",
                             "refs": [trip["bill_no"], twin["bill_no"], overload["bill_no"], elsewhere["bill_no"]], "checks": ["T11"]})
        # Price below contract without approval.
        contract_sales = [i for i in regular if i["customer"]["contract"] and i["date"].month in (1, 2, 3)][:3]
        for inv in contract_sales:
            inv["unit"] = (inv["unit"] * Decimal("0.88")).quantize(Decimal("0.01"))
            self._retax(inv)
        self.planted.append({"what": "Contract customer billed below the agreed price", "how": "3 invoices 12% under the price list; plus a discount scheme with no approval",
                             "refs": [i["bill_no"] for i in contract_sales] + [f"{self.prefix}-PROMO-02"], "checks": ["T14"]})
        # E-invoice problems.
        b2b = [i for i in regular if i["date"].month in (10, 11)]
        tampered, late = b2b[0], b2b[1]
        tampered["tamper_after_signing"] = True
        late["ack_days_late"] = 25
        missing = b2b[2:6]
        for inv in missing:
            inv["no_irn"] = True
        self.planted.append({"what": "E-invoice problems", "how": "One invoice changed after its QR code was signed; one registered 25 days after its date; 4 B2B invoices with no IRN",
                             "refs": [tampered["bill_no"], late["bill_no"]] + [i["bill_no"] for i in missing], "checks": ["T13"]})
        self.planted.append({"what": "Revenue entered by hand with no invoice", "how": "A Rs 6,50,000 'year-end sales adjustment' journal on 31 March",
                             "refs": [f"{self.prefix}-JV-ADJ-01"], "checks": ["T05"]})
        self.planted.append({"what": "Hidden relationship and a circular trading loop", "how": "Vardhan Distributors shares a director with Neelgiri; money and goods loop Neelgiri -> Vardhan -> Om Sai -> Neelgiri",
                             "refs": ["Vardhan Distributors", "Om Sai Trading Company"], "checks": ["T02"]})
        self.shell, self.partner = shell, partner

    @staticmethod
    def _retax(inv: dict) -> None:
        inv["taxable"] = (inv["unit"] * inv["qty"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if inv["igst"]:
            inv["igst"] = (inv["taxable"] * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            inv["cgst"] = inv["sgst"] = (inv["taxable"] * GST_RATE / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        inv["gross"] = inv["taxable"] + inv["cgst"] + inv["sgst"] + inv["igst"]

    # ----- files -----------------------------------------------------------------------------
    def write(self, split_threshold: Decimal, out: Path = OUT) -> dict[str, Any]:
        base = out / self.slug
        (base / "books").mkdir(parents=True, exist_ok=True)
        (base / "dataset").mkdir(parents=True, exist_ok=True)
        (base / "uploads" / "gstr1").mkdir(parents=True, exist_ok=True)
        customers = sorted({c["customer_id"]: c for c in self.customers.values()}.values(), key=lambda c: c["customer_id"])
        _csv(base / "books" / "customers.csv", ["customer_id", "name", "gstin", "city", "state_code"],
             [[c["customer_id"], c["name"], c["gstin"], c["city"], c["state"]] for c in customers])
        cn_by_invoice = {cn["invoice"]["invoice_id"]: cn for cn in self.credit_notes}
        sales = []
        for inv in self.invoices:
            row = [inv["invoice_id"], inv["bill_no"], inv["date"].isoformat(), inv["customer"]["customer_id"], money(inv["taxable"]),
                   money(inv["cgst"] + inv["sgst"] + inv["igst"]), money(inv["gross"])]
            cn = cn_by_invoice.get(inv["invoice_id"])
            row += [cn["id"], cn["date"].isoformat(), money(cn["amount"]), cn["reason"]] if cn else ["", "", "", ""]
            sales.append(row)
        _csv(base / "books" / "sales.csv", ["invoice_id", "bill_no", "invoice_date", "customer_id", "taxable_amount", "tax_amount", "gross_amount",
                                            "credit_note_id", "credit_date", "credit_amount", "credit_reason"], sales)
        self._dataset(base / "dataset", split_threshold)
        self._register(base / "uploads" / "sales_register.csv")
        for month in (1, 2, 3):
            self._gstr1(base / "uploads" / "gstr1" / f"GSTR1_{self.gstin}_{month:02d}2026.json", month)
        self._bank(base / "uploads" / "bank_statement.csv")
        return {"invoices": len(self.invoices), "credit_notes": len(self.credit_notes), "customers": len(customers)}

    def _dataset(self, d: Path, split_threshold: Decimal) -> None:
        rng = random.Random(self.slug + "-logistics")
        hub = self.city
        inv_rows, dsp, jrn, gst, routes, ver = [], [], [], [], [], []
        vehicle_state = "MH04" if self.state == "27" else "GJ05"
        trips: dict[str, dict] = {}
        for n, inv in enumerate(self.invoices, 1):
            c = inv["customer"]
            irn = "" if inv.get("no_irn") or not c["gstin"] else hashlib.sha256(f"{self.gstin}|{inv['bill_no']}".encode()).hexdigest()
            b2b = bool(c["gstin"])  # the detail files describe B2B sales; B2C sales live in the books only
            if b2b:
                    inv_rows.append([inv["invoice_id"], inv["bill_no"], inv["date"].isoformat(), c["customer_id"], c["name"], c["gstin"], self.gstin, "INR",
                                 money(inv["taxable"]), money(inv["cgst"]), money(inv["sgst"]), money(inv["igst"]), money(inv["gross"]), inv["qty"],
                                 inv["hsn"], irn, "not_verified", f"{self.slug}-books-{inv['invoice_id']}"])
            posting = inv["date"].isoformat()
            jid = f"{self.prefix}-JV-{n:04d}"
            if b2b:
                jrn.append([jid, posting, inv["invoice_id"], "Trade Receivables", money(inv["gross"]), "0", "invoice_posting", f"Sales invoice {inv['bill_no']}"])
                jrn.append([jid, posting, inv["invoice_id"], "Sales Revenue", "0", money(inv["taxable"]), "invoice_posting", f"Sales invoice {inv['bill_no']}"])
                for label, amount in (("Output CGST", inv["cgst"]), ("Output SGST", inv["sgst"]), ("Output IGST", inv["igst"])):
                    if amount:
                        jrn.append([jid, posting, inv["invoice_id"], label, "0", money(amount), "invoice_posting", f"Sales invoice {inv['bill_no']}"])
            if inv["date"] <= PERIOD_END and not inv.get("not_in_gstr1") and c["gstin"]:
                taxable = inv.get("gstr1_taxable", inv["taxable"])
                ratio = taxable / inv["taxable"]
                parts = [(x * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for x in (inv["igst"], inv["cgst"], inv["sgst"])]
                gst.append([inv["date"].strftime("%Y-%m"), self.gstin, inv["bill_no"], inv["date"].isoformat(), c["gstin"], money(taxable),
                            *map(money, parts), money(taxable + sum(parts)), "synthetic_return_row"])
            if b2b and not inv.get("no_dispatch"):
                vehicle = f"{vehicle_state}{chr(65 + n % 26)}{chr(65 + (n // 26) % 26)}{1000 + n % 9000:04d}"
                if inv.get("same_vehicle_as"):
                    vehicle = trips[inv["same_vehicle_as"]["invoice_id"]]["vehicle"] if inv["same_vehicle_as"]["invoice_id"] in trips else vehicle
                dest = c["city"]
                km = road_km(hub, dest)
                depart = datetime.combine(inv["date"], datetime.min.time()) + timedelta(hours=7)
                hours = inv.get("route_hours") or max(2, round(km / 40))
                arrive = depart + timedelta(hours=hours)
                capacity = max(inv["qty"] * 2, 6000)
                quantity_units = capacity + 900 if inv.get("over_capacity") else inv["qty"]
                consignee = gstin("19" if c["state"] != "19" else "07", random.Random(inv["invoice_id"])) if inv.get("deliver_to_other_state") else c["gstin"]
                to_pin = CITIES[dest][1]
                trips[inv["invoice_id"]] = {"vehicle": vehicle}
                eway = f"SYN-EWB-{self.prefix}-{n:05d}" if inv["gross"] > EWAY_LIMIT else ""
                dsp.append([f"{self.prefix}-D{n:04d}", inv["invoice_id"], inv["date"].isoformat(), f"LR-{self.prefix}-{n:05d}", money(inv["taxable"]), inv["qty"],
                            c["gstin"], vehicle, eway, f"POD-{self.prefix}-{n:05d}"])
                routes.append([inv["invoice_id"], hub, dest, km, capacity, quantity_units, "synthetic_transporter_log", vehicle,
                               depart.isoformat(), arrive.isoformat(), CITIES[hub][1], to_pin, consignee])
            if c["gstin"] and inv["date"] <= date(2026, 4, 15):
                if irn:
                    payload = {"irn": irn, "bill_no": inv["bill_no"], "buyer_gstin": c["gstin"], "seller_gstin": self.gstin,
                               "gross_cents": int(inv["gross"] * 100) + (500000 if inv.get("tamper_after_signing") else 0),
                               "hsn_code": inv["hsn"], "invoice_date": inv["date"].isoformat()}
                    ack = inv["date"] + timedelta(days=inv.get("ack_days_late", 0))
                    ver.append([inv["invoice_id"], "true", "true", "NOT_PERFORMED", "NOT_PERFORMED", "synthetic_demo_irp_signed",
                                p3_crypto.sign_envelope(payload), ack.isoformat()])
                else:
                    ver.append([inv["invoice_id"], "false", "false", "UNAVAILABLE", "UNAVAILABLE", "synthetic_missing_irn", "", ""])
        if self.hiding:
            jrn.append([f"{self.prefix}-JV-ADJ-01", "2026-03-31", "", "Suspense Account", "650000.00", "0", "manual_journal", "Year-end sales adjustment"])
            jrn.append([f"{self.prefix}-JV-ADJ-01", "2026-03-31", "", "Sales Revenue", "0", "650000.00", "manual_journal", "Year-end sales adjustment"])
        _csv(d / "invoices.csv", ["invoice_id", "bill_no", "invoice_date", "customer_id", "customer_name", "buyer_gstin", "seller_gstin", "currency",
                                  "taxable_amount", "cgst", "sgst", "igst", "gross_amount", "quantity", "hsn_code", "irn", "signature_status", "source_ref"], inv_rows)
        _csv(d / "dispatches.csv", ["dispatch_id", "invoice_id", "dispatch_date", "document_no", "taxable_value", "quantity", "gstin", "vehicle_no",
                                    "eway_bill_no", "proof_of_delivery"], dsp)
        _csv(d / "journal_entries.csv", ["journal_id", "posting_date", "invoice_id", "account", "debit", "credit", "source_type", "description"], jrn)
        _csv(d / "gstr1_rows.csv", ["return_period", "gstin", "invoice_no", "invoice_date", "buyer_gstin", "taxable_value", "igst", "cgst", "sgst",
                                    "gross_value", "source_status"], gst)
        _csv(d / "movement_routes.csv", ["invoice_id", "route_origin", "route_destination", "distance_km", "vehicle_capacity_units", "quantity_units",
                                         "event_time_source", "vehicle_no", "depart_ts", "arrive_ts", "from_pin", "to_pin", "consignee_gstin"], routes)
        _csv(d / "invoice_verification_status.csv", ["invoice_id", "irn_present", "qr_payload_present", "signature_check", "registration_timing_check",
                                                     "evidence_origin", "signed_qr_envelope", "irn_ack_date"], ver)
        # Prior-year monthly sales per customer (baseline for the year-end concentration check).
        hist = []
        monthly = defaultdict(lambda: defaultdict(lambda: [0, Decimal(0)]))
        for inv in self.invoices:
            if PERIOD_START <= inv["date"] <= PERIOD_END and not inv.get("no_dispatch") and inv["customer"]["gstin"]:
                bucket = monthly[inv["customer"]["customer_id"]][inv["date"].month]
                bucket[0] += 1
                bucket[1] += inv["gross"]
        for cid, months in sorted(monthly.items()):
            for m, (count, total) in sorted(months.items()):
                prior = date(2024 if m >= 4 else 2025, m, 1)
                hist.append([prior.strftime("%Y-%m"), cid, count, money(total * Decimal(str(0.85 + rng.random() * 0.2))), "synthetic_prior_period"])
        _csv(d / "historical_sales.csv", ["period", "customer_id", "invoice_count", "gross_sales", "source_type"], hist)
        _csv(d / "threshold_policies.csv", ["policy_id", "policy_version", "effective_from", "effective_to", "rule_type", "threshold_inr", "source", "notes"], [
            [f"{self.prefix}-POL-01", "v1", "2025-04-01", "", "high_value_transaction", "100000", "company_delegation_of_authority", "Sales above Rs 1,00,000 need a manager's approval (synthetic test-only policy)."],
            [f"{self.prefix}-POL-02", "v1", "2025-04-01", "", "split_transaction_window_total", money(split_threshold), "company_delegation_of_authority",
             f"Orders above Rs {split_threshold:,.0f} need director approval; splitting one order to avoid it is not allowed (synthetic test-only policy)."]])
        prices = [[f"{self.prefix}-PL-{k + 1:02d}", f"ITEM-{hsn}", cid, "2025-04-01", "", money(unit), "INR", "signed_rate_contract"]
                  for k, ((cid, hsn), unit) in enumerate(sorted(self.contract_price.items()))]
        _csv(d / "price_lists.csv", ["price_list_id", "item_code", "customer_id", "valid_from", "valid_to", "unit_price", "currency", "source_type"], prices)
        first_contract = next(c for c in self.customers.values() if c["contract"])
        promos = [[f"{self.prefix}-PROMO-01", first_contract["customer_id"], "ITEM-9505", "2025-10-01", "2025-11-15", "5", f"{self.prefix}-BOARD-2025-17", "approved_diwali_scheme"]]
        if self.hiding:
            promos.append([f"{self.prefix}-PROMO-02", first_contract["customer_id"], "ITEM-9405", "2026-01-01", "2026-03-31", "12", "", "scheme_without_approval"])
        _csv(d / "promotions.csv", ["promotion_id", "customer_id", "item_code", "valid_from", "valid_to", "discount_percent", "approval_ref", "source_type"], promos)
        edges = []
        if self.hiding:
            edges = [[f"{self.prefix}-REL-01", "customer", self.shell["customer_id"], "person", f"{self.prefix}-DIR-01", "common_director_candidate", "2025-01-01", "",
                      "mca_director_search_synthetic", "SYN-MCA-0091", "candidate_requires_review"],
                     [f"{self.prefix}-REL-02", "company", self.slug.upper(), "customer", self.shell["customer_id"], "sells_to_candidate", "2025-04-01", "",
                      "books_synthetic", "SYN-LEDGER-01", "candidate_requires_review"],
                     [f"{self.prefix}-REL-03", "customer", self.shell["customer_id"], "customer", self.partner["customer_id"], "pays_onward_candidate", "2026-03-01", "",
                      "bank_statement_synthetic", "SYN-BANK-01", "candidate_requires_review"],
                     [f"{self.prefix}-REL-04", "customer", self.partner["customer_id"], "company", self.slug.upper(), "pays_back_candidate", "2026-03-01", "",
                      "bank_statement_synthetic", "SYN-BANK-02", "candidate_requires_review"]]
        else:
            related = list(self.customers.values())[5]
            edges = [[f"{self.prefix}-REL-01", "customer", related["customer_id"], "person", f"{self.prefix}-DIR-02", "director_relative", "2024-04-01", "",
                      "disclosed_register", f"{self.prefix}-RPT-2025", "disclosed"]]
        _csv(d / "related_party_edges.csv", ["edge_id", "subject_type", "subject_id", "object_type", "object_id", "relationship_type", "valid_from", "valid_to",
                                             "source_type", "source_ref", "confidence"], edges)
        (d / "README.md").write_text(DATASET_README.format(name=self.name), encoding="utf-8")
        files = {}
        for f in sorted(d.glob("*.csv")):
            raw = f.read_bytes()
            files[f.name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "rows": max(0, raw.count(b"\n") - 1)}
        manifest = {"dataset_name": f"{self.name} - PRAMAAN sample company", "dataset_version": "1.0", "created_for": "PRAMAAN sample companies",
                    "data_classification": "synthetic-fictional-not-real-taxpayer-data",
                    "warning": "Fictional company. GSTINs have valid check digits but are not real registrations. E-invoice QR codes are signed with PRAMAAN's DEMO key, not a government key.",
                    "derived_from": {"name": "UCI Online Retail II (trading patterns only)", "url": "https://archive.ics.uci.edu/dataset/502/online+retail+ii", "licence": "CC BY 4.0"},
                    "public_schema_references": [], "files": files}
        (d / "source_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    def _register(self, path: Path) -> None:
        rows = []
        for inv in self.invoices:
            if inv.get("hide_from_register"):  # exported "as on 15 April 2026", so early April is included
                continue
            gross = inv.get("register_gross", inv["gross"])
            rows.append([inv["bill_no"], inv["date"].strftime("%d-%m-%Y"), inv["customer"]["name"], money(gross), inv["customer"]["gstin"],
                         money(inv["taxable"]), money(inv["cgst"]), money(inv["sgst"]), money(inv["igst"])])
        _csv(path, ["Bill No", "Date", "Customer", "Gross Amt", "GST No", "Taxable", "CGST", "SGST", "IGST"], rows)

    def _gstr1(self, path: Path, month: int) -> None:
        b2b, b2cl, b2cs, cdnr = defaultdict(list), [], defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0), Decimal(0)]), defaultdict(list)
        for inv in self.invoices:
            if inv["date"].year != 2026 or inv["date"].month != month or inv.get("not_in_gstr1"):
                continue
            c = inv["customer"]
            taxable = inv.get("gstr1_taxable", inv["taxable"])
            ratio = taxable / inv["taxable"]
            ig, cg, sg = ((x * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for x in (inv["igst"], inv["cgst"], inv["sgst"]))
            item = {"num": 1, "itm_det": {"rt": 18, "txval": float(taxable), "iamt": float(ig), "camt": float(cg), "samt": float(sg), "csamt": 0}}
            doc = {"inum": inv["bill_no"], "idt": inv["date"].strftime("%d-%m-%Y"), "val": float(taxable + ig + cg + sg), "pos": c["state"], "itms": [item]}
            if c["gstin"]:
                b2b[c["gstin"]].append({**doc, "rchrg": "N", "inv_typ": "R"})
            elif ig and inv["gross"] > Decimal("100000"):
                b2cl.append({"pos": c["state"], "inv": [doc]})
            else:
                agg = b2cs[(c["state"], "INTRA" if cg else "INTER")]
                for k, v in enumerate((taxable, ig, cg, sg)):
                    agg[k] += v
        for cn in self.credit_notes:
            inv = cn["invoice"]
            if cn["date"].year == 2026 and cn["date"].month == month and inv["customer"]["gstin"]:
                ratio = cn["amount"] / inv["gross"]
                parts = [(x * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for x in (inv["taxable"], inv["igst"], inv["cgst"], inv["sgst"])]
                cdnr[inv["customer"]["gstin"]].append({"ntty": "C", "nt_num": cn["id"], "nt_dt": cn["date"].strftime("%d-%m-%Y"), "val": float(cn["amount"]),
                                                       "itms": [{"num": 1, "itm_det": {"rt": 18, "txval": float(parts[0]), "iamt": float(parts[1]), "camt": float(parts[2]), "samt": float(parts[3]), "csamt": 0}}]})
        data = {"gstin": self.gstin, "fp": f"{month:02d}2026", "b2b": [{"ctin": k, "inv": v} for k, v in sorted(b2b.items())]}
        if b2cl:
            data["b2cl"] = b2cl
        if b2cs:
            data["b2cs"] = [{"sply_ty": t, "pos": s, "typ": "OE", "rt": 18, "txval": float(v[0]), "iamt": float(v[1]), "camt": float(v[2]), "samt": float(v[3]), "csamt": 0}
                            for (s, t), v in sorted(b2cs.items())]
        if cdnr:
            data["cdnr"] = [{"ctin": k, "nt": v} for k, v in sorted(cdnr.items())]
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def _bank(self, path: Path) -> None:
        events = []
        cn_amount = defaultdict(Decimal)
        for cn in self.credit_notes:
            cn_amount[cn["invoice"]["invoice_id"]] += cn["amount"]
        for inv in self.invoices:
            due = inv["date"] + timedelta(days=30 + int(inv["invoice_id"][-2:]) % 15)  # paid in 30-44 days
            amount = inv["gross"] - cn_amount[inv["invoice_id"]]
            if amount > 0 and due <= date(2026, 4, 30):
                events.append((due, f"NEFT CR {inv['customer']['name'].upper()} {inv['bill_no']}", Decimal(0), amount))
        if self.hiding:  # shell money comes in, goes straight out to the partner, and comes back
            events.append((date(2026, 3, 30), "RTGS CR VARDHAN DISTRIBUTORS ADVANCE", Decimal(0), Decimal("1500000.00")))
            events.append((date(2026, 3, 30), "RTGS DR OM SAI TRADING COMPANY", Decimal("1500000.00"), Decimal(0)))
            events.append((date(2026, 4, 3), "RTGS CR OM SAI TRADING COMPANY", Decimal(0), Decimal("1480000.00")))
        for m in range(4, 16):
            month, year = (m - 1) % 12 + 1, 2025 + (m - 1) // 12
            events.append((date(year, month, 5), "SALARY PAYOUT BATCH", Decimal("850000.00"), Decimal(0)))
            events.append((date(year, month, 20), "GST PAYMENT CHALLAN", Decimal("320000.00"), Decimal(0)))
        events.sort(key=lambda e: (e[0], e[1]))
        balance, rows = Decimal("2500000.00"), []
        for when, text, wd, dp in events:
            if when < PERIOD_START:
                continue
            balance += dp - wd
            rows.append([when.strftime("%d/%m/%Y"), text, money(wd) if wd else "", money(dp) if dp else "", money(balance)])
        _csv(path, ["Date", "Narration", "Withdrawal", "Deposit", "Balance"], rows)


DATASET_README = """# {name}: PRAMAAN sample company data

Fictional company built for trying PRAMAAN. Not real taxpayer data, not a filing, not evidence of compliance.
GSTINs have valid check digits but are not real registrations. E-invoice QR codes are signed with PRAMAAN's
labelled DEMO key, never a government key. Trading patterns are derived from UCI Online Retail II (CC BY 4.0).
See docs/sample-companies/README.md.
"""


def _csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def build(out: Path = OUT) -> dict[str, Any]:
    rows = read_extract()
    keys = sorted({r["customer_key"] for r in rows})
    honest = Company("honest", "Kesar Home Decor Pvt Ltd", "Bhiwandi", keys[0::2], "pramaan-sample-honest-v1", hiding=False)
    hiding = Company("hiding", "Neelgiri Lifestyle Pvt Ltd", "Surat", keys[1::2], "pramaan-sample-hiding-v1", hiding=True)
    for company in (honest, hiding):
        company.build_books(rows)
    hiding.plant()
    threshold = Decimal("1500000")
    summary = {"honest": honest.write(threshold, out), "hiding": hiding.write(threshold, out)}
    (out / "hiding" / "planted.json").write_text(json.dumps(hiding.planted, indent=1), encoding="utf-8")
    return summary


def hsn_item_codes() -> dict[str, str]:
    codes = {code for _, code in HSN_RULES} | {DEFAULT_HSN}
    return {code: f"ITEM-{code}" for code in sorted(codes)}


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
