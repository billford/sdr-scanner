"""
Soften words Facebook's moderation dislikes before they hit the Graph API.

Scanner traffic is, by nature, full of the exact vocabulary Meta demotes or
blocks outright ("shooting", "suicide", "overdose"). Rather than drop those
incidents we mask the middle of the offending word — "shooting" becomes
"s******g" — which stays readable to a human while dodging keyword matching.

Only the Facebook backend uses this; the queue/text/print backends keep the
original wording.
"""
import os
import re

# Stems, not full words — each matches the whole word it starts, so "kill"
# covers killed/killing/kills and "shoot" covers shooter/shooting.
SENSITIVE_STEMS = [
    "suicid",
    "kill",
    "murder",
    "homicid",
    "shoot",
    "shot",
    "gunshot",
    "gunman",
    "gunmen",
    "stab",
    "rape",
    "rapist",
    "assault",
    "molest",
    "abduct",
    "kidnap",
    "hostage",
    "arson",
    "bomb",
    "explosiv",
    "overdos",
    "heroin",
    "fentanyl",
    "cocaine",
    "meth",
    "narcotic",
    "dead",
    "death",
    "died",
    "fatal",
    "corpse",
    "hang",
    "drown",
    "strangl",
    "beat",
    "attack",
    "violen",
    "weapon",
    "blood",
    "wound",
    "sever",
    "trauma",
]

# Comma-separated extra stems, e.g. SOFTEN_EXTRA_WORDS=knife,machete
_EXTRA = [w.strip().lower() for w in os.getenv("SOFTEN_EXTRA_WORDS", "").split(",") if w.strip()]
# Comma-separated stems to leave alone, e.g. SOFTEN_SKIP_WORDS=beat,sever
_SKIP = {w.strip().lower() for w in os.getenv("SOFTEN_SKIP_WORDS", "").split(",") if w.strip()}

_STEMS = [s for s in SENSITIVE_STEMS + _EXTRA if s not in _SKIP]

# Longest stems first so "gunshot" wins over "shot" at the same position.
_PATTERN = re.compile(
    r"\b(" + "|".join(sorted((re.escape(s) for s in _STEMS), key=len, reverse=True)) + r")[a-z']*\b",
    re.IGNORECASE,
) if _STEMS else None


def _mask(word: str) -> str:
    """k*ll — keep the first and last character, star everything between.

    Short words get a single star instead of a run of them: starring every
    interior letter of a four-letter word can spell something worse than the
    word being hidden — "shot" became "s**t" on a live post.
    """
    if len(word) < 3:
        return word
    if len(word) <= 4:
        return word[0] + "*" + word[2:]
    return word[0] + "*" * (len(word) - 2) + word[-1]


def soften(text: str) -> str:
    """Return text with Facebook-hostile words masked."""
    if not text or _PATTERN is None:
        return text
    return _PATTERN.sub(lambda m: _mask(m.group(0)), text)
