"""Local anonymiser for Tally exports: run it on your own computer before sharing a real register.

    python -m backend.anonymise_tally --register "Sales Register.xlsx" --vouchers "Day Book.xml" \
        --out ..\\pramaan-shared --key ..\\pramaan-private\\anonymise.key [--dry-run] [--keep-narration]

Run from the PRAMAAN folder. It is a separate tool: the audit server never imports it.

What it does
- Writes NEW files; the originals are only read and are checked (SHA-256) to be unchanged afterwards.
  Because the output is rebuilt from cell values and XML text, hidden sheets, comments, images, defined names and
  file properties are never copied.
- Party and company names become "Party 3F2A9C" / "Company 1B7E04", the same everywhere (register cells, XML
  fields, ledger names and inside free text such as narration).
- GSTINs keep their first two digits (state code). The rest is replaced. The replacement has a valid check digit
  only if the original did, so data-quality problems survive anonymisation. Its PAN part starts "ZZ" and has
  holder type "X", which no real PAN uses, so a pseudonymised GSTIN can never be a real taxpayer.
- Addresses, phone numbers, e-mails, PANs, bank account numbers, IFSC codes and bank fields are removed.
  Narration is removed unless --keep-narration is given (then it is scrubbed instead).
- Bill numbers, dates, amounts and tax values are kept exactly. The tool proves it: the original and the output
  are both read with PRAMAAN's own readers, and every row must agree on everything except names and GSTINs.
- Pseudonyms are derived from a secret in the key file (HMAC-SHA256), so re-running gives the same names. The key
  file also holds the original -> pseudonym table. It is written outside the output folder, never inside a git
  repository, and must never be shared.
- Refuses to write inside a git repository, and refuses to finish if any original name, GSTIN, phone number or
  e-mail is still found in the output.
The report (printed and written as anonymise_report.json) holds counts only, never original values.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .document_import import _GSTIN_CHARS, GSTIN, DocumentReadError, _tally_root, gstin_check, parse_tally_sales
from .tally_register import _field_for, _find_header, _grid, _label, parse_tally_register

PHONE = re.compile(r"(?<![0-9])(?:\+?91[\s-]?)?(?:[6-9][0-9]{4}[\s-]?[0-9]{5}|0[0-9]{2,4}[\s-]?[0-9]{6,8})(?![0-9])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PAN = re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]\b")
ACCOUNT = re.compile(r"(?<![0-9])[0-9]{9,18}(?![0-9])")
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
PINCODE = re.compile(r"(?<![0-9])[1-9][0-9]{5}(?![0-9])")
GSTIN_ANY = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z][Z][0-9A-Z]\b")
# XML fields removed outright (case-insensitive tag names; ADDRESS covers ADDRESS.LIST children).
REMOVE_TAGS = {"ADDRESS", "BASICBUYERADDRESS", "PHONENUMBER", "LEDGERPHONE", "LEDGERMOBILE", "MOBILENUMBER", "EMAIL", "LEDGEREMAIL",
               "PINCODE", "BANKNAME", "IFSCODE", "ACCOUNTNUMBER", "BANKACCOUNTNUMBER", "BANKACCHOLDERNAME", "BANKBRANCHNAME",
               "INCOMETAXNUMBER", "PANNUMBER", "BASICBUYERPAN", "CONTACTPERSON", "LEDGERCONTACT", "WEBSITE", "STATENAME", "COUNTRYNAME"}
GSTIN_TAGS = {"PARTYGSTIN", "BASICBUYERGSTIN", "GSTREGISTRATIONNUMBER", "CMPGSTIN", "PARTYGSTREGISTRATIONNUMBER", "CONSIGNEEGSTIN"}
PARTY_TAGS = {"PARTYLEDGERNAME", "PARTYNAME", "BASICBUYERNAME", "PARTYMAILINGNAME", "CONSIGNEEMAILINGNAME", "BUYERNAME"}
COMPANY_TAGS = {"SVCURRENTCOMPANY", "COMPANYNAME", "BASICCOMPANYNAME"}
ID_ATTRS = {"REMOTEID", "GUID", "VCHKEY"}


class AnonymiseError(Exception):
    pass


def _token(secret: bytes, value: str) -> str:
    """A stable replacement ID made of letters only, so it can never look like a phone or account number."""
    return "anon-" + hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()[:16].translate(str.maketrans("0123456789", "ghijklmnop"))


def _git_root(path: Path) -> Path | None:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Pseudonyms:
    def __init__(self, secret: bytes):
        self.secret = secret
        self.table: dict[str, dict[str, str]] = {"party": {}, "company": {}, "gstin": {}}

    def _h(self, kind: str, value: str) -> bytes:
        return hmac.new(self.secret, f"{kind}:{value}".encode(), hashlib.sha256).digest()

    def name(self, kind: str, original: str) -> str:
        key = " ".join(original.split()).upper()
        if key not in self.table[kind]:
            pseudo = f"{'Party' if kind == 'party' else 'Company'} {self._h(kind, key).hex()[:6].upper()}"
            if pseudo in self.table[kind].values():
                raise AnonymiseError("two different names produced the same pseudonym; delete the key file and re-run")
            self.table[kind][key] = pseudo
        return self.table[kind][key]

    def gstin(self, original: str) -> str:
        value = re.sub(r"\s+", "", original).upper()
        if not value:
            return ""
        if value not in self.table["gstin"]:
            digest = self._h("gstin", value)
            letters = "ABCDEFGHJKLMNPQRSTUVWXY"
            if not GSTIN.fullmatch(value):
                pseudo = "NOTGSTIN" + digest.hex()[:7].upper()  # unreadable originals stay unreadable
            else:
                body = value[:2] + "ZZ" + letters[digest[0] % 23] + "X" + letters[digest[1] % 23] + f"{int.from_bytes(digest[2:4], 'big') % 10000:04d}" + letters[digest[4] % 23] + value[12] + "Z"
                check = _check_digit(body)
                if gstin_check(value) is not None:  # the original's check digit was wrong: keep it wrong
                    check = _GSTIN_CHARS[(_GSTIN_CHARS.index(check) + 1) % 36]
                pseudo = body + check
            self.table["gstin"][value] = pseudo
        return self.table["gstin"][value]


def _check_digit(body: str) -> str:
    total = 0
    for position, char in enumerate(body):
        product = _GSTIN_CHARS.index(char) * (2 if position % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


class Scrubber:
    """Replaces known names and GSTINs inside free text and removes contact and bank details."""

    def __init__(self, names: Pseudonyms):
        self.names = names
        self.counts: dict[str, int] = {}

    def _count(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n

    def text(self, value: str) -> str:
        if not value:
            return value
        out = value
        for kind in ("company", "party"):
            for original in sorted(self.names.table[kind], key=len, reverse=True):
                pattern = re.compile(r"\s+".join(map(re.escape, original.split())), re.IGNORECASE)
                out, n = pattern.subn(self.names.table[kind][original], out)
                if n:
                    self._count(f"{kind}_names_in_text", n)
        out = GSTIN_ANY.sub(lambda m: self.names.gstin(m.group(0)), out)
        for label, pattern in (("emails", EMAIL), ("pans", PAN), ("ifsc", IFSC), ("phones", PHONE), ("account_numbers", ACCOUNT)):
            out, n = pattern.subn("[removed]", out)
            if n:
                self._count(label, n)
        return out


def _load_key(path: Path) -> tuple[bytes, dict]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return bytes.fromhex(data["secret"]), data
    return secrets.token_bytes(32), {}


# --------------------------------------------------------------------------- register (.xlsx)

def _collect_register_names(source: bytes, names: Pseudonyms) -> dict[str, Any]:
    read = parse_tally_register(source)
    for row in read["rows"]:
        if row["Customer"]:
            names.name("party", row["Customer"])
        if row["GST No"]:
            names.gstin(row["GST No"])
    return read


def anonymise_register(source: bytes, names: Pseudonyms, scrub: Scrubber) -> bytes:
    from openpyxl import Workbook, load_workbook
    book = load_workbook(io.BytesIO(source), data_only=True)
    out = Workbook()
    out.remove(out.active)
    for sheet in book.worksheets:
        if sheet.sheet_state != "visible":
            scrub._count("hidden_sheets_dropped")
            continue
        grid = _grid(sheet)
        header = _find_header(grid)
        target = out.create_sheet(sheet.title[:31])
        start = header[0] if header else len(grid)
        header_end = start + (header[1] if header else 0)
        columns = header[2] if header else {}
        party_cols = {c for c, f in columns.items() if f == "party"}
        gstin_cols = {c for c, f in columns.items() if f == "gstin"}
        for r in range(1, (sheet.max_row or 0) + 1):
            for c in range(1, (sheet.max_column or 0) + 1):
                value = sheet.cell(r, c).value
                if value is None:
                    continue
                if isinstance(value, str):
                    if start <= r - 1 < header_end or _field_for(_label(value)):
                        pass  # header labels (also when repeated on a later page) are kept
                    elif r - 1 < start:  # lines above the header: company name, address, period
                        if r == 1 or (r == 2 and not re.search(r"\d{4}", value)):
                            value = names.name("company", value) if r == 1 else "[address removed]"
                        elif re.search(r"(?i)register|\bto\b|\d{1,2}-[a-z]{3}-\d{2,4}", value):
                            value = scrub.text(value)
                        else:
                            value = "[removed]"
                            scrub._count("header_lines_removed")
                    elif c - 1 in party_cols and value.strip() and not re.match(r"(?i)\s*(grand\s*total|sub[\s-]*total|total|\(cancelled\))", value):
                        value = names.name("party", value)
                    elif c - 1 in gstin_cols:
                        value = names.gstin(value)
                    else:
                        value = scrub.text(value)
                target.cell(r, c, value)
        for merged in sheet.merged_cells.ranges:
            target.merge_cells(str(merged))
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- vouchers (.xml)

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].upper()


def _collect_xml_names(source: bytes, names: Pseudonyms) -> None:
    root = _tally_root(source)
    for node in root.iter():
        tag, text = _local(node.tag), (node.text or "").strip()
        if not text:
            continue
        if tag in PARTY_TAGS:
            names.name("party", text)
        elif tag in COMPANY_TAGS:
            names.name("company", text)
        elif tag in GSTIN_TAGS:
            names.gstin(text)


def anonymise_vouchers(source: bytes, names: Pseudonyms, scrub: Scrubber, keep_narration: bool) -> bytes:
    root = _tally_root(source)
    parties = set(names.table["party"])
    for node in root.iter():
        tag = _local(node.tag)
        text = node.text or ""
        if tag.startswith("ADDRESS") or tag in REMOVE_TAGS:
            if text.strip():
                node.text = ""
                scrub._count("xml_fields_removed")
        elif tag == "NARRATION" and not keep_narration:
            if text.strip():
                node.text = ""
                scrub._count("narrations_removed")
        elif tag in GSTIN_TAGS:
            node.text = names.gstin(text) if text.strip() else text
        elif tag in PARTY_TAGS or (tag == "LEDGERNAME" and " ".join(text.split()).upper() in parties):
            node.text = names.name("party", text) if text.strip() else text
        elif tag in COMPANY_TAGS:
            node.text = names.name("company", text) if text.strip() else text
        elif text.strip():
            node.text = scrub.text(text)
        for attr in list(node.attrib):
            if attr.upper() in ID_ATTRS:
                node.set(attr, _token(names.secret, node.attrib[attr]))
            else:
                node.set(attr, scrub.text(node.attrib[attr]))
    for node in root.iter():
        if _local(node.tag) in ("GUID",) and node.text:
            node.text = _token(names.secret, node.text)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


# --------------------------------------------------------------------------- checks

def _same_figures(before: list[dict], after: list[dict], names: Pseudonyms, label: str) -> list[str]:
    problems = []
    if len(before) != len(after):
        return [f"{label}: {len(before)} rows before, {len(after)} after"]
    for i, (a, b) in enumerate(zip(before, after), 1):
        for field in set(a) | set(b):
            if field == "Customer":
                expected = names.name("party", a[field]) if a[field] else a[field]
            elif field == "GST No":
                expected = names.gstin(a[field]) if a[field] else a[field]
            else:
                expected = a.get(field)
            if b.get(field) != expected:
                problems.append(f"{label} row {i}: {field} changed")
    return problems


def _leaks(blob: str, names: Pseudonyms) -> dict[str, int]:
    upper = blob.upper()
    found = {"names": sum(1 for kind in ("party", "company") for n in names.table[kind] if len(n) >= 4 and n in upper),
             "gstins": sum(1 for g in names.table["gstin"] if g in upper),
             "emails": len(EMAIL.findall(blob)), "phones": len(PHONE.findall(blob))}
    return {k: v for k, v in found.items() if v}


def _xlsx_text(data: bytes) -> str:
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))


def run(register: Path | None, vouchers: Path | None, out: Path, key: Path, dry_run: bool = False, keep_narration: bool = False) -> dict[str, Any]:
    if not register and not vouchers:
        raise AnonymiseError("give --register and/or --vouchers")
    sources = [p for p in (register, vouchers) if p]
    for p in sources:
        if not p.is_file():
            raise AnonymiseError(f"file not found: {p.name}")
    out, key = out.resolve(), key.resolve()
    for label, place in (("output folder", out), ("key file", key.parent)):
        if repo := _git_root(place):
            raise AnonymiseError(f"the {label} is inside a git repository ({repo.name}); choose a folder outside it so nothing can be committed")
    if key.parent == out or out in key.parents:
        raise AnonymiseError("keep the key file outside the output folder: the output is shared, the key never is")
    if any(p.resolve().parent == out for p in sources):
        raise AnonymiseError("the output folder must not be the folder holding the originals")
    before = {p: _sha(p) for p in sources}
    secret, saved = _load_key(key)
    names = Pseudonyms(secret)
    for kind in names.table:
        names.table[kind].update(saved.get("table", {}).get(kind, {}))
    scrub = Scrubber(names)
    report: dict[str, Any] = {"tool": "pramaan-anonymise-tally-v1", "dry_run": dry_run, "files": {}}
    gstin_quality: dict[str, int] = {"valid": 0, "bad_check_digit": 0, "not_gstin_format": 0}
    reg_bytes = register.read_bytes() if register else None
    xml_bytes = vouchers.read_bytes() if vouchers else None
    try:
        # Names from both files first, so each file's free text is scrubbed of names that only the other one has.
        reg_read = _collect_register_names(reg_bytes, names) if reg_bytes else None
        if xml_bytes:
            _collect_xml_names(xml_bytes, names)
        xml_read = parse_tally_sales(xml_bytes) if xml_bytes else None
    except DocumentReadError as exc:
        raise AnonymiseError(f"could not read the export: {exc}") from exc
    for original in names.table["gstin"]:
        problem = gstin_check(original)
        gstin_quality["valid" if problem is None else "not_gstin_format" if "format" in problem else "bad_check_digit"] += 1
    outputs: dict[str, bytes] = {}
    problems: list[str] = []
    if reg_bytes:
        data = anonymise_register(reg_bytes, names, scrub)
        after = parse_tally_register(data)
        problems += _same_figures(reg_read["rows"], after["rows"], names, "register")
        if (len(after["skipped"]), len(after["rejected"])) != (len(reg_read["skipped"]), len(reg_read["rejected"])):
            problems.append("register: skipped/rejected line counts changed")
        if leak := _leaks(_xlsx_text(data), names):
            problems.append(f"register output still contains original details: {leak}")
        outputs["sales_register_anonymised.xlsx"] = data
        report["files"]["register"] = {"rows": len(after["rows"]), "credit_notes": sum(1 for s in after["sources"] if s["status"] == "credit_note"),
                                       "skipped_lines": len(after["skipped"]), "rejected_lines": len(after["rejected"]), "warnings": len(after["warnings"])}
    if xml_bytes:
        data = anonymise_vouchers(xml_bytes, names, scrub, keep_narration)
        after = parse_tally_sales(data)
        problems += _same_figures(xml_read["rows"], after["rows"], names, "vouchers")
        if leak := _leaks(data.decode("utf-8", "ignore"), names):
            problems.append(f"voucher output still contains original details: {leak}")
        outputs["vouchers_anonymised.xml"] = data
        report["files"]["vouchers"] = {"vouchers": after["vouchers_seen"], "sales_rows": len(after["rows"]), "rejected": len(after["rejected"])}
    report.update({"parties": len(names.table["party"]), "companies": len(names.table["company"]), "gstins": len(names.table["gstin"]),
                   "original_gstin_quality": gstin_quality, "removed_or_replaced": dict(sorted(scrub.counts.items())),
                   "figures_identical": not any("changed" in p or "rows before" in p for p in problems), "problems": problems[:50]})
    if problems:
        report["result"] = "refused: output not written"
        return report
    if after_hashes := {p: _sha(p) for p in sources}:
        if after_hashes != before:
            raise AnonymiseError("an original file changed while the tool ran")
    report["originals_unchanged"] = True
    if dry_run:
        report["result"] = "dry run: nothing written"
        return report
    out.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        target = out / name
        if target.exists() and target.read_bytes() != data:
            raise AnonymiseError(f"{name} already exists in the output folder with different content; remove it or choose another folder")
        target.write_bytes(data)
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps({"warning": "PRIVATE: maps pseudonyms back to real names. Never share or commit.", "secret": secret.hex(),
                               "table": names.table}, indent=1, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    (out / "anonymise_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    report["result"] = "written"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--register", type=Path, help="Tally Sales Register exported to .xlsx")
    parser.add_argument("--vouchers", type=Path, help="Tally vouchers / Day Book exported to XML")
    parser.add_argument("--out", type=Path, required=True, help="folder for the anonymised copies (outside any git repository)")
    parser.add_argument("--key", type=Path, required=True, help="private key file (created if missing; never share it)")
    parser.add_argument("--dry-run", action="store_true", help="check everything, write nothing")
    parser.add_argument("--keep-narration", action="store_true", help="keep narration text (names and contact details are still removed)")
    args = parser.parse_args(argv)
    try:
        report = run(args.register, args.vouchers, args.out, args.key, args.dry_run, args.keep_narration)
    except AnonymiseError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1))
    return 0 if report["result"] in ("written", "dry run: nothing written") else 1


if __name__ == "__main__":
    raise SystemExit(main())
