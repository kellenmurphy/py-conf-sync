# Security Policy

## Supported Versions

Security fixes are applied to the `main` branch and released as a new patch
version. Only the latest release is actively maintained.

| Version | Supported |
|---|---|
| Latest release (`0.1.x` and above) | Yes |
| Older releases | No — update to the latest release |
| `latest` Docker image | Yes (tracks the latest release) |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use GitHub's private vulnerability reporting instead:

1. Go to the [Security tab](../../security) of this repository.
2. Click **"Report a vulnerability"**.
3. Fill in the details and submit.

This opens a private security advisory visible only to maintainers. You will
receive a response within **5 business days** acknowledging the report.

### What to include

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any relevant configuration (redact credentials)
- The version of the tool you are running (`./csync --version` or `docker image inspect`)

### What to expect

- Acknowledgement within 5 business days
- An assessment and severity rating within 10 business days
- A fix and patched image published as promptly as the severity warrants
- Credit in the release notes if you would like it

## Supply chain

- Dependencies are pinned via pip-compile lockfiles (`requirements.txt`, `requirements-dev.txt`) and updated weekly by Dependabot
- All merges to `main` require a passing test suite
- Docker images are published via GitHub Actions with pinned action versions
- Images are tagged by semver and `latest` tracks the current release

## Scope

This tool runs as a local CLI and communicates only with a Confluence Data
Center instance you configure. The primary attack surface is:

- Credentials stored in `~/.csync.env`
- Confluence storage format content pulled from your instance
- The config file (`.py-conf-sync.config.yaml`) in your repository

Out of scope: vulnerabilities that require an attacker to already have write
access to your Confluence instance or your local filesystem.
