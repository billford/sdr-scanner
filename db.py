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
                post_id TEXT
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                transcript_hash TEXT NOT NULL UNIQUE,
                had_incident INTEGER DEFAULT 0
            );
        """)


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
            "raw_transcript, transcript_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _now(),
                incident.get("time"),
                incident.get("type"),
                incident.get("location"),
                incident["summary"],
                incident["raw_transcript"],
                incident["transcript_hash"],
            ),
        )
        return cur.lastrowid or None


def mark_posted(incident_id: int, post_id: str = ""):
    """Mark an incident as posted and store the post ID."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE incidents SET posted = 1, post_id = ? WHERE id = ?",
            (post_id, incident_id),
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
