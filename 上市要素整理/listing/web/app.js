(() => {
  "use strict";

  const state = { fields: {}, output: "", seq: 0, renderTimer: null };
  const $ = (id) => document.getElementById(id);

  const FIELD_DEFS = [
    ["date", "日期"],
    ["offset", "偏移"],
    ["code", "代码"],
    ["name", "名称"],
    ["face", "券面"],
    ["coupon", "票面"],
    ["net", "净价"],
    ["seller", "卖方"],
    ["buyer", "买方"],
    ["seller_contact.person", "卖方联系人"],
    ["seller_contact.channel", "卖方渠道"],
    ["seller_contact.number", "卖方号码"],
    ["buyer_contact.person", "买方联系人"],
    ["buyer_contact.channel", "买方渠道"],
    ["buyer_contact.number", "买方号码"],
  ];

  const REQUIRED = new Set([
    "date",
    "code",
    "name",
    "coupon",
    "seller",
    "buyer",
    "seller_contact.number",
    "buyer_contact.number",
  ]);

  function getPath(obj, path) {
    return path.split(".").reduce((cur, key) => (cur == null ? undefined : cur[key]), obj);
  }

  function setPath(obj, path, value) {
    const keys = path.split(".");
    let cur = obj;
    keys.slice(0, -1).forEach((key) => {
      if (cur[key] == null || typeof cur[key] !== "object") cur[key] = {};
      cur = cur[key];
    });
    cur[keys[keys.length - 1]] = value;
  }

  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => {
      el.hidden = true;
    }, 1600);
  }

  function renderOutput(text) {
    $("output").textContent = text || "";
  }

  function renderWarnings(warnings) {
    const box = $("warnings");
    box.innerHTML = "";
    if (!warnings || !warnings.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    warnings.forEach((warning) => {
      const chip = document.createElement("div");
      chip.className = "warn-chip" + (warning.includes("未识别") ? " error" : "");
      chip.textContent = warning;
      box.appendChild(chip);
    });
  }

  function renderFields(fields) {
    const box = $("fields");
    box.innerHTML = "";
    FIELD_DEFS.forEach(([path, label]) => {
      const value = getPath(fields, path) || "";
      const wrap = document.createElement("div");
      wrap.className = "field";
      if (REQUIRED.has(path) && !value) wrap.classList.add("missing");

      const labelEl = document.createElement("label");
      labelEl.textContent = label;
      labelEl.htmlFor = "f-" + path.replace(/\./g, "-");

      const input = document.createElement("input");
      input.id = labelEl.htmlFor;
      input.type = "text";
      input.value = value;
      input.spellcheck = false;
      input.autocomplete = "off";
      input.addEventListener("input", () => {
        setPath(state.fields, path, input.value);
        wrap.classList.toggle("missing", REQUIRED.has(path) && !input.value);
        scheduleRender();
      });

      wrap.appendChild(labelEl);
      wrap.appendChild(input);
      box.appendChild(wrap);
    });

    const missing = FIELD_DEFS.filter(
      ([path]) => REQUIRED.has(path) && !(getPath(fields, path) || "")
    ).length;
    $("status").textContent = missing ? `缺 ${missing} 项` : "字段齐全";
  }

  function scheduleRender() {
    clearTimeout(state.renderTimer);
    state.renderTimer = setTimeout(renderFromFields, 180);
  }

  async function renderFromFields() {
    if (!state.fields) return;
    const seq = ++state.seq;
    try {
      const response = await fetch("/api/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: state.fields }),
      });
      const data = await response.json();
      if (seq !== state.seq) return;
      state.output = data.output || "";
      renderOutput(state.output);
    } catch (error) {
      console.error(error);
    }
  }

  async function parseNow() {
    const text = $("source").value;
    if (!text.trim()) {
      state.fields = {};
      state.output = "";
      renderOutput("");
      renderWarnings([]);
      $("fields").innerHTML = "";
      $("status").textContent = "";
      return;
    }

    const seq = ++state.seq;
    try {
      const response = await fetch("/api/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await response.json();
      if (seq !== state.seq) return;
      state.fields = data.fields || {};
      state.output = data.output || "";
      renderOutput(state.output);
      renderWarnings(data.warnings || []);
      renderFields(state.fields);
    } catch (error) {
      console.error(error);
      renderWarnings(["解析失败，请确认服务仍在运行"]);
    }
  }

  let inputTimer = null;
  $("source").addEventListener("input", () => {
    clearTimeout(inputTimer);
    inputTimer = setTimeout(parseNow, 220);
  });

  $("clear").addEventListener("click", () => {
    $("source").value = "";
    parseNow();
    $("source").focus();
  });

  $("mock").addEventListener("click", async () => {
    try {
      const response = await fetch("/api/mock");
      const data = await response.json();
      $("source").value = data.text || "";
      await parseNow();
      toast("已生成随机示例");
    } catch (error) {
      console.error(error);
      toast("生成失败");
    }
  });

  $("copy").addEventListener("click", async () => {
    const text = state.output || $("output").textContent || "";
    if (!text) {
      toast("还没有可复制的内容");
      return;
    }
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (error) {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      ok = document.execCommand("copy");
      helper.remove();
    }
    toast(ok ? "已复制" : "复制失败，请手动选择");
  });

  $("source").focus();
})();
