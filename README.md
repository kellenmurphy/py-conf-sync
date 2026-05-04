# py-conf-sync

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
| Fenced code blocks (no language) | ` ``` ``` ` | `ac:structured-macro ac:name="code"` with `language=none`; also handles Confluence `noformat` macro on pull |
| Tables | GFM pipe tables | `<table class="wrapped">` |
| Ordered and unordered lists (nested) | `1.` / `-` with 2-space indent | `<ol>` / `<ul>` |
| Jira issue links | `[KEY-123](jira_url/browse/KEY-123)` | `ac:structured-macro ac:name="jira"` |
| Confluence page links | `[Title](confluence://page/Title)` | `ac:link` + `ri:page` |
| Blockquotes | `>` | `<blockquote>` |
| Horizontal rules | `---` | `<hr />` |

### Not yet supported (planned)

These are stripped on pull and lost on push. Pages that rely on them will degrade
the first time they are pushed through this tool.

| Feature | Notes |
|---|---|
| Info / Note / Warning / Tip panels | Planned: map to blockquotes with a prefix marker |
| Status badges | Planned: map to an inline marker e.g. `[STATUS:colour:label]` |

### Not supported (out of scope)

| Feature | Notes |
|---|---|
| Attachments and images | Only page body content is handled |
| User mentions (`@user`) | Stripped on pull |
| Page includes | Stripped on pull |
| Table of contents macro | Stripped on pull |
| Anchor macros | Stripped on pull |
| All other `ac:*` macros | Stripped on pull |

### General limitations

- **Push is full-replace.** The entire page body is replaced on each push. Do not use
  this on pages that are actively co-edited in Confluence.
- **First push of an existing Confluence page will show a large diff.** The storage
  format is normalised to match what this tool produces. Subsequent pushes of small
  changes will show only those changes.
- **Version conflict detection is optimistic.** If two people edit the same local file
  and push, the last writer wins.

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
