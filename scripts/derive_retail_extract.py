"""Derive the small trading-pattern extract used by the sample companies.

Source: UCI Online Retail II (Chen, D., 2019), https://archive.ics.uci.edu/dataset/502/online+retail+ii,
licensed CC BY 4.0 (also mirrored on Kaggle). Run once with the downloaded CSV:

    python scripts/derive_retail_extract.py online_retail_II.csv docs/sample-companies/source/online_retail_ii_extract.csv

Kept: one financial year (Apr 2010 - Mar 2011), the 50 busiest repeat customers, and for every invoice
its highest-value product line (a bulk B2B line). Cancellations (invoice numbers starting "C") are
kept as returns. Customer IDs are replaced by sequence keys; nothing identifies a person.
"""
import csv
import sys
from collections import Counter, defaultdict
from decimal import Decimal

src, out = sys.argv[1], sys.argv[2]
lines = defaultdict(list)
with open(src, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        when = r["InvoiceDate"][:10]
        if not ("2010-04-01" <= when <= "2011-03-31") or not r["Customer ID"]:
            continue
        try:
            qty, price = int(r["Quantity"]), Decimal(r["Price"])
        except Exception:
            continue
        if price <= 0 or qty == 0 or not r["StockCode"][:1].isdigit():
            continue
        lines[r["Invoice"]].append((when, r["Customer ID"], r["StockCode"], r["Description"].strip(), qty, price))
sales = {k: v for k, v in lines.items() if not k.startswith("C")}
busy = Counter(v[0][1] for v in sales.values())
keep = [c for c, n in busy.most_common() if n >= 6][:50]
key = {c: f"K{i:03d}" for i, c in enumerate(keep, 1)}
rows = []
for inv, v in lines.items():
    if v[0][1] not in key:
        continue
    top = max(v, key=lambda x: abs(x[4]) * x[5])
    rows.append({"date": top[0], "customer_key": key[top[1]], "kind": "return" if inv.startswith("C") else "sale",
                 "stock_code": top[2], "description": top[3], "quantity": abs(top[4]), "unit_price_gbp": str(top[5])})
rows.sort(key=lambda r: (r["date"], r["customer_key"], r["stock_code"]))
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), "rows;", sum(r["kind"] == "return" for r in rows), "returns;", len(key), "customers")
