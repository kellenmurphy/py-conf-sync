import pytest
from py_conf_sync import (
    storage_to_markdown,
    markdown_to_storage,
    _parse_front_matter,
    _write_front_matter,
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
