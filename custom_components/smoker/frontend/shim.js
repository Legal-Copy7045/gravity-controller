/* Smoker live-data shim (cut down from the home-dashboards / MagicbHAnds shim.js).
   The panel (panel.js) hands this frame the user's live `hass` object; this gives the page window.hdHA: states,
   history and a deliberately small set of controls (the smoker's own settings and actions). */
(function () {
  'use strict';
  function getHass() { try { return window.parent && window.parent !== window ? window.parent.__smHass : null; } catch (e) { return null; } }
  function lc(s) { return String(s || '').replace(/[‘’]/g, "'").toLowerCase().trim(); }
  var subs = [], spend = null;
  window.__smOnHass = function () {
    if (spend || !subs.length) return;
    spend = setTimeout(function () { spend = null; subs.forEach(function (cb) { try { cb(); } catch (e) { console.error('[smoker] update failed', e); } }); }, 150);
  };
  // Entity controls the page may use, and only on smoker entities (ids containing "smoker").
  var CTRL = { number: ['set_value'], select: ['select_option'], switch: ['turn_on', 'turn_off', 'toggle'], button: ['press'],
               text: ['set_value'], input_datetime: ['set_datetime'], input_number: ['set_value'], input_text: ['set_value'],
               input_boolean: ['turn_on', 'turn_off', 'toggle'], timer: ['start', 'cancel'] };
  var NOPRESS = /clear_cook_history|factory|safe_mode/;   // buttons the page may not press
  // Whole-integration actions: the controller's ESPHome actions and the package's scripts.
  var SVC = { esphome: ['gravity980_load_program', 'gravity980_start_program', 'gravity980_pause_program', 'gravity980_resume_program',
                        'gravity980_skip_step', 'gravity980_stop_program', 'gravity980_set_pit_target'],
              script: ['smoker_plan_cook', 'smoker_ai_advise'] };
  var idxFor = null, idx = {};
  function nameIndex(h) {
    if (idxFor === h.states) return idx;
    idx = {}; idxFor = h.states;
    for (var eid in h.states) { var k = lc((h.states[eid].attributes || {}).friendly_name); (idx[k] = idx[k] || []).push(eid); }
    return idx;
  }
  window.hdHA = {
    live: function () { var h = getHass(); return !!(h && h.states && h.callService); },
    state: function (eid) { var h = getHass(); return (h && h.states && h.states[eid]) || null; },
    find: function (name, doms) {
      var h = getHass(); if (!h || !h.states) return null;
      var best = null, bs = -1;
      (nameIndex(h)[lc(name)] || []).forEach(function (eid) {
        var di = doms ? doms.indexOf(eid.split('.')[0]) : 0; if (di < 0) return;
        var sc = (h.states[eid].state !== 'unavailable' ? 100 : 0) + (doms ? doms.length - di : 0);
        if (sc > bs) { bs = sc; best = eid; }
      });
      return best;
    },
    call: function (domain, service, eid, data) {
      var h = getHass(); if (!h || !h.callService) return Promise.reject(new Error('Home Assistant is not connected'));
      if (String(eid).split('.')[0] !== domain || !CTRL[domain] || CTRL[domain].indexOf(service) < 0) return Promise.reject(new Error('not allowed: ' + domain + '.' + service));
      if (String(eid).indexOf('smoker') < 0) return Promise.reject(new Error('not a smoker entity: ' + eid));
      if (domain === 'button' && NOPRESS.test(eid)) return Promise.reject(new Error('not allowed from this page: ' + eid));
      var d = { entity_id: eid }; for (var k in (data || {})) d[k] = data[k];
      return h.callService(domain, service, d);
    },
    service: function (domain, service, data, resp) {
      var h = getHass(); if (!h || !h.callWS) return Promise.reject(new Error('Home Assistant is not connected'));
      if (!SVC[domain] || SVC[domain].indexOf(service) < 0) return Promise.reject(new Error('not allowed: ' + domain + '.' + service));
      return h.callWS({ type: 'call_service', domain: domain, service: service, service_data: data || {}, return_response: !!resp })
        .then(function (r) { return resp ? (r && r.response) : r; });
    },
    subscribe: function (cb) { subs.push(cb); return function () { subs = subs.filter(function (x) { return x !== cb; }); }; },
    all: function () { var h = getHass(); return (h && h.states) || {}; },
    // history and logbook, read-only
    ws: function (msg) {
      var h = getHass(); if (!h || !h.callWS) return Promise.reject(new Error('Home Assistant is not connected'));
      var ok = ['history/history_during_period', 'logbook/get_events'];
      if (!msg || ok.indexOf(msg.type) < 0) return Promise.reject(new Error('not allowed: ' + (msg && msg.type)));
      return h.callWS(msg);
    }
  };
})();
