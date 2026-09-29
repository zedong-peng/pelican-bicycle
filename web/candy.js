/* Keys are never persisted. Shared mode publishes only server-scored summaries. */
(() => {
  const prompt = /* CANDY_PROMPT */ "";
  const get = name => document.querySelector(`#candy-${name}`);
  const form = get('form');
  const status = get('status');
  const history = get('history');
  const sharedAPI = document.querySelector('meta[name="candy-shared-api"]')?.content ||
    (location.pathname.startsWith('/ai-board/') ? '/ai-board/api/community' : null);
  const proxy = document.querySelector('meta[name="candy-local-proxy"]')?.content;
  if (proxy) get('connection').textContent = '本地模式：本机转发，不需要 CORS。';
  let active = null;
  const sites = new Map();
  let sharedSnapshot = null;
  get('question').textContent = prompt;

  function endpoint(raw, api) {
    const url = new URL(raw);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error('请填写 HTTP(S) API 地址，不要包含账号、密码、查询参数或片段。');
    }
    let path = url.pathname.replace(/\/+$/, '');
    path = path.replace(/\/(responses|chat\/completions)$/, '');
    url.pathname = `${path || '/v1'}/${api}`;
    return url.href;
  }

  function answerText(data, api) {
    if (api === 'responses') {
      if (data.status && data.status !== 'completed') throw new Error(`响应未完成（${data.status}），本次不判分。`);
      return (data.output || []).filter(item => item.type === 'message')
        .flatMap(item => item.content || []).filter(item => item.type === 'output_text')
        .map(item => item.text || '').join('\n') || data.output_text || '';
    }
    const choice = data.choices?.[0];
    if (choice?.finish_reason && choice.finish_reason !== 'stop') throw new Error(`响应未完成（${choice.finish_reason}），本次不判分。`);
    const content = choice?.message?.content;
    return typeof content === 'string' ? content : (Array.isArray(content) ? content.map(part => part.text || '').join('\n') : '');
  }

  function renderSites() {
    get('sites-count').textContent = `（${sites.size}）`;
    get('sites-empty').hidden = sites.size !== 0;
    get('sites-scroll').hidden = sites.size === 0;
    get('sites-body').replaceChildren(...[...sites.values()].reverse().map(site => {
      const row = document.createElement('tr');
      const values = [site.note, site.url, site.multiplier == null ? '—' : `${site.multiplier}×${site.multiplier_source === 'manual' ? '（手动）' : ''}`, `${site.model} / ${site.effort || '默认'}`,
        new Date(site.timestamp).toLocaleString('zh-CN', { hour12: false })];
      for (const value of values) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      }
      const resultCell = document.createElement('td');
      resultCell.className = 'candy-result';
      const score = document.createElement('span');
      const passed = !site.stopped && site.errors === 0 && site.hits === site.runs;
      score.textContent = `${passed ? '✓' : '✗'} ${site.hits}/${site.runs}`;
      const details = document.createElement('details');
      details.className = 'test-details';
      const summary = document.createElement('summary');
      summary.textContent = '检测记录';
      const content = document.createElement('div');
      const log = document.createElement('pre');
      log.className = 'test-log';
      log.tabIndex = 0;
      log.setAttribute('aria-label', '逐次检测记录，可滚动');
      content.append(log);
      details.append(summary, content);
      let loaded = false;
      let loading = false;
      details.addEventListener('toggle', async () => {
        if (!details.open || loaded || loading) return;
        loading = true;
        log.textContent = '正在加载检测记录…';
        try {
          let samples = site.samples || [];
          if (sharedAPI && site.has_samples) {
            const params = new URLSearchParams({ url: site.url, multiplier: site.multiplier, started_at: site.started_at });
            const response = await fetch(`${sharedAPI}/sites?${params}`, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
            if (!response.ok) throw new Error('检测记录加载失败，请收起后重试。');
            samples = (await response.json()).samples;
          }
          const overview = `计划 ${site.runs} 次 · 有效回复 ${site.completed} 次 · 请求失败 ${site.errors} 次${site.stopped ? ' · 已停止' : ''}`;
          const body = samples.length ? samples.map(sample => {
            const result = sample.error ? '异常' : sample.hit ? '✓' : '✗';
            const time = sample.timestamp ? ` · ${new Date(sample.timestamp).toLocaleString('zh-CN', { hour12: false })}` : '';
            return `第 ${sample.index} 次  ${result} · ${sample.seconds}s${time}\n${sample.answer || sample.error || '无文本'}${sample.truncated ? '\n[回复过长，仅展示前 20,000 字符]' : ''}`;
          }).join('\n\n────────────────────\n\n') : '这条记录未保存逐次回复，或已被更新的测试替换。';
          log.textContent = `${overview}\n\n${body}`;
          loaded = true;
        } catch (error) {
          log.textContent = error.message;
        } finally {
          loading = false;
        }
      });
      resultCell.append(score, details);
      row.append(resultCell);
      return row;
    }));
  }

  async function loadSharedSites() {
    const response = await fetch(`${sharedAPI}/sites`, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('公共记录暂时无法加载。');
    const data = await response.json();
    const snapshot = JSON.stringify(data.sites);
    if (snapshot === sharedSnapshot) return;
    sharedSnapshot = snapshot;
    sites.clear();
    for (const site of data.sites.reverse()) sites.set(JSON.stringify([site.url, site.multiplier]), site);
    renderSites();
  }

  async function runShared() {
    const config = Object.fromEntries(['url', 'note', 'model', 'api', 'effort'].map(field => [field, get(field).value.trim()]));
    config.runs = Number(get('runs').value);
    config.timeout = Number(get('timeout').value);
    let key = get('key').value.trim();
    if (!key) { status.textContent = '请输入 API Key。'; return; }
    const batch = { stopped: false, controller: new AbortController() };
    active = batch;
    const controls = [...form.elements];
    controls.forEach(control => { control.disabled = true; });
    get('key').value = '';
    get('stop').disabled = false;
    renderSites();
    status.textContent = '正在探测 Sub2API 倍率…';
    let finished = false;
    let lastEvent = Date.now();
    const watchdog = setInterval(() => {
      if (Date.now() - lastEvent > 30000) batch.controller.abort();
    }, 5000);
    try {
      const response = await fetch(`${sharedAPI}/test`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...config, key }), signal: batch.controller.signal,
        credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer',
      });
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        throw new Error(failure.error || `HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        lastEvent = Date.now();
        buffer += decoder.decode(value, { stream: true });
        let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, end).trim();
          buffer = buffer.slice(end + 1);
          if (!line) continue;
          const event = JSON.parse(line);
          if (event.type === 'billing') {
            status.textContent = event.multiplier == null ? event.warning : `当前倍率 ${event.multiplier}× · 开始测试…`;
          } else if (event.type === 'sample') {
            const record = document.createElement('details');
            const summary = document.createElement('summary');
            const detail = document.createElement('pre');
            detail.tabIndex = 0;
            const result = event.error ? '请求失败' : event.hit ? '命中 21' : '未命中';
            summary.textContent = `${new Date(event.timestamp).toLocaleString('zh-CN', { hour12: false })} · ${config.note || config.url} · ${event.index}/${config.runs} · ${result} · ${event.seconds}s`.split(key).join('[已隐藏 Key]');
            detail.textContent = String(event.answer || event.error).split(key).join('[已隐藏 Key]');
            record.append(summary, detail);
            history.prepend(record);
            if (history.children.length > 100) history.lastElementChild.remove();
            status.textContent = `已测试 ${event.index}/${config.runs}`;
          } else if (event.type === 'done') {
            const result = event.record;
            status.textContent = `已完成 · 命中 ${result.hits}/${result.completed} · 失败 ${result.errors} · ${event.saved ? '已更新公开记录' : event.warning}`;
            finished = true;
          } else if (event.type === 'error') {
            throw new Error(event.error);
          }
        }
      }
      if (!finished) throw new Error('连接中断，未收到完整测试结果。');
    } catch (error) {
      status.textContent = batch.stopped ? '已停止等待；已发送的请求仍可能计费，若服务器已完成，记录可能已收录。' : String(error.message).split(key).join('[已隐藏 Key]');
    } finally {
      key = '';
      clearInterval(watchdog);
      batch.controller.abort();
      active = null;
      controls.forEach(control => { control.disabled = false; });
      get('stop').disabled = true;
      renderSites();
      await loadSharedSites().catch(() => { get('sites-note').textContent = '公开记录刷新失败，稍后再试。'; });
    }
  }

  if (sharedAPI) {
    get('connection').textContent = '公共测试：自动探测 Sub2API 倍率，服务器判分并收录。';
    get('privacy').textContent = '开始即公开 URL、倍率、模型、强度、备注、结果，以及脱敏后的回复和耗时。Key 不保存。命中不代表模型身份。';
    get('sites-title').textContent = '公开记录';
    get('sites-note').textContent = '同一 URL + 倍率只留最新一次完成的测试，显示最近 200 项。倍率未知、没有有效回复或中途停止的不收录。';
    loadSharedSites().catch(() => { get('sites-empty').textContent = '公开记录暂时读不到，稍后刷新。'; });
    setInterval(() => { if (!active) loadSharedSites().catch(() => {}); }, 60000);
  }

  get('stop').addEventListener('click', () => {
    if (active) {
      active.stopped = true;
      active.controller?.abort();
      status.textContent = '正在停止…';
    }
  });
  window.addEventListener('pagehide', () => {
    get('key').value = '';
    if (active) { active.stopped = true; active.controller?.abort(); }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (active || !form.reportValidity()) return;
    if (sharedAPI) { await runShared(); return; }
    const api = get('api').value;
    let url;
    try { url = endpoint(get('url').value.trim(), api); }
    catch (error) { status.textContent = error.message; return; }
    let key = get('key').value.trim();
    if (!key) { status.textContent = '请输入 API Key。'; return; }
    const redact = value => String(value).split(key).join('[已隐藏 Key]');
    const model = get('model').value.trim();
    if (!model) { status.textContent = '请输入模型名称。'; return; }
    const note = redact(get('note').value.trim() || new URL(url).hostname);
    const effort = get('effort').value;
    const runs = Number(get('runs').value);
    const timeout = Number(get('timeout').value) * 1000;
    const batch = { stopped: false, controller: null };
    active = batch;
    renderSites();
    const controls = [...form.elements];
    controls.forEach(control => { control.disabled = true; });
    get('key').value = '';
    get('stop').disabled = false;
    let hits = 0;
    let completed = 0;
    let errors = 0;
    const samples = [];
    try {
      for (let i = 1; i <= runs && !batch.stopped; i++) {
        status.textContent = `测试中 ${i}/${runs} · 已命中 ${hits}`;
        const record = document.createElement('details');
        const summary = document.createElement('summary');
        const detail = document.createElement('pre');
        detail.tabIndex = 0;
        const timestamp = new Date().toLocaleString('zh-CN', { hour12: false });
        const title = `${timestamp} · ${note} · ${i}/${runs}`;
        summary.textContent = `${title} · 测试中…`;
        record.append(summary, detail);
        history.prepend(record);
        // Bound retained DOM even during a long testing session.
        if (history.children.length > 100) history.lastElementChild.remove();
        const started = performance.now();
        const controller = new AbortController();
        batch.controller = controller;
        let timedOut = false;
        const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
        let result;
        let bodyText;
        let sampleHit = null;
        try {
          const body = { model, stream: false };
          if (api === 'responses') {
            Object.assign(body, { input: prompt, store: false });
            if (effort) body.reasoning = { effort };
          } else {
            body.messages = [{ role: 'user', content: prompt }];
            if (effort) body.reasoning_effort = effort;
          }
          const response = await fetch(proxy || url, {
            method: 'POST', headers: { 'Content-Type': 'application/json', ...(proxy ? {} : { Authorization: `Bearer ${key}` }) },
            body: JSON.stringify(proxy ? { url, key, body, timeout: timeout / 1000 } : body), signal: controller.signal,
            credentials: 'omit', referrerPolicy: 'no-referrer', redirect: 'error', cache: 'no-store',
          });
          if (!response.ok) {
            const failure = proxy ? await response.json().catch(() => ({})) : {};
            throw new Error(failure.error || `HTTP ${response.status}；请检查地址、Key、额度和模型权限。`);
          }
          const data = await response.json();
          if (data.error) throw new Error('接口返回错误，请检查模型与推理强度是否受支持。');
          const answer = answerText(data, api);
          if (!answer.trim()) throw new Error('接口未返回可判分的文本，请检查接口类型。');
          const hit = /(?<!\d)21(?!\d)/u.test(answer.normalize('NFKC'));
          sampleHit = hit;
          hits += Number(hit);
          completed++;
          result = hit ? '命中 21' : '未命中';
          bodyText = `${answer}\n\nToken 用量：${JSON.stringify(data.usage || {})}`;
        } catch (error) {
          result = batch.stopped ? '已停止' : timedOut ? '超时' : '请求失败';
          if (!batch.stopped) errors++;
          if (batch.stopped) {
            bodyText = proxy ? '已停止等待和后续测试；已发往上游的请求可能仍会完成并计费。' : '已取消当前请求。';
          } else if (timedOut) {
            bodyText = `超过 ${timeout / 1000} 秒未完成。`;
          } else if (error instanceof TypeError) {
            bodyText = proxy ? '无法连接本地服务，请确认 local_server.py 正在运行。' :
              '浏览器无法连接：请检查网络、地址、HTTPS 和渠道 CORS 设置（需允许 Authorization / Content-Type）。';
          } else {
            bodyText = error.message;
          }
        } finally {
          clearTimeout(timer);
          batch.controller = null;
        }
        const seconds = ((performance.now() - started) / 1000).toFixed(1);
        summary.textContent = `${title} · ${result} · ${seconds}s`;
        detail.textContent = redact(`地址：${url}\n模型：${model} · 推理强度：${effort || '默认'}\n\n${bodyText}`);
        const savedText = redact(bodyText);
        samples.push({ index: i, timestamp: new Date().toISOString(), seconds, hit: sampleHit,
          truncated: savedText.length > 20000,
          ...(sampleHit !== null ? { answer: savedText.slice(0, 20000) } : { error: savedText.slice(0, 20000) }) });
      }
    } finally {
      // Keep only explicitly selected, redacted fields; never retain request objects or keys.
      const site = {
        url: redact(url), note, model: redact(model), api, effort, runs, timeout: timeout / 1000,
        timestamp: new Date().toISOString(),
        hits, completed, errors, stopped: batch.stopped, samples,
      };
      const siteId = JSON.stringify([site.url, site.note, site.model, api, effort]);
      sites.delete(siteId);
      sites.set(siteId, site);
      if (sites.size > 100) sites.delete(sites.keys().next().value);
      key = '';
      active = null;
      renderSites();
      controls.forEach(control => { control.disabled = false; });
      get('stop').disabled = true;
      status.textContent = `${batch.stopped ? '已停止' : '已完成'} · 命中 ${hits}/${completed} 次有效回复 · 失败 ${errors} 次`;
    }
  });
})();
