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
        "https://broadcastify.cdnstream1.com/23058",  # Cleveland Fire and EMS
        "https://broadcastify.cdnstream1.com/11446",  # Cleveland Police
    ]

BROADCASTIFY_FEED_URLS: list[str] = _parse_feed_urls()
BROADCASTIFY_FEED_URL = BROADCASTIFY_FEED_URLS[0]  # legacy single-feed compat
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
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL", "")
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")

# Ollama classifier (via olla proxy)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://192.168.1.182:40114/olla/ollama")

# Stream capture
STREAM_READ_TIMEOUT = 30
STREAM_CHUNK_BYTES = 4096
