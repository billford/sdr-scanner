import pytest
import db


def test_transcript_hash_deterministic():
    h1 = db.transcript_hash("Engine 3, structure fire")
    h2 = db.transcript_hash("Engine 3, structure fire")
    assert h1 == h2


def test_transcript_hash_whitespace_stripped():
    assert db.transcript_hash("  hello  ") == db.transcript_hash("hello")


def test_transcript_hash_different_inputs():
    assert db.transcript_hash("fire") != db.transcript_hash("accident")


def test_chunk_not_seen_initially(tmp_db):
    assert not db.chunk_seen("nonexistent_hash")


def test_chunk_seen_after_log(tmp_db):
    h = db.transcript_hash("some transcript")
    db.log_chunk(h, had_incident=False)
    assert db.chunk_seen(h)


def test_log_chunk_duplicate_ignored(tmp_db):
    h = db.transcript_hash("duplicate")
    db.log_chunk(h, had_incident=True)
    db.log_chunk(h, had_incident=True)  # should not raise


def test_save_incident_returns_id(tmp_db, sample_incident):
    iid = db.save_incident(sample_incident)
    assert isinstance(iid, int) and iid > 0


def test_save_incident_duplicate_returns_none(tmp_db, sample_incident):
    db.save_incident(sample_incident)
    iid2 = db.save_incident(sample_incident)
    assert iid2 is None


def test_mark_posted(tmp_db, sample_incident):
    iid = db.save_incident(sample_incident)
    db.mark_posted(iid, "fb-post-123")
    recent = db.recent_incidents(30)
    assert recent[0]["posted"] == 1
    assert recent[0]["post_id"] == "fb-post-123"


def test_recent_incidents_empty(tmp_db):
    assert db.recent_incidents(30) == []


def test_recent_incidents_returns_saved(tmp_db, sample_incident):
    db.save_incident(sample_incident)
    recent = db.recent_incidents(30)
    assert len(recent) == 1
    assert recent[0]["summary"] == sample_incident["summary"]


def test_recent_incidents_unposted_included(tmp_db, sample_incident):
    db.save_incident(sample_incident)
    recent = db.recent_incidents(30)
    assert recent[0]["posted"] == 0
