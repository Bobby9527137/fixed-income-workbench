# -*- coding: utf-8 -*-
"""单页网页界面（内嵌，无需额外静态文件）。"""

INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>投标簿记信息提取工具</title>
<style>
  :root{
    --bg:#f5f6f8; --panel:#ffffff; --ink:#1c2130; --muted:#6b7385;
    --line:#e3e6ec; --accent:#2563eb; --accent-soft:#eaf0ff;
    --ok:#0f9d58; --warn:#c47f00; --bad:#d93025; --code:#f6f8fa;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.92);
    border-bottom:1px solid var(--line);padding:12px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
  h1{font-size:16px;margin:0;font-weight:650;letter-spacing:.2px}
  .ver{color:var(--muted);font-size:12px;font-weight:400;margin-left:6px}
  .grow{flex:1}
  .badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);
    background:#fff;border:1px solid var(--line);border-radius:999px;padding:3px 10px;margin-left:6px}
  .dot{width:7px;height:7px;border-radius:50%;background:#cfd4dd}
  .dot.on{background:var(--ok)} .dot.off{background:#c9ccd4}
  main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;padding:16px 20px 300px;max-width:1680px;margin:0 auto}
  @media (max-width:1080px){main{grid-template-columns:minmax(0,1fr)}}
  section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
    box-shadow:0 1px 2px rgba(20,25,40,.04)}
  section h2{font-size:14px;margin:0 0 10px;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  section h2 .hint{font-weight:400;font-size:12px;color:var(--muted)}
  textarea{width:100%;min-height:150px;resize:vertical;border:1px solid var(--line);border-radius:9px;
    padding:10px 12px;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ink);background:#fcfcfd}
  textarea:focus,input:focus,select:focus{outline:2px solid var(--accent-soft);border-color:var(--accent)}
  .toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
  button{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:8px;padding:7px 13px;
    font-size:13px;cursor:pointer;transition:.12s}
  button:hover{border-color:#c7cddb;background:#fafbff}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
  button.primary:hover{background:#1d4fd7}
  button.ghost{background:transparent;padding:3px 9px}
  button:disabled{opacity:.5;cursor:not-allowed}
  .slots{display:flex;gap:6px;flex-wrap:wrap}
  .chip{border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:12.5px;cursor:pointer;background:#fff}
  .chip.on{background:var(--accent-soft);border-color:#bcd0ff;color:#1c46b8;font-weight:600}
  .chip small{color:var(--muted);font-weight:400}
  #drop{border:2px dashed #ccd3e0;border-radius:12px;padding:18px;text-align:center;color:var(--muted);
    background:#fbfcfe;cursor:pointer;transition:.15s}
  #drop.hot{border-color:var(--accent);background:var(--accent-soft);color:#1c46b8}
  .thumbs{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
  .thumb{position:relative;width:134px;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:#fff}
  .thumb img{display:block;width:100%;height:86px;object-fit:cover;cursor:zoom-in}
  .thumb .cap{font-size:11.5px;padding:4px 6px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .thumb .x{position:absolute;top:4px;right:4px;background:rgba(20,25,40,.66);color:#fff;border:0;border-radius:50%;
    width:20px;height:20px;line-height:1;font-size:12px;cursor:pointer;padding:0}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  label.inline{display:inline-flex;gap:6px;align-items:center;font-size:12.5px;color:var(--muted)}
  select,input[type=text],input[type=number]{border:1px solid var(--line);border-radius:7px;padding:5px 8px;
    font-size:13px;color:var(--ink);background:#fff;font-family:inherit}
  input.cell{width:100%;border:1px solid transparent;background:transparent;border-radius:6px;padding:4px 6px;font-size:13px}
  input.cell:hover{border-color:var(--line);background:#fcfcfd}
  .tablewrap{overflow:auto;max-height:400px;border:1px solid var(--line);border-radius:10px;margin-top:8px}
  table{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px}
  th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:left;white-space:nowrap}
  th{position:sticky;top:0;background:#fafbfd;font-weight:600;color:#3b4152;z-index:1}
  tr:last-child td{border-bottom:0}
  tr.review td{background:#fffaf0}
  .map{display:grid;grid-template-columns:auto minmax(90px,1fr);gap:6px 10px;align-items:center;margin-top:8px}
  .maplabel{font-size:12.5px;color:var(--muted)}
  #out{width:100%;min-height:170px;max-height:34vh;overflow:auto;
    font:13px/1.75 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    border:1px solid var(--line);border-radius:10px;padding:12px;background:#fff;white-space:pre-wrap;word-break:break-all}
  .stat{font-size:12.5px;color:var(--muted)}
  .msg{font-size:12.5px;color:var(--muted)}
  .msg.err{color:var(--bad)} .msg.ok{color:var(--ok)}
  #outWrap{position:fixed;left:0;right:0;bottom:0;padding:10px 20px 14px;z-index:9;
    background:rgba(255,255,255,.97);border-top:1px solid var(--line)}
  #outWrap .bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:8px;max-width:1680px;margin-left:auto;margin-right:auto}
  #outWrap #outBox{max-width:1680px;margin:0 auto}
  #outNote{display:none;margin-top:8px;padding:7px 10px;border:1px solid #f0c36d;background:#fffaf0;
    border-radius:8px;font-size:12.5px;line-height:1.7;color:#a05a00;max-height:104px;overflow:auto}
  .boxlabel{font-size:12.5px;line-height:1.7;color:var(--muted);margin-bottom:6px}
  .boxlabel b{color:#2b3245}
  code{background:var(--code);padding:1px 5px;border-radius:5px;font-size:12px}
  details{margin-top:10px}
  summary{cursor:pointer;font-size:12.5px;color:var(--muted)}
  .lightbox{position:fixed;inset:0;background:rgba(12,16,26,.78);display:none;align-items:center;justify-content:center;z-index:99}
  .lightbox.on{display:flex}
  .lightbox img{max-width:94vw;max-height:94vh;background:#fff;border-radius:8px}
</style>
</head>
<body>
<header>
  <h1>投标簿记信息提取<span class="ver" id="ver"></span></h1>
  <span class="grow"></span>
  <span id="engines"></span>
</header>

<main>
  <section>
    <h2>① 传表格截图 <span class="hint">投标量固定表头的表格，可一次传多张</span></h2>
    <div id="drop">
      点这里选图片，或把截图直接拖进来<br>
      <span style="font-size:12px">（PNG / JPG / 截屏均可；带表格框线的截图识别最准）</span>
    </div>
    <input type="file" id="file" accept="image/*" multiple hidden>
    <div class="thumbs" id="thumbs"></div>

    <div class="toolbar">
      <label class="inline">OCR 引擎
        <select id="engine"><option value="auto">自动（推荐）</option></select>
      </label>
      <button class="primary" id="btnOcr" disabled>识别表格</button>
      <span class="msg" id="ocrMsg"></span>
    </div>

    <div class="stat" id="ocrMeta" style="margin-top:8px"></div>

    <details id="mapBox" open>
      <summary>列对应关系（识别不对时才需要改）</summary>
      <div class="map" id="map"></div>
    </details>

    <div class="tablewrap">
      <table id="tbl">
        <thead><tr id="tblHead"></tr></thead>
        <tbody id="tblBody"><tr><td class="stat" style="padding:14px">还没有识别结果。传一张表格截图，点「识别表格」。</td></tr></tbody>
      </table>
    </div>
    <div class="stat" style="margin-top:6px">
      表格里<b>黄底</b>行表示某列没识别清楚，请对一眼截图再改；每格都可以直接编辑。
    </div>
  </section>

  <section>
    <h2>② 粘贴债券文本 <span class="hint">两个窗口，各管一块</span></h2>

    <div class="boxlabel">
      <b>窗口 1 · 债券行</b>（必填）：给输出提供【区间】、债券简称、期限、规模、评级。
      其中<b>债券简称</b>负责跟截图里的行一一对上；对不上的那一行也会出文案，缺的数写「待定」。
    </div>
    <textarea id="pasted" spellcheck="false" placeholder="【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%
【1.5-2.5】，26武清经开MTN008，2.5Y，1.4亿，AA+，10-13 簿记，10-14 缴款"></textarea>

    <div class="boxlabel" style="margin-top:14px">
      <b>窗口 2 · 边际数据</b>（可不填）：给输出提供<b>边际利率/价格、全场倍数、边际倍数</b>这三个数。
      截图里没有这只债、或者这三列没识别到时，靠它也能出文案。一行一只，先写简称再写数：
      <code>26天津城投CP001 2.30 1.55 3.10</code>（顺序＝边际利率/价格、全场倍数、边际倍数，缺的留空）；
      带标签更保险：<code>26天津城投CP001 边际2.30% 全场1.55倍 边际倍数3.10倍</code>。
      只写一个数也行，另外两项输出时写「待定」；边际利率写成范围（<code>1.75-1.95</code>）取上限。
      <b>别把整段簿记文本粘到这里</b>：出现「簿记／缴款／交款／上市／起息／发行／截止／建档／定价」里任意一个词，
      这个窗口的内容就整段不解析（那些日期会被误当成边际数据），网页会弹窗提示，清理后重试。
      截图里已经识别到的以截图为准，这里只补截图没有的。
    </div>
    <textarea id="values" spellcheck="false" placeholder="26天津城投CP001 2.30 1.55 3.10
26武清经开MTN009 边际2.05% 全场1.50倍 边际倍数3.00倍"></textarea>

    <h2 style="margin-top:16px">③ 输出时点 <span class="hint">默认按电脑时间自动判断，也可以直接指定</span></h2>
    <div class="slots" id="slots"></div>
    <div class="stat" id="clockLine" style="margin-top:6px"></div>
    <div class="toolbar">
      <label class="inline">匹配门槛
        <input type="range" id="thr" min="0.7" max="0.98" step="0.01" value="0.90">
        <span id="thrVal">0.90</span>
      </label>
      <label class="inline"><input type="checkbox" id="showTime"> 输出里带上时间</label>
    </div>
    <div class="toolbar">
      <button class="primary" id="btnBuild">生成结果</button>
      <span class="msg" id="buildMsg"></span>
    </div>
    <div class="stat" id="buildMeta" style="margin-top:8px"></div>
  </section>
</main>

<div id="outWrap">
  <div class="bar">
    <span class="stat">④ 输出</span>
    <span class="grow" style="flex:1"></span>
    <span class="stat" id="outMeta"></span>
    <button id="btnCopy">复制全部</button>
    <button id="btnTxt">存为 .txt</button>
  </div>
  <div id="outBox"><div id="out"></div><div id="outNote"></div></div>
</div>
<div class="lightbox" id="lightbox"><img id="lightboxImg" alt=""></div>

<script>
var S = { cfg:null, images:[], tableRows:[], results:[], defaultTime:"auto", thrTouched:false };
/* 窗口 2 不接受整段簿记文本：这些词由后端 /api/config 给，前端也是同一份 */
var VALUE_BLACKLIST = [];
function valuesBlacklistHit(text){
  for(var i = 0; i < VALUE_BLACKLIST.length; i++){
    if(String(text).indexOf(VALUE_BLACKLIST[i]) >= 0) return VALUE_BLACKLIST[i];
  }
  return "";
}
function applyThresholdCfg(cfg){
  VALUE_BLACKLIST = cfg.value_blacklist || [];
  if(typeof cfg.threshold_min === "number") $("thr").min = String(cfg.threshold_min);
  if(typeof cfg.threshold_max === "number") $("thr").max = String(cfg.threshold_max);
  // 默认门槛以后端为准；用户已经动过滑块就不覆盖他
  if(typeof cfg.default_threshold === "number" && !S.thrTouched){ $("thr").value = cfg.default_threshold.toFixed(2); }
  $("thrVal").textContent = Number($("thr").value).toFixed(2);
}
function $(id){ return document.getElementById(id); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){ return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]; }); }
function num2(v){ if(v===""||v===null||v===undefined) return ""; var n=Number(v); return isNaN(n)?"":n.toFixed(2); }
function toast(el, text, kind){ el.className = "msg" + (kind ? " " + kind : ""); el.textContent = text || ""; }

function api(path, body){
  return fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : {"Content-Type":"application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)
  }).then(function(r){ return r.json(); });
}

/* ---------------- 时点：按电脑时间自动判断 ---------------- */
function pad2(n){ return (n < 10 ? "0" : "") + n; }

/* 和 Python 端 rows.clock_slot 同一套规则：只在 17:30/17:40/17:50/18:00 四个时点里取
   不晚于现在的最近一个；还没到 17:30 算第一轮 17:30。 */
function localTimeInfo(){
  var cfg = S.cfg || {};
  var d = new Date(), h = d.getHours(), m = d.getMinutes(), mm = h * 60 + m;
  var slots = cfg.time_slots || ["17:30", "17:40", "17:50", "18:00"];
  var finalSlot = cfg.final_slot || "18:00";
  var slot = slots[0];
  for(var i = slots.length - 1; i >= 0; i--){
    var p = String(slots[i]).split(":");
    if(mm >= Number(p[0]) * 60 + Number(p[1])){ slot = slots[i]; break; }
  }
  return { now: pad2(h) + ":" + pad2(m), slot: slot,
           mode: (slot === finalSlot) ? "最终边际" : "目前边际" };
}

function tickClock(){
  var info = localTimeInfo(), el = $("clockLine");
  if(!el) return;
  var rule = "只在 17:30 / 17:40 / 17:50 / 18:00 四个时点里选，还没到 17:30 算第一轮";
  if(S.defaultTime === "auto"){
    el.innerHTML = "电脑时间 <b>" + info.now + "</b> → 自动判断为 <b>" + info.mode + "</b>（本轮时点 " +
      info.slot + "）；" + rule + "。文本行自己写了时间的话以那个为准。";
  }else{
    var manual = (S.defaultTime === "final") ? "最终边际" : "目前边际";
    el.innerHTML = "已手动指定 <b>" + manual + "</b>；电脑时间 " + info.now +
      " 自动判断本来会是 " + info.mode + "，点「自动」可以改回去。";
  }
}

function renderTimeChoices(cfg){
  var choices = cfg.time_choices || [{key:"auto", label:"自动（按电脑时间）"}];
  $("slots").innerHTML = choices.map(function(c){
    return '<span class="chip' + (c.key === S.defaultTime ? " on" : "") + '" data-k="' + c.key + '">' +
      esc(c.label) + '</span>';
  }).join("");
  $("slots").addEventListener("click", function(ev){
    var chip = ev.target.closest(".chip"); if(!chip) return;
    S.defaultTime = chip.dataset.k;
    Array.prototype.forEach.call($("slots").children, function(c){ c.classList.toggle("on", c === chip); });
    tickClock();
    rebuild(false);
  });
}

/* ---------------- 初始化 ---------------- */
function init(){
  return api("/api/config").then(function(cfg){
    S.cfg = cfg;
    $("ver").textContent = "v" + cfg.version;
    $("engines").innerHTML = cfg.engines.map(function(e){
      return '<span class="badge" title="' + esc(e.note) + '"><i class="dot ' + (e.available ? "on" : "off") + '"></i>' + esc(e.label) + '</span>';
    }).join("");
    cfg.engines.forEach(function(e){
      if(!e.available) return;
      var o = document.createElement("option"); o.value = e.key; o.textContent = e.label; $("engine").appendChild(o);
    });
    applyThresholdCfg(cfg);
    renderTimeChoices(cfg);
    tickClock();
    setInterval(tickClock, 15000);
    renderMap(null, null);
    renderTable();
  });
}

/* ---------------- 图片 ---------------- */
function addFiles(files){
  var jobs = [];
  Array.prototype.forEach.call(files, function(f){
    jobs.push(new Promise(function(done){
      var fr = new FileReader();
      fr.onload = function(){ done({ name:f.name, data_url:fr.result }); };
      fr.readAsDataURL(f);
    }));
  });
  return Promise.all(jobs).then(function(list){
    S.images = S.images.concat(list);
    renderThumbs();
    $("btnOcr").disabled = S.images.length === 0;
    toast($("ocrMsg"), S.images.length + " 张待识别");
  });
}
function renderThumbs(){
  $("thumbs").innerHTML = S.images.map(function(im, i){
    return '<div class="thumb"><button class="x" data-i="' + i + '" title="移除">×</button>' +
      '<img src="' + im.data_url + '" data-view="' + i + '" alt=""><div class="cap">' + esc(im.name) + '</div></div>';
  }).join("");
}
$("thumbs").addEventListener("click", function(ev){
  var x = ev.target.closest(".x");
  if(x){ S.images.splice(Number(x.dataset.i), 1); renderThumbs(); $("btnOcr").disabled = S.images.length === 0; return; }
  var v = ev.target.closest("img[data-view]");
  if(v){ $("lightboxImg").src = S.images[Number(v.dataset.view)].data_url; $("lightbox").classList.add("on"); }
});
$("lightbox").addEventListener("click", function(){ $("lightbox").classList.remove("on"); });
$("drop").addEventListener("click", function(){ $("file").click(); });
$("file").addEventListener("change", function(ev){ addFiles(ev.target.files); });
["dragenter","dragover"].forEach(function(t){ $("drop").addEventListener(t, function(ev){ ev.preventDefault(); $("drop").classList.add("hot"); }); });
["dragleave","drop"].forEach(function(t){ $("drop").addEventListener(t, function(ev){ ev.preventDefault(); $("drop").classList.remove("hot"); }); });
$("drop").addEventListener("drop", function(ev){ if(ev.dataTransfer && ev.dataTransfer.files) addFiles(ev.dataTransfer.files); });

/* ---------------- 识别 ---------------- */
$("btnOcr").addEventListener("click", function(){
  if(!S.images.length) return;
  $("btnOcr").disabled = true;
  toast($("ocrMsg"), "识别中…首次识别要加载模型，可能等十几秒");
  api("/api/recognize", { images:S.images, engine:$("engine").value }).then(function(data){
    S.tableRows = []; S.rawCols = [];
    var metas = [], firstHeader = null;
    data.images.forEach(function(im){
      if(!im.ok){ metas.push('<span style="color:#d93025">' + esc(im.name) + "：" + esc(im.error) + "</span>"); return; }
      var t = im.table;
      metas.push(esc(im.name) + "：" + esc(im.engine) + " · " + im.text_count + " 段文字 · " + t.rows.length + " 行 · " + (im.elapsed || "?") + "s" +
        (t.method === "cluster" ? ' <b>（没检测到框线，已按文字坐标重建）</b>' : ""));
      t.rows.forEach(function(r){
        r._image = im.name;
        r._review = (r.missing || []).length > 0;
        S.tableRows.push(r);
      });
      (t.warnings || []).forEach(function(w){ metas.push('<span style="color:#c47f00">提示：' + esc(w) + "</span>"); });
      if(!firstHeader){ firstHeader = t; }
    });
    if(firstHeader){ renderMap(firstHeader.header_map, firstHeader.header_texts, firstHeader.rows); }
    S.tableRows.forEach(function(r, i){
      r.index = i + 1;                       // 行号固定后不再变，人工改数也按它对应
      var j = (i < S.tableRows.length) ? i : 0;
      if(S.rawCols[j]){ S.rawCols[j].idx = { code:r.code, name:r.name, raw_name:r.raw_name,
                                             margin_rate:r.margin_rate, full_ratio:r.full_ratio,
                                             edge_ratio:r.edge_ratio }; }
    });
    $("ocrMeta").innerHTML = metas.join("<br>");
    renderTable();
    toast($("ocrMsg"), "识别完成：" + S.tableRows.length + " 行", "ok");
    rebuild(false);
  }).catch(function(err){
    toast($("ocrMsg"), "识别失败：" + err, "err");
  }).then(function(){
    $("btnOcr").disabled = S.images.length === 0;
  });
});

/* ---------------- 列对应关系 ---------------- */
function renderMap(map, headerTexts, rawRows){
  var headers = (S.cfg && S.cfg.headers) || [];
  if(!map || !map.length){
    $("map").innerHTML = '<span class="maplabel" style="grid-column:1/-1">识别完成后在这里显示</span>';
    return;
  }
  S.rawCols = (rawRows || []).map(function(r){
    return { cells: (r.extra && r.extra.__cols) || [], idx: {} };
  });
  S.orig = (rawRows || []).map(function(r){
    // 记录「原表认出来的」五个关键字段，改了下拉也能一键回退
    return { code:r.code, name:r.name, raw_name:r.raw_name,
             margin_rate:r.margin_rate, full_ratio:r.full_ratio, edge_ratio:r.edge_ratio };
  });
  $("map").innerHTML = map.map(function(v, i){
    var opts = '<option value="">（不使用）</option>' + headers.map(function(h){
      return '<option value="' + esc(h) + '"' + (h === v ? " selected" : "") + '>' + esc(h) + '</option>';
    }).join("");
    return '<span class="maplabel">第 ' + (i + 1) + ' 列' + (headerTexts && headerTexts[i] ? "（" + esc(headerTexts[i]) + "）" : "") + '</span>' +
      '<select data-col="' + i + '">' + opts + '</select>';
  }).join("");
}
$("map").addEventListener("change", function(ev){
  var s = ev.target.closest("select[data-col]"); if(!s) return;
  remapByColumn(Number(s.dataset.col), s.value);
  renderTable(); rebuild(true);
});
var FIELD_OF = { "债券简称":"name", "债券代码":"code", "边际利率/价格":"margin_rate", "全场倍数":"full_ratio", "边际倍数":"edge_ratio" };

function remapByColumn(col, field){
  // 单个下拉改了就整体重算：先按原表恢复五个关键字段，再按当前的下拉选择覆盖。
  applyColumnMap();
}

function currentColumnMap(){
  // ["", "债券简称", ...] 长度 = 列数，值是用户在下拉里选定的固定表头名
  var map = [];
  var selects = document.querySelectorAll('#map select[data-col]');
  for(var i = 0; i < selects.length; i++){ map[Number(selects[i].dataset.col)] = selects[i].value || ""; }
  return map;
}

function applyColumnMap(){
  if(!S.rawCols || !S.rawCols.length) return;
  var map = currentColumnMap();
  S.tableRows.forEach(function(r, i){
    var cols = S.rawCols[i];
    if(!cols) return;
    // 1) 回到原表识别出来的值
    if(cols.idx){ Object.keys(cols.idx).forEach(function(k){ r[k] = cols.idx[k]; }); }
    // 2) 再按下拉选择覆盖
    map.forEach(function(field, col){
      var key = FIELD_OF[field];
      if(!key) return;
      var v = cols.cells ? cols.cells[col] : undefined;
      if(v === undefined || v === null || v === "") return;
      if(["margin_rate","full_ratio","edge_ratio"].indexOf(key) >= 0){
        var s = String(v).replace(/%|倍/g, "").trim(), n = parseFloat(s);
        r[key] = isNaN(n) ? null : n;
      } else {
        r[key] = String(v).trim();
        if(key === "name") r.raw_name = String(v).trim();
      }
    });
  });
}

/* ---------------- 表格渲染 ---------------- */
var HEAD = ["#","代码","债券简称","期限","规模","评级","边际(%)","全场倍数","边际倍数","识别情况",""];
function renderTable(){
  $("tblHead").innerHTML = HEAD.map(function(h){ return "<th>" + esc(h) + "</th>"; }).join("");
  if(!S.tableRows.length){
    $("tblBody").innerHTML = '<tr><td class="stat" style="padding:14px">还没有识别结果。传一张表格截图，点「识别表格」。</td></tr>';
    return;
  }
  $("tblBody").innerHTML = S.tableRows.map(function(r, i){
    var cls = (r.missing && r.missing.length) ? "review" : "";
    return '<tr class="' + cls + '" data-i="' + i + '">' +
      "<td>" + (i + 1) + "</td>" +
      cell(i, "code", r.code, 74) + cell(i, "name", r.name, 168) +
      cell(i, "tenor_text", r.tenor_text || "", 50) + cell(i, "scale_text", r.scale_text || "", 60) +
      cell(i, "rating_text", r.rating_text || "", 52) +
      cell(i, "margin_rate", num2(r.margin_rate), 66) + cell(i, "full_ratio", num2(r.full_ratio), 66) +
      cell(i, "edge_ratio", num2(r.edge_ratio), 66) +
      "<td>" + ((r.missing && r.missing.length) ? '<span style="color:#c47f00">缺 ' + esc(r.missing.join("、")) + "</span>"
              : '<span style="color:#0f9d58">正常</span>') + "</td>" +
      "<td><button class='ghost' data-del='" + i + "'>删</button></td></tr>";
  }).join("");
}
function cell(i, key, val, w){
  return '<td><input class="cell" style="min-width:' + w + 'px" data-i="' + i + '" data-k="' + key + '" value="' + esc(val == null ? "" : val) + '"></td>';
}
$("tblBody").addEventListener("input", function(ev){
  var el = ev.target.closest("input.cell"); if(!el) return;
  var i = Number(el.dataset.i), k = el.dataset.k;
  if(["margin_rate","full_ratio","edge_ratio"].indexOf(k) >= 0){
    S.tableRows[i][k] = el.value === "" ? null : Number(el.value);
  } else {
    S.tableRows[i][k] = el.value;
    if(k === "name") S.tableRows[i].raw_name = el.value;
  }
  schedule();
});
$("tblBody").addEventListener("click", function(ev){
  var b = ev.target.closest("button[data-del]"); if(!b) return;
  S.tableRows.splice(Number(b.dataset.del), 1);
  renderTable(); rebuild(false);
});

/* ---------------- 生成 ---------------- */
$("thr").addEventListener("input", function(){ S.thrTouched = true; $("thrVal").textContent = Number($("thr").value).toFixed(2); rebuild(false); });
$("showTime").addEventListener("change", function(){ rebuild(false); });
$("pasted").addEventListener("input", schedule);
$("values").addEventListener("input", schedule);
$("btnBuild").addEventListener("click", function(){ rebuild(true); });
var timer = null;
function schedule(){ clearTimeout(timer); timer = setTimeout(function(){ rebuild(false); }, 350); }

function collectOverrides(){
  var overrides = {};
  S.tableRows.forEach(function(r, i){
    var o = {};
    ["margin_rate","full_ratio","edge_ratio"].forEach(function(k){
      var el = document.querySelector('input.cell[data-i="' + i + '"][data-k="' + k + '"]');
      if(el && el.value !== ""){ var n = parseFloat(el.value); if(!isNaN(n)) o[k] = n; }
    });
    overrides[String(r.index)] = o;
  });
  return overrides;
}

function rebuild(fromButton){
  var text = $("pasted").value;
  if(!text.trim()){ $("out").textContent = ""; $("outMeta").textContent = ""; $("buildMeta").innerHTML = "";
    $("outNote").innerHTML = ""; $("outNote").style.display = "none"; return; }
  // 窗口 2 只收「债券简称 + 边际利率/倍数」：粘了整段簿记文本就弹窗提示，内容整段不用
  var badWord = valuesBlacklistHit($("values").value);
  if(badWord){
    var badMsg = "【窗口2输入错误】该窗口仅接受「债券简称+边际利率/倍数」，请勿粘贴完整簿记文本，请清理内容后重试";
    $("buildMeta").innerHTML = '<span style="color:#c0392b">' + esc(badMsg)
      + "（出现「" + esc(badWord) + "」，这个窗口的内容已整段忽略）</span>";
    if(fromButton) alert(badMsg + "\n（出现「" + badWord + "」）");
  }
  api("/api/build", {
    text: text,
    values_text: $("values").value,
    default_time: S.defaultTime,
    show_time: $("showTime").checked,
    threshold: Number($("thr").value),
    rows: S.tableRows.map(function(r){
      return { index:r.index, code:r.code, name:r.name, raw_name:r.raw_name || r.name,
               margin_rate:r.margin_rate, full_ratio:r.full_ratio, edge_ratio:r.edge_ratio };
    }),
    overrides: collectOverrides()
  }).then(function(data){
    if(!data.ok){ toast($("buildMsg"), data.error || "生成失败", "err"); return; }
    S.results = data.results || [];
    var pending = S.results.filter(function(r){ return (r.pending && r.pending.length) || !r.has_data; });
    $("out").textContent = data.text;
    var slotInfo = data.time_slot ? ("本轮 " + (data.mode || "") + " " + data.time_slot + " · ") : "";
    $("outMeta").textContent = slotInfo + data.count + " 行"
      + (pending.length ? "，" + pending.length + " 行有「待定」" : "")
      + (data.review_count ? "，" + data.review_count + " 行建议核对" : "");
    $("outNote").innerHTML = pending.length
      ? "以下 " + pending.length + " 行里有<b>待定</b>项（截图里没有、窗口 2 也没给数），文案里那一项写的就是「待定」，请核对：<br>"
        + pending.map(function(r){
            var bits = [r.input.tenor_text, r.input.scale_text, r.input.rating_text].filter(Boolean).join("，");
            var which = (r.pending && r.pending.length) ? r.pending.join("、") : "三个数";
            return "△ " + esc(r.input.display_name || r.input.name) + (bits ? "（" + esc(bits) + "）" : "") + "：待定项 " + esc(which);
          }).join("<br>")
      : "";
    $("outNote").style.display = pending.length ? "block" : "none";
    $("buildMeta").innerHTML = S.results.map(function(r){
      var nm = esc(r.input.display_name || r.input.name);
      var extra = (r.input.notes && r.input.notes.length) ? ' · <span style="color:#c47f00">' + esc(r.input.notes.join("；")) + "</span>" : "";
      if(!r.has_data) return '<span style="color:#c47f00">△ ' + nm + "："
        + esc(r.review_reason || "没有对应的数据") + extra + "</span>";
      var srcTxt = r.values_source ? "数来自 " + esc(r.values_source) : "";
      var scoreTxt = r.table ? ("截图匹配度 " + Math.round(r.match_score * 100) + "%")
                             : ("窗口 2 匹配度 " + Math.round((r.values_score || 0) * 100) + "%");
      var warn = r.review ? ' · <span style="color:#c47f00">' + esc(r.review_reason) + "</span>" : "";
      if(r.warn_text) warn = ' · <span style="color:#c0392b">' + esc(String(r.warn_text).trim()) + "</span>" + warn;
      var mark = (r.pending && r.pending.length) ? '<span style="color:#c47f00">△</span>' : '<span style="color:#0f9d58">✓</span>';
      return mark + " " + nm + " · " + [srcTxt, scoreTxt].filter(Boolean).join(" · ")
        + " · " + esc(r.mode) + extra + warn;
    }).join("<br>");
    if(data.value_problems && data.value_problems.length){
      $("buildMeta").insertAdjacentHTML("beforeend",
        '<br><span style="color:#c47f00">窗口 2 里这几行没认出来（要有债券简称和至少一个数）：'
        + data.value_problems.map(esc).join("；") + "</span>");
    }
    if(data.values_rejected){
      $("buildMeta").insertAdjacentHTML("beforeend",
        '<br><span style="color:#c0392b">窗口 2 输入错误（出现「' + esc(data.values_rejected) + "」）："
        + esc(data.values_error || "") + "，这个窗口的内容没有用于生成。</span>");
    }
    var bad = pending.length;
    toast($("buildMsg"), bad ? bad + " 行有「待定」项，请核对" : "已生成", bad ? "" : "ok");
  }).catch(function(err){ toast($("buildMsg"), "生成失败：" + err, "err"); });
}

/* ---------------- 复制 / 下载 ---------------- */
$("btnCopy").addEventListener("click", function(){
  var t = $("out").textContent || "";
  if(!t){ toast($("buildMsg"), "还没有结果", "err"); return; }
  function fallback(){
    var ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta);
    ta.select(); document.execCommand("copy"); ta.remove();
    toast($("buildMsg"), "已复制", "ok");
  }
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(function(){
      toast($("buildMsg"), "已复制 " + t.split("\n").length + " 行", "ok");
    }).catch(fallback);
  } else { fallback(); }
});
$("btnTxt").addEventListener("click", function(){
  var t = $("out").textContent || ""; if(!t) return;
  var now = new Date(), p = function(n){ return String(n).padStart(2, "0"); };
  var name = "簿记" + now.getFullYear() + p(now.getMonth() + 1) + p(now.getDate()) + "-" + p(now.getHours()) + p(now.getMinutes()) + ".txt";
  var url = URL.createObjectURL(new Blob([t], { type:"text/plain;charset=utf-8" }));
  var a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
});

/* ---------------- 启动 ---------------- */
init().catch(function(err){
  document.body.insertAdjacentHTML("afterbegin", '<p style="color:#d93025;padding:12px">初始化失败：' + esc(err) + "</p>");
});
window.addEventListener("load", function(){ $("pasted").focus(); });
</script>
</body>
</html>
"""
