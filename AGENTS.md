# AGENTS.md

Personal AI usage page (sytoken.org/ai-board/): token dashboard, notes, relay-station stats, candy test and the "pelican rides bicycle" SVG archive. No dependencies or lint; Python standard library throughout, plus an external Codex CLI on the VPS.

## Layout

- `web/` page sources: `index.html` template, `style.css`, one script per module (`tokens.js`, `relay.js`, `cost.js`, `candy.js`, `gallery.js`), `notes.json`.
- `collector/` token collector (runs from au-linux cron). `monitor/` VPS relay stats service. `candy/` candy prompt + local/public servers. `pelican/` prompt + `results/`.
- `tests/` holds every test. `build.py` (repo root) validates and writes `site/`.

## Commands

- `python3 build.py` — only check/build (CI runs same on Python 3.12). Validates `pelican/results/`, regenerates `site/`; prints `Validated N results`. No args, no install.
- Preview locally: open `site/index.html` in browser directly, no server needed.
- `python3 -m unittest discover -s tests` runs all Python tests (collector, monitor, candy servers, notes).
- `for f in web/*.js; do node --check "$f"; done` validates browser scripts; `node --test tests/test_tokens_ui.js` checks dashboard math; `tests/browser.cjs` is the optional Playwright check.

## Token dashboard (`collector/`, `web/tokens.js`)

- `collector/ai_tokens.py` must stay Python 3.8 + stdlib: it is piped over ssh (`python3 -`) to machines with old system Pythons. Output is daily aggregates only — never prompts, paths, project names or session ids.
- Dedupe rules follow ccusage (see `collector/README.md`); `tests/test_collector.py` pins them. Don't loosen them without re-checking real logs for double counting.
- Cursor usage comes from the signed-in app's dashboard session (account-wide), never from other people's machines; the token is used in memory only and never logged or written out.
- Prices live in `collector/prices.json` (official list prices only; unknown models stay unpriced, never guessed).
- Deploying `site/` must not delete `/var/www/ai-benchmark/data/` — the daily publisher owns `data/tokens.json`.

## Candy test (`candy/`)

- `python3 candy/local_server.py` starts the local-only tool; `python3 candy/public_candy.py` starts shared collection. Both bind loopback.
- Public candy records use a SQLite database outside `site/` and the repo. Never persist keys or raw upstream response objects. Public records may retain redacted answer text (up to 20,000 characters per sample), timing and score details. Keep the fixed question in `candy/prompt.txt`; `build.py` injects it into the browser script.
- Keep live credentials and owner-specific configuration outside this public repo. See `monitor/README.md`.

## Submissions (`pelican/results/<slug>/`)

Each run is exactly 2 files, nothing else: `artwork.html` + `metadata.json`. Never edit an existing run's `artwork.html`; new/duplicate runs get a new dir. Renames are only allowed via `git mv` to keep the slug in sync with a metadata correction — never to reuse a slug for different content.

- `slug`: strictly derived from metadata as `<model>-<effort>-<provider>-<harness>`, all lowercase with every non-`[a-z0-9]` run collapsed to a single `-` (e.g. `gpt-5.6-sol` → `gpt-5-6-sol`; domain-style providers keep only the main label, e.g. `xmapi.site` → `xmapi`; composite `zlab(fengchao-api.com)` → `zlab-fengchao-api` with upstream TLD dropped). Must match `[a-z0-9-]{1,64}` with alnum leading/trailing char. Never pure 12-hex (`[0-9a-f]{12}...` is rejected as legacy hash dir). Repeat runs under identical config append `-01`, `-02`, `-03`; fixing metadata requires renaming the dir in the same commit.
- `metadata.json`: exactly these 4 non-empty string keys, no extras — `model`, `effort`, `provider`, `harness`. Unknown → `"unknown"`, n/a effort → `"not-applicable"`. Never guess.
- `model` vs `provider`: strip routing prefix, e.g. `opencode-go/deepseek-v4.1-flash` → `model: deepseek-v4.1-flash`, `provider: opencode-go`. Reuse existing same-model spelling; versions never merge. When the harness talks to a lab gateway that routes upstream, record both as `gateway(upstream)` with `()` (not `-`, since relay domains contain `-`), e.g. `zlab(fengchao-api.com)`; all lowercase, no spaces.
- `artwork.html`: ≤2 MiB, must contain `<!doctype html>`, `<head>`, `<svg>` (case-insensitive). Single file, resources inline, no remote deps, no secrets/PII/tracking. Never reformat or change line endings — `pelican/results/**/artwork.html -text` via `.gitattributes`.
- Byte-identical HTML across dirs is warning-only (SHA-256 in `build.py`), not failure; it needs a PR-description explanation.

## Build behavior (`build.py`, `web/index.html`)

- Sort order is `model, effort, provider, harness, slug` from metadata — the slug must mirror those four fields, and is only a tiebreaker in sorting.
- `site/` is gitignored build output — never commit. Build injects CSP `<meta>` + `sandbox="allow-scripts"` iframe wrappers; originals stay untouched.
- Template placeholders in `web/index.html`: `<!-- RESULTS -->`, `<!-- PROMPT -->` (from `pelican/prompt.txt`), `<!-- USAGE_NOTES -->` (from `web/notes.json`).

## CI (`.github/workflows/pages.yml`)

PRs only validate + build (`python3 build.py`); Pages deploy happens only on `push` to `main`. Don't add deploy/secret steps to PR path.

## Safety

Untrusted third-party HTML/JS in `pelican/results/`. Review via sandboxed gallery preview, not by opening `artwork.html` directly in a logged-in browser session.
