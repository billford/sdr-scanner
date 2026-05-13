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
POST_COOLDOWN_MINUTES = 5
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DB_PATH = "incidents.db"
QUEUE_FILE = "post_queue.json"
TEXT_OUTPUT_FILE = os.getenv("TEXT_OUTPUT_FILE", "incidents.txt")
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL", "")

# Local Ollama classifier
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Stream capture
STREAM_READ_TIMEOUT = 30
STREAM_CHUNK_BYTES = 4096
