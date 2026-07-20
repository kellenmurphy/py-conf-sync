import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from py_conf_sync import ConfluenceClient, CloudConfluenceClient

BASE = "https://confluence.example.com"
CLOUD_BASE = "https://site.atlassian.net/wiki"


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


class TestCloudClientInit:
    def test_email_token_sets_basic_auth(self):
        session = _make_session_mock()
        with patch('py_conf_sync.requests.Session', return_value=session):
            CloudConfluenceClient(CLOUD_BASE, username="me@example.com", password="apitok")
        assert session.auth == ("me@example.com", "apitok")
        assert "Authorization" not in session.headers


class TestCloudClientGetPage:
    def test_gets_v2_endpoint_with_storage_format(self):
        session = _make_session_mock()
        resp = MagicMock()
        resp.json.return_value = {"id": "123", "title": "T"}
        session.get.return_value = resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = CloudConfluenceClient(CLOUD_BASE, username="e", password="t")
            client.get_page("123")

        resp.raise_for_status.assert_called_once()
        session.get.assert_called_once_with(
            f"{CLOUD_BASE}/api/v2/pages/123",
            params={"body-format": "storage"},
        )

    def test_response_shape_matches_command_contract(self):
        # Realistic v2 response — lock in that the access paths cmd_pull/cmd_push
        # use (title, version.number, body.storage.value) resolve unchanged.
        session = _make_session_mock()
        resp = MagicMock()
        resp.json.return_value = {
            "id": "123",
            "title": "Cloud Page",
            "version": {"number": 3},
            "body": {"storage": {"value": "<p>x</p>", "representation": "storage"}},
        }
        session.get.return_value = resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = CloudConfluenceClient(CLOUD_BASE, username="e", password="t")
            page = client.get_page("123")

        assert page["title"] == "Cloud Page"
        assert page["version"]["number"] == 3
        assert page["body"]["storage"]["value"] == "<p>x</p>"


class TestCloudClientUpdatePage:
    def test_puts_v2_payload(self):
        session = _make_session_mock()
        resp = MagicMock()
        resp.json.return_value = {"id": "123", "version": {"number": 4}}
        session.put.return_value = resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = CloudConfluenceClient(CLOUD_BASE, username="e", password="t")
            client.update_page("123", "My Page", "<p>body</p>", 4)

        resp.raise_for_status.assert_called_once()
        put_url = session.put.call_args[0][0]
        assert put_url == f"{CLOUD_BASE}/api/v2/pages/123"
        payload = json.loads(session.put.call_args[1]["data"])
        assert payload["id"] == "123"
        assert payload["status"] == "current"
        assert payload["title"] == "My Page"
        assert payload["version"] == {"number": 4}
        assert payload["body"] == {"representation": "storage", "value": "<p>body</p>"}


class TestDownloadAttachmentText:
    def test_dc_fetches_download_url(self):
        session = _make_session_mock()
        resp = MagicMock()
        resp.text = "flowchart LR\n    A --> B"
        session.get.return_value = resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = ConfluenceClient(BASE, token="t")
            text = client.download_attachment_text("111", "mermaid-abc123def456.txt")

        assert text == "flowchart LR\n    A --> B"
        resp.raise_for_status.assert_called_once()
        session.get.assert_called_once_with(
            f"{BASE}/download/attachments/111/mermaid-abc123def456.txt"
        )

    def test_cloud_resolves_id_and_uses_rest_download(self):
        session = _make_session_mock()
        check_resp = MagicMock()
        check_resp.json.return_value = {"results": [{"id": "att999"}]}
        dl_resp = MagicMock()
        dl_resp.text = "flowchart LR\n    A --> B"
        session.get.side_effect = [check_resp, dl_resp]

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = CloudConfluenceClient(CLOUD_BASE, username="e", password="t")
            text = client.download_attachment_text("111", "mermaid-abc123def456.txt")

        assert text == "flowchart LR\n    A --> B"
        first_call, second_call = session.get.call_args_list
        assert first_call[0][0] == f"{CLOUD_BASE}/rest/api/content/111/child/attachment"
        assert first_call[1]["params"] == {"filename": "mermaid-abc123def456.txt"}
        assert second_call[0][0] == f"{CLOUD_BASE}/rest/api/content/111/child/attachment/att999/download"

    def test_cloud_raises_when_attachment_missing(self):
        session = _make_session_mock()
        check_resp = MagicMock()
        check_resp.json.return_value = {"results": []}
        session.get.return_value = check_resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = CloudConfluenceClient(CLOUD_BASE, username="e", password="t")
            with pytest.raises(Exception, match="attachment not found"):
                client.download_attachment_text("111", "missing.txt")


class TestCloudClientUploadAttachment:
    def test_inherited_upload_uses_wiki_paths(self, tmp_path):
        img = tmp_path / "diagram.png"
        img.write_bytes(b"fake image data")

        session = _make_session_mock()
        check_resp = MagicMock()
        check_resp.json.return_value = {"results": []}
        post_resp = MagicMock()
        session.get.return_value = check_resp
        session.post.return_value = post_resp

        with patch('py_conf_sync.requests.Session', return_value=session):
            client = CloudConfluenceClient(CLOUD_BASE, username="e", password="t")
            url = client.upload_attachment("456", img)

        post_url = session.post.call_args[0][0]
        assert post_url.startswith(f"{CLOUD_BASE}/rest/api/content/456/child/attachment")
        assert url.startswith(f"{CLOUD_BASE}/download/attachments/456/")
