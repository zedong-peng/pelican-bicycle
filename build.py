"""Validate submissions and build a dependency-free, offline gallery."""

import hashlib
import html
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
# Minimal metadata: exactly the four gallery dimensions. Authorship comes
# from git history / PR author; run disclosures go into the PR description.
FIELDS = {"model", "effort", "provider", "harness"}
# Human-readable run slug, ccfddl-style (e.g. conference/DB/sigmod.yml):
# lowercase alphanumerics + hyphens, no leading/trailing hyphen. Pure
# 12-hex strings are reserved for legacy content-hash directories.
SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
LEGACY_RE = re.compile(r"[0-9a-f]{12}(?:-[1-9][0-9]*)?")
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data:; font-src data:; media-src data:; connect-src 'none'; "
       "form-action 'none'; base-uri 'none'")


def collect():
    records = []
    seen_hashes = {}
    for directory in sorted((ROOT / "results").iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"Unexpected result entry: {directory.name}")
        if not SLUG_RE.fullmatch(directory.name):
            raise ValueError(
                f"Invalid run slug: {directory.name!r}; use lowercase "
                "letters, digits and hyphens, e.g. "
                "deepseek-v4-1-flash-opencode-go-opencode-01")
        if LEGACY_RE.fullmatch(directory.name):
            raise ValueError(
                f"{directory.name}: legacy content-hash directory; "
                "rename it to a readable slug (see CONTRIBUTING.md)")
        if {p.name for p in directory.iterdir()} != {"metadata.json", "artwork.html"}:
            raise ValueError(f"{directory.name}: expected artwork.html and metadata.json")
        if any(p.is_symlink() for p in directory.iterdir()):
            raise ValueError(f"{directory.name}: symlinks are not supported")
        meta = json.loads((directory / "metadata.json").read_text())
        if not isinstance(meta, dict) or set(meta) != FIELDS:
            raise ValueError(f"{directory.name}: metadata fields must match template")
        for key in FIELDS:
            if not isinstance(meta[key], str) or not meta[key].strip():
                raise ValueError(f"{directory.name}: invalid {key}")
        source = directory / "artwork.html"
        if source.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"{directory.name}: HTML exceeds 2 MiB")
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen_hashes:
            print(f"Warning: {directory.name} has identical HTML bytes to "
                  f"{seen_hashes[digest]}; explain in the PR description if independent runs.")
        else:
            seen_hashes[digest] = directory.name
        markup = content.decode("utf-8")
        if not all(re.search(pattern, markup, re.I) for pattern in
                   (r"<!doctype\s+html\s*>", r"<head\b[^>]*>", r"<svg\b")):
            raise ValueError(f"{directory.name}: expected HTML document with head and SVG")
        records.append((directory.name, meta, markup))
    if not records:
        raise ValueError("No results found")
    return sorted(records, key=lambda record: tuple(record[1][key] for key in
                  ("model", "effort", "provider", "harness")) + (record[0],))


def build():
    records = collect()
    output = ROOT / "site"
    if output.is_symlink():
        raise ValueError("site must not be a symlink")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(exist_ok=True)
    cards = []
    for index, (run_id, meta, markup) in enumerate(records, start=1):
        target = output / "previews" / run_id
        target.mkdir(parents=True, exist_ok=True)
        # Apply CSP before any submitted element; original files remain untouched.
        secured = '<meta http-equiv="Content-Security-Policy" content="' + html.escape(CSP, quote=True) + '">'
        preview = '<!doctype html><html><head><meta charset="utf-8">' + secured + markup
        (target / "index.html").write_text(preview, encoding="utf-8")
        attrs = " ".join(f'data-{key}="{html.escape(meta[key], quote=True)}"'
                         for key in ("model", "effort", "provider", "harness"))
        labels = "".join(f'<div><dt>{key}</dt><dd>{html.escape(meta[key])}</dd></div>'
                         for key in ("effort", "provider", "harness"))
        cards.append(f'''<article {attrs}>
<div class="preview"><iframe sandbox="allow-scripts" loading="lazy" referrerpolicy="no-referrer"
src="previews/{run_id}/index.html" title="{html.escape(meta['model'], quote=True)} animation"></iframe></div>
<div class="info"><div class="work-heading"><span class="index">{index:02d}</span><h2>{html.escape(meta['model'])}</h2></div><dl>{labels}</dl>
<div class="work-footer"><a href="https://github.com/zedong-peng/pelican-bicycle/tree/main/results/{run_id}" target="_blank" rel="noopener noreferrer">GitHub 源文件 ↗</a><button class="expand" type="button">放大作品 ↗</button></div></div></article>''')
    template = (ROOT / "gallery.html").read_text(encoding="utf-8")
    prompt = (ROOT / "prompt.txt").read_text(encoding="utf-8").strip()
    template = template.replace("<!-- PROMPT -->", html.escape(prompt))
    (output / "index.html").write_text(template.replace("<!-- RESULTS -->", "\n".join(cards)), encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f"Validated {len(records)} results; built {output / 'index.html'}")


if __name__ == "__main__":
    build()
