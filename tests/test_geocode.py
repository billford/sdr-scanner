import json
from unittest.mock import MagicMock, patch

import pytest

import db
import geocode


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(geocode, "_RATE_LIMIT_SECONDS", 0)


def _fake_response(payload):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_geocode_none_for_empty_location(tmp_db):
    assert geocode.geocode(None) is None
    assert geocode.geocode("") is None


def test_geocode_none_for_unknown_location(tmp_db):
    assert geocode.geocode("unknown") is None
    assert geocode.geocode("N/A") is None
    assert geocode.geocode("NONE") is None


def test_geocode_query_omits_duplicate_community_name(tmp_db):
    with patch("urllib.request.urlopen", return_value=_fake_response(
        [{"lat": "41.499", "lon": "-81.694"}]
    )) as mock_open:
        geocode.geocode("West 100th Street, Cleveland, OH")
    requested_url = mock_open.call_args[0][0].full_url
    assert requested_url.count("Cleveland") == 1


def test_geocode_query_appends_community_name_when_absent(tmp_db):
    with patch("urllib.request.urlopen", return_value=_fake_response(
        [{"lat": "41.499", "lon": "-81.694"}]
    )) as mock_open:
        geocode.geocode("123 Main St")
    requested_url = mock_open.call_args[0][0].full_url
    assert "Cleveland" in requested_url


def test_geocode_restricts_to_local_viewbox(tmp_db):
    with patch("urllib.request.urlopen", return_value=_fake_response(
        [{"lat": "41.499", "lon": "-81.694"}]
    )) as mock_open:
        geocode.geocode("Main St")
    requested_url = mock_open.call_args[0][0].full_url
    assert "bounded=1" in requested_url
    assert "viewbox=" in requested_url


def test_geocode_returns_coordinates(tmp_db):
    with patch("urllib.request.urlopen", return_value=_fake_response(
        [{"lat": "41.499", "lon": "-81.694"}]
    )) as mock_open:
        result = geocode.geocode("123 Main St")
    assert result == (41.499, -81.694)
    mock_open.assert_called_once()


def test_geocode_caches_hit(tmp_db):
    with patch("urllib.request.urlopen", return_value=_fake_response(
        [{"lat": "41.499", "lon": "-81.694"}]
    )) as mock_open:
        geocode.geocode("123 Main St")
        geocode.geocode("123 Main St")
    mock_open.assert_called_once()


def test_geocode_caches_miss(tmp_db):
    with patch("urllib.request.urlopen", return_value=_fake_response([])) as mock_open:
        first = geocode.geocode("some vague place")
        second = geocode.geocode("some vague place")
    assert first is None
    assert second is None
    mock_open.assert_called_once()
    assert db.cached_geocode("some vague place") is db.GEOCODE_MISS


def test_geocode_handles_network_error(tmp_db):
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert geocode.geocode("123 Main St") is None
