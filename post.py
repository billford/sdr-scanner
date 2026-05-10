"""
Posting layer — four backends selectable via POST_BACKEND env var:
  queue    — write to local JSON queue file (default, safe for testing)
  facebook — post directly via Graph API
  text     — append plain-text log to TEXT_OUTPUT_FILE (default: incidents.txt)
  print    — stdout only (debug)
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import FB_ACCESS_TOKEN, FB_PAGE_ID
from config import QUEUE_FILE, TEXT_OUTPUT_FILE  # module-level so tests can patch

log = logging.getLogger(__name__)

POST_BACKEND = os.getenv("POST_BACKEND", "queue")
GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def post_incident(incident: dict) -> str:
    """Post incident; returns post_id string (or empty on queue/print)."""
    message = incident["summary"]
    backend = POST_BACKEND.lower()

    if backend == "facebook":
        return _post_facebook(message)
    elif backend == "text":
        return _post_text(incident)
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

    try:
        resp = requests.post(
            f"{GRAPH_BASE}/{FB_PAGE_ID}/feed",
            json={"message": message, "access_token": FB_ACCESS_TOKEN},
            timeout=15,
        )
        _check_graph_error(resp)
        post_id = resp.json().get("id", "")
        log.info("Posted to Facebook: %s", post_id)
        return post_id
    except FacebookTokenError:
        log.error("Facebook token is invalid or expired — run: python check_token.py")
        raise
    except requests.RequestException as exc:
        log.error("Facebook post failed (network): %s", exc)
        raise


def _check_graph_error(resp: requests.Response):
    """Raise a typed exception for known Graph API error codes."""
    if resp.ok:
        return
    try:
        err = resp.json().get("error", {})
    except Exception:
        resp.raise_for_status()
        return

    code = err.get("code")
    message = err.get("message", "unknown error")

    # Token errors: 190 (invalid/expired), 102 (session expired)
    if code in (102, 190):
        raise FacebookTokenError(f"Token error ({code}): {message}")

    # Permission errors
    if code == 200:
        raise FacebookPermissionError(f"Permission denied ({code}): {message}")

    resp.raise_for_status()


class FacebookTokenError(Exception):
    pass


class FacebookPermissionError(Exception):
    pass


def get_token_info() -> dict:
    """
    Inspect the current access token via the Graph debug endpoint.
    Returns dict with keys: valid, expires_at, scopes, error.
    """
    if not FB_ACCESS_TOKEN:
        return {"valid": False, "error": "FB_ACCESS_TOKEN not set"}

    try:
        resp = requests.get(
            f"{GRAPH_BASE}/debug_token",
            params={"input_token": FB_ACCESS_TOKEN, "access_token": FB_ACCESS_TOKEN},
            timeout=10,
        )
        data = resp.json().get("data", {})
        expires_at = data.get("expires_at")
        return {
            "valid": data.get("is_valid", False),
            "expires_at": datetime.fromtimestamp(expires_at).isoformat() if expires_at else "never",
            "scopes": data.get("scopes", []),
            "app_id": data.get("app_id"),
            "error": data.get("error", {}).get("message"),
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


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
