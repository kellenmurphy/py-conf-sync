import pytest
from pathlib import Path
from py_conf_sync import (
    storage_to_markdown,
    markdown_to_storage,
    _parse_front_matter,
    _write_front_matter,
    _resolve_relative_md_links,
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
