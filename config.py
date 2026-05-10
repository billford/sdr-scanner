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

COMMUNITY_NAME = os.getenv("COMMUNITY_NAME", "Chagrin Valley")
COMMUNITY_DESC = os.getenv("COMMUNITY_DESC", "Chagrin Falls and surrounding Cuyahoga County communities")
BROADCASTIFY_FEED_URL = os.getenv("BROADCASTIFY_FEED_URL", "https://broadcastify.cdnstream1.com/42700")
CHUNK_DURATION_SECONDS = 60
SILENCE_THRESHOLD_RMS = 500
WHISPER_MODEL = "base.en"
CLAUDE_MODEL = "claude-sonnet-4-6"
POST_COOLDOWN_MINUTES = 5
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DB_PATH = "incidents.db"
QUEUE_FILE = "post_queue.json"
TEXT_OUTPUT_FILE = os.getenv("TEXT_OUTPUT_FILE", "incidents.txt")

# Local Ollama classifier
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Stream capture
STREAM_READ_TIMEOUT = 30
STREAM_CHUNK_BYTES = 4096
