"""
Posting layer — three backends selectable via POST_BACKEND env var:
  queue   — write to local JSON queue file (default, safe for testing)
  text    — append plain-text log to TEXT_OUTPUT_FILE (default: incidents.txt)
  zapier  — POST incident JSON to a Zapier Catch Hook webhook URL
  print   — stdout only (debug)
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import ZAPIER_WEBHOOK_URL
from config import QUEUE_FILE, TEXT_OUTPUT_FILE  # module-level so tests can patch

log = logging.getLogger(__name__)

POST_BACKEND = os.getenv("POST_BACKEND", "queue")


def post_incident(incident: dict) -> str:
    """Post incident; returns post_id string (or empty on queue/text/print)."""
    backend = POST_BACKEND.lower()

    if backend == "zapier":
        return _post_zapier(incident)
    elif backend == "text":
        return _post_text(incident)
    elif backend == "print":
        print("\n" + "=" * 60)
        print(incident["summary"])
        print("=" * 60 + "\n")
        return ""
    else:
        return _post_queue(incident)


def _post_zapier(incident: dict) -> str:
    if not ZAPIER_WEBHOOK_URL:
        log.error("ZAPIER_WEBHOOK_URL must be set for zapier backend")
        return ""

    payload = {
        "summary": incident["summary"],
        "type": incident.get("type"),
        "location": incident.get("location"),
        "time": incident.get("time"),
        "posted_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = requests.post(ZAPIER_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Sent to Zapier webhook: %s", incident["summary"][:80])
        return ""
    except requests.RequestException as exc:
        log.error("Zapier webhook failed: %s", exc)
        raise


def _post_text(incident: dict) -> str:
    path = Path(TEXT_OUTPUT_FILE)
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        f"[{ts}]",
    ]
    if incident.get("type"):
        lines.append(f"Type: {incident['type']}")
    if incident.get("location"):
        lines.append(f"Location: {incident['location']}")
    lines.append(incident["summary"])
    lines.append("-" * 60)
    with path.open("a") as f:
        f.write("\n".join(lines) + "\n\n")
    log.info("Wrote to text file: %s", incident["summary"][:80])
    return ""


def _post_queue(incident: dict) -> str:
    path = Path(QUEUE_FILE)
    queue = []
    if path.exists():
        try:
            queue = json.loads(path.read_text())
        except Exception:
            queue = []
    entry = {
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "summary": incident["summary"],
        "type": incident.get("type"),
        "location": incident.get("location"),
        "time": incident.get("time"),
    }
    queue.append(entry)
    path.write_text(json.dumps(queue, indent=2))
    log.info("Queued post: %s", entry["summary"][:80])
    return ""
