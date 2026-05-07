import pytest
from unittest.mock import patch, MagicMock


# ── local whisper backend ─────────────────────────────────────────────────────

def test_transcribe_local_returns_text():
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "  Engine 3 structure fire  "}

    with patch("transcribe.WHISPER_BACKEND", "local"):
        with patch("transcribe._get_local_model", return_value=mock_model):
            from transcribe import _transcribe_local
            result = _transcribe_local(b"fake audio bytes")

    assert result == "Engine 3 structure fire"


def test_transcribe_local_strips_whitespace():
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "\n  shots fired on Main  \n"}

    with patch("transcribe._get_local_model", return_value=mock_model):
        from transcribe import _transcribe_local
        result = _transcribe_local(b"audio")

    assert result == "shots fired on Main"


def test_transcribe_returns_empty_on_model_error():
    with patch("transcribe.WHISPER_BACKEND", "local"):
        with patch("transcribe._get_local_model", side_effect=RuntimeError("model load failed")):
            from transcribe import transcribe
            result = transcribe(b"some audio")
    assert result == ""


def test_transcribe_returns_empty_on_transcribe_error():
    mock_model = MagicMock()
    mock_model.transcribe.side_effect = Exception("GPU error")

    with patch("transcribe.WHISPER_BACKEND", "local"):
        with patch("transcribe._get_local_model", return_value=mock_model):
            from transcribe import transcribe
            result = transcribe(b"audio")
    assert result == ""


# ── openai whisper backend ────────────────────────────────────────────────────

def test_transcribe_openai_returns_text():
    mock_transcription = MagicMock()
    mock_transcription.text = "  Shots fired on Main  "
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_transcription

    with patch("transcribe.WHISPER_BACKEND", "openai"):
        with patch("transcribe.OpenAI", mock_client, create=True):
            # Patch at the point of use inside the function
            import transcribe
            with patch.object(transcribe, "_transcribe_openai",
                              wraps=lambda b: mock_transcription.text.strip()):
                result = transcribe.transcribe(b"fake mp3 bytes")

    assert result == "Shots fired on Main"


def test_transcribe_openai_via_module(monkeypatch):
    """Test the openai path by patching the internal function directly."""
    import transcribe
    monkeypatch.setattr(transcribe, "WHISPER_BACKEND", "openai")

    with patch.object(transcribe, "_transcribe_openai", return_value="EMS call, 55 Oak Ave"):
        result = transcribe.transcribe(b"audio")

    assert result == "EMS call, 55 Oak Ave"
