import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import post
from post import FacebookTokenError, FacebookPermissionError, get_token_info, _check_graph_error


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


# ── print backend ─────────────────────────────────────────────────────────────

def test_post_print_outputs_summary(incident, monkeypatch, capsys):
    monkeypatch.setattr(post, "POST_BACKEND", "print")
    post.post_incident(incident)
    captured = capsys.readouterr()
    assert incident["summary"] in captured.out


# ── facebook backend ──────────────────────────────────────────────────────────

def test_post_facebook_success(incident, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "facebook")
    monkeypatch.setattr(post, "FB_PAGE_ID", "123456789")
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "fake-token")

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"id": "123456789_987654321"}

    with patch("post.requests.post", return_value=mock_resp):
        result = post.post_incident(incident)

    assert result == "123456789_987654321"


def test_post_facebook_missing_credentials(incident, monkeypatch):
    monkeypatch.setattr(post, "POST_BACKEND", "facebook")
    monkeypatch.setattr(post, "FB_PAGE_ID", "")
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "")
    result = post._post_facebook(incident["summary"])
    assert result == ""


def test_post_facebook_token_error_raises(incident, monkeypatch):
    monkeypatch.setattr(post, "FB_PAGE_ID", "123")
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "expired-token")

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": {"code": 190, "message": "Token expired"}}

    with patch("post.requests.post", return_value=mock_resp):
        with pytest.raises(FacebookTokenError):
            post._post_facebook(incident["summary"])


def test_post_facebook_permission_error_raises(incident, monkeypatch):
    monkeypatch.setattr(post, "FB_PAGE_ID", "123")
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "no-perms-token")

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": {"code": 200, "message": "Permission denied"}}

    with patch("post.requests.post", return_value=mock_resp):
        with pytest.raises(FacebookPermissionError):
            post._post_facebook(incident["summary"])


# ── _check_graph_error ────────────────────────────────────────────────────────

def test_check_graph_error_ok():
    mock_resp = MagicMock()
    mock_resp.ok = True
    _check_graph_error(mock_resp)  # should not raise


def test_check_graph_error_190():
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": {"code": 190, "message": "Invalid token"}}
    with pytest.raises(FacebookTokenError):
        _check_graph_error(mock_resp)


def test_check_graph_error_102():
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": {"code": 102, "message": "Session expired"}}
    with pytest.raises(FacebookTokenError):
        _check_graph_error(mock_resp)


def test_check_graph_error_200():
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": {"code": 200, "message": "Permission denied"}}
    with pytest.raises(FacebookPermissionError):
        _check_graph_error(mock_resp)


def test_check_graph_error_unknown_raises_http():
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": {"code": 999, "message": "Unknown"}}
    mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
    with pytest.raises(Exception, match="HTTP 500"):
        _check_graph_error(mock_resp)


# ── get_token_info ────────────────────────────────────────────────────────────

def test_get_token_info_no_token(monkeypatch):
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "")
    result = get_token_info()
    assert result["valid"] is False
    assert "not set" in result["error"]


def test_get_token_info_valid(monkeypatch):
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "fake-token")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "is_valid": True,
            "expires_at": 9999999999,
            "scopes": ["pages_manage_posts", "pages_read_engagement"],
            "app_id": "123",
        }
    }

    with patch("post.requests.get", return_value=mock_resp):
        result = get_token_info()

    assert result["valid"] is True
    assert "pages_manage_posts" in result["scopes"]
    assert result["app_id"] == "123"


def test_get_token_info_request_failure(monkeypatch):
    monkeypatch.setattr(post, "FB_ACCESS_TOKEN", "fake-token")
    with patch("post.requests.get", side_effect=ConnectionError("Network error")):
        result = get_token_info()
    assert result["valid"] is False
    assert "Network error" in result["error"]
