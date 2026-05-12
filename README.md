# py-conf-sync

[![Tests](https://github.com/kellenmurphy/py-conf-sync/actions/workflows/test.yml/badge.svg)](https://github.com/kellenmurphy/py-conf-sync/actions/workflows/test.yml)

Technical writers and engineers often face a choice: write docs in Confluence's editor
(where they live as rich pages, version-controlled by Confluence) or write them in
Markdown alongside code (where they benefit from git history, PR reviews, and real
editor tooling). py-conf-sync removes the tradeoff.

Pull any Confluence page down as a Markdown file, edit it with your normal tools and
workflow, commit it to git, then push it back. Confluence stays the published source of
truth; your local repo is where the work happens.

This is particularly useful for:

- **Runbooks and operational docs** that belong near the code they describe
- **Architecture and design documents** where review via pull request is more effective than Confluence comments
- **Teams already using git** who want Confluence as a publishing target, not an editing environment
- **Bulk or scripted updates** that are painful to make through a browser

py-conf-sync handles the Markdown ↔ Confluence storage format conversion, tracks page
versions for conflict detection, and runs entirely inside Docker so nothing is installed
on your machine.

## Setup

The recommended way to run this tool is via Docker — nothing is installed on your host machine.

**1. Set up credentials** (once, on each machine you work from):

```bash
cp .csync.env.example ~/.csync.env
# then edit ~/.csync.env and add your CONFLUENCE_TOKEN
```

See [Credentials](#credentials) for details.

**2. Initialize a repository:**

```bash
/path/to/csync init
```

`init` creates `.py-conf-sync.config.yaml` in the current directory. Edit it to set `confluence_url`
and register your page mappings.

If you prefer running directly on the host:

```bash
pip install -r requirements.txt
python py_conf_sync.py init
```

## Running with Docker

Use the `csync` wrapper instead of calling `python py_conf_sync.py` directly.
It builds the image on first use and mounts your current directory into the container.

```bash
./csync pull
./csync push --dry-run
./csync status
```

**Scanning another repository:**

```bash
./csync scan /path/to/other-repo
./csync --config /path/to/other-repo/.confluence-sync.json pull
```

Absolute paths in arguments are automatically mounted into the container, so
cross-repo operations work without any extra flags.

**After updating `py_conf_sync.py` or `requirements.txt`**, rebuild the image:

```bash
./csync --rebuild pull
```

Or rebuild explicitly without running a command:

```bash
./csync --rebuild status
```

## Commands

```
csync init              # Create .py-conf-sync.config.yaml (credentials are set up separately)

csync status            # List all registered pages

csync add <id> <path>   # Register a new page mapping
csync remove <id>       # Remove a page mapping from config

csync pull              # Pull all pages from Confluence
csync pull --page ID    # Pull a single page
csync pull --force      # Overwrite local file even if it is ahead of remote version

csync push              # Push all pages to Confluence
csync push --page ID    # Push a single page
csync push --force      # Push even if remote is ahead of local version

csync scan <repo>       # Scan a repo for Markdown files, generate a JSON mapping
```

All write commands accept `--dry-run` to preview without making changes.

The `--config` flag on any command points to a JSON or YAML config file:

```bash
csync --config /path/to/repo/.confluence-sync.json pull
```

## Workflow

```bash
# First time: pull everything down
./csync pull

# Edit locally with your preferred editor
vim docs/runbooks/deploy.md

# Commit to git
git add docs/runbooks/deploy.md
git commit -m "docs: update deploy runbook"

# Push back to Confluence
./csync push --page 345678
```

### Mapping an existing repo

```bash
# Scan a repo and generate a mapping file
./csync scan /path/to/my-docs-repo

# Edit the generated file to add page_id values
vim /path/to/my-docs-repo/.confluence-sync.json

# Pull all mapped pages
./csync --config /path/to/my-docs-repo/.confluence-sync.json pull
```

## Front-matter

Each Markdown file gets a YAML front-matter block on pull:

```yaml
---
confluence_page_id: "345678"
confluence_version: 12
title: "Deployment Runbook"
---
```

`confluence_version` is used on push to detect conflicts — if the remote version
is ahead of your local version, the push is blocked and you're told to pull first.

## Conflict detection

Conflicts are detected in both directions by comparing the `confluence_version` in
the local front-matter against the current remote version.

**Remote is ahead of local** (someone edited Confluence directly):

```
CONFLICT — local v12 < remote v15. Pull first, or use --force to overwrite.
```

Pull to get the latest, re-apply your changes, then push. To overwrite the remote
regardless (e.g. you intentionally reverted the page in Confluence):

```bash
./csync push --force --page 345678
```

**Local is ahead of remote** (e.g. Confluence page was reverted):

```
CONFLICT — local v10 > remote v8. Local may have unpushed changes. Use --force to overwrite.
```

To discard local changes and overwrite the local file with the current Confluence version:

```bash
./csync pull --force --page 345678
```

## Supported features

### Full round-trip (Markdown ↔ Confluence)

These convert cleanly in both directions. Markdown authored locally and pushed to
Confluence will render correctly, and pulling that page back produces the same Markdown.

| Feature | Markdown | Confluence storage |
|---|---|---|
| Headings | `#` / `##` / etc. | `<h1>` – `<h6>` |
| Paragraphs, bold, italic, inline code | Standard Markdown | `<p>`, `<strong>`, `<em>`, `<code>` |
| Fenced code blocks (with language) | ` ```python ``` ` | `ac:structured-macro ac:name="code"` with `language` parameter |
| Fenced code blocks (no language / noformat) | ` ```noformat ``` ` | `ac:structured-macro ac:name="noformat"` |
| Table of contents | `[TOC]` | `ac:structured-macro ac:name="toc"` |
| Collapsible expand sections | `> [!EXPAND] Title` blockquote | `ac:structured-macro ac:name="expand"` |
| Tables | GFM pipe tables | `<table class="wrapped">` |
| Ordered and unordered lists (nested) | `1.` / `-` with 2-space indent | `<ol>` / `<ul>` |
| Attached images (with size, alignment, caption) | `![filename](img/filename "ac:width=750 ac:align=center ac:title=...")` | `ac:image` + `ri:attachment` with all display attributes restored |
| External images | `![alt](https://...)` | `ac:image` + `ri:url` |
| Info / Note / Warning / Tip panels | `> [!NOTE]` / `> [!INFO]` / `> [!WARNING]` / `> [!TIP]` | `ac:structured-macro ac:name="note\|info\|warning\|tip"` |
| Jira issue links | `[KEY-123](jira_url/browse/KEY-123)` | `ac:structured-macro ac:name="jira"` |
| Confluence page links | `[Title](confluence://page/Title)` | `ac:link` + `ri:page` |
| Relative links to tracked pages | `[Other Page](path/to/other.md)` | Resolved against config registry → `ac:link` internal link or page-ID URL |
| Blockquotes | `>` | `<blockquote>` |
| Horizontal rules | `---` | `<hr />` |

### Local image attachments

If your repo has an `img/` directory containing attachment images, py-conf-sync
handles them automatically in both directions:

- **On pull**: if `img/{filename}` exists locally, the Markdown image reference
  uses the relative path (`img/filename`) rather than the Confluence download URL,
  so images render locally without Confluence access.
- **On push**: local image paths are uploaded as Confluence page attachments
  before the page body is pushed. New and updated images are handled; existing
  attachments with the same filename are replaced.

The local image directory defaults to `img/` and can be changed in config:

```yaml
img_dir: assets/images
```

### Known round-trip limitations

- **Expand block code**: Code inside a collapsible expand section is stored by
  Confluence as a `code` macro. On pull, this renders as a fenced code block
  (`` ``` ``) rather than 4-space indented Markdown. The content is preserved;
  only the formatting style differs. Subsequent round-trips are stable.

- **Numbered lists split by block macros**: A `noformat` or other block macro
  between list items creates two separate `<ol>` elements in Confluence storage.
  Each list restarts at 1, so items after the break will appear renumbered on pull.
  This is stable after the first push with the renumbered list.

- **Push is full-replace.** The entire page body is replaced on each push. Do not use
  this on pages that are actively co-edited in Confluence.

- **First push of an existing Confluence page will show a large diff.** The storage
  format is normalised to match what this tool produces. Subsequent pushes of small
  changes will show only those changes.

- **Version conflict detection is optimistic.** If two people edit the same local file
  and push, the last writer wins.

### Not yet supported (planned)

| Feature | Notes |
|---|---|
| Status badges | Planned: map to an inline marker e.g. `[STATUS:colour:label]` |

### Not supported (out of scope)

| Feature | Notes |
|---|---|
| User mentions (`@user`) | Stripped on pull |
| Page includes | Stripped on pull |
| Anchor macros | Stripped on pull |
| All other `ac:*` macros | Stripped on pull |

## Credentials

Use a Personal Access Token (PAT) — it's scoped, revocable, and doesn't expose your password:

`Confluence → Profile → Personal Access Tokens → Create token`

Credentials are **never created automatically** by `csync init`. Set them up by hand:

```bash
cp .csync.env.example ~/.csync.env
# edit ~/.csync.env and fill in CONFLUENCE_TOKEN
```

### Credential file location

The tool searches for `.csync.env` in this order and uses the first file found:

1. `~/.csync.env` — **preferred.** One file, shared across all repos, never at risk of being committed.
2. `.csync.env` in the current directory (your target repo) — if using this, add `.csync.env` to `.gitignore`.
3. `.csync.env` in the directory where `py_conf_sync.py` lives.

Keeping credentials in `~/.csync.env` is the right default for most users.

### Basic auth

Basic auth is disabled by default. If you must use it, pass `--unsafe-auth`:

```bash
./csync --unsafe-auth pull
```

Basic auth credentials (`CONFLUENCE_USERNAME` + `CONFLUENCE_PASSWORD`) are silently ignored
without this flag and the command will exit with an error. PAT is strongly preferred.

## Version support

This tool targets **Confluence Data Center** and uses the v1 REST API
(`/rest/api/content/`). It has been tested against **DC 9.2.x**.

The v1 API has been stable since Confluence 6.x and remains fully supported
in the 9.x line, so any reasonably modern DC instance should work without
changes.

**Confluence Cloud is not currently supported.** Cloud uses a different base
URL structure and OAuth-based authentication model. Cloud support is planned
once the relevant infrastructure migration is complete.
