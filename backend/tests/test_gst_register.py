"""End-to-end reconciliation of a SYNTHETIC Indian GST sales register (fixtures_gst_register). No real taxpayer data."""
import base64
import collections
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, security, fixtures_gst_register as g
from Pramaan.backend.document_import import gstin_check


class SyntheticGstRegisterTests(unittest.TestCase):
    def test_every_planted_problem_is_found_and_nothing_else(self):
        root = Path(tempfile.mkdtemp(prefix="pramaan-gst-"))
        with patch.object(p1, "ROOT", root), patch.object(p1, "DB_PATH", root / "p1.sqlite3"), patch.object(p1, "VAULT", root / "vault"), patch.dict("os.environ", {"PRAMAAN_DATA": str(root)}):
            client = TestClient(p1.app)
            tokens = {"client": security.issue("emp", "client_employee", ttl=3600), "auditor": security.issue("aud", "auditor", ttl=3600)}
            call = lambda m, path, role, **kw: client.request(m, path, headers={"Authorization": "Bearer " + tokens[role]}, **kw)
            customers, sales, register, planted = g.build(120)
            self.assertTrue(all(gstin_check(c["gstin"]) is None for c in customers if c["gstin"]))
            for c in customers:
                self.assertEqual(call("POST", "/p2/customers", "client", json={k: c[k] for k in ("customer_id", "name", "gstin") if c[k]}).status_code, 200)
            for s in sales:
                self.assertEqual(call("POST", "/p2/sales", "client", json=s).status_code, 200)
            up = call("POST", "/p2/registers", "client", json={"period": "FY26", "source_base64": base64.b64encode(g.register_csv(register)).decode()}).json()
            result = call("POST", f"/p2/registers/{up['upload_id']}/reconcile?company_state=27", "auditor").json()
        self.assertEqual((result["date_order"]["used"], result["date_order"]["source"]), ("DMY", "detected"))
        self.assertGreater(result["gstin_not_applicable_rows"], 0)  # B2C rows: blank GSTIN on both sides
        got = collections.defaultdict(set)
        for f in result["findings"]:
            got[f["category"]].add((f["bill_no"], tuple(d["field"] for d in f["field_differences"])))
        self.assertEqual(got["FIELD_DIFF"], {(planted["AMOUNT"], ("Gross Amt",)), (planted["DATE"], ("Date",)), (planted["GSTIN"], ("GST No",)), (planted["TAX_SPLIT"], ("Tax split",)), (planted["CREDIT_DIFF"], ("Gross Amt",))})
        self.assertEqual(got["SYSTEM_ONLY"], {(planted["SYS_ONLY"], ())})
        self.assertEqual(got["DUPLICATE_ROW"], {(planted["DUP"], ())})
        self.assertEqual(got["REGISTER_ONLY"], {(planted["REG_ONLY"], ()), (planted["CREDIT_UNKNOWN"], ())})
        self.assertEqual(set(got) - {"FIELD_DIFF", "SYSTEM_ONLY", "DUPLICATE_ROW", "REGISTER_ONLY"}, set())


if __name__ == "__main__":
    unittest.main()
