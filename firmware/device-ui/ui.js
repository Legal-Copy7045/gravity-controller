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

// Brand (brand/ in the repo): favicon, the mark, and the line icons shared with the Home Assistant dashboard.
const FAVICON = 'data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%2064%2064%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22t%22%20x1%3D%220%22%20y1%3D%220%22%20x2%3D%221%22%20y2%3D%221%22%3E%3Cstop%20offset%3D%220%22%20stop-color%3D%22%23f97316%22/%3E%3Cstop%20offset%3D%221%22%20stop-color%3D%22%23b4330a%22/%3E%3C/linearGradient%3E%3ClinearGradient%20id%3D%22f%22%20x1%3D%220%22%20y1%3D%221%22%20x2%3D%220%22%20y2%3D%220%22%3E%3Cstop%20offset%3D%220%22%20stop-color%3D%22%23fde68a%22/%3E%3Cstop%20offset%3D%221%22%20stop-color%3D%22%23fff7ed%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%2264%22%20height%3D%2264%22%20rx%3D%2214%22%20fill%3D%22url%28%23t%29%22/%3E%3Cpath%20fill%3D%22url%28%23f%29%22%20d%3D%22M32%208C37%2017%2047%2024%2047%2037C47%2047.5%2040.5%2055%2032%2055C23.5%2055%2017%2047.5%2017%2037C17%2024%2027%2017%2032%208Z%22/%3E%3Cpath%20fill%3D%22%23f97316%22%20opacity%3D%22.55%22%20d%3D%22M32%2033C34.5%2037%2038%2039.5%2038%2044C38%2048%2035.5%2051%2032%2051C28.5%2051%2026%2048%2026%2044C26%2039.5%2029.5%2037%2032%2033Z%22/%3E%3C/svg%3E';
const MARK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" class="mark" aria-hidden="true"><defs><linearGradient id="mk-tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f97316"/><stop offset="1" stop-color="#b4330a"/></linearGradient><linearGradient id="mk-flame" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#fde68a"/><stop offset="1" stop-color="#fff7ed"/></linearGradient></defs><rect width="256" height="256" rx="58" fill="url(#mk-tile)"/><g fill="#1c1917"><rect x="167" y="54" width="40" height="138" rx="7"/><rect x="161" y="44" width="52" height="16" rx="6"/><rect x="43" y="100" width="134" height="66" rx="33"/><rect x="66" y="160" width="11" height="52" rx="4"/><rect x="143" y="160" width="11" height="52" rx="4"/><rect x="56" y="190" width="108" height="9" rx="4.5"/></g><path transform="translate(110 133) scale(.74) translate(-108.5 -126.5)" fill="url(#mk-flame)" d="M106 158c-15 0-24-10-24-22 0-11 8-17 12-27 1 7 5 11 9 13 0-11 7-21 15-27-2 10 3 17 9 24 5 6 8 11 8 17 0 13-11 22-29 22z"/></svg>';
const ICONS = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true"><symbol id="i-now" viewBox="0 0 24 24"><path d="M3 12h4l2-6 4 12 2-6h6"/></symbol><symbol id="i-flame" viewBox="0 0 24 24"><g transform="translate(-0.5 -0.2)"><path d="M12 21c-3.9 0-6.5-2.6-6.5-6 0-3.3 2.4-4.8 3.6-7.6.4 2.1 1.3 3.1 2.4 3.6.1-3.2 1.7-5.8 4-7.6-.5 2.8.8 4.7 2.3 6.6 1.2 1.6 1.7 3 1.7 4.6C19.5 18.6 16.4 21 12 21z"/></g></symbol><symbol id="i-food" viewBox="0 0 24 24"><g transform="translate(0 -0.5)"><path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/></g></symbol><symbol id="i-grill" viewBox="0 0 24 24"><g transform="translate(-0.5 0)"><path d="M3 12a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5H3z"/><path d="M3 12h16M6 12v8M16 12v8M5 17h12"/><path d="M19 4h3v16h-3z"/></g></symbol><symbol id="i-hopper" viewBox="0 0 24 24"><g transform="translate(0 -0.5)"><path d="M7 4h10v17H7zM6 4h12M10 8h4M10 12h4M10 16h4"/></g></symbol><symbol id="i-chart" viewBox="0 0 24 24"><path d="M4 4v16h16"/><path d="M7 15l4-5 3 3 5-6"/></symbol><symbol id="i-plan" viewBox="0 0 24 24"><g transform="translate(0 0.5)"><path d="M4 6h16v14H4zM4 10h16M8 3v4M16 3v4"/></g></symbol><symbol id="i-book" viewBox="0 0 24 24"><path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z"/><path d="M5 18a2 2 0 0 1 2-2h12M9 8h6"/></symbol><symbol id="i-setup" viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></symbol><symbol id="i-steps" viewBox="0 0 24 24"><g transform="translate(0.35 0)"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.2"/><circle cx="4.5" cy="12" r="1.2"/><circle cx="4.5" cy="18" r="1.2"/></g></symbol><symbol id="i-wifi" viewBox="0 0 24 24"><g transform="translate(0 -1.25)"><path d="M4 9.5a12 12 0 0 1 16 0M7 13a7.5 7.5 0 0 1 10 0M10 16.4a3 3 0 0 1 4 0"/><circle cx="12" cy="19.5" r=".6"/></g></symbol><symbol id="i-bt" viewBox="0 0 24 24"><path d="M7 7l10 10-5 4V3l5 4L7 17"/></symbol><symbol id="i-off" viewBox="0 0 24 24"><path d="M4 4l16 16M9 5.5A12 12 0 0 1 20 9.5M4 9.5a12 12 0 0 1 2.3-1.7M7 13a7.5 7.5 0 0 1 3-1.6"/><circle cx="12" cy="19.5" r=".6"/></symbol><symbol id="i-fan" viewBox="0 0 24 24"><circle cx="12" cy="12" r="1.6"/><path d="M12 10.4C11 7 12 4 15 4c2 0 2.5 3-3 6.4zM13.6 12c3.4-1 6.4 0 6.4 3 0 2-3 2.5-6.4-3zM12 13.6c1 3.4 0 6.4-3 6.4-2 0-2.5-3 3-6.4zM10.4 12C7 13 4 12 4 9c0-2 3-2.5 6.4 3z"/></symbol><symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.1"/></symbol></svg>`;
const ic = n => `<svg class="ic"><use href="#i-${n}"/></svg>`;
// Both links can be up (Wi-Fi read, Bluetooth standing by); older firmware reports only the one in use.
const bothLinks = () => on(E('binary_sensor', 'Grill on Wi-Fi')) && on(E('binary_sensor', 'Grill on Bluetooth'));

function start() {
  doc.documentElement.classList.add('gx');
  doc.documentElement.lang = 'en';
  doc.title = 'Smoker';
  meta('theme-color', '#c2410c');
  const ico = doc.createElement('link'); ico.rel = 'icon'; ico.href = FAVICON; doc.head.appendChild(ico);
  // Optional web fonts: offline, the system fonts in ui.css take over.
  const f = doc.createElement('link'); f.rel = 'stylesheet';
  f.href = 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600..800&family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap';
  doc.head.appendChild(f);
  const app = doc.querySelector('esp-app'); if (app) app.remove();
  doc.body.insertAdjacentHTML('afterbegin', ICONS + `<div class="wrap">
  <div class="topbar" id="topbar" role="status" aria-live="polite"></div>
  <header class="hero wide"><div class="htxt" id="hero"></div><div class="pic grillpic" id="grillpic" aria-label="The grill, live"></div></header>
  <nav class="secbar" id="secbar" aria-label="Sections"><a href="#s-food">${ic('food')}Food</a><a href="#s-pit">${ic('grill')}Pit &amp; program</a><a href="#s-fuel">${ic('hopper')}Charcoal &amp; plan</a><a href="#s-chart">${ic('chart')}Chart</a><a href="#s-journal">${ic('book')}Journal</a><a href="#s-setup">${ic('setup')}Setup</a></nav>
  <section class="sect" id="s-food"><h2 class="sec">${ic('food')}Food <small id="foodsub"></small></h2><div class="grid" id="food"></div></section>
  <section class="sect" id="s-pit"><h2 class="sec">${ic('grill')}Pit &amp; program</h2><div class="grid g-1-2"><div class="card" id="pit"></div><div class="card" id="prog"></div></div></section>
  <section class="sect" id="s-fuel"><h2 class="sec">${ic('hopper')}Charcoal &amp; plan</h2><div class="grid g-pair"><div class="card" id="fuel"></div><div class="card" id="plan"></div></div></section>
  <section class="sect" id="s-chart"><h2 class="sec">${ic('chart')}Temperatures <span class="seg" id="range"></span></h2><div class="card"><div class="chart" id="chart"></div><div class="legend" id="legend"></div></div></section>
  <section class="sect" id="s-journal"><h2 class="sec">${ic('book')}Cook journal</h2><div class="grid g-2-1"><div class="card" id="journal"></div><div class="card" id="share"></div></div></section>
  <section class="sect" id="s-setup"><h2 class="sec">${ic('setup')}Setup</h2><h3 class="sub">Grill connection</h3><div class="grid g-pair"><div class="card" id="conn"></div><div class="card" id="sources"></div></div>
    <h3 class="sub">Phone and weather</h3><div class="grid g-pair"><div class="card" id="notif"></div><div class="card" id="place"></div></div>
    <h3 class="sub">This controller</h3><div class="grid g-pair"><div class="card" id="lock"></div><div class="card" id="dev"></div></div></section>
  <footer id="foot"></footer></div><div id="toast" role="status" aria-live="polite"></div>`);
  wire();
  connect();
  loadLocal(); setInterval(loadLocal, 60000);
  loadHistory(); setInterval(loadHistory, 60000);
  loadJournal(); setInterval(loadJournal, 60000);
  loadCommunity(); setInterval(loadCommunity, 3600e3);
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
// The Bluetooth control switch was "(experimental)" before 0.2.9: accept either name.
const BLE = () => E('switch', 'Control over Bluetooth') ? 'Control over Bluetooth' : 'Control over Bluetooth (experimental)';
const tog = (name, label, note) => { const e = E('switch', name); return e ? `<div class="row"><span>${label}${note ? `<br><span class="muted small">${note}</span>` : ''}</span><button class="tg${on(e) ? ' on' : ''}" data-a="toggle" data-n="${esc(name)}" role="switch" aria-checked="${on(e)}" aria-label="${esc(name)}"></button></div>` : ''; };
const row = (l, r) => `<div class="row"><span>${l}</span><span class="r">${r}</span></div>`;

// ---------------------------------------------------------------- REST actions
function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600); }
// The device page's PIN (components/standalone): once one is set, every change needs this browser's session token.
const TOK = {
  get() { try { return localStorage.getItem('smokerToken') || ''; } catch (e) { return ''; } },
  set(t) { try { t ? localStorage.setItem('smokerToken', t) : localStorage.removeItem('smokerToken'); } catch (e) { /* private mode */ } },
};
const needPin = () => { toast('Enter the PIN (Setup → This page\'s PIN) to make changes'); const c = $('lock'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'center' }); };
async function post(dom, name, action, params) {
  const q = params ? '?' + new URLSearchParams(params) : '';
  try {
    const r = await fetch(`/${dom}/${encodeURIComponent(name)}/${action}${q}`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Smoker-Token': TOK.get() } });
    if (r.status === 401) { if (LOCAL) LOCAL.authed = false; renderLocal(); needPin(); return false; }
    if (!r.ok) throw new Error(r.status === 404 ? 'not found' : 'HTTP ' + r.status);
    return true;
  } catch (e) { toast('Couldn\'t change ' + name + ': ' + e.message); return false; }
}
// /local/...: the PIN, write-only keys, notifications, location and time zone.
let LOCAL = null;
async function local(path, body) {
  const r = await fetch('/local/' + path, body === undefined ? { headers: { 'X-Smoker-Token': TOK.get() } }
    : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Smoker-Token': TOK.get() }, body: JSON.stringify(body) });
  let d = {}; try { d = await r.json(); } catch (e) { /* empty */ }
  if (!r.ok) { if (r.status === 401 && LOCAL) { LOCAL.authed = false; renderLocal(); } throw new Error(d.error || 'HTTP ' + r.status); }
  return d;
}
async function loadLocal() {
  try { LOCAL = await local('status'); } catch (e) { LOCAL = LOCAL || null; }
  if (LOCAL && LOCAL.pin && !LOCAL.authed && TOK.get()) TOK.set('');
  renderLocal();
}
// The browser's time zone as offsets and daylight-saving rules (what the controller needs; it can't look zones up).
function tzRules() {
  const y = new Date().getFullYear(), off = t => new Date(t).getTimezoneOffset();
  const ch = []; let prev = off(Date.UTC(y, 0, 1));
  for (let t = Date.UTC(y, 0, 1); t < Date.UTC(y + 1, 0, 1); t += 3600e3) {
    const o = off(t); if (o === prev) continue;
    let lo = t - 3600e3, hi = t;
    while (hi - lo > 60e3) { const m = lo + Math.floor((hi - lo) / 120e3) * 60e3; if (off(m) === prev) lo = m; else hi = m; }
    ch.push({ at: hi, from: prev, to: o }); prev = o;
  }
  const rule = c => { const d = new Date(c.at - c.from * 60e3), day = d.getUTCDate(), dim = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
    return { m: d.getUTCMonth() + 1, w: day + 7 > dim ? 5 : Math.ceil(day / 7), d: d.getUTCDay(), t: d.getUTCHours() * 3600 + d.getUTCMinutes() * 60 }; };
  if (ch.length < 2) return { std: off(Date.now()) * 60, dst: off(Date.now()) * 60 };
  const start = ch.find(c => c.to < c.from), end = ch.find(c => c.to > c.from);
  return { std: Math.max(start.from, end.to) * 60, dst: Math.min(start.to, end.from) * 60, start: rule(start), end: rule(end) };
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
  wifipick(el) { const f = $('wifissid'); if (f) { f.value = el.dataset.v; f.dataset.dirty = '1'; } },
  async wifijoin() {
    const ssid = ($('wifissid') || {}).value || '', pass = ($('wifipass') || {}).value || '';
    if (!ssid.trim()) return toast('Pick or type the network name');
    if (!(await post('text', 'Grill Wi-Fi: network name', 'set', { value: ssid.trim() }))) return;
    if (!(await post('text', 'Grill Wi-Fi: password', 'set', { value: pass }))) return;
    await post('button', 'Grill Wi-Fi: set up', 'press');
    ['wifissid', 'wifipass'].forEach(k => { const f = $(k); if (f) { delete f.dataset.dirty; if (k === 'wifipass') f.value = ''; } });
    toast('Sent to the grill: watch "Grill\'s Wi-Fi"');
  },
  async pinset() {
    const a = ($('pin1') || {}).value || '', b = ($('pin2') || {}).value || '';
    if (a !== b) return toast('The two PINs differ');
    try { const d = await local('pin', { pin: a, current: ($('pin0') || {}).value || '' }); TOK.set(d.token); ['pin0', 'pin1', 'pin2'].forEach(k => { const f = $(k); if (f) { f.value = ''; delete f.dataset.dirty; } }); toast('PIN set: this browser stays unlocked for 12 h'); }
    catch (e) { toast(e.message); }
    loadLocal();
  },
  async login() {
    try { const d = await local('login', { pin: ($('pinin') || {}).value || '' }); TOK.set(d.token); const f = $('pinin'); if (f) { f.value = ''; delete f.dataset.dirty; } toast('Unlocked for 12 h in this browser'); }
    catch (e) { toast(e.message); }
    loadLocal();
  },
  async logout() { try { await local('logout', {}); } catch (e) { /* gone anyway */ } TOK.set(''); loadLocal(); toast('Locked'); },
  async secret(el) {
    const k = el.dataset.k, f = $('sec-' + k), v = el.dataset.clear ? '' : (f ? f.value.trim() : '');
    if (!el.dataset.clear && !v) return toast('Type it first');
    try { LOCAL = await local('secret', { name: k, value: v }); if (f) { f.value = ''; delete f.dataset.dirty; } toast(v ? 'Saved (it can\'t be read back, only replaced)' : 'Removed'); renderLocal(); }
    catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); }
  },
  async ntfyserver() {
    const f = $('ntfysrv'); try { LOCAL = await local('settings', { ntfy_server: f.value.trim() }); delete f.dataset.dirty; toast('ntfy server saved'); renderLocal(); } catch (e) { toast(e.message); }
  },
  async testnotify() { try { LOCAL = await local('test-notify', {}); toast('Test sent: check your phone'); renderLocal(); setTimeout(loadLocal, 8000); } catch (e) { toast(e.message); } },
  async geo() {
    const q = (($('geoq') || {}).value || '').trim(); if (!q) return toast('Type a town or postcode');
    const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (m) return ACT.place({ dataset: { lat: m[1], lon: m[2], n: 'that spot' } });
    try {  // the search goes from this browser to Open-Meteo, not through the controller
      const r = await fetch('https://geocoding-api.open-meteo.com/v1/search?count=5&name=' + encodeURIComponent(q));
      geoHits = ((await r.json()).results || []).map(x => ({ n: [x.name, x.admin1, x.country].filter(Boolean).join(', '), lat: x.latitude, lon: x.longitude }));
      if (!geoHits.length) toast('Nothing found: try a nearby town, or type "latitude, longitude"');
    } catch (e) { toast('Search needs internet on this phone; or type "latitude, longitude"'); }
    renderLocal();
  },
  async place(el) {
    try { LOCAL = await local('settings', { lat: parseFloat(el.dataset.lat), lon: parseFloat(el.dataset.lon) }); geoHits = []; const f = $('geoq'); if (f) { f.value = ''; delete f.dataset.dirty; } toast('Weather for ' + el.dataset.n + ' (rounded to about 1 km)'); renderLocal(); }
    catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); }
  },
  async clearplace() { try { LOCAL = await local('settings', { clear_location: true }); toast('Location removed: weather comes from Home Assistant again'); renderLocal(); } catch (e) { toast(e.message); } },
  async tz() { try { LOCAL = await local('settings', { tz: tzRules() }); toast('Time zone set from this browser'); renderLocal(); } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); } },
  range(el) { chartHours = +el.dataset.h; loadHistory(); },
  fuelmode(el) { fuelMode = el.dataset.m; renderFuel(); },
  async fuel(el) {
    const words = { start: 'Started at', check: 'Level', refill: 'Topped up to', add: 'Added', end: 'Finished with' };
    try { await local('fuel', { mode: fuelMode, percent: +el.dataset.p }); toast(words[fuelMode] + ' ' + el.dataset.p + '%'); } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); }
  },
  async jrate(el) { await jpost(el.dataset.id, { rating: +el.dataset.n }); },
  async jtag(el) {
    const e = (JOURNAL.entries || []).find(x => x.id === el.dataset.id); if (!e) return;
    const t = new Set(e.tags || []); t.has(el.dataset.t) ? t.delete(el.dataset.t) : t.add(el.dataset.t);
    e.tags = TASTE.flat().filter(x => t.has(x)); renderJournal();
    await jpost(e.id, { tags: e.tags });
  },
  async jnote(el) { const f = $('jn-' + el.dataset.id); if (!f) return; await jpost(el.dataset.id, { notes: f.value.slice(0, 99) }); delete f.dataset.dirty; toast('Saved'); },
  async jdel(el) {
    const k = 'del' + el.dataset.id;
    if (!armed[k]) { armed[k] = setTimeout(() => { delete armed[k]; renderJournal(); }, 3000); return renderJournal(); }
    clearTimeout(armed[k]); delete armed[k]; await jpost(el.dataset.id + '/delete', {}); toast('Removed from the journal');
  },
  async jshare(el) { if (await sharePost('share/' + el.dataset.id)) toast('Sharing, anonymously… thank you!'); setTimeout(loadJournal, 4000); },
  async jdecline(el) { await sharePost('share/' + el.dataset.id + '/decline'); },
  async sharecfg(el) { const o = {}; o[el.dataset.k] = el.dataset.v === '1'; if (await sharePost('share/settings', o)) toast(el.dataset.k === 'enabled' ? (o.enabled ? 'Sharing on: the journal asks after each cook' : 'Sharing off') : o.auto ? 'Cooks are shared once rated (or after 12 h)' : 'The journal asks after each cook'); },
  async sharewithdraw() {
    if (!armed.wd) { armed.wd = setTimeout(() => { delete armed.wd; renderShare(); }, 4000); return renderShare(); }
    clearTimeout(armed.wd); delete armed.wd;
    try { const d = await local('share/withdraw', {}); toast(`Removing ${d.removing} shared cook${d.removing === 1 ? '' : 's'}…`); setTimeout(loadJournal, 5000); } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); }
  },
  sharedl() {
    const recs = (JOURNAL.entries || []).filter(e => e.record).map(e => Object.assign({}, e.record, { id: undefined }));
    const a = doc.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({ v: 1, records: recs }, null, 1)], { type: 'application/json' }));
    a.download = 'smoker-cooks-anonymised.json'; doc.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  },
  async plansave() {
    const v = ($('servein') || {}).value, r = parseInt(($('restin') || {}).value, 10);
    const o = {}; if (v) o.serve_by = Math.round(new Date(v).getTime() / 1000); if (Number.isFinite(r)) o.rest_min = r;
    try { await local('plan', o); ['servein', 'restin'].forEach(k => { const f = $(k); if (f) delete f.dataset.dirty; }); toast('Plan saved'); loadLocal(); } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); }
  },
  async planclear() { try { await local('plan', { serve_by: 0 }); toast('Plan cleared'); loadLocal(); } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); } },
  ip() { const v = $('ipin').value.trim(); post('text', 'Grill IP address', 'set', { value: v }).then(ok => { if (ok) { delete $('ipin').dataset.dirty; toast(v ? 'Grill address set' : 'Finding the grill automatically'); } }); },
};
function wire() {
  doc.addEventListener('click', e => {  // a part of the grill drawing -> its section
    const g = e.target.closest('#grillpic [data-go]'); if (!g) return;
    const el = $(g.dataset.go), bar = $('secbar');
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - (bar ? bar.offsetHeight : 0) - 10, behavior: 'smooth' });
  });
  doc.addEventListener('keydown', e => { const g = e.target.closest && e.target.closest('#grillpic [data-go]'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.dispatchEvent(new MouseEvent('click', { bubbles: true })); } });
  doc.addEventListener('click', e => { const b = e.target.closest('[data-a]'); if (b && !b.disabled && ACT[b.dataset.a]) ACT[b.dataset.a](b); });
  doc.addEventListener('change', e => {
    const t = e.target, n = t.dataset && t.dataset.n; if (!n) return;
    if (n === 'Program preset') { progEd.state.touched = false; progEd.state.sent = null; }  // the editor follows the preset
    if (t.dataset.c === 'route') { local('settings', { route: t.value }).then(d => { LOCAL = d; renderLocal(); toast('Notifications: ' + t.selectedOptions[0].text); }).catch(err => { if (/PIN/.test(err.message)) needPin(); else toast(err.message); }); return; }
    if (t.dataset.c === 'select') post('select', n, 'set', { option: t.value }).then(ok => ok && toast(n + ': ' + t.value));
    else if (t.dataset.c === 'number') { delete t.dataset.dirty; setNum(n, parseFloat(t.value)); }
  });
  doc.addEventListener('input', e => { if (e.target.id) e.target.dataset.dirty = '1'; });
  doc.addEventListener('keydown', e => { if (e.key !== 'Enter') return; const k = { pitin: 'pitset', ipin: 'ip', pinin: 'login', pin2: 'pinset', geoq: 'geo' }[e.target.id]; if (k) ACT[k](); });
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
  const bleE = E('switch', BLE()), ble = on(bleE), br = E('switch', 'Bridge enabled');
  if (br && !on(br)) return { cls: 'warn', txt: 'Read-only', why: 'The bridge is turned off (Setup), so the Char-Griller app can use the grill.' };
  if (!conn) return { cls: 'warn', txt: 'Read-only', why: 'Not connected to the grill.' };
  if (via === 'wifi') return { cls: 'ok', txt: 'Controlling over Wi-Fi' };
  if (via === 'bluetooth') return ble || !bleE ? { cls: 'ok', txt: 'Controlling over Bluetooth' }
    : { cls: 'warn', txt: 'Read-only', why: 'Connected over Bluetooth with control turned off: turn on "Control over Bluetooth" in Setup.' };
  return { cls: 'ok', txt: 'Connected to the grill' };
}

function render() {
  const u = TU(), live = Date.now() - last < 25000;
  const pit = S('Pit temperature'), tgt = cur('Pit target') ?? S('Pit target (reported)') ?? S('Pit target reported');
  const L = link(), active = on(E('binary_sensor', 'Cook active')), el = S('Cook elapsed');
  const pst = T('Program state');
  put('hero', `<div class="eyebrow"><span class="brandline">${MARK}${esc(cfg.title || 'Smoker')} · Gravity 980</span><span><i class="dot ${live ? 'on' : 'off'}"></i>${live ? 'Live' : 'Reconnecting…'}</span></div>
    <div class="big"><span>${fmt(pit)}<small>${esc(u)}</small></span>${tgt != null ? `<span class="to">→ ${fmt(tgt)}${esc(u)}</span>` : ''}</div>
    <div class="chips"><span class="chip ${L.cls}">${esc(L.txt)}</span>${L.exp ? EXP('Setting targets over Bluetooth is new on the 980: check the grill follows the first change.') : ''}
      ${active ? `<span class="chip hot">Cooking${el != null ? ' · ' + mins(el) : ''}</span>` : '<span class="chip">No cook running</span>'}
      ${/Running|Paused/.test(pst) ? `<span class="chip ${pst === 'Paused' ? 'warn' : 'hot'}">Program ${esc(pst.toLowerCase())}</span>` : ''}
      ${on(E('binary_sensor', 'Lid')) ? '<span class="chip warn">Lid open</span>' : ''}
      ${on(E('binary_sensor', 'Grill alarm')) ? '<span class="chip bad">Grill alarm</span>' : ''}</div>
    ${L.why ? `<p class="why">${esc(L.why)}</p>` : ''}`);
  // Status strip, first on the page: connected? controlling? anything wrong?
  const conn = on(E('binary_sensor', 'Grill connected')), via = T('Grill link');
  const al = [], add = (c, t) => al.push(`<span class="chip ${c}">${esc(t)}</span>`);
  if (on(E('binary_sensor', 'Grill alarm'))) add('bad', 'Grill alarm');
  if (on(E('binary_sensor', 'Lid'))) add('warn', 'Lid open');
  if (active && pit != null && tgt != null && Math.abs(pit - tgt) > (isF() ? 25 : 14)) add('warn', pit > tgt ? 'Running hot' : 'Running cold');
  for (let i = 1; i <= 6; i++) if (on(E('binary_sensor', `Food ${i} probe warning`))) add('warn', `Food ${i}: check the probe`);
  const hl = S('Charcoal hours left');
  if (hl != null && hl < 1.5 && active) add(hl < 0.75 ? 'bad' : 'warn', `Charcoal ~${fmt(hl, 1)} h left`);
  if (pst === 'Paused') add('warn', 'Program paused');
  if (!live) add('warn', 'Page reconnecting to the controller');
  const ok = conn && via !== 'none';
  const how = bothLinks() ? ' · Wi-Fi + Bluetooth' : via === 'wifi' ? ' · Wi-Fi' : via === 'bluetooth' ? ' · Bluetooth' : '';
  const head = ok ? `<span class="t">Grill connected${how}<small>${L.cls === 'ok' ? 'this page controls it' : esc(L.why || 'read-only')}</small></span>`
    : `<span class="t">Grill not connected<small>${esc(T('Grill link status') || (L.why && /bridge/i.test(L.why) ? 'the bridge is turned off (Setup)' : 'is the grill on and in range?'))}</small></span>`;
  const tb = $('topbar');
  if (tb) tb.className = 'topbar' + (!ok || al.some(x => /chip bad/.test(x)) ? ' bad' : L.cls !== 'ok' || al.length ? ' warn' : '');
  put('topbar', `<span class="conn"><i class="dot ${!ok ? 'off' : L.cls === 'ok' ? 'on' : 'stale'}"></i>${!ok ? ic('off') : bothLinks() ? ic('wifi') + ic('bt') : ic(via === 'wifi' ? 'wifi' : via === 'bluetooth' ? 'bt' : 'grill')}${head}</span>
    <span class="alerts">${al.join('') || (ok ? '<span class="chip ok">All good</span>' : '')}</span>`);
  renderGrill(u, pit, tgt); renderPit(u, pit, tgt); renderFood(u); renderFuel(); renderProg(); renderSetup(u);
}

// The grill, drawn (ported from the HA panel's renderGrill(), page.html): controller (left shelf) · barrel
// (pit, food) · hopper tower (charcoal) · ash box (fan). Tap a part to jump to its section.
const photoBad = {};
window.__gxPhotoBad = url => { if (url && !photoBad[url]) { photoBad[url] = true; render(); } };  // unreachable: the drawing
const FOODC = ['var(--food1)', 'var(--food2)', 'var(--g1)', 'var(--g2)', 'var(--g3)', 'var(--g4)'];
function renderGrill(u0, pit, tgt) {
  const conn = on(E('binary_sensor', 'Grill connected')), via = T('Grill link');
  const lid = on(E('binary_sensor', 'Lid')), fan = on(E('binary_sensor', 'Fan')), cook = on(E('binary_sensor', 'Cook active'));
  const lvl = S('Charcoal level'), hrs = S('Charcoal hours left');
  const u = u0.replace('°', ''), deg = '°';
  const heat = pit == null ? 0 : Math.max(0, Math.min(1, ((isF() ? pit : pit * 9 / 5 + 32) - 120) / 480));
  const foods = [];
  for (let i = 1; i <= 6; i++) { const t = S('Food ' + i + ' temperature'); if (t != null) foods.push({ i, t }); }
  const tw = foods.length ? Math.min(150, 500 / foods.length - 8) : 0, fs = foods.length > 4 ? 16 : foods.length > 3 ? 20 : 23;
  const tags = foods.map(({ i, t }, k) => {
    const x = 258 + k * (tw + 8);
    return `<g class="hot" tabindex="0" role="link" data-go="s-food" aria-label="Food ${i} ${fmt(t)} degrees">
      <rect class="hl" x="${x}" y="248" width="${tw}" height="38" rx="19" fill="var(--surface)" stroke="${FOODC[i - 1]}" stroke-width="3"/>
      <text x="${x + tw / 2}" y="275" text-anchor="middle" font-size="${fs}" font-weight="700" fill="var(--ink)">F${i} ${fmt(t)}${deg}</text></g>`;
  }).join('');
  const fill = lvl == null ? 0 : Math.max(0, Math.min(1, lvl / 100)), fh = 330 * fill;
  const lk = !conn ? ['not connected', 'var(--bad)'] : bothLinks() ? ['via Wi-Fi + Bluetooth', 'var(--ok)'] : via === 'wifi' ? ['via Wi-Fi', 'var(--ok)'] : via === 'bluetooth' ? ['via Bluetooth', 'var(--ok)'] : ['connected', 'var(--ok)'];
  const ly = lvl == null ? 230 : Math.min(372, Math.max(118, 400 - fh / 2 + 10));
  // Your grill photo (text "Grill photo URL", filled in by the Smoker dashboard) with the readings pinned on it.
  const photo = str(E('text', 'Grill photo URL'));
  if (photo && /^https?:\/\//i.test(photo) && !photoBad[photo]) {
    const pin = (x, y, go, html, cls) => `<a class="pin ${cls || ''}" style="left:${x}%;top:${y}%" data-go="${go}" tabindex="0" role="link">${html}</a>`;
    put('grillpic', `<div class="gphoto"><img src="${esc(photo)}" alt="The grill" onerror="window.__gxPhotoBad(this.getAttribute('src'))">
      ${pin(50, 17, foods.length ? 's-food' : 's-pit', `<span class="m">${fmt(pit)}${deg}${esc(u)}</span>${tgt != null ? `<small>→ ${fmt(tgt)}${deg}</small>` : ''}`, 'big')}
      ${lid ? pin(50, 6, 's-pit', 'Lid open', 'warn') : ''}
      ${pin(14.5, 35, 's-pit', `<span class="m">${tgt != null ? fmt(tgt) + deg : '---'}</span> <span style="color:${lk[1]}">● ${esc(lk[0].replace('via ', ''))}</span>`)}
      <span class="shelf">${foods.map(({ i, t }) => `<a class="pin" data-go="s-food" tabindex="0" role="link" style="border-color:${FOODC[i - 1]}"><span class="m">F${i} ${fmt(t)}${deg}</span></a>`).join('')}</span>
      ${pin(82, 30, 's-fuel', `<span class="m">${lvl == null ? '?' : fmt(lvl) + '%'}</span>${hrs != null ? `<small>${fmt(hrs, 1)} h</small>` : ''}`)}
      ${pin(82, 58, 's-pit', `<span class="${fan ? 'spin' : ''}">✱</span> fan ${fan ? 'on' : 'off'}`)}</div>`);
    return;
  }
  put('grillpic', `<svg viewBox="0 0 1000 640" role="img" aria-label="Grill: pit ${fmt(pit)} degrees, target ${fmt(tgt)}, charcoal ${lvl == null ? 'unknown' : fmt(lvl) + ' percent'}">
  <defs>
    <pattern id="perf" width="14" height="14" patternUnits="userSpaceOnUse"><circle cx="7" cy="7" r="3.2" fill="rgba(0,0,0,.45)"/></pattern>
    <pattern id="mesh" width="10" height="10" patternUnits="userSpaceOnUse"><circle cx="5" cy="5" r="2.4" fill="rgba(0,0,0,.4)"/></pattern>
    <radialGradient id="heat" cx="50%" cy="100%" r="80%"><stop offset="0" stop-color="var(--pit)" stop-opacity=".95"/><stop offset="1" stop-color="var(--pit)" stop-opacity="0"/></radialGradient>
    <linearGradient id="lidg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".18"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>
  </defs>
  <ellipse cx="500" cy="612" rx="430" ry="14" fill="var(--line)" opacity=".7"/>
  <path d="M296 288 L268 580 L294 580 L322 288 Z M672 288 L704 580 L730 580 L698 288 Z" fill="var(--steel)"/>
  <rect x="300" y="288" width="396" height="92" rx="3" fill="var(--steel)"/>
  <text x="498" y="348" text-anchor="middle" font-size="44" font-weight="800" fill="none" stroke="var(--steel2)" stroke-width="2.5" letter-spacing="6" class="lbl">GRAVITY</text>
  <rect x="272" y="512" width="452" height="20" rx="3" fill="var(--steel2)"/><rect x="272" y="512" width="452" height="20" fill="url(#mesh)"/>
  <rect x="262" y="578" width="40" height="10" rx="3" fill="var(--steel2)"/><circle cx="282" cy="600" r="12" fill="var(--steel)"/>
  <circle cx="718" cy="586" r="36" fill="var(--steel)"/><circle cx="718" cy="586" r="24" fill="none" stroke="var(--steel2)" stroke-width="4"/><circle cx="718" cy="586" r="7" fill="var(--steel2)"/>
  <g class="hot" tabindex="0" role="link" data-go="s-pit" aria-label="Controller: pit target ${fmt(tgt)}">
    <rect class="hl" x="40" y="230" width="210" height="58" rx="4" fill="var(--steel)" stroke="transparent"/>
    <rect x="40" y="222" width="210" height="12" fill="var(--steel2)"/><rect x="40" y="222" width="210" height="12" fill="url(#mesh)"/>
    <rect x="62" y="238" width="166" height="42" rx="4" fill="var(--panel)"/>
    <circle cx="96" cy="259" r="11" fill="var(--steel)"/>
    <rect x="118" y="245" width="100" height="28" rx="3" fill="#13241a"/>
    <text x="168" y="266" text-anchor="middle" font-size="20" font-weight="600" fill="#7dfca0">${tgt != null ? fmt(tgt) : '---'}</text>
    <text x="145" y="318" text-anchor="middle" font-size="22" class="lbl" fill="${lk[1]}" font-weight="700">● ${lk[0]}</text>
  </g>
  <g class="hot" tabindex="0" role="link" data-go="${foods.length ? 's-food' : 's-pit'}" aria-label="Pit ${fmt(pit)} degrees">
    <rect class="hl" x="245" y="66" width="525" height="190" rx="95" fill="var(--steel)" stroke="transparent"/>
    <rect x="300" y="150" width="415" height="100" fill="url(#heat)" opacity="${(0.15 + 0.75 * heat).toFixed(2)}"/>
    <rect x="270" y="58" width="475" height="150" rx="72" fill="var(--lid)"/>
    <rect x="270" y="58" width="475" height="150" rx="72" fill="url(#lidg)"/>
    <rect x="378" y="186" width="260" height="11" rx="5.5" fill="#cfd6dc"/>
    <text x="507" y="136" text-anchor="middle" font-size="62" font-weight="700" fill="#fff">${fmt(pit)}${deg}</text>
    <text x="507" y="170" text-anchor="middle" font-size="24" fill="rgba(255,255,255,.9)" class="lbl">${tgt != null ? 'target ' + fmt(tgt) + deg + esc(u) : 'pit ' + deg + esc(u)}</text>
    ${lid ? '<rect x="432" y="18" width="150" height="30" rx="15" fill="var(--warn)"/><text x="507" y="39" text-anchor="middle" font-size="16" font-weight="700" fill="#fff" class="lbl">LID OPEN</text>' : ''}
  </g>
  <rect x="245" y="244" width="525" height="44" rx="4" fill="var(--steel2)"/>
  ${tags || '<text x="507" y="274" text-anchor="middle" font-size="20" fill="var(--panel)" class="lbl" opacity=".85">no food probes reading</text>'}
  <g class="hot" tabindex="0" role="link" data-go="s-fuel" aria-label="Charcoal ${lvl == null ? 'level unknown' : fmt(lvl) + ' percent'}">
    <rect class="hl" x="775" y="20" width="132" height="392" rx="6" fill="var(--steel)" stroke="transparent"/>
    <rect x="770" y="14" width="142" height="40" rx="4" fill="var(--steel2)"/>
    <rect x="792" y="70" width="98" height="330" fill="var(--coal)" opacity=".55"/>
    <rect x="792" y="${400 - fh}" width="98" height="${fh}" fill="var(--coal)"/>
    ${cook && fill > 0 ? '<rect class="ember" x="792" y="384" width="98" height="16" fill="var(--pit)" opacity=".9"/>' : ''}
    <rect x="792" y="70" width="98" height="330" fill="url(#perf)"/>
    <rect x="792" y="70" width="98" height="330" fill="none" stroke="var(--steel2)" stroke-width="3"/>
    <text x="841" y="${ly}" text-anchor="middle" font-size="36" font-weight="700" fill="#fff">${lvl == null ? '?' : fmt(lvl) + '%'}</text>
    <text x="841" y="${ly + 24}" text-anchor="middle" font-size="20" fill="rgba(255,255,255,.9)" class="lbl">${lvl == null ? 'no level' : hrs != null ? fmt(hrs, 1) + ' h left' : 'charcoal'}</text>
  </g>
  <rect x="785" y="414" width="120" height="132" rx="5" fill="var(--steel)"/>
  <text x="845" y="494" text-anchor="middle" font-size="34" font-weight="800" fill="none" stroke="var(--steel2)" stroke-width="2" class="lbl">980</text>
  <g class="hot" tabindex="0" role="link" data-go="s-pit" aria-label="Fan ${fan ? 'running' : 'off'}">
    <rect class="hl" x="905" y="446" width="50" height="70" rx="5" fill="var(--steel2)" stroke="transparent"/>
    <g class="fan${fan ? ' on' : ''}"><circle cx="930" cy="481" r="17" fill="var(--steel)"/>
      <path d="M930 481 L930 466 A15 15 0 0 1 943 474 Z M930 481 L945 486 A15 15 0 0 1 936 496 Z M930 481 L920 492 A15 15 0 0 1 916 474 Z" fill="${fan ? 'var(--page)' : 'var(--muted)'}"/></g>
    <text x="930" y="544" text-anchor="middle" font-size="20" class="lbl" fill="var(--ink-2)" font-weight="600">fan ${fan ? 'on' : 'off'}</text>
  </g>
</svg>`);
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
    cards.push(`<article class="card food" data-slot="${i}"><span class="edge" style="background:${FOODC[i - 1]}"></span>
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
  $('foodsub').textContent = cards.length ? cards.length + ' on the grill' : '';
  put('food', cards.join('') || '<div class="empty">No food probe is reading. Plug one in, or pick a thermometer for a slot under Setup.</div>');
}

let fuelMode = 'check';
function renderFuel() {
  const lvl = S('Charcoal level'), hrs = S('Charcoal hours left'), empty = T('Charcoal empty at'), basis = T('Charcoal estimate basis');
  const left = E('sensor', 'Charcoal left'), rate = E('sensor', 'Charcoal burn rate');
  put('fuel', `<h3><span>Hopper</span>${sel('select', 'Charcoal type')}</h3>
    ${lvl != null ? `<div class="eta"><span class="t">${fmt(lvl)}%</span><span class="muted small">${num(left) != null ? fmt(num(left), 1) + ' ' + esc(left.uom || '') + ' · ' : ''}${hrs != null ? '~' + fmt(hrs, 1) + ' h left' : ''}</span>${isExp(basis) ? EXP(basis) : ''}</div>
      <div class="gauge"><i class="${lvl < 25 ? 'low' : ''}" style="width:${Math.max(0, Math.min(100, lvl))}%"></i></div>
      ${row('Runs out', esc(empty || '--'))}${rate ? row('Burning', num(rate) != null ? fmt(num(rate), 2) + ' ' + esc(rate.uom || '') : '--') : ''}
      ${basis ? `<p class="note">${esc(basis)}</p>` : ''}` : '<p class="note" style="margin-top:0">No charcoal level yet.</p>'}
    ${LOCAL && LOCAL.plan ? (() => {
      const modes = [['start', 'Started at'], ['check', 'It\'s at'], ['refill', 'Topped up to'], ['add', 'Added'], ['end', 'Finished with']];
      const fr = fuelMode === 'add' ? [[25, '¼'], [50, '½'], [75, '¾']] : fuelMode === 'end' ? [[0, 'Empty'], [12.5, '⅛'], [25, '¼'], [50, '½'], [75, '¾']] : [[25, '¼'], [50, '½'], [75, '¾'], [100, 'Full']];
      return `<div class="seg" style="margin:8px 0;flex-wrap:wrap">${modes.map(([k, l]) => `<button aria-pressed="${fuelMode === k}" data-a="fuelmode" data-m="${k}">${l}</button>`).join('')}</div>
        <div class="btns">${fr.map(([v, l]) => `<button class="btn" data-a="fuel" data-p="${v}">${l}</button>`).join('')}</div>`;
    })() : '<p class="note">Log charcoal (lit, checked, topped up) from Home Assistant: this controller\'s firmware is too old to log it here.</p>'}`);
}

// ==== BEGIN cook program editor (shared block) ====
// The same block is in custom_components/smoker/frontend/page.html (Home Assistant panel) and
// firmware/device-ui/ui.js (the controller's own page): keep the two copies identical (tests/render_page.py checks).
// PG.parse/format follow components/cook_assistant/program.cpp; PG.editor draws the step editor into a container.
const PG = (() => {
  const UNITS = Object.assign(Object.create(null), { f: 'F', c: 'C', m: 'm', min: 'm', mins: 'm', minutes: 'm', h: 'h', hr: 'h', hrs: 'h', hour: 'h', hours: 'h' });
  const isD = c => c >= '0' && c <= '9', isA = c => /^[A-Za-z]$/.test(c || ''), isW = c => /^[A-Za-z0-9_]$/.test(c || '');
  const TEMP = { gte: 1, lte: 1, pit: 1 }, PROBE = { gte: 1, lte: 1, done: 1, stall_start: 1, stall_end: 1 }, HELD = { gte: 1, lte: 1, pit: 1, done: 1 };
  const U = m => ({ u: m });  // valid for the controller, but not something the step editor can show
  function tokenize(s) {
    const out = []; let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (/\s/.test(c) || c === ',') { i++; continue; }
      if (c === '"' || c === "'") { const j = s.indexOf(c, i + 1); if (j < 0) throw 'unterminated quote'; out.push({ k: 'S', t: s.slice(i + 1, j) }); i = j + 1; continue; }
      if (c === '>' || c === '<' || c === '=') { let op = c; if (s[i + 1] === '=') { op += '='; i++; } i++; out.push({ k: 'O', t: op === '>' ? '>=' : op === '<' ? '<=' : op }); continue; }
      if (isD(c) || c === '.') {
        let j = i; while (j < s.length && (isD(s[j]) || s[j] === '.' || s[j] === ':')) j++;
        const t = { k: 'N', t: s.slice(i, j), n: 0, u: '' };
        if (t.t.includes(':')) { const m = /^(\d+):(\d+)/.exec(t.t); if (!m || +m[1] > 23 || +m[2] > 59) throw "bad time '" + t.t + "'"; t.n = +m[1] * 60 + +m[2]; t.u = 't'; }
        else { t.n = parseFloat(t.t); if (!Number.isFinite(t.n)) throw "bad number '" + t.t + "'"; }
        let k = j; while (s[k] === ' ') k++;  // a unit after one space ("250 F", "2 h") or a degree sign
        let e = k; if (s[e] === '°') e++;
        let w = e; while (w < s.length && isA(s[w])) w++;
        if (k > j && (UNITS[s.slice(e, w).toLowerCase()] || e > k)) j = e;
        if (s[j] === '°') j++;
        if (isA(s[j])) { let k2 = j; while (isA(s[k2])) k2++; const u = s.slice(j, k2).toLowerCase(); if (!UNITS[u]) throw "unknown unit '" + u + "'"; t.u = UNITS[u]; j = k2; }
        out.push(t); i = j; continue;
      }
      if (isA(c) || c === '_') { let j = i; while (isW(s[j])) j++; out.push({ k: 'W', t: s.slice(i, j).toLowerCase() }); i = j; continue; }
      throw "unexpected '" + c + "'";
    }
    out.push({ k: 'E', t: '' });
    return out;
  }
  const food = t => { const m = t.k === 'W' && /^food([1-6])$/.exec(t.t); return m ? +m[1] : null; };
  const hhmm = n => String(Math.floor(n / 60)).padStart(2, '0') + ':' + String(n % 60).padStart(2, '0');
  const dur = t => t.k === 'N' && !/[FCt]/.test(t.u || '_') ? (t.u === 'h' ? t.n * 60 : t.n) : null;
  // A temperature in the device unit (an explicit F/C suffix is converted).
  function temp(t, f) {
    if (t.k !== 'N' || !(t.u === '' || t.u === 'F' || t.u === 'C')) return null;
    if (!t.u || (t.u === 'F') === f) return t.n;
    return Math.round(f ? t.n * 9 / 5 + 32 : (t.n - 32) * 5 / 9);
  }
  function step(text, f) {
    const t = tokenize(text); let i = 0, pit = null, hold = false, shut = false, note = '', any = false;
    while (t[i].k === 'W' && t[i].t !== 'until') {
      const w = t[i].t;
      if (w === 'pit' || w === 'hold' || w === 'set') {
        i++; if (t[i].k === 'W' && t[i].t === 'to') i++;
        const v = temp(t[i], f); if (v == null) throw "expected a temperature after '" + (w === 'hold' ? 'hold' : 'pit') + "'";
        pit = v; hold = hold || w === 'hold'; i++;
      } else if (w === 'notify' || w === 'alert') {
        i++; if (t[i].k !== 'S') throw 'notify needs a quoted message';
        note = t[i].t; i++;
      } else if (w === 'shutdown' || w === 'stop' || w === 'off') { shut = true; i++; } else if (w === 'then') { i++; continue; } else throw "unknown action '" + w + "'";
      any = true;
    }
    if (!any) throw 'step has no action (pit / hold / notify / shutdown)';
    if (note.includes('"')) throw U('a notification with double quotes');
    if (shut && pit != null) throw U('a pit temperature and shutdown in one step');
    const st = { kind: shut ? 'shutdown' : hold ? 'hold' : pit != null ? 'pit' : 'notify', temp: pit == null ? '' : String(pit), notify: note, until: [] };
    if (t[i].k === 'E') return st;
    if (!(t[i].k === 'W' && t[i].t === 'until')) throw "expected 'until'";
    if (st.kind === 'hold' || st.kind === 'shutdown') throw U("'until' on a " + (hold ? 'hold' : 'shutdown') + ' step');
    i++;
    for (;;) {
      if (t[i].k !== 'W') throw "expected a condition after 'until'/'or'";
      const w = t[i].t, c = { type: '', probe: 1, value: '', unit: 'm', held: '' };
      if (w === 'after') {
        i++; const d = dur(t[i]); if (d == null) throw "after needs a duration, e.g. 'after 2h'";
        c.type = 'after'; c.unit = d >= 60 && d % 60 === 0 ? 'h' : 'm'; c.value = String(c.unit === 'h' ? d / 60 : d); i++;
      } else if (w === 'at') {
        i++; if (t[i].k !== 'N' || t[i].u !== 't') throw "at needs a time, e.g. 'at 17:30'";
        c.type = 'at'; c.value = hhmm(t[i].n); i++;
      } else if (w === 'stall_start' || w === 'stall_end') {
        i++; const p = food(t[i]);
        if (p == null) { if (t[i].k === 'W' && t[i].t === 'pit') throw U('a pit stall'); throw w + ' needs a probe name'; }
        c.type = w; c.probe = p; i++;
      } else {
        const p = w === 'pit' ? 0 : food(t[i]); if (p == null) throw "unknown probe '" + w + "'";
        i++;
        if (t[i].k === 'W' && t[i].t === 'done') { if (!p) throw U("'pit done'"); c.type = 'done'; c.probe = p; i++; }
        else if (t[i].k === 'W' && t[i].t === 'stall') {
          i++; c.type = 'stall_start';
          if (t[i].k === 'W' && /^(ends|end|over)$/.test(t[i].t)) { c.type = 'stall_end'; i++; } else if (t[i].k === 'W' && /^(starts|start)$/.test(t[i].t)) i++;
          if (!p) throw U('a pit stall'); c.probe = p;
        } else if (t[i].k === 'O' && (t[i].t === '>=' || t[i].t === '<=')) {
          const ge = t[i].t === '>='; i++;
          const v = temp(t[i], f); if (v == null) throw "expected a temperature after '>='";
          i++;
          if (!p) { if (!ge) throw U("'pit <='"); c.type = 'pit'; } else { c.type = ge ? 'gte' : 'lte'; c.probe = p; }
          c.value = String(v);
        } else throw "expected >=, <=, 'done' or 'stall' after '" + w + "'";
      }
      if (t[i].k === 'W' && t[i].t === 'for') {
        i++; const d = dur(t[i]); if (d == null) throw "for needs a duration, e.g. 'for 30m'";
        if (!HELD[c.type]) throw U("'for' on this condition");
        c.held = String(d); i++;
      }
      st.until.push(c);
      if (t[i].k === 'W' && t[i].t === 'or') { i++; continue; }
      break;
    }
    if (t[i].k !== 'E') throw "unexpected '" + t[i].t + "' at end of step";
    return st;
  }
  // Text -> {prog} | {error} (the controller would refuse it too) | {unsupported} (fine, but not for the step editor).
  function parse(text, f) {
    const parts = []; let cur = '', q = '';
    for (const ch of String(text || '')) {
      if (q) { cur += ch; if (ch === q) q = ''; continue; }
      if (ch === '"' || ch === "'") { q = ch; cur += ch; continue; }
      if (ch === ';' || ch === '\n' || ch === '\r') { parts.push(cur); cur = ''; continue; }
      cur += ch;
    }
    parts.push(cur);
    const prog = { name: '', steps: [] }; let n = 0;
    for (const part of parts) {
      let s = part.replace(/^[ \t]+/, ''); if (!s) continue;
      if (s.slice(0, 5).toLowerCase() === 'name:') { prog.name = s.slice(5).trim(); continue; }
      const m = /^\d+[:.)]/.exec(s); if (m) s = s.slice(m[0].length);
      n++;
      try { prog.steps.push(step(s, f)); } catch (e) { return e && e.u ? { unsupported: 'step ' + n + ': ' + e.u } : { error: 'step ' + n + ': ' + e }; }
    }
    return prog.steps.length ? { prog } : { error: 'program has no steps' };
  }
  const numTxt = v => { const n = parseFloat(v); return Number.isFinite(n) ? String(n) : '?'; };
  const durTxt = m => !Number.isFinite(m) ? '?' : m >= 60 && m % 60 === 0 ? m / 60 + 'h' : m + 'm';
  function cond(c) {
    const P = 'food' + c.probe;
    const s = c.type === 'gte' ? P + ' >= ' + numTxt(c.value) : c.type === 'lte' ? P + ' <= ' + numTxt(c.value) : c.type === 'pit' ? 'pit >= ' + numTxt(c.value)
      : c.type === 'done' ? P + ' done' : c.type === 'after' ? 'after ' + durTxt(parseFloat(c.value) * (c.unit === 'h' ? 60 : 1))
        : c.type === 'at' ? 'at ' + (c.value || '?') : c.type + ' ' + P;
    const h = parseFloat(c.held);
    return s + (HELD[c.type] && h > 0 ? ' for ' + durTxt(h) : '');
  }
  // Steps -> text, in the presets' style ("name: X; pit 250 until food1 >= 165 for 30m; hold 200 notify \"Done\"").
  function format(p, sep) {
    const out = []; if ((p.name || '').trim()) out.push('name: ' + p.name.trim());
    p.steps.forEach(s => {
      const a = [];
      if (s.kind === 'pit' || s.kind === 'hold') a.push(s.kind + ' ' + numTxt(s.temp));
      if ((s.notify || '').trim()) a.push('notify "' + s.notify.trim() + '"');
      if (s.kind === 'shutdown') a.push('shutdown');
      if (s.kind === 'pit' || s.kind === 'notify') s.until.forEach((c, k) => a.push((k ? 'or ' : 'until ') + cond(c)));
      out.push(a.join(' '));
    });
    return out.join(sep || '; ');
  }
  const range = f => f ? [200, 700] : [93, 371];  // the stock controller's pit range
  // Problems the editor can see before sending (the controller still checks, and its error is shown after loading).
  function check(p, f) {
    const E = [], [lo, hi] = range(f), u = f ? '°F' : '°C';
    if (/[;"'\n\r]/.test(p.name || '')) E.push("The name can't contain ; or quotes");
    if (!p.steps.length) E.push('Add a step');
    p.steps.forEach((s, i) => {
      const add = m => E.push('Step ' + (i + 1) + ': ' + m), last = i === p.steps.length - 1;
      if (s.kind === 'pit' || s.kind === 'hold') {
        const v = parseFloat(s.temp);
        if (!Number.isFinite(v)) add('set the pit temperature'); else if (v < lo || v > hi) add('the pit range is ' + lo + '–' + hi + u);
      }
      if (s.kind === 'hold' && !last) add('"Hold at" must be the last step (the program stays there)');
      if (s.kind === 'shutdown' && !last) add('"Shut down" ends the program: the steps after it never run');
      if (s.kind === 'notify' && !(s.notify || '').trim()) add('write the notification');
      if ((s.notify || '').includes('"')) add("the notification can't contain double quotes");
      if (s.kind === 'pit' || s.kind === 'notify') s.until.forEach(c => {
        const v = parseFloat(c.value);
        if (TEMP[c.type] && !Number.isFinite(v)) add('a condition needs a temperature');
        if (c.type === 'after' && !(v > 0)) add('a condition needs a time in the step');
        if (c.type === 'at' && !/^\d{1,2}:\d{2}$/.test(c.value || '')) add('a condition needs a clock time');
        if (HELD[c.type] && c.held !== '' && !(parseFloat(c.held) >= 0)) add('"held for" needs minutes');
      });
    });
    return E;
  }

  // ---- the step editor. env: el() container, isF(), unit(), labels() [6 probe names], text() the controller's
  // program text (null = unknown), max() text limit (0 = none), load(text) -> Promise (false = failed), toast(msg).
  const KINDS = [['pit', 'Set pit to'], ['hold', 'Hold at'], ['notify', 'Notify only'], ['shutdown', 'Shut down']];
  const CONDS = [['gte', 'Food probe reaches'], ['lte', 'Food probe drops to'], ['pit', 'Pit reaches'], ['done', 'Probe done'],
    ['after', 'Time in step'], ['at', 'Clock time'], ['stall_start', 'Stall starts'], ['stall_end', 'Stall ends']];
  const h = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const opt = (list, cur) => list.map(([v, l]) => `<option value="${h(v)}"${String(v) === String(cur) ? ' selected' : ''}>${h(l)}</option>`).join('');
  function editor(env) {
    const S = { prog: { name: '', steps: [] }, mode: 'steps', raw: '', note: '', src: null, touched: false, sent: null, userText: false };
    const text = () => S.mode === 'text' ? S.raw : format(S.prog);
    const same = (srv, t) => srv.trim() === t.trim() || (srv.length >= 250 && srv.endsWith('...') && t.trim().startsWith(srv.slice(0, -3).trim()));
    function adopt(t) {
      S.note = ''; S.raw = t;
      if (!t.trim()) { S.prog = { name: '', steps: [] }; S.mode = S.userText ? 'text' : 'steps'; return; }
      if (t.length >= 250 && t.endsWith('...')) { S.mode = 'text'; S.note = 'The controller shows only the start of programs longer than 255 characters.'; return; }
      const r = parse(t, env.isF());
      if (r.prog) { S.prog = r.prog; S.mode = S.userText ? 'text' : 'steps'; return; }
      S.mode = 'text'; S.note = "The step editor can't show this program (" + (r.unsupported || r.error) + '), so it is shown as text.';
    }
    // Follow the controller's program (a preset picked, a load from elsewhere) unless there are edits not loaded yet.
    function sync() {
      const srv = env.text(); if (srv == null) return;
      if (S.sent != null && same(srv, S.sent)) { S.touched = false; S.sent = null; S.src = srv; return; }
      if (S.touched || srv === S.src) return;
      S.src = srv; adopt(srv);
    }
    function stepHTML(s, i, n, f, u, labels) {
      const id = 'pe-s' + i, N = 'Step ' + (i + 1), [lo, hi] = range(f);
      const conds = s.kind === 'pit' || s.kind === 'notify';
      const tempIn = (key, val, label, extra) => `<span class="pe-unit"><input id="${id}-${key}" type="number" inputmode="decimal" data-pe="${key}" data-i="${i}" value="${h(val)}" aria-label="${h(label)}"${extra || ''}><span>${h(u)}</span></span>`;
      const cs = conds ? s.until.map((c, k) => {
        const cid = id + '-c' + k, CN = N + ', condition ' + (k + 1), at = ` data-i="${i}" data-k="${k}"`;
        let v = '';
        if (TEMP[c.type]) v = `<span class="pe-unit"><input id="${cid}-v" type="number" inputmode="decimal" data-pe="cval"${at} value="${h(c.value)}" aria-label="${h(CN + ' temperature')}"><span>${h(u)}</span></span>`;
        else if (c.type === 'after') v = `<span class="pe-unit"><input id="${cid}-v" type="number" inputmode="decimal" min="0" data-pe="cval"${at} value="${h(c.value)}" aria-label="${h(CN + ' time in step')}">
          <select id="${cid}-u" data-pe="cunit"${at} aria-label="${h(CN + ' unit')}">${opt([['h', 'hours'], ['m', 'min']], c.unit)}</select></span>`;
        else if (c.type === 'at') v = `<input id="${cid}-v" type="time" data-pe="cval"${at} value="${h(c.value)}" aria-label="${h(CN + ' clock time')}">`;
        return `<div class="pe-cond"><span class="pe-or">${k ? 'or' : 'until'}</span>
          <select id="${cid}-type" data-pe="ctype"${at} aria-label="${h(CN)}">${opt(CONDS, c.type)}</select>
          ${PROBE[c.type] ? `<select id="${cid}-p" data-pe="cprobe"${at} aria-label="${h(CN + ' probe')}">${opt(labels.map((l, j) => [j + 1, l]), c.probe)}</select>` : ''}${v}
          ${HELD[c.type] ? `<label class="pe-held">held for <input id="${cid}-held" type="number" inputmode="numeric" min="0" data-pe="cheld"${at} value="${h(c.held)}" placeholder="0"> min</label>` : ''}
          <button type="button" class="btn pe-x" data-pe-act="del-cond"${at} aria-label="${h('Remove ' + CN.toLowerCase())}">×</button></div>`;
      }).join('') : '';
      const hint = s.kind === 'hold' ? 'Stays at this temperature until you stop the program.' : s.kind === 'shutdown' ? 'Ends the program.'
        : !s.until.length ? (i === n - 1 ? 'No condition: the program ends here and the pit stays at this temperature.' : 'No condition: moves straight on to the next step.') : '';
      return `<li class="pe-step" role="group" aria-label="${N}">
        <div class="pe-sh"><span class="pe-n" aria-hidden="true">${i + 1}</span>
          <select id="${id}-kind" data-pe="kind" data-i="${i}" aria-label="${N} action">${opt(KINDS, s.kind)}</select>
          ${s.kind === 'pit' || s.kind === 'hold' ? tempIn('temp', s.temp, N + ' pit temperature', ` min="${lo}" max="${hi}" step="${f ? 5 : 1}"`) : ''}
</div>
        ${cs}
        <div class="pe-sf">${conds ? `<button type="button" class="btn pe-add" id="${id}-addc" data-pe-act="add-cond" data-i="${i}">${s.until.length ? '+ or…' : '+ until…'}</button>` : ''}
          <span class="pe-tools"><button type="button" class="btn pe-x" id="${id}-up" data-pe-act="up" data-i="${i}" aria-label="Move ${N.toLowerCase()} up"${i ? '' : ' disabled'}>↑</button><button type="button" class="btn pe-x" id="${id}-dn" data-pe-act="down" data-i="${i}" aria-label="Move ${N.toLowerCase()} down"${i < n - 1 ? '' : ' disabled'}>↓</button><button type="button" class="btn pe-x" data-pe-act="del-step" data-i="${i}" aria-label="Remove ${N.toLowerCase()}">×</button></span></div>
        ${hint ? `<p class="pe-hint">${h(hint)}</p>` : ''}
        <input id="${id}-note" class="pe-note" type="text" data-pe="notify" data-i="${i}" value="${h(s.notify)}" maxlength="120" placeholder="${s.kind === 'notify' ? 'Notification text' : 'Notify when this step starts (optional)'}" aria-label="${N} notification"></li>`;
    }
    function mainHTML() {
      if (S.mode === 'text') {
        return `${S.note ? `<p class="pe-msg">${h(S.note)}</p>` : ''}
          <textarea id="progtext" data-pe="raw" spellcheck="false" aria-label="Program text" placeholder='name: Pork butt; pit 250 until food1 >= 165 for 30m; pit 275 until food1 >= 203; hold 200 notify "Done"'>${h(S.raw)}</textarea>
          <div class="btns"><button type="button" class="btn" id="pe-tosteps" data-pe-act="to-steps">Edit as steps</button></div>`;
      }
      const f = env.isF(), u = env.unit(), labels = env.labels(), P = S.prog.steps;
      return `<div class="pe-name"><label for="pe-name">Name</label><input id="pe-name" type="text" data-pe="name" value="${h(S.prog.name)}" maxlength="40" placeholder="e.g. Pork butt" autocomplete="off"></div>
        ${P.length ? `<ol class="pe-steps">${P.map((s, i) => stepHTML(s, i, P.length, f, u, labels)).join('')}</ol>` : '<p class="pe-hint">No steps yet.</p>'}
        <div class="btns"><button type="button" class="btn" id="pe-addstep" data-pe-act="add-step">+ Add step</button><button type="button" class="btn" id="pe-totext" data-pe-act="to-text">Edit as text</button></div>`;
    }
    function footHTML() {
      const t = text(), max = env.max(), errs = S.mode === 'steps' ? check(S.prog, env.isF()) : [], long = max && t.length > max;
      const ok = t.trim() && !errs.length && !long;
      return `${S.mode === 'steps' && S.prog.steps.length ? `<details class="more pe-prev" data-k="pe-prev"><summary>Program text · ${t.length}${max ? '/' + max : ''} characters</summary><pre class="pe-pre">${h(t)}</pre></details>` : ''}
        ${long ? `<p class="err">Too long for the controller's program field (${t.length}/${max} characters): load long programs from Home Assistant.</p>` : ''}
        ${errs.length ? `<ul class="err pe-errs" role="alert">${errs.map(e => `<li>${h(e)}</li>`).join('')}</ul>` : ''}
        <div class="btns pe-load"><button type="button" class="btn${S.touched && ok ? ' pri' : ''}" id="pe-load" data-pe-act="load"${ok ? '' : ' disabled'}>Load program</button>
          <span class="pe-state">${S.sent != null ? 'Sent to the controller' : S.touched ? 'Edited: load it, then Start' : 'This is the controller\'s program'}</span></div>`;
    }
    function bind(el) {
      el._pe = 1;
      el.addEventListener('click', e => { const b = e.target.closest('[data-pe-act]'); if (b && el.contains(b) && !b.disabled) act(b.dataset.peAct, +b.dataset.i, +b.dataset.k); });
      el.addEventListener('input', e => { const t = e.target; if (t.dataset && t.dataset.pe && t.tagName !== 'SELECT') { set(t); soft(); } });
      el.addEventListener('focusout', () => setTimeout(() => draw(false), 0));  // what was held back while a field had focus
      el.addEventListener('change', e => {
        const t = e.target; if (!t.dataset || !t.dataset.pe) return;
        set(t);
        if (t.tagName === 'SELECT') return draw(true, t.id);
        if (t.dataset.pe === 'temp') {  // keep the pit inside the controller's range
          const s = S.prog.steps[+t.dataset.i], v = parseFloat(t.value), [lo, hi] = range(env.isF());
          if (s && Number.isFinite(v) && (v < lo || v > hi)) { s.temp = t.value = String(Math.min(hi, Math.max(lo, v))); env.toast('The pit range is ' + lo + '–' + hi + env.unit()); }
        }
        soft();
      });
    }
    function set(t) {
      const k = t.dataset.pe, s = S.prog.steps[+t.dataset.i], c = s && s.until[+t.dataset.k], v = t.value;
      S.touched = true; S.sent = null;
      if (k === 'raw') S.raw = v; else if (k === 'name') S.prog.name = v;
      else if (s && k === 'kind') s.kind = v; else if (s && k === 'temp') s.temp = v; else if (s && k === 'notify') s.notify = v;
      else if (c && k === 'ctype') { const cat = x => TEMP[x] ? 'temp' : x; if (cat(c.type) !== cat(v)) c.value = ''; if (v === 'after' && c.type !== 'after') c.unit = 'h'; c.type = v; }
      else if (c && k === 'cprobe') c.probe = +v; else if (c && k === 'cval') c.value = v; else if (c && k === 'cunit') c.unit = v; else if (c && k === 'cheld') c.held = v;
    }
    function act(a, i, k) {
      const P = S.prog.steps;
      if (a === 'load') return load();
      if (a === 'to-text') { S.raw = format(S.prog); S.mode = 'text'; S.userText = true; S.note = ''; return draw(true, 'progtext'); }
      if (a === 'to-steps') {
        const r = S.raw.trim() ? parse(S.raw, env.isF()) : { prog: { name: '', steps: [] } };
        if (!r.prog) { S.note = "The step editor can't show this (" + (r.unsupported || r.error) + '): keep editing it as text.'; return draw(true, 'pe-tosteps'); }
        S.prog = r.prog; S.mode = 'steps'; S.userText = false; S.note = ''; return draw(true, 'pe-totext');
      }
      S.touched = true; S.sent = null;
      if (a === 'add-step') {
        const lastPit = [...P].reverse().find(s => s.kind === 'pit' && s.temp !== '');
        const at = P.length && /hold|shutdown/.test(P[P.length - 1].kind) ? P.length - 1 : P.length;
        P.splice(at, 0, { kind: 'pit', temp: lastPit ? lastPit.temp : env.isF() ? '225' : '107', notify: '', until: [{ type: 'gte', probe: 1, value: '', unit: 'h', held: '' }] });
        return draw(true, 'pe-s' + at + '-temp');
      }
      if (a === 'del-step') { P.splice(i, 1); return draw(true, 'pe-addstep'); }
      if (a === 'up' && i > 0) { [P[i - 1], P[i]] = [P[i], P[i - 1]]; return draw(true, 'pe-s' + (i - 1) + (i - 1 ? '-up' : '-dn')); }
      if (a === 'down' && i < P.length - 1) { [P[i + 1], P[i]] = [P[i], P[i + 1]]; return draw(true, 'pe-s' + (i + 1) + (i + 1 < P.length - 1 ? '-dn' : '-up')); }
      if (a === 'add-cond' && P[i]) { const prev = P[i].until[P[i].until.length - 1]; P[i].until.push({ type: 'gte', probe: prev ? prev.probe : 1, value: '', unit: 'h', held: '' }); return draw(true, 'pe-s' + i + '-c' + (P[i].until.length - 1) + '-type'); }
      if (a === 'del-cond' && P[i]) { P[i].until.splice(k, 1); return draw(true, 'pe-s' + i + '-addc'); }
      draw(true);
    }
    function load() {
      const t = text().trim(), max = env.max();
      if (!t) return env.toast('Add a step first');
      if (S.mode === 'steps' && check(S.prog, env.isF()).length) return env.toast('Fix the program first');
      if (max && t.length > max) return env.toast('Too long for the controller: load it from Home Assistant');
      S.sent = t; S.touched = true;
      return Promise.resolve(env.load(t)).then(ok => { if (ok === false) S.sent = null; else env.toast('Program sent: press Start when you\'re ready'); draw(true); });
    }
    const keepOpen = (el, fn) => { const o = [...el.querySelectorAll('details[data-k]')].filter(d => d.open).map(d => d.dataset.k); fn(); o.forEach(k => { const d = el.querySelector(`details[data-k="${k}"]`); if (d) d.open = true; }); };
    function soft() { const el = env.el(), ft = el && el.querySelector('.pe-foot'); if (ft) keepOpen(ft, () => { ft.innerHTML = footHTML(); }); }
    // Redraw when something changed, never under someone typing; `force` (after a button or menu) keeps focus on `focusId`.
    function draw(force, focusId) {
      const el = env.el(); if (!el) return;
      if (!el._pe) bind(el);
      const html = `<div class="pe-main">${mainHTML()}</div><div class="pe-foot">${footHTML()}</div>`;
      const a = document.activeElement;
      if (!force && (el._h === html || (a && el.contains(a) && /INPUT|TEXTAREA|SELECT/.test(a.tagName)))) return;
      keepOpen(el, () => { el._h = html; el.innerHTML = html; });
      const f = focusId && document.getElementById(focusId);
      if (f && !f.disabled) f.focus({ preventScroll: true });
    }
    return { render() { sync(); draw(false); }, text, state: S, load };
  }
  return { parse, format, check, editor, range };
})();
// ==== END cook program editor (shared block) ====

// Cook program card: status and preset (redrawn live), the step editor (shared block above: its own redraws, so
// edits survive live updates) and the run buttons. Programs load through the "Program" text (255 characters at most).
const progEd = PG.editor({
  el: () => $('progedit'), isF, unit: TU, toast,
  labels: () => [1, 2, 3, 4, 5, 6].map(i => { const pr = str(E('select', 'Food ' + i + ' protein')); return 'Food ' + i + (pr && !/^Auto/i.test(pr) ? ' · ' + pr : ''); }),
  text: () => { const e = E('text', 'Program'); return e ? str(e) : null; },
  max: () => { const e = E('text', 'Program'); return (e && parseInt(e.max_length, 10)) || 255; },
  load: t => post('text', 'Program', 'set', { value: t }),
});
function renderProg() {
  const st = T('Program state') || 'Idle', status = T('Program status'), err = T('Program error'), txt = E('text', 'Program');
  const run = st === 'Running', paused = st === 'Paused', known = !!E('text_sensor', 'Program state');
  const b = (name, label, ok, pri, confirm) => E('button', name) ? `<button class="btn${armed[name] ? ' arm' : pri ? ' pri' : ''}" data-a="press" data-n="${esc(name)}"${confirm ? ' data-confirm="1"' : ''}${known && !ok ? ' disabled' : ''}>${armed[name] ? 'Tap again to ' + label.toLowerCase() : label}</button>` : '';
  if (!$('progedit')) $('prog').innerHTML = '<h3 id="proghead"></h3><div id="progstat"></div><div id="progedit" class="pe"></div><div id="progbtns"></div>';
  put('proghead', `<span>Cook program</span><span class="chip ${run ? 'hot' : paused ? 'warn' : ''}">${esc(st)}</span>`);
  put('progstat', `${status ? `<p style="margin:0 0 6px">${esc(status)}</p>` : ''}${err ? `<p class="err" role="alert">The controller says: ${esc(err)}</p>` : ''}
    ${E('select', 'Program preset') ? `<div class="row"><span>Preset</span>${sel('select', 'Program preset')}</div>` : ''}
    ${txt ? '' : '<p class="note">This controller has no "Program" text to load programs into: load them from Home Assistant.</p>'}`);
  if (txt) progEd.render(); else if ($('progedit').innerHTML) { $('progedit').innerHTML = ''; $('progedit')._h = ''; }
  put('progbtns', `<div class="btns">${b('Start program', 'Start', !run && !paused, !progEd.state.touched)}${b('Pause program', 'Pause', run)}${b('Resume program', 'Resume', paused, true)}${b('Skip program step', 'Skip step', run || paused, false, true)}${b('Stop program', 'Stop', run || paused, false, true)}</div>`);
}

// Grill Wi-Fi setup over Bluetooth (the controller sends what the Char-Griller app would). The password is typed
// here, on the controller's own page: it goes to the controller only (never to Home Assistant) and isn't kept.
function wifiSetup() {
  if (!E('button', 'Grill Wi-Fi: set up')) return '';
  const nets = T('Grill Wi-Fi networks'), ss = E('text', 'Grill Wi-Fi: network name');
  const list = nets && !/^(Scanning|No networks)/.test(nets) ? nets.split(', ').filter(n => n && n !== '…') : [];
  return `<details class="more" data-k="wifi"><summary>Set up the grill's Wi-Fi</summary>
    <p class="note" style="margin-top:4px">Over Bluetooth, like the Char-Griller app (close the app first). 2.4 GHz networks only.</p>
    <div class="btns"><button class="btn" data-a="press" data-n="Grill Wi-Fi: join saved network">Join saved network</button>
      <button class="btn" data-a="press" data-n="Grill Wi-Fi: scan">Scan</button></div>
    ${nets ? `<div class="row"><span>Networks</span><span class="r" style="white-space:normal">${list.length ? list.map(n => `<button class="btn" data-a="wifipick" data-v="${esc(n)}">${esc(n)}</button>`).join(' ') : esc(nets)}</span></div>` : ''}
    <div class="row"><span>Network</span><span class="entry"><input id="wifissid" type="text" autocomplete="off" maxlength="32" value="${esc(str(ss))}" placeholder="name" aria-label="Wi-Fi network name"></span></div>
    <div class="row"><span>Password</span><span class="entry"><input id="wifipass" type="password" autocomplete="new-password" maxlength="63" aria-label="Wi-Fi password">
      <button class="btn pri" data-a="wifijoin">Set up</button></span></div>
    <p class="note">The password goes to the controller and on to the grill; it isn't stored.</p></details>`;
}

// ---------------------------------------------------------------- without Home Assistant: PIN, notifications, place
let geoHits = [];
function renderLocal() {
  renderPlan(); renderShare();
  const L = LOCAL;
  if (!L) { ['lock', 'notif', 'place'].forEach(k => put(k, '')); return; }
  const pw = (id, ph, ac) => `<input id="${id}" type="password" autocomplete="${ac || 'current-password'}" placeholder="${esc(ph)}" aria-label="${esc(ph)}" style="width:150px">`;
  const forgot = '<p class="note">Forgotten it? Hold the controller\'s BOOT button for 10 seconds, or press "Clear the device page PIN" in Home Assistant.</p>';
  if (!L.pin) put('lock', `<h3><span>This page's PIN</span><span class="chip warn">not set</span></h3>
    <p class="note" style="margin-top:0">Anyone on your Wi-Fi can open this page. A PIN stops them changing anything, and it's needed before
      notification or AI keys can be stored. 6+ characters; not 123456 or 111111.</p>
    <div class="row"><span>New PIN</span><span class="entry">${pw('pin1', 'PIN', 'new-password')}</span></div>
    <div class="row"><span>Again</span><span class="entry">${pw('pin2', 'Same PIN', 'new-password')}<button class="btn pri" data-a="pinset">Set PIN</button></span></div>`);
  else if (!L.authed) put('lock', `<h3><span>This page's PIN</span><span class="chip bad">locked</span></h3>
    <p class="note" style="margin-top:0">Readings are open; enter the PIN to change anything from this browser.</p>
    <div class="row"><span>PIN</span><span class="entry">${pw('pinin', 'PIN')}<button class="btn pri" data-a="login">Unlock</button></span></div>
    ${L.locked ? `<p class="note">Too many wrong PINs: try again in ${fmt(L.locked)} s.</p>` : ''}${forgot}`);
  else put('lock', `<h3><span>This page's PIN</span><span class="chip ok">unlocked</span></h3>
    <p class="note" style="margin-top:0">This browser can make changes for 12 hours from its last change.</p>
    <div class="btns"><button class="btn" data-a="logout">Lock now</button></div>
    <details class="more" data-k="chpin"><summary>Change the PIN</summary>
      <div class="row"><span>Current</span><span class="entry">${pw('pin0', 'Current PIN')}</span></div>
      <div class="row"><span>New</span><span class="entry">${pw('pin1', 'New PIN', 'new-password')}</span></div>
      <div class="row"><span>Again</span><span class="entry">${pw('pin2', 'New PIN again', 'new-password')}<button class="btn" data-a="pinset">Change</button></span></div></details>${forgot}`);

  const sec = (k, label, ph) => `<div class="row"><span>${label}</span><span class="entry"><input id="sec-${k}" type="password" autocomplete="off" placeholder="${esc(ph)}" aria-label="${esc(label)}" style="width:160px"><button class="btn" data-a="secret" data-k="${k}">Save</button></span></div>`;
  const svc = (name, on, last) => `<span class="chip ${on ? 'ok' : ''}">${name}${on ? ' ✓' : ''}</span>${last ? ` <span class="muted small">${esc(last)}</span>` : ''}`;
  const routes = [['auto', 'Automatic'], ['ha', 'Only via Home Assistant'], ['direct', 'Only straight to my phone'], ['both', 'Both (you may get two)']];
  put('notif', `<h3><span>Notifications</span>${L.ha ? '<span class="chip ok">Home Assistant connected</span>' : '<span class="chip">no Home Assistant</span>'}</h3>
    <div class="row"><span>Send them</span><select data-c="route" aria-label="Where notifications go">${routes.map(([v, t]) => `<option value="${v}"${L.route === v ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
    <p class="note">${L.route === 'auto' ? 'Automatic: via Home Assistant while it\'s connected, straight to your phone when it isn\'t. ' : ''}Critical alarms (fire out, way too hot) always go straight to your phone too, when a service below is set up.</p>
    <div class="chips" style="margin:6px 0">${svc('ntfy', L.set.ntfy, L.last.ntfy)} ${svc('Pushover', L.set.pushover, L.last.pushover)} ${svc('Telegram', L.set.telegram, L.last.telegram)}</div>
    ${L.authed ? `<details class="more" data-k="ntfy"><summary>ntfy (free app; pick a long random topic)</summary>
        <div class="row"><span>Server</span><span class="entry"><input id="ntfysrv" type="url" value="${esc(L.ntfy_server || 'https://ntfy.sh')}" style="width:160px" aria-label="ntfy server"><button class="btn" data-a="ntfyserver">Save</button></span></div>
        ${sec('ntfy_topic', 'Topic', L.set.ntfy ? 'set · type to replace' : 'e.g. smoker-k3v9x2q7')}
        ${L.set.ntfy ? '<div class="btns"><button class="btn" data-a="secret" data-k="ntfy_topic" data-clear="1">Remove ntfy</button></div>' : ''}</details>
      <details class="more" data-k="po"><summary>Pushover</summary>
        ${sec('pushover_user', 'User key', L.set.pushover ? 'set · type to replace' : 'from pushover.net')}${sec('pushover_token', 'App token', L.set.pushover ? 'set · type to replace' : 'create an app on pushover.net')}
        ${L.set.pushover ? '<div class="btns"><button class="btn" data-a="secret" data-k="pushover_user" data-clear="1">Remove Pushover</button></div>' : ''}</details>
      <details class="more" data-k="tg"><summary>Telegram</summary>
        ${sec('telegram_token', 'Bot token', L.set.telegram ? 'set · type to replace' : 'from @BotFather')}${sec('telegram_chat', 'Chat ID', L.set.telegram ? 'set · type to replace' : 'your chat with the bot')}
        ${L.set.telegram ? '<div class="btns"><button class="btn" data-a="secret" data-k="telegram_token" data-clear="1">Remove Telegram</button></div>' : ''}</details>
      <p class="note">Keys are stored on the controller and can be replaced or removed, never read back.</p>
      <div class="btns"><button class="btn" data-a="testnotify"${L.set.ntfy || L.set.pushover || L.set.telegram ? '' : ' disabled'}>Send a test</button></div>`
    : `<p class="note">${L.pin ? 'Unlock this page (This page\'s PIN, below) to set up ntfy, Pushover or Telegram.' : 'Set a PIN for this page (This page\'s PIN, below) to set up ntfy, Pushover or Telegram.'}</p>`}`);

  put('place', `<h3><span>Weather and time</span>${L.location ? '<span class="chip ok">weather here</span>' : ''}</h3>
    <div class="row"><span>Weather from</span><span class="r">${L.location ? 'Open-Meteo, for your area' + (L.weather_age_min >= 0 ? ' · ' + mins(L.weather_age_min) + ' ago' : '') : L.ha ? 'Home Assistant' : 'nowhere yet'}</span></div>
    ${L.authed ? `${L.location ? `<div class="row"><span>Area</span><span class="r">${fmt(L.lat, 2)}, ${fmt(L.lon, 2)} <button class="btn" data-a="clearplace">Remove</button></span></div>` : ''}
      <div class="row"><span>${L.location ? 'Move to' : 'Your area'}</span><span class="entry"><input id="geoq" type="search" placeholder="Town or postcode" autocomplete="off" style="width:150px" aria-label="Town or postcode"><button class="btn" data-a="geo">Find</button></span></div>
      ${geoHits.map(h => `<div class="row"><span class="small">${esc(h.n)}</span><button class="btn" data-a="place" data-lat="${h.lat}" data-lon="${h.lon}" data-n="${esc(h.n)}">Use</button></div>`).join('')}
      <p class="note">Stored on the controller, rounded to about 1 km, and only sent to Open-Meteo for the forecast. Searching asks Open-Meteo from this phone.</p>
      <div class="row"><span>Time zone<br><span class="muted small">${L.tz ? 'set' : L.ha ? 'from Home Assistant' : 'not set: clock times are UTC'}</span></span><button class="btn" data-a="tz">Use this phone's (${esc((Intl.DateTimeFormat().resolvedOptions().timeZone || '').replace(/_/g, ' '))})</button></div>`
    : `<p class="note">${L.pin ? 'Unlock' : 'Set a PIN for'} this page to set your area (for the weather) and time zone.</p>`}`);
}

// ---------------------------------------------------------------- chart, plan, journal, Open Pitmaster (stage 2)
let chartHours = 6, HIST = null, JOURNAL = { entries: [], share: {} }, COMMUNITY = null;
const TASTE = [['juicy', 'tender', 'dry', 'tough'], ['undercooked', 'just right', 'overcooked'], ['great bark', 'soft bark'],
  ['good smoke', 'too smoky', 'too little smoke'], ['fat rendered', 'fat not rendered']];
const TASTE_GROUPS = ['Texture', 'Doneness', 'Bark', 'Smoke', 'Fat'];
const COLORS = ['var(--pit)', 'var(--muted)', 'var(--food1, #2563eb)', 'var(--food2, #16a34a)', '#a855f7', '#d97706', '#0891b2', '#db2777'];
async function loadHistory() { try { HIST = await local('history?hours=' + chartHours); } catch (e) { /* older firmware */ } drawChart(); }
async function loadJournal() { try { JOURNAL = await local('journal'); } catch (e) { /* older firmware */ } renderJournal(); renderShare(); }
async function loadCommunity() { try { COMMUNITY = await local('community'); } catch (e) { /* offline */ } renderPlan(); }
async function jpost(path, body) { try { JOURNAL = await local('journal/' + path, body); renderJournal(); renderShare(); return true; } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); return false; } }
async function sharePost(path, body) { try { JOURNAL = await local(path, body || {}); renderJournal(); renderShare(); return true; } catch (e) { if (/PIN/.test(e.message)) needPin(); else toast(e.message); return false; } }
const tF = c => c == null ? null : (isF() ? c * 9 / 5 + 32 : c);
const atClock = t => new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
const dayLabel = t => { const d = new Date(t * 1000), now = new Date(); const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  return days === 0 ? 'Today' : days === 1 ? 'Yesterday' : d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }); };

function drawChart() {
  put('range', [3, 6, 12, 24].map(h => `<button aria-pressed="${h === chartHours}" data-a="range" data-h="${h}">${h}h</button>`).join(''));
  const box = $('chart'); if (!box) return;
  if (!HIST || !HIST.series || !HIST.series[0] || !HIST.series[0].length) { box.innerHTML = '<div class="empty" style="padding:4px 0">The chart fills in as the controller records (one point a minute; up to 24 hours, cleared by a restart).</div>'; put('legend', ''); return; }
  const W = box.clientWidth || 600, Hh = 260, L = 40, R = 10, T = 10, B = 24, step = HIST.step_min * 60, now = Date.now() / 1000 - (HIST.age_s || 0);
  const series = HIST.series.map((pts, i) => ({ name: HIST.names[i], color: COLORS[i], dash: i === 1, pts: pts.map((v, k) => [now - (pts.length - 1 - k) * step, v]).filter(p => p[1] != null) })).filter(s => s.pts.length);
  const all = series.flatMap(s => s.pts.map(p => p[1])), t0 = now - (HIST.series[0].length - 1) * step;
  let lo = Math.min(...all), hi = Math.max(...all); const pad = Math.max(10, (hi - lo) * 0.08); lo = Math.floor((lo - pad) / 25) * 25; hi = Math.ceil((hi + pad) / 25) * 25;
  const x = t => L + (W - L - R) * (t - t0) / Math.max(1, now - t0), y = v => T + (Hh - T - B) * (1 - (v - lo) / Math.max(1, hi - lo));
  let g = '';
  for (let v = lo; v <= hi; v += Math.max(25, Math.round((hi - lo) / 5 / 25) * 25)) g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  const hstep = chartHours <= 6 ? 1 : chartHours <= 12 ? 2 : 4;
  for (let t = Math.ceil(t0 / 3600 / hstep) * hstep * 3600; t <= now; t += hstep * 3600) g += `<text x="${x(t)}" y="${Hh - 6}" text-anchor="middle">${new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric' })}</text>`;
  const lines = series.map(s => `<path d="${s.pts.map((p, k) => (k ? 'L' : 'M') + x(p[0]).toFixed(1) + ',' + y(p[1]).toFixed(1)).join('')}" fill="none" stroke="${s.color}" stroke-width="${s.dash ? 1.5 : 2.2}"${s.dash ? ' stroke-dasharray="5 4"' : ''} stroke-linejoin="round"/>`).join('');
  box.innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" width="100%" height="${Hh}" role="img" aria-label="Temperature history" style="font:11px var(--mono, monospace);fill:var(--muted)">${g}${lines}</svg>`;
  put('legend', series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join(''));
}

function renderPlan() {
  const L = LOCAL, P = L && L.plan;
  if (!P) { put('plan', '<p class="note">Planning needs firmware 0.2.29 or later.</p>'); return; }
  const sv = P.serve_by ? new Date(P.serve_by * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '';
  const profiles = [1, 2, 3, 4, 5, 6].map(i => T('Food ' + i + ' protein') || str(E('select', 'Food ' + i + ' protein'))).filter(Boolean);
  const like = COMMUNITY && COMMUNITY.groups ? COMMUNITY.groups.filter(g => profiles.includes(g.cut)).slice(0, 3) : [];
  put('plan', `<h3><span>Plan a cook</span>${P.serve_by ? '<span class="chip ok">planned</span>' : ''}</h3>
    <div class="row"><span>Serve by</span><span class="entry"><input id="servein" type="datetime-local" value="${esc(sv)}" aria-label="Serve by"></span></div>
    <div class="row"><span>Rest</span><span class="entry"><input id="restin" type="number" min="0" max="360" step="5" value="${P.rest_min}" style="width:70px" aria-label="Rest minutes"><span class="muted">min</span></span></div>
    <div class="btns"><button class="btn pri" data-a="plansave">Save</button>${P.serve_by ? '<button class="btn" data-a="planclear">Clear</button>' : ''}</div>
    ${P.serve_by ? row('Light the grill by', P.light_by ? `${atClock(P.light_by)} <span class="muted small">(${P.light_by <= P.now ? 'now' : 'in ' + mins((P.light_by - P.now) / 60)})</span>` : '<span class="muted small">set the cut and weight on a Food card for an estimate</span>') : ''}
    ${P.est_min ? row('Cooking time', '~' + mins(P.est_min) + (P.rest_min ? ' + ' + P.rest_min + ' min rest' : '')) : ''}
    ${P.serve_by ? '<p class="note">You\'ll get a notification when it\'s time to light the grill.</p>' : '<p class="note">Pick when you want to eat: the controller works out when to light the grill from its estimate and reminds you.</p>'}
    ${like.length ? `<h3 style="margin-top:12px"><span>Shared cooks like this</span><span class="muted small">Open Pitmaster · ${fmt(COMMUNITY.cooks)} cooks</span></h3>${like.map(g => `<p class="note" style="margin:4px 0">${esc(g.line)}</p>`).join('')}` : ''}`);
}

const recWords = r => [r.cut, r.weight_lb != null ? r.weight_lb + ' lb' : '', r.pit_f != null ? 'pit ' + r.pit_f + '°F' : '', r.stall_h != null ? 'stall ' + r.stall_h + ' h' : '',
  r.total_h + ' h total', r.wrapped === true ? 'wrapped' : '', r.outside_f != null ? r.outside_f + '–' + (r.outside_f + 5) + '°F outside' : '', r.season, r.rating ? r.rating + '★' : '', (r.tags || []).join(', ')].filter(Boolean).join(' · ');
let journalAll = false;
function renderJournal() {
  const J = JOURNAL, list = J.entries || [], shown = journalAll ? list : list.slice(0, 5), u = TU();
  const sh = J.share || {}, pend = sh.enabled && !sh.auto ? list.find(e => e.share === 'pending' && e.record) : null;
  const ask = pend ? `<div class="sharebox"><b>Share this cook with Open Pitmaster?</b><p class="small muted" style="margin:4px 0">${esc(recWords(pend.record))}</p>
      <div class="btns"><button class="btn pri" data-a="jshare" data-id="${pend.id}">Share it</button><button class="btn" data-a="jdecline" data-id="${pend.id}">Not this one</button></div>
      <details class="more" data-k="exact"><summary>Exactly what's sent</summary><pre class="small" style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(pend.record))}</pre>
      <p class="note">No date or time, place, notes or names; a new random id.</p></details></div>` : '';
  const ent = e => {
    const w = e.weight_kg ? (isF() ? fmt(e.weight_kg * 2.2046, 1) + ' lb' : fmt(e.weight_kg, 1) + ' kg') : '';
    const chip = (c, t) => `<span class="chip ${c}">${t}</span>`;
    return `<div class="je"><div class="row"><span><b>${esc(e.profile || 'Cook')}</b>${w ? ' · ' + w : ''}</span><span class="muted small">${e.ended ? dayLabel(e.ended) : ''}</span></div>
      <div class="chips">${chip('', fmt(e.total_h, 1) + ' h total')}${e.stall_h ? chip('warn', 'stall ' + fmt(e.stall_h, 1) + ' h') : ''}${e.pit_c != null ? chip('hot', 'pit ' + fmt(tF(e.pit_c)) + u) : ''}${e.ambient_c != null ? chip('', 'outside ' + fmt(tF(e.ambient_c)) + u) : ''}${e.wrapped ? chip('', 'wrapped') : ''}${e.share === 'shared' ? chip('ok', 'shared') : e.share === 'sending' ? chip('', 'sharing…') : ''}</div>
      <div class="row"><span class="stars">${[1, 2, 3, 4, 5].map(n => `<button class="${(e.rating || 0) >= n ? 'on' : ''}" data-a="jrate" data-id="${e.id}" data-n="${n}" aria-label="${n} stars">★</button>`).join('')}</span>
        <span>${sh.enabled && e.share === 'declined' ? `<button class="btn" data-a="jshare" data-id="${e.id}">Share</button>` : ''}<button class="btn${armed['del' + e.id] ? ' arm' : ''}" data-a="jdel" data-id="${e.id}">${armed['del' + e.id] ? 'Tap again to remove' : 'Remove'}</button></span></div>
      <details class="more" data-k="t${e.id}"${(e.tags || []).length ? '' : ' open'}><summary>How was it?${(e.tags || []).length ? ' · ' + esc(e.tags.join(', ')) : ''}</summary>
        <div class="taste">${TASTE.map((g, k) => `<span class="grp">${TASTE_GROUPS[k]}</span>` + g.map(t => `<button aria-pressed="${(e.tags || []).includes(t)}" data-a="jtag" data-id="${e.id}" data-t="${t}">${t}</button>`).join('')).join('')}</div></details>
      <div class="row"><span class="entry" style="flex:1"><input id="jn-${e.id}" type="text" maxlength="99" value="${esc(e.notes || '')}" placeholder="Notes (bark, tenderness, what you'd change)" aria-label="Notes" style="flex:1"><button class="btn" data-a="jnote" data-id="${e.id}">Save</button></span></div></div>`;
  };
  put('journal', ask + (list.length ? shown.map(ent).join('') + (list.length > shown.length ? `<div class="btns"><button class="btn" onclick="journalAll=true;renderJournal()">Show all ${list.length}</button></div>` : '')
    : '<div class="empty">No cooks yet. Each finished cook is added here: rate it and tick how it was, and the controller learns from it.</div>'));
}

function renderShare() {
  const sh = JOURNAL.share || {}, L = LOCAL, shared = (JOURNAL.entries || []).filter(e => e.share === 'shared').length;
  if (!L) { put('share', ''); return; }
  const tg = (k, on, label, note) => `<div class="row"><span>${label}${note ? `<br><span class="muted small">${note}</span>` : ''}</span><button class="tg${on ? ' on' : ''}" data-a="sharecfg" data-k="${k}" data-v="${on ? 0 : 1}" role="switch" aria-checked="${on}" aria-label="${esc(label)}"></button></div>`;
  put('share', `<h3><span>Open Pitmaster</span><span class="muted small">anonymous · off unless you turn it on</span></h3>
    <p class="note" style="margin-top:0">Add finished cooks to an open, anonymous dataset that improves everyone's predictions. Only rounded numbers
      and how it turned out: never dates, place, notes or names. If you share from Home Assistant's Smoker page, leave this off (or you'd share each cook twice).</p>
    ${L.authed ? tg('enabled', sh.enabled, 'Share my cooks') + (sh.enabled ? tg('auto', sh.auto, 'Share automatically', 'Once rated (or 12 h after the cook); only cooks from now on') : '')
      : `<p class="note">${L.pin ? 'Unlock' : 'Set a PIN for'} this page to turn sharing on or off.</p>`}
    ${row('Shared from here', fmt(shared))}${COMMUNITY ? row('Open Pitmaster', fmt(COMMUNITY.cooks) + ' shared cooks') : ''}
    <div class="btns"><button class="btn" data-a="sharedl">Download my cooks (anonymised)</button>${shared && L.authed ? `<button class="btn${armed.wd ? ' arm' : ''}" data-a="sharewithdraw">${armed.wd ? 'Tap again to remove them' : 'Remove my shared cooks'}</button>` : ''}</div>`);
}

function renderSetup(u) {
  const wifi = T('Grill Wi-Fi'), ip = E('text', 'Grill IP address');
  put('conn', `<h3><span>Grill link</span><span class="chip ${on(E('binary_sensor', 'Grill connected')) ? 'ok' : 'bad'}">${on(E('binary_sensor', 'Grill connected')) ? (bothLinks() ? 'Wi-Fi + Bluetooth' : esc({ wifi: 'Wi-Fi', bluetooth: 'Bluetooth' }[T('Grill link')] || 'connected')) : 'not connected'}</span></h3>
    ${T('Grill link status') ? `<p class="linkstatus">${esc(T('Grill link status'))}</p>` : ''}
    ${(() => { const w = d => d >= -60 ? 'strong' : d >= -72 ? 'good' : d >= -82 ? 'weak' : 'very weak';
      const b = S('Grill Bluetooth signal'), g = S('Grill Wi-Fi signal');
      return (E('sensor', 'Grill Bluetooth signal') ? row('Bluetooth signal', b != null ? fmt(b) + ' dBm · ' + w(b) : 'no signal') : '') +
        (E('sensor', 'Grill Wi-Fi signal') ? row('Grill\'s Wi-Fi signal', (g != null ? fmt(g) + ' dBm · ' + w(g) : 'not reported') +
          (E('button', 'Grill Wi-Fi: join saved network') ? ' <button class="btn" data-a="press" data-n="Grill Wi-Fi: join saved network">Check</button>' : '')) : ''); })()}
    ${tog(BLE(), 'Control over Bluetooth', 'Sends pit and food targets over Bluetooth when the grill isn\'t on Wi-Fi.')}
    ${tog('Bridge enabled', 'Bridge enabled', 'Turn off while you use the Char-Griller app: the grill takes one connection.')}
    ${tog('Alerts enabled', 'Alerts')}
    ${ip ? `<div class="row"><span>Grill IP address</span><span class="entry"><input id="ipin" type="text" inputmode="decimal" autocomplete="off" value="${esc(str(ip))}" placeholder="automatic" style="width:140px" aria-label="Grill IP address"><button class="btn" data-a="ip">Save</button></span></div>` : ''}
    ${E('text_sensor', 'Grill Wi-Fi') ? row('Grill\'s Wi-Fi', esc(wifi && wifi !== 'unknown' ? wifi : 'not reported yet')) : ''}
    ${wifiSetup()}`);
  const h5 = E('binary_sensor', 'H5198 connected'), rssi = S('H5198 signal');
  let rows = '';
  for (let i = 1; i <= 6; i++) {
    const L = 'Food ' + i, e = E('select', L + ' probe'); if (!e) continue;
    const t = S(L + ' temperature');
    rows += `<div class="row"><span>${esc(L)} <span class="muted small">${t != null ? fmt(t) + esc(u) : 'no reading'}</span></span><span>${/^Wired/.test(str(e)) ? EXP('Wired probes need the ADS1115 add-on and calibrating against a thermometer you trust.') + ' ' : ''}${sel('select', L + ' probe')}</span></div>`;
  }
  put('sources', `<h3>Probe sources</h3>${rows || '<p class="note" style="margin-top:0">This controller has fixed probes.</p>'}
    ${h5 ? row('H5198 thermometer', on(h5) ? 'receiving' + (rssi != null ? ' · ' + fmt(rssi) + ' dBm' : '') : 'not heard') + `<p class="note">${EXP('Direct H5198 readings follow Home Assistant\'s Govee decoder but haven\'t been checked against its display on a real cook yet.')} "Home Assistant" sources need Home Assistant running; the rest work without it.</p>` : ''}`);
  const ver = T('Firmware version'), rel = T('Release'), sig = S('Wi-Fi signal'), up = S('Uptime');
  const dur = s => { const m = Math.floor(s / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
    return d ? `${d} d ${h % 24} h` : h ? `${h} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`; };
  put('dev', `<h3>This controller</h3>${rel ? row('Release', esc(rel)) : ''}${ver ? row('Built with', 'ESPHome ' + esc(String(ver).split(' ')[0])) : ''}${sig != null ? row('Its Wi-Fi <span class="muted small">(to your router, not the grill)</span>', fmt(sig) + ' dBm') : ''}${up != null ? row('Running for', dur(up)) : ''}
    ${row('Cooks learned', fmt(S('Cooks learned')))}
    ${E('button', 'Restart') ? `<div class="row"><span>Restart the controller<br><span class="muted small">Settings and learned cooks are kept; back in about 20 s.</span></span>
      <button class="btn${armed['Restart'] ? ' arm' : ''}" data-a="press" data-n="Restart" data-confirm="1">${armed['Restart'] ? 'Tap again to restart' : 'Restart'}</button></div>` : ''}
    <p class="note"><a href="?classic">Full device view</a>: ESPHome's standard page with every entity and the logs (loads from the internet).</p>`);
  put('foot', `<span>${esc(cfg.title || 'Smoker')}${T('Release') ? ' ' + esc(T('Release')) : ''} · served by the controller, works without Home Assistant</span><span>${Object.keys(ents).length} entities</span>`);
}

// Run last: everything above (let/const) must be initialised first.
if (Q.has('classic')) {
  // Stock page: drop our stylesheet and load ESPHome's app into the <esp-app> the index already has.
  const css = doc.querySelector('link[href="/0.css"]'); if (css) css.remove();
  const s = doc.createElement('script'); s.src = CLASSIC;
  s.onerror = () => { doc.body.insertAdjacentHTML('afterbegin', '<p style="font:15px system-ui;padding:16px">The full device view is ESPHome\'s standard page, loaded from oi.esphome.io: this phone needs internet access for it. <a href="./">Back to the smoker page</a></p>'); };
  doc.body.appendChild(s);
} else {
  start();
}
