import json
import pytest
from unittest.mock import patch, MagicMock

from classify import keyword_check, local_classify, _parse_incident_line


# ── keyword_check ─────────────────────────────────────────────────────────────

INCIDENT_PHRASES = [
    "Engine 3 respond to 123 Main Street for a structure fire",
    "EMS unit 7 en route for unconscious subject",
    "All units, shots fired at the corner of Main and Elm",
    "10-50 MVA with injuries on Route 82",
    "Hazmat team respond to gas leak at 400 Industrial Pkwy",
    "Units respond to reported fire on Oak Street",
    "Medical emergency, cardiac arrest, 55 Pine Ave",
    "Vehicle collision with entrapment on I-271",
]

NOISE_PHRASES = [
    "10-4",
    "Copy that",
    "Unit 5 available",
    "Mayor's Court until 1600 hours",
    "Out of service",
    "Radio check, do you copy?",
    "Affirmative, 10-4",
    "Stand by",
    "",
    "   ",
    "123",
]


@pytest.mark.parametrize("text", INCIDENT_PHRASES)
def test_keyword_check_detects_incidents(text):
    assert keyword_check(text) is True, f"Should detect: '{text}'"


@pytest.mark.parametrize("text", NOISE_PHRASES)
def test_keyword_check_ignores_noise(text):
    assert keyword_check(text) is False, f"Should ignore: '{text}'"


def test_keyword_check_short_text():
    assert keyword_check("fire") is False  # too short (< 10 chars after strip check)


def test_keyword_check_case_insensitive():
    assert keyword_check("ENGINE 3 RESPOND TO STRUCTURE FIRE") is True
    assert keyword_check("structure FIRE at main street") is True


# ── local_classify ────────────────────────────────────────────────────────────

def _mock_ollama_response(text: str):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"response": text}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@patch("classify.urllib.request.urlopen")
def test_local_classify_incident(mock_urlopen, tmp_db):
    mock_urlopen.return_value = _mock_ollama_response(
        "INCIDENT: Structure Fire | 123 Main Street | Engine 3 dispatched to structure fire with smoke showing"
    )
    result = local_classify("Engine 3 respond to 123 Main for a structure fire")
    assert result is not None
    assert result["type"] == "Structure Fire"
    assert result["location"] == "123 Main Street"
    assert "Engine 3" in result["local_summary"]
    assert "transcript_hash" in result


@patch("classify.urllib.request.urlopen")
def test_local_classify_no_incident(mock_urlopen, tmp_db):
    mock_urlopen.return_value = _mock_ollama_response("NO_INCIDENT")
    result = local_classify("Unit 5, 10-4, available")
    assert result is None


@patch("classify.urllib.request.urlopen")
def test_local_classify_ambiguous_response(mock_urlopen, tmp_db):
    mock_urlopen.return_value = _mock_ollama_response("I'm not sure about this one.")
    result = local_classify("Some ambiguous radio chatter")
    assert result is None


@patch("classify.urllib.request.urlopen", side_effect=ConnectionError("Ollama down"))
def test_local_classify_ollama_unavailable(mock_urlopen, tmp_db):
    result = local_classify("Engine 3 respond to structure fire")
    assert result is None


@patch("classify.urllib.request.urlopen")
def test_local_classify_partial_pipe_format(mock_urlopen, tmp_db):
    # Only type, no location or description
    mock_urlopen.return_value = _mock_ollama_response("INCIDENT: Medical Emergency")
    result = local_classify("EMS respond for unconscious subject")
    assert result is not None
    assert result["type"] == "Medical Emergency"


# ── _parse_incident_line ──────────────────────────────────────────────────────

def test_parse_incident_line_full(tmp_db):
    line = "INCIDENT: Structure Fire | 123 Main St | Engine 3 dispatched"
    raw = "Engine 3 structure fire 123 Main"
    result = _parse_incident_line(line, raw)
    assert result["type"] == "Structure Fire"
    assert result["location"] == "123 Main St"
    assert result["local_summary"] == "Engine 3 dispatched"


def test_parse_incident_line_missing_parts(tmp_db):
    line = "INCIDENT: Medical"
    result = _parse_incident_line(line, "EMS call")
    assert result["type"] == "Medical"
    assert result["location"] is None
