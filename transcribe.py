"""
Transcribes audio chunks via local whisper.cpp (preferred) or OpenAI Whisper API fallback.

Local path uses the `whisper-cpp` Python binding or the `whisper` package.
Set WHISPER_BACKEND = "local" or "openai" in config (defaults to "local").
"""
import io
import logging
import os
import tempfile

from config import WHISPER_MODEL

log = logging.getLogger(__name__)

WHISPER_BACKEND = os.getenv("WHISPER_BACKEND", "local")

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        try:
            import whisper  # openai-whisper package
            log.info("Loading local Whisper model: %s", WHISPER_MODEL)
            _local_model = whisper.load_model(WHISPER_MODEL)
        except ImportError:
            raise RuntimeError(
                "openai-whisper not installed. Run: pip install openai-whisper"
            )
    return _local_model


def _transcribe_local(audio_bytes: bytes) -> str:
    model = _get_local_model()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        result = model.transcribe(tmp_path, language="en", fp16=False)
        return result["text"].strip()
    finally:
        os.unlink(tmp_path)


def _transcribe_openai(audio_bytes: bytes) -> str:
    from openai import OpenAI

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
    except Exception as exc:
        log.error("Transcription failed: %s", exc)
        return ""
