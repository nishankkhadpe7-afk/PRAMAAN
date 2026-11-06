"""Portable import shim (B8/T6).

The code base imports itself as ``Pramaan.backend``. Put ``<repo>/launcher`` on PYTHONPATH and
this package resolves to the repository root, whatever the checkout folder is called and on
case-sensitive file systems. Replaces the generated shim that hard-coded an absolute Windows path.
"""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[2])]
