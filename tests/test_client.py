import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from py_conf_sync import ConfluenceClient

BASE = "https://confluence.example.com"


def _make_session_mock():
    """Return a MagicMock session with a real dict for headers."""
    mock = MagicMock()
    mock.headers = {}
    return mock


class TestConfluenceClientInit:
    def test_token_sets_authorization_header(self):
        with patch('py_conf_sync.requests.Session', return_value=_make_session_mock()):
            client = ConfluenceClient(BASE, token="mytoken")
        assert client.session.headers["Authorization"] == "Bearer mytoken"

    def test_basic_auth_sets_session_auth(self):
        session = _make_session_mock()
        with patch('py_conf_sync.requests.Session', return_value=session):
            ConfluenceClient(BASE, username="user", password="pass")
        assert session.auth == ("user", "pass")

    def test_no_credentials_exits(self):
        with patch('py_conf_sync.requests.Session', return_value=_make_session_mock()):
            with pytest.raises(SystemExit):
                ConfluenceClient(BASE)

    def test_strips_trailing_slash_from_base_url(self):
        with patch('py_conf_sync.requests.Session', return_value=_make_session_mock()):
            client = ConfluenceClient(BASE + "/", token="t")
        assert not client.base_url.endswith("/")

    def test_sets_content_type_header(self):
        with patch('py_conf_sync.requests.Session', return_value=_make_session_mock()):
            client = ConfluenceClient(BASE, token="t")
        assert client.session.headers["Content-Type"] == "application/json"


class TestConfluenceClientGetPage:
    def test_returns_page_json(self):
        session = _make_session_mock()
        resp = MagicMock()
        resp.json.return_value = {"title": "My Page", "version": {"number": 3}}
        session.get.return_value = resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = ConfluenceClient(BASE, token="t")
            result = client.get_page("123")

        assert result["title"] == "My Page"
        resp.raise_for_status.assert_called_once()
        session.get.assert_called_once_with(
            f"{BASE}/rest/api/content/123",
            params={"expand": "body.storage,version,title"},
        )


class TestConfluenceClientUploadAttachment:
    def test_uploads_new_attachment(self, tmp_path):
        img = tmp_path / "diagram.png"
        img.write_bytes(b"fake image data")

        session = _make_session_mock()
        check_resp = MagicMock()
        check_resp.json.return_value = {"results": []}
        post_resp = MagicMock()
        session.get.return_value = check_resp
        session.post.return_value = post_resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = ConfluenceClient(BASE, token="t")
            url = client.upload_attachment("456", img)

        assert "diagram.png" in url
        assert "456" in url
        post_resp.raise_for_status.assert_called_once()
        # Should have POSTed to the base attachment URL (new upload)
        post_url = session.post.call_args[0][0]
        assert "attachment" in post_url
        assert "data" not in post_url

    def test_updates_existing_attachment(self, tmp_path):
        img = tmp_path / "diagram.png"
        img.write_bytes(b"updated image")

        session = _make_session_mock()
        check_resp = MagicMock()
        check_resp.json.return_value = {"results": [{"id": "att-999"}]}
        post_resp = MagicMock()
        session.get.return_value = check_resp
        session.post.return_value = post_resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = ConfluenceClient(BASE, token="t")
            client.upload_attachment("456", img)

        # Should have POSTed to the /data sub-path for the existing attachment
        post_url = session.post.call_args[0][0]
        assert "att-999" in post_url
        assert "data" in post_url


class TestConfluenceClientUpdatePage:
    def test_puts_page_and_returns_json(self):
        session = _make_session_mock()
        resp = MagicMock()
        resp.json.return_value = {"id": "123", "version": {"number": 4}}
        session.put.return_value = resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = ConfluenceClient(BASE, token="t")
            result = client.update_page("123", "My Page", "<p>body</p>", 4)

        assert result["id"] == "123"
        resp.raise_for_status.assert_called_once()
        session.put.assert_called_once()
