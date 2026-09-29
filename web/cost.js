(function () {
  const $ = (id) => document.getElementById("cc-" + id);
  // V2EX topic 1241470, supplement 1 (2026-09-15). Treat this later sample as one week.
  const SAMPLE = { uncached: 26789763, cached: 845564800, output: 4447678 };
  const budget = 200;
  const exchange = 6.7223; // USD/CNY, Frankfurter historical rate dated 2026-09-01.
  const PRICE = { input: 10, cache: 1, output: 50 };
  const total = SAMPLE.uncached + SAMPLE.cached + SAMPLE.output;
  const inputShare = (SAMPLE.uncached + SAMPLE.cached) / total;
  const cacheRate = SAMPLE.cached / (SAMPLE.uncached + SAMPLE.cached) * 100;
  const monthScale = 30 / 7;
  const monthTokens = total * monthScale / 1e6;
  const proPerM = budget * exchange / monthTokens;
  const sampleApiCost = (SAMPLE.uncached * PRICE.input + SAMPLE.cached * PRICE.cache + SAMPLE.output * PRICE.output) / 1e6;
  const referenceApiPerM = sampleApiCost / (total / 1e6);
  const proInputPrice = PRICE.input * proPerM / referenceApiPerM;
  const num = (n, digits = 2) => n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const apiDollars = (tokensM) => "$" + num(tokensM * referenceApiPerM);
  const metric = (label, value, detail = "") => `<div class="metric"><div class="k">${label}</div><div class="v">${value}</div>${detail ? `<div class="u">${detail}</div>` : ""}</div>`;

  $("pricesP").textContent = `每百万 token：输入 $${PRICE.input} · 缓存 $${PRICE.cache} · 输出 $${PRICE.output}`;
  $("inputShare").textContent = "输入 : 输出 = " + num((SAMPLE.uncached + SAMPLE.cached) / SAMPLE.output) + " : 1，缓存率 " + num(cacheRate) + "%";
  $("distribution").innerHTML = [
    ["非缓存输入", SAMPLE.uncached, SAMPLE.uncached * PRICE.input],
    ["缓存输入", SAMPLE.cached, SAMPLE.cached * PRICE.cache],
    ["输出（含推理）", SAMPLE.output, SAMPLE.output * PRICE.output],
    ["合计", total, sampleApiCost * 1e6],
  ].map(([label, count, cost]) => `<tr><th scope="row">${label}</th><td>${num(count, 0)}</td><td>$${num(cost / 1e6)}</td></tr>`).join("");
  $("metricsP").innerHTML = metric("$200 可购买的 API 等价额度", apiDollars(monthTokens)) +
    metric("非缓存输入 / 百万 token", "¥" + num(proInputPrice, 3));
  $("cachePLabel").textContent = num(cacheRate, 1) + "%";

  const relayPerM = (paidMult, cache) => paidMult * (inputShare * ((1 - cache / 100) * PRICE.input + cache / 100 * PRICE.cache) + (1 - inputShare) * PRICE.output);
  function renderPurchasingPower() {
    for (const cell of document.querySelectorAll(".bm-power")) {
      const values = ["bmMult", "bmInput", "bmCached", "bmOutput"];
      if (!values.every(key => cell.dataset[key] !== undefined)) {
        cell.textContent = "—";
        cell.removeAttribute("title");
        continue;
      }
      const [mult, input, cached, output] = values.map(key => Number(cell.dataset[key]));
      const tokens = input + output;
      const standardCost = ((input - cached) * PRICE.input + cached * PRICE.cache + output * PRICE.output) / 1e6;
      const estimatedCost = standardCost * mult;
      const perM = estimatedCost / (tokens / 1e6);
      const stale = cell.dataset.bmStale;
      cell.textContent = perM > 0 ? num(proPerM / perM * 100, 1) + "%" + (stale ? "*" : "") : "—";
      cell.title = `近一周总输入 ${num(input, 0)}、缓存读取 ${num(cached, 0)}、输出 ${num(output, 0)} token；按${stale ? "上次有效" : "当前"}倍率估算 ¥${num(estimatedCost)}，每百万总 token ¥${num(perM)}${stale ? "（倍率探测异常，沿用旧值）" : ""}。相同预算可购买总 token 数 / Pro 20x 样本月度总 token 数。`;
    }
  }
  window.addEventListener("benchmark-updated", renderPurchasingPower);
  renderPurchasingPower();

  const previousRecharge = { A: 1, B: 1 };

  function render() {
    const availableTokens = { P: monthTokens };
    for (const station of ["A", "B"]) {
      const slider = $("mult" + station);
      const recharge = Number($("recharge" + station).value);
      const cache = Number($("cache" + station).value);
      $("cache" + station + "Label").textContent = num(cache, 1) + "%";
      if (!Number.isFinite(recharge) || recharge < 0.01) {
        $("metrics" + station).innerHTML = metric("$200 可购买的 API 等价额度", "—", "充值倍率须 ≥ 0.01");
        continue;
      }
      if (recharge !== previousRecharge[station]) {
        const next = Number(slider.value) * recharge / previousRecharge[station];
        slider.min = String(0.05 * recharge);
        slider.max = String(0.5 * recharge);
        slider.step = String(0.005 * recharge);
        slider.value = String(next);
        previousRecharge[station] = recharge;
      }
      const mult = Number(slider.value);
      const paidMult = mult / recharge;
      $("mult" + station + "Label").textContent = mult.toLocaleString("en-US", { maximumSignificantDigits: 4 }) + "×";
      const perM = relayPerM(paidMult, cache);
      const tokens = budget * exchange / perM;
      const inputPrice = PRICE.input * paidMult;
      availableTokens[station] = tokens;
      const difference = Number(((inputPrice / proInputPrice - 1) * 100).toFixed(1));
      const comparison = "比 Pro 20x " + (difference > 0 ? "+" : "") + num(difference, 1) + "%";
      $("metrics" + station).innerHTML = metric("$200 可购买的 API 等价额度", apiDollars(tokens), "Pro 20x 的 " + num(tokens / monthTokens * 100, 1) + "%") + metric("非缓存输入 / 百万 token", "¥" + num(inputPrice, 3), comparison);
    }
    const stations = ["P", "A", "B"];
    const complete = stations.every(station => Number.isFinite(availableTokens[station]));
    const ranked = complete ? [...stations].sort((a, b) => availableTokens[b] - availableTokens[a]) : [];
    for (const station of stations) {
      const badge = $("badge" + station);
      const rank = complete ? ranked.indexOf(station) : -1;
      badge.hidden = !complete;
      badge.className = "badge " + (rank === 0 ? "badge-best" : rank === ranked.length - 1 ? "badge-worst" : "badge-middle");
      badge.textContent = rank === 0 ? "最便宜" : rank === ranked.length - 1 ? "最贵" : "中等";
      badge.title = "按相同预算下 API 等价额度排序";
    }

  }
  for (const id of ["multA", "multB", "cacheA", "cacheB", "rechargeA", "rechargeB"]) $(id).addEventListener("input", render);
  render();
})();
