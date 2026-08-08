import pytest
import requests
from unittest.mock import patch, MagicMock, call
import main
import post


# ── _cooldown_ok ──────────────────────────────────────────────────────────────

def test_cooldown_ok_when_nothing_posted_recently():
    with patch("main.db.posted_within", return_value=False):
        assert main._cooldown_ok("Structure Fire") is True


def test_cooldown_blocked_when_same_type_posted_recently():
    with patch("main.db.posted_within", return_value=True):
        assert main._cooldown_ok("Structure Fire") is False


def test_cooldown_queries_actual_post_time_not_creation_time():
    """The window must be keyed on when we posted, not when the incident was
    saved — otherwise draining a backlog bypasses the cooldown entirely."""
    with patch("main.db.posted_within", return_value=False) as posted_within:
        main._cooldown_ok("Structure Fire")
    posted_within.assert_called_once_with(main.POST_COOLDOWN_MINUTES, "Structure Fire")


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
        "posted_within": MagicMock(return_value=False),
        "geocode": MagicMock(return_value=None),
    }
    return mocks


def _run_main_with_chunks(chunks, mocks):
    with patch("main.db.init_db", mocks["init_db"]), \
         patch("main.capture.stream_chunks_multi", return_value=iter(chunks)), \
         patch("main.capture.is_silent", mocks["is_silent"]), \
         patch("main.transcribe.transcribe", mocks["transcribe"]), \
         patch("main.db.transcript_hash", mocks["transcript_hash"]), \
         patch("main.db.chunk_seen", mocks["chunk_seen"]), \
         patch("main.classify.keyword_check", mocks["keyword_check"]), \
         patch("main.db.log_chunk", mocks["log_chunk"]), \
         patch("main.classify.local_classify", mocks["local_classify"]), \
         patch("main.summarize.polish", mocks["polish"]), \
         patch("main.geocode.geocode", mocks["geocode"]), \
         patch("main.db.save_incident", mocks["save_incident"]), \
         patch("main.db.mark_posted", mocks["mark_posted"]), \
         patch("main.post.post_incident", mocks["post_incident"]), \
         patch("main.db.recent_incidents", mocks["recent_incidents"]), \
         patch("main.db.posted_within", mocks["posted_within"]), \
         patch("main.db.unposted_incidents", return_value=[]), \
         patch("main.dashboard.generate"), \
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
    base_mocks["posted_within"] = MagicMock(return_value=True)
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


# ── post backend failure resilience ────────────────────────────────────────────

def test_main_post_failure_does_not_crash_loop(base_mocks):
    """A Facebook/API timeout on post_incident must not kill the whole process."""
    base_mocks["post_incident"] = MagicMock(side_effect=requests.ConnectionError("boom"))
    _run_main_with_chunks([b"audio1", b"audio2"], base_mocks)
    # loop kept going and processed both chunks despite the post failure
    assert base_mocks["transcribe"].call_count == 2
    base_mocks["mark_posted"].assert_not_called()


def _held_row():
    from datetime import datetime, timezone
    return {
        "id": 7,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "incident_type": "Structure Fire",
        "summary": "Fire at 123 Main St",
        "location": "123 Main St",
        "incident_time": "09:00",
    }


def _flush_with(exc):
    row = _held_row()
    with patch("main.db.unposted_incidents", return_value=[row]), \
         patch("main.db.posted_within", return_value=False), \
         patch("main.db.mark_posted") as mark_posted, \
         patch("main.post.post_incident", side_effect=exc):
        main._flush_unposted()  # must not raise
    return mark_posted


def test_flush_retryable_failure_leaves_incident_unposted():
    """A connection error never reached Facebook, so the incident stays queued."""
    exc = post.PostFailed("no route", maybe_delivered=False, retryable=True)
    _flush_with(exc).assert_not_called()


def test_flush_timeout_closes_incident_to_avoid_duplicate():
    """A timeout may already be published — retrying it posted the same
    incident two and three times, so the row is closed out instead."""
    exc = post.PostFailed("slow", maybe_delivered=True, retryable=False)
    _flush_with(exc).assert_called_once_with(7, "uncertain")


def test_flush_rejection_closes_incident_as_rejected():
    exc = post.PostFailed("rejected 400", maybe_delivered=False, retryable=False)
    _flush_with(exc).assert_called_once_with(7, "rejected")
