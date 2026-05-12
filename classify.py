"""
Two-stage local incident classifier:
  1. keyword_check()   — fast regex pre-filter, no model involved
  2. local_classify()  — Ollama LLM for structured YES/NO + basic summary

Returns None (no incident) or a basic incident dict for claude_polish() to refine.
"""
import json
import logging
import re
import urllib.request
import urllib.error

import db
from config import OLLAMA_MODEL, OLLAMA_URL

log = logging.getLogger(__name__)

# ── Stage 1: keyword pre-filter ───────────────────────────────────────────────

_INCIDENT_PATTERNS = re.compile(
    r"\b("
    # Fire
    r"structure fire|working fire|house fire|car fire|vehicle fire|brush fire|"
    r"fire at|fire on|reported fire|smoke showing|flames|"
    # Medical
    r"medical|ems|cardiac|unconscious|not breathing|difficulty breath|"
    r"overdose|trauma|chest pain|fall victim|seizure|unresponsive|"
    # Accident / traffic
    r"mva|motor vehicle|vehicle accident|traffic accident|10-50|collision|"
    r"crash|vehicle into|"
    # Crime / safety
    r"shots fired|shooting|stabbing|assault|robbery|burglary|break-?in|"
    r"domestic|fight|weapon|armed subject|fleeing|pursuit|"
    # Hazard
    r"gas leak|hazmat|power line|water main|flooding|downed wire|"
    # Dispatch triggers
    r"respond to|responding to|units respond|all units"
    r")\b",
    re.IGNORECASE,
)

_NOISE_PATTERNS = re.compile(
    r"^[\s\d\-\.]*$|"                          # digits/punctuation only
    r"\b(10-4|copy that|affirmative|negative|roger|stand by)\b",
    re.IGNORECASE,
)


def keyword_check(transcript: str) -> bool:
    """Return True if the transcript contains incident-relevant keywords."""
    if not transcript or len(transcript.strip()) < 10:
        return False
    if _NOISE_PATTERNS.search(transcript.strip()):
        return False
    return bool(_INCIDENT_PATTERNS.search(transcript))


# ── Stage 2: local Ollama classification ──────────────────────────────────────

_CLASSIFY_PROMPT = """\
You are classifying emergency dispatch radio transcripts for a community scanner page.

Respond with EXACTLY one of:
  NO_INCIDENT
  INCIDENT: <type> | <location or "unknown"> | <one sentence description>

Rules:
- NO_INCIDENT for: routine status checks, unit availability, 10-4 confirmations, weather, test calls
- INCIDENT for: fires, medical emergencies, accidents, crimes, hazards, anything dispatched to a scene
- Never include individual names
- Keep description to one sentence, plain English
- Do not add any other text

Transcript: {transcript}"""


def local_classify(transcript: str) -> dict | None:
    """
    Ask local Ollama model to classify the transcript.
    Returns incident dict or None.
    """
    prompt = _CLASSIFY_PROMPT.format(transcript=transcript.strip())
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 80},
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        response_text = result.get("response", "").strip()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.error("Ollama classify error: %s", exc)
        return None

    log.debug("Ollama response: %s", response_text)

    if response_text.upper().startswith("NO_INCIDENT"):
        return None

    if response_text.upper().startswith("INCIDENT:"):
        return _parse_incident_line(response_text, transcript)

    # Ambiguous — treat as no incident to avoid noise
    log.debug("Ambiguous Ollama response, skipping: %s", response_text[:80])
    return None


def _parse_incident_line(line: str, raw_transcript: str) -> dict:
    # Format: INCIDENT: <type> | <location> | <description>
    body = re.sub(r"^INCIDENT:\s*", "", line, flags=re.IGNORECASE).strip()
    parts = [p.strip() for p in body.split("|")]
    incident_type = parts[0] if len(parts) > 0 else None
    location = parts[1] if len(parts) > 1 else None
    description = parts[2] if len(parts) > 2 else body

    return {
        "time": None,  # claude_polish fills this in
        "type": incident_type,
        "location": location,
        "local_summary": description,
        "summary": description,           # placeholder, overwritten by polish
        "raw_transcript": raw_transcript,
        "transcript_hash": db.transcript_hash(raw_transcript),
    }
