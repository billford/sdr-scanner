import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import post


@pytest.fixture
def incident():
    return {
        "time": "14:32",
        "type": "Structure Fire",
        "location": "123 Main Street",
        "summary": "[14:32] Structure Fire — 123 Main Street — Engine 3 dispatched.",
        "raw_transcript": "Engine 3 structure fire",
        "transcript_hash": "abc123",
    }


@pytest.fixture
def tmp_queue(tmp_path, monkeypatch):
    q = str(tmp_path / "queue.json")
    monkeypatch.setattr(post, "QUEUE_FILE", q)
    import config
    monkeypatch.setattr(config, "QUEUE_FILE", q)
    return q


@pytest.fixture
def tmp_text(tmp_path, monkeypatch):
    t = str(tmp_path / "incidents.txt")
    monkeypatch.setattr(post, "TEXT_OUTPUT_FILE", t)
    return t


# ── queue backend ─────────────────────────────────────────────────────────────

def test_post_queue_creates_file(incident, tmp_queue, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "queue")
    post.post_incident(incident)
    data = json.loads(Path(tmp_queue).read_text())
    assert len(data) == 1
    assert data[0]["summary"] == incident["summary"]


def test_post_queue_appends(incident, tmp_queue, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "queue")
    post.post_incident(incident)
    incident2 = dict(incident, summary="[15:00] Accident — Route 82")
    post.post_incident(incident2)
    data = json.loads(Path(tmp_queue).read_text())
    assert len(data) == 2


def test_post_queue_handles_corrupt_file(incident, tmp_queue, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "queue")
    Path(tmp_queue).write_text("not valid json")
    post.post_incident(incident)  # should not raise
    data = json.loads(Path(tmp_queue).read_text())
    assert len(data) == 1


def test_post_queue_entry_has_required_fields(incident, tmp_queue, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "queue")
    post.post_incident(incident)
    entry = json.loads(Path(tmp_queue).read_text())[0]
    assert "queued_at" in entry
    assert "summary" in entry
    assert "type" in entry
    assert "location" in entry


# ── text backend ──────────────────────────────────────────────────────────────

def test_post_text_creates_file(incident, tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    post.post_incident(incident)
    assert Path(tmp_text).exists()


def test_post_text_contains_summary(incident, tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    post.post_incident(incident)
    content = Path(tmp_text).read_text()
    assert incident["summary"] in content


def test_post_text_contains_type_and_location(incident, tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    post.post_incident(incident)
    content = Path(tmp_text).read_text()
    assert "Structure Fire" in content
    assert "123 Main Street" in content


def test_post_text_contains_timestamp(incident, tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    post.post_incident(incident)
    content = Path(tmp_text).read_text()
    assert "[" in content  # timestamp bracket


def test_post_text_appends_multiple(incident, tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    post.post_incident(incident)
    incident2 = dict(incident, summary="[15:00] Accident — Route 82", type="Accident", location="Route 82")
    post.post_incident(incident2)
    content = Path(tmp_text).read_text()
    assert incident["summary"] in content
    assert incident2["summary"] in content


def test_post_text_omits_missing_type(tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    inc = {"summary": "Unknown incident", "type": None, "location": None}
    post.post_incident(inc)
    content = Path(tmp_text).read_text()
    assert "Type:" not in content
    assert "Location:" not in content
    assert "Unknown incident" in content


def test_post_text_returns_empty_string(incident, tmp_text, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "text")
    result = post.post_incident(incident)
    assert result == ""


# ── zapier backend ────────────────────────────────────────────────────────────

def test_post_zapier_success(incident, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "zapier")
    monkeypatch.setattr(post, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/fake/123")

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("post.requests.post", return_value=mock_resp) as mock_post:
        result = post.post_incident(incident)

    assert result == ""
    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["summary"] == incident["summary"]
    assert payload["type"] == incident["type"]
    assert payload["location"] == incident["location"]
    assert "posted_at" in payload


def test_post_zapier_missing_url(incident, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "zapier")
    monkeypatch.setattr(post, "ZAPIER_WEBHOOK_URL", "")
    result = post.post_incident(incident)
    assert result == ""


def test_post_zapier_network_error_raises(incident, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "zapier")
    monkeypatch.setattr(post, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/fake/123")

    with patch("post.requests.post", side_effect=ConnectionError("Network error")):
        with pytest.raises(ConnectionError):
            post.post_incident(incident)


def test_post_zapier_http_error_raises(incident, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "zapier")
    monkeypatch.setattr(post, "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/fake/123")

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("HTTP 400")

    with patch("post.requests.post", return_value=mock_resp):
        with pytest.raises(Exception, match="HTTP 400"):
            post.post_incident(incident)


# ── print backend ─────────────────────────────────────────────────────────────

def test_post_print_outputs_summary(incident, monkeypatch, capsys):
    monkeypatch.setattr(post, "POST_BACKEND", "print")
    post.post_incident(incident)
    captured = capsys.readouterr()
    assert incident["summary"] in captured.out
