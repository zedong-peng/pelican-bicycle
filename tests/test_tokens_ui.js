const assert = require("node:assert/strict");
const { test } = require("node:test");
const { parse, slots, lastDay, summarize, legendEntries, columns, yScale, SERIES } = require("../web/tokens.js");

const COLUMNS = ["date", "tool", "model", "requests", "input", "cache_read", "cache_write", "output", "api_usd"];
function snapshot(rows) {
  return { schema_version: 1, updated_at: "2026-09-30T05:00:00+08:00", columns: COLUMNS, rows };
}
const rows = parse(snapshot([
  ["2026-09-28", "claude-code", "claude-opus-5-5", 10, 100, 800, 50, 50, 1.5],
  ["2026-09-29", "claude-code", "claude-opus-5-5", 5, 100, 400, 0, 0, 0.5],
  ["2026-09-29", "codex", "gpt-6-astra", 3, 10, 80, 0, 10, 2],
  ["2026-08-01", "opencode", "muse-spark", 1, 1, 0, 0, 1, null],
  ["2026-09-29", "opencode", "tiny-1", 1, 1, 0, 0, 0, null],
  ["2026-09-29", "opencode", "tiny-2", 1, 1, 0, 0, 0, null],
  ["2026-09-29", "opencode", "tiny-3", 1, 1, 0, 0, 0, null],
  ["2026-09-29", "opencode", "tiny-4", 1, 1, 0, 0, 0, null],
]));

test("the last complete day is the day before the snapshot, in Beijing time", () => {
  assert.equal(lastDay("2026-09-30T05:00:00+08:00"), "2026-09-29");
  assert.equal(lastDay("2026-09-29T20:00:00Z"), "2026-09-29");
});

test("summaries fill empty days and keep unpriced tokens apart", () => {
  const view = summarize(rows, "2026-09-29", 3, slots(rows));
  assert.deepEqual(view.dates, ["2026-09-27", "2026-09-28", "2026-09-29"]);
  assert.equal(view.total.tokens, 1000 + 500 + 100 + 4);
  assert.equal(view.total.unpriced, 4);
  assert.equal(view.models[0].model, "claude-opus-5-5");
  assert.equal(view.series[0].get("2026-09-27"), 0);
});

test("colour slots follow all-time totals, so a range change never repaints a model", () => {
  const map = slots(rows);
  assert.equal(map.size, SERIES);
  const all = summarize(rows, "2026-09-29", 0, map);
  const recent = summarize(rows, "2026-09-29", 1, map);
  assert.equal(all.start, "2026-08-01");
  for (const model of recent.models) {
    assert.equal(model.slot, all.models.find(other => other.model === model.model).slot);
  }
  assert.equal(recent.models.filter(model => model.slot === SERIES).length, 7 - SERIES); // beyond the coloured slots
});

test("the legend carries each model's range total, with the tail folded into one grey entry", () => {
  const entries = legendEntries(summarize(rows, "2026-09-29", 0, slots(rows)));
  assert.equal(entries.length, SERIES + 1);
  assert.deepEqual(entries[0], { slot: 0, model: "claude-opus-5-5", tokens: 1500, usd: 2 });
  assert.equal(entries[1].usd, 4 - 2);
  const other = entries[SERIES];
  assert.equal(other.usd, null); // unpriced models make the sum unknown, not smaller
});

test("malformed snapshots are rejected", () => {
  for (const bad of [
    { ...snapshot([]), schema_version: 2 },
    snapshot([["2026-9-29", "codex", "m", 1, 1, 1, 1, 1, null]]),
    snapshot([["2026-09-29", "codex", "m", -1, 1, 1, 1, 1, null]]),
    snapshot([["2026-09-29", "codex", "m", 1, 1, 1, 1, 1, -2]]),
  ]) assert.throws(() => parse(bad));
});

test("x stays one column per day; y is linear up to 1B, outliers are squeezed above it", () => {
  const view = summarize(rows, "2026-09-29", 0, slots(rows));
  assert.equal(columns(view).length, 60);
  const days = [0.3e9, 0.5e9, 0.6e9, 0.7e9, 0.8e9, 0.9e9, 0.4e9, 0.2e9, 0.83e9, 0.1e9, 3.3e9, 29.8e9];
  const y = yScale(days);
  assert.equal(y.threshold, 1e9);
  assert.equal(y.at(5e8), 0.4);              // linear: half the threshold, half the linear band
  assert.equal(y.at(1e9), 0.8);
  assert.equal(y.at(29.8e9), 1);
  assert.ok(y.at(3.3e9) > 0.8 && y.at(3.3e9) < 0.9);
  assert.deepEqual(y.ticks, [5e8, 1e9, 1e10]);
  const flat = yScale([1e8, 2e8, 3e8]);       // no outliers: plain linear axis
  assert.equal(flat.threshold, null);
  assert.equal(flat.at(2.5e8), 0.5);
});

test("tooltips get per-model, per-tool rows with API price, largest first", () => {
  const view = summarize(rows, "2026-09-29", 1, slots(rows));
  const day = view.byDay.get("2026-09-29");
  assert.deepEqual(day.slice(0, 2).map(entry => [entry.model, entry.tool]), [["claude-opus-5-5", "claude-code"], ["gpt-6-astra", "codex"]]);
  const astra = day.find(entry => entry.model === "gpt-6-astra");
  assert.deepEqual([astra.tool, astra.tokens, astra.usd], ["codex", 100, 2]);
  assert.equal(day.find(entry => entry.model === "tiny-1").usd, null);
});
