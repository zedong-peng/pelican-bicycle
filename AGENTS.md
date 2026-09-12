# AGENTS.md

Static archive of "pelican rides bicycle" SVG animations. No dependencies, no tests, no lint. Single script owns validation + build.

## Commands

- `python3 build.py` — only check/build (CI runs same on Python 3.12). Validates `results/`, regenerates `site/`; prints `Validated N results`. No args, no install.
- Preview locally: open `site/index.html` in browser directly, no server needed.

## Submissions (`results/<slug>/`)

Each run is exactly 2 files, nothing else: `artwork.html` + `metadata.json`. Never touch existing run dirs; new/duplicate runs get a new dir.

- `slug`: `[a-z0-9-]{1,64}`, leading/trailing char must be alnum. Never pure 12-hex (`[0-9a-f]{12}...` is rejected as legacy hash dir). On conflict append `-02`, `-03`; renaming to fix metadata is forbidden.
- `metadata.json`: exactly these 4 non-empty string keys, no extras — `model`, `effort`, `provider`, `harness`. Unknown → `"unknown"`, n/a effort → `"not-applicable"`. Never guess.
- `model` vs `provider`: strip routing prefix, e.g. `opencode-go/deepseek-v4.1-flash` → `model: deepseek-v4.1-flash`, `provider: opencode-go`. Reuse existing same-model spelling; versions never merge.
- `artwork.html`: ≤2 MiB, must contain `<!doctype html>`, `<head>`, `<svg>` (case-insensitive). Single file, resources inline, no remote deps, no secrets/PII/tracking. Never reformat or change line endings — `results/**/artwork.html -text` via `.gitattributes`.
- Byte-identical HTML across dirs is warning-only (SHA-256 in `build.py`), not failure; it needs a PR-description explanation.

## Build behavior (`build.py`, `gallery.html`)

- Sort order is `model, effort, provider, harness, slug` from metadata — slugs carry no semantics.
- `site/` is gitignored build output — never commit. Build injects CSP `<meta>` + `sandbox="allow-scripts"` iframe wrappers; originals stay untouched.
- Template placeholders: `gallery.html` `<!-- RESULTS -->` / `<!-- PROMPT -->` (from `prompt.txt`).

## CI (`.github/workflows/pages.yml`)

PRs only validate + build (`python3 build.py`); Pages deploy happens only on `push` to `main`. Don't add deploy/secret steps to PR path.

## Safety

Untrusted third-party HTML/JS in `results/`. Review via sandboxed gallery preview, not by opening `artwork.html` directly in a logged-in browser session.
