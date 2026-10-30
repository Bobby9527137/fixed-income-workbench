"use strict";

const POLL_INTERVAL_MS = 2000;
const RECENT_INTERVAL_MS = 15000;
const RETRY_DELAY_MS = 10000;
const RECENT_TIMEOUT_MS = 8000;
const MAX_RECENT_FILES = 8;
const MAX_ERROR_LINES = 3;
const OUTPUT_DIR_KEY = "输出";

const STATE_LABELS = Object.freeze({
  stopped: "已停止",
  starting: "启动中",
  running: "运行中",
  stopping: "正在停止",
  error: "出错",
  unknown: "状态未知",
});

const KNOWN_TOOL_STATES = new Set([
  "stopped",
  "starting",
  "running",
  "stopping",
  "error",
]);

const LEGACY_HINT = "检测到你手动开的旧实例（8501），建议先关掉";

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "short",
  timeStyle: "short",
  hour12: false,
});

class ApiError extends Error {
  constructor(message, options) {
    super(message);
    this.name = "ApiError";
    this.network = Boolean(options && options.network);
  }
}

let elements = {};
let lastState = null;
let lastTools = [];
let lastLegacy = false;
let toolOrderKey = null;
let selectedToolId = null;
let stateRequestInFlight = false;
let stateRefreshQueued = false;
let recentRequestInFlight = false;
let retryNotBefore = 0;
let exited = false;
let lastBootstrapErrorKey = "";
let fileHintPath = "";

const cards = new Map();
const pendingActions = new Map();
const startingSince = new Map();

function init() {
  cacheElements();
  bindEvents();
  refreshState();
  loadRecent();
  window.setInterval(refreshState, POLL_INTERVAL_MS);
  window.setInterval(loadRecent, RECENT_INTERVAL_MS);
}

function cacheElements() {
  elements = {
    statusSummary: document.getElementById("status-summary"),
    startAll: document.getElementById("start-all"),
    stopAll: document.getElementById("stop-all"),
    rebuildEnvs: document.getElementById("rebuild-envs"),
    exitButton: document.getElementById("exit-workbench"),
    notice: document.getElementById("notice"),
    noticeText: document.getElementById("notice-text"),
    noticeClose: document.getElementById("notice-close"),
    bootstrap: document.getElementById("bootstrap-progress"),
    bootstrapSteps: document.getElementById("bootstrap-steps"),
    toolList: document.getElementById("tool-list"),
    toolEmpty: document.getElementById("tool-empty"),
    reservedStage: document.querySelector(".reserved-stage"),
    recentFiles: document.getElementById("recent-files"),
    fileHint: document.getElementById("file-hint"),
    openDir: document.getElementById("open-dir"),
    dirHint: document.getElementById("dir-hint"),
    logDialog: document.getElementById("log-dialog"),
    logTitle: document.getElementById("log-title"),
    logText: document.getElementById("log-text"),
    logClose: document.getElementById("log-close"),
    selfcheckButton: document.getElementById("workbench-selfcheck"),
    selfcheckDialog: document.getElementById("selfcheck-dialog"),
    selfcheckList: document.getElementById("selfcheck-list"),
    selfcheckReport: document.getElementById("selfcheck-report"),
  };
}

function bindEvents() {
  elements.exitButton.addEventListener("click", exitWorkbench);
  elements.selfcheckButton.addEventListener("click", runWorkbenchSelfcheck);
  elements.startAll.addEventListener("click", () => bulkAction("start"));
  elements.stopAll.addEventListener("click", () => bulkAction("stop"));
  elements.rebuildEnvs.addEventListener("click", rebuildBrokenEnvs);
  elements.noticeClose.addEventListener("click", () => clearNotice());
  elements.openDir.addEventListener("click", openOutputDir);
  elements.logClose.addEventListener("click", (event) => {
    // 老浏览器没有 <dialog>.showModal：form method="dialog" 不会关闭，
    // 这里用 open 属性兜底。
    if (typeof elements.logDialog.showModal !== "function") {
      event.preventDefault();
      closeLogDialog();
    }
  });
}

async function requestJSON(path, options) {
  const config = Object.assign({ cache: "no-store" }, options || {});
  let response;
  try {
    response = await fetch(path, config);
  } catch (error) {
    throw new ApiError("连接不上工作台，工作台可能已退出。", { network: true });
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }

  if (!response.ok || !payload || payload.ok !== true) {
    const message =
      payload && typeof payload.error === "string" && payload.error
        ? payload.error
        : `请求失败（HTTP ${response.status}）`;
    throw new ApiError(message);
  }
  return payload.data;
}

async function requestText(path) {
  let response;
  try {
    response = await fetch(path, { cache: "no-store" });
  } catch (error) {
    throw new ApiError("连接不上工作台，工作台可能已退出。", { network: true });
  }

  const text = await response.text();
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = JSON.parse(text);
      if (payload && typeof payload.error === "string" && payload.error) {
        message = payload.error;
      }
    } catch (error) {
      message = `请求失败（HTTP ${response.status}）`;
    }
    throw new ApiError(message);
  }
  return text;
}

async function refreshState() {
  if (exited) return;
  if (stateRequestInFlight) {
    stateRefreshQueued = true;
    return;
  }
  if (Date.now() < retryNotBefore) return;

  stateRequestInFlight = true;
  try {
    const data = await requestJSON("/api/state");
    if (exited) return;
    clearNotice("network");
    applyState(data);
  } catch (error) {
    if (exited) return;
    handleLoadError(error, "读取工作台状态失败");
  } finally {
    stateRequestInFlight = false;
    const queued = stateRefreshQueued;
    stateRefreshQueued = false;
    if (queued && !exited) refreshState();
  }
}

function handleLoadError(error, prefix) {
  if (exited) return;
  const message = error instanceof Error ? error.message : "未知错误";
  if (error instanceof ApiError && error.network) {
    setSummary("工作台未连接");
    showNotice(`${prefix}：${message} 10 秒后自动重试。`, "network");
    retryNotBefore = Date.now() + RETRY_DELAY_MS;
    return;
  }
  showNotice(`${prefix}：${message}。`, "error");
}

function applyState(data) {
  if (exited) return;
  lastState = data && typeof data === "object" ? data : {};
  const workbench =
    lastState.workbench && typeof lastState.workbench === "object"
      ? lastState.workbench
      : {};
  const pid = Number.isInteger(workbench.pid) ? workbench.pid : null;
  const port = Number.isInteger(workbench.port) ? workbench.port : null;
  const tools = Array.isArray(lastState.tools) ? lastState.tools : [];
  const running = tools.filter((tool) => normalizeState(tool.state) === "running").length;
  const envs = Object.entries(lastState.environments || {}).filter(
    ([key]) => key !== "python"
  );
  const ready = envs.filter(([, value]) => value && value.state === "ready").length;
  setSummary(
    `工作台运行中 · ${running}/${tools.length} 运行 · 环境 ${ready}/${envs.length} · PID ${
      pid === null ? "—" : pid
    } · 端口 ${port === null ? "—" : port}`
  );
  const broken = envs.some(([, value]) => value && value.state === "error");
  if (elements.rebuildEnvs) {
    elements.rebuildEnvs.hidden = !broken;
    elements.rebuildEnvs.disabled = exited;
  }
  renderBootstrap(lastState.environments);
  renderTools(tools, lastState.legacy_streamlit === true);
}

function setSummary(text) {
  setText(elements.statusSummary, text);
}

function renderTools(tools, legacy) {
  lastTools = tools;
  lastLegacy = legacy;

  const ids = tools.map((tool) => String(tool.id));
  const orderKey = ids.join("\u0001");
  if (orderKey !== toolOrderKey) {
    toolOrderKey = orderKey;
    rebuildToolList(tools);
  }

  elements.toolEmpty.hidden = tools.length !== 0;
  tools.forEach((tool) => updateCard(tool, legacy));

  if (
    selectedToolId !== null &&
    !tools.some((tool) => String(tool.id) === selectedToolId)
  ) {
    selectedToolId = null;
  }
  updateSelectionClasses();
}

function rebuildToolList(tools) {
  const fragment = document.createDocumentFragment();
  cards.clear();
  tools.forEach((tool) => {
    const card = createCard(tool);
    cards.set(String(tool.id), card);
    fragment.append(card.element);
  });
  elements.toolList.replaceChildren(fragment);
}

function createCard(tool) {
  const toolId = String(tool.id);

  const card = document.createElement("article");
  card.className = "tool-card";
  card.dataset.toolId = toolId;
  card.tabIndex = 0;
  card.setAttribute("role", "group");

  const head = document.createElement("div");
  head.className = "tool-head";

  const name = document.createElement("h3");
  name.className = "tool-name";

  const status = document.createElement("div");
  status.className = "tool-status";
  const dot = document.createElement("span");
  dot.className = "status-dot";
  dot.setAttribute("aria-hidden", "true");
  const stateText = document.createElement("span");
  stateText.className = "tool-state";
  status.append(dot, stateText);
  head.append(name, status);

  const desc = document.createElement("p");
  desc.className = "tool-desc";

  const meta = document.createElement("div");
  meta.className = "tool-meta";
  const port = document.createElement("span");
  port.className = "tool-port";
  const owned = document.createElement("span");
  owned.className = "tool-owned";
  owned.hidden = true;
  meta.append(port, owned);

  const errorBox = document.createElement("div");
  errorBox.className = "tool-error";
  errorBox.hidden = true;
  const errorText = document.createElement("p");
  errorText.className = "tool-error-text";
  const errorActions = document.createElement("div");
  errorActions.className = "tool-error-actions";
  const logButton = document.createElement("button");
  logButton.type = "button";
  logButton.className = "btn btn-small";
  logButton.dataset.action = "logs";
  logButton.textContent = "查看日志";
  errorActions.append(logButton);
  errorBox.append(errorText, errorActions);

  const actions = document.createElement("div");
  actions.className = "tool-actions";

  const legacy = document.createElement("p");
  legacy.className = "tool-legacy";
  legacy.textContent = LEGACY_HINT;
  legacy.hidden = true;

  card.append(head, desc, meta, errorBox, actions, legacy);
  card.addEventListener("click", (event) => onCardClick(event, toolId));
  card.addEventListener("keydown", (event) => {
    if (event.target !== card) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    selectTool(toolId);
  });

  return {
    element: card,
    name,
    desc,
    dot,
    stateText,
    port,
    owned,
    errorBox,
    errorText,
    actions,
    legacy,
    actionsSignature: "",
  };
}

function onCardClick(event, toolId) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target ? target.closest("button[data-action]") : null;
  if (button) {
    event.preventDefault();
    handleAction(toolId, button.dataset.action || "", button);
    return;
  }
  if (target && target.closest("button, a, input, select, textarea, label")) {
    return;
  }
  // 没有内嵌窗口了：点卡片正文等价于「选中 + 打开」，未运行则提示先启动。
  selectTool(toolId);
}

function updateCard(tool, legacy) {
  const toolId = String(tool.id);
  const refs = cards.get(toolId);
  if (!refs) return;

  const state = normalizeState(tool.state);
  const description =
    typeof tool.desc === "string" ? tool.desc.trim() : "";
  const errorMessage = typeof tool.error === "string" ? tool.error.trim() : "";
  const external = tool.owned === "external";
  const orphan = tool.owned === "orphan";

  setText(refs.name, displayName(tool));
  refs.element.setAttribute(
    "aria-label",
    `${displayName(tool)}，按回车选择工具`
  );
  setText(refs.desc, description);
  refs.desc.hidden = description === "";
  setText(refs.stateText, STATE_LABELS[state] || STATE_LABELS.unknown);
  refs.dot.className = `status-dot status-${state}`;
  setText(refs.port, `端口 ${formatPort(tool.port)}`);

  refs.owned.hidden = !external && !orphan;
  setText(
    refs.owned,
    external ? "外部实例（不可停）" : orphan ? "上次残留（可停）" : ""
  );

  const showError = state === "error";
  refs.errorBox.hidden = !showError;
  if (showError) {
    const tail = tailLines(errorMessage, MAX_ERROR_LINES);
    setText(refs.errorText, tail || "工具启动失败，请查看日志。");
  }

  refs.legacy.hidden = !legacy;

  if (state === "starting") {
    if (!startingSince.has(toolId)) {
      startingSince.set(toolId, Date.now());
    }
  } else {
    startingSince.delete(toolId);
  }

  const seconds = state === "starting" ? startingSeconds(tool) : 0;
  const pending = pendingActions.get(toolId) || "";
  const signature = [
    state,
    pending,
    String(seconds),
    String(tool.owned || ""),
    String(tool.url || ""),
  ].join("|");

  if (refs.actionsSignature !== signature) {
    refs.actionsSignature = signature;
    renderActions(refs.actions, tool, {
      toolId,
      state,
      external,
      seconds,
      pending,
    });
  }
}

function renderActions(container, tool, context) {
  const buttons = [];

  function add(label, action, options) {
    const settings = options || {};
    const button = document.createElement("button");
    button.type = "button";
    button.className = `btn ${settings.style || ""}`.trim();
    button.textContent = label;
    button.dataset.action = action;
    button.dataset.toolId = context.toolId;
    if (settings.disabled) button.disabled = true;
    if (settings.title) button.title = settings.title;
    buttons.push(button);
  }

  const externalTitle =
    "外部实例由你手动启动，工作台无法停止；请回到原来的终端关闭。";

  if (context.pending === "start") {
    add("正在启动…", "none", { disabled: true, style: "btn-primary" });
  } else if (context.pending === "stop") {
    add("正在停止…", "none", { disabled: true, style: "btn-danger" });
  } else if (context.state === "stopped" || context.state === "unknown") {
    add("启动", "start", { style: "btn-primary" });
  } else if (context.state === "starting") {
    add(`已等待 ${context.seconds} 秒`, "none", {
      disabled: true,
      style: "btn-primary",
    });
  } else if (context.state === "stopping") {
    add("正在停止…", "none", { disabled: true, style: "btn-danger" });
  } else if (context.state === "error") {
    add("重试", "start", { style: "btn-primary" });
    add("停止", "stop", {
      disabled: context.external,
      style: "btn-danger",
      title: context.external ? externalTitle : "",
    });
  } else if (context.state === "running") {
    if (context.external) {
      add("打开", "open", { style: "btn-primary" });
      add("停止", "stop", {
        disabled: true,
        style: "btn-danger",
        title: externalTitle,
      });
    } else {
      add("停止", "stop", { style: "btn-danger" });
      add("打开", "open", { style: "btn-primary" });
    }
  }

  // 次级操作：日志与产物目录（不占主按钮的位置）。
  add("日志", "logs", { style: "btn-small btn-quiet" });
  if (
    tool &&
    tool.dirs &&
    typeof tool.dirs === "object" &&
    Object.keys(tool.dirs).some((key) => key.includes("输出"))
  ) {
    add("目录", "reveal-output", { style: "btn-small btn-quiet" });
  }

  container.replaceChildren(...buttons);
}

async function handleAction(toolId, action, button) {
  if (exited) return;
  if (!action || action === "none") return;
  if (action === "open") {
    openTool(toolId);
    return;
  }
  if (action === "logs") {
    await showLogs(toolId);
    return;
  }
  if (action === "reveal-output" || action === "reveal-log") {
    await revealToolPath(toolId, action === "reveal-log" ? "log" : "output");
    return;
  }
  if (action !== "start" && action !== "stop") return;
  if (pendingActions.has(toolId)) return;

  const tool = findTool(toolId);
  if (action === "stop" && tool && tool.owned === "external") {
    showNotice(
      "外部实例由你手动启动，工作台无法停止；请回到原来的终端关闭。",
      "info"
    );
    return;
  }

  pendingActions.set(toolId, action);
  if (button) {
    button.disabled = true;
    button.textContent = action === "start" ? "正在启动…" : "正在停止…";
  }

  try {
    await requestJSON(
      `/api/tools/${encodeURIComponent(toolId)}/${action}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }
    );
    if (exited) return;
    pendingActions.delete(toolId);
    clearNotice();
    if (action === "start") startingSince.set(toolId, Date.now());
    await refreshState();
  } catch (error) {
    pendingActions.delete(toolId);
    if (exited) return;
    const message = error instanceof Error ? error.message : "未知错误";
    showNotice(
      action === "start" ? `启动失败：${message}` : `停止失败：${message}`,
      "error"
    );
  } finally {
    pendingActions.delete(toolId);
    if (!exited && lastState) {
      renderTools(lastTools, lastLegacy);
    }
  }
}

// 卡片选中只用于高亮与“输出目录”的归属，不再承载 iframe。
function selectTool(toolId) {
  if (exited) return;
  const tool = findTool(toolId);
  if (!tool) return;
  selectedToolId = String(tool.id);
  updateSelectionClasses();
  openTool(toolId);
}

function updateSelectionClasses() {
  cards.forEach((refs, toolId) => {
    const selected = toolId === selectedToolId;
    refs.element.classList.toggle("is-selected", selected);
    if (selected) {
      refs.element.setAttribute("aria-current", "true");
    } else {
      refs.element.removeAttribute("aria-current");
    }
  });
}

async function revealToolPath(toolId, what, name) {
  const params = new URLSearchParams({ what: what || "output" });
  if (name) params.set("name", name);
  try {
    const data = await requestJSON(
      `/api/tools/${encodeURIComponent(toolId)}/reveal?${params.toString()}`,
      { method: "POST" }
    );
    if (exited) return null;
    return data;
  } catch (error) {
    if (exited) return null;
    const message = error instanceof Error ? error.message : "未知错误";
    showNotice(`打开目录失败：${message}`, "error");
    return null;
  }
}

async function bulkAction(kind) {
  if (exited) return;
  const button = kind === "start" ? elements.startAll : elements.stopAll;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = kind === "start" ? "启动中…" : "停止中…";
  try {
    await requestJSON(
      kind === "start" ? "/api/tools/start-all" : "/api/tools/stop-all",
      { method: "POST" }
    );
  } catch (error) {
    if (!exited) {
      const message = error instanceof Error ? error.message : "未知错误";
      showNotice(`${kind === "start" ? "启动" : "停止"}失败：${message}`, "error");
    }
  } finally {
    if (!exited) {
      button.disabled = false;
      button.textContent = label;
      await refreshState();
    }
  }
}

async function rebuildBrokenEnvs() {
  if (exited) return;
  const envs = Object.entries(lastState?.environments || {}).filter(
    ([key, value]) => key !== "python" && value && ["error", "missing"].includes(value.state)
  );
  if (envs.length === 0) {
    showNotice("没有需要重建的环境。", "info");
    return;
  }
  const button = elements.rebuildEnvs;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "重建中…";
  try {
    for (const [envId] of envs) {
      button.textContent = `重建 ${envId}…`;
      await requestJSON(`/api/envs/${encodeURIComponent(envId)}/rebuild`, {
        method: "POST",
      });
      if (exited) return;
    }
    showNotice("环境已重建。", "info");
  } catch (error) {
    if (!exited) {
      const message = error instanceof Error ? error.message : "未知错误";
      showNotice(`重建环境失败：${message}`, "error");
    }
  } finally {
    if (!exited) {
      button.disabled = false;
      button.textContent = label;
      await refreshState();
    }
  }
}

function openTool(toolId) {
  const tool = findTool(toolId);
  if (
    !tool ||
    normalizeState(tool.state) !== "running" ||
    typeof tool.url !== "string" ||
    !tool.url
  ) {
    showNotice(
      "工具尚未运行，请启动并等待状态变为“运行中”后再打开。",
      "info"
    );
    return;
  }
  window.open(toolPageUrl(tool), "_blank", "noopener");
}

// 后端快照的 url 是健康检查地址（Streamlit 为 /_stcore/health），
// 打开新标签页时要换成应用根地址。
function toolPageUrl(tool) {
  const raw = tool && typeof tool.url === "string" ? tool.url : "";
  if (!raw) return "";

  let url;
  try {
    url = new URL(raw);
  } catch (error) {
    return "";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return "";

  let path = url.pathname || "/";
  if (/\/_stcore\/health\/?$/.test(path)) {
    path = path.replace(/\/_stcore\/health\/?$/, "/");
  }
  if (!path.endsWith("/")) path += "/";

  url.search = "";
  url.hash = "";
  url.pathname = path;
  return url.toString();
}

async function showLogs(toolId) {
  const tool = findTool(toolId);
  const name = tool ? displayName(tool) : toolId;
  setText(elements.logTitle, `${name} · 日志（最后 200 行）`);
  setText(elements.logText, "正在读取日志…");
  openLogDialog();

  try {
    const text = await requestText(
      `/api/logs/${encodeURIComponent(toolId)}?lines=200`
    );
    if (exited) return;
    setText(elements.logText, text.trim() ? text : "（日志为空）");
  } catch (error) {
    if (exited) return;
    const message = error instanceof Error ? error.message : "未知错误";
    setText(elements.logText, `读取日志失败：${message}`);
    showNotice(`读取日志失败：${message}`, "error");
  }
}

function openLogDialog() {
  if (typeof elements.logDialog.showModal === "function") {
    if (!elements.logDialog.open) elements.logDialog.showModal();
  } else {
    elements.logDialog.setAttribute("open", "");
  }
}

function closeLogDialog() {
  elements.logDialog.removeAttribute("open");
}

function openSelfcheckDialog() {
  if (typeof elements.selfcheckDialog.showModal === "function") {
    if (!elements.selfcheckDialog.open) elements.selfcheckDialog.showModal();
  } else {
    elements.selfcheckDialog.setAttribute("open", "");
  }
}

function downloadBase64(name, base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name || "自检报告.md";
  link.click();
  URL.revokeObjectURL(url);
}

async function runWorkbenchSelfcheck() {
  const button = elements.selfcheckButton;
  button.disabled = true;
  try {
    const payload = await requestJSON("/api/selfcheck?fix=1");
    if (exited) return;
    if (!payload || payload.ok === false) {
      throw new Error((payload && payload.error) || "自检失败");
    }
    const data = payload.data || {};
    elements.selfcheckList.replaceChildren();
    (data.checks || []).forEach((check) => {
      const item = document.createElement("div");
      item.className = "selfcheck-item";
      const dot = document.createElement("span");
      dot.className = "selfcheck-dot " + (check.status || "failed");
      const body = document.createElement("div");
      const name = document.createElement("div");
      name.textContent = check.name || "";
      const detail = document.createElement("div");
      detail.className = "selfcheck-detail";
      detail.textContent = check.detail || "";
      body.appendChild(name);
      body.appendChild(detail);
      item.appendChild(dot);
      item.appendChild(body);
      elements.selfcheckList.appendChild(item);
    });
    elements.selfcheckReport.hidden = true;
    elements.selfcheckReport.replaceChildren();
    if (data.report) {
      elements.selfcheckReport.hidden = false;
      const title = document.createElement("div");
      title.textContent = "已生成问题报告：" + (data.report.path || data.report.name);
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = "下载报告";
      link.addEventListener("click", (event) => {
        event.preventDefault();
        downloadBase64(data.report.name, data.report.base64);
      });
      const note = document.createElement("div");
      note.textContent = "请先查看，确认后再转发给维护者。";
      elements.selfcheckReport.appendChild(title);
      elements.selfcheckReport.appendChild(link);
      elements.selfcheckReport.appendChild(note);
    }
    openSelfcheckDialog();
  } catch (error) {
    showNotice(error.message || "自检失败");
  } finally {
    button.disabled = false;
  }
}

function renderBootstrap(environments) {
  const envs =
    environments && typeof environments === "object" ? environments : {};
  const keys = Object.keys(envs);
  const envKeys = keys.filter((key) => key !== "python");
  const busyStates = new Set(["missing", "extracting", "installing"]);
  const hasError = keys.some(
    (key) => normalizeEnvState(envs[key] && envs[key].state) === "error"
  );
  const anyBusy = keys.some((key) =>
    busyStates.has(normalizeEnvState(envs[key] && envs[key].state))
  );

  if (!anyBusy && !hasError) {
    elements.bootstrap.hidden = true;
    elements.bootstrapSteps.replaceChildren();
    lastBootstrapErrorKey = "";
    return;
  }

  elements.bootstrap.hidden = false;

  const pythonEntry = environmentEntry(envs.python);
  const envAId = envKeys[0] || "";
  const envBId = envKeys[1] || "";
  const envA = environmentEntry(envs[envAId]);
  const envB = environmentEntry(envs[envBId]);

  const allReady =
    pythonEntry.state === "ready" &&
    envKeys.every(
      (key) => environmentEntry(envs[key]).state === "ready"
    );
  const doneEnvs = envKeys.filter(
    (key) => environmentEntry(envs[key]).state === "ready"
  ).length;
  const finalState = allReady ? "done" : hasError ? "failed" : "active";
  const finalDetail = allReady
    ? "全部环境已就绪"
    : hasError
    ? "初始化未完成，请检查错误"
    : `正在准备环境（${doneEnvs}/${envKeys.length}）`;
  const finalProgress = allReady
    ? 100
    : envKeys.length
    ? Math.round((doneEnvs / envKeys.length) * 100)
    : 0;

  const steps = [
    {
      title: "解压解释器",
      kind: stepKind(pythonEntry.state),
      detail: pythonEntry.detail || "等待内置解释器",
      progress: pythonEntry.progress,
    },
    {
      title: "建环境 A",
      kind: envAId ? stepKind(envA.state) : "",
      detail: envAId
        ? `${envAId}：${envA.detail || "等待环境"}`
        : "未配置环境 A",
      progress: envAId ? envA.progress : 0,
    },
    {
      title: "建环境 B",
      kind: envBId ? stepKind(envB.state) : "",
      detail: envBId
        ? `${envBId}：${envB.detail || "等待环境"}`
        : "未配置环境 B",
      progress: envBId ? envB.progress : 0,
    },
    {
      title: "就绪",
      kind: finalState,
      detail: finalDetail,
      progress: finalProgress,
    },
  ];

  const fragment = document.createDocumentFragment();
  steps.forEach((step) => fragment.append(createBootstrapStep(step)));
  elements.bootstrapSteps.replaceChildren(fragment);

  const errorKey = hasError
    ? keys
        .filter(
          (key) => normalizeEnvState(envs[key] && envs[key].state) === "error"
        )
        .map((key) => {
          const entry = environmentEntry(envs[key]);
          return `${key}:${entry.detail}`;
        })
        .join("|")
    : "";

  if (errorKey && errorKey !== lastBootstrapErrorKey) {
    const first = keys.find(
      (key) => normalizeEnvState(envs[key] && envs[key].state) === "error"
    );
    const entry = environmentEntry(envs[first]);
    showNotice(
      `环境初始化失败：${entry.detail || `${first} 未能就绪`}`,
      "error"
    );
    lastBootstrapErrorKey = errorKey;
  } else if (!errorKey) {
    lastBootstrapErrorKey = "";
  }
}

function createBootstrapStep(step) {
  const item = document.createElement("li");
  item.className = "bootstrap-step";
  if (step.kind) item.classList.add(`is-${step.kind}`);

  const dot = document.createElement("span");
  dot.className = "step-dot";
  dot.setAttribute("aria-hidden", "true");

  const body = document.createElement("div");
  body.className = "step-body";

  const title = document.createElement("span");
  title.className = "step-title";
  title.textContent = step.title;

  const detail = document.createElement("span");
  detail.className = "step-detail";
  detail.textContent = step.detail;

  const track = document.createElement("div");
  track.className = "progress-track";
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", "100");
  track.setAttribute("aria-valuenow", String(step.progress));
  track.setAttribute("aria-label", `${step.title}进度`);

  const bar = document.createElement("div");
  bar.className = "progress-bar";
  bar.style.width = `${step.progress}%`;
  track.append(bar);

  body.append(title, detail, track);
  item.append(dot, body);
  item.setAttribute("aria-label", `${step.title}：${step.detail}`);
  return item;
}

function environmentEntry(raw) {
  const entry = raw && typeof raw === "object" ? raw : {};
  return {
    state: normalizeEnvState(entry.state),
    detail: typeof entry.detail === "string" ? entry.detail : "",
    progress: clampProgress(entry.progress),
  };
}

function normalizeEnvState(value) {
  const known = new Set(["missing", "extracting", "installing", "ready", "error"]);
  return known.has(value) ? value : "missing";
}

function stepKind(state) {
  if (state === "ready") return "done";
  if (state === "error") return "failed";
  return "active";
}

function clampProgress(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.min(100, Math.max(0, Math.round(number)));
}

async function loadRecent() {
  if (exited || recentRequestInFlight) return;

  recentRequestInFlight = true;
  const controller =
    typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller
    ? window.setTimeout(() => controller.abort(), RECENT_TIMEOUT_MS)
    : 0;

  try {
    const data = await requestJSON(
      "/api/files/recent",
      controller ? { signal: controller.signal } : undefined
    );
    if (exited) return;
    renderRecent(data);
  } catch (error) {
    if (exited) return;
    if (error instanceof ApiError && error.network) {
      return;
    }
    elements.recentFiles.replaceChildren(createEmptyLine("最近产物读取失败"));
    const message = error instanceof Error ? error.message : "未知错误";
    showNotice(`读取最近产物失败：${message}`, "error");
  } finally {
    if (timer) window.clearTimeout(timer);
    recentRequestInFlight = false;
  }
}

function renderRecent(data) {
  if (exited) return;

  const byTool =
    data && data.by_tool && typeof data.by_tool === "object" ? data.by_tool : null;
  elements.recentFiles.replaceChildren();

  if (!byTool) {
    // 兼容旧后端：仍按单个列表渲染。
    const files =
      data && Array.isArray(data.files)
        ? data.files.slice(0, MAX_RECENT_FILES)
        : [];
    const dir = data && typeof data.dir === "string" ? data.dir : "";
    if (files.length === 0) {
      elements.recentFiles.append(createEmptyLine("还没有输出文件"));
      return;
    }
    const fragment = document.createDocumentFragment();
    files.forEach((file) => fragment.append(recentItem(file, dir)));
    elements.recentFiles.append(fragment);
    return;
  }

  const fragment = document.createDocumentFragment();
  let shown = 0;
  Object.entries(byTool).forEach(([toolId, entry]) => {
    const files =
      entry && Array.isArray(entry.files)
        ? entry.files.slice(0, MAX_RECENT_FILES)
        : [];
    const header = document.createElement("li");
    header.className = "recent-group";
    const title = document.createElement("span");
    title.className = "recent-group-title";
    title.textContent = entry && entry.name ? entry.name : toolId;
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "btn btn-small btn-quiet";
    reveal.textContent = "在 Finder 中显示";
    reveal.addEventListener("click", () => revealToolPath(toolId, "output"));
    header.append(title, reveal);
    fragment.append(header);

    if (files.length === 0) {
      fragment.append(createEmptyLine("暂无输出"));
      return;
    }
    shown += 1;
    files.forEach((file) =>
      fragment.append(recentItem(file, entry && entry.dir ? entry.dir : "", toolId))
    );
  });

  if (shown === 0) {
    fragment.append(createEmptyLine("还没有输出文件"));
  }
  elements.recentFiles.append(fragment);
}

function recentItem(file, dir, toolId) {
  const name = file && typeof file.name === "string" ? file.name : "";
  const item = document.createElement("li");
  item.className = "recent-item";
  if (!name) return item;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "recent-name";
  button.textContent = name;
  button.title = "在 Finder 中定位";
  button.addEventListener("click", async () => {
    const fullPath = joinPath(dir, name);
    fileHintPath = fullPath;
    setText(elements.fileHint, `完整路径：${fullPath}`);
    elements.fileHint.title = fullPath;
    if (toolId) {
      await revealToolPath(toolId, "output", name);
      if (exited) return;
    }
  });

  const meta = document.createElement("span");
  meta.className = "recent-meta";
  meta.textContent = `${formatSize(file.size)} · ${formatTime(file.mtime)}`;
  item.append(button, meta);
  return item;
}

function clearFileHint() {
  fileHintPath = "";
  setText(elements.fileHint, "");
  elements.fileHint.removeAttribute("title");
}

function createEmptyLine(text) {
  const item = document.createElement("li");
  item.className = "empty-line";
  item.textContent = text;
  return item;
}

function joinPath(dir, name) {
  if (!dir) return name;
  const separator = dir.includes("\\") ? "\\" : "/";
  return `${dir.replace(/[\\/]+$/, "")}${separator}${name}`;
}

function formatSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${Math.max(0.1, bytes / 1024).toFixed(1)} KB`;
}

function formatTime(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return dateFormatter.format(date);
}

async function openOutputDir() {
  if (exited) return;

  if (selectedToolId === null) {
    showNotice("请先选择要查看输出目录的工具。", "info");
    return;
  }

  const toolId = selectedToolId;
  const button = elements.openDir;
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "正在查找…";
  setText(elements.dirHint, "");
  elements.dirHint.removeAttribute("title");

  try {
    let data = null;
    try {
      data = await requestJSON(
        `/api/dirs/${encodeURIComponent(toolId)}/${encodeURIComponent(
          OUTPUT_DIR_KEY
        )}`
      );
    } catch (error) {
      if (exited) return;
      if (error instanceof ApiError && error.network) throw error;
      // 当前工具没有配置“输出”key 时后端返回 404，按“没有输出目录”处理。
      data = null;
    }

    if (exited) return;
    const found =
      data && typeof data.path === "string" && data.path ? data.path : "";
    if (!found) {
      showNotice("当前工具没有输出目录。", "info");
      return;
    }

    const revealed = await revealToolPath(toolId, "output");
    if (exited) return;
    setText(
      elements.dirHint,
      `输出目录：${found}${
        revealed && revealed.opened ? "（已在 Finder 中打开）" : ""
      }`
    );
    elements.dirHint.title = found;
    if (!revealed || !revealed.opened) {
      await copyText(found);
      if (exited) return;
      setText(elements.dirHint, `输出目录：${found}（已复制路径）`);
    }
  } catch (error) {
    if (exited) return;
    const message = error instanceof Error ? error.message : "未知错误";
    showNotice(`读取输出目录失败：${message}`, "error");
  } finally {
    if (!exited) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
}

async function copyText(text) {
  if (
    navigator.clipboard &&
    typeof navigator.clipboard.writeText === "function"
  ) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      return false;
    }
  }
  return false;
}

async function exitWorkbench() {
  if (exited) return;
  const confirmed = window.confirm(
    "退出后会停止所有由工作台启动的工具，确定退出吗？"
  );
  if (!confirmed) return;

  const button = elements.exitButton;
  button.disabled = true;
  button.textContent = "正在退出…";

  try {
    await requestJSON("/api/shutdown", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    markExited();
  } catch (error) {
    button.disabled = false;
    button.textContent = "退出工作台";
    const message = error instanceof Error ? error.message : "未知错误";
    showNotice(`退出失败：${message}`, "error");
  }
}

function markExited() {
  exited = true;
  stateRefreshQueued = false;
  retryNotBefore = Number.POSITIVE_INFINITY;
  setSummary("已退出，可以关闭此页");
  clearNotice();
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = true;
  });
  if (elements.reservedStage) {
    elements.reservedStage.classList.add("is-exited");
  }
  document.title = "固收工作台（已退出）";
}

function startingSeconds(tool) {
  const toolId = String(tool.id);
  if (!startingSince.has(toolId)) {
    startingSince.set(toolId, Date.now());
  }
  const since = startingSince.get(toolId);

  let seconds;
  if (typeof tool.started_at === "number" && tool.started_at > 0) {
    seconds = Date.now() / 1000 - tool.started_at;
  } else if (typeof tool.waited === "number" && tool.waited >= 0) {
    seconds = tool.waited;
  } else {
    seconds = (Date.now() - since) / 1000;
  }
  return Math.max(0, Math.round(seconds));
}

function normalizeState(value) {
  return KNOWN_TOOL_STATES.has(value) ? value : "unknown";
}

function displayName(tool) {
  const name = tool && typeof tool.name === "string" ? tool.name.trim() : "";
  return name || "未命名工具";
}

function formatPort(value) {
  const port = Number(value);
  if (!Number.isFinite(port) || port <= 0) return "—";
  return String(Math.trunc(port));
}

function findTool(toolId) {
  return (
    lastTools.find((tool) => String(tool.id) === String(toolId)) || null
  );
}

function tailLines(text, limit) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .filter((line) => line.trim() !== "");
  return lines.slice(-limit).join("\n");
}

function setText(element, text) {
  if (!element) return;
  const value = String(text);
  if (element.textContent !== value) {
    element.textContent = value;
  }
}

function showNotice(message, kind) {
  setText(elements.noticeText, String(message || "发生未知错误。"));
  elements.notice.dataset.kind = kind === "info" ? "info" : kind === "network" ? "network" : "error";
  elements.notice.hidden = false;
}

function clearNotice(kind) {
  if (kind && elements.notice.dataset.kind !== kind) return;
  elements.notice.hidden = true;
  setText(elements.noticeText, "");
  delete elements.notice.dataset.kind;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
