"""Local OCR for scanned (image-only) PDF pages, using the Tesseract program if it is installed.

Design rules:
- Local only. Page images never leave the machine; Tesseract runs as a subprocess with no shell.
- Optional. If Tesseract is not installed, scanned PDFs are refused with a clear message, exactly
  as before. Nothing else in PRAMAAN depends on OCR.
- Bounded. Page count, image size, per-page time and total time are all capped.
- Provenance kept. Every word carries its page, position and Tesseract's own confidence (0-100).
  Callers mark OCR values as OCR-derived, and words below MIN_CONFIDENCE as uncertain; uncertain
  financial values are never imported automatically.
- OCR output is a reading of a company-supplied document. It is never verification.

Configuration (environment variables):
  PRAMAAN_TESSERACT       path to the tesseract executable (default: found on PATH); quotes are allowed
  PRAMAAN_OCR             set to "off" to disable OCR even when Tesseract is installed

Check an installation end to end (synthetic scans only):
  python -m Pramaan.backend.ocr_check
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any

OCR_ENGINE = "tesseract"
MAX_OCR_PAGES = 20            # a scanned statement or invoice longer than this is refused
OCR_DPI = 300
MAX_PIXELS = 40_000_000       # ~ A3 at 300 dpi; larger pages are rendered at a lower resolution
PAGE_TIMEOUT_SECONDS = 30
TOTAL_TIMEOUT_SECONDS = 120
MIN_CONFIDENCE = 80           # Tesseract word confidence below this is treated as uncertain


class OcrUnavailable(RuntimeError):
    """OCR is not installed or switched off; the message says how to enable it."""


class OcrFailed(RuntimeError):
    """OCR ran but could not finish within the limits."""


OCR_LANGUAGE = "eng"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: don't flash a console window per page


def _configured() -> str | None:
    raw = os.environ.get("PRAMAAN_TESSERACT")
    if raw is None:
        return None
    # Windows users often paste the path with quotes: "C:\Program Files\Tesseract-OCR\tesseract.exe"
    return raw.strip().strip('"').strip("'").strip() or None


def tesseract_path() -> str | None:
    if os.environ.get("PRAMAAN_OCR", "").lower() == "off":
        return None
    configured = _configured()
    if configured:
        return configured if os.path.isfile(configured) else None
    return shutil.which("tesseract")


def unavailable_reason() -> str:
    """Why OCR can't run, in words that say how to fix it."""
    if os.environ.get("PRAMAAN_OCR", "").lower() == "off":
        return "OCR is switched off (PRAMAAN_OCR=off)"
    configured = _configured()
    if configured and not os.path.isfile(configured):
        return f"PRAMAAN_TESSERACT points to {configured}, but no file exists there"
    return ("this PDF is scanned (no text layer) and OCR is not installed; install Tesseract "
            "(https://github.com/tesseract-ocr/tesseract) or upload a text PDF or CSV")


def _run(args: list[str], timeout: float, data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=data, capture_output=True, timeout=timeout, check=False, creationflags=_NO_WINDOW)


def engine_version() -> str | None:
    path = tesseract_path()
    if not path:
        return None
    try:
        out = _run([path, "--version"], 10)
    except (OSError, subprocess.SubprocessError):
        return None
    first = (out.stdout or out.stderr).decode("utf-8", "replace").splitlines()
    return first[0].strip() if first else None


_LANGS: dict[str, set[str] | None] = {}


def languages() -> set[str] | None:
    """Language packs Tesseract reports (`--list-langs`), or None if it could not be asked."""
    path = tesseract_path()
    if not path:
        return None
    if path not in _LANGS:
        try:
            out = _run([path, "--list-langs"], 10)
            lines = (out.stdout + out.stderr).decode("utf-8", "replace").splitlines()
            _LANGS[path] = {l.strip() for l in lines if l.strip() and not l.lower().startswith("list of")} if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    return _LANGS[path]


def page_has_text(page) -> bool:
    return bool(page.get_text("text").strip())


def ocr_page_words(page, deadline: float) -> list[tuple[float, float, float, float, str, float]]:
    """(x0, y0, x1, y1, text, confidence) in PDF points, like PyMuPDF's words plus a confidence."""
    path = tesseract_path()
    if not path:
        raise OcrUnavailable(unavailable_reason())
    langs = languages()
    if langs is not None and OCR_LANGUAGE not in langs:
        raise OcrUnavailable(f"Tesseract is installed but its English language data ({OCR_LANGUAGE}.traineddata) is missing; "
                             "reinstall Tesseract with English selected")
    import pymupdf
    rect = page.rect
    dpi = OCR_DPI
    while (rect.width / 72 * dpi) * (rect.height / 72 * dpi) > MAX_PIXELS and dpi > 100:
        dpi -= 50
    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OcrFailed(f"OCR stopped: the {TOTAL_TIMEOUT_SECONDS}-second limit for one document was reached")
    try:
        done = _run([path, "stdin", "stdout", "--psm", "6", "-l", OCR_LANGUAGE, "tsv"], min(PAGE_TIMEOUT_SECONDS, remaining), pixmap.tobytes("png"))
    except subprocess.TimeoutExpired as exc:
        raise OcrFailed(f"OCR of one page took longer than {PAGE_TIMEOUT_SECONDS} seconds") from exc
    except OSError as exc:
        raise OcrUnavailable("the Tesseract program could not be started") from exc
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrFailed("Tesseract could not read this page" + (f" ({detail[-1][:200]})" if detail else ""))
    scale = 72 / dpi
    words = []
    for line in done.stdout.decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or not parts[11].strip():
            continue
        try:
            left, top, width, height, conf = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9]), float(parts[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        words.append((left * scale, top * scale, (left + width) * scale, (top + height) * scale, parts[11].strip(), conf))
    return words


def check_page_budget(page_count: int) -> None:
    if page_count > MAX_OCR_PAGES:
        raise OcrFailed(f"scanned PDFs are read up to {MAX_OCR_PAGES} pages; this one has {page_count}")


def provenance() -> dict[str, Any]:
    return {"engine": OCR_ENGINE, "version": engine_version(), "language": OCR_LANGUAGE, "dpi": OCR_DPI, "min_confidence": MIN_CONFIDENCE}
