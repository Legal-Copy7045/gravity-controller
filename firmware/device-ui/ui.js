// Smoker device page: replaces ESPHome's stock web_server page on the controller itself (http://<ip>/).
// Served by web_server as /0.js (js_include, gzipped in flash) with ui.css as /0.css; js_url is empty, so the
// page never needs the internet. It reads live states from web_server's /events stream and acts through its
// REST API (POST /<domain>/<entity name>/<action>), the same calls ESPHome's own page makes.
// ?classic loads ESPHome's stock page instead (that one comes from oi.esphome.io, so it needs internet).
const Q = new URLSearchParams(location.search);
const CLASSIC = 'https://oi.esphome.io/v3/www.js';
const doc = document, $ = id => doc.getElementById(id);
const meta = (n, c) => { const m = doc.createElement('meta'); m.name = n; m.content = c; doc.head.appendChild(m); };
meta('viewport', 'width=device-width,initial-scale=1,viewport-fit=cover');

if (Q.has('classic')) {
  // Stock page: drop our stylesheet and load ESPHome's app into the <esp-app> the index already has.
  const css = doc.querySelector('link[href="/0.css"]'); if (css) css.remove();
  const s = doc.createElement('script'); s.src = CLASSIC;
  s.onerror = () => { doc.body.insertAdjacentHTML('afterbegin', '<p style="font:15px system-ui;padding:16px">The full device view is ESPHome\'s standard page, loaded from oi.esphome.io: this phone needs internet access for it. <a href="./">Back to the smoker page</a></p>'); };
  doc.body.appendChild(s);
} else {
  start();
}

function start() {
  doc.documentElement.classList.add('gx');
  doc.documentElement.lang = 'en';
  doc.title = 'Smoker';
  meta('theme-color', '#c2410c');
  // Optional web fonts: offline, the system fonts in ui.css take over.
  const f = doc.createElement('link'); f.rel = 'stylesheet';
  f.href = 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600..800&family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap';
  doc.head.appendChild(f);
  const app = doc.querySelector('esp-app'); if (app) app.remove();
  doc.body.insertAdjacentHTML('afterbegin', `<div class="wrap">
  <header class="hero" id="hero"></header>
  <nav class="secbar" aria-label="Sections"><a href="#s-pit">Pit</a><a href="#s-food">Food</a><a href="#s-fuel">Charcoal</a><a href="#s-prog">Program</a><a href="#s-setup">Setup</a></nav>
  <section class="sect" id="s-pit"><h2 class="sec">Pit</h2><div class="card" id="pit"></div></section>
  <section class="sect" id="s-food"><h2 class="sec">Food <small id="foodsub"></small></h2><div class="grid" id="food"></div></section>
  <section class="sect" id="s-fuel"><h2 class="sec">Charcoal</h2><div class="card" id="fuel"></div></section>
  <section class="sect" id="s-prog"><h2 class="sec">Program</h2><div class="card" id="prog"></div></section>
  <section class="sect" id="s-setup"><h2 class="sec">Setup</h2><div class="grid"><div class="card" id="conn"></div><div class="card" id="sources"></div><div class="card" id="dev"></div></div></section>
  <footer id="foot"></footer></div><div id="toast" role="status" aria-live="polite"></div>`);
  wire();
  connect();
  setInterval(() => { render(); }, 5000);  // the connection dot and "ago" texts
}

// ---------------------------------------------------------------- state from /events
const ents = {};       // "domain/Entity name" -> merged state + detail (domain, name, uom, option, min_value...)
const alias = {};      // legacy ids ("sensor-pit_temperature") -> key
let cfg = {}, last = 0, es = null, retry = null;
const keyOf = d => {
  const id = d.name_id || d.id; if (!id) return null;
  if (id.includes('/')) return id;
  if (alias[id]) return alias[id];
  if (d.domain && d.name) return (alias[id] = d.domain + '/' + d.name);
  return null;
};
function connect() {
  clearTimeout(retry);
  if (es) es.close();
  es = new EventSource('/events');
  es.addEventListener('ping', e => { last = Date.now(); try { const d = JSON.parse(e.data); if (d.title) cfg = d; } catch (_) {} soon(); });
  es.addEventListener('state', e => {
    last = Date.now();
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    const k = keyOf(d); if (!k) return;
    const o = ents[k] || (ents[k] = {});
    Object.assign(o, d);
    if (!o.domain) o.domain = k.split('/')[0];
    if (!o.name) o.name = k.slice(k.indexOf('/') + 1);
    soon();
  });
  es.addEventListener('log', () => { last = Date.now(); });
  // web_server asks for a 30 s reconnect delay; come back sooner (every reconnect resends every entity).
  es.onerror = () => { last = 0; soon(); es.close(); retry = setTimeout(connect, 3000); };
}
let pending = 0;
function soon() { if (!pending) pending = setTimeout(() => { pending = 0; render(); }, 120); }

const E = (dom, name) => ents[dom + '/' + name];
const num = e => { if (!e) return null; const v = e.value, n = typeof v === 'number' ? v : parseFloat(v); return Number.isFinite(n) ? n : null; };
const str = e => (e && typeof e.value === 'string') ? e.value : (e && typeof e.state === 'string' && e.state !== 'NA' ? e.state : '');
const on = e => !!e && (e.value === true || e.state === 'ON');
const S = n => num(E('sensor', n)), T = n => str(E('text_sensor', n));
const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const fmt = (v, d = 0) => v == null ? '--' : Number(v).toFixed(d);
const TU = () => { const e = E('sensor', 'Pit temperature'); return (e && e.uom) || '°F'; };
const isF = () => TU().indexOf('F') >= 0;
const mins = m => m == null ? '--' : m < 60 ? Math.round(m) + ' min' : Math.floor(m / 60) + 'h ' + String(Math.round(m % 60)).padStart(2, '0') + 'm';
const clock = m => new Date(Date.now() + m * 60000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const EXP = why => `<span class="chip exp" title="${esc(why)}">Experimental</span>`;
const isExp = s => /^Experimental/.test(s || '');
const pullExp = s => /pull-at experimental/.test(s || '');
const opts = (e, cur) => ((e && e.option) || []).map(o => `<option${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('');
const sel = (dom, name, attrs = '') => { const e = E(dom, name); return e ? `<select data-c="select" data-n="${esc(name)}" aria-label="${esc(name)}"${attrs}>${opts(e, str(e))}${str(e) && !(e.option || []).includes(str(e)) ? `<option selected>${esc(str(e))}</option>` : ''}</select>` : ''; };
const tog = (name, label, note) => { const e = E('switch', name); return e ? `<div class="row"><span>${label}${note ? `<br><span class="muted small">${note}</span>` : ''}</span><button class="tg${on(e) ? ' on' : ''}" data-a="toggle" data-n="${esc(name)}" role="switch" aria-checked="${on(e)}" aria-label="${esc(name)}"></button></div>` : ''; };
const row = (l, r) => `<div class="row"><span>${l}</span><span class="r">${r}</span></div>`;

// ---------------------------------------------------------------- REST actions
function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600); }
async function post(dom, name, action, params) {
  const q = params ? '?' + new URLSearchParams(params) : '';
  try {
    const r = await fetch(`/${dom}/${encodeURIComponent(name)}/${action}${q}`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
    if (!r.ok) throw new Error(r.status === 404 ? 'not found' : 'HTTP ' + r.status);
    return true;
  } catch (e) { toast('Couldn\'t change ' + name + ': ' + e.message); return false; }
}
// The value to step from: a target just sent counts until the device reports one (rapid taps add up).
const sent = {};
function cur(name) { const s = sent[name]; if (s && Date.now() - s.t < 4000) return s.v; return num(E('number', name)); }
function setNum(name, v) {
  const e = E('number', name); if (!e || v == null || !Number.isFinite(v)) return;
  const lo = parseFloat(e.min_value), hi = parseFloat(e.max_value);
  if (Number.isFinite(lo)) v = Math.max(lo, v); if (Number.isFinite(hi)) v = Math.min(hi, v);
  sent[name] = { v, t: Date.now() };
  post('number', name, 'set', { value: String(v) });
  render();
}
function stepOf(name, dflt) { const e = E('number', name), s = e && parseFloat(e.step); return Math.max(Number.isFinite(s) && s > 0 ? s : 0, dflt); }
const armed = {};
const ACT = {
  pit(el) { const c = cur('Pit target'); if (c == null) return toast('Pit target not known yet'); setNum('Pit target', c + Number(el.dataset.d) * stepOf('Pit target', isF() ? 5 : 2)); },
  pitset() { const v = parseFloat($('pitin').value); if (!Number.isFinite(v)) return toast('Type a temperature'); delete $('pitin').dataset.dirty; setNum('Pit target', v); },
  tgt(el) { const n = el.dataset.n, c = cur(n); if (c == null) return toast(n + ' not known yet'); setNum(n, c + Number(el.dataset.d) * stepOf(n, isF() ? 1 : 0.5)); },
  toggle(el) { post('switch', el.dataset.n, 'toggle'); },
  press(el) {
    const n = el.dataset.n;
    if (el.dataset.confirm && !armed[n]) { armed[n] = setTimeout(() => { delete armed[n]; render(); }, 3000); return render(); }
    clearTimeout(armed[n]); delete armed[n];
    post('button', n, 'press').then(ok => ok && toast(n)); render();
  },
  load() { const t = $('progtext').value.trim(); if (!t) return toast('Write a program first'); post('text', 'Program', 'set', { value: t }).then(ok => { if (ok) { delete $('progtext').dataset.dirty; toast('Program sent'); } }); },
  ip() { const v = $('ipin').value.trim(); post('text', 'Grill IP address', 'set', { value: v }).then(ok => { if (ok) { delete $('ipin').dataset.dirty; toast(v ? 'Grill address set' : 'Finding the grill automatically'); } }); },
};
function wire() {
  doc.addEventListener('click', e => { const b = e.target.closest('[data-a]'); if (b && !b.disabled && ACT[b.dataset.a]) ACT[b.dataset.a](b); });
  doc.addEventListener('change', e => {
    const t = e.target, n = t.dataset && t.dataset.n; if (!n) return;
    if (t.dataset.c === 'select') post('select', n, 'set', { option: t.value }).then(ok => ok && toast(n + ': ' + t.value));
    else if (t.dataset.c === 'number') { delete t.dataset.dirty; setNum(n, parseFloat(t.value)); }
  });
  doc.addEventListener('input', e => { if (e.target.id) e.target.dataset.dirty = '1'; });
  doc.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'pitin') ACT.pitset(); if (e.key === 'Enter' && e.target.id === 'ipin') ACT.ip(); });
  doc.addEventListener('focusout', () => setTimeout(render, 0));  // redraw what was held back while a field had focus
  // section bar: mark the section in view
  const links = [...doc.querySelectorAll('.secbar a')];
  const io = new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) links.forEach(a => a.setAttribute('aria-current', a.hash === '#' + x.target.id)); }), { rootMargin: '-45% 0px -50% 0px' });
  doc.querySelectorAll('.sect').forEach(s => io.observe(s));
}

// ---------------------------------------------------------------- drawing
// Redraw a section only when its HTML changed, never while someone is in one of its fields or menus; typed text
// (marked dirty) and open folds survive a redraw.
function put(id, html) {
  const el = $(id); if (!el || el._h === html) return;
  const a = doc.activeElement;
  if (a && el.contains(a) && /INPUT|TEXTAREA|SELECT/.test(a.tagName)) return;
  const keep = {}; el.querySelectorAll('input[id],textarea[id]').forEach(f => { if (f.dataset.dirty) keep[f.id] = f.value; });
  const open = [...el.querySelectorAll('details[data-k]')].filter(d => d.open).map(d => d.dataset.k);
  el._h = html; el.innerHTML = html;
  for (const k in keep) { const f = $(k); if (f) { f.value = keep[k]; f.dataset.dirty = '1'; } }
  open.forEach(k => { const d = el.querySelector(`details[data-k="${k}"]`); if (d) d.open = true; });
}

function link() {
  const conn = on(E('binary_sensor', 'Grill connected')), via = T('Grill link');
  const bleE = E('switch', 'Control over Bluetooth (experimental)'), ble = on(bleE), br = E('switch', 'Bridge enabled');
  if (br && !on(br)) return { cls: 'warn', txt: 'Read-only', why: 'The bridge is turned off (Setup), so the Char-Griller app can use the grill.' };
  if (!conn) return { cls: 'warn', txt: 'Read-only', why: 'Not connected to the grill.' };
  if (via === 'wifi') return { cls: 'ok', txt: 'Controlling over Wi-Fi' };
  if (via === 'bluetooth') return ble || !bleE ? { cls: 'ok', txt: 'Controlling over Bluetooth', exp: true }
    : { cls: 'warn', txt: 'Read-only', why: 'Connected over Bluetooth with control turned off: turn on "Control over Bluetooth" in Setup.' };
  return { cls: 'ok', txt: 'Connected to the grill' };
}

function render() {
  const u = TU(), live = Date.now() - last < 25000;
  const pit = S('Pit temperature'), tgt = cur('Pit target') ?? S('Pit target (reported)') ?? S('Pit target reported');
  const L = link(), active = on(E('binary_sensor', 'Cook active')), el = S('Cook elapsed');
  const pst = T('Program state');
  put('hero', `<div class="eyebrow"><span>${esc(cfg.title || 'Smoker')} · Gravity 980</span><span><i class="dot ${live ? 'on' : 'off'}"></i>${live ? 'Live' : 'Reconnecting…'}</span></div>
    <div class="big"><span>${fmt(pit)}<small>${esc(u)}</small></span>${tgt != null ? `<span class="to">→ ${fmt(tgt)}${esc(u)}</span>` : ''}</div>
    <div class="chips"><span class="chip ${L.cls}">${esc(L.txt)}</span>${L.exp ? EXP('Setting targets over Bluetooth is new on the 980: check the grill follows the first change.') : ''}
      ${active ? `<span class="chip hot">Cooking${el != null ? ' · ' + mins(el) : ''}</span>` : '<span class="chip">No cook running</span>'}
      ${/Running|Paused/.test(pst) ? `<span class="chip ${pst === 'Paused' ? 'warn' : 'hot'}">Program ${esc(pst.toLowerCase())}</span>` : ''}
      ${on(E('binary_sensor', 'Lid')) ? '<span class="chip warn">Lid open</span>' : ''}
      ${on(E('binary_sensor', 'Grill alarm')) ? '<span class="chip bad">Grill alarm</span>' : ''}</div>
    ${L.why ? `<p class="why">${esc(L.why)}</p>` : ''}`);
  renderPit(u, pit, tgt); renderFood(u); renderFuel(); renderProg(); renderSetup(u);
}

function renderPit(u, pit, tgt) {
  const n = E('number', 'Pit target');
  const fan = E('binary_sensor', 'Fan');
  put('pit', `${n ? `<div class="step big-step"><button class="btn" data-a="pit" data-d="-1" aria-label="Lower pit target">−</button>
      <span class="val" id="pitval">${fmt(tgt)}${esc(u)}</span><button class="btn" data-a="pit" data-d="1" aria-label="Raise pit target">+</button></div>
    <div class="row"><span>Set the pit to</span><span class="entry"><input id="pitin" type="number" inputmode="numeric" min="${esc(n.min_value || '')}" max="${esc(n.max_value || '')}" step="${esc(n.step || 1)}" placeholder="${fmt(tgt)}" aria-label="Pit target"><span class="muted">${esc(u)}</span><button class="btn pri" data-a="pitset">Set</button></span></div>` : '<p class="note">This controller has no pit target to set.</p>'}
    <div class="kpis" style="margin-top:10px">
      <div class="kpi"><span class="l">Pit now</span><span class="v">${fmt(pit)}<small>${esc(u)}</small></span></div>
      <div class="kpi"><span class="l">Grill reports</span><span class="v">${fmt(S('Pit target (reported)') ?? S('Pit target reported'))}<small>${esc(u)}</small></span></div>
      ${fan ? `<div class="kpi"><span class="l">Fan</span><span class="v">${on(fan) ? 'On' : 'Off'}${on(E('binary_sensor', 'Fan turbo')) ? '<small>turbo</small>' : ''}</span></div>` : ''}
      <div class="kpi"><span class="l">Lid</span><span class="v">${on(E('binary_sensor', 'Lid')) ? 'Open' : 'Closed'}</span></div></div>
    <p class="note">The grill only takes a new target while it is cooking (started from its own panel).</p>`);
}

function renderFood(u) {
  const cards = [];
  for (let i = 1; i <= 6; i++) {
    const L = 'Food ' + i, t = S(L + ' temperature'); if (t == null) continue;
    const tg = cur(L + ' target'), info = T(L + ' estimate basis'), phase = T(L + ' phase');
    const rem = S(L + ' time remaining'), fin = T(L + ' finish time'), pull = S(L + ' pull at');
    const stall = on(E('binary_sensor', L + ' stall')), warn = on(E('binary_sensor', L + ' probe warning'));
    const prot = str(E('select', L + ' protein')), pulled = on(E('switch', L + ' pulled')), rest = S(L + ' rest ready in');
    const w = E('number', L + ' weight'), rate = E('sensor', L + ' rate');
    const chip = stall ? '<span class="chip warn">Stall</span>' : phase ? `<span class="chip${/Done/.test(phase) ? ' ok' : ''}">${esc(phase)}</span>` : '';
    cards.push(`<article class="card food" data-slot="${i}"><span class="edge"></span>
      <h3><span>${esc(L)}${prot && !/^Auto/i.test(prot) ? ` <small>· ${esc(prot)}</small>` : ''}</span>${chip}</h3>
      <div class="ptemp">${fmt(t)}<small>${esc(u)}${tg != null ? ' / ' + fmt(tg) + esc(u) : ''}</small></div>
      ${warn ? '<p class="err">The probe jumped towards pit temperature: is it still in the meat?</p>' : ''}
      <div class="eta" style="margin-top:6px"><span class="t">${rem != null ? clock(rem) : '--'}</span><span class="muted small">${rem != null ? 'in ' + mins(rem) : esc(phase || 'no estimate yet')}</span>${rem != null && isExp(info) ? EXP('Finish times firm up after a few similar cooks. ' + info) : ''}</div>
      ${fin && fin !== '--' ? row('Finish', esc(fin)) : ''}
      ${E('number', L + ' target') ? `<div class="row"><span>Target</span><span class="step"><button class="btn" data-a="tgt" data-n="${L} target" data-d="-1" aria-label="Lower ${L} target">−</button><span class="r">${tg != null ? fmt(tg) + esc(u) : '--'}</span><button class="btn" data-a="tgt" data-n="${L} target" data-d="1" aria-label="Raise ${L} target">+</button></span></div>` : ''}
      ${pull != null ? row('Pull at', `${fmt(pull)}${esc(u)} <span class="muted">(coasts to target)</span>${pullExp(info) ? ' ' + EXP('A default until a couple of rests have been measured for this kind of meat: check with your thermometer.') : ''}`) : ''}
      ${pulled ? row('Ready to slice', rest != null ? (rest <= 0 ? 'now' : 'in ' + mins(rest)) : 'measuring…') : ''}
      ${E('select', L + ' probe') ? `<div class="row"><span>Probe</span>${sel('select', L + ' probe')}</div>` : ''}
      <details class="more" data-k="more${i}"><summary>Cook details</summary>
        ${E('select', L + ' protein') ? `<div class="row"><span>Protein</span>${sel('select', L + ' protein')}</div>` : ''}
        ${w ? `<div class="row"><span>Weight</span><span class="entry"><input id="w${i}" type="number" step="0.1" min="0" data-c="number" data-n="${L} weight" value="${num(w) ?? ''}" aria-label="${L} weight"><span class="muted">${esc(w.uom || (isF() ? 'lb' : 'kg'))}</span></span></div>` : ''}
        ${tog(L + ' wrapped', 'Wrapped')}${tog(L + ' pulled', 'Off the grill, resting')}
        ${rate ? row('Rising', num(rate) != null ? fmt(num(rate), 1) + ' ' + esc(rate.uom || '') : '--') : ''}
        ${info ? `<p class="note">${esc(info)}</p>` : ''}</details></article>`);
  }
  $('foodsub').textContent = cards.length ? cards.length + ' reading' : '';
  put('food', cards.join('') || '<div class="empty">No food probe is reading. Plug one in, or pick a thermometer for a slot under Setup.</div>');
}

function renderFuel() {
  const lvl = S('Charcoal level'), hrs = S('Charcoal hours left'), empty = T('Charcoal empty at'), basis = T('Charcoal estimate basis');
  const left = E('sensor', 'Charcoal left'), rate = E('sensor', 'Charcoal burn rate');
  put('fuel', `<h3><span>Hopper</span>${sel('select', 'Charcoal type')}</h3>
    ${lvl != null ? `<div class="eta"><span class="t">${fmt(lvl)}%</span><span class="muted small">${num(left) != null ? fmt(num(left), 1) + ' ' + esc(left.uom || '') + ' · ' : ''}${hrs != null ? '~' + fmt(hrs, 1) + ' h left' : ''}</span>${isExp(basis) ? EXP(basis) : ''}</div>
      <div class="gauge"><i class="${lvl < 25 ? 'low' : ''}" style="width:${Math.max(0, Math.min(100, lvl))}%"></i></div>
      ${row('Runs out', esc(empty || '--'))}${rate ? row('Burning', num(rate) != null ? fmt(num(rate), 2) + ' ' + esc(rate.uom || '') : '--') : ''}
      ${basis ? `<p class="note">${esc(basis)}</p>` : ''}` : '<p class="note" style="margin-top:0">No charcoal level yet.</p>'}
    <p class="note">Log charcoal (lit, checked, topped up) from Home Assistant: the fuel log is an action this page can't call.</p>`);
}

function renderProg() {
  const st = T('Program state') || 'Idle', status = T('Program status'), err = T('Program error'), txt = E('text', 'Program');
  const run = st === 'Running', paused = st === 'Paused', known = !!E('text_sensor', 'Program state');
  const pt = $('progtext');
  if (pt && pt.dataset.dirty && txt && pt.value.trim() === str(txt).trim()) delete pt.dataset.dirty;  // the device took it
  const b = (name, label, ok, pri, confirm) => E('button', name) ? `<button class="btn${armed[name] ? ' arm' : pri ? ' pri' : ''}" data-a="press" data-n="${esc(name)}"${confirm ? ' data-confirm="1"' : ''}${known && !ok ? ' disabled' : ''}>${armed[name] ? 'Tap again to ' + label.toLowerCase() : label}</button>` : '';
  put('prog', `<h3><span>Cook program</span><span class="chip ${run ? 'hot' : paused ? 'warn' : ''}">${esc(st)}</span></h3>
    ${status ? `<p style="margin:0 0 6px">${esc(status)}</p>` : ''}${err ? `<p class="err">${esc(err)}</p>` : ''}
    ${E('select', 'Program preset') ? `<div class="row"><span>Preset</span>${sel('select', 'Program preset')}</div>` : ''}
    ${txt ? `<textarea id="progtext" maxlength="${esc(txt.max_length || 255)}" aria-label="Program" spellcheck="false">${esc(str(txt))}</textarea>
      <div class="btns" style="margin-top:6px"><button class="btn" data-a="load">Load program</button></div>` : ''}
    <div class="btns">${b('Start program', 'Start', !run && !paused, true)}${b('Pause program', 'Pause', run)}${b('Resume program', 'Resume', paused, true)}${b('Skip program step', 'Skip step', run || paused, false, true)}${b('Stop program', 'Stop', run || paused, false, true)}</div>`);
}

function renderSetup(u) {
  const wifi = T('Grill Wi-Fi'), ip = E('text', 'Grill IP address');
  put('conn', `<h3><span>Grill link</span><span class="chip ${on(E('binary_sensor', 'Grill connected')) ? 'ok' : 'bad'}">${on(E('binary_sensor', 'Grill connected')) ? esc({ wifi: 'Wi-Fi', bluetooth: 'Bluetooth' }[T('Grill link')] || 'connected') : 'not connected'}</span></h3>
    ${tog('Control over Bluetooth (experimental)', 'Control over Bluetooth ' + EXP('Not yet confirmed on the 980: check the grill follows your first change.'), 'Sends pit and food targets over Bluetooth when the grill isn\'t on Wi-Fi.')}
    ${tog('Bridge enabled', 'Bridge enabled', 'Turn off while you use the Char-Griller app: the grill takes one connection.')}
    ${tog('Alerts enabled', 'Alerts')}
    ${ip ? `<div class="row"><span>Grill IP address</span><span class="entry"><input id="ipin" type="text" inputmode="decimal" autocomplete="off" value="${esc(str(ip))}" placeholder="automatic" style="width:140px" aria-label="Grill IP address"><button class="btn" data-a="ip">Save</button></span></div>` : ''}
    ${E('text_sensor', 'Grill Wi-Fi') ? row('Grill\'s Wi-Fi', esc(wifi && wifi !== 'unknown' ? wifi : 'not reported yet')) : ''}`);
  const h5 = E('binary_sensor', 'H5198 connected'), rssi = S('H5198 signal');
  let rows = '';
  for (let i = 1; i <= 6; i++) {
    const L = 'Food ' + i, e = E('select', L + ' probe'); if (!e) continue;
    const t = S(L + ' temperature');
    rows += `<div class="row"><span>${esc(L)} <span class="muted small">${t != null ? fmt(t) + esc(u) : 'no reading'}</span></span><span>${/^Wired/.test(str(e)) ? EXP('Wired probes need the ADS1115 add-on and calibrating against a thermometer you trust.') + ' ' : ''}${sel('select', L + ' probe')}</span></div>`;
  }
  put('sources', `<h3>Probe sources</h3>${rows || '<p class="note" style="margin-top:0">This controller has fixed probes.</p>'}
    ${h5 ? row('H5198 thermometer', on(h5) ? 'receiving' + (rssi != null ? ' · ' + fmt(rssi) + ' dBm' : '') : 'not heard') + `<p class="note">${EXP('Direct H5198 readings follow Home Assistant\'s Govee decoder but haven\'t been checked against its display on a real cook yet.')} "Home Assistant" sources need Home Assistant running; the rest work without it.</p>` : ''}`);
  const ver = T('Firmware version'), sig = S('Wi-Fi signal'), up = S('Uptime');
  put('dev', `<h3>This controller</h3>${ver ? row('Firmware', esc(ver)) : ''}${sig != null ? row('Wi-Fi signal', fmt(sig) + ' dBm') : ''}${up != null ? row('Running for', mins(up / 60)) : ''}
    ${row('Cooks learned', fmt(S('Cooks learned')))}
    <p class="note"><a href="?classic">Full device view</a>: ESPHome's standard page with every entity and the logs (loads from the internet).</p>`);
  put('foot', `<span>${esc(cfg.title || 'Smoker')} · served by the controller, works without Home Assistant</span><span>${Object.keys(ents).length} entities</span>`);
}
