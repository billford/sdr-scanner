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


def test_save_incident_stores_coordinates(tmp_db, sample_incident):
    sample_incident["lat"] = 41.499
    sample_incident["lon"] = -81.694
    db.save_incident(sample_incident)
    recent = db.recent_incidents(30)
    assert recent[0]["lat"] == 41.499
    assert recent[0]["lon"] == -81.694


def test_save_incident_without_coordinates(tmp_db, sample_incident):
    db.save_incident(sample_incident)
    recent = db.recent_incidents(30)
    assert recent[0]["lat"] is None
    assert recent[0]["lon"] is None


def test_cached_geocode_missing(tmp_db):
    assert db.cached_geocode("nowhere in particular") is None


def test_cached_geocode_hit(tmp_db):
    db.save_geocode("123 Main St", 41.499, -81.694)
    assert db.cached_geocode("123 Main St") == (41.499, -81.694)


def test_cached_geocode_negative_result(tmp_db):
    db.save_geocode("unknown", None, None)
    assert db.cached_geocode("unknown") is db.GEOCODE_MISS


# ── posted_within (post-time cooldown) ────────────────────────────────────────

def test_posted_within_false_when_nothing_posted(tmp_db, sample_incident):
    db.save_incident(sample_incident)
    assert db.posted_within(5, sample_incident["type"]) is False


def test_posted_within_true_after_marking_posted(tmp_db, sample_incident):
    incident_id = db.save_incident(sample_incident)
    db.mark_posted(incident_id, "fb_123")
    assert db.posted_within(5, sample_incident["type"]) is True


def test_posted_within_ignores_other_types(tmp_db, sample_incident):
    incident_id = db.save_incident(sample_incident)
    db.mark_posted(incident_id, "fb_123")
    assert db.posted_within(5, "Some Other Type") is False


def test_posted_within_ignores_old_posts(tmp_db, sample_incident):
    """An incident posted outside the window must not block a new one."""
    incident_id = db.save_incident(sample_incident)
    db.mark_posted(incident_id, "fb_123")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE incidents SET posted_at = datetime('now', '-30 minutes') WHERE id = ?",
            (incident_id,),
        )
    assert db.posted_within(5, sample_incident["type"]) is False


def test_posted_within_uses_post_time_not_creation_time(tmp_db, sample_incident):
    """The old cooldown filtered on created_at, so a backlog drained with no
    cooldown at all: rows created long ago matched nothing."""
    incident_id = db.save_incident(sample_incident)
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE incidents SET created_at = datetime('now', '-6 hours') WHERE id = ?",
            (incident_id,),
        )
    db.mark_posted(incident_id, "fb_123")  # posted right now, created hours ago
    assert db.posted_within(5, sample_incident["type"]) is True
