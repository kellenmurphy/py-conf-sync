"""Tests for command-layer functions, _get_client, _find_env_file, and main()."""

import argparse
import json
import runpy
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import requests

import py_conf_sync
from py_conf_sync import (
    _find_env_file,
    _file_path,
    _get_client,
    _resolve_pages,
    _upload_local_images,
    cmd_pull,
    cmd_push,
    cmd_status,
    cmd_scan,
    load_config,
    save_config,
    main,
    markdown_to_storage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(tmp_path, pages, confluence_url="https://conf.example.com", **extra):
    path = tmp_path / ".py-conf-sync.config.yaml"
    data = {"confluence_url": confluence_url, "pages": pages, **extra}
    save_config(data, path)
    return path


def _mock_client(version=5, storage="<p>Hello</p>", title="Test Page"):
    client = MagicMock()
    client.get_page.return_value = {
        "title": title,
        "body": {"storage": {"value": storage}},
        "version": {"number": version},
    }
    return client


def _pull_args(config_path, page=None, dry_run=False, force=False, debug=False):
    return argparse.Namespace(
        _config_path=config_path,
        page=page,
        dry_run=dry_run,
        force=force,
        debug=debug,
    )


def _push_args(config_path, page=None, dry_run=False, force=False):
    return argparse.Namespace(
        _config_path=config_path,
        page=page,
        dry_run=dry_run,
        force=force,
    )


# ---------------------------------------------------------------------------
# _find_env_file
# ---------------------------------------------------------------------------

class TestFindEnvFile:
    def test_finds_home_env_file(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".csync.env").write_text("CONFLUENCE_TOKEN=test\n")
        monkeypatch.setenv("HOME", str(home))
        result = _find_env_file()
        assert result == home / ".csync.env"

    def test_finds_cwd_env_file(self, tmp_path, monkeypatch):
        # Use a distinct home dir with no .csync.env so cwd is found first
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".csync.env").write_text("CONFLUENCE_TOKEN=test\n")
        result = _find_env_file()
        assert result is not None
        assert result.name == ".csync.env"

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.chdir(tmp_path)
        import py_conf_sync as _m
        script_dir = Path(_m.__file__).parent
        if (script_dir / ".csync.env").exists():
            pytest.skip("Script directory has .csync.env; cannot test None path reliably")
        result = _find_env_file()
        assert result is None


# ---------------------------------------------------------------------------
# _file_path
# ---------------------------------------------------------------------------

class TestFilePath:
    def test_relative_path_resolved_against_config_dir(self, tmp_path):
        config = {"_config_dir": tmp_path}
        entry = {"file_path": "docs/page.md"}
        result = _file_path(entry, config)
        assert result == tmp_path / "docs" / "page.md"

    def test_absolute_path_returned_as_is(self, tmp_path):
        abs_path = "/absolute/path/to/page.md"
        config = {"_config_dir": tmp_path}
        entry = {"file_path": abs_path}
        result = _file_path(entry, config)
        assert result == Path(abs_path)


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------

class TestGetClient:
    def _args(self, unsafe_auth=False):
        return argparse.Namespace(unsafe_auth=unsafe_auth)

    def test_exits_when_no_env_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.chdir(tmp_path)
        config = {"confluence_url": "https://conf.example.com"}
        import py_conf_sync as _m
        if (Path(_m.__file__).parent / ".csync.env").exists():
            pytest.skip("Script dir has .csync.env")
        with pytest.raises(SystemExit):
            _get_client(config, self._args())

    def test_exits_when_no_base_url(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".csync.env"
        env_file.write_text("CONFLUENCE_TOKEN=tok\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        with pytest.raises(SystemExit):
            _get_client({}, self._args())

    def test_exits_when_http_url(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".csync.env"
        env_file.write_text("CONFLUENCE_TOKEN=tok\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        with pytest.raises(SystemExit):
            _get_client({"confluence_url": "http://conf.example.com"}, self._args())

    def test_exits_on_basic_auth_without_unsafe_flag(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".csync.env"
        env_file.write_text("CONFLUENCE_USERNAME=user\nCONFLUENCE_PASSWORD=pass\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("CONFLUENCE_USERNAME", "user")
        monkeypatch.setenv("CONFLUENCE_PASSWORD", "pass")
        monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
        config = {"confluence_url": "https://conf.example.com"}
        with patch('py_conf_sync.requests.Session', return_value=MagicMock(headers={})):
            with pytest.raises(SystemExit):
                _get_client(config, self._args(unsafe_auth=False))

    def test_returns_client_with_token(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".csync.env"
        env_file.write_text("CONFLUENCE_TOKEN=mytoken\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("CONFLUENCE_TOKEN", "mytoken")
        monkeypatch.delenv("CONFLUENCE_USERNAME", raising=False)
        monkeypatch.delenv("CONFLUENCE_PASSWORD", raising=False)
        config = {"confluence_url": "https://conf.example.com"}
        with patch('py_conf_sync.requests.Session', return_value=MagicMock(headers={})):
            client = _get_client(config, self._args())
        assert client is not None

    def test_returns_client_with_basic_auth_unsafe(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".csync.env"
        env_file.write_text("CONFLUENCE_USERNAME=user\nCONFLUENCE_PASSWORD=pass\n")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("CONFLUENCE_USERNAME", "user")
        monkeypatch.setenv("CONFLUENCE_PASSWORD", "pass")
        monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
        config = {"confluence_url": "https://conf.example.com"}
        with patch('py_conf_sync.requests.Session', return_value=MagicMock(headers={})):
            client = _get_client(config, self._args(unsafe_auth=True))
        assert client is not None


# ---------------------------------------------------------------------------
# _resolve_pages
# ---------------------------------------------------------------------------

class TestResolvePages:
    def test_returns_all_pages_with_page_id(self):
        config = {"pages": [
            {"page_id": "1", "file_path": "a.md"},
            {"page_id": "2", "file_path": "b.md"},
            {"file_path": "c.md"},  # no page_id — filtered out
        ]}
        result = _resolve_pages(config)
        assert len(result) == 2

    def test_filters_by_page_id(self):
        config = {"pages": [
            {"page_id": "1", "file_path": "a.md"},
            {"page_id": "2", "file_path": "b.md"},
        ]}
        result = _resolve_pages(config, page_id_filter="2")
        assert len(result) == 1
        assert result[0]["page_id"] == "2"

    def test_exits_when_filter_not_found(self):
        config = {"pages": [{"page_id": "1", "file_path": "a.md"}]}
        with pytest.raises(SystemExit):
            _resolve_pages(config, page_id_filter="999")


# ---------------------------------------------------------------------------
# cmd_pull
# ---------------------------------------------------------------------------

class TestCmdPull:
    def test_writes_markdown_file(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        client = _mock_client()
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_pull(_pull_args(config_path))
        assert (tmp_path / "page.md").exists()
        content = (tmp_path / "page.md").read_text()
        assert "confluence_page_id" in content
        assert "Hello" in content

    def test_dry_run_does_not_write_file(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: _mock_client())
        cmd_pull(_pull_args(config_path, dry_run=True))
        assert not (tmp_path / "page.md").exists()

    def test_http_error_skips_page(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md"}])
        client = MagicMock()
        client.get_page.side_effect = requests.HTTPError("404")
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_pull(_pull_args(config_path))
        assert not (tmp_path / "page.md").exists()
        assert "FAILED" in capsys.readouterr().out

    def test_conflict_local_ahead_skips_without_force(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        existing = (
            "---\nconfluence_page_id: '111'\nconfluence_version: 10\ntitle: Test\n---\n\n# Test\n\nOld.\n"
        )
        (tmp_path / "page.md").write_text(existing)
        # Remote is at version 5, local front-matter says 10 → local ahead
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: _mock_client(version=5))
        cmd_pull(_pull_args(config_path, force=False))
        assert "CONFLICT" in capsys.readouterr().out
        # File must not have been overwritten
        assert "confluence_version: 10" in (tmp_path / "page.md").read_text()

    def test_conflict_local_ahead_force_overwrites(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        (tmp_path / "page.md").write_text(
            "---\nconfluence_page_id: '111'\nconfluence_version: 10\ntitle: Test\n---\n\n# Test\n"
        )
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: _mock_client(version=5))
        cmd_pull(_pull_args(config_path, force=True))
        content = (tmp_path / "page.md").read_text()
        assert "confluence_version: 5" in content

    def test_debug_flag_prints_raw_storage(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: _mock_client(storage="<p>Raw</p>"))
        cmd_pull(_pull_args(config_path, debug=True))
        assert "raw storage" in capsys.readouterr().out

    def test_auto_fills_missing_title(self, tmp_path, monkeypatch):
        # Entry has no title — should be filled in from the API response
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md"}])
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: _mock_client(title="Auto Title"))
        cmd_pull(_pull_args(config_path))
        config = load_config(config_path)
        assert config["pages"][0]["title"] == "Auto Title"


# ---------------------------------------------------------------------------
# _upload_local_images
# ---------------------------------------------------------------------------

class TestUploadLocalImages:
    def test_uploads_local_image_and_replaces_path(self, tmp_path):
        img = tmp_path / "img" / "fig.png"
        img.parent.mkdir()
        img.write_bytes(b"fake")
        md_file = tmp_path / "page.md"
        body = "![fig.png](img/fig.png)"

        client = MagicMock()
        client.upload_attachment.return_value = "https://conf.example.com/download/attachments/123/fig.png"

        result = _upload_local_images(body, client, "123", "https://conf.example.com", md_file)
        assert "download/attachments" in result
        client.upload_attachment.assert_called_once()

    def test_skips_http_urls(self, tmp_path):
        body = "![ext](https://example.com/img.png)"
        client = MagicMock()
        result = _upload_local_images(body, client, "123", "https://conf.example.com", tmp_path / "page.md")
        assert result == body
        client.upload_attachment.assert_not_called()

    def test_skips_missing_local_file(self, tmp_path, capsys):
        body = "![missing](img/missing.png)"
        client = MagicMock()
        result = _upload_local_images(body, client, "123", "https://conf.example.com", tmp_path / "page.md")
        assert result == body
        assert "warn" in capsys.readouterr().out

    def test_dry_run_skips_upload(self, tmp_path, capsys):
        img = tmp_path / "img" / "fig.png"
        img.parent.mkdir()
        img.write_bytes(b"fake")
        body = "![fig.png](img/fig.png)"
        client = MagicMock()
        result = _upload_local_images(body, client, "123", "https://conf.example.com", tmp_path / "page.md", dry_run=True)
        assert result == body
        assert "dry-run" in capsys.readouterr().out
        client.upload_attachment.assert_not_called()

    def test_upload_failure_keeps_original(self, tmp_path, capsys):
        img = tmp_path / "img" / "fig.png"
        img.parent.mkdir()
        img.write_bytes(b"fake")
        body = "![fig.png](img/fig.png)"
        client = MagicMock()
        client.upload_attachment.side_effect = Exception("network error")
        result = _upload_local_images(body, client, "123", "https://conf.example.com", tmp_path / "page.md")
        assert result == body
        assert "FAILED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_push
# ---------------------------------------------------------------------------

def _write_page(tmp_path, filename="page.md", version=5, body="Hello world."):
    content = (
        f"---\nconfluence_page_id: '111'\nconfluence_version: {version}\ntitle: Test Page\n---\n\n"
        f"# Test Page\n\n{body}\n"
    )
    (tmp_path / filename).write_text(content)


class TestCmdPush:
    def test_pushes_page_and_updates_front_matter(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test Page"}])
        _write_page(tmp_path, version=5)
        client = _mock_client(version=5)
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path))
        client.update_page.assert_called_once()
        content = (tmp_path / "page.md").read_text()
        assert "confluence_version: 6" in content

    def test_dry_run_does_not_call_update(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test Page"}])
        _write_page(tmp_path)
        client = _mock_client(version=5)
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path, dry_run=True))
        client.update_page.assert_not_called()

    def test_skips_missing_file(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "missing.md"}])
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: _mock_client())
        cmd_push(_push_args(config_path))
        assert "SKIP" in capsys.readouterr().out

    def test_conflict_remote_ahead_skips_without_force(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        _write_page(tmp_path, version=3)  # local v3, remote v5 → conflict
        client = _mock_client(version=5)
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path, force=False))
        assert "CONFLICT" in capsys.readouterr().out
        client.update_page.assert_not_called()

    def test_conflict_remote_ahead_force_pushes(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        _write_page(tmp_path, version=3)
        client = _mock_client(version=5)
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path, force=True))
        client.update_page.assert_called_once()

    def test_no_local_version_warns(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        (tmp_path / "page.md").write_text("# Test Page\n\nNo front-matter.\n")
        client = _mock_client(version=5)
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path))
        assert "confluence_version" in capsys.readouterr().out

    def test_http_error_on_get_page_skips(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        _write_page(tmp_path)
        client = MagicMock()
        client.get_page.side_effect = requests.HTTPError("404")
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path))
        assert "FAILED" in capsys.readouterr().out

    def test_http_error_on_update_page_skips(self, tmp_path, monkeypatch, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "Test"}])
        _write_page(tmp_path, version=5)
        client = _mock_client(version=5)
        err = requests.HTTPError("500")
        err.response = MagicMock()
        err.response.text = "Internal Server Error"
        client.update_page.side_effect = err
        monkeypatch.setattr(py_conf_sync, '_get_client', lambda c, a: client)
        cmd_push(_push_args(config_path))
        assert "FAILED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_prints_page_table(self, tmp_path, capsys):
        config_path = _save(tmp_path, [{"page_id": "111", "file_path": "page.md", "title": "My Page"}])
        args = argparse.Namespace(_config_path=config_path)
        cmd_status(args)
        out = capsys.readouterr().out
        assert "111" in out
        assert "My Page" in out

    def test_prints_message_when_no_pages(self, tmp_path, capsys):
        config_path = _save(tmp_path, [])
        args = argparse.Namespace(_config_path=config_path)
        cmd_status(args)
        assert "No pages configured" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_scan
# ---------------------------------------------------------------------------

class TestCmdScan:
    def _args(self, repo_path, output=None, url=None, exclude=None):
        return argparse.Namespace(
            repo_path=str(repo_path),
            output=output,
            url=url,
            exclude=exclude,
        )

    def test_scans_md_files(self, tmp_path):
        (tmp_path / "doc1.md").write_text("# Doc 1")
        (tmp_path / "doc2.md").write_text("# Doc 2")
        output = tmp_path / "mapping.json"
        cmd_scan(self._args(tmp_path, output=str(output)))
        data = json.loads(output.read_text())
        paths = [p["file_path"] for p in data["pages"]]
        assert "doc1.md" in paths
        assert "doc2.md" in paths

    def test_exits_when_not_a_directory(self, tmp_path):
        with pytest.raises(SystemExit):
            cmd_scan(self._args(tmp_path / "nonexistent"))

    def test_preserves_existing_page_id_mappings(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Doc")
        output = tmp_path / ".confluence-sync.json"
        # Write pre-existing mapping with a page_id
        output.write_text(json.dumps({
            "confluence_url": "https://conf.example.com",
            "pages": [{"page_id": "999", "file_path": "doc.md", "title": "Doc"}]
        }))
        cmd_scan(self._args(tmp_path, output=str(output)))
        data = json.loads(output.read_text())
        assert data["pages"][0]["page_id"] == "999"

    def test_exclude_regex_filters_files(self, tmp_path):
        (tmp_path / "keep.md").write_text("# Keep")
        (tmp_path / "skip-me.md").write_text("# Skip")
        output = tmp_path / "mapping.json"
        cmd_scan(self._args(tmp_path, output=str(output), exclude=r"skip"))
        data = json.loads(output.read_text())
        paths = [p["file_path"] for p in data["pages"]]
        assert "keep.md" in paths
        assert "skip-me.md" not in paths

    def test_invalid_exclude_regex_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            cmd_scan(self._args(tmp_path, exclude="[invalid"))

    def test_url_arg_used_when_no_existing_config(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Doc")
        output = tmp_path / "mapping.json"
        cmd_scan(self._args(tmp_path, output=str(output), url="https://my-conf.example.com"))
        data = json.loads(output.read_text())
        assert data["confluence_url"] == "https://my-conf.example.com"


# ---------------------------------------------------------------------------
# _resolve_relative_md_links — uncovered branches
# ---------------------------------------------------------------------------

class TestRelativeLinkUncoveredBranches:
    def _config(self, tmp_path, pages):
        return {
            "_config_dir": tmp_path,
            "confluence_url": "https://conf.example.com",
            "pages": pages,
        }

    def test_page_without_page_id_skipped_in_index(self, tmp_path):
        # Entry with no page_id — should be skipped when building the lookup,
        # and the link remains unchanged.
        config = self._config(tmp_path, [{"file_path": "docs/page.md", "title": "Page"}])
        current = tmp_path / "other.md"
        body = "[Page](docs/page.md)"
        from py_conf_sync import _resolve_relative_md_links
        result = _resolve_relative_md_links(body, current, config)
        assert result == body

    def test_absolute_file_path_outside_config_dir_skipped(self, tmp_path):
        # file_path is absolute and not under config_dir → ValueError → entry skipped
        config = self._config(tmp_path, [
            {"page_id": "1", "file_path": "/outside/the/config/dir.md", "title": "Page"}
        ])
        current = tmp_path / "other.md"
        body = "[Page](other.md)"
        from py_conf_sync import _resolve_relative_md_links
        result = _resolve_relative_md_links(body, current, config)
        assert result == body

    def test_link_resolving_outside_config_dir_unchanged(self, tmp_path):
        # Target resolves to a path outside config_dir → ValueError → return unchanged
        config = self._config(tmp_path, [
            {"page_id": "1", "file_path": "docs/page.md", "title": "Page"}
        ])
        current = tmp_path / "docs" / "sub" / "file.md"
        # ../../../../.. escapes well past tmp_path on any system
        body = "[Escape](../../../../../../../../../escape.md)"
        from py_conf_sync import _resolve_relative_md_links
        result = _resolve_relative_md_links(body, current, config)
        assert result == body

    def test_no_base_url_and_no_title_returns_unchanged(self, tmp_path):
        # page has page_id but no title, and no confluence_url → falls through to return m.group(0)
        config = {
            "_config_dir": tmp_path,
            "confluence_url": "",
            "pages": [{"page_id": "123", "file_path": "docs/page.md", "title": None}],
        }
        current = tmp_path / "other.md"
        body = "[Page](docs/page.md)"
        from py_conf_sync import _resolve_relative_md_links
        result = _resolve_relative_md_links(body, current, config)
        assert result == body


# ---------------------------------------------------------------------------
# markdown_to_storage — ImportError and img_to_ac_image no-src branches
# ---------------------------------------------------------------------------

class TestMarkdownToStorageEdgeCases:
    def test_exits_when_markdown_not_installed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, 'markdown', None)
        with pytest.raises(SystemExit):
            markdown_to_storage("# Hello")

    def test_img_without_src_passed_through_unchanged(self):
        # An <img> with no src attribute hits the no-src branch in img_to_ac_image
        # and is returned as-is (kept as the original <img> tag).
        result = markdown_to_storage('<img alt="no-src-here" />')
        # The img tag should be preserved (not converted to ac:image) since there's no src
        assert "ac:image" not in result
        assert "no-src-here" in result


# ---------------------------------------------------------------------------
# main() — argparse dispatch and __main__ guard
# ---------------------------------------------------------------------------

class TestMain:
    def test_version_flag(self, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['py_conf_sync', '--version'])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    def test_dispatches_status(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [])
        called = []
        monkeypatch.setattr(py_conf_sync, 'cmd_status', lambda args: called.append(args))
        monkeypatch.setattr(sys, 'argv', ['py_conf_sync', '--config', str(config_path), 'status'])
        main()
        assert len(called) == 1
        assert called[0]._config_path == config_path

    def test_scan_sets_config_path_to_none(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(py_conf_sync, 'cmd_scan', lambda args: called.append(args))
        monkeypatch.setattr(sys, 'argv', ['py_conf_sync', 'scan', str(tmp_path)])
        main()
        assert called[0]._config_path is None

    def test_custom_config_path_used(self, tmp_path, monkeypatch):
        config_path = _save(tmp_path, [])
        called = []
        monkeypatch.setattr(py_conf_sync, 'cmd_status', lambda args: called.append(args))
        monkeypatch.setattr(sys, 'argv', ['py_conf_sync', '--config', str(config_path), 'status'])
        main()
        assert called[0]._config_path == config_path

    def test_dunder_main_guard(self, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['py_conf_sync', '--version'])
        with pytest.raises(SystemExit):
            runpy.run_module('py_conf_sync', run_name='__main__', alter_sys=True)
