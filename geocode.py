"""
Best-effort geocoding of free-text dispatch locations via OpenStreetMap Nominatim.

Dispatch location text is often vague ("Highway with semi", "unknown", a bare
street name with no city) so most lookups are expected to miss — callers should
treat a None return as normal, not an error, and the dashboard must disclose
that not every incident has a mappable location.
"""
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import db
from config import COMMUNITY_NAME

log = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "sdr-scanner-dashboard/1.0 (community incident map)"

# Nominatim's usage policy caps unauthenticated use at 1 request/second.
_RATE_LIMIT_SECONDS = 1.1
_rate_lock = threading.Lock()
_LAST_REQUEST = 0.0

_UNRESOLVABLE = re.compile(r"^\s*(unknown|none|n/?a|—|-)?\s*$", re.IGNORECASE)


def geocode(location: str | None) -> tuple[float, float] | None:
    """Return (lat, lon) for a location string, or None if it can't be resolved."""
    if not location or _UNRESOLVABLE.match(location):
        return None

    cached = db.cached_geocode(location)
    if cached is db.GEOCODE_MISS:
        return None
    if cached is not None:
        return cached

    result = _lookup(location)
    lat, lon = result if result else (None, None)
    db.save_geocode(location, lat, lon)
    return result


def _lookup(location: str) -> tuple[float, float] | None:
    # Claude's geo_location is often already a full "street, city, state" query —
    # only append the community name when it isn't already part of the string.
    if COMMUNITY_NAME.lower() in location.lower():
        query = location
    else:
        query = f"{location}, {COMMUNITY_NAME}"
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    })

    with _rate_lock:
        global _LAST_REQUEST  # pylint: disable=global-statement
        wait = _RATE_LIMIT_SECONDS - (time.monotonic() - _LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(
                f"{_NOMINATIM_URL}?{params}",
                headers={"User-Agent": _USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — fixed HTTPS host, no user redirection
                results = json.loads(resp.read())
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.warning("Geocode lookup failed for %r: %s", location, exc)
            return None
        finally:
            _LAST_REQUEST = time.monotonic()

    if not results:
        return None
    try:
        return (float(results[0]["lat"]), float(results[0]["lon"]))
    except (KeyError, ValueError, TypeError):
        return None
