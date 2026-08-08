"""SQLite persistence — incident log and chunk dedup."""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    """Context manager: open, yield, commit/rollback, and always close."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                incident_time TEXT,
                incident_type TEXT,
                location TEXT,
                summary TEXT NOT NULL,
                raw_transcript TEXT NOT NULL,
                transcript_hash TEXT NOT NULL UNIQUE,
                posted INTEGER DEFAULT 0,
                post_id TEXT,
                lat REAL,
                lon REAL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                transcript_hash TEXT NOT NULL UNIQUE,
                had_incident INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS geocode_cache (
                location TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                looked_up_at TEXT NOT NULL
            );
        """)
        _add_column_if_missing(conn, "incidents", "lat", "REAL")
        _add_column_if_missing(conn, "incidents", "lon", "REAL")
        _add_column_if_missing(conn, "incidents", "posted_at", "TEXT")


def _add_column_if_missing(conn, table: str, column: str, coltype: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def transcript_hash(text: str) -> str:
    """Return a stable SHA-256 hex digest for a transcript string."""
    return hashlib.sha256(text.strip().encode()).hexdigest()


def chunk_seen(h: str) -> bool:
    """Return True if this transcript hash has been processed before."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM chunks WHERE transcript_hash = ?", (h,)
        ).fetchone()
        return row is not None


def log_chunk(h: str, had_incident: bool):
    """Record a processed chunk hash; silently ignores duplicates."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO chunks "
            "(captured_at, transcript_hash, had_incident) VALUES (?, ?, ?)",
            (_now(), h, int(had_incident)),
        )


def save_incident(incident: dict) -> int:
    """Save incident dict; returns row id. Ignores duplicate transcripts."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO incidents "
            "(created_at, incident_time, incident_type, location, summary, "
            "raw_transcript, transcript_hash, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _now(),
                incident.get("time"),
                incident.get("type"),
                incident.get("location"),
                incident["summary"],
                incident["raw_transcript"],
                incident["transcript_hash"],
                incident.get("lat"),
                incident.get("lon"),
            ),
        )
        return cur.lastrowid or None


def mark_posted(incident_id: int, post_id: str = ""):
    """Mark an incident as posted and store the post ID.

    posted_at is stamped by SQLite rather than Python so it matches the format
    datetime('now') produces — posted_within compares the two as strings.
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE incidents SET posted = 1, post_id = ?, posted_at = datetime('now') "
            "WHERE id = ?",
            (post_id, incident_id),
        )


def posted_within(minutes: int, incident_type: str | None) -> bool:
    """True if an incident of this type was actually posted in the last N minutes.

    Keyed on posted_at rather than created_at. The cooldown used to filter
    recent_incidents() by created_at, which silently did nothing whenever the
    unposted queue drained a backlog: every held row was created well outside
    the window, so nothing matched and same-type incidents posted back to back.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM incidents "
            "WHERE posted = 1 AND posted_at IS NOT NULL AND incident_type IS ? "
            "AND posted_at > datetime('now', ? || ' minutes') LIMIT 1",
            (incident_type, f"-{minutes}"),
        ).fetchone()
    return row is not None


def unposted_incidents() -> list:
    """Return all incidents saved but not yet posted, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM incidents WHERE posted = 0 ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


GEOCODE_MISS = object()


def cached_geocode(location: str):
    """
    Return a cached (lat, lon) for a location string, None if never looked up,
    or GEOCODE_MISS if it was looked up before but no coordinates were found.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT lat, lon FROM geocode_cache WHERE location = ?", (location,)
        ).fetchone()
        if row is None:
            return None
        if row["lat"] is None:
            return GEOCODE_MISS
        return (row["lat"], row["lon"])


def save_geocode(location: str, lat: float | None, lon: float | None) -> None:
    """Cache a geocoding result (lat/lon None records a confirmed miss)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache (location, lat, lon, looked_up_at) "
            "VALUES (?, ?, ?, ?)",
            (location, lat, lon, _now()),
        )


def recent_incidents(minutes: int = 30) -> list:
    """Return incidents created within the last N minutes."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM incidents "
            "WHERE created_at > datetime('now', ? || ' minutes') "
            "ORDER BY created_at DESC",
            (f"-{minutes}",),
        ).fetchall()
        return [dict(r) for r in rows]
