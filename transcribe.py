"""
Transcribes audio chunks via local Whisper (preferred) or OpenAI Whisper API fallback.

Set WHISPER_BACKEND = "local" or "openai" in config (defaults to "local").
"""
import io
import logging
import multiprocessing
import os
import tempfile

from config import WHISPER_MODEL

log = logging.getLogger(__name__)

WHISPER_BACKEND = os.getenv("WHISPER_BACKEND", "local")

_POOL: "multiprocessing.pool.Pool | None" = None

# ---------------------------------------------------------------------------
# Subprocess worker — runs in an isolated process.
# The pool recycles the worker every 50 tasks (maxtasksperchild), which
# releases any file descriptors leaked by Whisper's internal ffmpeg calls.
# ---------------------------------------------------------------------------

_WORKER_MODEL = None


def _worker_init(model_name: str) -> None:
    global _WORKER_MODEL  # pylint: disable=global-statement
    import whisper  # pylint: disable=import-outside-toplevel
    _WORKER_MODEL = whisper.load_model(model_name)


def _worker_transcribe(audio_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        result = _WORKER_MODEL.transcribe(tmp_path, language="en", fp16=False)
        return result["text"].strip()
    finally:
        os.unlink(tmp_path)


def _get_pool() -> "multiprocessing.pool.Pool":
    global _POOL  # pylint: disable=global-statement
    if _POOL is None:
        _POOL = multiprocessing.Pool(
            processes=1,
            initializer=_worker_init,
            initargs=(WHISPER_MODEL,),
            maxtasksperchild=50,
        )
    return _POOL


def _transcribe_local(audio_bytes: bytes) -> str:
    global _POOL  # pylint: disable=global-statement
    try:
        return _get_pool().apply(_worker_transcribe, (audio_bytes,))
    except Exception:  # pylint: disable=broad-exception-caught
        # Worker may have crashed; discard the broken pool and retry once.
        _POOL = None
        return _get_pool().apply(_worker_transcribe, (audio_bytes,))


def _transcribe_openai(audio_bytes: bytes) -> str:
    from openai import OpenAI  # pylint: disable=import-outside-toplevel,import-error
    client = OpenAI()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "chunk.mp3"
    resp = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en",
    )
    return resp.text.strip()


def transcribe(audio_bytes: bytes) -> str:
    """Returns transcript string, or empty string on failure."""
    try:
        if WHISPER_BACKEND == "openai":
            return _transcribe_openai(audio_bytes)
        return _transcribe_local(audio_bytes)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.error("Transcription failed: %s", exc)
        return ""
