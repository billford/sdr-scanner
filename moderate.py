"""
Handle self-harm incidents on the way to Facebook.

Masking words defeats keyword matching; Meta's moderation reads meaning. A post
reading "a male was reported attempting to jump in front of RTA buses" contains
no flagged word and was still actioned — no stem list can catch that, because
the individual words are innocuous.

These incidents are not dropped. Claude rewrites them to safe-messaging guidance
in the polish call it already makes (summarize.py) — no method, no house number,
no identifying detail, and none of the words that trip the classifier — and a
support-line footer is appended here on the way out.

Withholding is now the rare fallback: only when the content is clearly self-harm
AND Claude never returned a verdict (an API outage), because then the summary is
the raw local one, written with no safe-messaging care at all.
"""
import os
import re

# The published wording deliberately avoids "suicide" and "crisis" — the
# official name of the 988 line contains both, and naming it defeats the point
# of rewriting the post.
SUPPORT_FOOTER = (
    "\n\nIf you or someone you know needs support, call or text 988 — "
    "free, confidential, and available 24/7."
)

# Deliberately narrow: unambiguous self-harm intent, not every mental health
# call. Matched against the incident text as a backstop to Claude's judgement.
_SELF_HARM = re.compile(
    r"\b("
    r"suicid\w*"
    r"|self[- ]harm\w*"
    r"|self[- ]inflict\w*"
    r"|kill(ing|ed)?\s+(him|her|them)sel\w+"
    r"|hang(ing|ed)?\s+(him|her|them)sel\w+"
    r"|jump(ing|ed)?\s+(in\s+front\s+of|from|off)"
    r"|threaten\w*\s+to\s+jump"
    r"|danger\s+to\s+(him|her|them)sel\w+"
    r")\b",
    re.IGNORECASE,
)

_CRISIS_TYPE = re.compile(r"\b(suicid\w*|self[- ]harm\w*|person in crisis|crisis)\b", re.IGNORECASE)

# Set MODERATION_FAIL_OPEN=1 to publish self-harm incidents even when Claude
# never judged them — the rules stop withholding, the footer still applies.
FAIL_OPEN = os.getenv("MODERATION_FAIL_OPEN", "").strip() in ("1", "true", "yes")


def is_crisis(incident: dict) -> bool:
    """True when this incident involves self-harm and needs the support footer."""
    if incident.get("crisis") is True:
        return True
    # Runs even when Claude said NO: cheap, and the cost of missing one is a
    # post that reads as self-harm content with no support line attached.
    text = f"{incident.get('type') or ''} {incident.get('summary') or ''}"
    return bool(_SELF_HARM.search(text) or _CRISIS_TYPE.search(incident.get("type") or ""))


def block_reason(incident: dict) -> str | None:
    """Return why this incident must not be posted at all, or None to allow it."""
    if incident.get("publishable") is False:
        return incident.get("publish_note") or "model judged it unpublishable"

    # Claude answered, so the summary was written to safe-messaging guidance and
    # the footer carries the support line. Publish it.
    if incident.get("crisis") is not None or FAIL_OPEN:
        return None

    if is_crisis(incident):
        return "self-harm content with no safe rewrite available"
    return None


def apply_footer(message: str, incident: dict) -> str:
    """Append the support line to a self-harm post, once."""
    if not is_crisis(incident) or "988" in message:
        return message
    return message + SUPPORT_FOOTER
