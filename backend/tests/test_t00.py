"""T00 v2 formatting, parse review, provenance and legacy package regressions."""
import base64
import csv
import io
import json
import sqlite3
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from Pramaan.backend import app as p1, p3, p5, security, t00


class T00NormalizationTests(unittest.TestCase):
    def test_equivalent_values_and_identifier_boundaries(self):
        for field, left, right in [("Date", "4/13/2026", "2026-04-13"), ("Date", "4/3/2026", "2026-04-03"),
                                    ("Gross Amt", "48,400", "48400.00"), ("Gross Amt", "48400.000", "48400.00"),
                                    ("Gross Amt", "1,23,456.70", "123456.7"), ("Customer", "  ACME\t  Ltd ", "ACME Ltd")]:
            with self.subTest(field=field, left=left):
                self.assertEqual(t00.compare(field, left, right)["comparison"], "EQUAL")
        for field, left, right in [("Bill No", "00026", "26"), ("GST No", "001ABC", "1ABC"),
                                    ("Bill No", " B-1", "B-1"), ("GST No", "abc", "ABC")]:
            self.assertEqual(t00.compare(field, left, right)["comparison"], "DIFFERENT")

    def test_missing_invalid_and_fractional_cent_never_equal(self):
        for field, value in [("Date", "13/4/2026"), ("Date", "2026-02-30"), ("Date", "04-13-2026"),
                             ("Date", "04/13/26"), ("Gross Amt", "48,40"), ("Gross Amt", "NaN"),
                             ("Gross Amt", "1e3"), ("Gross Amt", "100.001"), ("Gross Amt", "₹48400"),
                             ("Customer", ""), ("GST No", None), ("Bill No", " ")]:
            with self.subTest(field=field, value=value):
                result = t00.compare(field, value, value)
                self.assertEqual(result["comparison"], "PARSE_REVIEW")
                self.assertIsNone(result["normalized_difference"])


class T00IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / '.runtime' / ('t00-' + uuid.uuid4().hex)
        self.patches = [patch.object(p1, 'ROOT', self.root), patch.object(p1, 'DB_PATH', self.root/'p1.sqlite3'), patch.object(p1, 'VAULT', self.root/'vault')]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("t00-client", "client_employee"), "auditor": security.issue("t00-auditor", "auditor"), "human": security.issue("t00-reviewer", "auditor", human=True)}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        self.api('POST', '/p2/customers', 'client', {"customer_id":"C-00", "name":"Demo Customer", "gstin":"001DEMO-GST"})
        self.rows = []
        for n in range(1, 27):
            d = date(2026, 3, 19) + timedelta(days=n) if n < 26 else date(2026, 4, 13)
            bill = f'DEMO/26/{n:03}'
            self.api('POST', '/p2/sales', 'client', {"order_id":f'O{n}', "dispatch_id":f'D{n}', "invoice_id":f'I{n}', "journal_id":f'J{n}', "customer_id":"C-00", "bill_no":bill, "order_date":d.isoformat(), "dispatch_date":d.isoformat(), "invoice_date":d.isoformat(), "net_amount":"48400.00"})
            self.rows.append({"Bill No":bill, "Date":f'{d.month}/{d.day}/{d.year}', "Customer":"  Demo   Customer ", "Gross Amt":"48,400", "GST No":"001DEMO-GST"})

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def api(self, method, path, role='auditor', body=None):
        result = self.client.request(method, path, headers={'Authorization':'Bearer '+self.tokens[role]}, **({'json':body} if body is not None else {}))
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def upload(self):
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]), lineterminator='\r\n')
        writer.writeheader(); writer.writerows(self.rows)
        self.source = stream.getvalue().encode()
        return self.api('POST', '/p2/registers', 'client', {'period':'FY26','source_base64':base64.b64encode(self.source).decode()}).json()

    def run_audit(self):
        return self.api('POST', '/p3/audit-runs', body={'period_start':'2025-04-01','period_end':'2026-03-31','sampling_seed':'t00-version-regression-2026'}).json()['run_id']

    def test_only_edited_amount_differs_original_values_and_hashes_preserved(self):
        self.rows[-1]['Gross Amt'] = '58,400'
        upload = self.upload()
        result = self.api('POST', f"/p2/registers/{upload['upload_id']}/reconcile").json()
        self.assertEqual(len(result['findings']), 1)
        finding = result['findings'][0]
        self.assertEqual((finding['bill_no'], finding['category']), ('DEMO/26/026', 'FIELD_DIFF'))
        self.assertEqual(len(finding['field_differences']), 1)
        d = finding['field_differences'][0]
        self.assertEqual((d['field'], d['register_value'], d['system_value']), ('Gross Amt', '58,400', '48400.00'))
        self.assertEqual(d['normalized_difference'], {'cents':1000000, 'inr':'10000.00'})
        self.assertEqual(result['ruleset_hash'], p1.digest(p1.canonical(t00.RULE)))
        self.assertEqual((p1.VAULT/upload['sha256']).read_bytes(), self.source)
        self.assertEqual(upload['sha256'], p1.digest(self.source))
        repeat = self.api('POST', f"/p2/registers/{upload['upload_id']}/reconcile").json()
        self.assertEqual(result, repeat)
        run_id = self.run_audit()
        context = self.api('GET', f"/ui/runs/{run_id}/context?upload_id={upload['upload_id']}").json()
        enriched = next(f for f in context['findings'] if f['test_id']=='T00')
        self.assertEqual(enriched['ruleset_version'], 'p2-t00-v2')
        self.assertEqual(context['reconciliation_rule'], t00.RULE)
        self.assertTrue(set(enriched['evidence_ids']) <= context['evidence_index'].keys())
        self.assertEqual(enriched['field_differences'], finding['field_differences'])

    def test_genuine_date_customer_gstin_and_amount_differences(self):
        self.rows[0].update({'Date':'2026-03-21','Customer':'Different customer','GST No':'1DEMO-GST','Gross Amt':'48,401'})
        upload = self.upload()
        findings = self.api('POST', f"/p2/registers/{upload['upload_id']}/reconcile").json()['findings']
        self.assertEqual(len(findings), 1)
        differences = {d['field']:d for d in findings[0]['field_differences']}
        self.assertEqual(set(differences), {'Date','Customer','GST No','Gross Amt'})
        self.assertEqual(differences['Date']['normalized_difference'], {'days':1})
        self.assertEqual(differences['Gross Amt']['normalized_difference']['cents'], 100)

    def test_missing_and_invalid_fields_require_review_and_roles_stay_enforced(self):
        self.rows[0].update({'Date':'2026-02-30', 'Gross Amt':'48,40', 'Customer':'', 'GST No':''})
        upload = self.upload()
        result = self.api('POST', f"/p2/registers/{upload['upload_id']}/reconcile").json()
        self.assertEqual([f['category'] for f in result['findings']], ['PARSE_REVIEW'])
        self.assertEqual(len(result['findings'][0]['field_differences']), 4)
        denial = self.client.post(f"/p2/registers/{upload['upload_id']}/reconcile", headers={'Authorization':'Bearer '+self.tokens['client']})
        self.assertEqual(denial.status_code, 403)
        forbidden = self.client.post('/p2/customers', headers={'Authorization':'Bearer '+self.tokens['auditor']}, json={'customer_id':'FORBIDDEN','name':'denied'})
        self.assertEqual(forbidden.status_code, 403)

    def test_v1_snapshots_reviews_and_all_frozen_exports_survive_v2_reconciliation(self):
        self.rows[-1]['Gross Amt'] = '58,400'
        upload = self.upload(); uid = upload['upload_id']
        legacy = {'finding_id':f'T00-{uid}-26-FIELD_DIFF','test_id':'T00','category':'FIELD_DIFF','row_no':26,'bill_no':'DEMO/26/026','field_differences':[{'field':'Date','register_value':'4/13/2026','system_value':'2026-04-13'}], 'reason':'Legacy text difference.'}
        with sqlite3.connect(p1.DB_PATH) as db:
            db.execute('INSERT INTO p2_reconciliations VALUES(?,?,?)', ('LEGACY-T00',uid,p1.canonical([legacy]).decode()))
        old_run = self.run_audit()
        review = self.api('POST', f"/p5/runs/{old_run}/findings/{legacy['finding_id']}/review", 'human', {'outcome':'DATA_ERROR','reason':'Legacy source data reviewed','expected_revision':0}).json()
        package = self.api('POST', f'/p5/runs/{old_run}/packages', body={'upload_id':uid}).json()['package_id']
        urls = [f'/p5/packages/{package}/{name}' for name in ('workpaper.xlsx','memo.pdf','defensibility.zip')]
        before = [self.api('GET', url).content for url in urls]
        old_context = self.api('GET', f'/ui/runs/{old_run}/context?upload_id={uid}').json()
        self.api('POST', f'/p2/registers/{uid}/reconcile')
        new_run = self.run_audit()
        context = self.api('GET', f'/ui/runs/{new_run}/context?upload_id={uid}').json()
        findings = [f for f in context['findings'] if f['test_id']=='T00']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['ruleset_version'], 'p2-t00-v2')
        self.assertNotEqual(findings[0]['finding_id'], legacy['finding_id'])
        self.assertIsNone(findings[0]['human_decision'])
        self.assertEqual(self.api('GET', f'/ui/runs/{old_run}/context?upload_id={uid}').json(), old_context)
        self.assertEqual([self.api('GET', url).content for url in urls], before)
        queue = self.api('GET', f'/p5/runs/{old_run}/reviews').json()['items']
        self.assertEqual(next(f for f in queue if f['finding_id'] == legacy['finding_id'])['human_decision'], review)
        new_package = self.api('POST', f'/p5/runs/{new_run}/packages', body={'upload_id':uid}).json()['package_id']
        report = self.api('GET', f'/p5/packages/{new_package}').json()
        self.assertEqual(report['reconciliation_rule']['version'], 'p2-t00-v2')
        self.assertEqual(report['receipt']['reconciliation_rules'][0]['hash'], p1.digest(p1.canonical(t00.RULE)))
