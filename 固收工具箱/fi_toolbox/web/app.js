(() => {
  "use strict";

  const S = { meta: {}, fields: [], values: {}, result: null, busy: false };
  const $ = (id) => document.getElementById(id);

  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.hidden = true; }, 1800);
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({ ok: false, errors: ["返回不是 JSON"] }));
    return data;
  }

  function post(path, payload) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  function fieldById(key) {
    return S.fields.find((field) => field.key === key);
  }

  function labelWrap(label, hint) {
    const wrap = document.createElement("label");
    wrap.textContent = label;
    if (hint) wrap.title = hint;
    return wrap;
  }

  function scalarInput(field) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    wrap.appendChild(labelWrap(field.label, field.hint));
    let input;
    if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach((option) => {
        const opt = document.createElement("option");
        opt.value = String(option.value);
        opt.textContent = option.label;
        input.appendChild(opt);
      });
    } else if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = field.rows || 8;
      input.placeholder = field.placeholder || "";
      input.spellcheck = false;
    } else {
      input = document.createElement("input");
      input.type = field.type === "number" ? "number" : field.type === "date" ? "date" : "text";
      if (field.type === "number") {
        input.step = field.step != null ? field.step : "any";
        if (field.min != null) input.min = field.min;
        if (field.max != null) input.max = field.max;
      }
      input.placeholder = field.placeholder || "";
      input.spellcheck = false;
    }
    input.dataset.key = field.key;
    input.addEventListener("input", () => {
      S.values[field.key] = input.value;
    });
    input.addEventListener("change", () => {
      S.values[field.key] = input.value;
    });
    wrap.appendChild(input);
    if (field.hint) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = field.hint;
      wrap.appendChild(hint);
    }
    return wrap;
  }

  function tableField(field) {
    const wrap = document.createElement("div");
    wrap.className = "table-field";
    const head = document.createElement("div");
    head.className = "table-head";
    head.innerHTML = `<strong>${esc(field.label)}</strong>`;
    const actions = document.createElement("div");
    actions.className = "table-actions";
    actions.style.padding = "0";
    actions.style.border = "0";
    const importBtn = document.createElement("button");
    importBtn.type = "button";
    importBtn.className = "ghost";
    importBtn.textContent = "导入 Excel/CSV";
    importBtn.addEventListener("click", () => pickFile(field));
    actions.appendChild(importBtn);
    head.appendChild(actions);
    wrap.appendChild(head);

    const scroll = document.createElement("div");
    scroll.className = "table-scroll";
    const table = document.createElement("table");
    table.className = "grid";
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    (field.columns || []).forEach((column) => {
      const th = document.createElement("th");
      th.textContent = column.label;
      tr.appendChild(th);
    });
    const th = document.createElement("th");
    th.textContent = "";
    tr.appendChild(th);
    thead.appendChild(tr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);
    scroll.appendChild(table);
    wrap.appendChild(scroll);

    const footer = document.createElement("div");
    footer.className = "table-actions";
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "ghost";
    addBtn.textContent = "＋ 加一行";
    addBtn.addEventListener("click", () => {
      S.values[field.key] = S.values[field.key] || [];
      S.values[field.key].push({});
      renderTableBody(field, tbody);
    });
    footer.appendChild(addBtn);
    wrap.appendChild(footer);
    wrap._tbody = tbody;
    wrap._field = field;
    return wrap;
  }

  function renderTableBody(field, tbody) {
    tbody.innerHTML = "";
    const rows = S.values[field.key] || [];
    rows.forEach((row, index) => {
      const tr = document.createElement("tr");
      (field.columns || []).forEach((column) => {
        const td = document.createElement("td");
        const input = document.createElement("input");
        input.type = "text";
        input.value = row[column.key] == null ? "" : row[column.key];
        input.addEventListener("input", () => {
          rows[index][column.key] = input.value;
        });
        td.appendChild(input);
        tr.appendChild(td);
      });
      const td = document.createElement("td");
      const del = document.createElement("button");
      del.type = "button";
      del.className = "ghost";
      del.textContent = "删";
      del.addEventListener("click", () => {
        rows.splice(index, 1);
        renderTableBody(field, tbody);
      });
      td.appendChild(del);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
  }

  function pickFile(field) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".xlsx,.xlsm,.csv";
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {
        const text = String(reader.result || "");
        const base64 = text.includes(",") ? text.split(",")[1] : text;
        const data = await post("/api/import", {
          filename: file.name,
          data_base64: base64,
          columns: field.columns,
        });
        if (!data.ok) {
          showErrors(data.errors || ["导入失败"]);
          return;
        }
        S.values[field.key] = data.rows || [];
        const body = [...document.querySelectorAll(".table-field")].find((node) => node._field === field);
        if (body) renderTableBody(field, body._tbody);
        if (data.warnings && data.warnings.length) showWarnings(data.warnings);
        else toast(`已导入 ${S.values[field.key].length} 行`);
      };
      reader.readAsDataURL(file);
    });
    input.click();
  }

  function renderFields() {
    const form = $("form");
    form.innerHTML = "";
    S.fields.forEach((field) => {
      if (field.type === "table") {
        const wrapper = tableField(field);
        form.appendChild(wrapper);
        renderTableBody(field, wrapper._tbody);
      } else {
        form.appendChild(scalarInput(field));
      }
    });
  }

  function setValues(data) {
    S.values = {};
    S.fields.forEach((field) => {
      const value = data ? data[field.key] : undefined;
      if (field.type === "table") {
        S.values[field.key] = Array.isArray(value) ? value.map((row) => ({ ...row })) : [];
        const wrapper = [...document.querySelectorAll(".table-field")].find((node) => node._field === field);
        if (wrapper) renderTableBody(field, wrapper._tbody);
        return;
      }
      S.values[field.key] = value == null ? (field.default == null ? "" : field.default) : value;
      const input = document.querySelector(`[data-key="${field.key}"]`);
      if (input) input.value = S.values[field.key] == null ? "" : S.values[field.key];
    });
  }

  function showWarnings(warnings) {
    const box = $("warnings");
    box.innerHTML = "";
    if (!warnings || !warnings.length) { box.hidden = true; return; }
    box.hidden = false;
    warnings.forEach((warning) => {
      const chip = document.createElement("div");
      chip.className = "warn-chip";
      chip.textContent = warning;
      box.appendChild(chip);
    });
  }

  function showErrors(errors) {
    const box = $("warnings");
    box.innerHTML = "";
    box.hidden = false;
    (errors || ["未知错误"]).forEach((error) => {
      const chip = document.createElement("div");
      chip.className = "warn-chip error";
      chip.textContent = error;
      box.appendChild(chip);
    });
  }

  function renderMetrics(metrics) {
    const box = $("metrics");
    box.innerHTML = "";
    (metrics || []).forEach((metric) => {
      const card = document.createElement("div");
      card.className = "metric";
      card.innerHTML = `<div class="label">${esc(metric.label)}</div>` +
        `<div class="value">${esc(metric.value)}${metric.unit ? `<span class="unit">${esc(metric.unit)}</span>` : ""}</div>` +
        (metric.hint ? `<div class="hint">${esc(metric.hint)}</div>` : "");
      box.appendChild(card);
    });
  }

  function renderTables(tables) {
    const box = $("tables");
    box.innerHTML = "";
    (tables || []).forEach((table) => {
      const block = document.createElement("div");
      block.className = "table-block";
      const title = document.createElement("h3");
      title.textContent = table.title || "";
      block.appendChild(title);
      const tableEl = document.createElement("table");
      const thead = document.createElement("thead");
      const tr = document.createElement("tr");
      (table.columns || []).forEach((column) => {
        const th = document.createElement("th");
        th.textContent = column.label;
        if (column.type === "number") th.className = "num";
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      tableEl.appendChild(thead);
      const tbody = document.createElement("tbody");
      (table.rows || []).forEach((row) => {
        const rowEl = document.createElement("tr");
        (table.columns || []).forEach((column) => {
          const td = document.createElement("td");
          td.textContent = row[column.key] == null ? "" : row[column.key];
          if (column.type === "number") td.className = "num";
          rowEl.appendChild(td);
        });
        tbody.appendChild(rowEl);
      });
      tableEl.appendChild(tbody);
      block.appendChild(tableEl);
      if (table.note) {
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = table.note;
        block.appendChild(note);
      }
      box.appendChild(block);
    });
  }

  function renderResult(result) {
    S.result = result;
    $("empty").hidden = true;
    showWarnings(result.warnings || []);
    renderMetrics(result.metrics || []);
    renderTables(result.tables || []);
    const text = $("text");
    if (result.text) {
      text.textContent = result.text;
      text.hidden = false;
    } else {
      text.hidden = true;
      text.textContent = "";
    }
    $("btnDownload").hidden = !(result.download && result.download.base64);
  }

  async function run() {
    if (S.busy) return;
    S.busy = true;
    $("btnRun").disabled = true;
    try {
      const data = await post("/api/run", S.values);
      if (!data.ok) {
        showErrors(data.errors || ["计算失败"]);
        if (data.report) showReport(data.report);
        return;
      }
      renderResult(data);
    } catch (error) {
      showErrors(["请求失败：" + error]);
    } finally {
      S.busy = false;
      $("btnRun").disabled = false;
    }
  }

  async function loadSample() {
    try {
      const data = await api("/api/sample");
      if (!data.ok) { showErrors(data.errors || ["示例生成失败"]); return; }
      setValues(data.data);
      $("seed").textContent = data.seed ? `本次示例种子：${data.seed}` : "";
      await run();
      toast("已生成随机示例");
    } catch (error) {
      showErrors(["示例生成失败：" + error]);
    }
  }

  function downloadBase64(name, base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name || "结果.xlsx";
    link.click();
    URL.revokeObjectURL(url);
  }

  function showReport(report) {
    const box = $("checkReport");
    box.hidden = false;
    box.innerHTML = `已生成问题报告：<b>${esc(report.path || report.name)}</b><br>` +
      `<a href="#" id="dlReport">下载报告</a>（请先查看，确认后再转发）`;
    const link = $("dlReport");
    link.addEventListener("click", (event) => {
      event.preventDefault();
      downloadBase64(report.name, report.base64);
    });
  }

  async function selfcheck() {
    const data = await api("/api/selfcheck?fix=1");
    const list = $("checkList");
    list.innerHTML = "";
    (data.checks || []).forEach((check) => {
      const item = document.createElement("div");
      item.className = "check";
      item.innerHTML = `<span class="dot ${esc(check.status)}"></span>` +
        `<div><div>${esc(check.name)}</div><div class="detail">${esc(check.detail)}</div></div>`;
      list.appendChild(item);
    });
    const report = $("checkReport");
    report.hidden = true;
    if (data.report) showReport(data.report);
    $("selfcheck").hidden = false;
  }

  function copyResult() {
    if (!S.result) { toast("还没有结果"); return; }
    const lines = [];
    (S.result.metrics || []).forEach((metric) => {
      lines.push(`${metric.label}：${metric.value}${metric.unit || ""}`);
    });
    (S.result.tables || []).forEach((table) => {
      lines.push("");
      lines.push(table.title || "");
      lines.push((table.columns || []).map((column) => column.label).join("\t"));
      (table.rows || []).forEach((row) => {
        lines.push((table.columns || []).map((column) => row[column.key] == null ? "" : row[column.key]).join("\t"));
      });
    });
    if (S.result.text) lines.push("", S.result.text);
    const text = lines.join("\n");
    navigator.clipboard.writeText(text).then(
      () => toast("已复制"),
      () => {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
        toast("已复制");
      }
    );
  }

  async function init() {
    const data = await api("/api/meta");
    if (!data.ok) { showErrors(data.errors || ["加载失败"]); return; }
    S.meta = data.meta || {};
    S.fields = data.fields || [];
    $("title").textContent = S.meta.name || "固收工具箱";
    $("desc").textContent = S.meta.desc || "";
    $("version").textContent = "v" + (S.meta.version || "");
    renderFields();
    setValues(data.defaults || {});
    $("btnRun").addEventListener("click", run);
    $("btnSample").addEventListener("click", loadSample);
    $("btnSelfcheck").addEventListener("click", selfcheck);
    $("btnCopy").addEventListener("click", copyResult);
    $("btnCloseCheck").addEventListener("click", () => { $("selfcheck").hidden = true; });
    $("btnDownload").addEventListener("click", () => {
      const download = S.result && S.result.download;
      if (download && download.base64) downloadBase64(download.name, download.base64);
    });
  }

  init().catch((error) => showErrors(["初始化失败：" + error]));
})();
