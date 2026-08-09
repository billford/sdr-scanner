"""
Decide whether an incident should go to Facebook at all.

Masking words defeats keyword matching; Meta's moderation reads meaning. A post
reading "a male was reported attempting to jump in front of RTA buses" contains
no flagged word and was still actioned — no stem list can catch that, because
the individual words are innocuous.

So the judgement happens twice, and either one can withhold a post:

1. Claude returns a publish verdict as part of the polish call it already makes
   (summarize.py), which is the part that can read context.
2. A small rule here catches the clearest self-harm cases, so a Claude outage
   doesn't silently reopen the gate.

Withheld incidents are still stored and still appear on the dashboard — this
only governs what gets published to Facebook.
"""
import os
import re

# Deliberately narrow: unambiguous self-harm intent, not every mention of a
# mental health call. This is a backstop for when the model verdict is missing,
# not the primary filter.
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

# Incident types that are about a person in crisis rather than a public event.
_CRISIS_TYPE = re.compile(r"\b(suicid\w*|self[- ]harm\w*|person in crisis|crisis)\b", re.IGNORECASE)

# Set MODERATION_FAIL_OPEN=1 to publish when Claude gave no verdict and no rule
# matched — the default already does that; this exists to disable the rules too.
FAIL_OPEN = os.getenv("MODERATION_FAIL_OPEN", "").strip() in ("1", "true", "yes")


def block_reason(incident: dict) -> str | None:
    """Return why this incident must not be posted, or None to allow it."""
    if incident.get("publishable") is False:
        return incident.get("publish_note") or "model judged it unpublishable"

    if FAIL_OPEN:
        return None

    # Runs even when the model said YES: cheap, and the model can be wrong about
    # the one category that actually costs us.
    text = f"{incident.get('type') or ''} {incident.get('summary') or ''}"
    if _SELF_HARM.search(text):
        return "self-harm content (rule)"
    if _CRISIS_TYPE.search(incident.get("type") or ""):
        return "person-in-crisis incident type (rule)"
    return None
