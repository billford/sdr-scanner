import os
import sys
import tempfile

import pytest

# Make the scanner-page package root importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def tmp_db(monkeypatch):
    """Isolated SQLite DB for each test."""
    import db, config
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(config, "DB_PATH", tmp)
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db.init_db()
    yield tmp
    if os.path.exists(tmp):
        os.unlink(tmp)


@pytest.fixture
def sample_incident(tmp_db):
    import db
    raw = "Engine 3 respond to 123 Main Street for a structure fire"
    h = db.transcript_hash(raw)
    return {
        "time": "14:32",
        "type": "Structure Fire",
        "location": "123 Main Street",
        "local_summary": "Structure fire with smoke showing at 123 Main Street.",
        "summary": "[14:32] Structure Fire — 123 Main Street — Engine 3 dispatched.",
        "raw_transcript": raw,
        "transcript_hash": h,
    }
