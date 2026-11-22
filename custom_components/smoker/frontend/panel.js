// Smoker panel: loads the management page (fetched with the user's own login) into a same-origin frame and
// shares Home Assistant's live `hass` object with it (the page's shim reads it through window.parent).
class SmokerPanel extends HTMLElement {
  constructor() {
    super();
    this._root = this.attachShadow({ mode: 'open' });
    this._root.innerHTML = `
      <style>
        :host{display:flex;flex-direction:column;height:100vh;height:100dvh;background:var(--primary-background-color,#f2f4f6)}
        .bar{display:none;align-items:center;gap:4px;height:56px;padding:0 4px;background:var(--app-header-background-color,var(--primary-color));
             color:var(--app-header-text-color,#fff);font:500 20px var(--paper-font-common-base_-_font-family,Roboto,sans-serif);flex:none}
        :host([narrow]) .bar{display:flex}
        iframe{border:0;width:100%;flex:1 1 0;min-height:0;display:block;background:var(--primary-background-color,#f2f4f6)}
      </style>
      <div class="bar"><ha-menu-button></ha-menu-button><span>Smoker</span></div>
      <iframe title="Smoker"></iframe>`;
    this._frame = this._root.querySelector('iframe');
    this._loaded = false;
  }
  set hass(h) {
    this._hass = h;
    window.__smHass = h;
    const mb = this._root.querySelector('ha-menu-button'); if (mb) { mb.hass = h; mb.narrow = this._narrow; }
    try { const w = this._frame.contentWindow; if (w && w.__smOnHass) w.__smOnHass(h); } catch (e) { /* frame not ready */ }
    if (!this._loaded) this._load();
  }
  get hass() { return this._hass; }
  set narrow(n) { this._narrow = n; this.toggleAttribute('narrow', !!n); const mb = this._root.querySelector('ha-menu-button'); if (mb) mb.narrow = n; }
  set panel(p) { this._panel = p; }
  async _load() {
    this._loaded = true;
    const h = this._hass, path = '/api/smoker/page';
    try {
      // Home Assistant's own authenticated fetch: the page never reads the login token itself.
      const r = await h.fetchWithAuth(path);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      this._frame.srcdoc = await r.text();
    } catch (e) {
      this._loaded = false;
      const msg = String((e && e.message) || e).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
      this._frame.srcdoc = '<p style="font:15px sans-serif;padding:24px">Couldn\'t load Smoker: ' + msg + '</p>';
    }
  }
}
customElements.define('smoker-panel', SmokerPanel);
