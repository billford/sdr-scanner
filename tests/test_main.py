import pytest
from unittest.mock import patch, MagicMock, call
import main


# ── _cooldown_ok ──────────────────────────────────────────────────────────────

def test_cooldown_ok_no_recent_incidents():
    with patch("main.db.recent_incidents", return_value=[]):
        assert main._cooldown_ok() is True


def test_cooldown_ok_recent_incident_not_posted():
    with patch("main.db.recent_incidents", return_value=[{"posted": 0}]):
        assert main._cooldown_ok() is True


def test_cooldown_ok_recent_incident_posted():
    with patch("main.db.recent_incidents", return_value=[{"posted": 1}]):
        assert main._cooldown_ok() is False


def test_cooldown_ok_mixed_incidents():
    incidents = [{"posted": 0}, {"posted": 1}, {"posted": 0}]
    with patch("main.db.recent_incidents", return_value=incidents):
        assert main._cooldown_ok() is False


# ── _handle_signal ────────────────────────────────────────────────────────────

def test_handle_signal_sets_running_false():
    main._RUNNING = True  # ensure clean state
    main._handle_signal(None, None)
    assert main._RUNNING is False
    main._RUNNING = True  # restore


# ── main loop ─────────────────────────────────────────────────────────────────

@pytest.fixture
def base_mocks(monkeypatch):
    """Patch all external collaborators used by main()."""
    monkeypatch.setattr(main, "_RUNNING", True)
    mocks = {
        "init_db": MagicMock(),
        "stream_chunks": None,  # set per test
        "is_silent": MagicMock(return_value=False),
        "transcribe": MagicMock(return_value="Engine 3 respond to structure fire"),
        "transcript_hash": MagicMock(return_value="abc123"),
        "chunk_seen": MagicMock(return_value=False),
        "keyword_check": MagicMock(return_value=True),
        "log_chunk": MagicMock(),
        "local_classify": MagicMock(return_value={
            "type": "Structure Fire",
            "location": "123 Main St",
            "local_summary": "Fire at 123 Main St",
            "summary": "Fire at 123 Main St",
            "raw_transcript": "Engine 3 respond to structure fire",
            "transcript_hash": "abc123",
        }),
        "polish": MagicMock(return_value={
            "type": "Structure Fire",
            "location": "123 Main St",
            "summary": "[14:32] Structure Fire — 123 Main St — Engine 3 dispatched.",
            "raw_transcript": "Engine 3 respond to structure fire",
            "transcript_hash": "abc123",
        }),
        "save_incident": MagicMock(return_value=1),
        "mark_posted": MagicMock(),
        "post_incident": MagicMock(return_value=""),
        "recent_incidents": MagicMock(return_value=[]),
    }
    return mocks


def _run_main_with_chunks(chunks, mocks):
    with patch("main.db.init_db", mocks["init_db"]), \
         patch("main.capture.stream_chunks", return_value=iter(chunks)), \
         patch("main.capture.is_silent", mocks["is_silent"]), \
         patch("main.transcribe.transcribe", mocks["transcribe"]), \
         patch("main.db.transcript_hash", mocks["transcript_hash"]), \
         patch("main.db.chunk_seen", mocks["chunk_seen"]), \
         patch("main.classify.keyword_check", mocks["keyword_check"]), \
         patch("main.db.log_chunk", mocks["log_chunk"]), \
         patch("main.classify.local_classify", mocks["local_classify"]), \
         patch("main.summarize.polish", mocks["polish"]), \
         patch("main.db.save_incident", mocks["save_incident"]), \
         patch("main.db.mark_posted", mocks["mark_posted"]), \
         patch("main.post.post_incident", mocks["post_incident"]), \
         patch("main.db.recent_incidents", mocks["recent_incidents"]), \
         patch("main.signal.signal"):
        main.main()


def test_main_silent_chunk_skipped(base_mocks):
    base_mocks["is_silent"] = MagicMock(return_value=True)
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["transcribe"].assert_not_called()


def test_main_empty_transcript_skipped(base_mocks):
    base_mocks["transcribe"] = MagicMock(return_value="")
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["keyword_check"].assert_not_called()


def test_main_duplicate_chunk_skipped(base_mocks):
    base_mocks["chunk_seen"] = MagicMock(return_value=True)
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["keyword_check"].assert_not_called()


def test_main_no_keywords_skips_ollama(base_mocks):
    base_mocks["keyword_check"] = MagicMock(return_value=False)
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["local_classify"].assert_not_called()


def test_main_ollama_no_incident_skips_post(base_mocks):
    base_mocks["local_classify"] = MagicMock(return_value=None)
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["polish"].assert_not_called()
    base_mocks["post_incident"].assert_not_called()


def test_main_full_pipeline_posts_incident(base_mocks):
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["polish"].assert_called_once()
    base_mocks["save_incident"].assert_called_once()
    base_mocks["post_incident"].assert_called_once()
    base_mocks["mark_posted"].assert_called_once_with(1, "")


def test_main_cooldown_skips_post(base_mocks):
    base_mocks["recent_incidents"] = MagicMock(return_value=[{"posted": 1}])
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["save_incident"].assert_called_once()
    base_mocks["post_incident"].assert_not_called()


def test_main_duplicate_incident_in_db_skips_post(base_mocks):
    base_mocks["save_incident"] = MagicMock(return_value=None)
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["post_incident"].assert_not_called()


def test_main_processes_multiple_chunks(base_mocks):
    _run_main_with_chunks([b"audio1", b"audio2", b"audio3"], base_mocks)
    assert base_mocks["transcribe"].call_count == 3


def test_main_stops_when_running_false(base_mocks, monkeypatch):
    monkeypatch.setattr(main, "_RUNNING", False)
    _run_main_with_chunks([b"audio"], base_mocks)
    base_mocks["transcribe"].assert_not_called()
