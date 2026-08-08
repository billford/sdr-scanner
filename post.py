"""
Posting layer — backends selectable via POST_BACKEND env var:
  queue    — write to local JSON queue file (default, safe for testing)
  text     — append plain-text log to TEXT_OUTPUT_FILE (default: incidents.txt)
  facebook — post directly to a Facebook Page via the Graph API (summaries are
             run through sanitize.soften first to mask moderation-bait words)
  print    — stdout only (debug)
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN  # module-level so tests can patch
from config import QUEUE_FILE, TEXT_OUTPUT_FILE  # module-level so tests can patch
from sanitize import soften

log = logging.getLogger(__name__)

POST_BACKEND = os.getenv("POST_BACKEND", "queue")


class PostFailed(requests.RequestException):
    """A post attempt failed.

    Subclasses RequestException so existing callers keep catching it.

    maybe_delivered — the request reached Facebook and the failure came after,
        so it may already have created the post. The Graph API's /feed edge has
        no idempotency key, which means a retry can't be deduplicated and would
        publish a second copy.
    retryable — we know nothing was created, so trying again later is safe.
    """

    def __init__(self, message: str, *, maybe_delivered: bool, retryable: bool):
        super().__init__(message)
        self.maybe_delivered = maybe_delivered
        self.retryable = retryable


def post_incident(incident: dict) -> str:
    """Post incident; returns post_id string (or empty on queue/text/print)."""
    backend = POST_BACKEND.lower()

    if backend == "facebook":
        return _post_facebook(incident)
    if backend == "text":
        return _post_text(incident)
    if backend == "print":
        print("\n" + "=" * 60)
        print(incident["summary"])
        print("=" * 60 + "\n")
        return ""
    return _post_queue(incident)


def _post_facebook(incident: dict) -> str:
    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        log.error("FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN must be set for facebook backend")
        return ""

    url = f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/feed"
    message = soften(incident["summary"])
    try:
        resp = requests.post(
            url,
            data={"message": message, "access_token": FB_PAGE_ACCESS_TOKEN},
            timeout=15,
        )
    except requests.ConnectionError as exc:
        # Never reached Facebook, so nothing was created — safe to try again.
        log.error("Facebook post failed to connect: %s", exc)
        raise PostFailed(str(exc), maybe_delivered=False, retryable=True) from exc
    except requests.Timeout as exc:
        # The request went out; we just never saw the reply. Facebook has very
        # likely created the post already, and retrying this is what published
        # the same incident two and three times over.
        log.error("Facebook post timed out (may have been delivered): %s", exc)
        raise PostFailed(str(exc), maybe_delivered=True, retryable=False) from exc
    except requests.RequestException as exc:
        log.error("Facebook post failed: %s", exc)
        raise PostFailed(str(exc), maybe_delivered=True, retryable=False) from exc

    if resp.status_code >= 500:
        # Facebook may have accepted the write before failing to respond.
        log.error("Facebook post got server error %s", resp.status_code)
        raise PostFailed(f"server error {resp.status_code}",
                         maybe_delivered=True, retryable=False)
    if resp.status_code >= 400:
        # Rejected outright — nothing created, but the same content will be
        # rejected again, so there is no point retrying it either.
        body = resp.text[:200]
        log.error("Facebook rejected post (%s): %s", resp.status_code, body)
        raise PostFailed(f"rejected {resp.status_code}: {body}",
                         maybe_delivered=False, retryable=False)

    post_id = resp.json().get("id", "")
    log.info("Posted to Facebook (%s): %s", post_id, message[:80])
    return post_id


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
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
    log.info("Wrote to text file: %s", incident["summary"][:80])
    return ""


def _post_queue(incident: dict) -> str:
    path = Path(QUEUE_FILE)
    queue = []
    if path.exists():
        try:
            queue = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # pylint: disable=broad-exception-caught
            queue = []
    entry = {
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "summary": incident["summary"],
        "type": incident.get("type"),
        "location": incident.get("location"),
        "time": incident.get("time"),
    }
    queue.append(entry)
    path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    log.info("Queued post: %s", entry["summary"][:80])
    return ""
