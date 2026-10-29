# -*- coding: utf-8 -*-
"""本地网页服务：上传表格截图 → OCR → 认列 → 和文本行对齐 → 输出固定文案。

图片以 base64 放在 JSON 里上传，这样即使 python-multipart 没装好也不会影响上传。
"""

from __future__ import annotations

import base64
import binascii
import importlib.util
import io
import sys
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image

try:
    from fastapi import File, UploadFile
except Exception:  # noqa: BLE001  pragma: no cover
    File = UploadFile = None  # type: ignore

# python-multipart 没装好时，FastAPI 会在「定义 File() 路由」那一刻就抛
# RuntimeError: Form data requires "python-multipart" to be installed，
# 整个服务都起不来。所以先探一下，装不上就干脆不注册这个备用入口
# （网页默认走 base64 上传，不依赖它）。
_HAS_MULTIPART = importlib.util.find_spec("multipart") is not None

from . import __version__
from . import ocr as ocr_mod
from . import rows as rows_mod
from . import table as table_mod
from .page import INDEX_HTML

MAX_SIDE = 2600  # 超过就先等比缩小，OCR 更快也更稳

app = FastAPI(title="投标簿记信息提取工具", version=__version__)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def _prepare_image(img: Image.Image) -> Image.Image:
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    scale = MAX_SIDE / float(max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return img


def _decode_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return _prepare_image(img)


def _decode_data_url(data_url: str) -> bytes:
    if "," in data_url and data_url.strip().lower().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    try:
        return base64.b64decode(data_url, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"图片 base64 解码失败：{exc}") from exc


def _table_payload(
    table: table_mod.RenderedTable,
    table_rows: Sequence[table_mod.TableRow],
) -> dict:
    return {
        "method": table.method,
        "image_width": table.image_width,
        "image_height": table.image_height,
        "columns": [{"x0": round(a, 1), "x1": round(b, 1)} for a, b in table.columns],
        "header_texts": list(table.column_texts),
        "header_map": [table.header_map.get(i, "") for i in range(len(table.columns))],
        "warnings": list(table.warnings),
        "rows": [r.as_dict() for r in table_rows],
    }


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/api/config")
def api_config() -> dict:
    return {
        "version": __version__,
        "engines": ocr_mod.available_engines(),
        "time_slots": rows_mod.TIME_SLOTS,
        "final_slot": rows_mod.FINAL_SLOT,
        # 时点：默认按电脑时间自动判断，网页上也可以直接指定「目前边际 / 最终边际」
        "time_choices": rows_mod.TIME_CHOICES,
        "default_time_choice": rows_mod.DEFAULT_TIME_CHOICE,
        "server_time": rows_mod.now_info(),
        "headers": table_mod.CANONICAL_HEADERS,
        "needed": table_mod.NEEDED_FIELDS,
        # 匹配门槛：默认 0.90，网页滑块的默认值/范围也从这里取
        "default_threshold": rows_mod.DEFAULT_THRESHOLD,
        "threshold_min": 0.70,
        "threshold_max": 0.98,
        "warn_score": rows_mod.WARN_SCORE,
        # 窗口 2 不接受整段簿记文本（这些词一出现就整段不解析）
        "value_blacklist": list(rows_mod.VALUE_BLACKLIST),
        "value_reject_message": rows_mod.VALUE_REJECT_MESSAGE,
    }


@app.post("/api/recognize")
def api_recognize(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    engine = str(payload.get("engine") or "auto")
    images: List[dict] = []

    raw_list = payload.get("images") or []
    if not isinstance(raw_list, list):
        return JSONResponse({"ok": False, "error": "images 必须是数组"}, status_code=400)

    for idx, item in enumerate(raw_list):
        name = f"图片{idx + 1}"
        try:
            if isinstance(item, str):
                data = _decode_data_url(item)
            else:
                name = str(item.get("name") or name)
                if item.get("data_url"):
                    data = _decode_data_url(str(item["data_url"]))
                elif item.get("data_b64"):
                    data = base64.b64decode(str(item["data_b64"]))
                else:
                    raise ValueError("既没有 data_url 也没有 data_b64")
        except Exception as exc:  # noqa: BLE001
            images.append({"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            continue

        try:
            img = _decode_image(data)
        except Exception as exc:  # noqa: BLE001
            images.append({"name": name, "ok": False, "error": f"图片打不开：{exc}"})
            continue

        try:
            started = time.time()
            used_engine, boxes = ocr_mod.run_ocr(img, engine=engine)
            bgr = np.array(img.convert("RGB"))[:, :, ::-1].copy()
            table_model, table_rows = table_mod.parse_image(
                bgr, boxes, guess_columns=bool(payload.get("guess_columns", True))
            )
            images.append({
                "name": name,
                "ok": True,
                "engine": used_engine,
                "elapsed": round(time.time() - started, 2),
                "text_count": len(boxes),
                "texts": [b.text for b in boxes][:400],
                "table": _table_payload(table_model, table_rows),
            })
        except Exception as exc:  # noqa: BLE001
            images.append({"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    return JSONResponse({"ok": True, "images": images})


def _register_upload_route() -> None:
    """multipart 形式的备用入口（网页默认走 base64，用不到也不影响）。"""

    @app.post("/api/upload")
    async def api_upload(files: List[UploadFile] = File(default=[])) -> JSONResponse:
        return await _upload_impl(files)

    return None


async def _upload_impl(files: List[UploadFile]) -> JSONResponse:
    images = []
    for f in files or []:
        try:
            data = await f.read()
            img = _decode_image(data)
            used_engine, boxes = ocr_mod.run_ocr(img, engine="auto")
            bgr = np.array(img.convert("RGB"))[:, :, ::-1].copy()
            table_model, table_rows = table_mod.parse_image(bgr, boxes)
            images.append({
                "name": f.filename or "上传图片",
                "ok": True,
                "engine": used_engine,
                "text_count": len(boxes),
                "table": _table_payload(table_model, table_rows),
            })
        except Exception as exc:  # noqa: BLE001
            images.append({"name": getattr(f, "filename", "上传图片"), "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return JSONResponse({"ok": True, "images": images})


if _HAS_MULTIPART:
    _register_upload_route()


@app.get("/api/debug-crop")
def api_debug_crop(
    x0: int = 0, y0: int = 0, x1: int = 100, y1: int = 100, engine: str = "auto"
) -> JSONResponse:
    """诊断用：对某个区域单独再跑一次 OCR，看是识别问题还是切列问题。"""
    return JSONResponse({
        "ok": False,
        "error": "该诊断接口需要先在内存里持有图片；请直接用「重新识别」按钮并查看 consts/columns 信息。",
        "region": [x0, y0, x1, y1],
        "engine": engine,
    })


@app.post("/api/build")
def api_build(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    pasted = str(payload.get("text") or "")
    # 第二个窗口：边际数据文本（截图里没有的，靠它也能出数）
    values_text = str(payload.get("values_text") or "")
    # default_time 可以是 auto（按电脑时间）/ current（目前边际）/ final（最终边际）/ "17:40"
    time_choice = str(payload.get("default_time") or rows_mod.DEFAULT_TIME_CHOICE)
    default_time = rows_mod.resolve_default_time(time_choice)
    show_time = bool(payload.get("show_time") or False)
    threshold = payload.get("threshold")
    threshold = (float(threshold) if threshold not in (None, "")
                 else rows_mod.DEFAULT_THRESHOLD)
    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}

    table_rows: List[table_mod.TableRow] = []
    for item in payload.get("rows") or []:
        if not isinstance(item, dict):
            continue
        table_rows.append(table_mod.TableRow(
            code=str(item.get("code") or ""),
            name=str(item.get("name") or ""),
            raw_name=str(item.get("raw_name") or item.get("name") or ""),
            margin_rate=_opt_float(item.get("margin_rate")),
            full_ratio=_opt_float(item.get("full_ratio")),
            edge_ratio=_opt_float(item.get("edge_ratio")),
            index=int(item.get("index") or (len(table_rows) + 1)),
        ))

    inputs = rows_mod.parse_input(pasted, auto_mode=default_time)
    if not inputs:
        return JSONResponse({"ok": False, "error": "没有解析到任何文本行，请检查粘贴内容"}, status_code=400)

    # 窗口 2 收到整段簿记文本：直接弹窗报错（见下面的 values_rejected），并且整段不解析
    values_rejected = rows_mod.check_values_text(values_text)
    value_problems: List[str] = []
    value_rows = rows_mod.parse_values(values_text, problems=value_problems)

    results = rows_mod.match_rows(
        inputs, table_rows, threshold=threshold, value_rows=value_rows,
    )
    text, results = rows_mod.format_results(
        results, default_time=default_time, show_time=show_time, overrides=overrides,
    )
    return JSONResponse({
        "ok": True,
        "text": text,
        # 实际用的时点（按电脑时间算出来的那个），网页上直接显示给用户核对
        "time_choice": time_choice,
        "time_slot": default_time,
        "mode": "最终边际" if default_time == rows_mod.FINAL_SLOT else "目前边际",
        # 一行一只：没对应上的也出一行，缺的数写「待定」
        "count": sum(1 for r in results if r.line),
        "no_data_count": sum(1 for r in results if not r.has_data),
        "pending_count": sum(1 for r in results if r.pending),
        "review_count": sum(1 for r in results if r.review),
        "value_count": len(value_rows),
        "value_problems": value_problems[:5],
        # 非空 = 窗口 2 粘贴了完整簿记文本，网页据此弹窗提示
        "values_rejected": values_rejected,
        "values_error": rows_mod.VALUE_REJECT_MESSAGE if values_rejected else "",
        "results": [r.as_dict() for r in results],
        "table_rows": [r.as_dict() for r in table_rows],
    })


def _opt_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #

def _probe(url: str, timeout: float = 1.0) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:  # noqa: BLE001
        return False


def run(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True, warmup: bool = True) -> None:
    import uvicorn

    url = f"http://{host}:{port}/"
    if _probe(url):
        print(f"[i] 服务已经在运行：{url}")
        if open_browser:
            webbrowser.open(url)
        return

    if warmup:
        engines = [e for e in ocr_mod.available_engines() if e["available"]]
        print("[i] 可用 OCR 引擎：" + ("、".join(e["key"] for e in engines) or "无"))
        if any(e["key"] == "rapidocr" for e in engines):
            def _preload() -> None:
                try:
                    ocr_mod._load_rapidocr()
                    print("[i] RapidOCR 模型已加载")
                except Exception as exc:  # noqa: BLE001
                    print(f"[!] RapidOCR 预加载失败（识别时会自动换引擎）：{exc}")

            threading.Thread(target=_preload, daemon=True).start()

    if open_browser:
        def _open() -> None:
            time.sleep(1.2)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    print(f"[i] 打开浏览器访问：{url}")
    print("[i] 关闭本窗口（或按 Ctrl+C）即停止服务")
    uvicorn.run(app, host=host, port=port, log_level="warning")
