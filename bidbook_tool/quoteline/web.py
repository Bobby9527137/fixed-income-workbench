# -*- coding: utf-8 -*-
"""本地网页服务：交易行文本 + DM 截图 → 一行固定格式报价。

图片用 base64 放在 JSON 里上传，不依赖 python-multipart；所有识别都在本机完成。
"""

from __future__ import annotations

import base64
import binascii
import io
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from PIL import Image, ImageOps

from bidbook import ocr as ocr_mod

from . import __version__, parse
from . import ocr_fields as ocr_fields_mod
from . import selfcheck as selfcheck_mod
from .page import INDEX_HTML

MAX_SIDE = 3200
MAX_UPLOAD_MB = 20

app = FastAPI(title="报价要素生成工具", version=__version__)

_SAMPLE_CACHE: Optional[str] = None


# --------------------------------------------------------------------------- #
# 图片
# --------------------------------------------------------------------------- #

def _prepare_image(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    width, height = img.size
    scale = MAX_SIDE / float(max(width, height))
    if scale < 1.0:
        img = img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.LANCZOS,
        )
    return img


def _decode_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return _prepare_image(img)


def _decode_data_url(data_url: str) -> bytes:
    if not data_url:
        raise ValueError("图片为空")
    if "," in data_url and data_url.strip().lower().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    try:
        return base64.b64decode(data_url, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"图片 base64 解码失败：{exc}") from exc


def _sample_path() -> Path:
    return Path(__file__).resolve().with_name("sample.png")


def _sample_data_url() -> str:
    global _SAMPLE_CACHE
    if _SAMPLE_CACHE is not None:
        return _SAMPLE_CACHE
    path = _sample_path()
    if not path.is_file():
        return ""
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    _SAMPLE_CACHE = "data:image/png;base64," + payload
    return _SAMPLE_CACHE


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
        "fields": [
            {"key": key, "label": parse.FIELD_LABELS[key]}
            for key in parse.FIELD_ORDER
        ],
        "sample_text": parse.SAMPLE_TEXT,
        "sample_expected": parse.SAMPLE_EXPECTED,
        "max_upload_mb": MAX_UPLOAD_MB,
    }


@app.get("/api/sample")
def api_sample() -> dict:
    return {
        "ok": True,
        "text": parse.SAMPLE_TEXT,
        "expected": parse.SAMPLE_EXPECTED,
        "image_b64": _sample_data_url(),
        "note": "示例截图是本地生成的 DM 风格头部，不含任何真实业务数据。",
    }


@app.get("/api/sample.png")
def api_sample_png() -> Response:
    path = _sample_path()
    if not path.is_file():
        return Response(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/png")


@app.get("/api/selfcheck")
def api_selfcheck() -> JSONResponse:
    return JSONResponse(selfcheck_mod.run_checks())


@app.get("/api/health")
def api_health() -> dict:
    return {"ok": True, "version": __version__}


@app.post("/api/parse")
def api_parse(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    text = str(payload.get("text") or "")
    image_b64 = str(payload.get("image_b64") or "")
    engine = str(payload.get("engine") or "auto")

    fields: Dict[str, str] = {}
    ocr_meta: Dict[str, Any] = {}
    ocr_error = ""

    if image_b64:
        try:
            data = _decode_data_url(image_b64)
            img = _decode_image(data)
            fields, ocr_meta = ocr_fields_mod.run_fields(img, engine=engine)
        except Exception as exc:  # noqa: BLE001 - 识别失败也要让交易行单独出结果
            ocr_error = f"{type(exc).__name__}: {exc}"

    if not text.strip() and not fields:
        message = f"截图识别失败：{ocr_error}" if ocr_error else "请粘贴交易行文本，或上传 DM 截图。"
        return JSONResponse({"ok": False, "error": message}, status_code=400)

    result = parse.generate(text, fields, has_image=bool(image_b64))
    if ocr_error:
        result["warnings"].insert(0, "截图识别失败：" + ocr_error)
    return JSONResponse(
        {
            "ok": True,
            "ocr_error": ocr_error,
            "ocr": ocr_meta,
            **result,
        }
    )


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


def run(
    host: str = "127.0.0.1",
    port: int = 8766,
    *,
    open_browser: bool = True,
    warmup: bool = True,
) -> None:
    import uvicorn

    url = f"http://{host}:{port}/"
    if _probe(url):
        print(f"[i] 服务已经在运行：{url}")
        if open_browser:
            webbrowser.open(url)
        return

    if warmup:
        engines = [item for item in ocr_mod.available_engines() if item["available"]]
        print("[i] 可用 OCR 引擎：" + ("、".join(item["key"] for item in engines) or "无"))
        if any(item["key"] == "rapidocr" for item in engines):
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
