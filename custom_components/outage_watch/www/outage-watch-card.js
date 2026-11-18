const TAG = "outage-watch-card";
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[c]);
const icons = (name) => `<ha-icon icon="mdi:${escape(name)}"></ha-icon>`;
const timestamp = (value) => value ? new Date(value * 1000).toLocaleTimeString([], {hour:"numeric", minute:"2-digit"}) : "—";
const labels = {
  provider_outage: "Provider outage", unreachable: "Unreachable",
  provider_degraded: "Possible problems", slow: "Slow response",
  intermittent: "Intermittent", blocked: "Check blocked", internet_down: "Unknown",
};
const rank = {outage: 0, possible_problems: 1, unknown: 2, operational: 3};
function label(service) {
  return labels[service.reason] || (service.status === "operational"
    ? (service.maintenance ? "Maintenance" : service.signal === "Checks only" || !service.feed_fresh ? "Reachable" : "Operational")
    : "Unknown");
}

function graph(service, detailed = false) {
  const rows = service.history || [];
  const successful = rows.filter((row) => row[1] === "ok");
  if (!successful.length) return `<div class="no-chart">${service.signal === "Feed only" ? "Provider feed only" : "No response time history yet"}</div>`;
  const max = Math.max(50, (service.baseline || 0) * 1.2, ...successful.map((row) => row[2])) * 1.04;
  const now = Date.now() / 1000, height = detailed ? 120 : 26;
  let path = "", gap = true;
  for (const [time, state, ms] of rows) {
    if (state !== "ok") { gap = true; continue; }
    const x = Math.max(0, Math.min(320, 320 * (time - now + 86400) / 86400));
    const y = height - 2 - (height - 4) * ms / max;
    path += `${gap ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    gap = false;
  }
  const baseline = height - 2 - (height - 4) * service.baseline / max;
  return `<svg class="chart" viewBox="0 0 320 ${height}" preserveAspectRatio="none" role="img" aria-label="Response time over 24 hours">
      ${detailed ? [0, 1, 2, 3, 4].map((i) => `<path class="gridline" d="M${i * 80} 0v${height} M0 ${i * height / 4}h320"/>`).join("") : ""}
      ${detailed && service.baseline != null ? `<path class="baseline" d="M0 ${baseline}h320"/>` : ""}
      <path class="trace" d="${path}"/></svg>
      ${detailed ? '<div class="axis"><span>24h ago</span><span>12h ago</span><span>Now</span></div>' : ""}`;
}

const SPEED_SENSORS = [
  {key:"download", label:"Download", arrow:"↓", unit:"Mbit/s"},
  {key:"upload", label:"Upload", arrow:"↑", unit:"Mbit/s"},
  {key:"ping", label:"Ping", arrow:"↔", unit:"ms"},
];
const SPEED_WINDOW = 24 * 60 * 60 * 1000;

function numeric(value) {
  return value != null && String(value).trim() !== "" && Number.isFinite(Number(value))
    ? Number(value) : null;
}

function speedGraph(history, series) {
  const end = Date.now(), start = end - SPEED_WINDOW;
  const lines = series.filter(({key}) => key !== "ping").map(({key, id}) => ({
    key,
    points: (history[id] || []).map((row) => [
      typeof row.lu === "number" ? row.lu * 1000 : Date.parse(row.last_updated || row.last_changed),
      numeric(row.s ?? row.state),
    ]).filter(([time]) => Number.isFinite(time)),
  }));
  const values = lines.flatMap(({points}) => points.map(([,value]) => value).filter((v) => v !== null));
  if (!values.length) return '<span class="speed-empty">No 24h history</span>';
  const maximum = Math.max(1, ...values);
  function marks(points) {
    let path = "", dot = "", previous = null;
    for (const [time, value] of points) {
      if (value === null) { previous = null; continue; }
      const x = (2 + 92 * Math.max(0, Math.min(1, (time - start) / SPEED_WINDOW))).toFixed(1);
      const y = (22 - 19 * value / maximum).toFixed(1);
      path += previous === null ? `M${x},${y} ` : `H${x} V${y} `;
      dot = `<circle cx="${x}" cy="${y}" r="1.6"/>`;
      previous = value;
    }
    return `<path d="${path}"/>${dot}`;
  }
  return `<svg class="speed-chart" viewBox="0 0 96 24" role="img" aria-label="Download and upload speeds over the last 24 hours">
    <path class="speed-grid" d="M2 12h92 M2 22h92 M25 2v20 M48 2v20 M71 2v20"/>
    ${lines.map(({key,points}) => `<g class="${key}">${marks(points)}</g>`).join("")}
  </svg>`;
}

const THEMES = {
  steel: ["Brushed Steel", "The original industrial console", "#292c30", "#737a85", "#ad9aff"],
  relay: ["Amber Relay", "Vintage instruments, amber displays", "#24291f", "#c5bda0", "#ffbd5d"],
  neon: ["Neon Grid", "Cyan wireframes and magenta accents", "#070d20", "#28deef", "#fd86e6"],
  abyss: ["Midnight Drift", "Soft blue glow and rounded panels", "#0b1022", "#626bd2", "#77f1ff"],
  tide: ["Aqua Current", "Layered teal and luminous glass", "#0b384b", "#47cddf", "#7dffde"],
  appearance: ["Follow Appearance", "Use your shared palette, font and text size", "#26382d", "#a6c48a", "#f2f5eb"],
};
const THEME_KEY = "outage-watch.theme";
const validTheme = (value) => Object.hasOwn(THEMES, value);

class OutageWatchCard extends HTMLElement {
  static getStubConfig() { return {}; }
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this.theme = "steel";
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (validTheme(saved)) this.theme = saved;
    } catch { /* Theme selection still works without storage. */ }
    this.appearanceReady = () => this.syncAppearance();
    this.shadowRoot.addEventListener("click", (event) => this.handle(event));
    this.shadowRoot.addEventListener("submit", (event) => this.submit(event));
    this.shadowRoot.addEventListener("input", (event) => {
      if (event.target.id === "search") this.filterCatalog(event.target.value);
    });
  }
  setConfig(config) { this.config = config; this.render(); }
  set hass(value) {
    const first = !this._hass;
    this._hass = value;
    this.syncAppearance();
    if (first && this.isConnected) this.refresh();
  }
  getGridOptions() { return {columns: "full", rows: "auto", min_columns: 6}; }
  getCardSize() { return 10; }
  connectedCallback() {
    window.addEventListener("yanke-appearance-ready", this.appearanceReady);
    this.syncAppearance();
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 15000);
  }
  disconnectedCallback() {
    clearInterval(this.timer);
    window.removeEventListener("yanke-appearance-ready", this.appearanceReady);
  }

  syncAppearance() {
    if (this.theme === "appearance" && this._hass) {
      const shell = this.shadowRoot.querySelector('[data-theme="appearance"]');
      if (shell) window.YankeAppearance?.apply(shell, this._hass);
    }
  }

  chooseTheme(theme) {
    if (!validTheme(theme)) return;
    this.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* Keep the in-memory choice. */ }
    this.shadowRoot.querySelector("dialog")?.close();
    this.syncAppearance();
    this.render();
    this.shadowRoot.querySelector('[data-action="themes"]')?.focus();
  }

  get speedSeries() {
    return SPEED_SENSORS.map((sensor) => ({
      ...sensor, id: this.config?.[`speedtest_${sensor.key}_entity`] || `sensor.speedtest_${sensor.key}`,
    })).filter(({id}) => this._hass?.states?.[id]);
  }

  async refreshSpeedHistory() {
    const ids = this.speedSeries.filter(({key}) => key !== "ping").map(({id}) => id);
    const key = ids.join("|");
    const now = Date.now();
    if (!ids.length || this.speedLoading ||
        (this.speedHistoryKey === key && now < this.speedHistoryDue)) return;
    this.speedLoading = true;
    this.speedHistoryKey = key;
    this.speedHistoryDue = now + 5 * 60 * 1000;
    try {
      const history = await this._hass.callWS({
        type:"history/history_during_period", entity_ids:ids,
        start_time:new Date(now - SPEED_WINDOW).toISOString(), end_time:new Date(now).toISOString(),
        minimal_response:true, no_attributes:true,
      });
      this.speedHistory = history || {};
    } catch {
      this.speedHistory = {};
    } finally {
      this.speedLoading = false;
      if (this.isConnected && !this.adding) this.render();
    }
  }

  async runSpeedtest() {
    if (this.speedRunning || !this._hass?.user?.is_admin) return;
    const download = this.speedSeries.find(({key}) => key === "download");
    if (!download) return;
    const before = this._hass.states[download.id];
    const oldReport = before.last_reported || before.last_updated;
    this.speedRunning = true;
    this.speedMessage = "Running Speedtest…";
    this.render();
    try {
      // Updating one sensor refreshes the integration's shared results.
      await this._hass.callService("homeassistant", "update_entity", {entity_id:download.id});
      const deadline = Date.now() + 10000;
      let fresh = false;
      while (this.isConnected && Date.now() < deadline) {
        const state = this._hass.states[download.id];
        if (!state || numeric(state.state) === null) break;
        if ((state.last_reported || state.last_updated) !== oldReport) {
          fresh = true;
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      this.speedMessage = fresh ? "Speedtest updated" : "No new Speedtest reading";
      // Give Recorder time to commit the readings before querying history again.
      this.speedHistoryDue = Date.now() + 10000;
    } catch {
      this.speedMessage = "Speedtest could not run";
    } finally {
      this.speedRunning = false;
      if (this.isConnected && !this.adding) this.render();
    }
  }

  speedHeader() {
    const series = this.speedSeries;
    if (!series.length) return "";
    const latest = series.map(({id}) => Date.parse(this._hass.states[id].last_updated)).filter(Number.isFinite);
    const last = latest.length ? new Date(Math.max(...latest)).toLocaleString() : "";
    const canRun = this._hass.user?.is_admin && series.some(({key}) => key === "download");
    const action = canRun ? `<div class="speed-action">
      <button type="button" data-action="speedtest" ${this.speedRunning ? "disabled" : ""}>${this.speedRunning ? "Testing…" : "Run test"}</button>
      <span role="status" class="speed-message" title="${escape(this.speedMessage)}">${escape(this.speedMessage)}</span>
    </div>` : "";
    return `<div class="speed-panel" title="${escape(last ? `Speedtest updated ${last}` : "Most recent Speedtest readings")}">
      <div class="speed-trend">${this.speedLoading && !this.speedHistory ? '<span class="speed-empty">Loading history</span>' : speedGraph(this.speedHistory || {}, series)}<span class="speed-caption">Speedtest · 24h</span></div>
      <div class="speed-values">${series.map(({id,key,label,arrow,unit}) => {
        const sensor = this._hass.states[id];
        const reading = numeric(sensor.state);
        const value = reading === null ? "—" : reading.toLocaleString(undefined, {maximumFractionDigits:1});
        return `<span class="${key}" aria-label="${escape(`${label} ${value} ${unit}`)}"><b>${arrow} ${escape(value)}</b> ${escape(sensor.attributes?.unit_of_measurement || unit)}</span>`;
      }).join("")}</div>${action}
    </div>`;
  }

  async refresh() {
    if (!this._hass || this.loading) return;
    this.loading = true;
    void this.refreshSpeedHistory();
    try {
      this.data = await this._hass.callWS({type: "outage_watch/dashboard"});
      this.loadError = "";
    } catch (error) {
      this.loadError = error.message || "Could not load Outage Map.";
    } finally {
      this.loading = false;
    }
    if (!this.adding) this.render();
  }

  async change(action, data) {
    this.error = "";
    try {
      await this._hass.callService("outage_watch", action, data);
      this.adding = false;
      this.confirmRemove = false;
      await this.refresh();
    } catch (error) {
      this.error = error.message || "Could not save the change.";
    }
    this.render();
  }

  handle(event) {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const {action, id} = button.dataset;
    if (action === "themes") {
      const dialog = this.shadowRoot.querySelector("dialog");
      dialog.showModal();
      dialog.querySelector('[aria-pressed="true"]')?.focus();
      return;
    }
    if (action === "close-themes") return this.shadowRoot.querySelector("dialog").close();
    if (action === "choose-theme") return this.chooseTheme(id);
    if (action === "speedtest") return this.runSpeedtest();
    const service = this.activeService;
    this.error = "";
    if (action === "track") return this.change("add_service", {catalog_id: id});
    if (action === "alerts") return this.change("set_alerts", {service_id: service.id, enabled: !service.alerts});
    if (action === "remove") return this.change("remove_service", {service_id: service.id});
    if (action === "select" || action === "close") {
      this.selected = id || null;
      this.confirmRemove = false;
    }
    if (action === "confirm" || action === "cancel-remove") this.confirmRemove = action === "confirm";
    if (action === "add" || action === "cancel") this.adding = action === "add";
    this.render();
    if (this.adding) this.shadowRoot.querySelector("#search")?.focus();
    else if (action === "select") this.shadowRoot.querySelector('[data-action="close"]')?.focus();
  }

  submit(event) {
    event.preventDefault();
    const data = new FormData(event.target);
    this.change("add_service", {name: data.get("name"), url: data.get("url")});
  }

  filterCatalog(query) {
    for (const element of this.shadowRoot.querySelectorAll("[data-search]")) {
      element.hidden = !element.dataset.search.toLowerCase().includes(query.trim().toLowerCase());
    }
  }

  render() {
    if (this.shadowRoot.querySelector("dialog[open]")) return;
    const {services = [], catalog = [], connected, can_manage, notify_configured} = this.data || {};
    const ordered = [...services].sort((a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name));
    const selected = this.selected === undefined ? ordered[0] : services.find((item) => item.id === this.selected);
    this.activeService = selected;
    const incident = ordered.find((item) => item.reason === "provider_outage");
    const counts = [["outage", "Outages"], ["possible_problems", "Possible problems"], ["operational", "Healthy"], ["unknown", "Unknown"]];
    const link = (url, title) => /^https:\/\//i.test(url || "") ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${title} ↗</a>` : "";
    const connection = this.data && !("connected" in this.data) ? "" : `<span class="connection"><span class="dot ${connected !== true ? "uncertain" : ""}">●</span>${connected === true ? "Home internet connected" : connected === false ? "Connectivity uncertain" : can_manage && !services.length && this.data ? "Connectivity checks paused" : "Checking connectivity"}</span>`;
    this.shadowRoot.innerHTML = `<style>
      :host {
        display:block;
        font:inherit;
        --ink:#f2f2f3;
        --muted:#c1c5c9;
        --line:#62676c;
        --blue:#a4cfff;
        --violet:#ad9aff;
        --good:#70f0c9;
        --warn:#ffcf87;
        --bad:#ffacac;
      }
      *, *::before, *::after {box-sizing:border-box}
      [hidden] {display:none!important}
      .shell {
        container-type:inline-size;
        color:var(--ink);
        padding:clamp(16px,3vw,38px);
        border:2px solid #72777b;
        border-radius:24px;
        background:
          repeating-linear-gradient(0deg,#fff0 0 2px,#ffffff06 3px,#0002 4px),
          radial-gradient(ellipse at 45% 0%,#454950,#272a2f 72%);
        box-shadow:inset 0 0 0 5px #121416,inset 0 0 16px 7px #0009,0 8px 20px #0008;
      }
      header,.row,.actions,.axis {
        display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
      }
      h1,h2,h3,p {margin:0}
      h1,h2,.identity {text-shadow:0 2px 2px #000}
      h1 {font-size:clamp(34px,5vw,62px);font-weight:760;letter-spacing:-.045em;line-height:1.08}
      h2 {font-size:clamp(20px,2.3cqw,29px)}
      h3 {font-size:15px}
      header p {color:#a8d4e5;font-size:clamp(15px,2cqw,21px);margin-top:7px}
      .muted,.axis,.no-chart {color:var(--muted);font-size:13px}
      button,input,a {font:inherit}
      button,a {cursor:pointer;color:inherit}
      button:disabled {cursor:default;opacity:.6}
      button,a {
        border:1px solid #707579;border-radius:8px;padding:8px 12px;
        background:linear-gradient(#3d4247,#202326);
        box-shadow:inset 0 1px 1px #ffffff31,0 2px 4px #0008;
      }
      button:hover:not(:disabled),a:hover {border-color:var(--blue)}
      button:focus-visible,a:focus-visible,input:focus-visible {outline:2px solid var(--blue);outline-offset:3px}
      .primary {
        padding:11px 18px;border:2px solid #758598;border-radius:999px;
        color:#e2eeff;font-weight:700;background:linear-gradient(#3b5a80,#1a2d49);
        box-shadow:inset 0 0 0 2px #1c293e,0 0 15px #579bfd45,0 4px 7px #000b;
      }
      .summary {display:flex;flex-wrap:wrap;gap:10px;margin:clamp(18px,3cqw,30px) 0 18px}
      .count,.connection {
        display:inline-flex;align-items:center;gap:7px;
        border:1px solid #747a80;border-radius:9px;padding:8px 12px;
        color:#e4e5e7;font-size:clamp(12px,1.5cqw,16px);
        background:linear-gradient(140deg,#ffffff22 0%,#ffffff09 48%,transparent 49%),linear-gradient(#16191d,#2c3035);
        box-shadow:inset 0 0 0 2px #101214,inset 0 -3px 6px #ffffff15,0 3px 6px #000a;
      }
      .count b {color:#9ad8ff;text-shadow:0 0 8px currentColor;font:700 1.35em ui-monospace,monospace}
      .count[data-state="outage"] b {color:var(--bad)}
      .count[data-state="possible_problems"] b,.count[data-state="unknown"] b {color:var(--warn)}
      .count[data-state="operational"] b {color:var(--good)}
      .connection {margin-left:auto;background:#1b1e21;box-shadow:inset 0 2px 5px #0009}
      .header-controls {display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:8px;min-width:0}
      .header-controls .connection {margin-left:0}
      .speed-panel {
        display:flex;align-items:center;gap:8px;padding:4px 8px;border:1px solid var(--line);
        border-radius:8px;background:#1b1e21;box-shadow:inset 0 2px 5px #0009;
      }
      .speed-trend {width:96px;text-align:center;line-height:1}
      .speed-chart {width:96px;height:24px;display:block}
      .speed-chart path {fill:none;stroke:currentColor;stroke-width:1.35}
      .speed-chart circle {fill:currentColor}
      .speed-chart .speed-grid {stroke:#505967;stroke-width:.5}
      .speed-caption,.speed-empty {font-size:9px;color:var(--muted)}
      .speed-values {display:flex;flex-wrap:wrap;gap:4px 8px;font-size:11px;font-variant-numeric:tabular-nums}
      .speed-values span {white-space:nowrap}
      .download {color:#a4cfff}
      .upload {color:#c7b2ff}
      .speed-values .ping {color:var(--muted)}
      .speed-action {display:grid;justify-items:center;gap:2px;min-width:66px}
      .speed-action button {font-size:11px;line-height:1.15;padding:5px 7px;white-space:nowrap}
      .speed-message {font-size:9px;line-height:1.1;color:var(--muted);max-width:76px;text-align:center}
      @container (max-width:689px) {.speed-panel {flex-wrap:wrap;max-width:100%}}
      @container (max-width:689px) {.header-controls {justify-content:flex-start}}
      .dot,.pill::after {
        display:inline-block;flex:0 0 auto;width:10px;height:10px;border-radius:50%;
        background:radial-gradient(circle at 35% 25%,#fff9,transparent 65%),currentColor;
        box-shadow:0 0 8px currentColor,inset 0 -2px 3px #0007;
      }
      .dot {color:var(--good);margin-right:2px;font-size:0}
      .dot.uncertain {color:var(--warn)}
      .banner {border:1px solid #b67477;background:#37282b;border-radius:10px;padding:12px 14px;margin-bottom:16px}
      .banner p {margin-top:4px;color:#f5c7cc}
      .warning {background:#332b20;border-color:#9a7a43}
      .warning p {color:#f4d99e}
      .layout {display:grid;gap:16px;align-items:start}
      .with-detail {grid-template-columns:minmax(0,1.95fr) minmax(0,1fr)}
      .tiles {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
      .tile,.detail,.add-box {
        position:relative;min-width:0;padding:clamp(14px,2cqw,24px);
        border:4px double #777c80;border-radius:15px;
        background:
          radial-gradient(circle at center,#ffffff12 .45px,transparent .7px) 0 0/3px 3px,
          linear-gradient(155deg,#383b3e,#252729 48%,#1c1e21);
        box-shadow:inset 0 0 0 1px #141516,inset 0 0 12px #0007,0 5px 8px #000b;
      }
      .tile::before,.detail::before {
        content:"";position:absolute;inset:4px;pointer-events:none;
        --screw:radial-gradient(circle at 40% 35%,#a1a4a7 0%,#4b4f52 47%,#121315 62%,#686b6e 72%,transparent 75%);
        background:var(--screw) top left/9px 9px no-repeat,var(--screw) top right/9px 9px no-repeat,
                   var(--screw) bottom left/9px 9px no-repeat,var(--screw) bottom right/9px 9px no-repeat;
      }
      .tile {width:100%;text-align:left;display:grid;align-content:start;gap:10px;min-height:148px}
      .tile[aria-pressed=true] {border-color:#a9b5c5;box-shadow:inset 0 0 0 1px #111,0 0 12px #a4cfff50,0 5px 8px #000b}
      .identity {display:flex;align-items:center;gap:8px;min-width:0;overflow-wrap:anywhere;font-size:clamp(16px,2.15cqw,25px)}
      .tile .identity {min-width:0;line-height:1.15;overflow-wrap:normal}
      .tile .identity ha-icon {flex:none}
      .service-name {
        display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;
        min-width:0;overflow:hidden;overflow-wrap:anywhere;
      }
      .tile-meta {display:flex;align-items:center;justify-content:space-between;gap:5px;min-width:0}
      .tile-meta .muted {min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .tile-meta .pill {flex:none;white-space:nowrap}
      .identity ha-icon {color:#e1e2e4;filter:drop-shadow(0 2px 1px #000)}
      .pill {
        display:inline-flex;align-items:center;gap:8px;
        font-weight:650;font-size:clamp(11px,1.3cqw,14px);
        padding:5px 9px;border-radius:999px;color:#e2e5ea;
        background:#33363a;box-shadow:inset 0 2px 6px #0008;
      }
      .pill::after {content:"";width:8px;height:8px}
      .operational {color:var(--good);background:#103a33}
      .outage {color:var(--bad);background:#542a30}
      .possible_problems {color:var(--warn);background:#4d3720}
      .trace {fill:none;stroke:var(--violet);stroke-width:1.55;vector-effect:non-scaling-stroke}
      .chart {display:block;width:100%;height:auto;min-height:26px;filter:drop-shadow(0 0 4px #8e77ff80)}
      .spark {display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;min-height:32px}
      .spark strong {font-variant-numeric:tabular-nums;font-size:14px}
      .gridline,.baseline {fill:none;stroke:#465761;stroke-width:.65}
      .baseline {stroke:#bcc9dc;stroke-dasharray:4 4}
      .detail {display:grid;gap:16px}
      .detail p {overflow-wrap:anywhere}
      .plot {border:1px solid #636d75;padding:10px;border-radius:9px;background:radial-gradient(ellipse at center,#202f3d,#11171d);box-shadow:inset 0 0 9px #000}
      .plot .row {margin-bottom:9px}
      .axis {font-size:11px;margin-top:5px}
      .chips {display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
      .chips span {font-size:12px;color:#151619;font-weight:700;border:1px solid #e2e3e4;background:linear-gradient(#c6c9cb,#858b91);padding:5px 8px;border-radius:5px;box-shadow:0 2px 3px #0009}
      .detail a {border-color:#8db2dc;text-decoration:none;padding:7px 9px;font-size:13px;box-shadow:inset 0 0 0 2px #15191e,0 0 8px #75adff55}
      .detail footer {border-top:1px solid #64686c;padding-top:11px}
      button.danger {border-color:#d79094}
      .danger {color:var(--bad)}
      .notice {margin-top:14px}
      .add-box {margin-bottom:14px}
      .catalog {display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
      .add-box form {display:flex;gap:8px;flex-wrap:wrap}
      .add-box input {min-width:0;max-width:100%;background:#16191d;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px}
      .add-box form input {flex:1 1 160px}
      /* Keep the normal dashboard view compact on desktop. */
      @container (min-width:690px) {
        header h1 {font-size:clamp(28px,3.4cqw,44px)}
        header p {font-size:13px;margin-top:2px;line-height:1.2}
        .summary {margin:10px 0 9px;gap:6px}
        .count,.connection {padding:5px 9px;font-size:12px}
        .layout,.tiles {gap:7px}
        .with-detail {grid-template-columns:minmax(0,2.65fr) minmax(245px,1fr)}
        .tiles {grid-template-columns:repeat(3,minmax(0,1fr))}
        .layout:not(.with-detail) .tiles {grid-template-columns:repeat(4,minmax(0,1fr))}
        .tile,.detail {padding:9px 11px}
        .tile {gap:3px;min-height:0;grid-template-rows:30px 18px 17px 14px;line-height:1.12;padding:6px 9px}
        .tile .identity {font-size:13px;line-height:1.12}
        .tile ha-icon {--mdc-icon-size:16px;flex:none}
        .pill {font-size:10px;padding:3px 6px;gap:5px}
        .pill::after {width:6px;height:6px}
        .tile .muted,.tile .no-chart {font-size:11px;line-height:1.1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .spark {min-height:15px}
        .spark .chart {height:17px;min-height:0}
        .spark strong {font-size:11px}
        .detail {gap:9px;max-height:calc(100dvh - 215px);overflow:auto}
        .detail .plot .chart {max-height:120px}
        .detail button,.detail a {padding:5px 7px}
        .notice {margin-top:8px}
        .banner {padding:6px 10px;margin-bottom:8px;font-size:13px}
        .banner p {display:none}
      }
      @container (min-width:900px) {
        .tiles {grid-template-columns:repeat(4,minmax(0,1fr))}
        .layout:not(.with-detail) .tiles {grid-template-columns:repeat(5,minmax(0,1fr))}
      }
      @media (max-height:800px) {
        @container (min-width:690px) {
          .tile {grid-template-rows:27px 16px 14px 12px;padding-block:5px}
          .tile .identity {font-size:12px}
          .spark .chart {height:14px}
        }
      }
      @media (min-width:1024px) {
        .shell {padding:14px 16px}
      }
      @container (max-width:689px) {
        .with-detail {grid-template-columns:minmax(0,1fr)}
        .detail {grid-row:1}
        .connection {margin-left:0}
      }
      @container (max-width:500px) {.tiles {grid-template-columns:minmax(0,1fr)}}
      .theme-open {white-space:nowrap}
      @container (min-width:690px) and (max-width:1100px) {
        .header-controls {gap:5px}
        .header-controls .primary,.theme-open {font-size:11px;padding:6px 9px}
        .header-controls .connection {font-size:11px;padding-inline:6px}
        .speed-panel {gap:5px;padding-inline:6px}
        .speed-trend,.speed-chart {width:74px}
        .speed-values {gap:4px;font-size:10px}
      }
      .theme-dialog {
        box-sizing:border-box;width:min(540px,calc(100vw - 26px));max-height:calc(100dvh - 26px);
        color:var(--ink);background:var(--theme-surface,#22262b);border:1px solid var(--line);
        padding:16px;border-radius:14px;box-shadow:0 12px 54px #0009;
      }
      .theme-dialog::backdrop {background:#060a1199}
      .theme-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,205px),1fr));gap:8px;margin-top:12px}
      .theme-choice {display:grid;grid-template-columns:auto 1fr;align-items:center;gap:8px;text-align:left;min-width:0}
      .theme-choice[aria-pressed="true"] {outline:2px solid var(--blue);outline-offset:-2px}
      .theme-choice small {display:block;color:var(--muted);margin-top:3px;line-height:1.2}
      .theme-swatch {width:26px;height:26px;border:1px solid var(--swatch-edge);border-radius:5px;background:linear-gradient(140deg,var(--swatch-bg) 60%,var(--swatch-accent) 61%)}

      .shell:not([data-theme="steel"]) {
        --blue:var(--accent);
        --violet:var(--trace-color,var(--accent));
        background:var(--backdrop,var(--theme-bg));
        border:1px solid var(--line);
        box-shadow:inset 0 0 24px var(--glow,transparent);
        border-radius:var(--theme-radius,12px);
      }
      .shell:not([data-theme="steel"]) :is(.tile,.detail,.add-box) {
        color:var(--ink);background:var(--panel,var(--theme-surface));border:1px solid var(--line);
        border-radius:var(--theme-radius,12px);box-shadow:inset 0 0 10px var(--glow,transparent);
      }
      .shell:not([data-theme="steel"]) :is(.tile,.detail)::before {display:none}
      .shell:not([data-theme="steel"]) :is(button,a,.count,.connection,.speed-panel,.plot,.chips span,.add-box input):not(.tile) {
        color:var(--ink);background:var(--theme-raised);border-color:var(--line);box-shadow:none;
      }
      .shell:not([data-theme="steel"]) :is(button,a):hover:not(:disabled),
      .shell:not([data-theme="steel"]) .tile[aria-pressed="true"] {
        border-color:var(--accent);box-shadow:0 0 9px var(--glow,transparent);
      }
      .shell:not([data-theme="steel"]) .primary {
        background:var(--action-bg,var(--accent));color:var(--on-accent);border-color:var(--accent);
      }
      .shell:not([data-theme="steel"]) :is(header p,.count b,.identity ha-icon,.download) {color:var(--accent)}
      .shell:not([data-theme="steel"]) .upload {color:var(--trace-color,var(--accent))}
      .shell:not([data-theme="steel"]) :is(h1,h2,.identity,.count b) {text-shadow:none}
      .shell:not([data-theme="steel"]) .chart {filter:drop-shadow(0 0 3px var(--glow,transparent))}
      .shell:not([data-theme="steel"]) .banner {background:var(--theme-raised);border-color:var(--bad)}
      .shell:not([data-theme="steel"]) .banner p {color:var(--muted)}
      .shell:not([data-theme="steel"]) .warning {border-color:var(--warn)}
      .shell:not([data-theme="steel"]) .operational {color:var(--good);background:color-mix(in srgb,var(--good) 14%,var(--theme-bg))}
      .shell:not([data-theme="steel"]) .possible_problems {color:var(--warn);background:color-mix(in srgb,var(--warn) 14%,var(--theme-bg))}
      .shell:not([data-theme="steel"]) .outage {color:var(--bad);background:color-mix(in srgb,var(--bad) 14%,var(--theme-bg))}
      .shell:not([data-theme="steel"]) .unknown {color:var(--muted);background:var(--theme-raised)}
      .shell:not([data-theme="steel"]) .pill {box-shadow:none}
      .shell:not([data-theme="steel"]) .count[data-state="outage"] b {color:var(--bad)}
      .shell:not([data-theme="steel"]) .count[data-state="possible_problems"] b {color:var(--warn)}
      .shell:not([data-theme="steel"]) .count[data-state="operational"] b {color:var(--good)}
      .shell[data-theme="relay"] {
        --theme-bg:#20251e;--theme-surface:#292b22;--theme-raised:#34372c;--line:#93896b;
        --ink:#f4e9ca;--muted:#d8cca8;--accent:#ffca75;--on-accent:#261d0d;
        --trace-color:#ffb45c;--theme-radius:7px;
        --backdrop:repeating-linear-gradient(0deg,#0002 0 1px,transparent 1px 4px),#242a21;
      }
      .shell[data-theme="relay"] h1 {font-family:ui-monospace,monospace;text-transform:uppercase;letter-spacing:.015em;color:var(--accent)}
      .shell[data-theme="relay"] .tile {border-top:4px solid #c6bb97}
      .shell[data-theme="relay"] .count {outline:1px solid #c6bb97;outline-offset:-3px}
      .shell[data-theme="neon"] {
        --theme-bg:#060b1c;--theme-surface:#0c1428;--theme-raised:#121c33;--line:#4c7898;
        --ink:#f0f3ff;--muted:#b3c4df;--accent:#70f5ff;--on-accent:#231021;
        --action-bg:#ff91e7;--trace-color:#f887ed;--glow:#59e9ff47;--theme-radius:4px;
        --backdrop:linear-gradient(#64dfff14 1px,transparent 1px) 0 0/24px 24px,
                   linear-gradient(90deg,#64dfff14 1px,transparent 1px) 0 0/24px 24px,#080d20;
      }
      .shell[data-theme="neon"] h1 {font-family:ui-monospace,monospace;text-transform:uppercase;color:var(--accent);text-shadow:0 0 12px #ef74e5aa}
      .shell[data-theme="neon"] :is(.tile,.detail) {border-top:2px solid var(--accent)}
      .shell[data-theme="abyss"] {
        --theme-bg:#0a1021;--theme-surface:#141b32;--theme-raised:#212947;--line:#576393;
        --ink:#f2f5ff;--muted:#bfc9e9;--accent:#77f1ff;--on-accent:#07262c;
        --trace-color:#8ce6ba;--glow:#7275df55;--theme-radius:20px;
        --backdrop:radial-gradient(ellipse at 100% 100%,#26204a,transparent 62%),#0a1021;
        --panel:linear-gradient(145deg,#202b46,#121a30);
      }
      .shell[data-theme="abyss"] h1 {color:var(--accent);text-shadow:0 0 14px #58eeff65}
      .shell[data-theme="tide"] {
        --theme-bg:#062939;--theme-surface:#0d3546;--theme-raised:#184959;--line:#4392a3;
        --ink:#f1fbff;--muted:#b8dfe7;--accent:#85ffe4;--on-accent:#042e32;
        --trace-color:#72eaff;--glow:#58e9ed50;--theme-radius:10px;
        --backdrop:radial-gradient(ellipse at 100% 90%,#0a6676,transparent 62%),
                   radial-gradient(ellipse at 0 0,#147688,transparent 55%),#08293c;
        --panel:linear-gradient(160deg,#185060,#0b3446 70%);
      }
      .shell[data-theme="tide"] h1 {color:#d6fbff;text-shadow:0 2px 0 #0a5267,0 0 14px #67f1f585}
      .shell[data-theme="tide"] :is(.count,.detail a) {border-radius:999px}
      .shell[data-theme="appearance"] {
        --theme-bg:var(--yanke-bg,var(--primary-background-color,#20242b));
        --theme-surface:var(--yanke-surface,var(--ha-card-background,#292f39));
        --theme-raised:var(--yanke-raised,var(--secondary-background-color,#343d49));
        --ink:var(--yanke-text,var(--primary-text-color,#f0f2f7));
        --muted:var(--yanke-muted,var(--secondary-text-color,#b6c5db));
        --accent:var(--yanke-accent,var(--primary-color,#65d4ee));
        --on-accent:var(--yanke-on-accent,var(--text-primary-color,#10191c));
        --line:var(--yanke-line,var(--divider-color,#758294));
        --good:var(--yanke-success,var(--success-color,#6fd2a6));
        --warn:var(--yanke-warning,var(--warning-color,#ffce83));
        --bad:var(--yanke-danger,var(--error-color,#ff9d9d));
        font-family:var(--yanke-font,var(--ha-font-family-body,inherit));
      }
      .shell[data-theme="appearance"] .tile {grid-template-rows:auto;grid-auto-rows:minmax(min-content,auto)}
      .shell[data-theme="appearance"] .identity {font-size:calc(1em * var(--yanke-scale,1))}
      .shell[data-theme="appearance"] :is(.muted,.pill,.count,.connection,.speed-values) {
        font-size:calc(11px * var(--yanke-scale,1));
      }
      .shell[data-theme="appearance"] .header-controls button {font-size:calc(12px * var(--yanke-scale,1))}
      .shell[data-theme="appearance"] h1 {font-size:calc(clamp(28px,3.4cqw,44px) * var(--yanke-scale,1))}
    </style><main class="shell" data-theme="${this.theme}">
      <dialog class="theme-dialog" aria-labelledby="ow-theme-title">
        <div class="row"><h2 id="ow-theme-title">Dashboard theme</h2><button type="button" data-action="close-themes" aria-label="Close theme picker">×</button></div>
        <div class="theme-grid">${Object.entries(THEMES).map(([id,[name,description,bg,edge,accent]]) => `
          <button type="button" class="theme-choice" data-action="choose-theme" data-id="${id}" aria-pressed="${this.theme === id}">
            <span class="theme-swatch" aria-hidden="true" style="--swatch-bg:${bg};--swatch-edge:${edge};--swatch-accent:${accent}"></span>
            <span><strong>${name}</strong><small>${description}</small></span>
          </button>`).join("")}</div>
      </dialog>
      <header><div><h1>Outage Map</h1><p>Your services, at a glance.</p></div><div class="header-controls">${connection}${this.speedHeader()}<button type="button" class="theme-open" data-action="themes" aria-haspopup="dialog">Theme</button>${can_manage ? '<button class="primary" data-action="add">+ Add service</button>' : ""}</div></header>
      ${this.loadError ? `<p class="notice" role="status">${escape(this.loadError)}</p>` : ""}
      ${this.error ? `<p class="notice danger" role="alert">${escape(this.error)}</p>` : ""}
      <div class="summary"><span class="count"><b>${services.length}</b> Services</span>
        ${counts.map(([state, name]) => `<span class="count" data-state="${state}"><b>${services.filter((item) => item.status === state).length}</b> ${name}</span>`).join("")}
      </div>
      ${connected === false ? '<div class="banner warning"><strong>Internet connectivity may be disrupted</strong><p>Home Assistant couldn’t reach either connectivity check. Service alerts are paused.</p></div>' :
        incident ? `<div class="banner"><strong>${escape(incident.name)} is reporting an incident</strong><p>${escape(incident.incident || "See official status for details.")}</p></div>` : ""}
      ${this.adding ? `<section class="add-box"><div class="row"><h2>Track a service</h2><button data-action="cancel">Close</button></div>
        <input id="search" type="search" aria-label="Search catalog" placeholder="Search catalog">
        <div class="catalog">${catalog.filter((item) => !services.some((service) => service.id === item.id)).map((item) => `<button data-search="${escape(item.name)}" data-action="track" data-id="${escape(item.id)}">${escape(item.name)}</button>`).join("")}</div>
        <form><input name="name" aria-label="Service name" placeholder="Service name" maxlength="80" required><input name="url" type="url" aria-label="Public HTTP URL" placeholder="https://example.com" required><button class="primary">Track URL</button></form></section>` : ""}
      <div class="layout ${selected ? "with-detail" : ""}">
        <div class="tiles">${ordered.map((item) => `<button class="tile" data-action="select" data-id="${escape(item.id)}" aria-pressed="${selected?.id === item.id}">
          <strong class="identity" title="${escape(item.name)}">${icons(item.icon || "link-variant")}<span class="service-name">${escape(item.name)}</span></strong>
          <span class="tile-meta"><span class="muted">${escape(item.signal)}${item.feed_scope ? " · " + escape(item.feed_scope) : ""}${item.signal !== "Checks only" && !item.feed_fresh ? " · Feed unavailable" : ""}</span><span class="pill ${escape(item.status)}">${label(item)}</span></span>
          <span class="spark">${graph(item)}<strong>${item.latency == null ? "—" : `${escape(item.latency)} ms`}</strong></span>
          <span class="muted">${item.signal === "Feed only" ? "Feed refreshed" : "Checked"} ${timestamp(item.checked || item.feed_checked)}</span>
        </button>`).join("") || (this.data ? `<p class="muted">${can_manage ? "No services tracked yet." : "No services available to view."}</p>` : "")}</div>
        ${selected ? `<aside class="detail"><div class="row"><h2 class="identity">${icons(selected.icon || "link-variant")}${escape(selected.name)}</h2><button aria-label="Close details" data-action="close">×</button></div>
          <div><span class="pill ${escape(selected.status)}">${label(selected)}</span><p class="muted">${selected.reason === "unreachable" ? "Home Assistant could not reach this endpoint." : selected.signal === "Checks only" ? "This tile reflects checks from your network." : escape(selected.signal)}</p></div>
          ${selected.incident ? `<p>${escape(selected.incident)}</p>` : ""}
          <div class="plot"><div class="row"><h3>Response time · 24 hours</h3>${selected.baseline == null ? "" : `<span class="muted">Baseline ${escape(selected.baseline)} ms</span>`}</div>${graph(selected,true)}</div>
          ${selected.components?.length ? `<div><h3>Affected components</h3><div class="chips">${selected.components.map((name) => `<span>${escape(name)}</span>`).join("")}</div></div>` : ""}
          <p class="muted">Last successful feed update ${timestamp(selected.feed_checked)}</p>
          <div class="actions">${link(selected.official, selected.name === "Spotify" ? "Spotify ongoing issues" : "Official status")}${link(selected.crowd,"Downdetector")}</div>
          ${can_manage ? `<footer class="actions"><button data-action="alerts" aria-pressed="${!!selected.alerts}" ${!notify_configured && !selected.alerts ? "disabled title=\"Configure a notification action in integration options\"" : ""}>Notifications ${selected.alerts ? "on" : "off"}</button>
          ${this.confirmRemove ? '<button data-action="cancel-remove">Cancel</button><button class="danger" data-action="remove">Confirm removal</button>' : '<button data-action="confirm">Remove service</button>'}</footer>` : ""}
        </aside>` : ""}
      </div><p class="muted notice">Charts show response time. A reachable endpoint can still have partial outages.</p>
    </main>`;
    this.syncAppearance();
  }
}
if (!customElements.get(TAG)) {
  customElements.define(TAG, OutageWatchCard);
  window.customCards = window.customCards || [];
  window.customCards.push({type: TAG, name: "Outage Map", description: "Provider incidents and local reachability."});
}
