# AGENTS.md

Static archive of "pelican rides bicycle" SVG animations. No dependencies, no tests, no lint. Single script owns validation + build.

## Commands

- `python3 build.py` — only check/build (CI runs same on Python 3.12). Validates `results/`, regenerates `site/`; prints `Validated N results`. No args, no install.
- Preview locally: open `site/index.html` in browser directly, no server needed.

## Submissions (`results/<slug>/`)

Each run is exactly 2 files, nothing else: `artwork.html` + `metadata.json`. Never edit an existing run's `artwork.html`; new/duplicate runs get a new dir. Renames are only allowed via `git mv` to keep the slug in sync with a metadata correction — never to reuse a slug for different content.

- `slug`: strictly derived from metadata as `<model>-<effort>-<provider>-<harness>`, all lowercase with every non-`[a-z0-9]` run collapsed to a single `-` (e.g. `gpt-5.6-sol` → `gpt-5-6-sol`; domain-style providers keep only the main label, e.g. `xmapi.site` → `xmapi`). Must match `[a-z0-9-]{1,64}` with alnum leading/trailing char. Never pure 12-hex (`[0-9a-f]{12}...` is rejected as legacy hash dir). Repeat runs under identical config append `-01`, `-02`, `-03`; fixing metadata requires renaming the dir in the same commit.
- `metadata.json`: exactly these 4 non-empty string keys, no extras — `model`, `effort`, `provider`, `harness`. Unknown → `"unknown"`, n/a effort → `"not-applicable"`. Never guess.
- `model` vs `provider`: strip routing prefix, e.g. `opencode-go/deepseek-v4.1-flash` → `model: deepseek-v4.1-flash`, `provider: opencode-go`. Reuse existing same-model spelling; versions never merge.
- `artwork.html`: ≤2 MiB, must contain `<!doctype html>`, `<head>`, `<svg>` (case-insensitive). Single file, resources inline, no remote deps, no secrets/PII/tracking. Never reformat or change line endings — `results/**/artwork.html -text` via `.gitattributes`.
- Byte-identical HTML across dirs is warning-only (SHA-256 in `build.py`), not failure; it needs a PR-description explanation.

## Build behavior (`build.py`, `gallery.html`)

- Sort order is `model, effort, provider, harness, slug` from metadata — the slug must mirror those four fields, and is only a tiebreaker in sorting.
- `site/` is gitignored build output — never commit. Build injects CSP `<meta>` + `sandbox="allow-scripts"` iframe wrappers; originals stay untouched.
- Template placeholders: `gallery.html` `<!-- RESULTS -->` / `<!-- PROMPT -->` (from `prompt.txt`).

## CI (`.github/workflows/pages.yml`)

PRs only validate + build (`python3 build.py`); Pages deploy happens only on `push` to `main`. Don't add deploy/secret steps to PR path.

## Safety

Untrusted third-party HTML/JS in `results/`. Review via sandboxed gallery preview, not by opening `artwork.html` directly in a logged-in browser session.
