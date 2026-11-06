const WEG_DOMAIN = "wegood_charge";
const WEG_DEVICE_IDENTIFIER = "wegood_ev_charger";

const WEG_KEYS = {
  state: { unique: "wegood_state", name: "State" },
  power: { unique: "wegood_power", name: "Power" },
  session_energy: { unique: "wegood_session_energy", name: "Session energy" },
  session_minutes: { unique: "wegood_session_minutes", name: "Session time" },
  temperature: { unique: "wegood_temperature", name: "Temperature" },
  voltage: { unique: "wegood_voltage", name: "Voltage" },
  connector: { unique: "wegood_connector", name: "Connector" },
  charging: { unique: "wegood_charging", name: "Charging" },
  charging_current: { unique: "wegood_charging_current", name: "Charging current" },
  charging_mode: { unique: "wegood_charging_mode", name: "Charging mode" },
  station_seen: { unique: "wegood_station_seen", name: "Station online" },
  cloud_connected: { unique: "wegood_cloud_connected", name: "Cloud MQTT" },
  thermal_trip: { unique: "wegood_thermal_trip", name: "Thermal trip" },
  observed_today_energy: { unique: "wegood_observed_today_energy", name: "Observed energy today" },
  observed_month_energy: { unique: "wegood_observed_month_energy", name: "Observed energy this month" },
  observed_total_energy: { unique: "wegood_observed_total_energy", name: "Observed total energy" },
  observed_sessions: { unique: "wegood_observed_sessions", name: "Observed sessions" },
};

const MODE_OPTIONS = ["Standard Mode", "Free Card Swipe", "Plug and Charge"];

const TEXT = {
  ru: {
    title: "WeGoodCharge",
    subtitle: "Зарядная станция",
    notFound: "Устройство WeGoodCharge не найдено",
    notFoundHint: "Добавьте и настройте интеграцию WeGoodCharge, затем обновите страницу.",
    charging: "Заряжается",
    ready: "Готова",
    offline: "Нет связи",
    start: "Начать зарядку",
    stop: "Остановить зарядку",
    controlIntegrationOffline: "Интеграция не запущена",
    controlProtocolUnverified: "Управление доступно только для подтверждённого протокола ICS_10 V1.4",
    controlTransportOffline: "Нет связи с MQTT",
    controlTelemetryStale: "Нет свежей телеметрии станции",
    controlThermalTrip: "Сработала защита от перегрева",
    controlWaitingResponse: "Ожидание ответа станции",
    controlConnectVehicle: "Подключите автомобиль",
    controlStationNotReady: "Станция пока не готова принять команду",
    power: "Мощность",
    currentPower: "Текущая мощность",
    state: "Состояние",
    sessionEnergy: "Сессия",
    temperature: "Температура",
    voltage: "Напряжение",
    sessionTime: "Время",
    connector: "Коннектор",
    connectorConnected: "Автомобиль подключён",
    connectorDisconnected: "Автомобиль не подключён",
    connectorUnknown: "Состояние подключения неизвестно",
    current: "Ток зарядки",
    mode: "Режим зарядки",
    station: "Станция",
    cloud: "Облако",
    thermal: "Перегрев",
    ok: "Норма",
    online: "Онлайн",
    offlineShort: "Офлайн",
    counters: "Счётчики",
    today: "Сегодня",
    month: "Месяц",
    total: "Всего",
    sessions: "Сессий",
  },
  en: {
    title: "WeGoodCharge",
    subtitle: "EV charger",
    notFound: "WeGoodCharge device was not found",
    notFoundHint: "Add and configure the WeGoodCharge integration, then refresh this page.",
    charging: "Charging",
    ready: "Ready",
    offline: "Offline",
    start: "Start charging",
    stop: "Stop charging",
    controlIntegrationOffline: "Integration is not running",
    controlProtocolUnverified: "Control requires the verified ICS_10 V1.4 protocol",
    controlTransportOffline: "MQTT connection is offline",
    controlTelemetryStale: "No fresh charger telemetry",
    controlThermalTrip: "Thermal protection is active",
    controlWaitingResponse: "Waiting for the charger response",
    controlConnectVehicle: "Connect the vehicle",
    controlStationNotReady: "The charger is not ready for this command yet",
    power: "Power",
    currentPower: "Current power",
    state: "State",
    sessionEnergy: "Session",
    temperature: "Temperature",
    voltage: "Voltage",
    sessionTime: "Time",
    connector: "Connector",
    connectorConnected: "Vehicle connected",
    connectorDisconnected: "Vehicle disconnected",
    connectorUnknown: "Connection state unknown",
    current: "Charging current",
    mode: "Charging mode",
    station: "Station",
    cloud: "Cloud",
    thermal: "Thermal",
    ok: "OK",
    online: "Online",
    offlineShort: "Offline",
    counters: "Counters",
    today: "Today",
    month: "Month",
    total: "Total",
    sessions: "Sessions",
  },
};

class WeGoodChargeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._entityIds = {};
    this._rendered = false;
    this._hasDevice = false;
    this._renderedLang = null;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._entityIds = this._discoverEntities(hass);
    this._render();
  }

  getCardSize() {
    return 7;
  }

  _lang() {
    return String(this._hass?.language || "en").toLowerCase().startsWith("ru") ? "ru" : "en";
  }

  _t(key) {
    return TEXT[this._lang()][key] || TEXT.en[key] || key;
  }

  _discoverEntities(hass) {
    if (!hass) return {};
    const registry = hass.entities || {};
    const devices = hass.devices || {};
    const device = Object.values(devices).find((item) =>
      Array.isArray(item?.identifiers) && item.identifiers.some((identifier) =>
        Array.isArray(identifier) && identifier[0] === WEG_DOMAIN && identifier[1] === WEG_DEVICE_IDENTIFIER
      )
    );
    const candidates = Object.entries(registry).filter(([, entry]) => {
      if (device) return entry.device_id === device.id;
      return entry.platform === WEG_DOMAIN || String(entry.unique_id || "").startsWith("wegood_");
    });
    const result = {};

    for (const [key, spec] of Object.entries(WEG_KEYS)) {
      const exact = candidates.find(([, entry]) => entry.unique_id === spec.unique);
      const byName = candidates.find(([, entry]) => entry.original_name === spec.name || entry.name === spec.name);
      const fallback = Object.keys(hass.states || {}).find((entityId) => {
        if (device && registry[entityId]?.device_id !== device.id) return false;
        const normalized = entityId.replace(/^.*\./, "");
        return normalized.includes("wegood") && normalized.endsWith(`_${key}`);
      });
      result[key] = exact?.[0] || byName?.[0] || fallback || null;
    }
    return result;
  }

  _state(key) {
    const entityId = this._entityIds[key];
    return entityId ? this._hass?.states?.[entityId] : null;
  }

  _available(key) {
    const state = this._state(key);
    return Boolean(state && state.state !== "unavailable" && state.state !== "unknown");
  }

  _isOn(key) {
    return this._state(key)?.state === "on";
  }

  _connectorStatus() {
    const value = String(this._state("connector")?.state || "unknown").toLowerCase();
    if (value === "connected") return { text: this._t("connectorConnected"), className: "connected" };
    if (value === "disconnected") return { text: this._t("connectorDisconnected"), className: "disconnected" };
    return { text: this._t("connectorUnknown"), className: "unknown" };
  }

  _chargingControl() {
    const entity = this._state("charging");
    const stationState = String(this._state("state")?.state || "").toLowerCase();
    const suggested = entity?.attributes?.suggested_action;
    const action = suggested === "start" || suggested === "stop"
      ? suggested
      : (stationState === "charging" || entity?.state === "on" ? "stop" : "start");
    const entityAvailable = this._available("charging");
    const controlAvailable = entity?.attributes?.control_available;
    const available = entityAvailable && (controlAvailable === undefined || controlAvailable === true);
    if (available) return { action, available, reason: "" };

    if (!entityAvailable) {
      return { action, available, reason: this._t("controlIntegrationOffline") };
    }

    const reasons = {
      integration_offline: "controlIntegrationOffline",
      protocol_unverified: "controlProtocolUnverified",
      transport_offline: "controlTransportOffline",
      telemetry_stale: "controlTelemetryStale",
      thermal_trip: "controlThermalTrip",
      waiting_response: "controlWaitingResponse",
      connect_vehicle: "controlConnectVehicle",
      station_not_ready: "controlStationNotReady",
    };
    const reasonKey = reasons[entity?.attributes?.control_reason];
    if (reasonKey) return { action, available, reason: this._t(reasonKey) };
    if (!this._isOn("station_seen")) return { action, available, reason: this._t("controlTelemetryStale") };
    if (this._isOn("thermal_trip")) return { action, available, reason: this._t("controlThermalTrip") };
    if (this._connectorStatus().className !== "connected" && action === "start") {
      return { action, available, reason: this._t("controlConnectVehicle") };
    }
    return { action, available, reason: this._t("controlStationNotReady") };
  }

  _format(key, fallbackUnit = "") {
    const state = this._state(key);
    if (!state || ["unknown", "unavailable", "none", ""].includes(String(state.state).toLowerCase())) return "—";
    const unit = state.attributes?.unit_of_measurement || fallbackUnit;
    const numeric = Number(state.state);
    const value = Number.isFinite(numeric)
      ? new Intl.NumberFormat(this._lang() === "ru" ? "ru-RU" : "en-US", { maximumFractionDigits: 2 }).format(numeric)
      : state.state;
    return unit ? `${value} ${unit}` : value;
  }

  _formatPower() {
    const state = this._state("power");
    const watts = Number(state?.state);
    if (!Number.isFinite(watts)) return "—";
    const value = new Intl.NumberFormat(this._lang() === "ru" ? "ru-RU" : "en-US", {
      maximumFractionDigits: 2,
    }).format(watts / 1000);
    return `${value} ${this._lang() === "ru" ? "кВт" : "kW"}`;
  }

  _statusLabel() {
    if (!this._isOn("station_seen")) return this._t("offline");
    if (String(this._state("state")?.state || "").toLowerCase() === "charging" || this._isOn("charging")) {
      return this._t("charging");
    }
    return this._t("ready");
  }

  _metric(icon, label, value) {
    return `<div class="metric"><ha-icon icon="${icon}"></ha-icon><div><span>${label}</span><strong>${value}</strong></div></div>`;
  }

  _chip(label, on, bad = false) {
    const activeClass = bad ? (on ? "bad" : "good") : (on ? "good" : "muted");
    const value = bad ? (on ? this._t("thermal") : this._t("ok")) : (on ? this._t("online") : this._t("offlineShort"));
    return `<div class="chip ${activeClass}"><span class="dot"></span><span>${label}: ${value}</span></div>`;
  }

  async _call(domain, service, data) {
    if (!this._hass) return;
    await this._hass.callService(domain, service, data);
  }

  _bindEvents() {
    const root = this.shadowRoot;
    const charging = this._entityIds.charging;
    root.querySelector("[data-action='charge']")?.addEventListener("click", () => {
      const control = this._chargingControl();
      if (!charging || !control.available) return;
      this._call("switch", control.action === "stop" ? "turn_off" : "turn_on", { entity_id: charging });
    });

    const slider = root.querySelector("[data-action='current']");
    slider?.addEventListener("change", (event) => {
      const entityId = this._entityIds.charging_current;
      if (!entityId || !this._available("charging_current")) return;
      this._call("number", "set_value", { entity_id: entityId, value: Number(event.target.value) });
    });

    root.querySelectorAll("[data-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        const entityId = this._entityIds.charging_mode;
        if (!entityId || !this._available("charging_mode")) return;
        this._call("select", "select_option", { entity_id: entityId, option: button.dataset.mode });
      });
    });
  }

  _update() {
    if (!this._hasDevice) return;
    const root = this.shadowRoot;
    const chargeControl = this._chargingControl();
    const charging = chargeControl.action === "stop";
    const connector = this._connectorStatus();
    const chargingEntity = this._state("charging");

    root.querySelector("[data-field='status']").textContent = this._statusLabel();
    root.querySelector("[data-field='power']").textContent = this._formatPower();
    root.querySelector("[data-field='session-energy']").textContent = this._format("session_energy", "kWh");
    root.querySelector("[data-field='temperature']").textContent = this._format("temperature", "°C");
    root.querySelector("[data-field='voltage']").textContent = this._format("voltage", "V");
    root.querySelector("[data-field='session-time']").textContent = this._format("session_minutes", "min");
    root.querySelector("[data-field='state']").textContent = this._format("state");

    const connectorNode = root.querySelector("[data-field='connector']");
    connectorNode.className = `connector-status ${connector.className}`;
    connectorNode.querySelector("span").textContent = `${this._t("connector")}: ${connector.text}`;

    root.querySelector("[data-field='chips']").innerHTML = `
      ${this._chip(this._t("station"), this._isOn("station_seen"))}
      ${this._chip(this._t("cloud"), this._isOn("cloud_connected"))}
      ${this._chip(this._t("thermal"), this._isOn("thermal_trip"), true)}
    `;

    const chargeButton = root.querySelector("[data-action='charge']");
    chargeButton.classList.toggle("stop", charging);
    chargeButton.disabled = !chargeControl.available;
    chargeButton.textContent = charging ? this._t("stop") : this._t("start");
    const chargeHint = root.querySelector("[data-field='charge-hint']");
    chargeHint.hidden = chargeControl.available;
    chargeHint.textContent = chargeControl.reason;

    const currentState = this._state("charging_current");
    const current = Number(currentState?.state);
    const currentMin = Number(currentState?.attributes?.min ?? 8);
    const currentMax = Number(currentState?.attributes?.max ?? 32);
    const currentAllowed = chargingEntity?.attributes?.can_set_current;
    const currentAvailable = this._available("charging_current")
      && Number.isFinite(current)
      && currentAllowed !== false;
    const slider = root.querySelector("[data-action='current']");
    slider.min = String(currentMin);
    slider.max = String(currentMax);
    slider.disabled = !currentAvailable;
    if (root.activeElement !== slider) {
      slider.value = String(Number.isFinite(current) ? current : currentMin);
    }
    root.querySelector("[data-field='current-value']").textContent = `${Number.isFinite(current) ? current : "—"} A`;

    const modeState = this._state("charging_mode");
    const mode = modeState?.state;
    const modeAllowed = chargingEntity?.attributes?.can_set_mode;
    const modeAvailable = this._available("charging_mode") && modeAllowed !== false;
    root.querySelectorAll("[data-mode]").forEach((button) => {
      button.classList.toggle("active", mode === button.dataset.mode);
      button.disabled = !modeAvailable;
    });

    root.querySelector("[data-field='today']").textContent = this._format("observed_today_energy", "kWh");
    root.querySelector("[data-field='month']").textContent = this._format("observed_month_energy", "kWh");
    root.querySelector("[data-field='total']").textContent = this._format("observed_total_energy", "kWh");
    root.querySelector("[data-field='sessions']").textContent = this._format("observed_sessions");
  }

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    const hasDevice = Object.values(this._entityIds).some(Boolean);
    const lang = this._lang();
    const style = `
      :host { display:block; container-type:inline-size; }
      ha-card { overflow:hidden; padding:0; border-radius:22px; }
      .hero { padding:22px 22px 18px; background:linear-gradient(135deg, var(--primary-color), var(--accent-color, var(--primary-color))); color:var(--text-primary-color, #fff); }
      .hero-top { display:flex; align-items:center; justify-content:space-between; gap:16px; }
      .brand { display:flex; align-items:center; gap:14px; min-width:0; }
      .brand ha-icon { --mdc-icon-size:36px; padding:10px; border-radius:16px; background:rgba(255,255,255,.16); }
      .title { font-size:22px; font-weight:700; line-height:1.15; }
      .subtitle { margin-top:4px; font-size:13px; opacity:.82; }
      .status { flex:0 0 auto; padding:7px 11px; border-radius:999px; background:rgba(255,255,255,.16); font-size:12px; font-weight:700; }
      .power { margin-top:22px; display:flex; flex-direction:column; align-items:flex-start; gap:4px; }
      .power span { font-size:12px; font-weight:600; opacity:.82; }
      .power strong { font-size:36px; line-height:1; letter-spacing:-1px; }
      .body { padding:18px 20px 20px; }
      .metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
      .metric { display:grid; grid-template-columns:24px minmax(0,1fr); column-gap:9px; align-items:center; min-width:0; padding:12px; border-radius:14px; background:var(--secondary-background-color); }
      .metric ha-icon { color:var(--primary-color); }
      .metric div { min-width:0; }
      .metric span { display:block; color:var(--secondary-text-color); font-size:11px; line-height:1.2; white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:break-word; word-break:normal; }
      .metric strong { display:block; margin-top:2px; font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .chips { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0; }
      .chip { display:flex; align-items:center; gap:6px; padding:6px 9px; border-radius:999px; background:var(--secondary-background-color); font-size:11px; }
      .dot { width:7px; height:7px; border-radius:50%; background:var(--secondary-text-color); }
      .good .dot { background:var(--success-color, #43a047); }
      .bad .dot { background:var(--error-color, #db4437); }
      .section { margin-top:15px; }
      .section-title { margin-bottom:8px; color:var(--secondary-text-color); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
      .connector-status { display:flex; align-items:center; gap:10px; margin:14px 0; padding:11px 13px; border-radius:13px; background:var(--secondary-background-color); font-size:13px; font-weight:600; }
      .connector-status ha-icon { color:var(--secondary-text-color); }
      .connector-status.connected ha-icon { color:var(--success-color, #43a047); }
      .connector-status.disconnected ha-icon { color:var(--warning-color, #f9a825); }
      .charge { width:100%; min-height:48px; border:0; border-radius:14px; background:var(--primary-color); color:var(--text-primary-color, #fff); font:inherit; font-weight:700; cursor:pointer; }
      .charge.stop { background:var(--error-color, #db4437); }
      .charge-hint { margin-top:7px; padding:0 5px; color:var(--secondary-text-color); font-size:12px; text-align:center; line-height:1.35; }
      button:disabled, input:disabled { opacity:.42; cursor:not-allowed; }
      .current-row { display:grid; grid-template-columns:1fr auto; gap:12px; align-items:center; }
      input[type='range'] { width:100%; accent-color:var(--primary-color); }
      .current-value { min-width:52px; text-align:right; font-weight:700; }
      .modes { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; }
      .mode { min-height:42px; border:1px solid var(--divider-color); border-radius:12px; background:var(--card-background-color); color:var(--primary-text-color); padding:7px 5px; font:inherit; font-size:11px; cursor:pointer; }
      .mode.active { border-color:var(--primary-color); color:var(--primary-color); background:var(--secondary-background-color); font-weight:700; }
      .counters { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
      .counter { padding:10px; border-radius:12px; background:var(--secondary-background-color); text-align:center; }
      .counter strong { display:block; font-size:13px; }
      .counter span { display:block; margin-top:3px; color:var(--secondary-text-color); font-size:10px; }
      .empty { padding:28px 22px; text-align:center; }
      .empty ha-icon { --mdc-icon-size:40px; color:var(--warning-color); }
      .empty strong { display:block; margin:12px 0 6px; }
      .empty span { color:var(--secondary-text-color); font-size:13px; }
      @container (max-width:560px) { .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } .modes { grid-template-columns:1fr; } .counters { grid-template-columns:repeat(2,minmax(0,1fr)); } }
      @media (max-width:520px) { .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } .modes { grid-template-columns:1fr; } .counters { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    `;

    if (!hasDevice) {
      if (!this._rendered || this._hasDevice || this._renderedLang !== lang) {
        this.shadowRoot.innerHTML = `<style>${style}</style><ha-card><div class="empty"><ha-icon icon="mdi:ev-station"></ha-icon><strong>${this._t("notFound")}</strong><span>${this._t("notFoundHint")}</span></div></ha-card>`;
      }
      this._rendered = true;
      this._hasDevice = false;
      this._renderedLang = lang;
      return;
    }

    if (this._rendered && this._hasDevice && this._renderedLang === lang) {
      this._update();
      return;
    }

    const currentState = this._state("charging_current");
    const current = Number(currentState?.state);
    const currentMin = Number(currentState?.attributes?.min ?? 8);
    const currentMax = Number(currentState?.attributes?.max ?? 32);
    const modes = MODE_OPTIONS.map((option) => `<button class="mode" data-mode="${option}">${option}</button>`).join("");

    this.shadowRoot.innerHTML = `
      <style>${style}</style>
      <ha-card>
        <div class="hero">
          <div class="hero-top">
            <div class="brand"><ha-icon icon="mdi:ev-station"></ha-icon><div><div class="title">${this._t("title")}</div><div class="subtitle">${this._t("subtitle")}</div></div></div>
            <div class="status" data-field="status"></div>
          </div>
          <div class="power"><span>${this._t("currentPower")}</span><strong data-field="power"></strong></div>
        </div>
        <div class="body">
          <div class="metrics">
            <div class="metric"><ha-icon icon="mdi:lightning-bolt"></ha-icon><div><span>${this._t("sessionEnergy")}</span><strong data-field="session-energy"></strong></div></div>
            <div class="metric"><ha-icon icon="mdi:thermometer"></ha-icon><div><span>${this._t("temperature")}</span><strong data-field="temperature"></strong></div></div>
            <div class="metric"><ha-icon icon="mdi:sine-wave"></ha-icon><div><span>${this._t("voltage")}</span><strong data-field="voltage"></strong></div></div>
            <div class="metric"><ha-icon icon="mdi:timer-outline"></ha-icon><div><span>${this._t("sessionTime")}</span><strong data-field="session-time"></strong></div></div>
            <div class="metric"><ha-icon icon="mdi:information-outline"></ha-icon><div><span>${this._t("state")}</span><strong data-field="state"></strong></div></div>
          </div>
          <div class="connector-status" data-field="connector"><ha-icon icon="mdi:ev-plug-type2"></ha-icon><span></span></div>
          <div class="chips" data-field="chips"></div>
          <button class="charge" data-action="charge"></button>
          <div class="charge-hint" data-field="charge-hint" hidden></div>
          <div class="section">
            <div class="section-title">${this._t("current")}</div>
            <div class="current-row"><input data-action="current" type="range" min="${currentMin}" max="${currentMax}" step="1" value="${Number.isFinite(current) ? current : currentMin}"><div class="current-value" data-field="current-value"></div></div>
          </div>
          <div class="section">
            <div class="section-title">${this._t("mode")}</div>
            <div class="modes">${modes}</div>
          </div>
          <div class="section">
            <div class="section-title">${this._t("counters")}</div>
            <div class="counters">
              <div class="counter"><strong data-field="today"></strong><span>${this._t("today")}</span></div>
              <div class="counter"><strong data-field="month"></strong><span>${this._t("month")}</span></div>
              <div class="counter"><strong data-field="total"></strong><span>${this._t("total")}</span></div>
              <div class="counter"><strong data-field="sessions"></strong><span>${this._t("sessions")}</span></div>
            </div>
          </div>
        </div>
      </ha-card>`;
    this._rendered = true;
    this._hasDevice = true;
    this._renderedLang = lang;
    this._bindEvents();
    this._update();
  }
}

if (!customElements.get("wegood-charge-card")) {
  customElements.define("wegood-charge-card", WeGoodChargeCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "wegood-charge-card")) {
  window.customCards.push({
    type: "wegood-charge-card",
    name: "WeGoodCharge",
    description: "WeGoodCharge EV charger control and telemetry",
    preview: true,
  });
}
