const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const API_META = [
  { key: 'pro', label: '正方接口', dot: 'pro', ph: 'gpt-4o-mini' },
  { key: 'con', label: '反方接口', dot: 'con', ph: 'gpt-4o-mini' },
  { key: 'judge', label: '总结评价接口', dot: 'judge', ph: 'gpt-4o' },
];

const STATUS_TEXT = {
  IDLE: '待开始', VALIDATING: '校验选题', OPENING: '开场立论', FREE: '自由辩论',
  CLOSING: '总结陈词', JUDGING: '评委点评', DONE: '已结束',
  WARNING: '选题待确认', PAUSED: '已暂停', ABORTED: '已中止',
};

const STAGE_TEXT = {
  validating: '选题校验', opening: '开场立论', free: '自由辩论',
  closing: '总结陈词', judging: '评委点评', done: '辩论结束', aborted: '已中止',
};

const ACTIVE = ['VALIDATING', 'OPENING', 'FREE', 'CLOSING', 'JUDGING'];

let config = null;
let topicSource = 'manual';
const bubbles = new Map();
let pendingTopic = '';

/* ── 设置表单 ───────────────────────────────────────── */

function buildApiForms() {
  const host = $('#api-forms');
  host.innerHTML = '';
  for (const meta of API_META) {
    const card = document.createElement('section');
    card.className = 'api-card';
    card.innerHTML = `
      <div class="api-title"><i class="dot ${meta.dot}"></i>${meta.label}</div>
      <div class="grid-2">
        <label class="field"><span>昵称</span>
          <input id="api-${meta.key}-nickname" type="text"></label>
        <label class="field"><span>模型名</span>
          <input id="api-${meta.key}-model" type="text" placeholder="${meta.ph}"></label>
      </div>
      <label class="field"><span>API Key</span>
        <input id="api-${meta.key}-key" type="password" autocomplete="off"
               placeholder="sk-..."></label>
      <label class="field"><span>Base URL</span>
        <input id="api-${meta.key}-base" type="text" placeholder="https://api.openai.com/v1"></label>
      <div class="grid-2">
        <label class="field"><span>温度</span>
          <input id="api-${meta.key}-temp" type="number" min="0" max="2" step="0.1"></label>
        <label class="field"><span>思考强度</span>
          <select id="api-${meta.key}-effort">
            <option value="low">low</option>
            <option value="high">high</option>
            <option value="max">max</option>
          </select></label>
      </div>
      <label class="check">
        <input type="checkbox" id="api-${meta.key}-thinking">
        <span>开启思考模式</span>
      </label>`;
    host.appendChild(card);
    card.querySelector(`#api-${meta.key}-thinking`).addEventListener('change', (e) => {
      card.querySelector(`#api-${meta.key}-effort`).disabled = !e.currentTarget.checked;
    });
  }
}

function fillForm() {
  for (const { key } of API_META) {
    const api = config.apis[key] || {};
    $(`#api-${key}-nickname`).value = api.nickname || '';
    $(`#api-${key}-model`).value = api.model || '';
    $(`#api-${key}-key`).value = api.api_key || '';
    $(`#api-${key}-base`).value = api.base_url || '';
    $(`#api-${key}-temp`).value = api.temperature ?? 0.8;
    const thinking = api.thinking_enabled !== false;
    $(`#api-${key}-thinking`).checked = thinking;
    const effort = $(`#api-${key}-effort`);
    effort.value = api.reasoning_effort || 'high';
    effort.disabled = !thinking;
  }
  $('#f-topic').value = config.debate.topic || '';
  $('#f-rounds').value = config.debate.rounds ?? 7;
  $('#f-persona-pro').value = config.debate.personas?.pro || '';
  $('#f-persona-con').value = config.debate.personas?.con || '';
  $('#f-retries').value = config.runtime.max_retries ?? 3;
  $('#f-timeout').value = config.runtime.timeout_seconds ?? 120;
  $('#f-sound').checked = config.ui.sound !== false;
  renderNames();
  applyTheme();
}

function collectForm() {
  const next = structuredClone(config);
  for (const { key } of API_META) {
    next.apis[key].nickname = $(`#api-${key}-nickname`).value.trim();
    next.apis[key].model = $(`#api-${key}-model`).value.trim();
    next.apis[key].api_key = $(`#api-${key}-key`).value.trim();
    next.apis[key].base_url = $(`#api-${key}-base`).value.trim();
    next.apis[key].temperature = Number($(`#api-${key}-temp`).value);
    next.apis[key].thinking_enabled = $(`#api-${key}-thinking`).checked;
    next.apis[key].reasoning_effort = $(`#api-${key}-effort`).value || 'high';
  }
  next.debate.topic = $('#f-topic').value.trim();
  next.debate.rounds = Number($('#f-rounds').value) || 1;
  next.debate.personas = {
    pro: $('#f-persona-pro').value.trim(),
    con: $('#f-persona-con').value.trim(),
  };
  next.runtime.max_retries = Number($('#f-retries').value) || 0;
  next.runtime.timeout_seconds = Number($('#f-timeout').value) || 120;
  next.ui.sound = $('#f-sound').checked;
  return next;
}

async function saveConfig(silent) {
  const res = await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(collectForm()),
  });
  if (!res.ok) { flash('#save-hint', '保存失败'); return false; }
  config = await (await fetch('/api/config')).json();
  fillForm();
  if (!silent) flash('#save-hint', '已保存');
  return true;
}

let flashTimer = null;
function flash(sel, text) {
  const el = $(sel);
  if (!el) return;
  el.textContent = text;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { el.textContent = ''; }, 2400);
}

/* ── 界面状态 ───────────────────────────────────────── */

function renderNames() {
  const pro = config.apis.pro.nickname || '正方';
  const con = config.apis.con.nickname || '反方';
  $('#pro-name').textContent = pro;
  $('#con-name').textContent = con;
  $('#col-pro-name').textContent = pro;
  $('#col-con-name').textContent = con;
}

function applyTheme() {
  document.documentElement.dataset.theme = config?.ui?.theme === 'light' ? 'light' : 'dark';
}

function updateControls(status) {
  const running = ACTIVE.includes(status);
  const paused = status === 'PAUSED';
  const warning = status === 'WARNING';
  $('#btn-start').disabled = running || paused || warning;
  $('#btn-pause').disabled = !running && !paused;
  $('#btn-abort').disabled = !running && !paused;
  $('#btn-pause').textContent = paused ? '继续' : '暂停';
  $('#btn-pause').dataset.action = paused ? 'resume' : 'pause';
}

function updateRail() {
  const rounds = Number($('#f-rounds').value) || 0;
  const total = 2 + rounds * 2 + 2;
  const done = $$('.bubble').length;
  const pct = Math.max(0, Math.min(100, Math.round((done / total) * 100)));
  const fill = $('#rail-fill');
  fill.style.height = `${pct}%`;
  fill.style.width = `${pct}%`;
  $('#rail-meta').textContent = `共 ${rounds} 轮`;
}

function reducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function handleState(s) {
  const pill = $('#status-pill');
  pill.dataset.status = s.status;
  pill.textContent = STATUS_TEXT[s.status] || s.status;
  if (s.stage) $('#rail-stage').textContent = STAGE_TEXT[s.stage] || s.stage;
  if (s.status !== 'WARNING') $('#warning').hidden = true;
  if (s.status !== 'PAUSED') $('#error-banner').hidden = true;
  if (s.topic) $('#topic-line').textContent = s.topic;
  updateControls(s.status);
  updateRail();
}

/* ── Markdown 渲染 ──────────────────────────────────── */

const MD_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => MD_ESCAPES[ch]);
}

function inlineMarkdown(raw) {
  const codes = [];
  let out = raw.replace(/`([^`]+)`/g, (m, code) => {
    codes.push(`<code class="md-inline">${escapeHtml(code)}</code>`);
    return `\u0001${codes.length - 1}\u0001`;
  });
  out = escapeHtml(out);
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  out = out.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
                    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return out.replace(/\u0001(\d+)\u0001/g, (m, i) => codes[Number(i)]);
}

// 渲染模型返回的 Markdown。全程转义 HTML，只生成白名单标签，避免注入。
function renderMarkdown(source) {
  const blocks = [];
  const stash = (code) => {
    blocks.push(`<pre class="md-code"><code>${escapeHtml(code)}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  };
  // 先摘出围栏代码块，避免其中的符号被当成 Markdown 解析
  let text = source.replace(/```[^\n`]*\n?([\s\S]*?)```/g, (m, code) => stash(code.replace(/\n$/, '')));
  // 流式输出时可能只有开围栏还没闭合
  text = text.replace(/```[^\n`]*\n?([\s\S]*)$/, (m, code) => stash(code));

  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => {
    if (para.length) { out.push(`<p>${para.join('<br>')}</p>`); para = []; }
  };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };

  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) { flushPara(); closeList(); continue; }
    if (/^\u0000\d+\u0000$/.test(trimmed)) { flushPara(); closeList(); out.push(trimmed); continue; }

    let m;
    if ((m = trimmed.match(/^(#{1,6})\s+(.*)$/))) {
      flushPara(); closeList();
      const level = Math.min(m[1].length + 2, 6);
      out.push(`<h${level} class="md-h">${inlineMarkdown(m[2])}</h${level}>`);
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushPara(); closeList(); out.push('<hr class="md-hr">'); continue;
    }
    if ((m = trimmed.match(/^>\s?(.*)$/))) {
      flushPara(); closeList();
      out.push(`<blockquote class="md-quote">${inlineMarkdown(m[1])}</blockquote>`);
      continue;
    }
    if ((m = trimmed.match(/^[-*+]\s+(.*)$/))) {
      flushPara();
      if (list !== 'ul') { closeList(); out.push('<ul class="md-list">'); list = 'ul'; }
      out.push(`<li>${inlineMarkdown(m[1])}</li>`);
      continue;
    }
    if ((m = trimmed.match(/^\d+[.)]\s+(.*)$/))) {
      flushPara();
      if (list !== 'ol') { closeList(); out.push('<ol class="md-list">'); list = 'ol'; }
      out.push(`<li>${inlineMarkdown(m[1])}</li>`);
      continue;
    }
    closeList();
    para.push(inlineMarkdown(trimmed));
  }
  flushPara(); closeList();
  return out.join('').replace(/\u0000(\d+)\u0000/g, (m, i) => blocks[Number(i)]);
}

// 流式输出时逐字重排 DOM 太浪费，按 70ms 合并一次
const mdRaw = new WeakMap();
const mdQueue = new Set();
let mdTimer = null;

function scheduleMarkdown(node) {
  mdQueue.add(node);
  if (mdTimer) return;
  mdTimer = setTimeout(() => {
    mdTimer = null;
    for (const el of mdQueue) el.innerHTML = renderMarkdown(mdRaw.get(el) || '');
    mdQueue.clear();
  }, 70);
}

/* ── 思考计时器 ─────────────────────────────────────── */

const thinkTimers = new Map();   // id -> { startedAt, interval, final }

function paintThinkLabel(id, el, seconds) {
  const node = el.querySelector('.think-timer');
  if (!node) return;
  if (seconds === null) {
    const state = thinkTimers.get(id);
    if (!state || state.startedAt === null) return;
    node.textContent = `Thinking ${((performance.now() - state.startedAt) / 1000).toFixed(1)}s`;
    node.classList.remove('done');
    return;
  }
  node.textContent = `Thought ${Number(seconds).toFixed(1)}s`;
  node.classList.add('done');
}

function thinkStart(id, el) {
  let state = thinkTimers.get(id);
  if (!state) { state = { startedAt: null, interval: null, final: null }; thinkTimers.set(id, state); }
  if (state.startedAt !== null || state.final !== null) return;
  state.startedAt = performance.now();
  state.interval = setInterval(() => paintThinkLabel(id, el, null), 100);
  paintThinkLabel(id, el, null);
}

function thinkFinish(id, el, seconds) {
  const state = thinkTimers.get(id);
  if (!state || state.startedAt === null) return;
  if (state.interval) { clearInterval(state.interval); state.interval = null; }
  if (state.final !== null) return;
  const value = (seconds === null || seconds === undefined)
    ? (performance.now() - state.startedAt) / 1000
    : seconds;
  state.final = value;
  paintThinkLabel(id, el, value);
}

function thinkReset(id) {
  const state = thinkTimers.get(id);
  if (state?.interval) clearInterval(state.interval);
  thinkTimers.delete(id);
}

/* ── 发言气泡 ───────────────────────────────────────── */

function containerFor(entry) {
  if (!entry.side) return $('#verdict-body');
  return entry.side === 'pro' ? $('#stream-pro') : $('#stream-con');
}

function clearLive() {
  $$('.bubble.live').forEach((b) => b.classList.remove('live'));
}

function ensureBubble(entry) {
  let el = bubbles.get(entry.id);
  if (el) {
    thinkReset(entry.id);
    const node = el.querySelector('.content');
    mdRaw.delete(node);
    node.innerHTML = '';
    el.querySelector('.thinking').textContent = '';
    const timer = el.querySelector('.think-timer');
    timer.textContent = '';
    timer.classList.remove('done');
    el.querySelector('.thinking-toggle').hidden = true;
  } else {
    el = document.createElement('article');
    el.className = 'bubble';
    el.dataset.side = entry.side || 'judge';
    el.innerHTML = `
      <header class="bubble-head">
        <span class="badge"></span>
        <span class="meta"></span>
      </header>
      <button class="thinking-toggle" type="button" aria-expanded="false" hidden>
        <span>思考过程</span><span class="think-timer"></span>
      </button>
      <div class="thinking" hidden></div>
      <div class="content"></div>`;
    el.querySelector('.badge').textContent = entry.speaker || '评委';
    el.querySelector('.thinking-toggle').addEventListener('click', (ev) => {
      const btn = ev.currentTarget;
      const box = el.querySelector('.thinking');
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      box.hidden = open;
    });
    containerFor(entry).appendChild(el);
    bubbles.set(entry.id, el);
  }
  if (!entry.side) $('#verdict').hidden = false;
  el.classList.add('live');
  scrollIntoView(el);
  updateRail();
  return el;
}

function appendText(id, kind, text) {
  const el = bubbles.get(id);
  if (!el) return;
  if (kind === 'reasoning') {
    const box = el.querySelector('.thinking');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.textContent += text;
    el.querySelector('.thinking-toggle').hidden = false;
    thinkStart(id, el);
    if (atBottom) box.scrollTop = box.scrollHeight;
  } else {
    // 正文一开始输出，就说明思考阶段结束了
    thinkFinish(id, el, null);
    const node = el.querySelector('.content');
    mdRaw.set(node, (mdRaw.get(node) || '') + text);
    scheduleMarkdown(node);
  }
  scrollIntoView(el);
}

function scrollIntoView(el) {
  const stream = el.parentElement;
  if (!stream || !stream.scrollHeight) return;
  const nearBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 140;
  if (nearBottom) stream.scrollTop = stream.scrollHeight;
}

function handleStart(entry) {
  clearLive();
  pendingTopic = $('#f-topic').value.trim() || pendingTopic;
  if (pendingTopic) $('#topic-line').textContent = pendingTopic;
  ensureBubble(entry);
}

function handleEnd(d) {
  const el = bubbles.get(d.id);
  if (!el) return;
  el.classList.remove('live');
  el.querySelector('.meta').textContent = `${d.chars} 字 · ${(d.elapsed_ms / 1000).toFixed(1)}s`;
  const state = thinkTimers.get(d.id);
  if (state && state.startedAt !== null) {
    // 后端给的 thinking_ms 是权威值，用于跨刷新保持一致
    thinkFinish(d.id, el, d.thinking_ms > 0 ? d.thinking_ms / 1000 : null);
  }
}

function handleWarning(d) {
  $('#warning-reason').textContent = d.reason || '未给出理由';
  $('#warning').hidden = false;
}

function handleError(d) {
  $('#error-message').textContent =
    `${STAGE_TEXT[d.stage] || d.stage || '请求'}阶段调用失败：${d.message}（已自动重试 ${d.retries} 次）`;
  $('#error-banner').hidden = false;
}

function handleDone(d) {
  $('#hint').textContent = `结果已保存：${d.txt_path}`;
  if (config?.ui?.sound !== false) chime();
}

function chime() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.value = 660;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.11, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.55);
    osc.start();
    osc.stop(ctx.currentTime + 0.56);
  } catch (err) { /* 浏览器未授权音频时忽略 */ }
}

/* ── 事件流 ─────────────────────────────────────────── */

function connect() {
  const es = new EventSource('/api/events');
  const on = (name, fn) => es.addEventListener(name, (e) => {
    try { fn(JSON.parse(e.data)); } catch (err) { /* 忽略坏帧 */ }
  });
  on('state', handleState);
  on('message_start', handleStart);
  on('reasoning_delta', (d) => appendText(d.id, 'reasoning', d.text));
  on('content_delta', (d) => appendText(d.id, 'content', d.text));
  on('message_end', handleEnd);
  on('warning', handleWarning);
  on('error', handleError);
  on('judge_end', handleEnd);
  on('done', handleDone);
  es.addEventListener('open', () => $('#hint').textContent = '');
  es.addEventListener('error', () => $('#hint').textContent = '连接中断，浏览器将自动重连…');
}

function applyMessage(el, m) {
  const node = el.querySelector('.content');
  mdRaw.set(node, m.content || '');
  node.innerHTML = renderMarkdown(m.content || '');
  el.querySelector('.thinking').textContent = m.reasoning || '';
  el.querySelector('.thinking-toggle').hidden = !m.reasoning;
  if (m.thinking_ms > 0) {
    thinkTimers.set(m.id, { startedAt: 0, interval: null, final: m.thinking_ms / 1000 });
    paintThinkLabel(m.id, el, m.thinking_ms / 1000);
  }
  if (m.chars !== undefined || m.elapsed_ms !== undefined) {
    el.querySelector('.meta').textContent =
      `${m.chars || 0} 字 · ${((m.elapsed_ms || 0) / 1000).toFixed(1)}s`;
  }
  el.classList.remove('live');
}

async function recover() {
  const s = await (await fetch('/api/debate/state')).json();
  if (s.topic) $('#topic-line').textContent = s.topic;
  for (const m of s.messages || []) {
    ensureBubble(m);
    applyMessage(bubbles.get(m.id), m);
  }
  if (s.judge) {
    ensureBubble({ id: 'judge', speaker: '评委', side: null });
    applyMessage(bubbles.get('judge'), { id: 'judge', ...s.judge });
  }
  if (s.current) {
    ensureBubble(s.current);
    applyMessage(bubbles.get(s.current.id), s.current);
    bubbles.get(s.current.id).classList.add('live');
  }
  handleState(s);
}

/* ── 操作 ───────────────────────────────────────────── */

async function control(action) {
  await fetch('/api/debate/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
}

function resetArena() {
  bubbles.clear();
  $('#stream-pro').innerHTML = '';
  $('#stream-con').innerHTML = '';
  $('#verdict-body').innerHTML = '';
  $('#verdict').hidden = true;
  $('#warning').hidden = true;
  $('#error-banner').hidden = true;
  $('#rail-stage').textContent = '准备中';
  updateRail();
}

async function startDebate(force) {
  if (startDebate.busy) return;
  startDebate.busy = true;
  try {
    if (!(await saveConfig(true))) return;
    const topic = $('#f-topic').value.trim();
    if (!topic) {
      openDrawer('drawer-settings');
      flash('#save-hint', '请先填写辩题');
      $('#f-topic').focus();
      return;
    }
    resetArena();
    $('#topic-line').textContent = topic;
    pendingTopic = topic;
    await fetch('/api/debate/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, topic_source: topicSource, force: !!force }),
    });
    closeDrawers();
  } finally {
    startDebate.busy = false;
  }
}

async function generateTopics() {
  const btn = $('#btn-gen-topic');
  const host = $('#candidates');
  btn.disabled = true;
  btn.textContent = '生成中…';
  host.textContent = '';
  try {
    await saveConfig(true);
    const res = await fetch('/api/topic/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ n: 4 }),
    });
    const data = await res.json();
    if (!data.topics || !data.topics.length) {
      host.textContent = '未能生成候选选题，请检查「总结评价接口」配置。';
      return;
    }
    host.innerHTML = '';
    for (const item of data.topics) {
      const btnEl = document.createElement('button');
      btnEl.type = 'button';
      btnEl.className = 'candidate';
      const title = document.createElement('b');
      title.textContent = item.topic || '（无标题）';
      const note = document.createElement('small');
      note.textContent = item.note || '';
      btnEl.append(title, note);
      btnEl.addEventListener('click', () => {
        $('#f-topic').value = item.topic || '';
        topicSource = 'generated';
        host.innerHTML = '';
      });
      host.appendChild(btnEl);
    }
  } catch (err) {
    host.textContent = `生成失败：${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = '生成候选选题';
  }
}

/* ── 抽屉 ───────────────────────────────────────────── */

const DRAWER_MS = 360;

function hideDrawer(el) {
  if (!el || (el.hidden && !el.classList.contains('is-open'))) return;
  el.classList.remove('is-open');
  const finish = () => {
    if (!el.classList.contains('is-open')) el.hidden = true;
  };
  window.setTimeout(finish, reducedMotion() ? 0 : DRAWER_MS);
}

function openDrawer(id) {
  const target = $('#' + id);
  if (!target) return;
  $$('.drawer').forEach((d) => { if (d !== target) hideDrawer(d); });
  const scrim = $('#scrim');
  scrim.hidden = false;
  target.hidden = false;
  // 从当前呈现值继续，避免二次打开跳变
  requestAnimationFrame(() => {
    scrim.classList.add('is-open');
    requestAnimationFrame(() => {
      target.classList.add('is-open');
      const focusable = target.querySelector(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
      );
      if (focusable) focusable.focus({ preventScroll: true });
    });
  });
}

function closeDrawers() {
  $$('.drawer').forEach((d) => hideDrawer(d));
  const scrim = $('#scrim');
  scrim.classList.remove('is-open');
  window.setTimeout(() => {
    if (!scrim.classList.contains('is-open')) scrim.hidden = true;
  }, reducedMotion() ? 0 : 240);
}

async function openHistory() {
  const res = await (await fetch('/api/history')).json();
  const logs = await (await fetch('/api/logs')).json();
  const logLine = $('#log-paths');
  logLine.textContent = '';
  for (const [label, path] of [['操作日志', logs.operations], ['请求日志', logs.api_requests]]) {
    const row = document.createElement('span');
    row.textContent = `${label}：${path || '（尚未开始）'}`;
    logLine.appendChild(row);
  }
  const body = document.querySelector('#drawer-history .drawer-body');
  body.innerHTML = '';
  const list = document.createElement('ul');
  list.className = 'history-list';
  if (!res.files.length) {
    const li = document.createElement('li');
    li.className = 'history-empty';
    li.textContent = '暂无历史记录。完成一场辩论后，结果会出现在这里。';
    list.appendChild(li);
  } else {
    for (const name of res.files) {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = name.replace(/^Result_/, '').replace(/\.txt$/, '');
      btn.addEventListener('click', () => showHistory(name));
      li.appendChild(btn);
      list.appendChild(li);
    }
  }
  body.appendChild(list);
  openDrawer('drawer-history');
}

async function showHistory(name) {
  const res = await (await fetch(`/api/history/${encodeURIComponent(name)}`)).json();
  if (!res.ok) return;
  const body = document.querySelector('#drawer-history .drawer-body');
  body.innerHTML = '';
  const back = document.createElement('button');
  back.type = 'button';
  back.className = 'ghost';
  back.textContent = '← 返回列表';
  back.addEventListener('click', openHistory);
  const pre = document.createElement('pre');
  pre.className = 'history-pre';
  pre.textContent = res.content;
  body.append(back, pre);
}

async function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  if (config) config.ui.theme = next;
  await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(collectForm()),
  });
}

/* ── 启动 ───────────────────────────────────────────── */

function wire() {
  $('#btn-start').addEventListener('click', () => startDebate(false));
  $('#btn-force').addEventListener('click', () => { $('#warning').hidden = true; control('force'); });
  $('#btn-edit-topic').addEventListener('click', () => {
    $('#warning').hidden = true;
    control('abort');
    openDrawer('drawer-settings');
    $('#f-topic').focus();
  });
  $('#btn-pause').addEventListener('click', (e) => control(e.currentTarget.dataset.action || 'pause'));
  $('#btn-abort').addEventListener('click', () => control('abort'));
  $('#btn-retry').addEventListener('click', () => { $('#error-banner').hidden = true; control('retry'); });
  $('#btn-skip').addEventListener('click', () => { $('#error-banner').hidden = true; control('skip'); });
  $('#btn-abort-err').addEventListener('click', () => { $('#error-banner').hidden = true; control('abort'); });
  $('#btn-settings').addEventListener('click', () => openDrawer('drawer-settings'));
  $('#btn-history').addEventListener('click', openHistory);
  $('#btn-theme').addEventListener('click', toggleTheme);
  $('#btn-save').addEventListener('click', () => saveConfig(false));
  $('#btn-gen-topic').addEventListener('click', generateTopics);
  $('#f-topic').addEventListener('input', () => { topicSource = 'manual'; });
  $$('[data-close]').forEach((b) => b.addEventListener('click', closeDrawers));
  $('#scrim').addEventListener('click', closeDrawers);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawers(); });
}

async function init() {
  buildApiForms();
  wire();
  config = await (await fetch('/api/config')).json();
  fillForm();
  updateRail();
  await recover();
  connect();
}

init();
