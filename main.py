#!/usr/bin/env python3
"""
Chagrin Valley Scanner Page — main loop.

Pipeline:
  stream → whisper → keyword_check (free) → ollama_classify (local)
         → claude_polish (API, only on real incidents) → post/queue
"""
import logging
import signal

import db
import capture
import transcribe
import classify
import summarize
import post
from config import POST_COOLDOWN_MINUTES, BROADCASTIFY_FEED_URLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

_RUNNING = True


def _handle_signal(_sig, _frame):
    global _RUNNING  # pylint: disable=global-statement
    log.info("Shutting down…")
    _RUNNING = False


def _cooldown_ok(incident_type: str | None) -> bool:
    recent = db.recent_incidents(minutes=POST_COOLDOWN_MINUTES)
    return not any(
        r["posted"] and r["incident_type"] == incident_type
        for r in recent
    )


def _flush_unposted() -> None:
    """Post any incidents that were held back by cooldown and are now clear."""
    for row in db.unposted_incidents():
        if _cooldown_ok(row.get("incident_type")):
            log.info("Cooldown cleared — posting held incident #%d: %s", row["id"], row["summary"][:80])
            incident = {
                "summary": row["summary"],
                "type": row["incident_type"],
                "location": row["location"],
                "time": row["incident_time"],
            }
            post_id = post.post_incident(incident)
            db.mark_posted(row["id"], post_id)


def main():
    """Run the scanner pipeline until interrupted."""
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    db.init_db()
    log.info("Scanner monitor started. Backend: %s | Feeds: %s", post.POST_BACKEND, BROADCASTIFY_FEED_URLS)

    chunk_count = 0
    for audio_chunk in capture.stream_chunks_multi(BROADCASTIFY_FEED_URLS):
        if not _RUNNING:
            break

        _flush_unposted()
        chunk_count += 1

        if capture.is_silent(audio_chunk):
            log.debug("Chunk #%d: silent, skipping.", chunk_count)
            continue

        transcript = transcribe.transcribe(audio_chunk)
        if not transcript:
            log.debug("Chunk #%d: empty transcript.", chunk_count)
            continue

        log.info("Chunk #%d: %s", chunk_count, transcript[:100])

        h = db.transcript_hash(transcript)
        if db.chunk_seen(h):
            log.debug("Duplicate chunk, skipping.")
            continue

        # Stage 1: keyword pre-filter (free)
        if not classify.keyword_check(transcript):
            log.info("No incident keywords — skipping Ollama.")
            db.log_chunk(h, had_incident=False)
            continue

        # Stage 2: local Ollama classification (free)
        incident = classify.local_classify(transcript)
        db.log_chunk(h, had_incident=incident is not None)

        if incident is None:
            log.info("Ollama: NO_INCIDENT.")
            continue

        log.info("Ollama confirmed incident: %s", incident.get("local_summary", "")[:80])

        # Stage 3: Claude polish (API — only hits here on real incidents)
        incident = summarize.polish(incident)

        incident_id = db.save_incident(incident)
        if incident_id is None:
            log.info("Duplicate incident in DB.")
            continue

        if _cooldown_ok(incident.get("type")):
            post_id = post.post_incident(incident)
            db.mark_posted(incident_id, post_id)
        else:
            log.info("Cooldown active — saved but not posted.")


if __name__ == "__main__":
    main()
