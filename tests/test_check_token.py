import pytest
from unittest.mock import patch, MagicMock

import post


def _token_info(valid=True, scopes=None, expires_days=30, error=None):
    from datetime import datetime, timedelta
    expires = (datetime.now() + timedelta(days=expires_days)).isoformat()
    return {
        "valid": valid,
        "expires_at": expires,
        "scopes": scopes or ["pages_manage_posts"],
        "app_id": "999",
        "error": error,
    }


def _mock_page_resp(name="Test Scanner Page", page_id="123"):
    mock = MagicMock()
    mock.json.return_value = {"name": name, "id": page_id}
    mock.raise_for_status = MagicMock()
    return mock


# ── check_token.main ──────────────────────────────────────────────────────────

def test_check_token_all_good(monkeypatch, capsys):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "valid-token")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "123")

    with patch("check_token.get_token_info", return_value=_token_info()):
        with patch("check_token.requests.get", return_value=_mock_page_resp()):
            check_token.main()

    out = capsys.readouterr().out
    assert "All checks passed" in out


def test_check_token_no_access_token(monkeypatch):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "123")

    with pytest.raises(SystemExit) as exc:
        check_token.main()
    assert exc.value.code == 1


def test_check_token_no_page_id(monkeypatch):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "some-token")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "")

    with pytest.raises(SystemExit) as exc:
        check_token.main()
    assert exc.value.code == 1


def test_check_token_invalid_token(monkeypatch):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "bad-token")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "123")

    with patch("check_token.get_token_info", return_value=_token_info(valid=False, error="Token expired")):
        with pytest.raises(SystemExit) as exc:
            check_token.main()
    assert exc.value.code == 1


def test_check_token_missing_scope(monkeypatch, capsys):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "token")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "123")

    with patch("check_token.get_token_info", return_value=_token_info(scopes=["public_profile"])):
        with pytest.raises(SystemExit) as exc:
            check_token.main()
    assert exc.value.code == 1
    assert "pages_manage_posts" in capsys.readouterr().out


def test_check_token_expiry_warning(monkeypatch, capsys):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "token")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "123")

    with patch("check_token.get_token_info", return_value=_token_info(expires_days=7)):
        with patch("check_token.requests.get", return_value=_mock_page_resp()):
            check_token.main()

    out = capsys.readouterr().out
    assert "WARN" in out
    assert "days" in out  # exact count varies by test timing


def test_check_token_page_not_found(monkeypatch):
    import check_token
    monkeypatch.setattr(check_token, "FB_ACCESS_TOKEN", "token")
    monkeypatch.setattr(check_token, "FB_PAGE_ID", "bad-page-id")

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("404 Not Found")

    with patch("check_token.get_token_info", return_value=_token_info()):
        with patch("check_token.requests.get", return_value=mock_resp):
            with pytest.raises(SystemExit) as exc:
                check_token.main()
    assert exc.value.code == 1
