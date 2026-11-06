"""T8: per-test SQLite instances live under tests/.runtime; remove them after the session."""
import shutil
from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parent / ".runtime"


@pytest.fixture(scope="session", autouse=True)
def clean_runtime_directories():
    yield
    shutil.rmtree(RUNTIME, ignore_errors=True)
