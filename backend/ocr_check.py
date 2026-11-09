"""End-to-end check of the local OCR installation, using synthetic scans only.

  python -m Pramaan.backend.ocr_check            (Windows: run from the PRAMAAN folder with the venv active)

Prints PASS/FAIL for each step and exits with status 1 if any step fails. Nothing is uploaded or stored.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from datetime import date
from unittest.mock import patch

from . import document_import as di, fixtures_documents as fx, ocr

results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {detail}" if detail else ""))
    return ok


def main() -> int:
    print(f"PRAMAAN OCR check: {platform.system()} {platform.release()}, Python {platform.python_version()}")
    configured = os.environ.get("PRAMAAN_TESSERACT")
    path = ocr.tesseract_path()
    source = "PRAMAAN_TESSERACT" if configured else "PATH" if shutil.which("tesseract") else "none"
    if not step("1. Tesseract executable found", path is not None, f"{path} (from {source})" if path else ocr.unavailable_reason()):
        return 1
    version = ocr.engine_version()
    major = int(version.split()[-1].lstrip("v").split(".")[0]) if version and version.split()[-1].lstrip("v")[:1].isdigit() else 0
    step("2. Executable runs and reports its version", major >= 4, version or "no version output")
    langs = ocr.languages()
    step(f"3. Language data includes '{ocr.OCR_LANGUAGE}'", bool(langs) and ocr.OCR_LANGUAGE in langs, f"available: {', '.join(sorted(langs or [])) or 'unknown'}")

    bill, when, buyer, gstin, total = fx.SALES[0]
    started = time.monotonic()
    try:
        read = di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(bill, when, buyer, gstin, total, tax="cgst_sgst")))
    except di.DocumentReadError as exc:
        step("4. Scanned invoice is read", False, str(exc))
        read = None
    if read:
        quality = di.field_quality(read)
        expected = {"invoice_number": bill, "invoice_date": when.isoformat(), "total_cents": 11800000, "taxable_cents": 10000000}
        got = {k: read.get(k) for k in expected}
        step("4. Scanned invoice values match the synthetic document", got == expected and read["extraction"] == "ocr",
             f"read {got}, extraction={read['extraction']}, {time.monotonic() - started:.1f}s")
        step("5. Page references recorded", all(read["pages"].get(k) == 1 for k in expected), f"pages {read['pages']}")
        states = {k: v["state"] for k, v in quality.items()}
        step("6. OCR fields labelled 'ocr' or 'unreadable', never exact/validated", set(states.values()) <= {"ocr", "unreadable"}, f"{states}")
        books = {"bill_no": bill, "invoice_date": when.isoformat(), "gross_cents": 11800000, "gstin": None}
        status = di.compare_invoice(read, books)["status"]
        step("7. A matching OCR invoice still needs a person ('needs_review', not 'matches')", status == "needs_review", f"status={status}")

    try:
        bank = di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf()))
        rows = [(r["direction"], r["amount_cents"], r["page"]) for r in bank["rows"]]
        expected_rows = [("credit", 11800000, 1), ("debit", 4500000, 1), ("credit", 5900000, 1), ("debit", 825050, 1)]
        balance = di.check_balances(bank["rows"], bank["opening_balance_cents"])["status"]
        step("8. Scanned bank statement rows, pages and running balance", rows == expected_rows and balance == "consistent" and bank["extraction"] == "ocr",
             f"rows {rows}, balance {balance}, unread {len(bank['unread_lines'])}")
    except di.DocumentReadError as exc:
        step("8. Scanned bank statement is read", False, str(exc))

    degraded = di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(bill, when, buyer, gstin, total), dpi=60))
    dq = {k: v["state"] for k, v in di.field_quality(degraded).items()}
    dstatus = di.compare_invoice(degraded, {"bill_no": bill, "invoice_date": when.isoformat(), "gross_cents": 11800000, "gstin": gstin})["status"]
    step("9. Poor scan: unclear values are left out, never matched or verified",
         dstatus != "matches" and not ({"validated", "human_verified", "exact"} & set(dq.values())),
         f"status={dstatus}, total read={degraded.get('total_cents')}, set aside={degraded.get('uncertain')}, states={sorted(set(dq.values()))}")
    try:
        di.parse_bank_pdf(fx.scanned(fx.bank_statement_pdf(), dpi=45))
        step("10. Unreadable statement is refused", False, "a 45-dpi scan was accepted")
    except di.DocumentReadError as exc:
        step("10. Unreadable statement is refused", True, str(exc))

    with patch.object(ocr, "PAGE_TIMEOUT_SECONDS", 0.001):
        try:
            di.read_invoice_pdf(fx.scanned(fx.invoice_pdf(*fx.SALES[0])))
            step("11. Per-page time limit stops Tesseract", False, "no timeout")
        except di.DocumentReadError as exc:
            step("11. Per-page time limit stops Tesseract", "longer than" in str(exc), str(exc))
    two_pages = fx.scanned(fx.invoice_pdf(bill, when, buyer, gstin, total, second_page=("Terms: synthetic",)))
    with patch.object(ocr, "MAX_OCR_PAGES", 1):
        try:
            di.read_invoice_pdf(two_pages)
            step("12. Page limit refuses longer scans", False, "accepted")
        except di.DocumentReadError as exc:
            step("12. Page limit refuses longer scans", "up to 1 pages" in str(exc), str(exc))

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
