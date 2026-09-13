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
    el.querySelector('.content').textContent = '';
    el.querySelector('.thinking').textContent = '';
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
      <button class="thinking-toggle" type="button" aria-expanded="false" hidden>思考过程</button>
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
    if (atBottom) box.scrollTop = box.scrollHeight;
  } else {
    el.querySelector('.content').textContent += text;
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

async function recover() {
  const s = await (await fetch('/api/debate/state')).json();
  if (s.topic) $('#topic-line').textContent = s.topic;
  for (const m of s.messages || []) {
    ensureBubble(m);
    const el = bubbles.get(m.id);
    el.querySelector('.content').textContent = m.content;
    el.querySelector('.thinking').textContent = m.reasoning || '';
    el.querySelector('.thinking-toggle').hidden = !m.reasoning;
    el.querySelector('.meta').textContent = `${m.chars} 字 · ${(m.elapsed_ms / 1000).toFixed(1)}s`;
    el.classList.remove('live');
  }
  if (s.judge) {
    ensureBubble({ id: 'judge', speaker: '评委', side: null });
    const el = bubbles.get('judge');
    el.querySelector('.content').textContent = s.judge.content;
    el.querySelector('.thinking').textContent = s.judge.reasoning || '';
    el.querySelector('.thinking-toggle').hidden = !s.judge.reasoning;
    el.classList.remove('live');
  }
  if (s.current) {
    ensureBubble(s.current);
    const el = bubbles.get(s.current.id);
    el.querySelector('.content').textContent = s.current.content || '';
    el.querySelector('.thinking').textContent = s.current.reasoning || '';
    el.querySelector('.thinking-toggle').hidden = !s.current.reasoning;
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

function openDrawer(id) {
  $$('.drawer').forEach((d) => { d.hidden = true; });
  $('#' + id).hidden = false;
  $('#scrim').hidden = false;
}

function closeDrawers() {
  $$('.drawer').forEach((d) => { d.hidden = true; });
  $('#scrim').hidden = true;
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
