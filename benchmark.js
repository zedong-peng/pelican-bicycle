(() => {
  "use strict";
  // Absolute canonical endpoint also lets the GitHub Pages mirror show live data.
  const api = location.pathname.startsWith("/ai-recommend/")
    ? "/ai-recommend/api/" : "https://sytoken.org/ai-recommend/api/";
  const status = document.getElementById("live-status");
  const date = value => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
  const percent = value => Number.isFinite(value) ? (value * 100).toFixed(1) + "%" : "暂无数据";
  function renderValue(element, value, updatedAt) {
    const label = document.createElement("span");
    label.textContent = value;
    element.replaceChildren(label);
    if (updatedAt) {
      const stamp = document.createElement("small");
      stamp.className = "bm-updated";
      stamp.textContent = `更新于 ${date(updatedAt)}`;
      element.append(stamp);
    }
  }
  let busy = false;

  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(api + "stats", { cache: "no-store", signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error("数据服务暂不可用");
      const data = await response.json();
      const age = Date.now() - Date.parse(data.updated_at);
      renderValue(status, data.updated_at
        ? `统计区间：${date(data.start)} — ${date(data.end)}（北京时间）${age > 900000 ? " · 数据已过期，等待更新" : ""}`
        : "用量统计尚未生成。", data.updated_at);
      for (const row of document.querySelectorAll("tr[data-channel]")) {
        const id = row.dataset.channel;
        const stats = data.channels[id];
        renderValue(row.querySelector(".availability"), stats
          ? `${data.availability_verified ? percent(stats.availability) : "日志覆盖待确认"}（${stats.successes}/${stats.requests} 请求）`
          : "暂无数据", stats ? data.updated_at : null);
        renderValue(row.querySelector(".cache-rate"), stats
          ? `${percent(stats.cache_rate)}（${stats.usage_requests} 次用量记录）` : "暂无数据", stats ? data.updated_at : null);
        if (stats) row.querySelector(".cache-rate").title = `缓存读取 ${stats.cached_tokens.toLocaleString()} / 总输入 ${stats.input_tokens.toLocaleString()} token`;
        const power = row.querySelector(".bm-power");
        const price = stats?.upstream_price;
        const cell = row.querySelector(".bm-input");
        const hasRate = Number.isFinite(price?.multiplier);
        const fresh = price?.status === "ok" && Date.parse(price.fresh_until) > Date.now();
        const label = fresh ? "" : price?.status === "error" ? " · 探测失败" : " · 已过期";
        renderValue(cell, hasRate ? `${price.multiplier}×${label}` : "暂无上游倍率", price?.received_at);
        if (hasRate && fresh && age <= 900000) power.dataset.bmMult = price.multiplier;
        else delete power.dataset.bmMult;
        if (stats && Number.isFinite(stats.cache_rate)) power.dataset.bmCache = stats.cache_rate * 100;
        else delete power.dataset.bmCache;
        // Price the observed mix, including output; do not borrow Pro's mix.
        const input = stats?.input_tokens;
        const cached = stats?.cached_tokens;
        const output = stats?.output_tokens;
        if ([input, cached, output].every(Number.isFinite) && input >= cached && cached >= 0 && output >= 0 && input + output > 0) {
          power.dataset.bmInput = input;
          power.dataset.bmCached = cached;
          power.dataset.bmOutput = output;
        } else {
          delete power.dataset.bmInput;
          delete power.dataset.bmCached;
          delete power.dataset.bmOutput;
        }
        const test = data.tests[id];
        const running = data.running.includes(id);
        const result = row.querySelector(".test-result");
        const details = row.querySelector(".test-details");
        renderValue(result, test
          ? `${test.passed ? "✓" : "✗"} ${test.samples.filter(s => s.ok === true).length}/5`
          : running ? "检测中…" : "尚未检测", test?.finished_at);
        if (test) {
          // Put the disclosure after the score, before the timestamp.
          result.insertBefore(details, result.querySelector(".bm-updated"));
        }
        if (test && details.dataset.finished !== test.finished_at) {
          details.hidden = false;
          details.dataset.finished = test.finished_at;
          const content = details.querySelector("div");
          const block = document.createElement("pre");
          block.className = "test-log";
          block.tabIndex = 0;
          block.setAttribute("aria-label", "五次检测记录，可横向和纵向滚动");
          const code = document.createElement("code");
          code.textContent = test.samples.map((sample, index) =>
            `第 ${index + 1} 次  ${sample.ok === true ? "✓" : sample.ok === false ? "✗" : "异常"}\n${sample.answer || sample.error}`
          ).join("\n\n────────────────────\n\n");
          block.append(code);
          content.replaceChildren(block);
        }
      }
      window.dispatchEvent(new Event("benchmark-updated"));
      for (const cell of document.querySelectorAll(".bm-power")) {
        renderValue(cell, cell.textContent, cell.textContent === "—" ? null : data.updated_at);
      }
    } catch (error) {
      status.textContent = "暂时无法更新 VPS 数据，已显示的数据可能过期。";
    } finally {
      busy = false;
    }
  }

  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 15000);
})();
