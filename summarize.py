"""
Claude polish step — only called when Ollama has already confirmed a real incident.
Takes the local_summary from classify.py and produces a clean Facebook-ready post.
"""
import logging
from datetime import datetime
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, COMMUNITY_DESC

log = logging.getLogger(__name__)

_POLISH_PROMPT = """\
You are writing brief, factual posts for a local community scanner Facebook page \
covering {community_desc}.

Given this draft incident summary and the original dispatch transcript, write a \
clean, Facebook-ready post.

Format: [HH:MM] [Incident type] — [Location] — [1–2 sentence description]

Rules:
- Factual and neutral, like a local news brief
- Never include individual names
- Never speculate beyond what was said
- Translate 10-codes to plain English
- If no time was mentioned use {time_now}
- Return only the formatted post, no other text"""

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    return _client


def polish(incident: dict) -> dict:
    """
    Refine a locally-classified incident into a polished Facebook post.
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
        polished_text = msg.content[0].text.strip()
        incident = dict(incident)
        incident["summary"] = polished_text
        log.info("Polished: %s", polished_text[:120])
    except Exception as exc:
        log.error("Claude polish failed: %s — using local summary", exc)

    return incident
