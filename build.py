"""Validate submissions and build a dependency-free, offline gallery."""

import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
FIELDS = {"model", "effort", "provider", "harness", "harness_version",
          "prompt_id", "prompt_verified", "created_at", "contributor",
          "generation", "notes"}
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data:; font-src data:; media-src data:; connect-src 'none'; "
       "form-action 'none'; base-uri 'none'")


def collect():
    records = []
    for directory in sorted((ROOT / "results").iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"Unexpected result entry: {directory.name}")
        if not re.fullmatch(r"[0-9a-f]{12}(?:-[1-9][0-9]*)?", directory.name):
            raise ValueError(f"Invalid run ID: {directory.name}")
        if {p.name for p in directory.iterdir()} != {"metadata.json", "artwork.html"}:
            raise ValueError(f"{directory.name}: expected artwork.html and metadata.json")
        if any(p.is_symlink() for p in directory.iterdir()):
            raise ValueError(f"{directory.name}: symlinks are not supported")
        meta = json.loads((directory / "metadata.json").read_text())
        if not isinstance(meta, dict) or set(meta) != FIELDS:
            raise ValueError(f"{directory.name}: metadata fields must match template")
        for key in FIELDS - {"harness_version", "created_at", "prompt_verified"}:
            if not isinstance(meta[key], str) or (key != "notes" and not meta[key].strip()):
                raise ValueError(f"{directory.name}: invalid {key}")
        for key in ("harness_version", "created_at"):
            if meta[key] is not None and (not isinstance(meta[key], str) or not meta[key].strip()):
                raise ValueError(f"{directory.name}: invalid {key}")
        if meta["created_at"] is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["created_at"]):
                raise ValueError(f"{directory.name}: date must be YYYY-MM-DD")
            datetime.date.fromisoformat(meta["created_at"])
        if type(meta["prompt_verified"]) is not bool:
            raise ValueError(f"{directory.name}: prompt_verified must be boolean")
        if meta["prompt_id"] != "pelican-bicycle-v1":
            raise ValueError(f"{directory.name}: unsupported prompt")
        if meta["generation"] not in {"single-turn", "multi-turn", "unknown"}:
            raise ValueError(f"{directory.name}: invalid generation")
        source = directory / "artwork.html"
        if source.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"{directory.name}: HTML exceeds 2 MiB")
        content = source.read_bytes()
        expected_id = hashlib.sha256(content).hexdigest()[:12]
        if directory.name.split("-")[0] != expected_id:
            raise ValueError(f"{directory.name}: HTML hash mismatch; expected {expected_id}")
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
        status = "Prompt 已确认" if meta["prompt_verified"] else "Prompt 未确认"
        cards.append(f'''<article {attrs}>
<div class="preview"><iframe sandbox="allow-scripts" loading="lazy" referrerpolicy="no-referrer"
src="previews/{run_id}/index.html" title="{html.escape(meta['model'], quote=True)} animation"></iframe></div>
<div class="info"><div class="work-heading"><span class="index">{index:02d}</span><h2>{html.escape(meta['model'])}</h2></div><dl>{labels}</dl>
<div class="work-footer"><span class="status">{status}</span><button class="expand" type="button">放大作品 ↗</button></div></div>
<details><summary>运行记录</summary><p>{html.escape(meta['generation'])}</p><p>{html.escape(meta['notes'])}</p>
<p>Contributor: {html.escape(meta['contributor'])}<br>Version: {html.escape(meta['harness_version'] or 'unknown')}<br>Date: {html.escape(meta['created_at'] or 'unknown')}</p>
<a href="https://github.com/zedong-peng/pelican-bicycle/tree/main/results/{run_id}" target="_blank" rel="noopener noreferrer">GitHub 源文件 ↗</a></details></article>''')
    template = (ROOT / "gallery.html").read_text(encoding="utf-8")
    prompt = (ROOT / "prompt.txt").read_text(encoding="utf-8").strip()
    template = template.replace("<!-- PROMPT -->", html.escape(prompt))
    (output / "index.html").write_text(template.replace("<!-- RESULTS -->", "\n".join(cards)), encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f"Validated {len(records)} results; built {output / 'index.html'}")


if __name__ == "__main__":
    build()
