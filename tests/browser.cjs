const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { chromium } = require("playwright");

const base = process.env.APP_URL || "http://127.0.0.1:18766";
const screenshots = process.env.SCREENSHOT_DIR || path.join(os.tmpdir(), "ai-usage-preview");
fs.mkdirSync(screenshots, { recursive: true });
const day = offset => new Date(Date.now() + 8 * 3600000 - offset * 86400000).toISOString().slice(0, 10);
const tokens = { schema_version: 1, updated_at: new Date().toISOString(), timezone: "Asia/Shanghai", machines: 3, stale_machines: 1,
  columns: ["date", "tool", "model", "requests", "input", "cache_read", "cache_write", "output", "api_usd"],
  rows: [
    [day(1), "claude-code", "claude-opus-5-5", 800, 2000000, 90000000, 3000000, 900000, 42.5],
    [day(2), "codex", "gpt-6-astra", 300, 5000000, 40000000, 0, 400000, 120],
    [day(40), "codex", "gpt-5.6-sol", 9000, 90000000, 900000000, 0, 5000000, 900],
    [day(3), "opencode", "muse-spark-1.3-contributor", 50, 10000, 900000, 0, 5000, null],
  ] };

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: "reduce" });
  let mode = "ok";
  const errors = [];
  await context.route("**/*", async route => {
    const url = route.request().url();
    if (url === base + "/data/tokens.json") {
      return mode === "outage" ? route.fulfill({ status: 503, body: "" }) : route.fulfill({ json: tokens });
    }
    if (url === base + "/api/stats") return route.fulfill({ status: 503, body: "" });
    if (url.startsWith(base + "/")) return route.continue();
    return route.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(base + "/");
    await page.locator("#tokens:not(.is-loading)").waitFor();
    assert.equal(await page.title(), "AI 使用实况");
    assert.equal(await page.locator('[data-range="60"]').getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#tk-legend li").count(), 4);
    assert.match(await page.locator("#tk-legend li").first().innerText(), /\$900$/);
    await page.locator('[data-range="365"]').click();
    assert.equal(await page.locator('[data-range="365"]').getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("#tk-updated").innerText(), /1 台未连上/);
    await page.locator('[data-range="0"]').click();
    assert.equal(await page.locator("#tk-legend li").count(), 4);
    const box = await page.locator("#tk-chart svg").boundingBox();
    await page.mouse.move(box.x + box.width - 30, box.y + box.height / 2);
    await page.locator("#tk-tip:not([hidden])").waitFor();
    assert.equal(await page.locator("#tk-chart g.is-day").count(), 1, "hovered day stays lit, the rest fade");
    assert.equal(await page.locator(".support-panel[open]").count(), 0);
    assert.ok(await page.locator(".usage-notes li").count() > 0);
    const ids = await page.locator("[id]").evaluateAll(nodes => nodes.map(node => node.id));
    assert.equal(new Set(ids).size, ids.length, "Duplicate HTML ids");
    await page.screenshot({ path: path.join(screenshots, "desktop.png"), fullPage: true });

    await page.goto(base + "/#model-tests");
    await page.locator("#candy-form").waitFor({ state: "visible" });
    assert.equal(new URL(page.url()).hash, "#model-tests");
    await page.goto(base + "/#works");
    await page.locator(".gallery").waitFor({ state: "visible" });
    const works = await page.locator(".gallery > article").count();
    assert.ok(works > 0);
    await page.locator('.check-list[data-options-for="model"] input').first().check();
    assert.ok(new URL(page.url()).searchParams.has("model"));
    await page.reload();
    await page.locator("#artwork-panel[open]").waitFor();
    assert.ok(await page.locator(".gallery > article:visible").count() < works);
    await page.locator(".gallery > article:visible .expand").first().click();
    await page.locator("dialog[open]").waitFor();
    await page.locator("#close-viewer").click();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + "/");
    await page.locator("#tokens:not(.is-loading)").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "Mobile page overflows");
    await page.screenshot({ path: path.join(screenshots, "mobile.png"), fullPage: true });
    mode = "outage";
    await page.reload();
    await page.locator("#tokens.is-error").waitFor();
    assert.match(await page.locator("#tk-updated").innerText(), /读取失败/);
    assert.deepEqual(errors, [], "Uncaught browser errors");
    console.log("Browser checks passed: dashboard ranges, hover, stale machines, outage, mobile width, deep links, gallery filters and viewer.");
    console.log("Synthetic-data screenshots:", screenshots);
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
