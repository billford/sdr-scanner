"""
Posting layer — three backends selectable via POST_BACKEND env var:
  queue   — write to local JSON queue file (default, safe for testing)
  facebook — post directly via Graph API
  print    — stdout only (debug)
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

from config import FB_ACCESS_TOKEN, FB_PAGE_ID
from config import QUEUE_FILE  # module-level so tests can patch post.QUEUE_FILE

log = logging.getLogger(__name__)

POST_BACKEND = os.getenv("POST_BACKEND", "queue")


def post_incident(incident: dict) -> str:
    """Post incident; returns post_id string (or empty on queue/print)."""
    message = incident["summary"]
    backend = POST_BACKEND.lower()

    if backend == "facebook":
        return _post_facebook(message)
    elif backend == "print":
        print("\n" + "=" * 60)
        print(message)
        print("=" * 60 + "\n")
        return ""
    else:
        return _post_queue(incident)


def _post_facebook(message: str) -> str:
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        log.error("FB_PAGE_ID and FB_ACCESS_TOKEN must be set for facebook backend")
        return ""
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
    resp = requests.post(url, data={"message": message, "access_token": FB_ACCESS_TOKEN}, timeout=15)
    resp.raise_for_status()
    post_id = resp.json().get("id", "")
    log.info("Posted to Facebook: %s", post_id)
    return post_id


def _post_queue(incident: dict) -> str:
    path = Path(QUEUE_FILE)
    queue = []
    if path.exists():
        try:
            queue = json.loads(path.read_text())
        except Exception:
            queue = []
    entry = {
        "queued_at": datetime.utcnow().isoformat(),
        "summary": incident["summary"],
        "type": incident.get("type"),
        "location": incident.get("location"),
        "time": incident.get("time"),
    }
    queue.append(entry)
    path.write_text(json.dumps(queue, indent=2))
    log.info("Queued post: %s", entry["summary"][:80])
    return ""
