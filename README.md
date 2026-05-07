# Scanner Page

Automated pipeline: Broadcastify audio → Whisper STT → Ollama (local) → Claude polish → Facebook post queue.

Works with any Broadcastify feed. Configured by default for Chagrin Valley Dispatch.

## Quick start

```bash
# 1. Install system deps
brew install ffmpeg
brew install ollama && ollama pull llama3.2:3b

# 2. Python deps
cd scanner-page
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure (copy and edit)
cp .env.example .env

# 4. Run (prints to console by default)
POST_BACKEND=print python main.py
```

## Configuration

All settings live in `.env`. Copy `.env.example` to get started:

| Variable | Default | Description |
|---|---|---|
| `BROADCASTIFY_FEED_URL` | Chagrin Valley feed | Full stream URL from Broadcastify |
| `COMMUNITY_NAME` | `Chagrin Valley` | Short name, used in logs |
| `COMMUNITY_DESC` | `Chagrin Falls and surrounding Cuyahoga County communities` | Used in Claude prompt |
| `ANTHROPIC_API_KEY` | — | Required for Claude polish step |
| `OLLAMA_MODEL` | `llama3.2:3b` | Local model for incident classification |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `POST_BACKEND` | `queue` | `queue`, `print`, or `facebook` |
| `FB_PAGE_ID` | — | Facebook Page ID (facebook backend only) |
| `FB_ACCESS_TOKEN` | — | Long-lived Page Access Token |

### Finding your Broadcastify stream URL

1. Go to broadcastify.com and find your feed
2. The feed ID is in the URL: `broadcastify.com/listen/feed/XXXXX`
3. Stream URL format: `https://broadcastify.cdnstream1.com/XXXXX`

### Example: configuring for a different community

```
BROADCASTIFY_FEED_URL=https://broadcastify.cdnstream1.com/99999
COMMUNITY_NAME=Akron Metro
COMMUNITY_DESC=Akron and surrounding Summit County communities
```

## Pipeline

```
stream → whisper (free, local)
       → keyword filter (free, instant)
       → ollama classify (free, local)
       → claude polish (API, ~pennies/month — only on confirmed incidents)
       → post/queue
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
| `local` (default) | Uses `openai-whisper` package locally (free, ~150 MB model download) |
| `openai` | Uses OpenAI Whisper API (requires `OPENAI_API_KEY`) |

## Files

| File | Purpose |
|---|---|
| `main.py` | Main loop |
| `capture.py` | Broadcastify stream capture + silence detection |
| `transcribe.py` | Whisper transcription |
| `classify.py` | Keyword pre-filter + Ollama local classification |
| `summarize.py` | Claude API polish step |
| `post.py` | Facebook / queue posting |
| `db.py` | SQLite incident log + dedup |
| `config.py` | All configuration |

## Facebook setup

1. Create a Facebook Page
2. Register a Developer App at developers.facebook.com
3. Get a long-lived Page Access Token with `pages_manage_posts` permission
4. Set `FB_PAGE_ID` and `FB_ACCESS_TOKEN` in `.env`
5. Set `POST_BACKEND=facebook`

## Notes

- `ffmpeg` is required by openai-whisper for MP3 decoding.
- Incidents are always saved to `incidents.db` regardless of backend.
- Review `post_queue.json` to approve posts before going live.
- The Whisper `base.en` model is English-only and fast. Use `base` for multilingual feeds.
