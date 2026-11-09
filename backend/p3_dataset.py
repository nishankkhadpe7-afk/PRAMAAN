"""Importer for the checked-in, synthetic P3 source-data pack."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import app as p1

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TABLES = {
    "invoices.csv": {"invoice_id", "bill_no", "invoice_date", "customer_id", "customer_name", "buyer_gstin", "seller_gstin", "currency", "taxable_amount", "cgst", "sgst", "igst", "gross_amount", "quantity", "hsn_code", "irn", "signature_status", "source_ref"},
    "dispatches.csv": {"dispatch_id", "invoice_id", "dispatch_date", "document_no", "taxable_value", "quantity", "gstin", "vehicle_no", "eway_bill_no", "proof_of_delivery"},
    "journal_entries.csv": {"journal_id", "posting_date", "invoice_id", "account", "debit", "credit", "source_type", "description"},
    "related_party_edges.csv": {"edge_id", "subject_type", "subject_id", "object_type", "object_id", "relationship_type", "valid_from", "valid_to", "source_type", "source_ref", "confidence"},
    "historical_sales.csv": {"period", "customer_id", "invoice_count", "gross_sales", "source_type"},
    "threshold_policies.csv": {"policy_id", "policy_version", "effective_from", "effective_to", "rule_type", "threshold_inr", "source", "notes"},
    "gstr1_rows.csv": {"return_period", "gstin", "invoice_no", "invoice_date", "buyer_gstin", "taxable_value", "igst", "cgst", "sgst", "gross_value", "source_status"},
    "price_lists.csv": {"price_list_id", "item_code", "customer_id", "valid_from", "valid_to", "unit_price", "currency", "source_type"},
    "promotions.csv": {"promotion_id", "customer_id", "item_code", "valid_from", "valid_to", "discount_percent", "approval_ref", "source_type"},
    "movement_routes.csv": {"invoice_id", "route_origin", "route_destination", "distance_km", "vehicle_capacity_units", "quantity_units", "event_time_source", "vehicle_no", "depart_ts", "arrive_ts", "from_pin", "to_pin", "consignee_gstin"},
    "invoice_verification_status.csv": {"invoice_id", "irn_present", "qr_payload_present", "signature_check", "registration_timing_check", "evidence_origin", "signed_qr_envelope", "irn_ack_date"},
}
DATE_COLUMNS = {
    "invoices.csv": ("invoice_date",), "dispatches.csv": ("dispatch_date",),
    "journal_entries.csv": ("posting_date",), "related_party_edges.csv": ("valid_from", "valid_to"),
    "threshold_policies.csv": ("effective_from", "effective_to"), "gstr1_rows.csv": ("invoice_date",),
    "price_lists.csv": ("valid_from", "valid_to"), "promotions.csv": ("valid_from", "valid_to"),
    "invoice_verification_status.csv": ("irn_ack_date",),
}
# ISO-8601 datetime columns (date-only validator would reject the time component).
DATETIME_COLUMNS = {"movement_routes.csv": ("depart_ts", "arrive_ts")}
DECIMAL_COLUMNS = {
    "invoices.csv": ("taxable_amount", "cgst", "sgst", "igst", "gross_amount", "quantity"),
    "dispatches.csv": ("taxable_value", "quantity"),
    "journal_entries.csv": ("debit", "credit"),
    "historical_sales.csv": ("gross_sales",),
    "threshold_policies.csv": ("threshold_inr",),
    "gstr1_rows.csv": ("taxable_value", "igst", "cgst", "sgst", "gross_value"),
    "price_lists.csv": ("unit_price",), "promotions.csv": ("discount_percent",),
    "movement_routes.csv": ("distance_km", "vehicle_capacity_units", "quantity_units"),
}
BOOL_COLUMNS = {"invoice_verification_status.csv": ("irn_present", "qr_payload_present")}
MONEY_COLUMNS = {
    "invoices.csv": {"taxable_amount", "cgst", "sgst", "igst", "gross_amount"},
    "dispatches.csv": {"taxable_value"}, "historical_sales.csv": {"gross_sales"},
    "threshold_policies.csv": {"threshold_inr"}, "gstr1_rows.csv": {"taxable_value", "igst", "cgst", "sgst", "gross_value"},
    "price_lists.csv": {"unit_price"},
}
OPTIONAL_EMPTY = {
    "invoices.csv": {"irn"}, "dispatches.csv": {"eway_bill_no", "proof_of_delivery"},
    "journal_entries.csv": {"invoice_id"}, "related_party_edges.csv": {"valid_to"},
    "threshold_policies.csv": {"effective_to"}, "price_lists.csv": {"valid_to"},
    "promotions.csv": {"valid_to", "approval_ref"},
    "invoice_verification_status.csv": {"signed_qr_envelope", "irn_ack_date"},
}


def init_dataset(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE IF NOT EXISTS p3_dataset_imports(dataset_id TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL, dataset_version TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS p3_dataset_files(dataset_id TEXT NOT NULL REFERENCES p3_dataset_imports(dataset_id), file_name TEXT NOT NULL, sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL, row_count INTEGER NOT NULL, PRIMARY KEY(dataset_id,file_name));
      CREATE TABLE IF NOT EXISTS p3_dataset_rows(dataset_id TEXT NOT NULL, file_name TEXT NOT NULL, row_no INTEGER NOT NULL, record_json TEXT NOT NULL, PRIMARY KEY(dataset_id,file_name,row_no), FOREIGN KEY(dataset_id,file_name) REFERENCES p3_dataset_files(dataset_id,file_name));
    """)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{label}: invalid decimal {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{label}: decimal must be finite")
    return result


def _date(value: str, label: str, nullable: bool = False) -> None:
    if (value is None or value == "") and nullable:
        return
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: expected ISO YYYY-MM-DD") from exc


def _datetime(value: str, label: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: expected ISO-8601 datetime") from exc


def _normalize(file_name: str, row: dict[str, str], row_no: int) -> dict[str, Any]:
    label = f"{file_name} row {row_no}"
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key in DATETIME_COLUMNS.get(file_name, ()):
            _datetime(value, f"{label}.{key}")
            result[key] = value
        elif key in DATE_COLUMNS.get(file_name, ()):
            _date(value, f"{label}.{key}", nullable=key in {"valid_to", "effective_to", "irn_ack_date"})
            result[key] = value or None
        elif key in DECIMAL_COLUMNS.get(file_name, ()):
            number = _decimal(value, f"{label}.{key}")
            if number < 0:
                raise ValueError(f"{label}.{key}: negative values are not allowed")
            if key in MONEY_COLUMNS.get(file_name, set()) and number.as_tuple().exponent < -2:
                raise ValueError(f"{label}.{key}: monetary precision exceeds two decimal places")
            result[key] = format(number, "f")
        elif key in BOOL_COLUMNS.get(file_name, ()):
            if value.lower() not in {"true", "false"}:
                raise ValueError(f"{label}.{key}: expected true or false")
            result[key] = value.lower() == "true"
        else:
            result[key] = value if value != "" else None
    return result


def validate_dataset(directory: Path) -> tuple[dict[str, Any], dict[str, bytes], dict[str, list[dict[str, Any]]]]:
    manifest_path, readme_path = directory / "source_manifest.json", directory / "README.md"
    if not manifest_path.is_file() or not readme_path.is_file():
        raise ValueError("source_manifest.json and README.md are required")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source_manifest.json is invalid JSON") from exc
    if manifest.get("data_classification") != "synthetic-fictional-not-real-taxpayer-data":
        raise ValueError("dataset must be explicitly labeled synthetic")
    expected_files = manifest.get("files")
    if not isinstance(expected_files, dict) or set(expected_files) != set(TABLES):
        raise ValueError("manifest CSV file list does not match the required P3 fixture contract")
    actual_csvs = {path.name for path in directory.glob("*.csv")}
    if actual_csvs != set(TABLES):
        missing, extra = sorted(set(TABLES) - actual_csvs), sorted(actual_csvs - set(TABLES))
        raise ValueError(f"CSV file set mismatch; missing={missing}, extra={extra}")

    raw: dict[str, bytes] = {"source_manifest.json": manifest_bytes, "README.md": readme_path.read_bytes()}
    records: dict[str, list[dict[str, Any]]] = {}
    for name, required in TABLES.items():
        content = (directory / name).read_bytes()
        entry = expected_files[name]
        sha = hashlib.sha256(content).hexdigest()
        if sha != entry.get("sha256") or len(content) != entry.get("bytes"):
            raise ValueError(f"{name}: manifest SHA-256 or byte count mismatch")
        try:
            reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
            if reader.fieldnames is None or len(reader.fieldnames) != len(required) or set(reader.fieldnames) != required:
                raise ValueError(f"{name}: columns do not match required schema")
            normalized = [_normalize(name, row, index) for index, row in enumerate(reader, 2)]
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError(f"{name}: invalid UTF-8 CSV") from exc
        if len(normalized) != entry.get("rows"):
            raise ValueError(f"{name}: manifest row count mismatch")
        for row_no, record in enumerate(normalized, 2):
            empty_required = [field for field, value in record.items() if value is None and field not in OPTIONAL_EMPTY.get(name, set())]
            if empty_required:
                raise ValueError(f"{name} row {row_no}: required values are empty for {empty_required}")
        raw[name], records[name] = content, normalized

    invoices = records["invoices.csv"]
    invoice_ids = [row["invoice_id"] for row in invoices]
    bill_nos = [row["bill_no"] for row in invoices]
    if len(set(invoice_ids)) != len(invoice_ids) or len(set(bill_nos)) != len(bill_nos):
        raise ValueError("invoices.csv contains duplicate invoice_id or bill_no")
    invoice_by_id = {row["invoice_id"]: row for row in invoices}
    invoice_by_bill = {row["bill_no"]: row for row in invoices}
    customer_ids = {row["customer_id"] for row in invoices}
    for row in invoices:
        label = f"invoices.csv {row['invoice_id']}"
        if row["currency"] != "INR":
            raise ValueError(f"{label}: only INR is supported by the configured synthetic checks")
        taxes = sum((_decimal(row[field], f"{label}.{field}") for field in ("cgst", "sgst", "igst")), Decimal(0))
        if _decimal(row["taxable_amount"], label) + taxes != _decimal(row["gross_amount"], label):
            raise ValueError(f"{label}: gross_amount does not equal taxable amount plus tax")
        if _decimal(row["quantity"], label) <= 0:
            raise ValueError(f"{label}: quantity must be positive")
    dispatches = records["dispatches.csv"]
    dispatch_invoice_ids = [row["invoice_id"] for row in dispatches]
    dispatch_ids = [row["dispatch_id"] for row in dispatches]
    if len(set(dispatch_invoice_ids)) != len(dispatch_invoice_ids) or len(set(dispatch_ids)) != len(dispatch_ids):
        raise ValueError("dispatches.csv contains duplicate invoice or dispatch IDs")
    for row in dispatches:
        if row["invoice_id"] not in invoice_by_id:
            raise ValueError(f"dispatches.csv references unknown invoice {row['invoice_id']}")
        if _decimal(row["quantity"], "dispatch quantity") <= 0:
            raise ValueError("dispatch quantity must be positive")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records["journal_entries.csv"]:
        if row["invoice_id"] and row["invoice_id"] not in invoice_by_id:
            raise ValueError(f"journal_entries.csv references unknown invoice {row['invoice_id']}")
        if (Decimal(row["debit"]) > 0) == (Decimal(row["credit"]) > 0):
            raise ValueError(f"journal_entries.csv {row['journal_id']} must have exactly one positive side per line")
        _date(row["posting_date"], f"journal_entries.csv {row['journal_id']}.posting_date")
        grouped.setdefault(row["journal_id"], []).append(row)
    for journal_id, lines in grouped.items():
        if len(lines) < 2:
            raise ValueError(f"journal_entries.csv journal {journal_id} must have at least two lines")
        if sum((Decimal(line["debit"]) for line in lines), Decimal(0)) != sum((Decimal(line["credit"]) for line in lines), Decimal(0)):
            raise ValueError(f"journal_entries.csv journal {journal_id} is not balanced")

    edge_ids: set[str] = set()
    for row in records["related_party_edges.csv"]:
        if row["edge_id"] in edge_ids:
            raise ValueError("related_party_edges.csv contains duplicate edge_id")
        edge_ids.add(row["edge_id"])
        for typ, object_id in ((row["subject_type"], row["subject_id"]), (row["object_type"], row["object_id"])):
            if typ == "customer" and object_id not in customer_ids:
                raise ValueError(f"related_party_edges.csv references unknown customer {object_id}")
        if row["valid_from"] and row["valid_to"] and row["valid_from"] > row["valid_to"]:
            raise ValueError(f"related_party_edges.csv {row['edge_id']} has reversed validity dates")
    for row in records["historical_sales.csv"]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", row["period"]):
            raise ValueError("historical_sales.csv period must be YYYY-MM")
        if row["customer_id"] not in customer_ids:
            raise ValueError(f"historical_sales.csv references unknown customer {row['customer_id']}")
        if int(row["invoice_count"]) < 0:
            raise ValueError("historical_sales.csv invoice_count cannot be negative")
    history_keys = [(row["customer_id"], row["period"]) for row in records["historical_sales.csv"]]
    if len(set(history_keys)) != len(history_keys):
        raise ValueError("historical_sales.csv contains duplicate customer-month rows")
    for row in records["threshold_policies.csv"]:
        _date(row["effective_from"], "threshold policy effective_from")
        _date(row["effective_to"], "threshold policy effective_to", nullable=True)
        if row["effective_to"] and row["effective_to"] < row["effective_from"]:
            raise ValueError(f"threshold policy {row['policy_id']} has reversed dates")
        if "test" not in (row["notes"] or "").lower() and "not legal" not in (row["source"] or "").lower():
            raise ValueError(f"threshold policy {row['policy_id']} is not labeled test-only")
        if Decimal(row["threshold_inr"]) <= 0:
            raise ValueError(f"threshold policy {row['policy_id']} threshold must be positive")
    gstr_bill_nos = [row["invoice_no"] for row in records["gstr1_rows.csv"]]
    if len(set(gstr_bill_nos)) != len(gstr_bill_nos):
        raise ValueError("gstr1_rows.csv contains duplicate invoice_no rows")
    for row in records["gstr1_rows.csv"]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", row["return_period"]):
            raise ValueError("gstr1_rows.csv return_period must be YYYY-MM")
        if row["invoice_no"] not in invoice_by_bill:
            raise ValueError(f"gstr1_rows.csv references unknown bill number {row['invoice_no']}")
        if sum((Decimal(row[field]) for field in ("igst", "cgst", "sgst")), Decimal(0)) + Decimal(row["taxable_value"]) != Decimal(row["gross_value"]):
            raise ValueError(f"gstr1_rows.csv {row['invoice_no']} gross_value arithmetic is inconsistent")
    for name in ("price_lists.csv", "promotions.csv"):
        for row in records[name]:
            _date(row["valid_from"], f"{name} valid_from")
            _date(row["valid_to"], f"{name} valid_to", nullable=True)
            if row["valid_to"] and row["valid_to"] < row["valid_from"]:
                raise ValueError(f"{name} contains reversed validity dates")
    for row in records["price_lists.csv"]:
        if Decimal(row["unit_price"]) <= 0:
            raise ValueError("price_lists.csv unit_price must be positive")
    for row in records["promotions.csv"]:
        if Decimal(row["discount_percent"]) > 100:
            raise ValueError("promotions.csv discount_percent must not exceed 100")
    for row in records["movement_routes.csv"]:
        if row["invoice_id"] not in invoice_by_id:
            raise ValueError(f"movement_routes.csv references unknown invoice {row['invoice_id']}")
        if Decimal(row["vehicle_capacity_units"]) <= 0 or Decimal(row["quantity_units"]) <= 0 or Decimal(row["distance_km"]) <= 0:
            raise ValueError("movement_routes.csv distance, quantity and vehicle capacity must be positive")
        if not row["vehicle_no"]:
            raise ValueError("movement_routes.csv vehicle_no is required")
        for pin_field in ("from_pin", "to_pin"):
            if not re.fullmatch(r"\d{6}", row[pin_field] or ""):
                raise ValueError(f"movement_routes.csv {pin_field} must be a 6-digit PIN")
        if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", row["consignee_gstin"] or ""):
            raise ValueError("movement_routes.csv consignee_gstin must be a well-formed GSTIN")
    verification_ids = [row["invoice_id"] for row in records["invoice_verification_status.csv"]]
    if len(set(verification_ids)) != len(verification_ids):
        raise ValueError("invoice_verification_status.csv contains duplicate invoice IDs")
    for row in records["invoice_verification_status.csv"]:
        if row["invoice_id"] not in invoice_by_id:
            raise ValueError(f"invoice_verification_status.csv references unknown invoice {row['invoice_id']}")
        if row["signature_check"] not in {"NOT_PERFORMED", "UNAVAILABLE"} or row["registration_timing_check"] not in {"NOT_PERFORMED", "UNAVAILABLE"}:
            raise ValueError("synthetic fixture verification statuses must not imply completed verification")
        # A signed QR envelope must be accompanied by its registration (ack) date so timing can be assessed.
        if row["signed_qr_envelope"] and not row["irn_ack_date"]:
            raise ValueError("invoice_verification_status.csv rows carrying a signed_qr_envelope must supply irn_ack_date")
    return manifest, raw, records


def import_dataset(directory: Path, db: sqlite3.Connection, vault: Path) -> dict[str, Any]:
    manifest, raw, records = validate_dataset(directory)
    manifest_sha = hashlib.sha256(raw["source_manifest.json"]).hexdigest()
    dataset_id = "DS-" + manifest_sha[:20]
    init_dataset(db)
    existing = db.execute("SELECT dataset_id FROM p3_dataset_imports WHERE dataset_id=?", (dataset_id,)).fetchone()
    if existing:
        return {"dataset_id": dataset_id, "already_imported": True, "file_count": len(raw), "row_count": sum(map(len, records.values())), "synthetic": True}
    for content in raw.values():
        sha = hashlib.sha256(content).hexdigest()
        from . import vault_crypto
        path = vault / sha
        path.parent.mkdir(parents=True, exist_ok=True)
        key = vault_crypto.configured_key(vault.parent)
        if not path.exists():
            path.write_bytes(vault_crypto.seal(sha, content, key) if key else content)
        elif hashlib.sha256(vault_crypto.unseal(sha, path.read_bytes(), key)).hexdigest() != sha:
            raise ValueError(f"content-addressed vault collision for {sha}")
    files: list[tuple[str, bytes, int]] = [(name, raw[name], len(records.get(name, []))) for name in raw]
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO p3_dataset_imports VALUES(?,?,datetime('now'),?)", (dataset_id, manifest_sha, str(manifest["dataset_version"])))
        for name, content, count in files:
            sha = hashlib.sha256(content).hexdigest()
            db.execute("INSERT INTO p3_dataset_files VALUES(?,?,?,?,?)", (dataset_id, name, sha, len(content), count))
            for row_no, record in enumerate(records.get(name, []), 1):
                db.execute("INSERT INTO p3_dataset_rows VALUES(?,?,?,?)", (dataset_id, name, row_no, p1.canonical(record).decode("utf-8")))
        p1.log_event(db, "client-demo", "p3_dataset_imported", dataset_id, {"manifest_sha256": manifest_sha, "file_hashes": {name: hashlib.sha256(content).hexdigest() for name, content, _ in files}, "synthetic": True})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"dataset_id": dataset_id, "already_imported": False, "file_count": len(raw), "row_count": sum(map(len, records.values())), "synthetic": True, "manifest_sha256": manifest_sha}


def import_endpoint(directory: Path, db: sqlite3.Connection, vault: Path) -> dict[str, Any]:
    try:
        return import_dataset(directory, db, vault)
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise HTTPException(422, f"P3 dataset rejected: {exc}") from exc

