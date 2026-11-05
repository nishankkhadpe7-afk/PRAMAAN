"""TEST FIXTURE ONLY: large synthetic data set for UI density checks.

Builds `.demo/<name>` through the real API (no direct DB writes): the standard demo reset, then
140 extra synthetic sales, a register with deliberate differences, related-party disclosures,
client evidence uploads for 60+ requested documents and a fresh audit run. Never touches
`backend/data` or `.demo/runtime`. Usage:

    PYTHONPATH=<repo>/launcher python web/e2e/ui-audit/seed_large.py --name uiaudit
"""
import argparse
import base64
import csv
import io
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, demo


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="uiaudit")
    args = parser.parse_args()
    if args.name in {"runtime", "browser"}:
        sys.exit("refusing to overwrite a shared demo instance")
    demo.reset(args.name)
    root = demo.data_path(args.name)
    demo.configure(root)
    creds = json.loads((root / "session-credentials.json").read_text())
    state = json.loads((root / "demo-state.json").read_text())
    client = TestClient(p1.app)
    C = {"Authorization": "Bearer " + creds["client"]}
    A = {"Authorization": "Bearer " + creds["auditor"]}

    def ok(response):
        if response.status_code >= 300:
            raise SystemExit(f"{response.request.method} {response.request.url.path}: {response.status_code} {response.text[:200]}")
        return response.json()

    customers = [("FX-CUST-%02d" % n, f"Fixture Trading Co {n:02d}", f"27AAAAF{n:04d}A1Z5") for n in range(1, 9)]
    for cid, name, gstin in customers:
        ok(client.post("/p2/customers", headers=C, json={"customer_id": cid, "name": name, "gstin": gstin}))
    rows = []
    for n in range(140):
        month = 1 + n % 12
        year = 2025 if month >= 4 else 2026
        day = 1 + (n * 7) % 27
        when = f"{year}-{month:02d}-{day:02d}"
        net = 10000 + (n * 3713) % 190000
        cid, name, gstin = customers[n % len(customers)]
        sale = {"order_id": f"FX-SO-{n:03d}", "dispatch_id": f"FX-DSP-{n:03d}", "invoice_id": f"FX-INV-{n:03d}",
                "journal_id": f"FX-JRN-{n:03d}", "customer_id": cid, "order_date": when, "dispatch_date": when,
                "invoice_date": when, "bill_no": f"FX/{year % 100}/{n:03d}", "net_amount": f"{net}.00", "tax_amount": f"{net * 18 // 100}.00"}
        if n % 9 == 0:
            sale["credit_note"] = {"credit_note_id": f"FX-CN-{n:03d}", "credit_date": "2026-04-10", "amount": "500.00", "reason": "Fixture post-period return"}
        ok(client.post("/p2/sales", headers=C, json=sale))
        gross = net + net * 18 // 100
        if n % 7 != 0:  # every 7th sale missing from the register
            rows.append([sale["bill_no"], when, name, f"{gross + (100 if n % 5 == 0 else 0)}.00", gstin])
    for extra in range(12):  # register-only rows
        rows.append([f"FX/REG/{extra}", "2026-02-15", "Unknown buyer", "9999.00", ""])
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["Bill No", "Date", "Customer", "Gross Amt", "GST No"])
    writer.writerows(rows)
    upload = ok(client.post("/p2/registers", headers=C, json={"period": "FY26 fixture", "source_base64": b64(buffer.getvalue().encode())}))
    ok(client.post(f"/p2/registers/{upload['upload_id']}/reconcile", headers=A))
    disclosure = b"customer_id,related_party,relationship_type,valid_from\r\nFX-CUST-03,yes,Fixture common director,2025-04-01\r\nFX-CUST-06,yes,Fixture affiliate,2025-10-01\r\n"
    ok(client.post("/p2/related-parties", headers=C, json={"period": "FY26 fixture", "source_base64": b64(disclosure)}))
    run = ok(client.post("/p3/audit-runs", headers=A, json={"period_start": "2025-04-01", "period_end": "2026-03-31", "upload_id": upload["upload_id"], "audit_name": "Fixture density audit - FY 2025-26"}))
    requests = ok(client.get(f"/p3/audit-runs/{run['run_id']}/evidence-requests", headers=C))["requests"]
    uploaded = 0
    for request in requests:
        for doc in request["required_docs"][:2]:
            if uploaded >= 70:
                break
            body = {"evidence_id": f"FX-EV-{uploaded:03d}", "document_type": doc, "content_type": "text/plain",
                    "content_base64": b64(f"Fixture {doc} for {request['sample_ref']}".encode()), "controller": "client", "acquisition_channel": "fixture upload"}
            response = client.post(f"/p3/evidence-requests/{request['request_id']}/evidence", headers=C, json=body)
            if response.status_code == 200:
                uploaded += 1
    final = ok(client.post(f"/p3/audit-runs/{run['run_id']}/rerun", headers=A))
    context = ok(client.get(f"/ui/runs/{final['run_id']}/context", headers=A))
    state.update(fixture_run_id=final["run_id"], fixture_upload_id=upload["upload_id"], fixture_findings=len(context["findings"]), fixture_evidence=uploaded)
    (root / "demo-state.json").write_text(json.dumps(state, indent=2))
    print(json.dumps({"run_id": final["run_id"], "findings": len(context["findings"]), "evidence_uploaded": uploaded, "samples": len(final["sample_items"])}))


if __name__ == "__main__":
    main()
