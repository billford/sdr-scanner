# Chagrin Valley Scanner Page

Automated pipeline: Broadcastify audio → Whisper STT → Claude → Facebook post queue.

## Quick start

```bash
# 1. Install system deps
brew install ffmpeg

# 2. Python deps
cd scanner-page
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Run (prints to console by default)
POST_BACKEND=print python main.py
```

## Backends

| `POST_BACKEND` | Behavior |
|---|---|
| `queue` (default) | Appends to `post_queue.json` for manual review |
| `print` | Prints formatted post to stdout |
| `facebook` | Posts via Graph API (requires `FB_PAGE_ID` + `FB_ACCESS_TOKEN`) |

## Whisper backend

| `WHISPER_BACKEND` | Behavior |
|---|---|
| `local` (default) | Uses `openai-whisper` package locally (free, ~1 GB model download) |
| `openai` | Uses OpenAI Whisper API (requires `OPENAI_API_KEY`) |

## Files

| File | Purpose |
|---|---|
| `main.py` | Main loop |
| `capture.py` | Broadcastify stream capture + silence detection |
| `transcribe.py` | Whisper transcription |
| `summarize.py` | Claude API summarization |
| `post.py` | Facebook / queue posting |
| `db.py` | SQLite incident log + dedup |
| `config.py` | Feed URLs, thresholds, model names |

## Facebook setup (Phase 3)

1. Create a Facebook Page
2. Register a Developer App at developers.facebook.com
3. Get a long-lived Page Access Token with `pages_manage_posts` permission
4. Set `FB_PAGE_ID` and `FB_ACCESS_TOKEN` env vars
5. Set `POST_BACKEND=facebook`

## Notes

- The Whisper `base.en` model downloads ~150 MB on first run.
- `ffmpeg` is required by openai-whisper for MP3 decoding.
- Incidents are always saved to `incidents.db` regardless of backend.
- Review `post_queue.json` to approve posts before going live.
