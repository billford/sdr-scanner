"""Central configuration — reads from environment and .env file."""
import os
from pathlib import Path

# Load .env if present (key=value, one per line, # comments ok)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

COMMUNITY_NAME = os.getenv("COMMUNITY_NAME", "Cleveland")
COMMUNITY_DESC = os.getenv(
    "COMMUNITY_DESC",
    "Cleveland and surrounding Cuyahoga County communities",
)

# Bounding box (left,top,right,bottom = min_lon,max_lat,max_lon,min_lat) covering
# Greater Cleveland / Cuyahoga County. Geocoding is hard-restricted to this box so
# an ambiguous street name can't resolve to, e.g., Cleveland, TN or Cleveland, MS.
GEOCODE_VIEWBOX = os.getenv("GEOCODE_VIEWBOX", "-82.05,41.66,-81.35,41.28")
MAP_CENTER_LAT = float(os.getenv("MAP_CENTER_LAT", "41.4993"))
MAP_CENTER_LON = float(os.getenv("MAP_CENTER_LON", "-81.6944"))
MAP_DEFAULT_ZOOM = int(os.getenv("MAP_DEFAULT_ZOOM", "11"))
# How far the dashboard map can be panned/zoomed out — south,west,north,east.
# Looser than GEOCODE_VIEWBOX on purpose, just to keep neighboring-state context off-screen.
MAP_MAX_BOUNDS = os.getenv("MAP_MAX_BOUNDS", "40.95,-82.60,42.05,-80.90")

def _parse_feed_urls() -> list[str]:
    raw = os.getenv("BROADCASTIFY_FEED_URLS") or os.getenv("BROADCASTIFY_FEED_URL", "")
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return [
        "https://audio.broadcastify.com/23058.mp3",  # Cleveland Fire and EMS
        "https://audio.broadcastify.com/11446.mp3",  # Cleveland Police
        "https://audio.broadcastify.com/25008.mp3",  # Cleveland Police - West
        "https://audio.broadcastify.com/42707.mp3",  # East Cleveland Police and Fire
        "https://audio.broadcastify.com/38526.mp3",  # Parma / Parma Heights Police and Fire
        "https://audio.broadcastify.com/35157.mp3",  # Lakewood Police and Fire
        "https://audio.broadcastify.com/31282.mp3",  # South Euclid/Cleveland Hts/Richmond Hts/University Hts PD
        "https://audio.broadcastify.com/29943.mp3",  # Shaker Hts/University Hts/Cleveland Hts Fire
        "https://audio.broadcastify.com/24080.mp3",  # Shaker Heights Police
        "https://audio.broadcastify.com/21419.mp3",  # Garfield Heights and Maple Heights PD
        "https://audio.broadcastify.com/15234.mp3",  # WestCom Fire and West Suburbs Police
        "https://audio.broadcastify.com/38131.mp3",  # Southwest Emergency Dispatch (SWEDC)
        "https://audio.broadcastify.com/38127.mp3",  # Brook Park Police
    ]

BROADCASTIFY_FEED_URLS: list[str] = _parse_feed_urls()
BROADCASTIFY_FEED_URL = BROADCASTIFY_FEED_URLS[0]  # legacy single-feed compat

# Premium account credentials — required for audio.broadcastify.com feeds.
# The old unauthenticated broadcastify.cdnstream1.com mounts stopped serving
# audio; Premium feeds now require HTTP Basic Auth with your account login.
BROADCASTIFY_USERNAME = os.getenv("BROADCASTIFY_USERNAME", "")
BROADCASTIFY_PASSWORD = os.getenv("BROADCASTIFY_PASSWORD", "")
CHUNK_DURATION_SECONDS = 60
SILENCE_THRESHOLD_RMS = 500
WHISPER_MODEL = "base.en"
CLAUDE_MODEL = "claude-sonnet-4-6"
POST_COOLDOWN_MINUTES = int(os.getenv("POST_COOLDOWN_MINUTES", "2"))
POST_MAX_AGE_HOURS = int(os.getenv("POST_MAX_AGE_HOURS", "4"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DB_PATH = "incidents.db"
QUEUE_FILE = "post_queue.json"
TEXT_OUTPUT_FILE = os.getenv("TEXT_OUTPUT_FILE", "incidents.txt")
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")

# Ollama classifier (via olla proxy)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://lampoon.billford.io:40114/olla/ollama")

# Stream capture
STREAM_READ_TIMEOUT = 30
STREAM_CHUNK_BYTES = 4096
