(() => {
  "use strict";

  const SERIES = 6; // top models get a fixed colour slot; the rest fold into 其他
  const TOOLS = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", cursor: "Cursor" };
  const DAY = 86400000;

  const iso = time => new Date(time).toISOString().slice(0, 10);
  const addDays = (date, days) => iso(Date.parse(date + "T00:00:00Z") + days * DAY);
  const tokensOf = row => row.input + row.cache_read + row.cache_write + row.output;

  // Past this many days the chart reads better one column per week than per day.
  const WEEKLY_AFTER_DAYS = 120;
  // Monday (calendar week) containing date, as YYYY-MM-DD.
  function weekStart(date) {
    const daysSinceEpoch = Math.round(Date.parse(date + "T00:00:00Z") / DAY);
    return addDays(date, -((daysSinceEpoch + 3) % 7));
  }

  function parse(data) {
    if (!data || data.schema_version !== 1 || !Array.isArray(data.rows) || !Array.isArray(data.columns)) {
      throw new Error("Unsupported token snapshot");
    }
    const rows = data.rows.map(values => Object.fromEntries(data.columns.map((key, index) => [key, values[index]])));
    for (const row of rows) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date) || typeof row.model !== "string" || typeof row.tool !== "string"
          || !["requests", "input", "cache_read", "cache_write", "output"].every(key => Number.isSafeInteger(row[key]) && row[key] >= 0)
          || !(row.api_usd === null || (Number.isFinite(row.api_usd) && row.api_usd >= 0))) {
        throw new Error("Invalid token row");
      }
    }
    return rows;
  }

  // Colour follows the model, never its rank in the visible range: slots come from all-time totals.
  function slots(rows) {
    const totals = new Map();
    for (const row of rows) totals.set(row.model, (totals.get(row.model) || 0) + tokensOf(row));
    return new Map([...totals].sort((a, b) => b[1] - a[1]).slice(0, SERIES).map(([model], index) => [model, index]));
  }

  // Last complete day: a 05:00 snapshot only holds a few hours of today.
  function lastDay(updatedAt) {
    return addDays(iso(Date.parse(updatedAt) + 8 * 3600000), -1);
  }

  function summarize(rows, end, days, slotMap) {
    const start = days ? addDays(end, 1 - days) : rows.reduce((min, row) => row.date < min ? row.date : min, end);
    const inRange = rows.filter(row => row.date >= start && row.date <= end);
    const dates = [];
    for (let date = start; date <= end; date = addDays(date, 1)) dates.push(date);
    // Long ranges aggregate into Monday-to-Sunday calendar weeks; edge weeks may be partial.
    const weekly = dates.length > WEEKLY_AFTER_DAYS;
    const buckets = [];
    const bucketOf = new Map();
    for (const date of dates) {
      const key = weekly ? weekStart(date) : date;
      let bucket = bucketOf.get(key);
      if (!bucket) { bucket = { key, start: date, end: date }; bucketOf.set(key, bucket); buckets.push(bucket); }
      bucket.end = date;
    }
    const bucketKey = date => weekly ? weekStart(date) : date;
    const series = Array.from({ length: SERIES + 1 }, () => new Map(buckets.map(bucket => [bucket.key, 0])));
    const models = new Map();
    const tools = new Map();
    const byDay = new Map(buckets.map(bucket => [bucket.key, new Map()]));
    const total = { tokens: 0, unpriced: 0 };
    for (const row of inRange) {
      const tokens = tokensOf(row);
      const slot = slotMap.has(row.model) ? slotMap.get(row.model) : SERIES;
      const day = bucketKey(row.date);
      series[slot].set(day, series[slot].get(day) + tokens);
      const model = models.get(row.model) || { model: row.model, slot, tokens: 0, usd: 0, priced: true };
      model.tokens += tokens;
      if (row.api_usd === null) model.priced = false;
      else model.usd += row.api_usd;
      models.set(row.model, model);
      tools.set(row.tool, (tools.get(row.tool) || 0) + tokens);
      const key = row.model + "|" + row.tool;
      const entry = byDay.get(day).get(key) || { model: row.model, tool: row.tool, slot, tokens: 0, usd: 0 };
      entry.tokens += tokens;
      entry.usd = entry.usd === null || row.api_usd === null ? null : entry.usd + row.api_usd;
      byDay.get(day).set(key, entry);
      total.tokens += tokens;
      if (row.api_usd === null) total.unpriced += tokens;
    }
    return {
      start, end, weekly, buckets,
      dates: buckets.map(bucket => bucket.key), series, total,
      // Per column, per model and tool, largest first (the bars stack the same way, from the bottom).
      byDay: new Map([...byDay].map(([date, entries]) => [date,
        [...entries.values()].sort((a, b) => b.tokens - a.tokens)])),
      models: [...models.values()].sort((a, b) => b.tokens - a.tokens),
      tools: [...tools].sort((a, b) => b[1] - a[1]),
    };
  }

  // One legend entry per colour slot, biggest in the visible range first; "其他" sums the uncoloured tail and stays last.
  function legendEntries(view) {
    const entries = new Map();
    for (const model of view.models) {
      const entry = entries.get(model.slot) || { slot: model.slot, model: model.model, tokens: 0, usd: 0 };
      entry.tokens += model.tokens;
      entry.usd = entry.usd === null || !model.priced ? null : entry.usd + model.usd;
      entries.set(model.slot, entry);
    }
    return [...entries.values()].sort((a, b) => (a.slot === SERIES) - (b.slot === SERIES) || b.tokens - a.tokens);
  }

  // One column per bucket: a calendar day, or a Monday-to-Sunday week on long ranges.
  function columns(view) {
    return view.buckets.map(bucket => ({ date: bucket.key, start: bucket.start, end: bucket.end,
      total: view.series.reduce((sum, series) => sum + series.get(bucket.key), 0) }));
  }

  // Linear y axis for ordinary columns; only outliers above the threshold are squeezed (log) into the top band.
  // 1B covers a heavy day of normal use; the automated sub-agent runs (3B–44B a day) sit above it.
  // Weekly columns hold ~7x a day, so the threshold scales with the column span.
  const DAY_THRESHOLD = 1e9;
  const LINEAR_SHARE = 0.8;
  function niceCeil(value) {
    const step = 10 ** Math.floor(Math.log10(value));
    return [1, 2, 5, 10].map(n => n * step).find(n => n >= value * (1 - 1e-9));
  }
  function yScale(values, daysPerColumn = 1) {
    const threshold = DAY_THRESHOLD * daysPerColumn;
    const positive = values.filter(value => value > 0).sort((a, b) => a - b);
    if (!positive.length) return { threshold: null, ticks: [], at: () => 0 };
    const max = positive[positive.length - 1];
    if (max <= threshold * 1.2) {
      const top = niceCeil(max);
      return { threshold: null, ticks: [top / 2, top], at: value => Math.min(Math.max(value, 0) / top, 1) };
    }
    const span = Math.log10(max) - Math.log10(threshold);
    const at = value => value <= threshold ? Math.max(value, 0) / threshold * LINEAR_SHARE
      : LINEAR_SHARE + (1 - LINEAR_SHARE) * Math.min((Math.log10(value) - Math.log10(threshold)) / span, 1);
    const ticks = [threshold / 2, threshold];
    // One tick in the squeezed band: the first power of ten that has room above the threshold and below the max.
    for (let decade = 10 ** Math.ceil(Math.log10(threshold * 1.0001)); decade < max; decade *= 10) {
      if (at(decade) - LINEAR_SHARE > 0.06 && 1 - at(decade) > 0.04) { ticks.push(decade); break; }
    }
    return { threshold, ticks, at };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { parse, slots, lastDay, summarize, legendEntries, columns, yScale, SERIES };
    return;
  }

  const root = document.getElementById("tokens");
  if (!root) return;
  const $ = id => document.getElementById("tk-" + id);
  const compact = value => new Intl.NumberFormat("en-US", { notation: "compact", maximumSignificantDigits: 3 }).format(value);
  const usd = value => "$" + Math.round(value).toLocaleString("en-US");
  const percent = value => value === null ? "—" : value > 0 && value < 0.005 ? "<1%" : `${(value * 100).toFixed(value >= 0.995 && value < 1 ? 1 : 0)}%`;
  const price = value => value === null ? "—" : value < 1 ? "<$1" : usd(value);
  const short = date => `${Number(date.slice(5, 7))}/${Number(date.slice(8))}`;
  const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  // "SEP 29"; the year is added only when it differs from the neighbour it is read against.
  const tickLabel = (date, reference) => `${MONTHS[Number(date.slice(5, 7)) - 1]} ${Number(date.slice(8))}`
    + (reference && reference.slice(0, 4) !== date.slice(0, 4) ? ` ’${date.slice(2, 4)}` : "");
  const svgNS = "http://www.w3.org/2000/svg";
  const node = (tag, attrs = {}, text) => {
    const element = tag.startsWith("svg:") ? document.createElementNS(svgNS, tag.slice(4)) : document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const label = (slot, model) => slot === SERIES ? "其他" : model;

  let rows = [];
  let slotMap = new Map();
  let end = null;
  let days = 60;
  let view = null;

  function column(x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height);
    return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
  }

  // Hovering a legend entry or a model block lights that model up across every column.
  function focus(slot) {
    root.classList.toggle("has-focus", slot !== null);
    for (const element of root.querySelectorAll("[data-slot]")) {
      element.classList.toggle("is-focus", element.dataset.slot === String(slot));
    }
  }

  function drawChart() {
    const chart = $("chart");
    const width = Math.max(chart.clientWidth, 280);
    const height = width < 560 ? 180 : 220;
    const pad = { top: 8, right: 0, bottom: 22, left: 44 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const cols = columns(view);
    const y = yScale(cols.map(col => col.total), view.weekly ? 7 : 1);
    const slotWidth = plotW / cols.length;
    const gap = slotWidth > 8 ? 2 : slotWidth > 3 ? 1 : 0;
    const barWidth = Math.max(slotWidth - gap, 1);
    const scale = value => y.at(value) * plotH;
    const svg = node("svg:svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img",
      "aria-label": `${view.weekly ? "每周" : "每日"} token，${short(view.start)} 至 ${short(view.end)}` + (y.threshold ? `，超过 ${compact(y.threshold)} 的部分压缩显示` : "") });
    svg.append(node("svg:line", { x1: pad.left, x2: width - pad.right, y1: pad.top + plotH, y2: pad.top + plotH, class: "axis" }));
    for (const tick of y.ticks) {
      const ty = pad.top + plotH - scale(tick);
      svg.append(node("svg:line", { x1: pad.left, x2: width - pad.right, y1: ty, y2: ty, class: tick === y.threshold ? "grid threshold" : "grid" }));
      svg.append(node("svg:text", { x: pad.left - 8, y: ty + 4, class: "tick", "text-anchor": "end" }, compact(tick)));
    }
    const stacks = cols.map(() => []);
    // One group per column, so hovering a column can fade all the others.
    const days = cols.map((col, index) => svg.appendChild(node("svg:g", { "data-day": index })));
    cols.forEach((col, index) => {
      const x = pad.left + index * slotWidth + gap / 2;
      let base = pad.top + plotH;
      let below = 0;
      const stacked = view.series.map((series, slot) => [slot, series.get(col.date)]).filter(([, value]) => value > 0);
      stacked.forEach(([slot, value], order) => {
        const full = scale(below + value) - scale(below);
        below += value;
        stacks[index].push({ slot, top: base - full, bottom: base });
        const segment = order < stacked.length - 1 ? full - (gap ? 1 : 0) : full;
        if (segment < 0.5) { base -= full; return; }
        const segTop = base - full;
        const top = order === stacked.length - 1;
        days[index].append(top ? node("svg:path", { d: column(x, segTop, barWidth, segment, 3), class: `s${slot}`, "data-slot": slot })
          : node("svg:rect", { x, y: segTop + (full - segment), width: barWidth, height: segment, class: `s${slot}`, "data-slot": slot }));
        base -= full;
      });
    });
    // Daily: weekly ticks counted back from the last day (SEP 29, SEP 22, …).
    // Weekly: roughly monthly ticks. Colliding ones are dropped either way.
    const wanted = [];
    for (let index = cols.length - 1; index >= 0; index -= view.weekly ? 4 : 7) wanted.push(index);
    const placed = [];
    for (const index of wanted) {
      if (placed.every(other => Math.abs(other - index) * slotWidth >= 76)) placed.push(index);
    }
    placed.sort((a, b) => a - b).forEach((index, order) => {
      const x = pad.left + (index + 0.5) * slotWidth;
      const anchor = index === cols.length - 1 && x > width - 30 ? "end" : x < pad.left + 20 ? "start" : "middle";
      svg.append(node("svg:text", { x: anchor === "end" ? width : anchor === "start" ? pad.left : x, y: height - 4,
        class: "tick", "text-anchor": anchor }, tickLabel(cols[index].date, order ? cols[placed[order - 1]].date : view.end)));
    });
    const tip = $("tip");
    let shown = null;  // "index|slot" currently in the tooltip
    let day = null;
    function highlightDay(index) {
      if (day) day.classList.remove("is-day");
      day = index === null ? null : days[index];
      if (day) day.classList.add("is-day");
      root.classList.toggle("has-day", day !== null);
    }
    function show(event) {
      const box = svg.getBoundingClientRect();
      const ratio = width / box.width;
      const px = (event.clientX - box.left) * ratio;
      const py = (event.clientY - box.top) * ratio;
      const index = Math.floor((px - pad.left) / slotWidth);
      if (index < 0 || index >= cols.length) return hide();
      const col = cols[index];
      // The segment under the pointer; the 1px gap counts as the segment below it.
      const hit = stacks[index].find(part => py >= part.top - 1 && py <= part.bottom);
      const slot = hit ? hit.slot : null;
      if (shown !== `${index}|${slot}`) {
        shown = `${index}|${slot}`;
        // Blank space in a column keeps the day highlight; a model block lights that model up everywhere.
        highlightDay(slot === null ? index : null);
        focus(slot);
        fillTip(col, slot);
      }
      const left = (event.clientX - box.left) + 16;
      tip.style.left = `${Math.max(0, left + tip.offsetWidth > box.width ? event.clientX - box.left - tip.offsetWidth - 16 : left)}px`;
    }
    function fillTip(col, slot) {
      const entries = view.byDay.get(col.date);
      const dayUsd = entries.every(entry => entry.usd !== null) ? entries.reduce((sum, entry) => sum + entry.usd, 0) : null;
      const head = node("div", { class: "tip-head" });
      const headDate = col.start === col.end ? tickLabel(col.date, view.end)
        : `${tickLabel(col.start, view.end)}–${tickLabel(col.end, view.end)}`;
      head.append(node("strong", {}, headDate), node("span", {}, `${compact(col.total)} · ${price(dayUsd)}`));
      const list = node("div", { class: "tip-list" });
      const listed = entries.slice(0, 8);
      for (const entry of listed) {
        const line = node("div", { class: `tip-row${entry.slot === slot ? " is-focus" : ""}` });
        const name = node("span", { class: "tip-name" });
        name.append(node("i", { class: `dot s${entry.slot}` }), document.createTextNode(entry.model));
        line.append(name, node("span", { class: "tip-tool" }, TOOLS[entry.tool] || entry.tool),
          node("b", {}, compact(entry.tokens)), node("span", { class: "tip-usd" }, price(entry.usd)));
        list.append(line);
      }
      if (entries.length > listed.length) list.append(node("div", { class: "tip-more" }, `还有 ${entries.length - listed.length} 项`));
      if (!entries.length) list.append(node("div", { class: "tip-more" }, "没有记录"));
      tip.replaceChildren(head, list);
      tip.classList.toggle("has-focus", slot !== null);
      tip.hidden = false;
    }
    function hide() { shown = null; tip.hidden = true; highlightDay(null); focus(null); }
    svg.addEventListener("pointermove", show);
    svg.addEventListener("pointerdown", show);
    svg.addEventListener("pointerleave", hide);
    chart.replaceChildren(svg, tip);
  }

  function render() {
    view = summarize(rows, end, days, slotMap);
    $("legend").replaceChildren(...legendEntries(view).map(entry => {
      const item = node("li", { "data-slot": entry.slot });
      item.append(node("i", { class: `dot s${entry.slot}` }), node("span", {}, label(entry.slot, entry.model)),
        node("small", {}, `${compact(entry.tokens)} · ${price(entry.usd)}`));
      return item;
    }));
    $("tools").textContent = view.tools.map(([tool, value]) => `${TOOLS[tool] || tool} ${percent(value / view.total.tokens)}`).join(" · ");
    $("unpriced").hidden = view.total.unpriced / view.total.tokens < 0.005;
    $("unpriced").textContent = `${percent(view.total.unpriced / view.total.tokens)} 的 token 没有官方价，未计入。`;
    drawChart();
  }

  $("legend").addEventListener("pointerover", event => {
    const target = event.target.closest("[data-slot]");
    if (target) focus(Number(target.dataset.slot));
  });
  $("legend").addEventListener("pointerleave", () => focus(null));

  for (const button of document.querySelectorAll("[data-range]")) {
    button.addEventListener("click", () => {
      days = Number(button.dataset.range);
      document.querySelectorAll("[data-range]").forEach(other => other.setAttribute("aria-pressed", String(other === button)));
      if (rows.length) render();
    });
  }
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => view && drawChart(), 120); });

  fetch("data/tokens.json", { cache: "no-store", signal: AbortSignal.timeout(12000) })
    .then(response => { if (!response.ok) throw new Error("HTTP " + response.status); return response.json(); })
    .then(data => {
      rows = parse(data);
      slotMap = slots(rows);
      end = lastDay(data.updated_at);
      const updated = new Date(data.updated_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false,
        month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
      $("updated").textContent = `${updated} 更新 · ${data.machines} 台机器${data.stale_machines ? `，${data.stale_machines} 台未连上，用上次数据` : ""}`;
      root.classList.remove("is-loading");
      render();
    })
    .catch(() => {
      root.classList.remove("is-loading");
      root.classList.add("is-error");
      $("updated").textContent = "读取失败，稍后再刷新。";
    });
})();
