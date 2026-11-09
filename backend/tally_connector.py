"""Fetch a Day Book export from a running TallyPrime / Tally.ERP 9 over its HTTP/XML interface.

Status: client only. It builds Tally's documented XML export request, sends it to the Tally HTTP
server (Tally: F1 Help > Settings > Connectivity > "TallyPrime acts as: Server", port 9000 by
default), checks the reply with the same reader the upload uses, and saves the XML to a file.
You then upload that file as a "Sales register (Tally XML export)", so the original bytes are
preserved exactly like any other upload.

It is tested against a local stand-in HTTP server that returns synthetic Tally XML. It has NOT been
run against a real TallyPrime installation, so it is not a verified live integration.

Deliberately not a server endpoint: the PRAMAAN server never makes outbound connections to an
address a user typed (no server-side request forgery), and Tally needs no credentials of its own
over this interface, so it should only ever be reachable on the accountant's own machine or LAN.

Usage:
  python -m Pramaan.backend.tally_connector --url http://localhost:9000 --from 2025-04-01 --to 2026-03-31 \
      --company "Fictional Manufacturing Pvt Ltd" --out tally_daybook.xml
"""
from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from .document_import import DocumentReadError, parse_tally_sales

MAX_RESPONSE_BYTES = 50 * 1024 * 1024
TIMEOUT_SECONDS = 60


class TallyConnectionError(RuntimeError):
    """Tally could not be reached or did not return a usable export."""


def daybook_request(start: date, end: date, company: str | None = None) -> bytes:
    """Tally's XML export request for the Day Book between two dates (inclusive)."""
    company_var = f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>" if company else ""
    return ("<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Day Book</ID></HEADER>"
            "<BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
            f"<SVFROMDATE>{start:%Y%m%d}</SVFROMDATE><SVTODATE>{end:%Y%m%d}</SVTODATE>{company_var}"
            "</STATICVARIABLES></DESC></BODY></ENVELOPE>").encode("utf-8")


def fetch_daybook(url: str, start: date, end: date, company: str | None = None) -> tuple[bytes, dict]:
    """POST the export request; return (raw XML bytes, the reader's report). Raises on any problem."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TallyConnectionError("the Tally address must look like http://localhost:9000")
    if end < start:
        raise TallyConnectionError("the end date is before the start date")
    request = urllib.request.Request(url, data=daybook_request(start, end, company), method="POST",
                                     headers={"Content-Type": "text/xml; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - scheme checked above
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TallyConnectionError(f"could not reach Tally at {url}: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise TallyConnectionError("Tally's reply is larger than 50 MB; export a shorter period")
    if b"<LINEERROR>" in body.upper():
        start_at = body.upper().index(b"<LINEERROR>")
        raise TallyConnectionError("Tally reported an error: " + body[start_at:start_at + 300].decode("utf-8", "replace"))
    try:
        report = parse_tally_sales(body)
    except DocumentReadError as exc:
        raise TallyConnectionError(f"Tally replied, but not with a usable Day Book export ({exc})") from exc
    return body, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a Tally Day Book XML export for upload to PRAMAAN.")
    parser.add_argument("--url", default="http://localhost:9000")
    parser.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="end", required=True, type=date.fromisoformat)
    parser.add_argument("--company")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    body, report = fetch_daybook(args.url, args.start, args.end, args.company)
    Path(args.out).write_bytes(body)
    print(f"saved {len(body):,} bytes to {args.out}: {len(report['rows'])} sales vouchers, {len(report['skipped'])} skipped, "
          f"{len(report['rejected'])} rejected, {len(report['warnings'])} warnings. Upload this file as 'Sales register (Tally XML export)'.")


if __name__ == "__main__":
    main()
