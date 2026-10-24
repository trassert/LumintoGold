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
  refreshTimer: null,
  systemTimer: null,
  refreshing: false,
  ws: null,
  wsRetry: 0,
  modalClose: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) =>
  Array.from(root.querySelectorAll(selector));

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));

const icon = (name) =>
  `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;

const STATUS = {
  running: { label: "Работает", tone: "success" },
  starting: { label: "Запускается", tone: "warning" },
  stopping: { label: "Останавливается", tone: "warning" },
  stopped: { label: "Остановлен", tone: "neutral" },
  disabled: { label: "Отключён", tone: "neutral" },
  unauthorized: { label: "Нужен вход", tone: "warning" },
  error: { label: "Ошибка", tone: "danger" },
  invalid: { label: "Ошибка конфига", tone: "danger" },
};

const statusInfo = (status) => STATUS[status] || STATUS.stopped;

const badge = (status) => {
  const info = statusInfo(status);
  return `<span class="badge badge--${info.tone}"><span class="badge__dot"></span>${esc(info.label)}</span>`;
};

const alertHtml = (message, tone = "error") =>
  `<div class="alert alert--${tone}">${icon(tone === "success" ? "check" : "alert")}<span>${esc(message)}</span></div>`;

const noticeHtml = (message) => `<div class="notice">${esc(message)}</div>`;

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

const fmtNumber = (value) =>
  new Intl.NumberFormat("ru-RU").format(Number(value) || 0);

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
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast is-visible${tone === "error" ? " toast--error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    element.classList.remove("is-visible");
  }, tone === "error" ? 5000 : 3200);
}

function setPage(title, subtitle, actions = "") {
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
  $("#page-actions").innerHTML = actions;
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle("is-busy", busy);
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

function themeIcon() {
  const dark = document.documentElement.dataset.theme === "dark";
  $$("#theme-toggle use, #theme-toggle-mobile use").forEach((use) => {
    use.setAttribute("href", dark ? "#i-sun" : "#i-moon");
  });
}

function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
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
  $("#login-page").hidden = false;
  $("#login-error").hidden = true;
  $("#login-password").value = "";
  setTimeout(() => $("#login-password").focus(), 40);
}

async function enterApp() {
  state.authenticated = true;
  $("#login-page").hidden = true;
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
        }
      } catch {
        // next poll will retry
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
  const button = $("#login-submit");
  const error = $("#login-error");
  error.hidden = true;
  setBusy(button, true);
  try {
    await api("/api/login", {
      method: "POST",
      body: { password: $("#login-password").value },
    });
    $("#login-form").reset();
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
  try {
    await refreshClients(false);
  } catch (err) {
    setPage("Клиенты", "Не удалось загрузить список", "");
    $("#view").innerHTML = alertHtml(err.message);
  }
}

function clientsSubtitle() {
  const total = state.counts.total || 0;
  if (!total) return "Клиентов пока нет";
  const parts = [`Всего: ${total}`];
  if (state.counts.running) parts.push(`работают: ${state.counts.running}`);
  if (state.counts.disabled) parts.push(`отключены: ${state.counts.disabled}`);
  if (state.counts.errors) parts.push(`с ошибкой: ${state.counts.errors}`);
  return parts.join(" · ");
}

function clientsActions() {
  return `
    <button class="btn btn--secondary" data-top-action="import">${icon("upload")} Импорт</button>
    <button class="btn btn--danger" data-top-action="stop-all">${icon("stop")} Остановить всех</button>
    <button class="btn btn--primary" data-top-action="add">${icon("plus")} Добавить</button>
  `;
}

function drawClients() {
  setPage("Клиенты", clientsSubtitle(), clientsActions());
  const view = $("#view");
  if (!state.clients.length) {
    view.innerHTML = `
      <div class="empty">
        <h2>Нет клиентов</h2>
        <p>Добавьте аккаунт по коду Telegram, через QR или импортируйте готовый JSON-конфиг.</p>
        <div class="empty__actions">
          <button class="btn btn--primary" data-action="add">${icon("plus")} Добавить клиента</button>
          <button class="btn btn--secondary" data-action="import">${icon("upload")} Импорт JSON</button>
        </div>
      </div>`;
    return;
  }
  view.innerHTML = `
    <div class="table-wrap">
      <table class="table clients-table">
        <thead>
          <tr>
            <th>Клиент</th>
            <th>Статус</th>
            <th>Сессия</th>
            <th>Автостарт</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${state.clients.map(clientRow).join("")}
        </tbody>
      </table>
    </div>`;
}

function clientRow(client) {
  const running = ["running", "starting", "stopping"].includes(client.status);
  const busy = ["starting", "stopping"].includes(client.status);
  const canStart = client.valid && client.has_session;
  const needLogin =
    client.valid && (!client.has_session || client.status === "unauthorized");
  const error = client.error
    ? `<span class="row-error" title="${esc(client.error)}">${esc(client.error)}</span>`
    : "";
  const runtimeButton = running
    ? `<button class="btn btn--secondary" data-action="stop" ${busy ? "disabled" : ""}>${icon("stop")} Стоп</button>`
    : `<button class="btn btn--secondary" data-action="start" ${canStart ? "" : "disabled"}>${icon("play")} Старт</button>`;
  return `
    <tr data-phone="${esc(client.phone)}">
      <td data-label="" class="client-cell">
        <strong>+${esc(client.phone)}</strong>
        <span>api_id ${esc(client.api_id ?? "—")}${client.valid ? "" : " · конфиг повреждён"}</span>
        ${error}
      </td>
      <td data-label="Статус">${badge(client.status)}</td>
      <td data-label="Сессия" class="cell-muted">${client.has_session ? "Есть" : "Нет"}</td>
      <td data-label="Автостарт">
        <label class="switch">
          <input type="checkbox" data-autostart data-phone="${esc(client.phone)}" ${client.disabled ? "" : "checked"}>
          <span class="switch__box"></span>
        </label>
      </td>
      <td data-label="">
        <div class="row-actions">
          <button class="btn btn--ghost" data-action="open">Открыть</button>
          ${runtimeButton}
          <button class="btn btn--ghost" data-action="restart" ${canStart && !busy ? "" : "disabled"}>${icon("restart")} Рестарт</button>
          ${needLogin ? `<button class="btn btn--ghost" data-action="login">${icon("key")} Войти</button>` : ""}
        </div>
      </td>
    </tr>`;
}

function findClient(phone) {
  return state.clients.find((client) => client.phone === phone) || null;
}

async function clientAction(action, phone, button) {
  if (!phone) return;
  setBusy(button, true);
  try {
    await api(`/api/clients/${encodeURIComponent(phone)}/${action}`, {
      method: "POST",
    });
    const labels = {
      start: "Клиент запускается",
      stop: "Клиент остановлен",
      restart: "Клиент перезапускается",
    };
    toast(labels[action] || "Готово");
    await refreshClients(true);
    if (state.view === "client" && state.clientPhone === phone) {
      await loadClient(phone);
    }
  } catch (err) {
    toast(err.message, "error");
    if (err.message.includes("сессии")) {
      const client = findClient(phone) || state.client;
      if (client) {
        openAddDialog("code", {
          phone: client.phone,
          api_id: client.api_id,
          api_hash: client.config?.api_hash,
        });
      }
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
      openAddDialog("code", {
        phone: client.phone,
        api_id: client.api_id,
      });
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
    "Запущенные клиенты будут остановлены. Флаг автостарта не изменится.",
    "Остановить",
  );
  if (!confirmed) return;
  try {
    const data = await api("/api/clients/stop-all", { method: "POST" });
    toast(`Остановлено: ${data.stopped}`);
    await refreshClients(true);
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------------------------------------------------------------- detail

async function loadClient(phone) {
  const previous = state.clientPhone;
  state.clientPhone = phone;
  try {
    const data = await api(`/api/clients/${encodeURIComponent(phone)}`);
    if (previous !== data.phone) {
      state.clientTab = data.valid ? "settings" : "json";
    }
    state.client = data;
    drawClient(data);
  } catch (err) {
    setPage("Клиент", "Не удалось загрузить", "");
    $("#view").innerHTML = alertHtml(err.message);
  }
}

function drawClient(client) {
  const running = ["running", "starting", "stopping"].includes(client.status);
  const busy = ["starting", "stopping"].includes(client.status);
  const canStart = client.valid && client.has_session;
  const needLogin =
    client.valid && (!client.has_session || client.status === "unauthorized");
  const tab = client.valid ? state.clientTab : "json";
  state.clientTab = tab;
  setPage("Клиент", "");

  const error = client.error
    ? `<div style="margin-bottom:16px">${alertHtml(
        client.error,
        client.status === "unauthorized" ? "warning" : "error",
      )}</div>`
    : "";

  const actions = `
    ${
      running
        ? `<button class="btn btn--secondary" data-detail-action="stop" ${busy ? "disabled" : ""}>${icon("stop")} Остановить</button>`
        : `<button class="btn btn--secondary" data-detail-action="start" ${canStart ? "" : "disabled"}>${icon("play")} Запустить</button>`
    }
    <button class="btn btn--secondary" data-detail-action="restart" ${canStart && !busy ? "" : "disabled"}>${icon("restart")} Перезапустить</button>
    ${needLogin ? `<button class="btn btn--primary" data-detail-action="login">${icon("key")} Войти</button>` : ""}`;

  const accessFields = client.valid
    ? `
      <div class="form-field">
        <span>api_id</span>
        <input data-key="api_id" data-kind="number" type="number" step="1" value="${esc(client.config?.api_id ?? "")}">
      </div>
      <div class="form-field">
        <span>api_hash</span>
        <input data-key="api_hash" data-kind="string" type="text" spellcheck="false" value="${esc(client.config?.api_hash ?? "")}">
      </div>`
    : `<p class="form-hint">Доступ появится после исправления JSON.</p>`;

  $("#view").innerHTML = `
    <div class="page-head">
      <div>
        <div class="breadcrumb">
          <button data-detail-action="back">Клиенты</button>
          <span>/</span>
          <span>+${esc(client.phone)}</span>
        </div>
        <h2>+${esc(client.phone)} ${badge(client.status)}</h2>
      </div>
      <div class="page-head__actions">${actions}</div>
    </div>
    ${error}
    <div class="detail-layout">
      <div class="stack">
        <section class="panel">
          <div class="tabs" id="config-tabs">
            <button class="tab ${tab === "settings" ? "is-active" : ""}" data-tab="settings" ${client.valid ? "" : "disabled"}>Настройки</button>
            <button class="tab ${tab === "json" ? "is-active" : ""}" data-tab="json">JSON</button>
          </div>
          <div id="panel-settings" class="tab-panel" ${tab === "settings" ? "" : "hidden"}>
            ${client.valid ? renderSettings(client) : ""}
          </div>
          <div id="panel-json" class="tab-panel" ${tab === "json" ? "" : "hidden"}>
            <p class="form-hint" style="margin-bottom:10px">Сырой JSON файла клиента. Перед записью структура проверяется.</p>
            <textarea id="json-editor" class="code-editor" spellcheck="false">${esc(client.raw || "")}</textarea>
            <div class="form-actions">
              <button id="save-json" class="btn btn--primary">${icon("check")} Сохранить JSON</button>
              <button id="format-json" class="btn btn--secondary">Форматировать</button>
            </div>
          </div>
        </section>
      </div>
      <div class="stack">
        <section class="panel">
          <div class="side-section" id="access-section" ${tab === "json" ? "hidden" : ""}>
            <h4>Доступ</h4>
            ${accessFields}
          </div>
          <div class="side-section">
            <h4>Сессия</h4>
            <div class="meta-list">
              <div class="meta-row"><span>Файл сессии</span><span>${client.has_session ? "Есть" : "Нет"}</span></div>
              <div class="meta-row"><span>Автостарт</span><span>${client.disabled ? "Выключен" : "Включён"}</span></div>
            </div>
          </div>
          <div class="side-section">
            <h4>Автостарт</h4>
            <div class="side-switch">
              <span class="muted">Запускать при старте панели</span>
              <label class="switch">
                <input type="checkbox" data-detail-autostart ${client.disabled ? "" : "checked"}>
                <span class="switch__box"></span>
              </label>
            </div>
          </div>
        </section>
      </div>
    </div>`;
}

function renderSettings(client) {
  const config = client.config || {};
  const keys = Object.entries(config)
    .filter(([key]) => !["api_id", "api_hash", "phone", "disabled"].includes(key))
    .sort(([a], [b]) => a.localeCompare(b));
  const defaults = Object.entries(client.available_defaults || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key]) => `<option value="${esc(key)}">${esc(key)}</option>`)
    .join("");
  return `
    ${
      keys.length
        ? `<div class="settings-list" id="settings-list">${keys.map(([key, value]) => settingRow(key, value)).join("")}</div>`
        : `<div class="settings-list" id="settings-list"><p class="form-hint" style="padding:12px 0">Дополнительных настроек нет. Добавьте нужные из списка ниже.</p></div>`
    }
    <div class="add-setting">
      <label class="form-field">
        <span>Добавить настройку</span>
        <select id="new-setting-key"><option value="">Выберите ключ</option>${defaults}</select>
      </label>
      <button class="btn btn--secondary" id="add-setting-btn" ${defaults ? "" : "disabled"}>${icon("plus")} Добавить</button>
    </div>
    ${noticeHtml("Токены и флаги фоновых задач применяются после перезапуска клиента. api_id/api_hash перезапускают его автоматически.")}
    <div class="form-actions">
      <button class="btn btn--secondary" id="reset-settings">Сбросить</button>
      <button class="btn btn--primary" id="save-settings">${icon("check")} Сохранить</button>
    </div>`;
}

function settingRow(key, value) {
  const label = `<div class="setting__key">${esc(key)}</div>`;
  if (typeof value === "boolean") {
    return `<div class="setting" data-setting="${esc(key)}">
      ${label}
      <div class="setting__control setting__control--switch">
        <label class="switch">
          <input type="checkbox" data-key="${esc(key)}" data-kind="bool" ${value ? "checked" : ""}>
          <span class="switch__box"></span>
        </label>
      </div>
    </div>`;
  }
  if (typeof value === "number") {
    return `<div class="setting" data-setting="${esc(key)}">
      ${label}
      <div class="setting__control"><input type="number" step="any" data-key="${esc(key)}" data-kind="number" value="${esc(value)}"></div>
    </div>`;
  }
  if (typeof value === "string") {
    return `<div class="setting" data-setting="${esc(key)}">
      ${label}
      <div class="setting__control"><input type="text" data-key="${esc(key)}" data-kind="string" value="${esc(value)}"></div>
    </div>`;
  }
  if (value === null) {
    return `<div class="setting" data-setting="${esc(key)}">
      ${label}
      <div class="setting__control">
        <input type="text" data-key="${esc(key)}" data-kind="null" value="" placeholder="null">
        <span class="setting__hint">Пустое значение означает null.</span>
      </div>
    </div>`;
  }
  return `<div class="setting" data-setting="${esc(key)}">
    ${label}
    <div class="setting__control"><textarea data-key="${esc(key)}" data-kind="json" spellcheck="false">${esc(JSON.stringify(value, null, 2))}</textarea></div>
  </div>`;
}

function collectSettings() {
  if (!state.client?.config) throw new Error("Нет конфигурации");
  const config = JSON.parse(JSON.stringify(state.client.config));
  $$("#view [data-key]").forEach((input) => {
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
    const data = await api(
      `/api/clients/${encodeURIComponent(state.clientPhone)}`,
      { method: "PUT", body: { config } },
    );
    state.client = data;
    await refreshClients(true);
    drawClient(data);
    toast(data.restarted ? "Сохранено, клиент перезапущен" : "Сохранено");
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
    const data = await api(
      `/api/clients/${encodeURIComponent(state.clientPhone)}`,
      { method: "PUT", body: { raw: editor.value } },
    );
    state.client = data;
    state.clientTab = "json";
    await refreshClients(true);
    drawClient(data);
    toast(data.restarted ? "Сохранено, клиент перезапущен" : "JSON сохранён");
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
  const list = $("#settings-list");
  if (!list) return;
  list.insertAdjacentHTML("beforeend", settingRow(key, value));
  const select = $("#new-setting-key");
  const option = Array.from(select.options).find((item) => item.value === key);
  if (option) option.remove();
  if (
    !select.options.length ||
    (select.options.length === 1 && !select.options[0].value)
  ) {
    $("#add-setting-btn")?.setAttribute("disabled", "");
  }
  toast(`Добавлена настройка ${key}`);
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

const LOG_RANK = {
  DEBUG: 0,
  INFO: 1,
  SUCCESS: 2,
  WARNING: 3,
  ERROR: 4,
  CRITICAL: 5,
};

function filteredLogs() {
  const needle = state.logSearch.trim().toLowerCase();
  const minRank =
    state.logLevel === "ALL" ? -1 : LOG_RANK[state.logLevel] ?? 0;
  return state.logs.filter((entry) => {
    if (minRank >= 0 && (LOG_RANK[entry.level] ?? 0) < minRank) return false;
    if (!needle) return true;
    return `${entry.message || ""} ${entry.source || ""}`
      .toLowerCase()
      .includes(needle);
  });
}

function renderLogs() {
  setPage(
    "Логи",
    "Поток событий в реальном времени",
    `<button class="btn btn--secondary" data-top-action="clear-logs">Очистить</button>`,
  );
  const levels = [
    ["ALL", "Все уровни"],
    ["INFO", "INFO и выше"],
    ["WARNING", "WARNING и выше"],
    ["ERROR", "ERROR и выше"],
  ];
  $("#view").innerHTML = `
    <div class="toolbar">
      <select id="log-level" aria-label="Уровень логов">
        ${levels
          .map(
            ([value, label]) =>
              `<option value="${value}" ${state.logLevel === value ? "selected" : ""}>${label}</option>`,
          )
          .join("")}
      </select>
      <label class="search-field">
        ${icon("search")}
        <input id="log-search" type="search" placeholder="Поиск" value="${esc(state.logSearch)}" aria-label="Поиск по логам">
      </label>
      <span class="toolbar-spacer"></span>
      <button id="log-pause" class="btn btn--secondary">
        ${state.logPaused ? icon("play") : icon("pause")} ${state.logPaused ? "Продолжить" : "Пауза"}
      </button>
    </div>
    <div class="log-box"><div class="log-list" id="log-list"></div></div>`;
  renderLogRows();
}

function renderLogRows() {
  const list = $("#log-list");
  if (!list) return;
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  const entries = filteredLogs().slice(-900);
  if (!entries.length) {
    list.innerHTML = `<div class="log-empty">${state.logs.length ? "Ничего не найдено" : "Логов пока нет"}</div>`;
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
  if (atBottom) list.scrollTop = list.scrollHeight;
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
    "Состояние хоста",
    `<button class="btn btn--secondary" data-top-action="refresh-system">${icon("refresh")} Обновить</button>`,
  );
  $("#view").innerHTML =
    '<div class="stats-grid" id="system-grid"><div class="stat-card"><div class="stat-card__title">Загрузка…</div></div></div>';
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
    const grid = $("#system-grid");
    if (grid) grid.innerHTML = systemHtml(data);
  } catch (err) {
    if (showError) toast(err.message, "error");
  }
}

function barClass(percent) {
  const value = Number(percent) || 0;
  if (value >= 85) return "bar__fill bar__fill--danger";
  if (value >= 70) return "bar__fill bar__fill--warning";
  return "bar__fill";
}

function bar(percent) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  return `<div class="bar"><div class="${barClass(value)}" style="width:${value}%"></div></div>`;
}

function systemHtml(data) {
  const cpu = data.cpu || {};
  const memory = data.memory || {};
  const disk = data.disk || {};
  const network = data.network || {};
  const clients = data.clients || {};
  return `
    <article class="stat-card">
      <div class="stat-card__title">Процессор</div>
      <div class="stat-card__value">${Math.round(cpu.percent || 0)}%<small> загрузка</small></div>
      ${bar(cpu.percent)}
      <div class="kv"><span>Ядра / потоки</span><span>${esc(cpu.physical ?? "?")} / ${esc(cpu.cores ?? "?")}</span></div>
      <div class="kv"><span>Частота</span><span>${cpu.freq ? `${fmtNumber(cpu.freq)} МГц` : "—"}</span></div>
      <div class="kv"><span>Load average</span><span>${(cpu.load || []).join(" · ") || "—"}</span></div>
    </article>
    <article class="stat-card">
      <div class="stat-card__title">Память</div>
      <div class="stat-card__value">${Math.round(memory.percent || 0)}%<small> занято</small></div>
      ${bar(memory.percent)}
      <div class="kv"><span>Использовано</span><span>${fmtBytes(memory.used)}</span></div>
      <div class="kv"><span>Всего</span><span>${fmtBytes(memory.total)}</span></div>
      <div class="kv"><span>Доступно</span><span>${fmtBytes(memory.available)}</span></div>
    </article>
    <article class="stat-card">
      <div class="stat-card__title">Диск</div>
      <div class="stat-card__value">${Math.round(disk.percent || 0)}%<small> занято</small></div>
      ${bar(disk.percent)}
      <div class="kv"><span>Использовано</span><span>${fmtBytes(disk.used)}</span></div>
      <div class="kv"><span>Всего</span><span>${fmtBytes(disk.total)}</span></div>
      <div class="kv"><span>Свободно</span><span>${fmtBytes(disk.free)}</span></div>
    </article>
    <article class="stat-card">
      <div class="stat-card__title">Хост</div>
      <div class="stat-card__value">${esc(fmtUptime(data.uptime))}</div>
      <div class="stat-note" style="margin-top:-4px;margin-bottom:10px">время работы</div>
      <div class="kv"><span>ОС</span><span>${esc(data.platform || "—")}</span></div>
      <div class="kv"><span>Python</span><span>${esc(data.python || "—")}</span></div>
      <div class="kv"><span>Клиентов запущено</span><span>${esc(clients.running ?? 0)} / ${esc(clients.total ?? 0)}</span></div>
    </article>
    <article class="stat-card">
      <div class="stat-card__title">Сеть</div>
      <div class="kv"><span>Отправлено</span><span>${fmtBytes(network.sent)}</span></div>
      <div class="kv"><span>Принято</span><span>${fmtBytes(network.recv)}</span></div>
      <p class="stat-note">Счётчики интерфейсов с момента запуска хоста. Скорость не измеряется, чтобы не создавать лишнюю нагрузку.</p>
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
    if (event.target === root || event.target.closest("[data-close-modal]")) {
      close();
    }
  });
  document.addEventListener("keydown", onKey);
  state.modalClose = close;
  setTimeout(() => {
    root
      .querySelector("input:not([type=hidden]), textarea, select, button")
      ?.focus();
  }, 30);
  return { root, bodyEl: root.querySelector(".modal__body"), close };
}

function closeModal() {
  if (state.modalClose) state.modalClose();
}

function confirmDialog(title, message, confirmLabel = "Подтвердить") {
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
      <button class="btn btn--secondary" data-cancel>Отмена</button>
      <button class="btn btn--danger-filled" data-confirm>${esc(confirmLabel)}</button>`;
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

async function fetchLoginOptions() {
  try {
    return await api("/api/login-options");
  } catch {
    return { has_credentials: false, source: null };
  }
}

async function openAddDialog(initialTab = "code", prefill = {}) {
  const ctx = {
    tab: initialTab,
    prefill,
    login: null,
    poll: null,
    files: [],
    forceCreds: false,
    options: { has_credentials: false, source: null },
  };
  const modal = openModal({
    title: "Добавить клиента",
    subtitle: "Вход по коду, QR или импорт конфигурации",
    wide: true,
    body: '<p class="form-hint">Загрузка…</p>',
    onClose: () => cleanupAdd(ctx),
  });
  ctx.modal = modal;
  ctx.body = modal.bodyEl;
  ctx.options = await fetchLoginOptions();
  if (!modal.root.isConnected) return;
  renderAdd(ctx, initialTab);
}

function renderAdd(ctx, tab) {
  if (tab !== ctx.tab) cancelLogin(ctx);
  ctx.tab = tab;
  ctx.body.innerHTML = `
    <div class="dialog-tabs" id="add-tabs">
      <button class="dialog-tab ${tab === "code" ? "is-active" : ""}" data-add-tab="code">По коду</button>
      <button class="dialog-tab ${tab === "qr" ? "is-active" : ""}" data-add-tab="qr">QR-код</button>
      <button class="dialog-tab ${tab === "import" ? "is-active" : ""}" data-add-tab="import">Импорт</button>
    </div>
    <div id="add-content"></div>`;
  $$("[data-add-tab]", ctx.body).forEach((button) => {
    button.addEventListener("click", () => renderAdd(ctx, button.dataset.addTab));
  });
  if (tab === "code") renderCodeForm(ctx);
  else if (tab === "qr") renderQrForm(ctx);
  else renderImport(ctx);
}

function credentialsSourceLabel(ctx) {
  return ctx.options.source ? `Источник: ${ctx.options.source}` : "";
}

function renderCredentialFields(ctx) {
  if (ctx.options.has_credentials && !ctx.forceCreds) {
    return `
      <div class="credentials-note form-field--full">
        <span>api_id и api_hash не нужны. ${esc(credentialsSourceLabel(ctx))}.</span>
        <button type="button" id="show-creds">Указать другие</button>
      </div>`;
  }
  return `
    <label class="form-field">
      <span>api_id</span>
      <input name="api_id" type="number" inputmode="numeric" value="${esc(ctx.prefill.api_id ?? "")}" placeholder="из my.telegram.org">
    </label>
    <label class="form-field">
      <span>api_hash</span>
      <input name="api_hash" type="text" spellcheck="false" value="${esc(ctx.prefill.api_hash ?? "")}" placeholder="32 hex-символа">
    </label>
    ${
      ctx.options.has_credentials
        ? `<div class="credentials-note form-field--full"><span>Можно оставить пустым — будут использованы сохранённые данные.</span><button type="button" id="hide-creds">Скрыть</button></div>`
        : `<p class="form-hint form-field--full">Нужны api_id/api_hash приложения с my.telegram.org: панель ещё не знает ни одного клиента.</p>`
    }`;
}

function captureCodeForm(ctx) {
  const form = $("#add-code-form");
  if (!form) return;
  const data = new FormData(form);
  ctx.prefill.phone = String(data.get("phone") || ctx.prefill.phone || "");
  ctx.prefill.api_id = String(data.get("api_id") || ctx.prefill.api_id || "");
  ctx.prefill.api_hash = String(data.get("api_hash") || ctx.prefill.api_hash || "");
}

function renderCodeForm(ctx) {
  ctx.body.querySelector("#add-content").innerHTML = `
    <form id="add-code-form" class="form-grid" autocomplete="off">
      <label class="form-field form-field--full">
        <span>Телефон</span>
        <input name="phone" type="tel" inputmode="tel" value="${esc(ctx.prefill.phone || "")}" placeholder="79991234567" required>
      </label>
      ${renderCredentialFields(ctx)}
      <div id="add-error" class="form-field--full"></div>
      <div class="form-actions form-field--full">
        <button class="btn btn--primary" type="submit">Получить код</button>
      </div>
    </form>`;
  $("#show-creds")?.addEventListener("click", () => {
    captureCodeForm(ctx);
    ctx.forceCreds = true;
    renderCodeForm(ctx);
  });
  $("#hide-creds")?.addEventListener("click", () => {
    captureCodeForm(ctx);
    ctx.forceCreds = false;
    renderCodeForm(ctx);
  });
  $("#add-code-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAddError(ctx);
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector("button[type=submit]");
    const body = {
      phone: String(form.get("phone") || "").trim(),
      method: "code",
    };
    ctx.prefill.phone = body.phone;
    if (ctx.forceCreds || !ctx.options.has_credentials) {
      body.api_id = String(form.get("api_id") || "").trim();
      body.api_hash = String(form.get("api_hash") || "").trim();
      ctx.prefill.api_id = body.api_id;
      ctx.prefill.api_hash = body.api_hash;
    }
    setBusy(button, true);
    try {
      const data = await api("/api/logins", { method: "POST", body });
      ctx.login = data;
      if (data.state === "password_required") {
        renderPasswordStep(ctx, "Аккаунт защищён паролем 2FA.", "code");
      } else {
        renderCodeStep(ctx);
      }
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
}

function renderCodeStep(ctx) {
  ctx.body.querySelector("#add-content").innerHTML = `
    <div class="alert alert--info">${icon("key")}<span>Код отправлен на +${esc(ctx.login.phone)}.</span></div>
    <form id="code-step-form" class="form-grid" autocomplete="off" style="margin-top:14px">
      <label class="form-field form-field--full">
        <span>Код из Telegram</span>
        <input name="code" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="12345" required>
      </label>
      <div id="add-error" class="form-field--full"></div>
      <div class="form-actions form-field--full">
        <button class="btn btn--secondary" type="button" id="code-back">Назад</button>
        <button class="btn btn--secondary" type="button" id="code-resend">Отправить ещё раз</button>
        <button class="btn btn--primary" type="submit">Войти</button>
      </div>
    </form>`;
  $("#code-step-form").addEventListener("submit", async (event) => {
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
        renderPasswordStep(ctx, "Аккаунт защищён паролем 2FA.", "code");
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
  $("#code-resend").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    clearAddError(ctx);
    setBusy(button, true);
    try {
      ctx.login = await api(`/api/logins/${ctx.login.id}/resend`, {
        method: "POST",
        body: {},
      });
      toast("Код отправлен повторно");
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
  $("#code-back").addEventListener("click", () => {
    cancelLogin(ctx);
    renderAdd(ctx, "code");
  });
}

function renderPasswordStep(ctx, message, origin = "code") {
  ctx.passwordOrigin = origin;
  ctx.body.querySelector("#add-content").innerHTML = `
    <div class="alert alert--warning">${icon("key")}<span>${esc(message || "Введите пароль 2FA.")}</span></div>
    <form id="password-step-form" class="form-grid" autocomplete="off" style="margin-top:14px">
      <label class="form-field form-field--full">
        <span>Пароль 2FA</span>
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <div id="add-error" class="form-field--full"></div>
      <div class="form-actions form-field--full">
        <button class="btn btn--secondary" type="button" id="password-back">Назад</button>
        <button class="btn btn--primary" type="submit">Подтвердить</button>
      </div>
    </form>`;
  $("#password-step-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearAddError(ctx);
    const password = String(
      new FormData(event.currentTarget).get("password") || "",
    );
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
  $("#password-back").addEventListener("click", () => {
    cancelLogin(ctx);
    renderAdd(ctx, ctx.passwordOrigin === "qr" ? "qr" : "code");
  });
}

function renderQrForm(ctx) {
  const container = ctx.body.querySelector("#add-content");
  if (!ctx.options.has_credentials) {
    container.innerHTML = `
      ${alertHtml(
        "Нет api_id/api_hash приложения. Укажите их на вкладке «По коду» или в telegram.api_id/api_hash (configs/config.yml).",
        "warning",
      )}
      <p class="form-hint" style="margin-top:12px">QR-вход требует api_id/api_hash приложения на уровне Telegram. Панель не может сгенерировать QR без них.</p>`;
    return;
  }
  container.innerHTML = `
    <div class="credentials-note">
      <span>api_id и api_hash не нужны. ${esc(credentialsSourceLabel(ctx))}.</span>
    </div>
    <p class="form-hint">Нажмите «Сгенерировать QR» и отсканируйте код в Telegram. Номер аккаунта определится автоматически.</p>
    <div id="add-error"></div>
    <div class="form-actions">
      <button class="btn btn--primary" id="qr-generate">${icon("qr")} Сгенерировать QR</button>
    </div>`;
  $("#qr-generate").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    clearAddError(ctx);
    setBusy(button, true);
    try {
      const data = await api("/api/logins", {
        method: "POST",
        body: { method: "qr" },
      });
      ctx.login = data;
      renderQrStep(ctx);
      startQrPoll(ctx);
    } catch (err) {
      showAddError(ctx, err.message);
    } finally {
      setBusy(button, false);
    }
  });
}

function renderQrStep(ctx) {
  const svg = ctx.login.qr_svg || "";
  ctx.body.querySelector("#add-content").innerHTML = `
    <div class="qr-layout">
      <div class="qr-frame" id="qr-frame">${svg || '<span class="qr-placeholder">QR недоступен</span>'}</div>
      <div class="qr-copy">
        <h4>Сканируйте код</h4>
        <p>Откройте Telegram → Настройки → Устройства → Подключить устройство.</p>
        <ol>
          <li>Наведите камеру на QR.</li>
          <li>Подтвердите вход на телефоне.</li>
          <li>Если включён 2FA, введите пароль здесь.</li>
        </ol>
      </div>
    </div>
    <p class="qr-status" id="qr-status">Ожидаю подтверждения…</p>
    <div id="add-error"></div>
    <div class="form-actions">
      <button class="btn btn--secondary" type="button" id="qr-cancel">Отмена</button>
    </div>`;
  $("#qr-cancel").addEventListener("click", () => ctx.modal.close());
  ctx.lastSvg = svg;
}

function startQrPoll(ctx) {
  if (ctx.poll) clearInterval(ctx.poll);
  const loginId = ctx.login?.id;
  if (!loginId) return;
  ctx.poll = setInterval(async () => {
    if (!ctx.login || ctx.login.id !== loginId || ctx.login.state === "authorized") return;
    try {
      const data = await api(`/api/logins/${loginId}`);
      if (!ctx.login || ctx.login.id !== loginId) return;
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
        renderPasswordStep(ctx, "QR подтверждён. Введите пароль 2FA.", "qr");
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
  ctx.body.querySelector("#add-content").innerHTML = `
    <div class="dropzone" id="dropzone" role="button" tabindex="0">
      <input id="import-files" type="file" accept=".json,application/json" multiple hidden>
      ${icon("upload")}
      <strong>Перетащите JSON-файлы</strong>
      <span>или нажмите, чтобы выбрать несколько файлов</span>
    </div>
    <ul class="file-list" id="import-file-list"></ul>
    <label class="form-field" style="margin-top:14px">
      <span>Или вставьте JSON</span>
      <textarea id="import-paste" spellcheck="false" placeholder='{"phone":"79991234567","api_id":123456,"api_hash":"..."}'></textarea>
    </label>
    <p class="form-hint">Поле phone обязательно, если конфиг вставлен без имени файла. Существующие клиенты не перезаписываются.</p>
    <div id="add-error"></div>
    <div class="form-actions">
      <button class="btn btn--primary" id="import-run">${icon("upload")} Импортировать</button>
    </div>
    <div class="import-results" id="import-results"></div>`;
  const input = $("#import-files", ctx.body);
  const dropzone = $("#dropzone", ctx.body);
  const fileList = $("#import-file-list", ctx.body);

  const showFiles = () => {
    fileList.innerHTML = ctx.files
      .map((file) => `<li>${icon("file")}<span>${esc(file.name)}</span></li>`)
      .join("");
  };
  const addFiles = (files) => {
    for (const file of Array.from(files || [])) {
      if (
        !ctx.files.some(
          (item) => item.name === file.name && item.size === file.size,
        )
      ) {
        ctx.files.push(file);
      }
    }
    showFiles();
  };
  input.addEventListener("change", () => addFiles(input.files));
  dropzone.addEventListener("click", (event) => {
    if (event.target !== input) input.click();
  });
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
  if (ctx.files.length) showFiles();

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
          throw new Error(`Некорректный JSON: ${err.message}`);
        }
        for (const config of Array.isArray(parsed) ? parsed : [parsed]) {
          items.push({ config });
        }
      }
      if (!items.length) throw new Error("Добавьте файлы или вставьте JSON");
      setBusy(button, true);
      const data = await api("/api/clients/import", {
        method: "POST",
        body: { items },
      });
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

function showAddError(ctx, message) {
  const holder = ctx.body.querySelector("#add-error");
  if (holder) holder.innerHTML = alertHtml(message);
  else toast(message, "error");
}

function clearAddError(ctx) {
  const holder = ctx.body.querySelector("#add-error");
  if (holder) holder.innerHTML = "";
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

function cancelLogin(ctx) {
  if (ctx.poll) {
    clearInterval(ctx.poll);
    ctx.poll = null;
  }
  const login = ctx.login;
  ctx.login = null;
  if (login && login.state !== "authorized") {
    fetch(`/api/logins/${login.id}`, {
      method: "DELETE",
      credentials: "same-origin",
    }).catch(() => {});
  }
}

// ---------------------------------------------------------------- events

async function onViewClick(event) {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    event.preventDefault();
    event.stopPropagation();
    const row = actionButton.closest("[data-phone]");
    const phone = row?.dataset.phone || state.clientPhone;
    const action = actionButton.dataset.action;
    if (action === "add") return openAddDialog("code");
    if (action === "import") return openAddDialog("import");
    if (action === "login") {
      const client = findClient(phone) || state.client;
      return openAddDialog("code", {
        phone: client?.phone,
        api_id: client?.api_id,
        api_hash: client?.config?.api_hash,
      });
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
      return openAddDialog("code", {
        phone: client?.phone,
        api_id: client?.api_id,
        api_hash: client?.config?.api_hash,
      });
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
    const accessSection = $("#access-section");
    if (accessSection) accessSection.hidden = state.clientTab !== "settings";
    return;
  }

  if (event.target.closest("#save-settings")) {
    return saveSettings(event.target.closest("#save-settings"));
  }
  if (event.target.closest("#save-json")) {
    return saveJson(event.target.closest("#save-json"));
  }
  if (event.target.closest("#format-json")) return formatJson();
  if (event.target.closest("#reset-settings")) {
    return loadClient(state.clientPhone);
  }
  if (event.target.closest("#add-setting-btn")) {
    return addSetting($("#new-setting-key")?.value);
  }
  if (event.target.closest("#log-pause")) return toggleLogPause();
  if (event.target.closest("[data-top-action]")) return;

  const row = event.target.closest(".clients-table tbody tr");
  if (row && !event.target.closest("button, input, label, a")) {
    navigate(`client/${encodeURIComponent(row.dataset.phone)}`);
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
  if (event.target.id === "log-level") {
    state.logLevel = event.target.value;
    renderLogRows();
  }
}

function onViewInput(event) {
  if (event.target.id === "log-search") {
    state.logSearch = event.target.value;
    renderLogRows();
  }
}

async function onPageAction(event) {
  const button = event.target.closest("[data-top-action]");
  if (!button) return;
  const action = button.dataset.topAction;
  if (action === "add") return openAddDialog("code");
  if (action === "import") return openAddDialog("import");
  if (action === "stop-all") return stopAll();
  if (action === "refresh-system") return loadSystem(true);
  if (action === "clear-logs") {
    state.logs = [];
    renderLogRows();
    toast("Логи очищены");
  }
}

function bindEvents() {
  $("#login-form").addEventListener("submit", handleLogin);
  $("#toggle-password").addEventListener("click", () => {
    const input = $("#login-password");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    $("#toggle-password use").setAttribute(
      "href",
      show ? "#i-eye-off" : "#i-eye",
    );
    $("#toggle-password").setAttribute(
      "aria-label",
      show ? "Скрыть пароль" : "Показать пароль",
    );
  });
  $$("#theme-toggle, #theme-toggle-mobile").forEach((button) => {
    button.addEventListener("click", toggleTheme);
  });
  $$("#logout-button, #logout-mobile").forEach((button) => {
    button.addEventListener("click", logout);
  });
  $$("[data-nav]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.nav));
  });
  $("#view").addEventListener("click", onViewClick);
  $("#view").addEventListener("change", onViewChange);
  $("#view").addEventListener("input", onViewInput);
  $("#page-actions").addEventListener("click", onPageAction);
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
    const session = await api("/api/session");
    if (session.authenticated) await enterApp();
    else showLogin();
  } catch {
    showLogin();
  }
}

document.addEventListener("DOMContentLoaded", init);
