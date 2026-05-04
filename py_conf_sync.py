#!/usr/bin/env python3
"""
py-conf-sync: Keep Confluence Data Center pages in sync with Markdown files in a git repo.

Usage:
    python py_conf_sync.py [--config PATH] pull [--page PAGE_ID] [--dry-run]
    python py_conf_sync.py [--config PATH] push [--page PAGE_ID] [--dry-run]
    python py_conf_sync.py [--config PATH] status
    python py_conf_sync.py [--config PATH] add <page_id> <file_path>
    python py_conf_sync.py scan <repo_path> [--output PATH] [--url URL] [--exclude REGEX]
"""

import argparse
import html as html_lib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote

import requests
import yaml
from markdownify import markdownify as md
from dotenv import load_dotenv

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_FILE = Path(".py-conf-sync.config.yaml")


def _find_env_file() -> Path | None:
    """Search for .csync.env in order: home dir, cwd (target repo), script dir."""
    candidates = [
        Path.home() / ".csync.env",
        Path.cwd() / ".csync.env",
        Path(__file__).parent / ".csync.env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_config(path: Path) -> dict:
    p = path.resolve()
    if not p.exists():
        print(f"[error] {p} not found. Run 'init' or create it manually.")
        sys.exit(1)
    with open(p) as f:
        if p.suffix == ".json":
            config = json.load(f)
        else:
            config = yaml.safe_load(f) or {}
    config["_config_dir"] = p.parent
    return config


def save_config(config: dict, path: Path):
    to_save = {k: v for k, v in config.items() if not k.startswith("_")}
    with open(path.resolve(), "w") as f:
        if path.suffix == ".json":
            json.dump(to_save, f, indent=2)
            f.write("\n")
        else:
            yaml.dump(to_save, f, default_flow_style=False, sort_keys=False)


def _file_path(entry: dict, config: dict) -> Path:
    """Resolve entry file_path relative to the config file's directory."""
    fp = Path(entry["file_path"])
    if fp.is_absolute():
        return fp
    return Path(config["_config_dir"]) / fp


# ---------------------------------------------------------------------------
# Confluence API client
# ---------------------------------------------------------------------------

class ConfluenceClient:
    def __init__(self, base_url: str, token: str = None, username: str = None, password: str = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            self.session.auth = (username, password)
        else:
            print("[error] No credentials found. Set CONFLUENCE_TOKEN in .csync.env")
            sys.exit(1)

        self.session.headers["Content-Type"] = "application/json"

    def get_page(self, page_id: str) -> dict:
        url = f"{self.base_url}/rest/api/content/{page_id}"
        resp = self.session.get(url, params={"expand": "body.storage,version,title"})
        resp.raise_for_status()
        return resp.json()

    def update_page(self, page_id: str, title: str, storage_body: str, version: int) -> dict:
        url = f"{self.base_url}/rest/api/content/{page_id}"
        payload = {
            "version": {"number": version},
            "title": title,
            "type": "page",
            "body": {
                "storage": {
                    "value": storage_body,
                    "representation": "storage",
                }
            },
        }
        resp = self.session.put(url, data=json.dumps(payload))
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Format conversion
# ---------------------------------------------------------------------------

_MACRO_RE = re.compile(r"<ac:[^>]+>.*?</ac:[^>]+>|<ac:[^/]*/?>", re.DOTALL)
_RI_TAG_RE = re.compile(r"<ri:[^>]+/?>", re.DOTALL)
_CODE_MACRO_RE = re.compile(
    r'<ac:structured-macro[^>]*ac:name="code"[^>]*>.*?</ac:structured-macro>',
    re.DOTALL,
)
_CODE_LANG_RE = re.compile(r'<ac:parameter ac:name="language">([^<]*)</ac:parameter>')
_CODE_BODY_RE = re.compile(r'<ac:plain-text-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-body>', re.DOTALL)
_JIRA_MACRO_RE = re.compile(
    r'<ac:structured-macro[^>]*ac:name="jira"[^>]*>.*?</ac:structured-macro>',
    re.DOTALL,
)
_JIRA_KEY_RE = re.compile(r'<ac:parameter ac:name="key">([^<]+)</ac:parameter>')
_JIRA_KEY_BARE_RE = re.compile(r'<ac:parameter ac:name="">([A-Z]+-\d+)</ac:parameter>')
_AC_LINK_RE = re.compile(
    r'<ac:link[^>]*>.*?<ri:page[^>]*ri:content-title="([^"]+)"[^>]*/?>.*?</ac:link>',
    re.DOTALL,
)
_TRAILING_BR_RE = re.compile(r'(\s*<br\s*/?>)+(?=\s*</)', re.IGNORECASE)
# Confluence wraps <li> content in <p> for "loose" lists; strip that wrapping so
# markdownify produces tight lists with proper nesting instead of blank-line-separated items.
_LI_P_UNWRAP_RE = re.compile(r'(<li[^>]*>)\s*<p>(.*?)</p>(?=\s*(?:</li>|<ul))', re.DOTALL)


def _replace_code_macro(macro_html: str) -> str:
    lang_match = _CODE_LANG_RE.search(macro_html)
    body_match = _CODE_BODY_RE.search(macro_html)
    if not body_match:
        return ""
    lang = (lang_match.group(1).strip() if lang_match else "").lower()
    if lang in ("none", "text", "plain text", ""):
        lang = ""
    lang = html_lib.escape(lang, quote=True)
    code = html_lib.escape(body_match.group(1))
    lang_class = f' class="language-{lang}"' if lang else ""
    return f"<pre><code{lang_class}>{code}</code></pre>"


def _code_language_callback(el) -> str | None:
    # markdownify passes the <pre> element; the language class is on the <code> child.
    code = el.find("code")
    for cls in (code.get("class") if code else []) or []:
        if cls.startswith("language-"):
            return cls[len("language-"):]
    return None


def _replace_jira_macro(macro_html: str, jira_url: str | None) -> str:
    m = _JIRA_KEY_RE.search(macro_html) or _JIRA_KEY_BARE_RE.search(macro_html)
    if not m:
        return ""
    key = m.group(1).strip()
    if jira_url:
        return f"[{key}]({jira_url.rstrip('/')}/browse/{key})"
    return key


def storage_to_markdown(storage_html: str, jira_url: str | None = None) -> str:
    # TODO: add round-trip support for info/note/warning/tip panels
    #       (ac:structured-macro ac:name="info|note|warning|tip") →
    #       blockquote with a prefix marker, restored on push.
    # TODO: add round-trip support for status badges
    #       (ac:structured-macro ac:name="status") →
    #       inline marker e.g. `[STATUS:colour:label]`, restored on push.
    cleaned = _CODE_MACRO_RE.sub(lambda m: _replace_code_macro(m.group(0)), storage_html)
    cleaned = _JIRA_MACRO_RE.sub(lambda m: _replace_jira_macro(m.group(0), jira_url), cleaned)
    def _replace_ac_link(m):
        title = html_lib.unescape(m.group(1))
        return f"[{title}](confluence://page/{quote(title, safe='')})"

    cleaned = _AC_LINK_RE.sub(_replace_ac_link, cleaned)
    cleaned = _TRAILING_BR_RE.sub("", cleaned)
    cleaned = _LI_P_UNWRAP_RE.sub(r'\1\2', cleaned)
    cleaned = _MACRO_RE.sub("", cleaned)
    cleaned = _RI_TAG_RE.sub("", cleaned)
    result = md(
        cleaned,
        heading_style="ATX",
        bullets="-",
        code_language_callback=_code_language_callback,
        newline_style="backslash",
    )
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def markdown_to_storage(markdown_text: str) -> str:
    try:
        import markdown as mdlib
    except ImportError:
        print("[error] 'markdown' package not installed. Run: pip install markdown")
        sys.exit(1)

    extensions = ["tables", "fenced_code", "attr_list", "nl2br"]
    # tab_length=2 matches markdownify's 2-space list indentation so nested
    # lists survive the round-trip without being flattened.
    html = mdlib.markdown(markdown_text, extensions=extensions, tab_length=2)

    html = re.sub(r"<br>", "<br />", html)
    html = re.sub(r"<hr>", "<hr />", html)

    def replace_pre(m):
        inner = m.group(1)
        lang_match = re.match(r'<code class="language-([^"]+)">(.*)</code>', inner, re.DOTALL)
        if lang_match:
            lang, code = lang_match.groups()
            lang = html_lib.escape(lang, quote=True)
            code = _unescape_html(code)
        else:
            lang = "none"
            code_match = re.match(r"<code>(.*)</code>", inner, re.DOTALL)
            code = _unescape_html(code_match.group(1)) if code_match else _unescape_html(inner)
        # Escape CDATA end sequence so user code can't break the CDATA block.
        code = code.replace("]]>", "]]]]><![CDATA[>")
        return (
            f'<ac:structured-macro ac:name="code">'
            f'<ac:parameter ac:name="language">{lang}</ac:parameter>'
            f'<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>'
            f"</ac:structured-macro>"
        )

    html = re.sub(r"<pre>(.*?)</pre>", replace_pre, html, flags=re.DOTALL)

    # Match Confluence's native table structure: class="wrapped" on the table,
    # and every th/td cell content wrapped in <p>.
    html = re.sub(r"<table>", '<table class="wrapped">', html)
    html = re.sub(r"<(th|td)>(.*?)</\1>", lambda m: f"<{m.group(1)}><p>{m.group(2)}</p></{m.group(1)}>", html, flags=re.DOTALL)

    def restore_conf_link(m):
        title = html_lib.escape(unquote(m.group(1)), quote=True)
        return f'<ac:link><ri:page ri:content-title="{title}" /></ac:link>'

    html = re.sub(
        r'<a href="confluence://page/([^"]+)">([^<]+)</a>',
        restore_conf_link,
        html,
    )
    return html


def _unescape_html(text: str) -> str:
    return html_lib.unescape(text)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    config_path = args._config_path
    if config_path.exists() and not args.force:
        print(f"[skip] {config_path} already exists (use --force to overwrite)")
    else:
        sample = {
            "confluence_url": "https://confluence.example.com",
            "pages": [
                {
                    "page_id": "123456",
                    "file_path": "docs/example-page.md",
                    "title": "Example Page",
                }
            ],
        }
        with open(config_path, "w") as f:
            if config_path.suffix == ".json":
                json.dump(sample, f, indent=2)
                f.write("\n")
            else:
                yaml.dump(sample, f, default_flow_style=False, sort_keys=False)
        print(f"[ok] Created {config_path}")

    _ensure_gitignore(Path(".gitignore"), [".csync.env", ".py-conf-sync.config.yaml"])


def _ensure_gitignore(gitignore_path: Path, entries: list[str]):
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    to_add = [e for e in entries if e not in existing.splitlines()]
    if not to_add:
        return
    with open(gitignore_path, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("# py-conf-sync — never commit credentials or local config\n")
        for entry in to_add:
            f.write(f"{entry}\n")
    print(f"[ok] Added to {gitignore_path}: {', '.join(to_add)}")


def cmd_add(args):
    config = load_config(args._config_path)
    entries = config.setdefault("pages", [])

    for e in entries:
        if str(e["page_id"]) == str(args.page_id):
            print(f"[skip] page_id {args.page_id} already in config")
            return

    entry = {"page_id": args.page_id, "file_path": args.file_path}
    if args.title:
        entry["title"] = args.title
    entries.append(entry)
    save_config(config, args._config_path)
    print(f"[ok] Added page {args.page_id} → {args.file_path}")


def cmd_remove(args):
    config = load_config(args._config_path)
    entries = config.get("pages", [])
    before = len(entries)
    config["pages"] = [e for e in entries if str(e.get("page_id")) != str(args.page_id)]
    if len(config["pages"]) == before:
        print(f"[error] page_id {args.page_id} not found in config")
        sys.exit(1)
    save_config(config, args._config_path)
    print(f"[ok] Removed page {args.page_id}")


def _get_client(config: dict, args) -> ConfluenceClient:
    env_file = _find_env_file()
    if not env_file:
        print("[error] No .csync.env found.")
        print("        Checked: ~/.csync.env, current directory, script directory.")
        print("        Run 'init' to create one. Preferred location: ~/.csync.env")
        sys.exit(1)
    load_dotenv(env_file)
    base_url = config.get("confluence_url")
    if not base_url:
        print("[error] confluence_url not set in config.")
        sys.exit(1)
    if not base_url.startswith("https://"):
        print("[error] confluence_url must use HTTPS — HTTP would expose credentials in plaintext.")
        sys.exit(1)

    token = os.getenv("CONFLUENCE_TOKEN")
    username = os.getenv("CONFLUENCE_USERNAME")
    password = os.getenv("CONFLUENCE_PASSWORD")

    if not token and (username or password):
        if not getattr(args, "unsafe_auth", False):
            print("[error] Basic auth credentials found but --unsafe-auth was not passed.")
            print("        Basic auth transmits your password in base64 and is not recommended.")
            print("        Use a Personal Access Token instead, or pass --unsafe-auth to proceed anyway.")
            sys.exit(1)

    return ConfluenceClient(
        base_url=base_url,
        token=token,
        username=username if getattr(args, "unsafe_auth", False) else None,
        password=password if getattr(args, "unsafe_auth", False) else None,
    )


def _resolve_pages(config: dict, page_id_filter: str = None) -> list:
    pages = [p for p in config.get("pages", []) if p.get("page_id")]
    if page_id_filter:
        pages = [p for p in pages if str(p["page_id"]) == str(page_id_filter)]
        if not pages:
            print(f"[error] page_id {page_id_filter} not found in config")
            sys.exit(1)
    return pages


def cmd_pull(args):
    config = load_config(args._config_path)
    client = _get_client(config, args)
    pages = _resolve_pages(config, args.page)

    for entry in pages:
        page_id = str(entry["page_id"])
        file_path = _file_path(entry, config)

        print(f"  pulling {page_id} → {file_path} ...", end=" ")

        try:
            page_data = client.get_page(page_id)
        except requests.HTTPError as e:
            print(f"FAILED ({e})")
            continue

        title = page_data["title"]
        storage_body = page_data["body"]["storage"]["value"]
        version = page_data["version"]["number"]

        if file_path.exists():
            existing_fm, _ = _parse_front_matter(file_path.read_text(encoding="utf-8"))
            local_version = existing_fm.get("confluence_version")
            if local_version and int(local_version) > version:
                if args.force:
                    print(f"CONFLICT (forced — local v{local_version} > remote v{version})", end=" ")
                else:
                    print(
                        f"CONFLICT — local v{local_version} > remote v{version}. "
                        "Local may have unpushed changes. Use --force to overwrite."
                    )
                    continue

        if args.debug:
            print(f"\n[warn] --debug dumps raw page content — do not share output publicly")
            print(f"\n--- raw storage: {page_id} ---\n{storage_body}\n--- end ---\n")

        markdown_text = storage_to_markdown(storage_body, jira_url=config.get("jira_url"))

        fm_data = {
            "confluence_page_id": str(page_id),
            "confluence_version": version,
            "title": title,
        }
        front_matter = "---\n" + yaml.dump(fm_data, default_flow_style=False, sort_keys=False) + "---\n\n"
        output = front_matter + f"# {title}\n\n" + markdown_text

        if args.dry_run:
            print("DRY RUN")
            print(output[:500])
        else:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(output, encoding="utf-8")
            if not entry.get("title"):
                entry["title"] = title
            print(f"ok (v{version}, {len(markdown_text)} chars)")

    if not args.dry_run:
        save_config(config, args._config_path)


def cmd_push(args):
    config = load_config(args._config_path)
    client = _get_client(config, args)
    pages = _resolve_pages(config, args.page)

    for entry in pages:
        page_id = str(entry["page_id"])
        file_path = _file_path(entry, config)

        print(f"  pushing {file_path} → {page_id} ...", end=" ")

        if not file_path.exists():
            print(f"SKIP (file not found: {file_path})")
            continue

        raw = file_path.read_text(encoding="utf-8")
        fm, body = _parse_front_matter(raw)
        local_version = fm.get("confluence_version")
        title = fm.get("title") or entry.get("title") or file_path.stem

        if not local_version:
            print("[warn] no confluence_version in front-matter — conflict detection skipped", end=" ")

        try:
            remote = client.get_page(page_id)
        except requests.HTTPError as e:
            print(f"FAILED fetching remote ({e})")
            continue

        remote_version = remote["version"]["number"]

        if local_version and int(local_version) < remote_version:
            if args.force:
                print(f"[warn] forcing push — local v{local_version} < remote v{remote_version}", end=" ")
            else:
                print(
                    f"CONFLICT — local v{local_version} < remote v{remote_version}. "
                    "Pull first, or use --force to overwrite."
                )
                continue

        body_for_conversion = re.sub(r"^#\s+.+\n", "", body, count=1).strip()
        storage_body = markdown_to_storage(body_for_conversion)
        new_version = remote_version + 1

        if args.dry_run:
            print(f"DRY RUN (would push v{new_version})")
            print(storage_body[:500])
        else:
            try:
                client.update_page(page_id, title, storage_body, new_version)
            except requests.HTTPError as e:
                print(f"FAILED ({e.response.text[:200]})")
                continue

            fm["confluence_version"] = new_version
            updated = _write_front_matter(fm, body)
            file_path.write_text(updated, encoding="utf-8")
            print(f"ok (now v{new_version})")


def cmd_status(args):
    config = load_config(args._config_path)
    pages = config.get("pages", [])
    if not pages:
        print("No pages configured. Run 'add' to register a page.")
        return

    print(f"{'PAGE ID':<15} {'FILE':<45} {'EXISTS':<8} TITLE")
    print("-" * 85)
    for entry in pages:
        page_id = str(entry.get("page_id") or "—")
        file_path = _file_path(entry, config)
        exists = "yes" if file_path.exists() else "no"
        title = entry.get("title") or "—"
        suffix = " [unmapped]" if not entry.get("page_id") else ""
        print(f"{page_id:<15} {str(entry['file_path']):<45} {exists:<8} {title}{suffix}")


def cmd_scan(args):
    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"[error] {repo_path} is not a directory")
        sys.exit(1)

    output_path = Path(args.output).resolve() if args.output else repo_path / ".confluence-sync.json"

    # Preserve existing mappings so a re-scan doesn't wipe page_id values
    existing_by_path: dict = {}
    existing_config: dict = {}
    if output_path.exists():
        with open(output_path) as f:
            existing_config = json.load(f)
        for p in existing_config.get("pages", []):
            existing_by_path[p["file_path"]] = p

    if args.exclude:
        try:
            exclude_re = re.compile(args.exclude)
        except re.error as e:
            print(f"[error] Invalid --exclude regex: {e}")
            sys.exit(1)
    else:
        exclude_re = None
    found_files = sorted(
        str(f.relative_to(repo_path))
        for f in repo_path.glob("**/*.md")
        if not exclude_re or not exclude_re.search(str(f.relative_to(repo_path)))
    )

    new_count = 0
    pages = []
    for rel_path in found_files:
        if rel_path in existing_by_path:
            pages.append(existing_by_path[rel_path])
        else:
            pages.append({"page_id": None, "file_path": rel_path, "title": None})
            new_count += 1

    mapped_count = sum(1 for p in pages if p.get("page_id"))
    confluence_url = existing_config.get("confluence_url") or args.url or "https://confluence.example.com"

    with open(output_path, "w") as f:
        json.dump({"confluence_url": confluence_url, "pages": pages}, f, indent=2)
        f.write("\n")

    print(f"Scanned {repo_path}")
    print(f"  {len(found_files)} markdown file(s) found")
    print(f"  {mapped_count} already mapped to Confluence pages")
    print(f"  {new_count} new (page_id is null)")
    print(f"\nMapping file: {output_path}")
    if new_count:
        print(f"\nEdit {output_path} to add page_id values, then:")
        print(f"  ./csync --config {output_path} pull")


# ---------------------------------------------------------------------------
# Front-matter helpers
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\n(.*?)\n---\n\n?", re.DOTALL)


def _parse_front_matter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if m:
        fm = yaml.safe_load(m.group(1)) or {}
        body = text[m.end():]
    else:
        fm = {}
        body = text
    return fm, body


def _write_front_matter(fm: dict, body: str) -> str:
    header = "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---\n\n"
    return header + body


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="py_conf_sync",
        description="Sync Confluence Data Center pages with Markdown files in a git repo.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Config file path (YAML or JSON; default: .py-conf-sync.config.yaml)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--unsafe-auth",
        action="store_true",
        default=False,
        help="Allow basic auth (username+password). PAT via CONFLUENCE_TOKEN is strongly preferred.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Create starter config and .env files")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing files")

    # add
    p_add = sub.add_parser("add", help="Register a page<->file mapping")
    p_add.add_argument("page_id", help="Confluence page ID")
    p_add.add_argument("file_path", help="Relative path to the Markdown file")
    p_add.add_argument("--title", help="Page title (optional, auto-detected on first pull)")

    # remove
    p_remove = sub.add_parser("remove", help="Remove a page<->file mapping from config")
    p_remove.add_argument("page_id", help="Confluence page ID to remove")

    # pull
    p_pull = sub.add_parser("pull", help="Pull pages from Confluence → Markdown files")
    p_pull.add_argument("--page", metavar="PAGE_ID", help="Only pull a specific page")
    p_pull.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    p_pull.add_argument("--force", action="store_true", help="Overwrite local file even if it is ahead of remote version")
    p_pull.add_argument("--debug", action="store_true", help="Dump raw storage HTML before conversion")

    # push
    p_push = sub.add_parser("push", help="Push Markdown files → Confluence pages")
    p_push.add_argument("--page", metavar="PAGE_ID", help="Only push a specific page")
    p_push.add_argument("--dry-run", action="store_true", help="Preview without making API calls")
    p_push.add_argument("--force", action="store_true", help="Overwrite remote even if it is ahead of local version")

    # status
    sub.add_parser("status", help="List registered pages and their local file status")

    # scan
    p_scan = sub.add_parser("scan", help="Scan a repo for Markdown files and build a JSON mapping")
    p_scan.add_argument("repo_path", help="Path to the repository to scan")
    p_scan.add_argument("--output", metavar="PATH", help="Output JSON file (default: <repo_path>/.confluence-sync.json)")
    p_scan.add_argument("--url", metavar="URL", help="Confluence base URL to embed in the mapping file")
    p_scan.add_argument("--exclude", metavar="REGEX", help="Exclude files whose relative path matches this regex")

    args = parser.parse_args()

    if args.command == "scan":
        args._config_path = None
    else:
        args._config_path = Path(args.config) if args.config else DEFAULT_CONFIG_FILE

    dispatch = {
        "init": cmd_init,
        "add": cmd_add,
        "remove": cmd_remove,
        "pull": cmd_pull,
        "push": cmd_push,
        "status": cmd_status,
        "scan": cmd_scan,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
