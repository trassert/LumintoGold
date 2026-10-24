"use strict";

const state = {
  authenticated: false,
  view: "clients",
  clients: [],
  counts: {},
  client: null,
  clientPhone: null,
  clientTab: "settings",
  logs: [],
  logLevel: "ALL",
  logSearch: "",
  logPaused: false,
  logRenderQueued: false,
  system: null,
  systemTimer: null,
  refreshTimer: null,
  refreshing: false,
  ws: null,
  wsRetry: 0,
  modalClose: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));

const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;

const STATUS = {
  running: { label: "Работает", cls: "running" },
  starting: { label: "Запускается", cls: "starting" },
  stopping: { label: "Останавливается", cls: "stopping" },
  stopped: { label: "Остановлен", cls: "stopped" },
  disabled: { label: "Отключён", cls: "disabled" },
  unauthorized: { label: "Нужен вход", cls: "unauthorized" },
  error: { label: "Ошибка", cls: "error" },
  invalid: { label: "Битый конфиг", cls: "invalid" },
};

const statusInfo = (status) => STATUS[status] || STATUS.stopped;

const statusChip = (status) => {
  const info = statusInfo(status);
  return `<span class="status status--${info.cls}" id="client-status"><span class="status-dot"></span>${esc(info.label)}</span>`;
};

const alertHtml = (message, tone = "") =>
  `<div class="alert ${tone ? `alert--${tone}` : ""}">${icon(tone === "success" ? "check" : "alert")}<span>${esc(message)}</span></div>`;

const noticeHtml = (message) =>
  `<div class="notice">${icon("spark")}<span>${esc(message)}</span></div>`;

const fmtBytes = (value) => {
  const size = Number(value) || 0;
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let amount = size;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

const fmtUptime = (seconds) => {
  const total = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days} д ${hours} ч ${minutes} мин`;
  if (hours) return `${hours} ч ${minutes} мин`;
  return `${minutes} мин`;
};

const fmtNumber = (value) => new Intl.NumberFormat("ru-RU").format(Number(value) || 0);

async function api(path, options = {}) {
  const opts = {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.headers || {}) },
  };
  if (opts.body && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text };
    }
  }
  if (response.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error(data?.error || "Требуется вход в панель");
  }
  if (!response.ok) {
    throw new Error(data?.error || `HTTP ${response.status}`);
  }
  return data;
}

let toastTimer = null;
function toast(message, tone = "") {
  const element = $("#snackbar");
  element.textContent = message;
  element.className = `snackbar is-visible${tone === "error" ? " snackbar--error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    element.classList.remove("is-visible");
  }, tone === "error" ? 5200 : 3400);
}

function setPage(title, subtitle, actions = "") {
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
  $("#topbar-actions").innerHTML = actions;
}

function updateNav() {
  const active = state.view === "client" ? "clients" : state.view;
  $$("[data-nav]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.nav === active);
  });
}

function navigate(path) {
  const hash = `#/${String(path).replace(/^\/+/, "")}`;
  if (location.hash === hash) {
    route();
    return;
  }
  location.hash = hash;
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle("is-busy", busy);
}

function themeIcon() {
  const dark = document.documentElement.dataset.theme === "dark";
  const use = $("#theme-toggle use");
  if (use) use.setAttribute("href", dark ? "#i-sun" : "#i-moon");
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("luminto-theme", next);
  } catch {}
  themeIcon();
}

function showLogin() {
  state.authenticated = false;
  state.view = "clients";
  state.client = null;
  state.clientPhone = null;
  state.logs = [];
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  clearInterval(state.refreshTimer);
  state.refreshTimer = null;
  stopSystemTimer();
  closeModal();
  $("#app").hidden = true;
  $("#login-screen").hidden = false;
  $("#login-error").hidden = true;
  $("#login-password").value = "";
  setTimeout(() => $("#login-password").focus(), 50);
}

async function enterApp() {
  state.authenticated = true;
  $("#login-screen").hidden = true;
  $("#app").hidden = false;
  themeIcon();
  connectLogs();
  if (!state.refreshTimer) {
    state.refreshTimer = setInterval(async () => {
      if (!state.authenticated || state.refreshing) return;
      state.refreshing = true;
      try {
        if (state.view === "clients") {
          await refreshClients(true);
        } else if (state.view === "client") {
          await refreshClientHead();
        }
      } catch {
        // The next poll will retry.
      } finally {
        state.refreshing = false;
      }
    }, 8000);
  }
  if (!location.hash) {
    history.replaceState(null, "", "#/clients");
  }
  await route();
}

async function handleLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#login-submit");
  const error = $("#login-error");
  error.hidden = true;
  setBusy(button, true);
  try {
    await api("/api/login", {
      method: "POST",
      body: { password: $("#login-password").value },
    });
    form.reset();
    await enterApp();
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    setBusy(button, false);
  }
}

async function logout() {
  try {
    await api("/api/logout", { method: "POST" });
  } catch {}
  showLogin();
}

async function route() {
  if (!state.authenticated) return;
  stopSystemTimer();
  const raw = (location.hash || "#/clients").replace(/^#\/?/, "");
  const parts = raw.split("/");
  const view = parts[0] || "clients";
  if (view === "client" && parts[1]) {
    state.view = "client";
    await loadClient(decodeURIComponent(parts.slice(1).join("/")));
  } else if (view === "logs") {
    state.view = "logs";
    renderLogs();
  } else if (view === "system") {
    state.view = "system";
    await renderSystem();
  } else {
    state.view = "clients";
    await renderClients();
  }
  updateNav();
}

// ---------------------------------------------------------------- clients

async function refreshClients(silent = false) {
  const data = await api("/api/clients");
  const changed = JSON.stringify(data.clients) !== JSON.stringify(state.clients);
  state.clients = data.clients || [];
  state.counts = data.counts || {};
  if (state.view === "clients" && (!silent || changed)) {
    drawClients();
  }
}

async function renderClients() {
  if (!state.authenticated) return;
  try {
    await refreshClients(false);
  } catch (err) {
    setPage("Клиенты", "Не удалось загрузить список", "");
    $("#view").innerHTML = alertHtml(err.message);
  }
}

function clientsSubtitle() {
  const total = state.counts.total || 0;
  const running = state.counts.running || 0;
  const disabled = state.counts.disabled || 0;
  const errors = state.counts.errors || 0;
  if (!total) return "Пока пусто — добавьте первого клиента";
  const parts = [`${total} всего`, `${running} работают`, `${disabled} отключены`];
  if (errors) parts.push(`${errors} с ошибкой`);
  return parts.join(" · ");
}

function clientsActions() {
  return `
    <button class="btn btn--tonal btn--small" data-top-action="import">${icon("upload")} Импорт</button>
    <button class="btn btn--outlined btn--small" data-top-action="stop-all">${icon("stop")} Стоп все</button>
    <button class="btn btn--filled btn--small" data-top-action="add">${icon("plus")} Добавить</button>
  `;
}

function drawClients() {
  setPage("Клиенты", clientsSubtitle(), clientsActions());
  const view = $("#view");
  if (!state.clients.length) {
    view.innerHTML = `
      <div class="empty">
        <div class="empty__icon">${icon("spark")}</div>
        <h2>Пока ни одного клиента</h2>
        <p>Добавьте аккаунт по коду из Telegram или QR. Уже есть готовые конфиги? Импортируйте их пачкой.</p>
        <div class="empty__actions">
          <button class="btn btn--filled" data-action="add">${icon("plus")} Добавить клиента</button>
          <button class="btn btn--tonal" data-action="import">${icon("upload")} Импорт JSON</button>
        </div>
      </div>`;
    return;
  }
  view.innerHTML = `<div class="clients-grid">${state.clients.map(clientCard).join("")}</div>`;
}

function clientCard(client) {
  const info = statusInfo(client.status);
  const running = ["running", "starting", "stopping"].includes(client.status);
  const busy = ["starting", "stopping"].includes(client.status);
  const canStart = client.valid && client.has_session;
  const needLogin = client.valid && (!client.has_session || client.status === "unauthorized");
  const errorClass = client.status === "unauthorized" ? "client-error client-error--warning" : "client-error";
  const errorText = client.error ? `<p class="${errorClass}">${esc(client.error)}</p>` : "";
  const startButton = running
    ? `<button class="btn btn--tonal btn--small" data-action="stop" ${busy ? "disabled" : ""}>${icon("stop")} Остановить</button>`
    : `<button class="btn btn--tonal btn--small" data-action="start" ${canStart ? "" : "disabled"}>${icon("play")} Запустить</button>`;
  const loginButton = needLogin
    ? `<button class="btn btn--outlined btn--small" data-action="login">${icon("key")} Войти</button>`
    : "";
  return `
    <article class="client-card" data-phone="${esc(client.phone)}">
      <div class="client-card__top">
        <span class="status status--${info.cls}"><span class="status-dot"></span>${esc(info.label)}</span>
        <button class="icon-btn" data-action="open" aria-label="Открыть конфиг">${icon("settings")}</button>
      </div>
      <h3 class="client-phone">+${esc(client.phone)}</h3>
      <p class="client-sub">
        <span class="chip">api ${esc(client.api_id ?? "—")}</span>
        <span class="chip">${client.has_session ? "сессия есть" : "нет сессии"}</span>
        <span class="chip">${client.settings_count || 0} настроек</span>
      </p>
      ${errorText}
      <div class="client-card__actions">
        ${startButton}
        <button class="btn btn--text btn--small" data-action="restart" ${canStart && !busy ? "" : "disabled"}>${icon("restart")} Рестарт</button>
        ${loginButton}
        <label class="switch" title="Запускать при старте панели">
          <input type="checkbox" data-autostart data-phone="${esc(client.phone)}" ${client.disabled ? "" : "checked"}>
          <span class="switch__track"></span>
          <span>Автостарт</span>
        </label>
      </div>
    </article>`;
}

function findClient(phone) {
  return state.clients.find((client) => client.phone === phone) || null;
}

async function clientAction(action, phone, button) {
  if (!phone) return;
  setBusy(button, true);
  try {
    await api(`/api/clients/${encodeURIComponent(phone)}/${action}`, { method: "POST" });
    const labels = { start: "Клиент запускается", stop: "Клиент остановлен", restart: "Клиент перезапускается" };
    toast(labels[action] || "Готово");
    await refreshClients(true);
    if (state.view === "client" && state.clientPhone === phone) {
      await loadClient(phone);
    }
  } catch (err) {
    toast(err.message, "error");
    if (err.message.includes("сессии")) {
      const client = findClient(phone) || state.client;
      if (client) openAddDialog({ phone: client.phone, api_id: client.api_id }, "code");
    }
    await refreshClients(true).catch(() => {});
  } finally {
    setBusy(button, false);
  }
}

async function setAutostart(phone, enabled, input) {
  if (input) input.disabled = true;
  try {
    const data = await api(`/api/clients/${encodeURIComponent(phone)}`, {
      method: "PATCH",
      body: { disabled: !enabled },
    });
    toast(enabled ? "Автостарт включён" : "Клиент отключён");
    await refreshClients(true);
    if (state.view === "client" && state.clientPhone === phone) {
      await loadClient(phone);
    }
    if (data.needs_login) {
      const client = findClient(phone) || data;
      openAddDialog({ phone: client.phone, api_id: client.api_id }, "code");
    }
  } catch (err) {
    toast(err.message, "error");
    await refreshClients(true).catch(() => {});
  } finally {
    if (input) input.disabled = false;
  }
}

async function stopAll() {
  const confirmed = await confirmDialog(
    "Остановить всех клиентов?",
    "Все запущенные клиенты будут отключены. Флаг автостарта не изменится.",
    "Остановить всех",
    true,
  );
  if (!confirmed) return;
  try {
    const data = await api("/api/clients/stop-all", { method: "POST" });
    toast(`Остановлено клиентов: ${data.stopped}`);
    await refreshClients(true);
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------------------------------------------------------------- client detail

async function loadClient(phone) {
  const previous = state.clientPhone;
  state.clientPhone = phone;
  try {
    const data = await api(`/api/clients/${encodeURIComponent(phone)}`);
    if (previous !== data.phone) state.clientTab = data.valid ? "settings" : "json";
    state.client = data;
    drawClient(data);
  } catch (err) {
    setPage("Клиент", "Не удалось загрузить", "");
    $("#view").innerHTML = alertHtml(err.message);
  }
}

function drawClient(client) {
  const info = statusInfo(client.status);
  const running = ["running", "starting", "stopping"].includes(client.status);
  const busy = ["starting", "stopping"].includes(client.status);
  const canStart = client.valid && client.has_session;
  const needLogin = client.valid && (!client.has_session || client.status === "unauthorized");
  const tab = client.valid ? state.clientTab : "json";
  state.clientTab = tab;
  setPage(
    "Клиент",
    `+${client.phone} · ${info.label}`,
    `<button class="btn btn--outlined btn--small" data-top-action="back">${icon("back")} Назад</button>`,
  );

  const actions = `
    <button class="btn btn--tonal btn--small" data-detail-action="restart" ${canStart && !busy ? "" : "disabled"}>${icon("restart")} Рестарт</button>
    ${
      running
        ? `<button class="btn btn--tonal btn--small" data-detail-action="stop" ${busy ? "disabled" : ""}>${icon("stop")} Остановить</button>`
        : `<button class="btn btn--tonal btn--small" data-detail-action="start" ${canStart ? "" : "disabled"}>${icon("play")} Запустить</button>`
    }
    ${needLogin ? `<button class="btn btn--outlined btn--small" data-detail-action="login">${icon("key")} Войти</button>` : ""}
    <label class="switch">
      <input type="checkbox" data-detail-autostart ${client.disabled ? "" : "checked"}>
      <span class="switch__track"></span>
      <span>Автостарт</span>
    </label>`;

  const meta = `
    <span class="chip">api ${esc(client.api_id ?? "—")}</span>
    <span class="chip ${client.has_session ? "chip--success" : "chip--warning"}">${client.has_session ? "сессия есть" : "нет сессии"}</span>
    <span class="chip ${client.disabled ? "chip--warning" : "chip--primary"}">${client.disabled ? "автостарт выкл." : "автостарт вкл."}</span>
    ${client.error ? `<span class="chip chip--error">есть ошибка</span>` : ""}`;

  const settingsPanel = client.valid
    ? renderSettingsPanel(client)
    : `<div class="alert">${icon("alert")}<span>${esc(client.error || "Конфиг повреждён")}. Исправьте JSON во вкладке «JSON».</span></div>`;

  $("#view").innerHTML = `
    <div class="client-detail">
      <header class="detail-head">
        <div>
          <div class="detail-title">
            <h2>+${esc(client.phone)}</h2>
            ${statusChip(client.status)}
          </div>
          <div class="detail-meta">${meta}</div>
          ${client.error ? `<p class="form-error ${client.status === "unauthorized" ? "form-error--warning" : ""}" id="client-error">${esc(client.error)}</p>` : `<p class="form-error" id="client-error" hidden></p>`}
        </div>
        <div class="detail-actions">${actions}</div>
      </header>
      <section class="panel-section">
        <div class="section-head">
          <div>
            <h3>Конфигурация</h3>
            <p>Правки сохраняются в clients/${esc(client.phone)}.json</p>
          </div>
          <div class="tabs" id="config-tabs">
            <button class="tab ${tab === "settings" ? "is-active" : ""}" data-tab="settings" ${client.valid ? "" : "disabled"}>Настройки</button>
            <button class="tab ${tab === "json" ? "is-active" : ""}" data-tab="json">JSON</button>
          </div>
        </div>
        <div id="panel-settings" ${tab === "settings" ? "" : "hidden"}>${settingsPanel}</div>
        <div id="panel-json" ${tab === "json" ? "" : "hidden"}>
          <p class="form-hint">Сырой JSON файла клиента. Кнопка «Сохранить JSON» проверит структуру перед записью.</p>
          <textarea id="json-editor" class="code-editor" spellcheck="false">${esc(client.raw || "")}</textarea>
          <div class="section-actions">
            <button id="save-json" class="btn btn--filled btn--small">${icon("check")} Сохранить JSON</button>
            <button id="format-json" class="btn btn--outlined btn--small">${icon("spark")} Форматировать</button>
          </div>
        </div>
      </section>
    </div>`;
}

function renderSettingsPanel(client) {
  const config = client.config || {};
  const values = Object.entries(config)
    .filter(([key]) => !["api_id", "api_hash", "phone", "disabled"].includes(key))
    .sort(([a], [b]) => a.localeCompare(b));
  const defaults = Object.entries(client.available_defaults || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key]) => `<option value="${esc(key)}">${esc(key)}</option>`)
    .join("");
  return `
    <div class="access-grid">
      <label class="form-field">
        <span>api_id</span>
        <input id="cfg-api-id" data-key="api_id" data-kind="number" type="number" step="1" value="${esc(config.api_id ?? "")}">
      </label>
      <label class="form-field">
        <span>api_hash</span>
        <input id="cfg-api-hash" data-key="api_hash" data-kind="string" type="text" spellcheck="false" value="${esc(config.api_hash ?? "")}">
      </label>
    </div>
    <div class="settings-grid" id="settings-grid">
      ${values.map(([key, value]) => settingRow(key, value)).join("")}
    </div>
    <div class="add-setting" id="add-setting">
      <label class="form-field">
        <span>Добавить настройку из defaults</span>
        <select id="new-setting-key"><option value="">Выберите ключ…</option>${defaults}</select>
      </label>
      <button class="btn btn--tonal btn--small" id="add-setting-btn" ${defaults ? "" : "disabled"}>${icon("plus")} Добавить</button>
    </div>
    ${noticeHtml("Токены и флаги фоновых задач применяются после перезапуска клиента. api_id/api_hash перезапускают его автоматически.")}
    <div class="section-actions">
      <button id="save-settings" class="btn btn--filled btn--small">${icon("check")} Сохранить настройки</button>
      <button id="reset-settings" class="btn btn--text btn--small">${icon("refresh")} Сбросить</button>
    </div>`;
}

function settingRow(key, value) {
  const label = `<label title="${esc(key)}">${esc(key)}</label>`;
  if (typeof value === "boolean") {
    return `<div class="setting-row setting-row--bool" data-setting="${esc(key)}">
      ${label}
      <label class="switch switch--setting">
        <input type="checkbox" data-key="${esc(key)}" data-kind="bool" ${value ? "checked" : ""}>
        <span class="switch__track"></span>
      </label>
    </div>`;
  }
  if (typeof value === "number") {
    return `<div class="setting-row" data-setting="${esc(key)}">${label}<input type="number" step="any" data-key="${esc(key)}" data-kind="number" value="${esc(value)}"></div>`;
  }
  if (typeof value === "string") {
    return `<div class="setting-row" data-setting="${esc(key)}">${label}<input type="text" data-key="${esc(key)}" data-kind="string" value="${esc(value)}"></div>`;
  }
  if (value === null) {
    return `<div class="setting-row setting-row--null" data-setting="${esc(key)}">${label}<input type="text" data-key="${esc(key)}" data-kind="null" value="" placeholder="null"><span class="setting-hint">Пусто = null, иначе строка</span></div>`;
  }
  return `<div class="setting-row" data-setting="${esc(key)}">${label}<textarea data-key="${esc(key)}" data-kind="json" spellcheck="false">${esc(JSON.stringify(value, null, 2))}</textarea></div>`;
}

function collectSettings() {
  if (!state.client?.config) throw new Error("Нет конфига для сохранения");
  const config = JSON.parse(JSON.stringify(state.client.config));
  $$("#panel-settings [data-key]").forEach((input) => {
    const key = input.dataset.key;
    const kind = input.dataset.kind;
    if (kind === "bool") {
      config[key] = input.checked;
    } else if (kind === "number") {
      const value = Number(input.value);
      if (!Number.isFinite(value)) throw new Error(`Поле ${key}: нужно число`);
      config[key] = value;
    } else if (kind === "string") {
      config[key] = input.value;
    } else if (kind === "null") {
      const value = input.value.trim();
      config[key] = !value || value === "null" ? null : value;
    } else if (kind === "json") {
      try {
        config[key] = JSON.parse(input.value);
      } catch {
        throw new Error(`Поле ${key}: некорректный JSON`);
      }
    }
  });
  return config;
}

async function saveSettings(button) {
  if (!state.clientPhone) return;
  let config;
  try {
    config = collectSettings();
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  setBusy(button, true);
  try {
    const data = await api(`/api/clients/${encodeURIComponent(state.clientPhone)}`, {
      method: "PUT",
      body: { config },
    });
    state.client = data;
    await refreshClients(true);
    drawClient(data);
    toast(data.restarted ? "Сохранено, клиент перезапущен" : "Настройки сохранены");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function saveJson(button) {
  if (!state.clientPhone) return;
  const editor = $("#json-editor");
  if (!editor) return;
  try {
    JSON.parse(editor.value);
  } catch (err) {
    toast(`Некорректный JSON: ${err.message}`, "error");
    return;
  }
  setBusy(button, true);
  try {
    const data = await api(`/api/clients/${encodeURIComponent(state.clientPhone)}`, {
      method: "PUT",
      body: { raw: editor.value },
    });
    state.client = data;
    state.clientTab = "json";
    await refreshClients(true);
    drawClient(data);
    toast(data.restarted ? "JSON сохранён, клиент перезапущен" : "JSON сохранён");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(button, false);
  }
}

function formatJson() {
  const editor = $("#json-editor");
  if (!editor) return;
  try {
    editor.value = JSON.stringify(JSON.parse(editor.value), null, 2);
    toast("JSON отформатирован");
  } catch (err) {
    toast(`Некорректный JSON: ${err.message}`, "error");
  }
}

function addSetting(key) {
  if (!key || !state.client?.available_defaults) return;
  if ($(`[data-setting="${CSS.escape(key)}"]`)) {
    toast("Такая настройка уже есть");
    return;
  }
  const value = state.client.available_defaults[key];
  const grid = $("#settings-grid");
  if (!grid) return;
  grid.insertAdjacentHTML("beforeend", settingRow(key, value));
  const select = $("#new-setting-key");
  const option = Array.from(select.options).find((item) => item.value === key);
  if (option) option.remove();
  if (!select.options.length || (select.options.length === 1 && !select.options[0].value)) {
    $("#add-setting-btn")?.setAttribute("disabled", "");
  }
  toast(`Добавлена настройка ${key}`);
}

async function refreshClientHead() {
  if (!state.clientPhone || state.view !== "client") return;
  const data = await api(`/api/clients/${encodeURIComponent(state.clientPhone)}`);
  if (!state.client) return;
  state.client.status = data.status;
  state.client.error = data.error;
  state.client.disabled = data.disabled;
  state.client.has_session = data.has_session;
  const chip = $("#client-status");
  if (chip) chip.outerHTML = statusChip(data.status);
  const error = $("#client-error");
  if (error) {
    error.className = `form-error ${data.status === "unauthorized" ? "form-error--warning" : ""}`;
    error.textContent = data.error || "";
    error.hidden = !data.error;
  }
  const toggle = $("[data-detail-autostart]");
  if (toggle && document.activeElement !== toggle) toggle.checked = !data.disabled;
}

// ---------------------------------------------------------------- logs

function connectLogs() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws/logs`);
  state.ws = socket;
  socket.addEventListener("open", () => {
    state.wsRetry = 0;
  });
  socket.addEventListener("message", (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    if (data.type === "history") {
      state.logs = (data.entries || []).slice(-2000);
      if (state.view === "logs") renderLogRows();
    } else if (data.type === "log" && data.entry) {
      const entry = data.entry;
      const last = state.logs[state.logs.length - 1];
      if (last && entry.id && last.id >= entry.id) return;
      state.logs.push(entry);
      if (state.logs.length > 2000) state.logs.shift();
      if (state.view === "logs" && !state.logPaused) scheduleLogRender();
    }
  });
  socket.addEventListener("close", () => {
    state.ws = null;
    if (!state.authenticated) return;
    const delay = Math.min(30000, 1500 * 2 ** Math.min(state.wsRetry, 4));
    state.wsRetry += 1;
    setTimeout(() => {
      if (state.authenticated && !state.ws) connectLogs();
    }, delay);
  });
}

function scheduleLogRender() {
  if (state.logRenderQueued) return;
  state.logRenderQueued = true;
  requestAnimationFrame(() => {
    state.logRenderQueued = false;
    renderLogRows();
  });
}

const LOG_RANK = { DEBUG: 0, INFO: 1, SUCCESS: 2, WARNING: 3, ERROR: 4, CRITICAL: 5 };

function filteredLogs() {
  const needle = state.logSearch.trim().toLowerCase();
  const minRank = state.logLevel === "ALL" ? -1 : LOG_RANK[state.logLevel] ?? 0;
  return state.logs.filter((entry) => {
    if (minRank >= 0 && (LOG_RANK[entry.level] ?? 0) < minRank) return false;
    if (!needle) return true;
    return `${entry.message || ""} ${entry.source || ""}`.toLowerCase().includes(needle);
  });
}

function renderLogs() {
  setPage(
    "Логи",
    "Поток loguru в реальном времени",
    `<button class="btn btn--outlined btn--small" data-top-action="clear-logs">${icon("close")} Очистить</button>`,
  );
  const levels = ["ALL", "INFO", "WARNING", "ERROR"];
  $("#view").innerHTML = `
    <div class="logs-toolbar">
      <div class="segmented" id="log-levels">
        ${levels.map((level) => `<button class="${state.logLevel === level ? "is-active" : ""}" data-log-level="${level}">${level === "ALL" ? "Все" : level}</button>`).join("")}
      </div>
      <div class="search-box">
        ${icon("search")}
        <input id="log-search" type="search" placeholder="Поиск по логам" value="${esc(state.logSearch)}">
      </div>
      <div class="logs-spacer"></div>
      <button id="log-pause" class="btn btn--outlined btn--small">
        ${state.logPaused ? icon("play") : icon("pause")} ${state.logPaused ? "Продолжить" : "Пауза"}
      </button>
    </div>
    <div class="log-list" id="log-list"></div>`;
  renderLogRows();
}

function renderLogRows() {
  const list = $("#log-list");
  if (!list) return;
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 90;
  const entries = filteredLogs().slice(-900);
  if (!entries.length) {
    list.innerHTML = `<div class="log-empty">${icon("logs")}<p>${state.logs.length ? "Ничего не найдено по фильтру" : "Пока тихо. Логи появятся здесь."}</p></div>`;
    return;
  }
  list.innerHTML = entries
    .map(
      (entry) => `
      <div class="log-row">
        <span class="log-time">${esc(entry.ts || "")}</span>
        <span class="log-level log-level--${esc(entry.level || "INFO")}">${esc(entry.level || "INFO")}</span>
        <span class="log-message">${esc(entry.message || "")}</span>
        <span class="log-source">${esc(entry.source || "")}</span>
        ${
          entry.traceback
            ? `<details class="log-trace"><summary>traceback</summary><pre>${esc(entry.traceback)}</pre></details>`
            : ""
        }
      </div>`,
    )
    .join("");
  if (atBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

function setLogLevel(level) {
  state.logLevel = level;
  $$("#log-levels button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.logLevel === level);
  });
  renderLogRows();
}

function toggleLogPause() {
  state.logPaused = !state.logPaused;
  const button = $("#log-pause");
  if (button) {
    button.innerHTML = `${state.logPaused ? icon("play") : icon("pause")} ${state.logPaused ? "Продолжить" : "Пауза"}`;
  }
  if (!state.logPaused) renderLogRows();
}

// ---------------------------------------------------------------- system

function stopSystemTimer() {
  clearInterval(state.systemTimer);
  state.systemTimer = null;
}

async function renderSystem() {
  setPage(
    "Система",
    "Хост, память, диск и сеть",
    `<button class="btn btn--outlined btn--small" data-top-action="refresh-system">${icon("refresh")} Обновить</button>`,
  );
  $("#view").innerHTML = `<div class="system-grid" id="system-grid"><div class="metric-card"><div class="metric-label">Загрузка метрик…</div></div></div>`;
  await loadSystem();
  if (state.view !== "system") return;
  stopSystemTimer();
  state.systemTimer = setInterval(() => {
    if (state.view === "system") loadSystem();
  }, 5000);
}

async function loadSystem(showError = false) {
  try {
    const data = await api("/api/system");
    state.system = data;
    const grid = $("#system-grid");
    if (grid) grid.innerHTML = systemHtml(data);
  } catch (err) {
    if (showError) toast(err.message, "error");
  }
}

function gaugeStyle(percent) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  const color = value >= 85 ? "var(--error)" : value >= 65 ? "var(--warning)" : "var(--primary)";
  return `--value:${value};--gauge-color:${color}`;
}

function systemHtml(data) {
  const cpu = data.cpu || {};
  const memory = data.memory || {};
  const disk = data.disk || {};
  const network = data.network || {};
  const clients = data.clients || {};
  return `
    <article class="metric-card">
      <div class="metric-card__head"><h3>Процессор</h3>${icon("system")}</div>
      <div class="gauge" style="${gaugeStyle(cpu.percent)}">
        <div class="gauge__inner">${Math.round(cpu.percent || 0)}%<small>CPU</small></div>
      </div>
      <div class="metric-row"><span>Ядра / потоки</span><span>${esc(cpu.physical ?? "?")} / ${esc(cpu.cores ?? "?")}</span></div>
      <div class="metric-row"><span>Частота</span><span>${cpu.freq ? `${fmtNumber(cpu.freq)} МГц` : "—"}</span></div>
      <div class="metric-row"><span>Load average</span><span>${(cpu.load || []).join(" · ") || "—"}</span></div>
    </article>
    <article class="metric-card">
      <div class="metric-card__head"><h3>Память</h3>${icon("spark")}</div>
      <div class="gauge" style="${gaugeStyle(memory.percent)}">
        <div class="gauge__inner">${Math.round(memory.percent || 0)}%<small>RAM</small></div>
      </div>
      <div class="metric-row"><span>Использовано</span><span>${fmtBytes(memory.used)}</span></div>
      <div class="metric-row"><span>Всего</span><span>${fmtBytes(memory.total)}</span></div>
      <div class="metric-row"><span>Доступно</span><span>${fmtBytes(memory.available)}</span></div>
    </article>
    <article class="metric-card">
      <div class="metric-card__head"><h3>Диск</h3>${icon("file")}</div>
      <div class="gauge" style="${gaugeStyle(disk.percent)}">
        <div class="gauge__inner">${Math.round(disk.percent || 0)}%<small>диск</small></div>
      </div>
      <div class="metric-row"><span>Использовано</span><span>${fmtBytes(disk.used)}</span></div>
      <div class="metric-row"><span>Всего</span><span>${fmtBytes(disk.total)}</span></div>
      <div class="metric-row"><span>Свободно</span><span>${fmtBytes(disk.free)}</span></div>
    </article>
    <article class="metric-card">
      <div class="metric-card__head"><h3>Хост</h3>${icon("power")}</div>
      <div class="metric-value">${esc(fmtUptime(data.uptime))}</div>
      <div class="metric-label">время работы</div>
      <div class="metric-row"><span>ОС</span><span>${esc(data.platform || "—")}</span></div>
      <div class="metric-row"><span>Python</span><span>${esc(data.python || "—")}</span></div>
      <div class="metric-row"><span>Клиентов запущено</span><span>${esc(clients.running ?? 0)} / ${esc(clients.total ?? 0)}</span></div>
    </article>
    <article class="metric-card metric-card--wide">
      <div class="metric-card__head"><h3>Сеть</h3>${icon("refresh")}</div>
      <div class="metric-row"><span>Отправлено</span><span>${fmtBytes(network.sent)}</span></div>
      <div class="metric-row"><span>Принято</span><span>${fmtBytes(network.recv)}</span></div>
      <p class="form-hint" style="margin-top:10px">Счётчики интерфейсов с момента запуска хоста. Скорость не измеряется, чтобы не создавать лишнюю нагрузку.</p>
    </article>`;
}

// ---------------------------------------------------------------- modal

function openModal({ title, subtitle = "", body = "", wide = false, onClose = null }) {
  closeModal();
  const root = document.createElement("div");
  root.className = "modal-backdrop";
  root.innerHTML = `
    <div class="modal ${wide ? "modal--wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal__head">
        <div><h2>${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>
        <button class="icon-btn" data-close-modal aria-label="Закрыть">${icon("close")}</button>
      </div>
      <div class="modal__body">${body}</div>
    </div>`;
  $("#modal-root").appendChild(root);

  const onKey = (event) => {
    if (event.key === "Escape") close();
  };
  const close = () => {
    if (!root.isConnected) return;
    root.remove();
    document.removeEventListener("keydown", onKey);
    state.modalClose = null;
    onClose?.();
  };
  root.addEventListener("click", (event) => {
    if (event.target === root || event.target.closest("[data-close-modal]")) close();
  });
  document.addEventListener("keydown", onKey);
  state.modalClose = close;
  setTimeout(() => {
    const focusable = root.querySelector("input:not([type=hidden]), textarea, select, button");
    focusable?.focus();
  }, 40);
  return { root, bodyEl: root.querySelector(".modal__body"), close };
}

function closeModal() {
  if (state.modalClose) state.modalClose();
}

function confirmDialog(title, message, confirmLabel = "Подтвердить", danger = false) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      resolve(value);
    };
    const modal = openModal({
      title,
      body: `<p class="form-hint">${esc(message)}</p>`,
      onClose: () => finish(false),
    });
    const foot = document.createElement("div");
    foot.className = "modal__foot";
    foot.innerHTML = `
      <button class="btn btn--text" data-cancel>Отмена</button>
      <button class="btn ${danger ? "btn--danger" : "btn--filled"}" data-confirm>${esc(confirmLabel)}</button>`;
    modal.root.querySelector(".modal").appendChild(foot);
    foot.querySelector("[data-cancel]").addEventListener("click", () => {
      finish(false);
      modal.close();
    });
    foot.querySelector("[data-confirm]").addEventListener("click", () => {
      finish(true);
      modal.close();
    });
  });
}

// ---------------------------------------------------------------- add client

function openAddDialog(prefill = {}, initialTab = "code") {
  const ctx = {
    prefill,
    login: null,
    poll: null,
    files: [],
    mode: initialTab,
    lastSvg: null,
  };
  const modal = openModal({
    title: "Добавить клиента",
    subtitle: "Вход по коду, QR или импорт готового JSON",
    wide: true,
    body: `
      <div class="tabs tabs--modal" id="add-tabs">
        <button class="tab" data-add-tab="code">Код</button>
        <button class="tab" data-add-tab="qr">QR-вход</button>
        <button class="tab" data-add-tab="import">Импорт JSON</button>
      </div>
      <div id="add-body"></div>`,
    onClose: () => cleanupAdd(ctx),
  });
  ctx.modal = modal;
  ctx.body = modal.bodyEl.querySelector("#add-body");
  $$("[data-add-tab]", modal.root).forEach((button) => {
    button.addEventListener("click", () => switchAddTab(ctx, button.dataset.addTab));
  });
  switchAddTab(ctx, initialTab);
}

async function switchAddTab(ctx, tab) {
  if (ctx.mode === tab && (ctx.login || ctx.body.innerHTML)) {
    setAddTabs(ctx, tab);
    return;
  }
  await cancelLogin(ctx);
  ctx.mode = tab;
  setAddTabs(ctx, tab);
  if (tab === "import") {
    renderImport(ctx);
  } else {
    renderCredentials(ctx);
  }
}

function setAddTabs(ctx, tab) {
  $$("[data-add-tab]", ctx.modal.root).forEach((button) => {
    button.classList.toggle("is-active", button.dataset.addTab === tab);
  });
}

function cleanupAdd(ctx) {
  if (ctx.poll) {
    clearInterval(ctx.poll);
    ctx.poll = null;
  }
  if (ctx.login && ctx.login.state !== "authorized") {
    fetch(`/api/logins/${ctx.login.id}`, {
      method: "DELETE",
      credentials: "same-origin",
    }).catch(() => {});
  }
  ctx.login = null;
}

async function cancelLogin(ctx) {
  if (ctx.poll) {
    clearInterval(ctx.poll);
    ctx.poll = null;
  }
  if (ctx.login && ctx.login.state !== "authorized") {
    try {
      await fetch(`/api/logins/${ctx.login.id}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
    } catch {}
  }
  ctx.login = null;
}

function showAddError(ctx, message) {
  const holder = ctx.body.querySelector("#add-error");
  if (holder) holder.innerHTML = alertHtml(message);
  else toast(message, "error");
}

function clearAddError(ctx) {
  const holder = ctx.body.querySelector("#add-error");
  if (holder) holder.innerHTML = "";
}

function loginSteps(active) {
  const steps = [
    ["creds", "Данные"],
    ["code", "Код / QR"],
    ["done", "Готово"],
  ];
  return `<div class="login-steps">${steps
    .map(([key, label], index) => {
      const order = ["creds", "code", "done"];
      const activeIndex = order.indexOf(active);
      const cls = index < activeIndex ? "is-done" : index === activeIndex ? "is-active" : "";
      return `<span class="login-step ${cls}"><span class="login-step__num">${index < activeIndex ? "✓" : index + 1}</span>${label}</span>`;
    })
    .join("")}</div>`;
}

function renderCredentials(ctx) {
  const p = ctx.prefill || {};
  ctx.body.innerHTML = `
    ${loginSteps("creds")}
    <form id="add-creds" class="form-grid" autocomplete="off">
      <label class="form-field span-2">
        <span>Телефон</span>
        <input name="phone" type="tel" inputmode="tel" placeholder="79991234567" value="${esc(p.phone || "")}" required>
      </label>
      <label class="form-field">
        <span>api_id</span>
        <input name="api_id" type="number" inputmode="numeric" placeholder="из my.telegram.org" value="${esc(p.api_id ?? "")}">
      </label>
      <label class="form-field">
        <span>api_hash</span>
        <input name="api_hash" type="text" spellcheck="false" placeholder="32 hex-символа" value="${esc(p.api_hash || "")}">
      </label>
      <p class="form-hint span-2">Для уже существующего клиента api_id и api_hash можно не заполнять — они возьмутся из конфига.</p>
      <div class="section-actions span-2">
        <button class="btn btn--filled" type="submit">${icon(ctx.mode === "qr" ? "qr" : "key")} ${ctx.mode === "qr" ? "Сгенерировать QR" : "Получить код"}</button>
      </div>
    </form>
    <div id="add-error"></div>`;
  $("#add-creds", ctx.body).addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAddError(ctx);
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector("button[type=submit]");
    setBusy(button, true);
    try {
      const data = await api("/api/logins", {
        method: "POST",
        body: {
          phone: String(form.get("phone") || "").trim(),
          api_id: String(form.get("api_id") || "").trim(),
          api_hash: String(form.get("api_hash") || "").trim(),
          method: ctx.mode === "qr" ? "qr" : "code",
        },
      });
      ctx.login = data;
      if (data.state === "qr_waiting") {
        renderQr(ctx);
        startQrPoll(ctx);
      } else {
        renderCode(ctx);
      }
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
}

function renderCode(ctx) {
  ctx.body.innerHTML = `
    ${loginSteps("code")}
    <div class="alert alert--success">${icon("check")}<span>Код отправлен на +${esc(ctx.login.phone)}. Введите его из Telegram.</span></div>
    <form id="code-form" class="form-grid" autocomplete="off" style="margin-top:16px">
      <label class="form-field span-2">
        <span>Код из Telegram</span>
        <input name="code" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="12345" required>
      </label>
      <div class="section-actions span-2">
        <button class="btn btn--filled" type="submit">${icon("check")} Войти</button>
        <button class="btn btn--text" type="button" id="resend-code">Отправить ещё раз</button>
        <button class="btn btn--text" type="button" id="back-to-creds">Назад</button>
      </div>
    </form>
    <div id="add-error"></div>`;
  $("#code-form", ctx.body).addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAddError(ctx);
    const code = String(new FormData(event.currentTarget).get("code") || "").trim();
    const button = event.currentTarget.querySelector("button[type=submit]");
    setBusy(button, true);
    try {
      const data = await api(`/api/logins/${ctx.login.id}/code`, {
        method: "POST",
        body: { code },
      });
      ctx.login = data;
      if (data.state === "password_required") {
        renderPassword(ctx, "Код принят. Аккаунт защищён паролем 2FA.");
      } else if (data.state === "authorized") {
        finishAdd(ctx, data);
      } else {
        showAddError(ctx, data.error || "Не удалось войти");
      }
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
  $("#resend-code", ctx.body).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true);
    clearAddError(ctx);
    try {
      ctx.login = await api(`/api/logins/${ctx.login.id}/resend`, { method: "POST", body: {} });
      toast("Код отправлен повторно");
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
  $("#back-to-creds", ctx.body).addEventListener("click", async () => {
    await cancelLogin(ctx);
    renderCredentials(ctx);
  });
}

function renderPassword(ctx, message) {
  ctx.body.innerHTML = `
    ${loginSteps("code")}
    <div class="alert alert--warn">${icon("key")}<span>${esc(message || "Введите пароль двухфакторной аутентификации.")}</span></div>
    <form id="password-form" class="form-grid" autocomplete="off" style="margin-top:16px">
      <label class="form-field span-2">
        <span>Пароль 2FA</span>
        <input name="password" type="password" autocomplete="current-password" placeholder="Пароль облачного аккаунта" required>
      </label>
      <div class="section-actions span-2">
        <button class="btn btn--filled" type="submit">${icon("check")} Подтвердить</button>
        <button class="btn btn--text" type="button" id="back-to-creds">Назад</button>
      </div>
    </form>
    <div id="add-error"></div>`;
  $("#password-form", ctx.body).addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAddError(ctx);
    const password = String(new FormData(event.currentTarget).get("password") || "");
    const button = event.currentTarget.querySelector("button[type=submit]");
    setBusy(button, true);
    try {
      const data = await api(`/api/logins/${ctx.login.id}/password`, {
        method: "POST",
        body: { password },
      });
      ctx.login = data;
      if (data.state === "authorized") finishAdd(ctx, data);
      else showAddError(ctx, data.error || "Не удалось войти");
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
  $("#back-to-creds", ctx.body).addEventListener("click", async () => {
    await cancelLogin(ctx);
    renderCredentials(ctx);
  });
}

function renderQr(ctx) {
  const svg = ctx.login.qr_svg || "";
  ctx.lastSvg = svg;
  ctx.body.innerHTML = `
    ${loginSteps("code")}
    <div class="qr-layout">
      <div class="qr-frame" id="qr-frame">${svg || `<span class="qr-placeholder">QR недоступен</span>`}</div>
      <div class="qr-copy">
        <h4>Сканируйте код</h4>
        <p>Откройте Telegram на телефоне и отсканируйте QR. Если 2FA включён, панель попросит пароль.</p>
        <ol>
          <li>Настройки → Устройства</li>
          <li>Подключить устройство</li>
          <li>Наведите камеру на QR</li>
        </ol>
      </div>
    </div>
    <p class="form-hint" id="qr-status" style="margin-top:14px">Ожидаю подтверждения в Telegram…</p>
    <div id="add-error"></div>
    <div class="section-actions">
      <button class="btn btn--text" type="button" id="qr-cancel">Отмена</button>
    </div>`;
  $("#qr-cancel", ctx.body).addEventListener("click", () => ctx.modal.close());
}

function startQrPoll(ctx) {
  if (ctx.poll) clearInterval(ctx.poll);
  ctx.poll = setInterval(async () => {
    if (!ctx.login || ctx.login.state === "authorized") return;
    try {
      const data = await api(`/api/logins/${ctx.login.id}`);
      ctx.login = data;
      if (data.state === "qr_waiting") {
        if (data.qr_svg && data.qr_svg !== ctx.lastSvg) {
          ctx.lastSvg = data.qr_svg;
          const frame = ctx.body.querySelector("#qr-frame");
          if (frame) frame.innerHTML = data.qr_svg;
        }
      } else if (data.state === "password_required") {
        clearInterval(ctx.poll);
        ctx.poll = null;
        renderPassword(ctx, "QR подтверждён. Введите пароль 2FA.");
      } else if (data.state === "authorized") {
        clearInterval(ctx.poll);
        ctx.poll = null;
        finishAdd(ctx, data);
      } else if (data.state === "error" || data.state === "expired") {
        clearInterval(ctx.poll);
        ctx.poll = null;
        showAddError(ctx, data.error || "Время входа истекло");
        const status = ctx.body.querySelector("#qr-status");
        if (status) status.textContent = "Вход не завершён. Закройте окно и попробуйте снова.";
      }
    } catch (err) {
      if (err.message.includes("не найден") || err.message.includes("истёк")) {
        clearInterval(ctx.poll);
        ctx.poll = null;
        showAddError(ctx, err.message);
      }
    }
  }, 2000);
}

function finishAdd(ctx, login) {
  ctx.login = login;
  if (ctx.poll) {
    clearInterval(ctx.poll);
    ctx.poll = null;
  }
  const phone = login.result_phone || login.phone;
  toast(`Клиент +${phone} добавлен`);
  ctx.modal.close();
  refreshClients(true).catch(() => {});
  navigate(`client/${encodeURIComponent(phone)}`);
}

function renderImport(ctx) {
  ctx.body.innerHTML = `
    <div class="dropzone" id="dropzone" role="button" tabindex="0">
      <input id="import-files" type="file" accept=".json,application/json" multiple hidden>
      ${icon("upload")}
      <strong>Перетащите JSON-файлы сюда</strong>
      <span>или нажмите, чтобы выбрать несколько clients/*.json</span>
    </div>
    <ul class="file-list" id="import-file-list"></ul>
    <label class="form-field" style="margin-top:16px">
      <span>Или вставьте JSON</span>
      <textarea id="import-paste" spellcheck="false" placeholder='{"phone":"79991234567","api_id":123456,"api_hash":"..."} или массив таких объектов'></textarea>
    </label>
    <p class="form-hint">Поле phone обязательно, если конфиг вставлен без имени файла. Существующие клиенты не перезаписываются.</p>
    <div class="section-actions">
      <button class="btn btn--filled" id="import-run">${icon("upload")} Импортировать</button>
    </div>
    <div class="import-results" id="import-results"></div>
    <div id="add-error"></div>`;

  const input = $("#import-files", ctx.body);
  const dropzone = $("#dropzone", ctx.body);
  const fileList = $("#import-file-list", ctx.body);

  const showFiles = () => {
    fileList.innerHTML = ctx.files
      .map((file) => `<li>${icon("file")}<span>${esc(file.name)}</span></li>`)
      .join("");
  };

  const addFiles = (files) => {
    const next = Array.from(files || []);
    for (const file of next) {
      if (!ctx.files.some((item) => item.name === file.name && item.size === file.size)) {
        ctx.files.push(file);
      }
    }
    showFiles();
  };

  input.addEventListener("change", () => addFiles(input.files));
  dropzone.addEventListener("click", (event) => {
    if (event.target !== input) input.click();
  });
  if (ctx.files.length) showFiles();
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("is-drag");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-drag"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-drag");
    addFiles(event.dataTransfer.files);
  });

  $("#import-run", ctx.body).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const holder = $("#import-results", ctx.body);
    clearAddError(ctx);
    holder.innerHTML = "";
    const items = [];
    try {
      for (const file of ctx.files) {
        items.push({ filename: file.name, content: await file.text() });
      }
      const paste = $("#import-paste", ctx.body).value.trim();
      if (paste) {
        let parsed;
        try {
          parsed = JSON.parse(paste);
        } catch (err) {
          throw new Error(`Некорректный JSON в поле вставки: ${err.message}`);
        }
        const configs = Array.isArray(parsed) ? parsed : [parsed];
        for (const config of configs) items.push({ config });
      }
      if (!items.length) throw new Error("Добавьте файлы или вставьте JSON");
      setBusy(button, true);
      const data = await api("/api/clients/import", { method: "POST", body: { items } });
      holder.innerHTML = (data.results || [])
        .map((result) => {
          if (result.ok) {
            return `<div class="import-result">${icon("check")}<div>Импортирован +${esc(result.phone)}${result.has_session ? " (сессия найдена)" : " (нужен вход)"}</div></div>`;
          }
          return `<div class="import-result import-result--error">${icon("alert")}<div>${esc(result.filename || "Конфиг")}: ${esc(result.error || "ошибка")}</div></div>`;
        })
        .join("");
      await refreshClients(true);
      const ok = (data.results || []).filter((result) => result.ok).length;
      if (ok) toast(`Импортировано: ${ok}`);
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
}

// ---------------------------------------------------------------- events

async function onViewClick(event) {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    event.preventDefault();
    event.stopPropagation();
    const card = actionButton.closest("[data-phone]");
    const phone = card?.dataset.phone || state.clientPhone;
    const action = actionButton.dataset.action;
    if (action === "add") return openAddDialog();
    if (action === "import") return openAddDialog({}, "import");
    if (action === "login") {
      const client = findClient(phone) || state.client;
      return openAddDialog(
        { phone: client?.phone, api_id: client?.api_id },
        "code",
      );
    }
    if (action === "open") return navigate(`client/${encodeURIComponent(phone)}`);
    if (["start", "stop", "restart"].includes(action)) {
      return clientAction(action, phone, actionButton);
    }
    return;
  }

  const detailAction = event.target.closest("[data-detail-action]");
  if (detailAction) {
    event.preventDefault();
    const action = detailAction.dataset.detailAction;
    if (action === "back") return navigate("clients");
    if (action === "login") {
      const client = state.client;
      return openAddDialog(
        {
          phone: client?.phone,
          api_id: client?.api_id,
          api_hash: client?.config?.api_hash,
        },
        "code",
      );
    }
    if (["start", "stop", "restart"].includes(action)) {
      return clientAction(action, state.clientPhone, detailAction);
    }
    return;
  }

  const tab = event.target.closest("[data-tab]");
  if (tab && state.client) {
    event.preventDefault();
    state.clientTab = tab.dataset.tab;
    $$("[data-tab]", $("#config-tabs")).forEach((button) => {
      button.classList.toggle("is-active", button === tab);
    });
    $("#panel-settings").hidden = state.clientTab !== "settings";
    $("#panel-json").hidden = state.clientTab !== "json";
    return;
  }

  if (event.target.closest("#save-settings")) {
    return saveSettings(event.target.closest("#save-settings"));
  }
  if (event.target.closest("#save-json")) {
    return saveJson(event.target.closest("#save-json"));
  }
  if (event.target.closest("#format-json")) {
    return formatJson();
  }
  if (event.target.closest("#reset-settings")) {
    return loadClient(state.clientPhone);
  }
  if (event.target.closest("#add-setting-btn")) {
    return addSetting($("#new-setting-key")?.value);
  }

  const logLevel = event.target.closest("[data-log-level]");
  if (logLevel) return setLogLevel(logLevel.dataset.logLevel);

  if (event.target.closest("#log-pause")) return toggleLogPause();

  const card = event.target.closest(".client-card");
  if (card && !event.target.closest("button, input, label, a")) {
    navigate(`client/${encodeURIComponent(card.dataset.phone)}`);
  }
}

function onViewChange(event) {
  const auto = event.target.closest("[data-autostart]");
  if (auto) {
    return setAutostart(auto.dataset.phone, auto.checked, auto);
  }
  const detailAuto = event.target.closest("[data-detail-autostart]");
  if (detailAuto) {
    return setAutostart(state.clientPhone, detailAuto.checked, detailAuto);
  }
}

function onViewInput(event) {
  if (event.target.id === "log-search") {
    state.logSearch = event.target.value;
    renderLogRows();
  }
}

async function onTopbarClick(event) {
  const button = event.target.closest("[data-top-action]");
  if (!button) return;
  const action = button.dataset.topAction;
  if (action === "add") return openAddDialog();
  if (action === "import") return openAddDialog({}, "import");
  if (action === "stop-all") return stopAll();
  if (action === "back") return navigate("clients");
  if (action === "clear-logs") {
    state.logs = [];
    renderLogRows();
    toast("Логи очищены");
    return;
  }
  if (action === "refresh-system") return loadSystem(true);
}

function bindEvents() {
  $("#login-form").addEventListener("submit", handleLogin);
  $("#toggle-password").addEventListener("click", () => {
    const input = $("#login-password");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    $("#toggle-password use").setAttribute("href", show ? "#i-eye-off" : "#i-eye");
    $("#toggle-password").setAttribute("aria-label", show ? "Скрыть пароль" : "Показать пароль");
  });
  $("#theme-toggle").addEventListener("click", toggleTheme);
  $("#logout-button").addEventListener("click", logout);
  $("#mobile-logout").addEventListener("click", logout);
  $$("[data-nav]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.nav));
  });
  $("#view").addEventListener("click", onViewClick);
  $("#view").addEventListener("change", onViewChange);
  $("#view").addEventListener("input", onViewInput);
  $("#topbar-actions").addEventListener("click", onTopbarClick);
  window.addEventListener("hashchange", () => {
    if (state.authenticated) route();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.authenticated) {
      if (state.view === "clients") refreshClients(true).catch(() => {});
      if (state.view === "system") loadSystem();
    }
  });
}

async function init() {
  bindEvents();
  themeIcon();
  try {
    await api("/api/me");
    await enterApp();
  } catch {
    showLogin();
  }
}

document.addEventListener("DOMContentLoaded", init);
