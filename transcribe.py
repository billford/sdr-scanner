"""
Transcribes audio chunks via local Whisper (preferred) or OpenAI Whisper API fallback.

Set WHISPER_BACKEND = "local" or "openai" in config (defaults to "local").
"""
import io
import logging
import os
import tempfile

from config import WHISPER_MODEL

log = logging.getLogger(__name__)

WHISPER_BACKEND = os.getenv("WHISPER_BACKEND", "local")

_LOCAL_MODEL = None


def _get_local_model():
    global _LOCAL_MODEL  # pylint: disable=global-statement
    if _LOCAL_MODEL is None:
        try:
            import whisper  # pylint: disable=import-outside-toplevel
            log.info("Loading local Whisper model: %s", WHISPER_MODEL)
            _LOCAL_MODEL = whisper.load_model(WHISPER_MODEL)
        except ImportError as exc:
            raise RuntimeError(
                "openai-whisper not installed. Run: pip install openai-whisper"
            ) from exc
    return _LOCAL_MODEL


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
