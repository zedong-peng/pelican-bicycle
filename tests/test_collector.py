import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
import ai_tokens  # noqa: E402
import publish  # noqa: E402


def write_lines(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))


def claude(message_id, request_id, output, sidechain=False, stamp="2026-09-29T01:00:00Z", model="claude-opus-5-5"):
    return {"type": "assistant", "timestamp": stamp, "requestId": request_id, "isSidechain": sidechain,
            "message": {"id": message_id, "model": model, "usage": {
                "input_tokens": 10, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20,
                "output_tokens": output}}}


def token_count(stamp, total, last):
    usage = lambda n: {"input_tokens": n, "cached_input_tokens": n // 2, "cache_write_input_tokens": 0,
                       "output_tokens": 5, "total_tokens": n + 5}
    return {"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": usage(total), "last_token_usage": usage(last)}}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.previous = ai_tokens.HOME, ai_tokens.CACHE
        ai_tokens.HOME = str(self.home)
        ai_tokens.CACHE = str(self.home / ".cache" / "ai-tokens")

    def tearDown(self):
        ai_tokens.HOME, ai_tokens.CACHE = self.previous

    def test_claude_dedupes_blocks_copies_and_sidechain_replays(self):
        project = self.home / ".claude" / "projects" / "p"
        write_lines(project / "a.jsonl", [claude("m1", "r1", 3), claude("m1", "r1", 7), claude("m2", "r2", 1)])
        write_lines(project / "b.jsonl", [claude("m1", "r1", 7)])  # response copied into another transcript
        write_lines(project / "a" / "subagents" / "s.jsonl",
                    [claude("m1", "r9", 7, sidechain=True), claude("m3", "r3", 2, sidechain=True)])
        totals = ai_tokens.Totals()
        ai_tokens.claude_code(totals)
        rows = totals.export("")
        self.assertEqual(rows, [["2026-09-29", "claude-code", "claude-opus-5-5", 3, 30, 300, 60, 10, None]])

    def test_codex_skips_replayed_parent_history_and_repeated_snapshots(self):
        day = self.home / ".codex" / "sessions" / "2026" / "09" / "29"
        context = {"timestamp": "2026-09-29T01:00:00Z", "type": "turn_context", "payload": {"model": "gpt-6-astra"}}
        write_lines(day / "parent.jsonl", [
            {"type": "session_meta", "payload": {"source": "cli"}}, token_count("2026-09-29T00:59:00Z", 50, 50),
            context, token_count("2026-09-29T01:01:00Z", 100, 100), token_count("2026-09-29T01:01:00Z", 100, 100),
            token_count("2026-09-29T01:02:00Z", 300, 200)])
        write_lines(day / "child.jsonl", [
            {"type": "session_meta", "payload": {"forked_from_id": "x", "source": {"subagent": {}}}},
            context, token_count("2026-09-29T01:01:00Z", 100, 100),
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"timestamp": "2026-09-29T02:00:00Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            token_count("2026-09-29T17:00:00Z", 40, 40)])
        totals = ai_tokens.Totals()
        ai_tokens.codex(totals)
        self.assertEqual(totals.export(""), [
            ["2026-09-29", "codex", "gpt-6-astra", 2, 150, 150, 0, 10, None],
            ["2026-09-30", "codex", "gpt-5.6-sol", 1, 20, 20, 0, 5, None]])  # 17:00Z is next day in Beijing
        cached = ai_tokens.Totals()
        ai_tokens.codex(cached)
        self.assertEqual(cached.export(""), totals.export(""))

    def test_opencode_counts_reasoning_as_output_and_keeps_recorded_cost(self):
        base = self.home / ".local" / "share" / "opencode"
        base.mkdir(parents=True)
        database = sqlite3.connect(base / "opencode.db")
        database.execute("CREATE TABLE message (id text, session_id text, time_created integer, time_updated integer, data text)")
        for index, data in enumerate([
            {"role": "assistant", "modelID": "muse-spark-1.3-contributor", "cost": 0.5,
             "tokens": {"input": 10, "output": 5, "reasoning": 3, "cache": {"read": 100, "write": 0}}},
            {"role": "user", "tokens": {"input": 999}},
        ]):
            database.execute("INSERT INTO message VALUES (?, 's', ?, 0, ?)", (str(index), 1790640000000, json.dumps(data)))
        database.commit()
        database.close()
        totals = ai_tokens.Totals()
        ai_tokens.opencode(totals, 0)
        self.assertEqual(totals.export(""), [["2026-09-29", "opencode", "muse-spark-1.3-contributor", 1, 10, 100, 0, 8, 0.5]])

    def test_cursor_reads_account_events_and_folds_effort_into_the_base_model(self):
        state = self.home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage"
        state.mkdir(parents=True)
        database = sqlite3.connect(state / "state.vscdb")
        database.execute("CREATE TABLE ItemTable (key text, value text)")
        claims = base64.urlsafe_b64encode(json.dumps({"sub": "auth0|user_1"}).encode()).decode().rstrip("=")
        database.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', ?)", ("h.%s.s" % claims,))
        database.commit()
        database.close()
        event = lambda model, stamp, usage: {"timestamp": str(stamp), "model": model, "tokenUsage": usage}
        pages = {1: [event("claude-opus-5-thinking-medium", 1790640000000,
                           {"inputTokens": 10, "cacheReadTokens": 100, "outputTokens": 5, "totalCents": 50}),
                     event("default", 1790640000000, {"inputTokens": 1, "outputTokens": 1})],
                 2: [event("cursor-grok-4.6-xhigh", 1790640000000, None)]}
        seen = []
        previous = ai_tokens.cursor_page
        ai_tokens.cursor_page = lambda session, start, end, page, size: seen.append(session) or pages.get(page, [])
        try:
            totals = ai_tokens.Totals()
            ai_tokens.cursor(totals, 0, size=2)
        finally:
            ai_tokens.cursor_page = previous
        self.assertEqual(seen, ["WorkosCursorSessionToken=user_1%3A%3Ah." + claims + ".s"] * 2)
        self.assertEqual(totals.export(""), [
            ["2026-09-29", "cursor", "claude-opus-5", 1, 10, 100, 0, 5, 0.5],
            ["2026-09-29", "cursor", "cursor-auto", 1, 1, 0, 0, 1, None]])
        self.assertEqual(ai_tokens.cursor_model("grok-4.7-high-fast"), "grok-4.7")

    def test_cursor_is_skipped_where_it_is_not_signed_in(self):
        totals = ai_tokens.Totals()
        ai_tokens.cursor(totals, 0)
        self.assertEqual(totals.export(""), [])


class PublishTests(unittest.TestCase):
    def test_model_names_drop_routing_prefix_and_relay_suffix(self):
        self.assertEqual(publish.model_name("openai/GPT-4o-mini"), "gpt-4o-mini")
        self.assertEqual(publish.model_name("gpt-6-astra-cc-format"), "gpt-6-astra")

    def test_prices_use_official_rates_or_recorded_opencode_cost(self):
        prices = {"claude-opus-5-5": [4, 0.2, 5, 20]}
        self.assertAlmostEqual(publish.api_cost(prices, "claude-opus-5-5",
                                                [1, 1_000_000, 1_000_000, 1_000_000, 1_000_000, None]), 29.2)
        self.assertIsNone(publish.api_cost(prices, "unknown", [1, 1, 1, 1, 1, None]))
        self.assertEqual(publish.api_cost(prices, "x", [1, 1, 1, 1, 1, 0.25]), 0.25)
        self.assertEqual(publish.api_cost(prices, "grok-4.6", [1, 1, 1, 1, 1, 0.3]), 0.3)
        # a listed price beats OpenCode's recorded (subscription) cost; aliases borrow another model's price
        self.assertAlmostEqual(publish.api_cost(prices, "claude-opus-5-5", [1, 1_000_000, 0, 0, 0, 0.01]), 4)
        self.assertAlmostEqual(publish.api_cost(prices, "opus-alias", [1, 1_000_000, 0, 0, 0, None],
                                                {"opus-alias": "claude-opus-5-5"}), 4)

    def test_history_keeps_days_that_logs_no_longer_hold(self):
        state = tempfile.mkdtemp()
        previous = publish.STATE
        publish.STATE = state
        try:
            publish.merge_history("h", {"generated_at": "t1", "rows": [
                ["2026-08-01", "claude-code", "m", 5, 50, 0, 0, 5, None],
                ["2026-09-29", "claude-code", "m", 1, 10, 0, 0, 1, None]]})
            history = publish.merge_history("h", {"generated_at": "t2", "rows": [
                ["2026-09-29", "claude-code", "m", 3, 30, 0, 0, 3, None]]})
            self.assertEqual(history["rows"]["2026-08-01|claude-code|m"][0], 5)
            self.assertEqual(history["rows"]["2026-09-29|claude-code|m"][0], 3)
            self.assertEqual(publish.merge_history("h", None)["rows"], history["rows"])
        finally:
            publish.STATE = previous


if __name__ == "__main__":
    unittest.main()
