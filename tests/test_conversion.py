import argparse
import json
import pytest
import yaml
from pathlib import Path
from py_conf_sync import (
    storage_to_markdown,
    markdown_to_storage,
    _parse_front_matter,
    _write_front_matter,
    _resolve_relative_md_links,
    _replace_code_macro,
    _replace_noformat_macro,
    _replace_jira_macro,
    _replace_image_macro,
    _ensure_gitignore,
    load_config,
    save_config,
    cmd_init,
    cmd_add,
    cmd_remove,
)


class TestStorageToMarkdown:
    def test_heading(self):
        assert storage_to_markdown("<h1>Hello</h1>") == "# Hello"

    def test_code_block_with_language(self):
        storage = (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            '<ac:plain-text-body><![CDATA[print("hello")]]></ac:plain-text-body>'
            "</ac:structured-macro>"
        )
        result = storage_to_markdown(storage)
        assert "```python" in result
        assert 'print("hello")' in result

    def test_code_block_preserves_indentation(self):
        storage = (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">yaml</ac:parameter>'
            "<ac:plain-text-body><![CDATA[key:\n  nested:\n    deep: value]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        result = storage_to_markdown(storage)
        assert "  nested:" in result
        assert "    deep: value" in result

    def test_code_block_no_language(self):
        storage = (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">none</ac:parameter>'
            "<ac:plain-text-body><![CDATA[plain text]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        result = storage_to_markdown(storage)
        assert "```\n" in result
        assert "plain text" in result

    def test_jira_macro_key_parameter(self):
        storage = (
            '<ac:structured-macro ac:name="jira">'
            '<ac:parameter ac:name="key">IDP-246</ac:parameter>'
            "</ac:structured-macro>"
        )
        result = storage_to_markdown(storage, jira_url="https://jira.example.com")
        assert "[IDP-246](https://jira.example.com/browse/IDP-246)" in result

    def test_jira_macro_bare_key(self):
        storage = (
            '<ac:structured-macro ac:name="jira">'
            '<ac:parameter ac:name="">IDP-239</ac:parameter>'
            "</ac:structured-macro>"
        )
        result = storage_to_markdown(storage, jira_url="https://jira.example.com")
        assert "[IDP-239](https://jira.example.com/browse/IDP-239)" in result

    def test_jira_macro_no_url(self):
        storage = (
            '<ac:structured-macro ac:name="jira">'
            '<ac:parameter ac:name="key">PROJECT-1</ac:parameter>'
            "</ac:structured-macro>"
        )
        result = storage_to_markdown(storage)
        assert "PROJECT-1" in result
        assert "browse" not in result

    def test_confluence_page_link(self):
        storage = '<ac:link><ri:page ri:content-title="My Page" /></ac:link>'
        result = storage_to_markdown(storage)
        assert "[My Page](confluence://page/My%20Page)" in result

    def test_confluence_page_link_html_entities(self):
        storage = '<ac:link><ri:page ri:content-title="My &quot;Quoted&quot; Page" /></ac:link>'
        result = storage_to_markdown(storage)
        assert '[My "Quoted" Page]' in result

    def test_unknown_macros_stripped(self):
        storage = (
            "<p>Before</p>"
            '<ac:structured-macro ac:name="info">'
            "<ac:rich-text-body>ignored</ac:rich-text-body>"
            "</ac:structured-macro>"
            "<p>After</p>"
        )
        result = storage_to_markdown(storage)
        assert "Before" in result
        assert "After" in result
        assert "ac:structured-macro" not in result


class TestMarkdownToStorage:
    def test_heading(self):
        result = markdown_to_storage("# Hello")
        assert "<h1>Hello</h1>" in result

    def test_fenced_code_block(self):
        result = markdown_to_storage("```python\nprint('hello')\n```")
        assert 'ac:name="code"' in result
        assert 'language">python' in result
        assert "print('hello')" in result

    def test_cdata_injection_protection(self):
        result = markdown_to_storage("```python\ncode]]>evil\n```")
        assert "]]]]><![CDATA[>" in result  # escape technique applied
        assert "]]>evil" not in result       # raw injection sequence neutralized

    def test_lang_xml_injection(self):
        result = markdown_to_storage("```python<evil>\ncode\n```")
        assert "<evil>" not in result

    def test_table_wrapped_class(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = markdown_to_storage(md)
        assert 'class="wrapped"' in result

    def test_table_cell_wrapped_in_p(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = markdown_to_storage(md)
        assert "<td><p>1</p></td>" in result

    def test_confluence_link_restored(self):
        result = markdown_to_storage("[My Page](confluence://page/My%20Page)")
        assert 'ri:content-title="My Page"' in result
        assert "<ac:link>" in result

    def test_confluence_link_special_chars(self):
        result = markdown_to_storage('[My "Page"](confluence://page/My%20%22Page%22)')
        assert 'ri:content-title="My &quot;Page&quot;"' in result

    def test_nonhtml_placeholder_escaped(self):
        result = markdown_to_storage("The email is <computingId>@example.com")
        assert "<computingId>" not in result
        assert "&lt;computingId&gt;" in result

    def test_known_html_tags_not_escaped(self):
        result = markdown_to_storage("Hello **world** and `code`")
        assert "&lt;strong&gt;" not in result
        assert "&lt;code&gt;" not in result


class TestImages:
    BASE = "https://confluence.example.com"
    PAGE = "123456"

    def test_pull_attachment_image(self):
        storage = (
            '<ac:image ac:height="507" ac:width="3309">'
            '<ri:attachment ri:filename="auth-flows.png" />'
            "</ac:image>"
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        assert "![auth-flows.png]" in result
        assert f"{self.BASE}/download/attachments/{self.PAGE}/auth-flows.png" in result

    def test_pull_attachment_image_filename_url_encoded(self):
        storage = (
            '<ac:image>'
            '<ri:attachment ri:filename="my file.png" />'
            "</ac:image>"
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        assert "my%20file.png" in result

    def test_pull_external_url_image(self):
        storage = (
            "<ac:image>"
            '<ri:url ri:value="https://example.com/diagram.png" />'
            "</ac:image>"
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        assert "![diagram.png](https://example.com/diagram.png)" in result

    def test_pull_image_without_base_url(self):
        storage = (
            "<ac:image>"
            '<ri:attachment ri:filename="shot.png" />'
            "</ac:image>"
        )
        result = storage_to_markdown(storage)
        assert "![shot.png](shot.png)" in result

    def test_pull_image_is_not_merged_with_adjacent_text(self):
        storage = (
            "<p>Before</p>"
            "<ac:image>"
            '<ri:attachment ri:filename="fig.png" />'
            "</ac:image>"
            "<p>After</p>"
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        img_pos = result.index("![fig.png]")
        before_pos = result.index("Before")
        after_pos = result.index("After")
        assert before_pos < img_pos < after_pos

    def test_pull_layout_macro_content_preserved(self):
        storage = (
            "<ac:layout>"
            '<ac:layout-section ac:type="single">'
            "<ac:layout-cell>"
            "<h2>How It Works</h2>"
            "<p>Explanation here.</p>"
            "</ac:layout-cell>"
            "</ac:layout-section>"
            "</ac:layout>"
        )
        result = storage_to_markdown(storage)
        assert "How It Works" in result
        assert "Explanation here" in result
        assert "ac:layout" not in result

    def test_pull_centered_paragraph_promotes_align(self):
        storage = (
            '<p style="text-align: center;">'
            '<ac:image ac:width="750">'
            '<ri:attachment ri:filename="fig.png" />'
            '</ac:image></p>'
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        assert "ac:align=center" in result

    def test_pull_centered_paragraph_round_trip(self):
        storage = (
            '<p style="text-align: center;">'
            '<ac:image ac:width="750">'
            '<ri:attachment ri:filename="fig.png" />'
            '</ac:image></p>'
        )
        md = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        result = markdown_to_storage(md, base_url=self.BASE, page_id=self.PAGE)
        assert 'ac:align="center"' in result
        assert 'ac:width="750"' in result

    def test_pull_image_with_title_caption(self):
        storage = (
            '<ac:image ac:title="The authentication flows panel." ac:width="750">'
            '<ri:attachment ri:filename="auth.png" />'
            '</ac:image>'
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        assert "ac:title=The%20authentication%20flows%20panel." in result

    def test_push_image_title_restored(self):
        storage = (
            '<ac:image ac:title="The authentication flows panel." ac:width="750">'
            '<ri:attachment ri:filename="auth.png" />'
            '</ac:image>'
        )
        md = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        result = markdown_to_storage(md, base_url=self.BASE, page_id=self.PAGE)
        assert 'ac:title="The authentication flows panel."' in result

    def test_pull_image_attrs_encoded_in_title(self):
        storage = (
            '<ac:image ac:height="507" ac:width="3309" ac:align="center">'
            '<ri:attachment ri:filename="fig.png" />'
            "</ac:image>"
        )
        result = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        assert 'ac:height=507' in result
        assert 'ac:width=3309' in result
        assert 'ac:align=center' in result

    def test_push_attachment_image(self):
        md = f"![auth-flows.png]({self.BASE}/download/attachments/{self.PAGE}/auth-flows.png)"
        result = markdown_to_storage(md, base_url=self.BASE, page_id=self.PAGE)
        assert '<ac:image>' in result
        assert '<ri:attachment ri:filename="auth-flows.png"' in result
        assert "<ri:url" not in result

    def test_push_image_attrs_restored(self):
        storage = (
            '<ac:image ac:height="507" ac:width="3309" ac:align="center">'
            '<ri:attachment ri:filename="fig.png" />'
            "</ac:image>"
        )
        md = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        result = markdown_to_storage(md, base_url=self.BASE, page_id=self.PAGE)
        assert 'ac:height="507"' in result
        assert 'ac:width="3309"' in result
        assert 'ac:align="center"' in result

    def test_push_external_url_image(self):
        result = markdown_to_storage(
            "![diagram.png](https://example.com/diagram.png)",
            base_url=self.BASE,
            page_id=self.PAGE,
        )
        assert '<ac:image>' in result
        assert '<ri:url ri:value="https://example.com/diagram.png"' in result
        assert "<ri:attachment" not in result

    def test_image_round_trip(self):
        storage = (
            "<ac:image>"
            '<ri:attachment ri:filename="screenshot.png" />'
            "</ac:image>"
        )
        md = storage_to_markdown(storage, base_url=self.BASE, page_id=self.PAGE)
        result = markdown_to_storage(md, base_url=self.BASE, page_id=self.PAGE)
        assert '<ri:attachment ri:filename="screenshot.png"' in result


class TestPanels:
    def test_pull_note_panel(self):
        storage = (
            '<ac:structured-macro ac:name="note" ac:schema-version="1">'
            '<ac:rich-text-body><p>Be careful here.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "[!NOTE]" in result
        assert "Be careful here" in result
        assert "ac:structured-macro" not in result

    def test_pull_info_panel(self):
        storage = (
            '<ac:structured-macro ac:name="info" ac:schema-version="1">'
            '<ac:rich-text-body><p>Helpful info.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "[!INFO]" in result

    def test_pull_warning_panel(self):
        storage = (
            '<ac:structured-macro ac:name="warning" ac:schema-version="1">'
            '<ac:rich-text-body><p>Watch out.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "[!WARNING]" in result

    def test_pull_tip_panel(self):
        storage = (
            '<ac:structured-macro ac:name="tip" ac:schema-version="1">'
            '<ac:rich-text-body><p>Pro tip.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "[!TIP]" in result

    def test_push_note_panel_inline(self):
        md = "> [!NOTE]\n> Be careful here."
        result = markdown_to_storage(md)
        assert 'ac:name="note"' in result
        assert "Be careful here" in result
        assert "<ac:rich-text-body>" in result

    def test_push_note_panel_block(self):
        md = "> [!NOTE]\n>\n> Be careful here."
        result = markdown_to_storage(md)
        assert 'ac:name="note"' in result
        assert "Be careful here" in result

    def test_panel_round_trip(self):
        storage = (
            '<ac:structured-macro ac:name="note" ac:schema-version="1">'
            '<ac:rich-text-body><p>Remember this.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        md = storage_to_markdown(storage)
        result = markdown_to_storage(md)
        assert 'ac:name="note"' in result
        assert "Remember this" in result

    def test_trailing_backslash_stripped_on_push(self):
        md = "Step one.\\\nStep two."
        result = markdown_to_storage(md)
        assert "\\" not in result.replace("\\\\", "")  # no literal backslashes in output

    def test_indented_backslash_line_does_not_become_code_block(self):
        # Two-digit numbered list items require 4-space continuation indentation,
        # which equals the code block threshold. A blank line before the image
        # (produced by stripping a "    \" continuation line) must not cause the
        # image to be rendered as a code block outside the list.
        md = "11. Navigate to the tab.\\\n    \\\n    ![screenshot.png](https://example.com/img.png)\n12. Next step."
        result = markdown_to_storage(md)
        assert "ac:structured-macro" not in result or "ac:name=\"code\"" not in result
        assert "<ol>" in result
        assert "ac:image" in result or "img.png" in result
        # Both items must be in the same list, not split by a code block
        ol_start = result.index("<ol>")
        assert "Navigate to the tab" in result[ol_start:]
        assert "Next step" in result[ol_start:]


class TestTOC:
    def test_pull_toc_self_closing(self):
        storage = '<ac:structured-macro ac:name="toc" ac:schema-version="1" ac:macro-id="abc123" />'
        result = storage_to_markdown(storage)
        assert "[TOC]" in result

    def test_pull_toc_does_not_eat_following_content(self):
        # The self-closing TOC macro must not consume everything up to the next
        # </ac:structured-macro> — the original data-loss bug.
        storage = (
            '<ac:structured-macro ac:name="toc" ac:schema-version="1" ac:macro-id="abc" />'
            '<h2>Section Heading</h2>'
            '<p>Paragraph text.</p>'
            '<ac:structured-macro ac:name="noformat">'
            '<ac:plain-text-body><![CDATA[some code]]></ac:plain-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "[TOC]" in result
        assert "Section Heading" in result
        assert "Paragraph text" in result
        assert "some code" in result

    def test_push_toc_placeholder(self):
        result = markdown_to_storage("[TOC]")
        assert 'ac:name="toc"' in result

    def test_toc_round_trip(self):
        storage = '<ac:structured-macro ac:name="toc" ac:schema-version="1" />'
        md = storage_to_markdown(storage)
        result = markdown_to_storage(md)
        assert 'ac:name="toc"' in result


class TestNoformat:
    def test_pull_noformat_macro(self):
        storage = (
            '<ac:structured-macro ac:name="noformat">'
            '<ac:plain-text-body><![CDATA[raw text here]]></ac:plain-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "raw text here" in result

    def test_pull_noformat_with_schema_attrs(self):
        storage = (
            '<ac:structured-macro ac:name="noformat" ac:schema-version="1" ac:macro-id="a5d2">'
            '<ac:plain-text-body><![CDATA[template text]]></ac:plain-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "template text" in result

    def test_push_noformat_block(self):
        md = "```noformat\nraw text here\n```"
        result = markdown_to_storage(md)
        assert 'ac:name="noformat"' in result
        assert "raw text here" in result
        assert "<ac:plain-text-body>" in result

    def test_noformat_round_trip(self):
        storage = (
            '<ac:structured-macro ac:name="noformat">'
            '<ac:plain-text-body><![CDATA[some raw text]]></ac:plain-text-body>'
            '</ac:structured-macro>'
        )
        md = storage_to_markdown(storage)
        result = markdown_to_storage(md)
        assert 'ac:name="noformat"' in result
        assert "some raw text" in result


class TestExpand:
    def test_pull_expand_macro(self):
        storage = (
            '<ac:structured-macro ac:name="expand">'
            '<ac:parameter ac:name="title">Click to expand</ac:parameter>'
            '<ac:rich-text-body><p>Hidden content here.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "[!EXPAND]" in result
        assert "Click to expand" in result
        assert "Hidden content here" in result

    def test_pull_expand_with_schema_attrs(self):
        storage = (
            '<ac:structured-macro ac:name="expand" ac:schema-version="1" ac:macro-id="abc">'
            '<ac:parameter ac:name="title">Details</ac:parameter>'
            '<ac:rich-text-body><p>Detail text.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        result = storage_to_markdown(storage)
        assert "Details" in result
        assert "Detail text" in result

    def test_push_expand_block(self):
        md = "> [!EXPAND] My Section\n>\n> Some content here."
        result = markdown_to_storage(md)
        assert 'ac:name="expand"' in result
        assert "My Section" in result
        assert "Some content here" in result

    def test_push_expand_inline(self):
        md = "> [!EXPAND] My Section\n> Some content here."
        result = markdown_to_storage(md)
        assert 'ac:name="expand"' in result
        assert "My Section" in result

    def test_expand_round_trip(self):
        storage = (
            '<ac:structured-macro ac:name="expand">'
            '<ac:parameter ac:name="title">Details</ac:parameter>'
            '<ac:rich-text-body><p>Some detail text.</p></ac:rich-text-body>'
            '</ac:structured-macro>'
        )
        md = storage_to_markdown(storage)
        result = markdown_to_storage(md)
        assert 'ac:name="expand"' in result
        assert "Details" in result
        assert "Some detail text" in result


class TestLocalImgDir:
    def test_pull_uses_local_path_when_file_exists(self, tmp_path):
        img_dir = tmp_path / "img"
        img_dir.mkdir()
        (img_dir / "screenshot.png").write_bytes(b"fake")
        storage = (
            '<ac:image ac:width="800">'
            '<ri:attachment ri:filename="screenshot.png" />'
            '</ac:image>'
        )
        result = storage_to_markdown(
            storage,
            base_url="https://confluence.example.com",
            page_id="123",
            img_dir=str(img_dir),
        )
        assert str(img_dir / "screenshot.png") in result
        assert "download/attachments" not in result

    def test_pull_falls_back_to_confluence_url_when_missing(self):
        storage = (
            '<ac:image>'
            '<ri:attachment ri:filename="missing.png" />'
            '</ac:image>'
        )
        result = storage_to_markdown(
            storage,
            base_url="https://confluence.example.com",
            page_id="123",
            img_dir="/tmp/nonexistent_dir_for_csync_test",
        )
        assert "download/attachments" in result

    def test_pull_no_img_dir_uses_confluence_url(self):
        storage = (
            '<ac:image>'
            '<ri:attachment ri:filename="fig.png" />'
            '</ac:image>'
        )
        result = storage_to_markdown(
            storage,
            base_url="https://confluence.example.com",
            page_id="123",
        )
        assert "download/attachments" in result


class TestRoundTrip:
    def test_code_block_indentation(self):
        original = "```yaml\nkey:\n  nested:\n    deep: value\n```"
        storage = markdown_to_storage(original)
        result = storage_to_markdown(storage)
        assert "  nested:" in result
        assert "    deep: value" in result

    def test_confluence_page_link(self):
        original = "[Some Page](confluence://page/Some%20Page)"
        storage = markdown_to_storage(original)
        result = storage_to_markdown(storage)
        assert "[Some Page](confluence://page/Some%20Page)" in result

    def test_jira_link(self):
        original = "[IDP-123](https://jira.example.com/browse/IDP-123)"
        storage = markdown_to_storage(original)
        result = storage_to_markdown(storage, jira_url="https://jira.example.com")
        assert "[IDP-123](https://jira.example.com/browse/IDP-123)" in result


class TestRelativeLinkResolution:
    def _config(self, tmp_path, pages):
        return {
            "_config_dir": str(tmp_path),
            "confluence_url": "https://confluence.example.com",
            "pages": pages,
        }

    def test_relative_link_with_title_becomes_confluence_link(self, tmp_path):
        config = self._config(tmp_path, [
            {"page_id": "111222", "file_path": "docs/ci/auth.md", "title": "Auth Integrations"},
        ])
        current = tmp_path / "docs" / "containerization.md"
        body = "[Auth Repo](ci/auth.md)"
        result = _resolve_relative_md_links(body, current, config)
        assert "confluence://page/Auth%20Integrations" in result
        assert "ci/auth.md" not in result

    def test_relative_link_without_title_uses_page_id_url(self, tmp_path):
        config = self._config(tmp_path, [
            {"page_id": "111222", "file_path": "docs/ci/auth.md", "title": None},
        ])
        current = tmp_path / "docs" / "containerization.md"
        body = "[Auth Repo](ci/auth.md)"
        result = _resolve_relative_md_links(body, current, config)
        assert "111222" in result
        assert "confluence.example.com" in result

    def test_relative_link_to_untracked_file_unchanged(self, tmp_path):
        config = self._config(tmp_path, [])
        current = tmp_path / "docs" / "containerization.md"
        body = "[Other](ci/untracked.md)"
        result = _resolve_relative_md_links(body, current, config)
        assert result == body

    def test_external_link_unchanged(self, tmp_path):
        config = self._config(tmp_path, [
            {"page_id": "1", "file_path": "docs/page.md", "title": "Page"},
        ])
        current = tmp_path / "docs" / "other.md"
        body = "[External](https://example.com/page.md)"
        result = _resolve_relative_md_links(body, current, config)
        assert result == body

    def test_image_links_unchanged(self, tmp_path):
        config = self._config(tmp_path, [
            {"page_id": "1", "file_path": "docs/ci/fig.md", "title": "Fig"},
        ])
        current = tmp_path / "docs" / "page.md"
        body = "![alt text](ci/fig.md)"
        result = _resolve_relative_md_links(body, current, config)
        assert result == body

    def test_dotdot_relative_path_resolved(self, tmp_path):
        config = self._config(tmp_path, [
            {"page_id": "999", "file_path": "docs/overview.md", "title": "Overview"},
        ])
        current = tmp_path / "docs" / "ci" / "auth.md"
        body = "[Overview](../overview.md)"
        result = _resolve_relative_md_links(body, current, config)
        assert "confluence://page/Overview" in result

    def test_non_md_links_unchanged(self, tmp_path):
        config = self._config(tmp_path, [])
        current = tmp_path / "docs" / "page.md"
        body = "[PDF](report.pdf)"
        result = _resolve_relative_md_links(body, current, config)
        assert result == body


class TestFrontMatter:
    def test_parse_normal(self):
        text = "---\nconfluence_page_id: '123'\nconfluence_version: 5\ntitle: My Page\n---\n\nbody"
        fm, body = _parse_front_matter(text)
        assert fm["confluence_page_id"] == "123"
        assert fm["confluence_version"] == 5
        assert fm["title"] == "My Page"
        assert body == "body"

    def test_parse_missing(self):
        fm, body = _parse_front_matter("just a body")
        assert fm == {}
        assert body == "just a body"

    def test_write_round_trip_with_special_chars(self):
        fm = {"confluence_page_id": "456", "confluence_version": 3, "title": 'My "Quoted" Title'}
        body = "# Heading\n\nSome text."
        result = _write_front_matter(fm, body)
        parsed_fm, parsed_body = _parse_front_matter(result)
        assert parsed_fm["title"] == 'My "Quoted" Title'
        assert parsed_body == body


class TestConversionHelperEdgeCases:
    def test_replace_code_macro_no_body_returns_empty(self):
        result = _replace_code_macro('<ac:structured-macro ac:name="code"></ac:structured-macro>')
        assert result == ""

    def test_replace_noformat_macro_no_body_returns_empty(self):
        result = _replace_noformat_macro('<ac:structured-macro ac:name="noformat"></ac:structured-macro>')
        assert result == ""

    def test_replace_jira_macro_no_key_returns_empty(self):
        result = _replace_jira_macro(
            '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="other">value</ac:parameter></ac:structured-macro>',
            None,
        )
        assert result == ""

    def test_replace_image_macro_no_url_returns_empty(self):
        result = _replace_image_macro("", "<p>no attachment or url here</p>", None, None)
        assert result == ""

    def test_replace_pre_no_language_class(self):
        # Fenced code block with no language produces <pre><code>...</code></pre> (no class).
        # This hits the else branch in replace_pre where lang defaults to "none".
        result = markdown_to_storage("```\nplain code here\n```")
        assert 'ac:name="code"' in result
        assert "plain code here" in result


class TestEnsureGitignore:
    def test_creates_new_gitignore(self, tmp_path):
        gp = tmp_path / ".gitignore"
        _ensure_gitignore(gp, [".csync.env"])
        assert ".csync.env" in gp.read_text()

    def test_appends_to_existing_gitignore(self, tmp_path):
        gp = tmp_path / ".gitignore"
        gp.write_text("node_modules/\n")
        _ensure_gitignore(gp, [".csync.env"])
        content = gp.read_text()
        assert "node_modules/" in content
        assert ".csync.env" in content

    def test_skips_already_present_entries(self, tmp_path, capsys):
        gp = tmp_path / ".gitignore"
        gp.write_text(".csync.env\n")
        _ensure_gitignore(gp, [".csync.env"])
        captured = capsys.readouterr()
        assert "Added" not in captured.out

    def test_adds_newline_before_entries_when_no_trailing_newline(self, tmp_path):
        gp = tmp_path / ".gitignore"
        gp.write_text("existing")
        _ensure_gitignore(gp, [".csync.env"])
        content = gp.read_text()
        assert "existing\n" in content


class TestCmdInit:
    def test_creates_yaml_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".py-conf-sync.config.yaml"
        args = argparse.Namespace(_config_path=config_path, force=False)
        cmd_init(args)
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert "confluence_url" in data
        assert "pages" in data

    def test_creates_json_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".py-conf-sync.config.json"
        args = argparse.Namespace(_config_path=config_path, force=False)
        cmd_init(args)
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "confluence_url" in data

    def test_skips_existing_without_force(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".py-conf-sync.config.yaml"
        config_path.write_text("confluence_url: https://old.example.com\n")
        args = argparse.Namespace(_config_path=config_path, force=False)
        cmd_init(args)
        captured = capsys.readouterr()
        assert "skip" in captured.out
        assert "old.example.com" in config_path.read_text()

    def test_overwrites_with_force(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".py-conf-sync.config.yaml"
        config_path.write_text("confluence_url: https://old.example.com\n")
        args = argparse.Namespace(_config_path=config_path, force=True)
        cmd_init(args)
        data = yaml.safe_load(config_path.read_text())
        assert data["confluence_url"] == "https://confluence.example.com"

    def test_creates_gitignore(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".py-conf-sync.config.yaml"
        args = argparse.Namespace(_config_path=config_path, force=False)
        cmd_init(args)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".csync.env" in gitignore.read_text()


class TestCmdAdd:
    def _make_config(self, tmp_path, pages=None):
        path = tmp_path / ".py-conf-sync.config.yaml"
        save_config({"confluence_url": "https://confluence.example.com", "pages": pages or []}, path)
        return path

    def test_adds_page_entry(self, tmp_path):
        config_path = self._make_config(tmp_path)
        args = argparse.Namespace(_config_path=config_path, page_id="99999", file_path="docs/new.md", title=None)
        cmd_add(args)
        config = load_config(config_path)
        assert any(str(e["page_id"]) == "99999" for e in config["pages"])

    def test_adds_page_with_title(self, tmp_path):
        config_path = self._make_config(tmp_path)
        args = argparse.Namespace(_config_path=config_path, page_id="88888", file_path="docs/titled.md", title="My Title")
        cmd_add(args)
        config = load_config(config_path)
        entry = next(e for e in config["pages"] if str(e["page_id"]) == "88888")
        assert entry["title"] == "My Title"

    def test_skips_duplicate_page_id(self, tmp_path, capsys):
        config_path = self._make_config(tmp_path, [{"page_id": "77777", "file_path": "docs/existing.md"}])
        args = argparse.Namespace(_config_path=config_path, page_id="77777", file_path="docs/other.md", title=None)
        cmd_add(args)
        captured = capsys.readouterr()
        assert "skip" in captured.out
        config = load_config(config_path)
        assert len([e for e in config["pages"] if str(e["page_id"]) == "77777"]) == 1


class TestCmdRemove:
    def _make_config(self, tmp_path, pages):
        path = tmp_path / ".py-conf-sync.config.yaml"
        save_config({"confluence_url": "https://confluence.example.com", "pages": pages}, path)
        return path

    def test_removes_existing_page(self, tmp_path):
        config_path = self._make_config(tmp_path, [
            {"page_id": "11111", "file_path": "docs/a.md"},
            {"page_id": "22222", "file_path": "docs/b.md"},
        ])
        args = argparse.Namespace(_config_path=config_path, page_id="11111")
        cmd_remove(args)
        config = load_config(config_path)
        assert not any(str(e["page_id"]) == "11111" for e in config["pages"])
        assert any(str(e["page_id"]) == "22222" for e in config["pages"])

    def test_exits_on_missing_page_id(self, tmp_path):
        config_path = self._make_config(tmp_path, [{"page_id": "11111", "file_path": "docs/a.md"}])
        args = argparse.Namespace(_config_path=config_path, page_id="99999")
        with pytest.raises(SystemExit):
            cmd_remove(args)


class TestLoadSaveConfig:
    def test_load_yaml(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("confluence_url: https://example.com\npages: []\n")
        config = load_config(path)
        assert config["confluence_url"] == "https://example.com"
        assert config["_config_dir"] == tmp_path

    def test_load_json(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"confluence_url": "https://example.com", "pages": []}\n')
        config = load_config(path)
        assert config["confluence_url"] == "https://example.com"

    def test_save_yaml(self, tmp_path):
        path = tmp_path / "config.yaml"
        save_config({"confluence_url": "https://example.com", "pages": []}, path)
        data = yaml.safe_load(path.read_text())
        assert data["confluence_url"] == "https://example.com"
        assert "_config_dir" not in data

    def test_save_json(self, tmp_path):
        path = tmp_path / "config.json"
        save_config({"confluence_url": "https://example.com", "pages": [], "_config_dir": "/tmp"}, path)
        data = json.loads(path.read_text())
        assert data["confluence_url"] == "https://example.com"
        assert "_config_dir" not in data

    def test_load_missing_config_exits(self, tmp_path):
        path = tmp_path / "nonexistent.yaml"
        with pytest.raises(SystemExit):
            load_config(path)
