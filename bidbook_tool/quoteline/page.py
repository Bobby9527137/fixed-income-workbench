# -*- coding: utf-8 -*-
"""单页网页界面（内嵌，无需额外静态文件）。"""

INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>报价要素生成工具</title>
<style>
  :root{
    --bg:#f5f6f8; --panel:#ffffff; --soft:#fbfcfe; --ink:#1c2130; --muted:#6b7385;
    --line:#e3e6ec; --line-strong:#cfd5e2; --accent:#2563eb; --accent-soft:#eaf0ff;
    --ok:#0f9d58; --warn:#b26a00; --bad:#d93025; --code:#f6f8fa;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.94);
    border-bottom:1px solid var(--line);padding:12px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
  h1{font-size:16px;margin:0;font-weight:650;letter-spacing:.2px}
  .ver{color:var(--muted);font-size:12px;font-weight:400;margin-left:6px}
  .grow{flex:1}
  .badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);
    background:#fff;border:1px solid var(--line);border-radius:999px;padding:3px 10px;margin-left:6px}
  .dot{width:7px;height:7px;border-radius:50%;background:#cfd4dd}
  .dot.on{background:var(--ok)} .dot.off{background:#c9ccd4}
  main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.05fr);gap:16px;
    padding:16px 20px 48px;max-width:1540px;margin:0 auto;align-items:start}
  @media (max-width:1020px){main{grid-template-columns:minmax(0,1fr)}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;
    box-shadow:0 1px 2px rgba(20,25,40,.04);min-width:0}
  .card + .card{margin-top:16px}
  .card h2{font-size:14px;margin:0 0 10px;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .card h2 .hint{font-weight:400;font-size:12px;color:var(--muted)}
  .head-actions{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
  textarea{width:100%;min-height:160px;resize:vertical;border:1px solid var(--line);border-radius:10px;
    padding:10px 12px;font:13px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    color:var(--ink);background:var(--soft)}
  textarea:focus,input:focus,select:focus{outline:2px solid var(--accent-soft);border-color:var(--accent)}
  .toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
  button{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:8px;padding:7px 13px;
    font-size:13px;cursor:pointer;transition:.12s}
  button:hover{border-color:var(--line-strong);background:#fafbff}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
  button.primary:hover{background:#1d4fd7}
  button.ghost{background:transparent;padding:3px 9px}
  button:disabled{opacity:.5;cursor:not-allowed}
  #drop{border:2px dashed #ccd3e0;border-radius:12px;padding:22px 18px;text-align:center;color:var(--muted);
    background:var(--soft);cursor:pointer;transition:.15s}
  #drop.hot{border-color:var(--accent);background:var(--accent-soft);color:#1c46b8}
  #drop b{color:var(--ink);font-weight:600}
  .preview{display:none;margin-top:12px;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff}
  .preview.on{display:block}
  .preview img{display:block;width:100%;max-height:220px;object-fit:contain;background:#0f1b2d;cursor:zoom-in}
  .preview-bar{display:flex;align-items:center;gap:10px;padding:7px 10px;font-size:12px;color:var(--muted)}
  .preview-bar .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .preview-bar button{padding:3px 9px;font-size:12px}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  label.inline{display:inline-flex;gap:6px;align-items:center;font-size:12.5px;color:var(--muted)}
  select{border:1px solid var(--line);border-radius:7px;padding:5px 8px;font-size:13px;
    color:var(--ink);background:#fff;font-family:inherit}
  .stat{font-size:12.5px;color:var(--muted)}
  .msg{font-size:12.5px;color:var(--muted)}
  .msg.err{color:var(--bad)} .msg.ok{color:var(--ok)} .msg.warn{color:var(--warn)}
  #line{width:100%;min-height:92px;border:1px solid var(--line);border-radius:10px;padding:12px 14px;
    background:var(--soft);font:15px/1.8 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    white-space:pre-wrap;word-break:break-all;color:var(--ink)}
  #line.empty{color:var(--muted);font-family:inherit;font-size:13px}
  .field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
  @media (max-width:640px){.field-grid{grid-template-columns:minmax(0,1fr)}}
  .field{border:1px solid var(--line);border-radius:9px;padding:8px 10px;background:#fff;min-width:0}
  .field-label{font-size:11.5px;color:var(--muted);display:flex;align-items:center;gap:6px}
  .field-value{margin-top:3px;font:13.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    color:var(--ink);overflow-wrap:anywhere}
  .source{font-size:10.5px;line-height:1.4;padding:0 5px;border-radius:999px;border:1px solid var(--line);
    color:var(--muted);background:#fafbfd;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
  .source.text{color:#1c46b8;border-color:#bcd0ff;background:var(--accent-soft)}
  .source.ocr{color:#0b6b45;border-color:#b7e3cc;background:#eefaf3}
  .source.default{color:#9a5b00;border-color:#f0d6a8;background:#fffaf0}
  .warnings{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:6px}
  .warnings li{position:relative;padding:7px 10px 7px 28px;border:1px solid #f0d6a8;background:#fffaf0;
    border-radius:8px;font-size:12.5px;color:#8a5200;line-height:1.6}
  .warnings li::before{content:"!";position:absolute;left:10px;top:7px;width:13px;height:13px;border-radius:50%;
    background:#e8a33d;color:#fff;font-size:10px;line-height:13px;text-align:center;font-weight:700}
  .warnings li.ok{border-color:#cfe9d9;background:#f2fbf6;color:#0b6b45}
  .warnings li.ok::before{content:"✓";background:var(--ok);font-size:9px}
  details{margin-top:12px}
  summary{cursor:pointer;font-size:12.5px;color:var(--muted)}
  pre{margin:8px 0 0;padding:10px 12px;background:var(--code);border:1px solid var(--line);border-radius:9px;
    font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all;
    max-height:260px;overflow:auto}
  .foot{padding:0 20px 26px;max-width:1540px;margin:0 auto;color:var(--muted);font-size:12px;line-height:1.7}
  .lightbox{position:fixed;inset:0;background:rgba(12,16,26,.8);display:none;align-items:center;justify-content:center;z-index:99}
  .lightbox.on{display:flex}
  .lightbox img{max-width:94vw;max-height:94vh;background:#fff;border-radius:8px}
  dialog{border:1px solid var(--line);border-radius:14px;padding:0;max-width:620px;width:calc(100vw - 40px);
    box-shadow:0 18px 50px rgba(20,25,40,.22)}
  dialog::backdrop{background:rgba(12,16,26,.45)}
  .dialog-head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line)}
  .dialog-head h2{margin:0;font-size:14px}
  .dialog-body{padding:12px 16px 16px;max-height:60vh;overflow:auto}
  .check-list{margin:0;padding:0;list-style:none;display:grid;gap:6px}
  .check-list li{display:flex;gap:8px;align-items:flex-start;font-size:12.5px;line-height:1.6}
  .check-list .ok{color:var(--ok);font-weight:700}
  .check-list .bad{color:var(--bad);font-weight:700}
</style>
</head>
<body>
<header>
  <h1>报价要素生成<span class="ver" id="ver"></span></h1>
  <span class="grow"></span>
  <span id="engines"></span>
  <button class="ghost" id="btnSelfcheck" type="button">自检</button>
</header>

<main>
  <div>
    <section class="card">
      <h2>① 交易行文本 <span class="hint">报价本身：期限、代码、简称、价格、带量</span>
        <span class="head-actions">
          <button class="ghost" id="btnExample" type="button" title="填入济南城建样例（含示例截图）">示例</button>
        </span>
      </h2>
      <textarea id="tradeText" spellcheck="false" placeholder="26济南城建SCP004 012681631.IB 3D 1.80* 3000w&#10;&#10;支持这些写法：3D / 9.69Y、1.80* / OFR 1.80、3000w / 3000万 / 1.5亿、AAA/--、票面1.36%"></textarea>
      <p class="stat" id="exampleNote" hidden></p>
    </section>

    <section class="card">
      <h2>② DM 截图 <span class="hint">补全公募/私募、票面、中债估值、主体/债项评级</span></h2>
      <div id="drop" tabindex="0" role="button" aria-label="选择或拖入 DM 截图">
        <b>点这里选图片</b>，或把截图直接拖进来 / 按 Ctrl+V 粘贴<br>
        <span style="font-size:12px">整窗截图、只裁顶部条都可以；图片只在本机识别，不上传</span>
      </div>
      <input type="file" id="file" accept="image/*" hidden>
      <div class="preview" id="preview">
        <img id="previewImg" alt="DM 截图预览">
        <div class="preview-bar">
          <span class="name" id="previewName"></span>
          <button id="btnClearImage" type="button">移除</button>
        </div>
      </div>
      <div class="toolbar">
        <label class="inline">OCR 引擎
          <select id="engine"><option value="auto">自动（推荐）</option></select>
        </label>
        <button class="primary" id="btnBuild" type="button">生成报价</button>
        <span class="msg" id="buildMsg"></span>
      </div>
      <p class="stat" style="margin-top:8px">只贴交易行也能出结果；截图上没有的字段会写 <code>--</code>，并在右侧提示。</p>
    </section>
  </div>

  <section class="card">
    <h2>③ 报价行
      <span class="head-actions">
        <button id="btnCopy" type="button" disabled>复制</button>
      </span>
    </h2>
    <div id="line" class="empty">生成后这里会显示一行固定格式的报价。</div>
    <div class="field-grid" id="fields"></div>
    <ul class="warnings" id="warnings"></ul>

    <details id="ocrDetails" hidden>
      <summary>识别明细</summary>
      <pre id="ocrMeta"></pre>
    </details>
  </section>
</main>

<p class="foot">
  全部在本机运行（127.0.0.1），不上传任何数据。模板：剩余期限 · 代码 · 简称 · 公募/私募 · --/OFR价格* · --/带量w · 主体/债项 · 昨日中债 · 中债估值 · 票面 · 票面利率 · 带量w。
</p>

<div class="lightbox" id="lightbox"><img id="lightboxImg" alt=""></div>

<dialog id="selfcheckDialog">
  <div class="dialog-head">
    <h2>自检结果</h2>
    <span class="grow"></span>
    <button id="selfcheckClose" type="button">关闭</button>
  </div>
  <div class="dialog-body">
    <ul class="check-list" id="selfcheckList"></ul>
  </div>
</dialog>

<script>
"use strict";
var S = { config:null, imageDataUrl:"", imageName:"", busy:false, expected:"" };

function $(id){ return document.getElementById(id); }
function setText(el, text){ if (el) el.textContent = String(text == null ? "" : text); }

function setMsg(text, kind){
  var el = $("buildMsg");
  el.textContent = text || "";
  el.className = "msg" + (kind ? " " + kind : "");
}

function init(){
  $("btnExample").addEventListener("click", loadExample);
  $("btnBuild").addEventListener("click", build);
  $("btnCopy").addEventListener("click", copyLine);
  $("btnSelfcheck").addEventListener("click", runSelfcheck);
  $("selfcheckClose").addEventListener("click", function(){ $("selfcheckDialog").close(); });
  $("btnClearImage").addEventListener("click", clearImage);
  $("file").addEventListener("change", function(event){
    var file = event.target.files && event.target.files[0];
    if (file) readFile(file);
    event.target.value = "";
  });
  var drop = $("drop");
  drop.addEventListener("click", function(){ $("file").click(); });
  drop.addEventListener("keydown", function(event){
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("file").click(); }
  });
  ["dragenter","dragover"].forEach(function(name){
    drop.addEventListener(name, function(event){ event.preventDefault(); drop.classList.add("hot"); });
  });
  ["dragleave","drop"].forEach(function(name){
    drop.addEventListener(name, function(event){ event.preventDefault(); drop.classList.remove("hot"); });
  });
  drop.addEventListener("drop", function(event){
    var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) readFile(file);
  });
  document.addEventListener("paste", function(event){
    var items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    for (var i = 0; i < items.length; i++){
      if (items[i].type && items[i].type.indexOf("image/") === 0){
        var file = items[i].getAsFile();
        if (file){ event.preventDefault(); readFile(file); }
        return;
      }
    }
  });
  $("tradeText").addEventListener("keydown", function(event){
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter"){ event.preventDefault(); build(); }
  });
  $("previewImg").addEventListener("click", function(){
    $("lightboxImg").src = S.imageDataUrl;
    $("lightbox").classList.add("on");
  });
  $("lightbox").addEventListener("click", function(){ $("lightbox").classList.remove("on"); });
  loadConfig();
}

function loadConfig(){
  fetch("/api/config", {cache:"no-store"}).then(function(response){
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }).then(function(data){
    S.config = data;
    setText($("ver"), " v" + data.version);
    var select = $("engine");
    select.replaceChildren();
    var auto = document.createElement("option");
    auto.value = "auto"; auto.textContent = "自动（推荐）";
    select.appendChild(auto);
    var engines = Array.isArray(data.engines) ? data.engines : [];
    engines.forEach(function(engine){
      if (!engine.available) return;
      var option = document.createElement("option");
      option.value = engine.key;
      option.textContent = engine.label || engine.key;
      select.appendChild(option);
    });
    var box = $("engines");
    box.replaceChildren();
    engines.forEach(function(engine){
      var badge = document.createElement("span");
      badge.className = "badge";
      var dot = document.createElement("span");
      dot.className = "dot " + (engine.available ? "on" : "off");
      var text = document.createElement("span");
      text.textContent = engine.key + (engine.available ? "" : " 不可用");
      badge.appendChild(dot); badge.appendChild(text);
      box.appendChild(badge);
    });
  }).catch(function(error){
    setMsg("读取配置失败：" + error.message, "err");
  });
}

function readFile(file){
  if (!file.type || file.type.indexOf("image/") !== 0){
    setMsg("请选择图片文件（PNG / JPG）。", "err");
    return;
  }
  if (file.size > 20 * 1024 * 1024){
    setMsg("图片太大（超过 20MB），请先裁一下。", "err");
    return;
  }
  var reader = new FileReader();
  reader.onload = function(){
    setImage(String(reader.result || ""), file.name || "DM 截图");
  };
  reader.onerror = function(){ setMsg("图片读取失败。", "err"); };
  reader.readAsDataURL(file);
}

function setImage(dataUrl, name){
  if (!dataUrl){ clearImage(); return; }
  S.imageDataUrl = dataUrl;
  S.imageName = name || "DM 截图";
  $("previewImg").src = dataUrl;
  setText($("previewName"), S.imageName);
  $("preview").classList.add("on");
  $("drop").style.display = "none";
  setMsg("已载入截图，点「生成报价」开始识别。", "ok");
}

function clearImage(){
  S.imageDataUrl = "";
  S.imageName = "";
  $("previewImg").removeAttribute("src");
  $("preview").classList.remove("on");
  $("drop").style.display = "";
  setMsg("已移除截图。", "");
}

function loadExample(){
  fetch("/api/sample", {cache:"no-store"}).then(function(response){
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }).then(function(data){
    $("tradeText").value = data.text || "";
    if (data.image_b64) setImage(data.image_b64, "示例：济南城建 DM 头部");
    S.expected = data.expected || "";
    var note = $("exampleNote");
    note.hidden = false;
    note.textContent = S.expected ? ("示例预期：" + S.expected) : "";
    setMsg("示例已填入，点「生成报价」验证。", "ok");
  }).catch(function(error){
    setMsg("加载示例失败：" + error.message, "err");
  });
}

function build(){
  if (S.busy) return;
  var text = $("tradeText").value.trim();
  if (!text && !S.imageDataUrl){
    setMsg("请先粘贴交易行文本，或上传一张 DM 截图。", "err");
    return;
  }
  S.busy = true;
  $("btnBuild").disabled = true;
  setMsg(S.imageDataUrl ? "正在识别截图并生成…" : "正在生成…", "warn");
  var payload = {
    text: text,
    image_b64: S.imageDataUrl || "",
    engine: $("engine").value || "auto"
  };
  fetch("/api/parse", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  }).then(function(response){
    return response.json().then(function(data){ return {ok:response.ok, data:data}; });
  }).then(function(result){
    if (!result.ok || !result.data || !result.data.ok){
      throw new Error((result.data && result.data.error) || "生成失败");
    }
    renderResult(result.data);
    setMsg("已生成。", "ok");
  }).catch(function(error){
    setMsg("生成失败：" + error.message, "err");
  }).finally(function(){
    S.busy = false;
    $("btnBuild").disabled = false;
  });
}

function renderResult(data){
  var line = $("line");
  setText(line, data.line || "");
  line.classList.remove("empty");
  $("btnCopy").disabled = !data.line;

  var fields = data.fields || {};
  var sources = data.sources || {};
  var labels = (S.config && S.config.fields) || [];
  var grid = $("fields");
  grid.replaceChildren();
  labels.forEach(function(item){
    var key = item.key;
    var value = fields[key] || "--";
    var source = sources[key] || "default";
    var card = document.createElement("div");
    card.className = "field";
    var label = document.createElement("div");
    label.className = "field-label";
    label.appendChild(document.createTextNode(item.label || key));
    var badge = document.createElement("span");
    badge.className = "source " + source;
    badge.textContent = source === "text" ? "交易行" : source === "ocr" ? "截图" : "默认";
    label.appendChild(badge);
    var valueEl = document.createElement("div");
    valueEl.className = "field-value";
    valueEl.textContent = value;
    card.appendChild(label); card.appendChild(valueEl);
    grid.appendChild(card);
  });

  var list = $("warnings");
  list.replaceChildren();
  var warnings = Array.isArray(data.warnings) ? data.warnings : [];
  if (!warnings.length){
    var ok = document.createElement("li");
    ok.className = "ok";
    ok.textContent = "没有需要注意的地方，可以直接复制。";
    list.appendChild(ok);
  } else {
    warnings.forEach(function(text){
      var item = document.createElement("li");
      item.textContent = text;
      list.appendChild(item);
    });
  }

  var details = $("ocrDetails");
  if (data.ocr && data.ocr.engine){
    details.hidden = false;
    var lines = [];
    lines.push("引擎：" + data.ocr.engine + "　耗时：" + data.ocr.elapsed + "s　文本框：" + data.ocr.text_count);
    lines.push("裁剪区域：" + (data.ocr.crop || []).join(" × "));
    (data.ocr.attempts || []).forEach(function(attempt){
      lines.push("尝试：" + attempt.variant + " / " + (attempt.engine || "") +
        (attempt.text_count != null ? " / " + attempt.text_count + " 框" : "") +
        (attempt.error ? " / " + attempt.error : ""));
    });
    if (Array.isArray(data.ocr.texts) && data.ocr.texts.length){
      lines.push("");
      lines.push("识别到的文字：");
      lines.push(data.ocr.texts.join(" ｜ "));
    }
    setText($("ocrMeta"), lines.join("\n"));
  } else {
    details.hidden = true;
    setText($("ocrMeta"), "");
  }
}

function copyLine(){
  var text = $("line").textContent || "";
  if (!text) return;
  function fallback(){
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (error) { ok = false; }
    document.body.removeChild(area);
    setMsg(ok ? "已复制。" : "复制失败，请手动选中。", ok ? "ok" : "err");
  }
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){ setMsg("已复制。", "ok"); }, fallback);
  } else {
    fallback();
  }
}

function runSelfcheck(){
  fetch("/api/selfcheck", {cache:"no-store"}).then(function(response){
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }).then(function(data){
    var list = $("selfcheckList");
    list.replaceChildren();
    (data.checks || []).forEach(function(check){
      var item = document.createElement("li");
      var mark = document.createElement("span");
      mark.className = check.ok ? "ok" : "bad";
      mark.textContent = check.ok ? "✓" : "✗";
      var text = document.createElement("span");
      text.textContent = check.name + "：" + (check.detail || "");
      item.appendChild(mark); item.appendChild(text);
      list.appendChild(item);
    });
    var dialog = $("selfcheckDialog");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "open");
  }).catch(function(error){
    setMsg("自检失败：" + error.message, "err");
  });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
</script>
</body>
</html>
"""
