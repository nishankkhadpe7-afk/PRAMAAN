"""A second synthetic population, independent of sales_register.csv.

Run against the trusted local instance with PRAMAAN_DATA set to its database.
Existing snapshots, credentials and uploads are preserved.
"""
import argparse
import base64
import csv
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import app as p1, security

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "sample_uploads" / "cedar_wholesale_q2"
START, END = "2026-07-01", "2026-09-30"


def fixtures():
    customers = [{"customer_id": f"CEDAR-CUSTOMER-{i}", "name": f"Cedar Retail {i} (synthetic)", "gstin": f"29ABCDE1234F{i}Z5"} for i in range(1, 5)]
    dates = ([date(2026, 7, day) for day in range(1, 11)]
             + [date(2026, 8, day) for day in range(1, 11)]
             + [date(2026, 9, day) for day in range(1, 13)]
             + [date(2026, 9, day) for day in range(27, 31)]
             + [date(2026, 10, day) for day in range(1, 5)])
    sales, rows = [], []
    for number, invoice_date in enumerate(dates, 1):
        customer = customers[(number - 1) % 4]
        net = Decimal(250000 if number == 1 else 4000 + number * 175)
        tax, gross = net * Decimal("0.18"), net * Decimal("1.18")
        sale = {"order_id": f"CEDAR-ORDER-{number:03}", "dispatch_id": f"CEDAR-DISPATCH-{number:03}",
                "invoice_id": f"CEDAR-INVOICE-{number:03}", "journal_id": f"CEDAR-JOURNAL-{number:03}",
                "customer_id": customer["customer_id"], "bill_no": f"CEDAR/Q2/{number:03}",
                "order_date": (invoice_date - timedelta(days=2)).isoformat(),
                "dispatch_date": (invoice_date - timedelta(days=1)).isoformat(), "invoice_date": invoice_date.isoformat(),
                "net_amount": f"{net:.2f}", "tax_amount": f"{tax:.2f}", "vehicle_no": "SYNTHETIC-VEHICLE"}
        if number in (1, 2):
            sale["evidence"] = [{"evidence_id": f"CEDAR-SUPPORT-{number:03}",
                                 "content_base64": base64.b64encode(b"SYNTHETIC shared document for duplicate-support review; not proof of delivery.").decode(),
                                 "content_type": "text/plain"}]
        if number == 5:
            sale["receipt"] = {"receipt_id": "CEDAR-RECEIPT-005", "amount": f"{gross:.2f}", "value_date": "2026-07-20", "bank_ref": "SYNTHETIC-RECEIPT-REFERENCE"}
        if number == 6:
            sale["credit_note"] = {"credit_note_id": "CEDAR-CREDIT-IN-PERIOD", "credit_date": "2026-07-28", "amount": "125.00", "reason": "Synthetic in-period credit for review"}
        if number == 36:
            sale["credit_note"] = {"credit_note_id": "CEDAR-CREDIT-POST-PERIOD", "credit_date": "2026-10-06", "amount": "250.00", "reason": "Synthetic subsequent credit for cutoff review"}
        sales.append(sale)
        rows.append({"Bill No": sale["bill_no"], "Date": sale["invoice_date"], "Customer": customer["name"], "Gross Amt": f"{gross:.2f}", "GST No": customer["gstin"]})
    changed = [dict(row) for index, row in enumerate(rows) if index != 8]
    changed[13]["Gross Amt"] = f"{Decimal(changed[13]['Gross Amt']) + 500:.2f}"
    changed.append({"Bill No": "CEDAR/Q2/UNMATCHED", "Date": "2026-09-15", "Customer": customers[0]["name"], "Gross Amt": "1500.00", "GST No": customers[0]["gstin"]})
    formatted = []
    for row in rows:
        day = date.fromisoformat(row["Date"])
        formatted.append({**row, "Date": f"{day.month}/{day.day}/{day.year}", "Gross Amt": f"{Decimal(row['Gross Amt']):,.2f}"})
    ledgers = {}
    for label, values in (("clean", rows), ("difference_checks", changed), ("excel_formatted", formatted)):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(values)
        ledgers[label] = stream.getvalue().encode("utf-8")
    disclosures = [{"customer_id": customers[0]["customer_id"], "related_party": True, "relationship_type": "Synthetic disclosed affiliate", "valid_from": "2026-04-01", "valid_to": "2027-03-31"}]
    return {"classification": "entirely synthetic; no independent verification", "customers": customers, "sales": sales, "disclosures": disclosures}, ledgers


def write_fixtures():
    population, ledgers = fixtures()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / "business_lifecycles.json").write_text(json.dumps(population, indent=2), encoding="utf-8")
    (FIXTURE_DIR / "related_party_disclosures.json").write_text(json.dumps(population["disclosures"], indent=2), encoding="utf-8")
    for variant, raw in ledgers.items():
        (FIXTURE_DIR / f"cedar_q2_ledger_{variant}.csv").write_bytes(raw)
    return population, ledgers


def load_and_test(url="http://127.0.0.1:8000"):
    target = urlsplit(url)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"} or target.username or target.password or target.query or target.fragment:
        raise ValueError("Synthetic demo loading is restricted to a local HTTP instance.")
    population, ledgers = write_fixtures()
    client_token = security.issue("cedar-synthetic-loader", "client_employee", ttl=900)
    auditor_token = security.issue("cedar-synthetic-auditor", "auditor", ttl=900)
    try:
        with httpx.Client(base_url=url, trust_env=False, timeout=30) as client:
            def call(method, path, body=None, auditor=False):
                response = client.request(method, path, json=body, headers={"Authorization": "Bearer " + (auditor_token if auditor else client_token)})
                response.raise_for_status()
                return response.json()
            existing = call("GET", "/ui/business")
            if any(not row["invoice_id"].startswith("CEDAR-INVOICE-") for row in existing["invoices"]):
                raise RuntimeError("Use an isolated instance: unrelated business invoices are already present.")
            known_customers = {row["customer_id"]: row for row in existing["customers"]}
            known_sales = {row["invoice_id"]: row for row in existing["invoices"]}
            for customer in population["customers"]:
                if customer["customer_id"] not in known_customers:
                    call("POST", "/p2/customers", customer)
                elif any(known_customers[customer["customer_id"]].get(key) != value for key, value in customer.items()):
                    raise RuntimeError("Existing Cedar customer differs from the synthetic fixture.")
            for sale in population["sales"]:
                if sale["invoice_id"] not in known_sales:
                    call("POST", "/p2/sales", sale)
                else:
                    saved = known_sales[sale["invoice_id"]]
                    expected_gross = int((Decimal(sale["net_amount"]) + Decimal(sale["tax_amount"])) * 100)
                    if saved["bill_no"] != sale["bill_no"] or saved["invoice_date"] != sale["invoice_date"] or saved["gross_cents"] != expected_gross:
                        raise RuntimeError("Existing Cedar invoice differs from the synthetic fixture.")
            disclosures = json.dumps(population["disclosures"]).encode()
            existing_registers = call("GET", "/ui/registers")
            if not any(row["sha256"] == hashlib.sha256(disclosures).hexdigest() for row in existing_registers["related_parties"]):
                call("POST", "/p2/related-parties", {"period": "Cedar Wholesale - Q2 FY 2026-27", "source_base64": base64.b64encode(disclosures).decode(), "records": population["disclosures"]})
            uploads, reconciliations = {}, {}
            for variant, raw in ledgers.items():
                existing_upload = next((row for row in existing_registers["registers"] if row["sha256"] == hashlib.sha256(raw).hexdigest()), None)
                uploads[variant] = existing_upload["upload_id"] if existing_upload else call("POST", "/p2/registers", {"period": "Cedar Q2 FY 2026-27 - " + variant.replace("_", " "), "source_base64": base64.b64encode(raw).decode()})["upload_id"]
                reconciliations[variant] = call("POST", f"/p2/registers/{uploads[variant]}/reconcile", auditor=True)
            results = []
            for variant in ledgers:
                expected = 3 if variant == "difference_checks" else 0
                actual = len(reconciliations[variant]["findings"])
                if actual != expected:
                    raise AssertionError(f"{variant}: expected {expected} reconciliation observations, received {actual}")
                title = "Cedar Wholesale - Q2 FY 2026-27 - " + variant.replace("_", " ").title()
                run = call("POST", "/p3/audit-runs", {"audit_name": title, "upload_id": uploads[variant], "period_start": START, "period_end": END, "sampling_seed": "cedar-wholesale-q2-2026-" + variant + "-v1"}, auditor=True)
                context = call("GET", f"/ui/runs/{run['run_id']}/context", auditor=True)
                assert context["audit_name"] == title and context["selected_upload_id"] == uploads[variant]
                assert len(context["invoices"]) == 40 and run["sample_items"]
                assert call("POST", f"/p3/audit-runs/{run['run_id']}/reproduce", auditor=True)["identical"]
                assert {"T01", "T07", "T09"} <= {finding["test_id"] for finding in run["findings"]}
                package = call("POST", f"/p5/runs/{run['run_id']}/packages", {"upload_id": uploads[variant], "client_name": "Cedar Wholesale (synthetic)"}, auditor=True)
                report = call("GET", "/p5/packages/" + package["package_id"], auditor=True)
                assert report["audit_name"] == title
                results.append({"audit_name": title, "run_id": run["run_id"], "selected_upload_id": uploads[variant], "invoices": 40,
                                "reconciliation_observations": actual, "automated_observations": len(context["findings"]),
                                "workpaper_items": len(run["sample_items"]), "sales_selected": run["coverage"]["sales_tod"]["selected"],
                                "cutoff_selected": run["coverage"]["cutoff_tod"]["before_selected"] + run["coverage"]["cutoff_tod"]["after_selected"],
                                "credit_notes_selected": len([item for item in run["sample_items"] if item["sheet"] == "credit_note_tod"]),
                                "reproduced_identically": True, "package_id": package["package_id"]})
            (FIXTURE_DIR / "test_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            return results
    finally:
        security.revoke(client_token)
        security.revoke(auditor_token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--fixtures-only", action="store_true")
    args = parser.parse_args()
    if args.fixtures_only:
        write_fixtures()
        print("Synthetic fixtures written to " + str(FIXTURE_DIR))
    else:
        print(json.dumps(load_and_test(args.url), indent=2))
