/* Shared helpers for the Smoker page (from the home-dashboards project's live_common.js). */
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const H = () => window.hdHA;
const S = eid => { const h = H(); return h ? h.state(eid) : null; };
const val = eid => { const s = S(eid); return s && s.state !== 'unavailable' && s.state !== 'unknown' ? s.state : null; };
const num = eid => { const v = parseFloat(val(eid)); return isFinite(v) ? v : null; };
const fname = eid => { const s = S(eid); return (s && s.attributes && s.attributes.friendly_name) || eid; };
const byName = (name, doms) => { const h = H(); return h ? h.find(name, doms) : null; };
function ago(ts) {
  if (!ts) return '–'; const t = typeof ts === 'number' ? ts : Date.parse(ts); if (!isFinite(t)) return '–';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return 'just now'; if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 86400) return Math.round(s / 3600) + ' h ago';
  // older than a day: "yesterday 9:14 am", "Tue 9:14 am" within the week, then the date
  const d = new Date(t), now = new Date(), day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(now) - day(d)) / 86400e3), hm = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  if (days <= 1) return 'yesterday ' + hm;
  if (days < 7) return d.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' + hm;
  return d.toLocaleDateString('en-US', d.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
}
function until(ts) { const t = Date.parse(ts); if (!isFinite(t)) return null; const m = Math.round((t - Date.now()) / 60000); return m <= 0 ? 'any minute' : m < 90 ? m + ' min' : Math.round(m / 6) / 10 + ' h'; }
const clock = t => new Date(t).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const dayLabel = t => new Date(t).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
// wait for Home Assistant, then call fn now and on every state change (debounced by the shim)
function live(fn, every) {
  let started = false;
  const go = () => { try { fn(); } catch (e) { console.error(e); } };
  (function wait(n) {
    if (H() && H().live()) { started = true; $('lstatus') && ($('lstatus').textContent = 'Live from Home Assistant'); $('ldot') && $('ldot').classList.add('on');
      go(); H().subscribe(go); setInterval(go, every || 30000); return; }
    if (n > 40) { $('lstatus') && ($('lstatus').textContent = 'This page only works inside Home Assistant (open it from the Smoker sidebar entry).'); $('ldot') && $('ldot').classList.add('off'); return; }
    setTimeout(() => wait(n + 1), 300);
  })(0);
}
// state history for some entities over the last `hours` hours: {eid: [{s, t(ms)}...]} oldest first
async function hist(ids, hours, attrs) {
  const start = new Date(Date.now() - hours * 3600e3).toISOString();
  const r = await H().ws({ type: 'history/history_during_period', start_time: start, entity_ids: ids, minimal_response: !attrs,
                           no_attributes: !attrs, significant_changes_only: false });
  const out = {};
  Object.entries(r || {}).forEach(([eid, L]) => { out[eid] = L.map(p => ({ s: p.s, a: p.a, t: Math.round((p.lu || p.lc) * 1000) })); });
  return out;
}
// periods where `test(state)` was true, clipped to [t0, now]: [[start, end], ...]
function spans(L, test, t0) {
  const out = []; let open = null; const now = Date.now();
  (L || []).forEach(p => { const on = test(p.s); if (on && open == null) open = Math.max(p.t, t0); if (!on && open != null) { out.push([open, p.t]); open = null; } });
  if (open != null) out.push([open, now]); return out.filter(x => x[1] > t0);
}
const dur = ms => { const m = Math.round(ms / 60000); return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : ''); };
