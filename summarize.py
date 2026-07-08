"""
Claude polish step — only called when Ollama has already confirmed a real incident.
Takes the local_summary from classify.py and produces a clean, post-ready summary,
plus a geocoding-ready location string pulled from whatever the dispatcher actually
said ("West 100th Street area", "the Cleveland area", cross streets, etc) rather
than Ollama's rougher local extraction.
"""
import logging
import re
from datetime import datetime
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, COMMUNITY_DESC

log = logging.getLogger(__name__)

_POLISH_PROMPT = """\
You are writing brief, factual posts for a local community scanner page \
covering {community_desc}.

Given this draft incident summary and the original dispatch transcript, produce \
two things.

1. A clean, concise post.
Format: [HH:MM] [Incident type] — [Location] — [1–2 sentence description]

2. A geocoding-ready location: the most specific place actually mentioned in the \
transcript, written the way you'd type it into a map search (e.g. "West 100th \
Street, Cleveland, OH" or "St Clair Avenue and E 55th Street, Cleveland, OH"). \
Dispatchers describe locations loosely ("west 100th street area", "near the \
Cleveland area", a bare cross street with no house number) — pull out whatever \
real street, intersection, or neighborhood name is there even if it's imprecise. \
Only write NONE if nothing more specific than the general listening area is \
mentioned, or the only "location" given is an internal dispatch code/zone with \
no public meaning.

Rules for the post:
- Factual and neutral, like a local news brief
- Never include individual names
- Never speculate beyond what was said
- Translate 10-codes to plain English
- If no time was mentioned use {time_now}

Respond in exactly this format and nothing else:
POST: <formatted post>
GEO: <geocoding-ready location, or NONE>"""

_POST_LINE = re.compile(r"^POST:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_GEO_LINE = re.compile(r"^GEO:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

_CLIENT: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _CLIENT  # pylint: disable=global-statement
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    return _CLIENT


def polish(incident: dict) -> dict:
    """
    Refine a locally-classified incident into a polished post.
    Returns the incident dict with updated 'summary' field.
    Falls back to local_summary if API call fails.
    """
    if not ANTHROPIC_API_KEY:
        log.warning("No ANTHROPIC_API_KEY — using local summary as-is")
        return incident

    time_now = datetime.now().strftime("%H:%M")
    user_content = (
        f"Draft summary: {incident.get('local_summary', '')}\n\n"
        f"Original transcript: {incident['raw_transcript']}"
    )

    try:
        client = _get_client()
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            system=_POLISH_PROMPT.format(community_desc=COMMUNITY_DESC, time_now=time_now),
            messages=[{"role": "user", "content": user_content}],
        )
        response_text = msg.content[0].text.strip()
        incident = dict(incident)

        post_match = _POST_LINE.search(response_text)
        geo_match = _GEO_LINE.search(response_text)
        incident["summary"] = post_match.group(1).strip() if post_match else response_text

        if geo_match:
            geo = geo_match.group(1).strip()
            if geo.upper() != "NONE":
                incident["geo_location"] = geo

        log.info("Polished: %s", incident["summary"][:120])
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.error("Claude polish failed: %s — using local summary", exc)

    return incident
