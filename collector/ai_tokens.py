"""Aggregate local AI tool token usage into per-day rows.

Reads Claude Code, Codex and OpenCode logs on this machine, plus the Cursor
account's usage events when Cursor is signed in here, and prints JSON to
stdout. Only daily totals per tool and model leave the machine: no prompts,
paths, project names or session ids. Python 3.8+, standard library only, so it
can be piped over ssh: ``ssh host python3 - --host name < ai_tokens.py``.
"""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import glob
import json
import os
import re
import sqlite3
import sys
import urllib.request

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai, no DST
HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cache", "ai-tokens")


def day_of(value):
    """ISO string or epoch milliseconds -> YYYY-MM-DD in Asia/Shanghai."""
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value / 1000, TZ)
    else:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)
    return moment.strftime("%Y-%m-%d")


def count(value):
    return value if isinstance(value, int) and value > 0 else 0


def write_json(path, data, **options):
    """Write via a temporary file so readers never see half a file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(data, handle, **options)
    os.replace(path + ".tmp", path)


class Totals:
    def __init__(self):
        self.rows = {}

    def add(self, day, tool, model, fresh, cache_read, cache_write, output, cost=None):
        key = (day, tool, model or "unknown")
        row = self.rows.setdefault(key, [0, 0, 0, 0, 0, None])
        row[0] += 1
        row[1] += fresh
        row[2] += cache_read
        row[3] += cache_write
        row[4] += output
        if cost is not None:
            row[5] = (row[5] or 0) + cost

    def merge(self, rows):
        for day, tool, model, requests, fresh, read, write, output, cost in rows:
            row = self.rows.setdefault((day, tool, model), [0, 0, 0, 0, 0, None])
            for index, value in enumerate((requests, fresh, read, write, output)):
                row[index] += value
            if cost is not None:
                row[5] = (row[5] or 0) + cost

    def export(self, since):
        return [[day, tool, model] + values[:5] + [round(values[5], 6) if values[5] is not None else None]
                for (day, tool, model), values in sorted(self.rows.items()) if day >= since]


def claude_usage(usage):
    return (count(usage.get("input_tokens")), count(usage.get("cache_read_input_tokens")),
            count(usage.get("cache_creation_input_tokens")), count(usage.get("output_tokens")))


def claude_code(totals):
    """Dedupe the way ccusage does.

    Claude Code writes one line per content block and can copy a response into
    several transcripts, so message id + request id identify one request.
    Sidechain logs (subagents/, /btw) replay parent messages under a new request
    id; those copies are dropped when the parent entry is present. Advisor
    iterations are counted under their own model.
    """
    records = {}
    for root in (os.path.join(HOME, ".claude", "projects"), os.path.join(HOME, ".config", "claude", "projects")):
        for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
            try:
                handle = open(path, encoding="utf-8", errors="replace")
            except OSError:
                continue
            with handle:
                for line in handle:
                    if '"usage"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                        message = entry["message"]
                        usage = message["usage"]
                        model = message.get("model")
                        day = day_of(entry["timestamp"])
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
                    if entry.get("type") != "assistant" or not model or model == "<synthetic>":
                        continue
                    request = entry.get("requestId") or entry["timestamp"]
                    key = (message.get("id"), request)
                    values = claude_usage(usage)
                    previous = records.get(key)
                    if previous is None or values[3] > previous[2][3]:
                        records[key] = (day, model, values, entry.get("isSidechain") is True)
                    for index, step in enumerate(usage.get("iterations") or []):
                        if isinstance(step, dict) and step.get("type") == "advisor_message" and step.get("model"):
                            records[key + ("advisor", index)] = (day, step["model"], claude_usage(step), False)
    primary = {key[0] for key, record in records.items() if not record[3]}
    for key, (day, model, values, sidechain) in records.items():
        if sidechain and key[0] in primary:
            continue
        totals.add(day, "claude-code", model, *values)


def codex_file(path):
    """Per-request usage from one rollout file.

    A sub-agent rollout first replays its parent's history; as in ccusage, its
    own usage starts at task_started or a trigger_turn inter-agent message.
    Usage before the first turn_context has no model and is skipped, as are
    repeated snapshots of the same cumulative total.
    """
    rows = Totals()
    model, last_total, replaying = None, None, False
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle):
            if number == 0 and '"session_meta"' in line:
                try:
                    meta = json.loads(line)["payload"]
                    replaying = bool(meta.get("forked_from_id")) or isinstance(meta.get("source"), dict)
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
                continue
            if replaying and ('"task_started"' in line or (
                    '"inter_agent_communication' in line and '"trigger_turn":true' in line.replace(" ", ""))):
                replaying = False
                continue
            if '"turn_context"' in line:
                try:
                    model = json.loads(line)["payload"].get("model") or model or "unknown"
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
                continue
            if replaying or model is None or '"token_count"' not in line:
                continue
            try:
                entry = json.loads(line)
                info = entry["payload"]["info"]
                usage = info["last_token_usage"]
                total = json.dumps(info.get("total_token_usage"), sort_keys=True)
            except (ValueError, KeyError, TypeError):
                continue
            if total == last_total:
                continue
            last_total = total
            cached = count(usage.get("cached_input_tokens"))
            written = count(usage.get("cache_write_input_tokens"))
            fresh = max(count(usage.get("input_tokens")) - cached - written, 0)
            rows.add(day_of(entry["timestamp"]), "codex", model, fresh, cached, written,
                     count(usage.get("output_tokens")))
    return rows.export("")


def codex(totals):
    """Rollout files never change once a session ends, so cache them by size and mtime."""
    cache_path = os.path.join(CACHE, "codex-v3.json")
    try:
        with open(cache_path, encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, ValueError):
        cache = {}
    fresh_cache = {}
    codex_home = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
    paths = {}
    for folder in ("archived_sessions", "sessions"):  # the active copy wins
        base = os.path.join(codex_home, folder)
        for path in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True):
            paths[os.path.relpath(path, base)] = path
    for path in paths.values():
        try:
            stat = os.stat(path)
        except OSError:
            continue
        stamp = [stat.st_size, int(stat.st_mtime)]
        hit = cache.get(path)
        rows = hit["rows"] if hit and hit["stamp"] == stamp else codex_file(path)
        fresh_cache[path] = {"stamp": stamp, "rows": rows}
        totals.merge(rows)
    write_json(cache_path, fresh_cache)


def opencode(totals, since_ms):
    base = os.environ.get("OPENCODE_DATA_DIR") or os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "opencode")
    for path in sorted(glob.glob(os.path.join(base, "opencode.db")) + glob.glob(os.path.join(base, "opencode-*.db"))):
        opencode_db(totals, path, since_ms)


def opencode_db(totals, path, since_ms):
    """Reasoning tokens are reported apart from output and billed as output."""
    database = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
    try:
        query = """SELECT time_created, json_extract(data, '$.modelID'), json_extract(data, '$.tokens.input'),
                          json_extract(data, '$.tokens.cache.read'), json_extract(data, '$.tokens.cache.write'),
                          json_extract(data, '$.tokens.output'), json_extract(data, '$.tokens.reasoning'),
                          json_extract(data, '$.cost')
                   FROM message WHERE time_created >= ? AND json_extract(data, '$.role') = 'assistant'"""
        for created, model, fresh, read, write, output, reasoning, cost in database.execute(query, (since_ms,)):
            if not any((fresh, read, write, output, reasoning)):
                continue
            totals.add(day_of(created), "opencode", model, count(fresh), count(read), count(write),
                       count(output) + count(reasoning), cost if isinstance(cost, (int, float)) and cost > 0 else None)
    finally:
        database.close()


CURSOR_EVENTS = "https://cursor.com/api/dashboard/get-filtered-usage-events"


def cursor_state():
    for path in (os.path.join(HOME, "Library", "Application Support", "Cursor", "User", "globalStorage", "state.vscdb"),
                 os.path.join(HOME, ".config", "Cursor", "User", "globalStorage", "state.vscdb")):
        if os.path.exists(path):
            return path
    return None


def cursor_session(path):
    """Dashboard cookie built from the signed-in app's access token; None when signed out."""
    database = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
    try:
        found = database.execute("SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'").fetchone()
    finally:
        database.close()
    if not found or not found[0]:
        return None
    token = found[0]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    return "WorkosCursorSessionToken=%s%%3A%%3A%s" % (claims["sub"].split("|")[-1], token)


def cursor_page(session, start_ms, end_ms, page, size):
    body = json.dumps({"startDate": str(start_ms), "endDate": str(end_ms), "page": page, "pageSize": size}).encode()
    request = urllib.request.Request(CURSOR_EVENTS, data=body, headers={
        "Content-Type": "application/json", "Origin": "https://cursor.com", "Cookie": session, "User-Agent": "ai-tokens"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response).get("usageEventsDisplay") or []


def cursor_model(name):
    """claude-opus-5-thinking-medium -> claude-opus-5; the "default" model is Cursor's Auto."""
    name = (name or "").lower()
    if name in ("", "default", "auto"):
        return "cursor-auto"
    name = re.sub(r"^cursor-", "", name)
    while True:
        base = re.sub(r"-(thinking|fast|low|medium|high|xhigh|max)$", "", name)
        if base == name:
            return name
        name = base


def cursor(totals, since_ms, size=500):
    """Cursor keeps usage server-side (about the last 3.5 months), not in local logs.

    The events are per account, so only one machine should be signed in to the
    same account. Cursor's own totalCents is kept as the recorded cost.
    """
    path = cursor_state()
    session = path and cursor_session(path)
    if not session:
        return
    end_ms = int(datetime.now(TZ).timestamp() * 1000)
    page = 1
    while True:
        events = cursor_page(session, since_ms, end_ms, page, size)
        for event in events:
            usage = event.get("tokenUsage")
            if not usage:  # request-priced calls carry no token counts
                continue
            cents = usage.get("totalCents")
            totals.add(day_of(int(event["timestamp"])), "cursor", cursor_model(event.get("model")), count(usage.get("inputTokens")),
                       count(usage.get("cacheReadTokens")), count(usage.get("cacheWriteTokens")),
                       count(usage.get("outputTokens")),
                       cents / 100 if isinstance(cents, (int, float)) and cents > 0 else None)
        if len(events) < size:
            return
        page += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.uname().nodename)
    parser.add_argument("--days", type=int, default=400)
    args = parser.parse_args()
    now = datetime.now(TZ)
    since = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")
    totals = Totals()
    errors = []
    since_ms = int((now - timedelta(days=args.days)).timestamp() * 1000)
    for name, collect in (("claude-code", claude_code), ("codex", codex),
                          ("opencode", lambda t: opencode(t, since_ms)), ("cursor", lambda t: cursor(t, since_ms))):
        try:
            collect(totals)
        except Exception as error:  # one broken source must not hide the others
            errors.append("%s: %s" % (name, type(error).__name__))
    json.dump({"schema": "ai-tokens-host/1", "host": args.host, "generated_at": now.isoformat(timespec="seconds"),
               "columns": ["date", "tool", "model", "requests", "input", "cache_read", "cache_write", "output", "recorded_cost"],
               "rows": totals.export(since), "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
