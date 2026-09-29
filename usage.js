(() => {
  "use strict";

  const count = value => Number.isSafeInteger(value) && value >= 0;
  const timestamp = value => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
  const number = value => count(value) ? value.toLocaleString("zh-CN") : "未提供";
  const compact = value => count(value) ? new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(value) : "未提供";
  const date = value => timestamp(value) ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "未提供";
  const percent = value => Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "未提供";
  const sum = values => values.length && values.every(count) && count(values.reduce((a, b) => a + b, 0))
    ? values.reduce((a, b) => a + b, 0) : null;

  function pendingClaude() {
    return { id: "claude", label: "Claude", provider: "Anthropic", tool: null, models: [],
      scope: "Claude 用量尚未接入；不计入当前统计。", status: "pending", updated_at: null,
      period: null, freshness_seconds: 900, availability_verified: false, metrics: null };
  }

  function fromLegacy(data) {
    if (!data || typeof data !== "object" || !data.channels || typeof data.channels !== "object" || Array.isArray(data.channels)) {
      throw new Error("Invalid legacy snapshot");
    }
    const rows = Object.values(data.channels);
    const source = { id: "gpt-vps", label: "GPT · VPS", provider: "OpenAI", tool: null,
      models: typeof data.model === "string" ? [data.model] : [],
      scope: "仅统计我经 VPS 调用的已配置模型。请求记录按渠道计数，跨渠道切换分别计入，不等于独立任务数。",
      status: data.updated_at ? "ready" : "pending", updated_at: data.updated_at || null,
      period: data.updated_at ? { start: data.start, end: data.end } : null,
      freshness_seconds: 900, availability_verified: data.availability_verified === true, metrics: null };
    if (source.status === "ready") {
      const total = key => sum(rows.map(row => row?.[key]));
      source.metrics = { requests: total("requests"), successes: total("successes"),
        total_input_tokens: total("input_tokens"), cache_read_tokens: total("cached_tokens"),
        cache_creation_tokens: null, output_tokens: total("output_tokens"), cost: null };
    }
    return validateSnapshot({ schema_version: 1, sources: [source, pendingClaude()], extensions_status: "missing" });
  }

  function validateSnapshot(data) {
    if (!data || data.schema_version !== 1 || !Array.isArray(data.sources) || !data.sources.length || data.sources.length > 32) {
      throw new Error("Unsupported usage snapshot");
    }
    const ids = new Set();
    for (const source of data.sources) {
      if (!source || typeof source.id !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(source.id) || ids.has(source.id)
          || typeof source.label !== "string" || !source.label.trim() || typeof source.provider !== "string"
          || (source.tool !== null && typeof source.tool !== "string") || typeof source.scope !== "string"
          || !Array.isArray(source.models) || !source.models.every(model => typeof model === "string")
          || !["ready", "pending", "error"].includes(source.status) || typeof source.availability_verified !== "boolean"
          || !Number.isSafeInteger(source.freshness_seconds) || source.freshness_seconds < 60) {
        throw new Error("Invalid usage source");
      }
      ids.add(source.id);
      if (source.status !== "ready") {
        if (source.metrics !== null || source.period !== null || source.updated_at !== null) throw new Error("Inactive source has metrics");
        continue;
      }
      if (!timestamp(source.updated_at) || !timestamp(source.period?.start) || !timestamp(source.period?.end)
          || Date.parse(source.period.start) >= Date.parse(source.period.end) || Date.parse(source.period.end) > Date.parse(source.updated_at)) {
        throw new Error("Invalid usage period");
      }
      const metrics = source.metrics;
      const fields = ["requests", "successes", "total_input_tokens", "cache_read_tokens", "cache_creation_tokens", "output_tokens"];
      if (!metrics || !fields.every(key => metrics[key] === null || count(metrics[key]))) throw new Error("Invalid usage metrics");
      if (count(metrics.requests) && count(metrics.successes) && metrics.successes > metrics.requests) throw new Error("Invalid success count");
      const cached = (metrics.cache_read_tokens ?? 0) + (metrics.cache_creation_tokens ?? 0);
      if (count(metrics.total_input_tokens) && cached > metrics.total_input_tokens) throw new Error("Invalid cache count");
      const cost = metrics.cost;
      if (cost !== null && (!cost || typeof cost.amount !== "number" || !Number.isFinite(cost.amount) || cost.amount < 0
          || typeof cost.currency !== "string" || !/^[A-Z]{3}$/.test(cost.currency) || !["actual", "estimate"].includes(cost.basis))) {
        throw new Error("Invalid usage cost");
      }
    }
    return data;
  }

  function derivedMetrics(source) {
    const metrics = source.metrics || {};
    const cacheRate = count(metrics.cache_read_tokens) && count(metrics.total_input_tokens) && metrics.total_input_tokens > 0
      ? metrics.cache_read_tokens / metrics.total_input_tokens : null;
    const availability = source.availability_verified && count(metrics.requests) && metrics.requests > 0 && count(metrics.successes)
      ? metrics.successes / metrics.requests : null;
    return { total: sum([metrics.total_input_tokens, metrics.output_tokens]), cacheRate, availability };
  }

  function sourceState(source, now = Date.now(), failed = false) {
    if (source.status === "pending") return { label: "○ 待接入", className: "is-pending" };
    if (source.status === "error") return { label: "! 暂不可用", className: "is-error" };
    if (failed) return { label: "! 更新失败 · 旧快照", className: "is-stale" };
    if (now - Date.parse(source.updated_at) > source.freshness_seconds * 1000) return { label: "◷ 数据已过期", className: "is-stale" };
    return { label: "✓ 已接入", className: "is-ready" };
  }

  function money(cost) {
    return cost ? new Intl.NumberFormat("zh-CN", { style: "currency", currency: cost.currency,
      minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(cost.amount) : "未提供";
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { fromLegacy, validateSnapshot, derivedMetrics, sourceState, pendingClaude, sum };
    return;
  }

  const root = document.getElementById("usage-sources");
  const status = document.getElementById("usage-status");
  const refreshButton = document.getElementById("usage-refresh");
  if (!root || !status || !refreshButton) return;
  const api = location.pathname.startsWith("/ai-recommend/")
    ? "/ai-recommend/api/" : "https://sytoken.org/ai-recommend/api/";
  const legacyEndpoint = Symbol("legacy endpoint");

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderSource(source, failed, expanded) {
    const state = sourceState(source, Date.now(), failed);
    const card = element("section", `usage-source ${state.className}`);
    card.dataset.source = source.id;
    card.setAttribute("aria-labelledby", `usage-source-${source.id}`);
    card.append(element("p", "source-provider", source.provider));
    const heading = element("div", "source-heading");
    const title = element("h3", "", source.label);
    title.id = `usage-source-${source.id}`;
    heading.append(title, element("span", "source-badge", state.label));
    card.append(heading);
    if (source.status !== "ready") {
      card.append(element("p", "source-empty-title", source.status === "pending" ? "等待接入真实用量" : "暂时无法读取用量"),
        element("p", "source-scope", source.scope),
        element("p", "source-scope", source.status === "pending"
          ? "接入后独立展示统计区间、模型与用量。未接入不代表用量为零。"
          : "该来源没有可展示的有效快照，其他来源的记录不受影响。"));
      return card;
    }
    const metrics = source.metrics;
    const derived = derivedMetrics(source);
    card.append(element("p", "source-context", `模型：${source.models.join(" · ") || "未区分"}　/　工具：${source.tool || "未区分"}`),
      element("p", "source-scope", source.scope));
    const values = element("dl", "source-metrics");
    const costLabel = metrics.cost?.basis === "estimate" ? "估算费用（非实付）" : "实际支出";
    for (const [label, value, exact] of [
      ["请求记录", compact(metrics.requests), number(metrics.requests)],
      ["总 Token（输入 + 输出）", compact(derived.total), number(derived.total)],
      ["输入缓存读取率", percent(derived.cacheRate)],
      [costLabel, money(metrics.cost)],
    ]) {
      const pair = element("div");
      const figure = element("dd", value === "未提供" ? "is-unknown" : "", value);
      if (exact) figure.title = exact;
      pair.append(element("dt", "", label), figure);
      values.append(pair);
    }
    card.append(values, element("p", "source-period", `统计区间：${date(source.period.start)} — ${date(source.period.end)}`),
      element("p", "source-updated", `更新于 ${date(source.updated_at)} · 北京时间`));
    const details = element("details", "source-details");
    details.open = expanded;
    details.append(element("summary", "", "查看精确用量与口径"));
    const table = element("table");
    table.append(element("caption", "", "Token 均为精确计数；缓存读取和写入已包含在总输入中。"));
    const body = element("tbody");
    for (const [label, value] of [
      ["请求记录", number(metrics.requests)], ["成功记录", number(metrics.successes)],
      ["留存日志可用性", source.availability_verified ? percent(derived.availability) : "错误日志覆盖未确认"],
      ["总输入 Token（含缓存）", number(metrics.total_input_tokens)],
      ["其中：缓存读取 Token", number(metrics.cache_read_tokens)],
      ["其中：缓存写入 Token", number(metrics.cache_creation_tokens)],
      ["输出 Token", number(metrics.output_tokens)], ["总 Token", number(derived.total)],
      [costLabel, money(metrics.cost) + (metrics.cost ? ` ${metrics.cost.currency}` : "")],
    ]) {
      const row = element("tr");
      const labelCell = element("th", "", label);
      labelCell.scope = "row";
      row.append(labelCell, element("td", "", value));
      body.append(row);
    }
    table.append(body);
    details.append(table);
    card.append(details);
    return card;
  }

  function render(data, failed = false) {
    const expanded = new Set([...root.querySelectorAll(".source-details[open]")].map(node => node.closest("[data-source]").dataset.source));
    root.replaceChildren(...data.sources.map(source => renderSource(source, failed, expanded.has(source.id))));
  }

  let busy = false;
  let latest = null;
  async function getJSON(endpoint) {
    const response = await fetch(api + endpoint, { cache: "no-store", signal: AbortSignal.timeout(12000) });
    if (endpoint === "usage" && response.status === 404) return legacyEndpoint;
    if (!response.ok) throw new Error("Usage service unavailable");
    return response.json();
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    refreshButton.disabled = true;
    refreshButton.textContent = "正在刷新…";
    try {
      const response = await getJSON("usage");
      const legacy = response === legacyEndpoint;
      const data = legacy ? fromLegacy(await getJSON("stats")) : validateSnapshot(response);
      latest = data;
      render(data);
      const ready = data.sources.filter(source => source.status === "ready").length;
      const pending = data.sources.filter(source => source.status === "pending").length;
      const errors = data.sources.filter(source => source.status === "error").length;
      const stale = data.sources.some(source => sourceState(source).className === "is-stale");
      status.textContent = `${ready} 个来源已接入${pending ? ` · ${pending} 个待接入` : ""}${errors ? ` · ${errors} 个暂不可用` : ""} · 各来源独立统计`
        + (stale ? " · 部分快照已过期，请留意更新时间。" : "")
        + (legacy ? " · 当前使用旧版 VPS 接口，扩展用量接口尚未上线。" : "")
        + (data.extensions_status === "error" ? " · 扩展用量读取失败，VPS 统计不受影响。" : "");
    } catch {
      if (latest) render(latest, true);
      else {
        const initial = fromLegacy({ channels: {}, updated_at: null });
        initial.sources[0].status = "error";
        render(initial);
      }
      status.textContent = latest ? "暂时无法更新用量；保留上次快照，请以各来源的更新时间为准。" : "暂时无法读取公开用量，不代表用量为零。可稍后刷新重试。";
    } finally {
      busy = false;
      refreshButton.disabled = false;
      refreshButton.textContent = "刷新用量";
    }
  }

  function openAnchor() {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch { return; }
    if (!target) return;
    for (let parent = target; parent; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS") parent.open = true;
    }
    requestAnimationFrame(() => target.scrollIntoView());
  }
  if (["model", "effort", "provider", "harness"].some(key => new URLSearchParams(location.search).has(key))) {
    document.getElementById("artwork-panel").open = true;
    window.dispatchEvent(new Event("resize"));
  }
  document.querySelectorAll(".support-panel").forEach(panel => panel.addEventListener("toggle", () => window.dispatchEvent(new Event("resize"))));
  window.addEventListener("hashchange", openAnchor);
  openAnchor();
  refreshButton.addEventListener("click", refresh);
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 60000);
})();
