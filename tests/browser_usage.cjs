const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const base = process.env.APP_URL || "http://127.0.0.1:18766";
const screenshots = process.env.SCREENSHOT_DIR || path.join(os.tmpdir(), "ai-usage-preview");
fs.mkdirSync(screenshots, { recursive: true });
const fixtures = JSON.parse(execFileSync("python3", ["-c", `
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from test_usage import legacy_fixture, claude_fixture
from usage import public_usage
now = datetime.now(timezone.utc)
legacy = legacy_fixture()
legacy.update(start=(now-timedelta(days=7)).isoformat(), end=now.isoformat(), updated_at=now.isoformat())
claude = claude_fixture()
claude.update(period={'start': (now-timedelta(days=1)).isoformat(), 'end': now.isoformat()}, updated_at=now.isoformat())
with tempfile.TemporaryDirectory() as state:
    (Path(state)/'stats.json').write_text(json.dumps(legacy))
    pending = public_usage(state)
    (Path(state)/'usage-sources.json').write_text(json.dumps({'schema_version':1,'sources':[claude]}))
    ready = public_usage(state)
print(json.dumps({'pending':pending,'ready':ready,'legacy':dict(legacy,tests={},running=[])}))
`], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "monitor") }, encoding: "utf8" }));

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: "reduce" });
  let mode = "pending";
  const errors = [];
  await context.route("**/*", async route => {
    const url = route.request().url();
    if (url.startsWith(base + "/")) return route.continue();
    if (url === "https://sytoken.org/ai-recommend/api/stats") {
      return route.fulfill({ json: fixtures.legacy });
    }
    if (url === "https://sytoken.org/ai-recommend/api/usage") {
      if (mode === "legacy") return route.fulfill({ status: 404, json: {} });
      if (mode === "outage") return route.fulfill({ status: 503, json: {} });
      if (mode === "invalid") return route.fulfill({ json: null });
      const data = structuredClone(fixtures[mode === "stale" ? "ready" : mode]);
      if (mode === "stale") {
        for (const source of data.sources) {
          source.updated_at = new Date(Date.now() - 7200000).toISOString();
          source.period.end = source.updated_at;
          source.period.start = new Date(Date.now() - 172800000).toISOString();
        }
      }
      return route.fulfill({ json: data });
    }
    return route.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(base + "/");
    await page.locator('[data-source="gpt-vps"].is-ready').waitFor();
    assert.equal(await page.title(), "我的 AI 使用实况");
    assert.equal(await page.locator('[data-source="claude"] .source-metrics').count(), 0);
    assert.match(await page.locator('[data-source="claude"]').innerText(), /待接入/);
    assert.equal(await page.locator(".support-panel[open]").count(), 0);
    assert.match(await page.locator(".usage-notes").innerText(), /还没有公开手记/);
    const ids = await page.locator("[id]").evaluateAll(nodes => nodes.map(node => node.id));
    assert.equal(new Set(ids).size, ids.length, "Duplicate HTML ids");
    await page.screenshot({ path: path.join(screenshots, "desktop.png"), fullPage: true });

    mode = "ready";
    await page.locator("#usage-refresh").click();
    await page.locator('[data-source="claude"].is-ready').waitFor();
    assert.match(await page.locator('[data-source="claude"]').innerText(), /Claude Code/);
    assert.match(await page.locator('[data-source="claude"] .source-metrics').innerText(), /估算费用（非实付）/);
    await page.locator('[data-source="claude"] .source-details > summary').click();
    assert.match(await page.locator('[data-source="claude"] table').innerText(), /1,700/);
    await page.locator("#usage-refresh").click();
    await page.waitForFunction(() => !document.getElementById("usage-refresh").disabled);
    assert.equal(await page.locator('[data-source="claude"] .source-details[open]').count(), 1);

    mode = "outage";
    await page.locator("#usage-refresh").click();
    await page.waitForFunction(() => document.getElementById("usage-status").textContent.includes("保留上次快照"));
    assert.match(await page.locator('[data-source="claude"] .source-badge').innerText(), /旧快照/);
    assert.match(await page.locator('[data-source="claude"] table').innerText(), /1,700/);
    mode = "invalid";
    await page.locator("#usage-refresh").click();
    await page.waitForFunction(() => !document.getElementById("usage-refresh").disabled);
    assert.match(await page.locator("#usage-status").innerText(), /保留上次快照/);

    mode = "stale";
    await page.locator("#usage-refresh").click();
    await page.waitForFunction(() => document.getElementById("usage-status").textContent.includes("部分快照已过期"));
    assert.match(await page.locator('[data-source="claude"] .source-badge').innerText(), /已过期/);

    mode = "legacy";
    await page.locator("#usage-refresh").click();
    await page.waitForFunction(() => document.getElementById("usage-status").textContent.includes("旧版 VPS 接口"));
    assert.equal(await page.locator('[data-source="claude"] .source-metrics').count(), 0);
    await page.goto(base + "/#model-tests");
    await page.locator("#candy-form").waitFor({ state: "visible" });
    assert.equal(new URL(page.url()).hash, "#model-tests");
    await page.goto(base + "/#works");
    await page.locator(".gallery").waitFor({ state: "visible" });
    assert.equal(await page.locator(".gallery > article").count(), 26);
    await page.locator('.check-list[data-options-for="model"] input').first().check();
    assert.ok(new URL(page.url()).searchParams.has("model"));
    await page.reload();
    await page.locator("#artwork-panel[open]").waitFor();
    assert.ok(await page.locator(".gallery > article:visible").count() < 26);
    await page.locator(".gallery > article:visible .expand").first().click();
    await page.locator("dialog[open]").waitFor();
    await page.locator("#close-viewer").click();

    mode = "pending";
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + "/");
    await page.locator('[data-source="gpt-vps"].is-ready').waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "Mobile page overflows");
    await page.screenshot({ path: path.join(screenshots, "mobile.png"), fullPage: true });
    mode = "ready";
    await page.locator("#usage-refresh").click();
    await page.locator('[data-source="claude"].is-ready').waitFor();
    await page.locator('[data-source="claude"] .source-details > summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "Mobile metrics overflow");
    await page.screenshot({ path: path.join(screenshots, "claude-connected-mobile.png"), fullPage: true });
    assert.deepEqual(errors, [], "Uncaught browser errors");
    console.log("Browser checks passed: desktop/mobile, pending/ready Claude, exact counts, stale/error/null snapshots, legacy fallback, deep links, gallery filters and viewer.");
    console.log("Synthetic-data screenshots:", screenshots);
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
