const assert = require("node:assert/strict");
const { test } = require("node:test");
const { fromLegacy, validateSnapshot, derivedMetrics, sourceState, pendingClaude, sum } = require("../usage.js");

function legacy() {
  return { model: "gpt-6-astra", updated_at: "2026-09-29T08:00:01Z", start: "2026-09-22T08:00:00Z",
    end: "2026-09-29T08:00:00Z", availability_verified: true,
    channels: { a: { requests: 10, successes: 8, input_tokens: 1000, cached_tokens: 700, output_tokens: 100 },
      b: { requests: 2, successes: 2, input_tokens: 100, cached_tokens: 10, output_tokens: 20 } } };
}

function snapshot() { return fromLegacy(legacy()); }

test("legacy adapter keeps cache inside total input and leaves unknown costs empty", () => {
  const data = snapshot();
  const source = data.sources[0];
  assert.equal(source.metrics.requests, 12);
  assert.equal(source.metrics.total_input_tokens, 1100);
  assert.equal(source.metrics.cache_read_tokens, 710);
  assert.equal(source.metrics.cache_creation_tokens, null);
  assert.equal(source.metrics.cost, null);
  assert.deepEqual(derivedMetrics(source), { total: 1220, cacheRate: 710 / 1100, availability: 10 / 12 });
  assert.equal(data.sources[1].status, "pending");
  assert.equal(data.sources[1].metrics, null);
  assert.equal(data.totals, undefined);
});

test("unknown counters, zero counters and unverified availability stay distinct", () => {
  const data = legacy();
  delete data.channels.a.output_tokens;
  data.availability_verified = false;
  let source = fromLegacy(data).sources[0];
  assert.equal(source.metrics.output_tokens, null);
  assert.equal(derivedMetrics(source).total, null);
  assert.equal(derivedMetrics(source).availability, null);
  data.channels = { a: { requests: 0, successes: 0, input_tokens: 0, cached_tokens: 0, output_tokens: 0 } };
  source = fromLegacy(data).sources[0];
  assert.equal(source.metrics.requests, 0);
  assert.equal(derivedMetrics(source).total, 0);
  assert.equal(derivedMetrics(source).cacheRate, null);
  assert.equal(fromLegacy({ channels: {}, updated_at: null }).sources[0].status, "pending");
  assert.equal(sum([Number.MAX_SAFE_INTEGER, 1]), null);
});

test("Claude uses the same contract without merging periods, costs or cache writes", () => {
  const data = snapshot();
  const source = { ...pendingClaude(), status: "ready", updated_at: "2026-09-29T08:00:01Z",
    period: { start: "2026-09-28T08:00:00Z", end: "2026-09-29T08:00:00Z" },
    tool: "Claude Code", models: ["example-model"],
    metrics: { requests: 20, successes: null, total_input_tokens: 1500, cache_read_tokens: 1000,
      cache_creation_tokens: 200, output_tokens: 200, cost: { amount: 1.25, currency: "USD", basis: "estimate" } } };
  data.sources[1] = source;
  assert.equal(validateSnapshot(data), data);
  assert.equal(derivedMetrics(source).total, 1700);
  assert.equal(derivedMetrics(source).availability, null);
  assert.notDeepEqual(data.sources[0].period, source.period);
});

test("invalid versions, duplicate sources, counts, costs and periods are rejected", () => {
  for (const mutate of [
    data => { data.schema_version = 2; },
    data => { data.sources.push(data.sources[0]); },
    data => { data.sources[0].metrics.requests = true; },
    data => { data.sources[0].metrics.requests = -1; },
    data => { data.sources[0].metrics.cache_read_tokens = 1101; },
    data => { data.sources[0].metrics.cache_creation_tokens = 500; },
    data => { data.sources[0].metrics.successes = 13; },
    data => { data.sources[0].metrics.output_tokens = Infinity; },
    data => { data.sources[0].metrics.cost = { amount: NaN, currency: "USD", basis: "actual" }; },
    data => { data.sources[0].period.end = data.sources[0].period.start; },
    data => { data.sources[0].period.start = "2026-09-22T08:00:00"; },
  ]) {
    const data = snapshot();
    mutate(data);
    assert.throws(() => validateSnapshot(data));
  }
});

test("freshness and fetch failures never pass an old snapshot off as live", () => {
  const source = snapshot().sources[0];
  const now = Date.parse(source.updated_at);
  assert.equal(sourceState(source, now).className, "is-ready");
  assert.equal(sourceState(source, now + 901000).className, "is-stale");
  assert.match(sourceState(source, now, true).label, /旧快照/);
  assert.equal(sourceState(pendingClaude(), now, true).className, "is-pending");
  assert.equal(sourceState({ ...pendingClaude(), status: "error" }, now).className, "is-error");
});
