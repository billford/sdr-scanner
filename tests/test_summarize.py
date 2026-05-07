import pytest
from unittest.mock import patch, MagicMock


def _make_incident(raw="Engine 3 structure fire 123 Main"):
    import db
    return {
        "time": "14:32",
        "type": "Structure Fire",
        "location": "123 Main Street",
        "local_summary": "Structure fire at 123 Main Street, Engine 3 dispatched.",
        "summary": "Structure fire at 123 Main Street, Engine 3 dispatched.",
        "raw_transcript": raw,
        "transcript_hash": db.transcript_hash(raw),
    }


def _mock_claude_response(text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text)]
    return mock_msg


# ── polish ────────────────────────────────────────────────────────────────────

def test_polish_updates_summary(tmp_db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    import summarize, config
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    summarize._client = None

    polished_text = "[14:32] Structure Fire — 123 Main Street — Engine 3 responded to a working fire."
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response(polished_text)

    with patch("summarize.anthropic.Anthropic", return_value=mock_client):
        summarize._client = None
        result = summarize.polish(_make_incident())

    assert result["summary"] == polished_text
    mock_client.messages.create.assert_called_once()


def test_polish_no_api_key_returns_unchanged(tmp_db, monkeypatch):
    import summarize
    monkeypatch.setattr(summarize, "ANTHROPIC_API_KEY", "")
    summarize._client = None

    incident = _make_incident()
    result = summarize.polish(incident)
    assert result["summary"] == incident["summary"]


def test_polish_api_error_falls_back_to_local(tmp_db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    import summarize, config
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API timeout")

    with patch("summarize.anthropic.Anthropic", return_value=mock_client):
        summarize._client = None
        incident = _make_incident()
        result = summarize.polish(incident)

    # Falls back — summary unchanged from local
    assert result["summary"] == incident["summary"]


def test_polish_does_not_mutate_original(tmp_db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    import summarize, config
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response("Polished version")

    with patch("summarize.anthropic.Anthropic", return_value=mock_client):
        summarize._client = None
        incident = _make_incident()
        original_summary = incident["summary"]
        result = summarize.polish(incident)

    assert incident["summary"] == original_summary  # original unchanged
    assert result["summary"] == "Polished version"
