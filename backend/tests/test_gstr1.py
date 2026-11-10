"""GSTR-1 JSON (as downloaded from the GST portal) read as a sales register. SYNTHETIC data only."""
import base64
import collections
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, security, fixtures_gst_register as g
from Pramaan.backend.document_import import DocumentReadError
from Pramaan.backend.gstr1 import parse_gstr1

BUYER = "27AABKP1007K1Z7"  # synthetic GSTIN from fixtures_gst_register (valid check digit)


def _item(taxable, igst=0.0, cgst=0.0, sgst=0.0):
    return {"num": 1, "itm_det": {"rt": 18, "txval": taxable, "iamt": igst, "camt": cgst, "samt": sgst, "csamt": 0}}


def _small_return():
    return {"gstin": BUYER, "fp": "042025",
            "b2b": [{"ctin": BUYER, "inv": [
                {"inum": "S-1", "idt": "05-04-2025", "val": 1180, "pos": "27", "rchrg": "N", "inv_typ": "R", "itms": [_item(1000, cgst=90, sgst=90)]},
                {"inum": "S-2", "idt": "31-05-2025", "val": 2360, "itms": [_item(2000, igst=360)]},
                {"inum": "", "idt": "06-04-2025", "val": 100, "itms": []},
                {"inum": "S-4", "idt": "not a date", "val": 100, "itms": []},
                {"inum": "S-5", "idt": "07-04-2025", "val": 999, "itms": [_item(1000, igst=180)]}]}],
            "b2cl": [{"pos": "29", "inv": [{"inum": "S-6", "idt": "08-04-2025", "val": 295000, "itms": [_item(250000, igst=45000)]}]}],
            "exp": [{"exp_typ": "WOPAY", "inv": [{"inum": "E-1", "idt": "09-04-2025", "val": 50000, "itms": [{"txval": 50000, "rt": 0, "iamt": 0}]}]}],
            "cdnr": [{"ctin": BUYER, "nt": [{"ntty": "C", "nt_num": "CN-1", "nt_dt": "10-04-2025", "val": 590, "itms": [_item(500, cgst=45, sgst=45)]},
                                            {"ntty": "D", "nt_num": "DN-1", "nt_dt": "11-04-2025", "val": 118, "itms": [_item(100, igst=18)]}]}],
            "b2cs": [{"sply_ty": "INTRA", "pos": "27", "typ": "OE", "rt": 18, "txval": 10000, "camt": 900, "samt": 900}],
            "b2ba": [{"ctin": BUYER, "inv": []}],
            "hsn": {"data": []}}


class Gstr1ReaderTests(unittest.TestCase):
    def setUp(self):
        self.read = parse_gstr1(json.dumps(_small_return()).encode())

    def test_invoice_sections_become_rows_with_signs_and_tax_split(self):
        rows = {r["Bill No"]: r for r in self.read["rows"]}
        self.assertEqual(set(rows), {"S-1", "S-2", "S-5", "S-6", "E-1", "CN-1", "DN-1"})
        self.assertEqual(rows["S-1"], {"Bill No": "S-1", "Date": "2025-04-05", "Customer": "", "Gross Amt": "1180.00", "GST No": BUYER,
                                       "Return": "GSTR-1", "Return Period": "2025-04", "Taxable": "1000.00", "CGST": "90.00", "SGST": "90.00"})
        self.assertEqual((rows["CN-1"]["Gross Amt"], rows["CN-1"]["CGST"]), ("-590.00", "-45.00"))  # credit note is negative
        self.assertEqual(rows["DN-1"]["Gross Amt"], "118.00")  # debit note adds to sales
        self.assertEqual((rows["S-6"]["GST No"], rows["E-1"]["GST No"]), ("", ""))  # unregistered buyers carry no GSTIN

    def test_problems_are_rejected_or_warned_never_guessed(self):
        self.assertEqual(sorted(r["reason"][:20] for r in self.read["rejected"]), ["document number miss", "unreadable date 'not"])
        reasons = " | ".join(w["reason"] for w in self.read["warnings"])
        self.assertIn("does not match the document value (999.00)", reasons)  # S-5: 1000 + 180 is not 999
        self.assertIn("outside the return period 042025", reasons)  # S-2 is dated in May
        self.assertEqual(self.read["vouchers_seen"], 9)

    def test_b2cs_totals_and_unread_sections_are_reported(self):
        skipped = " | ".join(s["reason"] for s in self.read["skipped"])
        self.assertIn("taxable 10000.00, tax 1800.00", skipped)
        self.assertIn("amended B2B invoices are not read yet", skipped)
        self.assertEqual(self.read["summary"]["return_period"], "042025")
        self.assertIn("not fetched from or verified with the GST portal", self.read["summary"]["note"])

    def test_bad_files_are_refused(self):
        for bad in (b"not json", b"[]", json.dumps({"gstin": BUYER}).encode(), json.dumps({"b2b": []}).encode()):
            with self.assertRaises(DocumentReadError):
                parse_gstr1(bad)
        wrapped = parse_gstr1(json.dumps({"data": _small_return()}).encode())  # some tools wrap the return in "data"
        self.assertEqual(len(wrapped["rows"]), len(self.read["rows"]))


def _return_from_books(customers, sales, drop, change, extra):
    """What a company would have filed: every books invoice, with planted differences."""
    gstin = {c["customer_id"]: c["gstin"] for c in customers}
    b2b, b2cl, cdnr = collections.defaultdict(list), [], collections.defaultdict(list)
    for s in sales:
        if s["bill_no"] == drop:
            continue
        net, tax = Decimal(s["net_amount"]), Decimal(s["tax_amount"])
        value = net + tax + (Decimal(100) if s["bill_no"] == change else 0)
        d = s["invoice_date"]
        inv = {"inum": s["bill_no"], "idt": f"{d[8:]}-{d[5:7]}-{d[:4]}", "val": float(value), "itms": [_item(float(net), igst=float(tax))]}
        if gstin[s["customer_id"]]:
            b2b[gstin[s["customer_id"]]].append(inv)
        else:
            b2cl.append(inv)
        if s.get("credit_note"):
            cn = s["credit_note"]
            cdnr[gstin[s["customer_id"]] or BUYER].append({"ntty": "C", "nt_num": cn["credit_note_id"], "nt_dt": f"{cn['credit_date'][8:]}-{cn['credit_date'][5:7]}-{cn['credit_date'][:4]}",
                                                         "val": float(cn["amount"]), "itms": []})
    b2cl.append({"inum": extra, "idt": "01-05-2025", "val": 1180.0, "itms": [_item(1000, igst=180)]})
    return {"gstin": BUYER, "b2b": [{"ctin": k, "inv": v} for k, v in b2b.items()], "b2cl": [{"pos": "27", "inv": b2cl}],
            "cdnr": [{"ctin": k, "nt": v} for k, v in cdnr.items()]}


class Gstr1ReconciliationTests(unittest.TestCase):
    def test_return_reconciles_against_the_books_and_finds_each_planted_difference(self):
        root = Path(tempfile.mkdtemp(prefix="pramaan-gstr1-"))
        with patch.object(p1, "ROOT", root), patch.object(p1, "DB_PATH", root / "p1.sqlite3"), patch.object(p1, "VAULT", root / "vault"), patch.dict("os.environ", {"PRAMAAN_DATA": str(root)}):
            client = TestClient(p1.app)
            tokens = {"client": security.issue("emp", "client_employee", ttl=3600), "auditor": security.issue("aud", "auditor", ttl=3600)}
            call = lambda m, path, role, **kw: client.request(m, path, headers={"Authorization": "Bearer " + tokens[role]}, **kw)
            customers, sales, _, _ = g.build(120)
            for c in customers:
                self.assertEqual(call("POST", "/p2/customers", "client", json={k: c[k] for k in ("customer_id", "name", "gstin") if c[k]}).status_code, 200)
            for s in sales:
                self.assertEqual(call("POST", "/p2/sales", "client", json=s).status_code, 200)
            plain = [s["bill_no"] for s in sales if not s.get("credit_note")]
            drop, change, extra = plain[3], plain[7], "MH/25-26/9999"
            filed = _return_from_books(customers, sales, drop, change, extra)
            up = call("POST", "/p2/registers", "client", json={"period": "FY26", "source_format": "gstr1_json", "source_base64": base64.b64encode(json.dumps(filed).encode()).decode()})
            self.assertEqual(up.status_code, 200, up.text)
            self.assertEqual(up.json()["parser"], "gstr1-json-v1")
            result = call("POST", f"/p2/registers/{up.json()['upload_id']}/reconcile", "auditor").json()
        got = collections.defaultdict(set)
        for f in result["findings"]:
            got[f["category"]].add((f["bill_no"], tuple(d["field"] for d in f["field_differences"])))
        self.assertEqual(got["FIELD_DIFF"], {(change, ("Gross Amt",))})
        self.assertIn((extra, ()), got["REGISTER_ONLY"])
        self.assertIn(drop, {b for b, _ in got["SYSTEM_ONLY"]})
        # No customer-name reviews: GSTR-1 identifies buyers by GSTIN only.
        self.assertFalse([f for f in result["findings"] if any(d["field"] == "Customer" for d in f["field_differences"])])
        self.assertFalse(got["PARSE_REVIEW"])


if __name__ == "__main__":
    unittest.main()
