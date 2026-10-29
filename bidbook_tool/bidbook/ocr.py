# -*- coding: utf-8 -*-
"""OCR 层：把图片变成 (文字, 像素包围盒, 置信度) 列表。

三条引擎链，全部离线、免费：
1. rapidocr  —— 基于 ONNXRuntime + PaddleOCR 模型，中文表格识别最稳（首选）
2. vision    —— macOS 自带 Vision 框架（pyobjc），零模型下载、速度极快
3. tesseract —— 系统里已有 tesseract 时可作为最后兜底

任何一条链不可用都不会让程序崩溃：`available_engines()` 会告诉你可用的有哪些，
`run_ocr()` 会按优先级自动挑选。
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image


@dataclass
class TextBox:
    """一段被识别出来的文字。坐标是像素坐标，(0, 0) 在左上角。"""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def w(self) -> float:
        return max(1.0, self.x1 - self.x0)

    @property
    def h(self) -> float:
        return max(1.0, self.y1 - self.y0)

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "x0": round(self.x0, 1),
            "y0": round(self.y0, 1),
            "x1": round(self.x1, 1),
            "y1": round(self.y1, 1),
            "score": round(float(self.score), 4),
        }


# --------------------------------------------------------------------------- #
# 文本清洗
# --------------------------------------------------------------------------- #

_FULL2HALF = {
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D", "Ｅ": "E", "Ｆ": "F",
    "Ｇ": "G", "Ｈ": "H", "Ｉ": "I", "Ｊ": "J", "Ｋ": "K", "Ｌ": "L",
    "Ｍ": "M", "Ｎ": "N", "Ｏ": "O", "Ｐ": "P", "Ｑ": "Q", "Ｒ": "R",
    "Ｓ": "S", "Ｔ": "T", "Ｕ": "U", "Ｖ": "V", "Ｗ": "W", "Ｘ": "X",
    "Ｙ": "Y", "Ｚ": "Z", "．": ".", "，": ",", "％": "%", "　": " ",
}


def normalise_text(text: str) -> str:
    """统一全角/半角、去空白、去零宽字符。"""
    if not text:
        return ""
    out = []
    for ch in text:
        if ch in ("\u200b", "\ufeff", "\u200e", "\u200f"):
            continue
        out.append(_FULL2HALF.get(ch, ch))
    s = "".join(out)
    s = re.sub(r"\s+", "", s)
    return s


def strip_junk(text: str) -> str:
    """去掉 OCR 常见的噪点字符，但保留中文、字母、数字与常见标点。"""
    s = normalise_text(text)
    s = re.sub(r"[\u0000-\u001f]", "", s)
    return s


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def first_number(text: str, *, prefer_decimal: bool = False) -> Optional[float]:
    """从一段文字里取第一个数字。

    OCR 会把「1.77倍」读成「1.77倍」「1.77 」甚至「l.77倍」，所以这里做
    常见误识别纠正 (O/o/l/I → 数字)，再取第一个数值。
    """
    if text is None:
        return None
    s = normalise_text(str(text))
    s = s.replace("，", "").replace(",", "")
    # 字母误识别修正：只在紧挨数字或小数点时替换，避免把债券代码里的字母改坏
    s = re.sub(r"(?<![0-9A-Za-z])([OoIl])(?=[0-9.])", lambda m: {"O": "0", "o": "0", "l": "1", "I": "1"}[m.group(1)], s)
    s = re.sub(r"(?<=[0-9.])([OoIl])", lambda m: {"O": "0", "o": "0", "l": "1", "I": "1"}[m.group(1)], s)
    candidates = _NUM_RE.findall(s)
    if not candidates:
        return None
    values = []
    for c in candidates:
        try:
            values.append(float(c))
        except ValueError:
            continue
    if not values:
        return None
    if prefer_decimal:
        decimals = [v for v in values if "." in next((c for c in candidates if float(c) == v), "")]
        if decimals:
            return decimals[0]
    return values[0]


def format_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


# --------------------------------------------------------------------------- #
# 引擎探测
# --------------------------------------------------------------------------- #

_RAPID_CACHE: dict = {}
_TESSERACT_PATH: Optional[str] = None
_TESSERACT_CHECKED = False


def _find_tesseract() -> Optional[str]:
    global _TESSERACT_PATH, _TESSERACT_CHECKED
    if not _TESSERACT_CHECKED:
        _TESSERACT_CHECKED = True
        _TESSERACT_PATH = shutil.which("tesseract")
        if not _TESSERACT_PATH:
            for p in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"):
                if os.path.exists(p):
                    _TESSERACT_PATH = p
                    break
    return _TESSERACT_PATH


def available_engines() -> List[dict]:
    """返回当前环境里可用的 OCR 引擎（含说明），供网页显示。"""
    result = []

    rapid_ok, rapid_note = False, ""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        rapid_ok = True
        rapid_note = "已安装 rapidocr-onnxruntime"
    except Exception as exc:  # pragma: no cover - 取决于环境
        try:
            import rapidocr  # noqa: F401
            rapid_ok = True
            rapid_note = "已安装 rapidocr"
        except Exception:
            rapid_note = f"未安装：{type(exc).__name__}"
    result.append({"key": "rapidocr", "label": "RapidOCR（离线中文模型）", "available": rapid_ok, "note": rapid_note})

    vision_ok, vision_note = False, ""
    try:
        import Vision  # noqa: F401
        vision_ok = True
        vision_note = "macOS 原生 Vision 可用"
    except Exception:
        vision_note = "仅 macOS 可用（需 pyobjc-framework-Vision）"
    result.append({"key": "vision", "label": "macOS Vision（原生、无模型）", "available": vision_ok, "note": vision_note})

    tess = _find_tesseract()
    result.append({
        "key": "tesseract",
        "label": "Tesseract",
        "available": bool(tess),
        "note": tess or "未找到 tesseract（brew install tesseract tesseract-lang）",
    })
    return result


def resolve_engine(preferred: str = "auto") -> str:
    """把 auto 解析成实际可用的引擎名。全部不可用时抛 RuntimeError。"""
    engines = {e["key"]: e["available"] for e in available_engines()}
    if preferred and preferred != "auto":
        if engines.get(preferred):
            return preferred
        # 指定的引擎不可用就退回 auto，而不是直接失败
    for key in ("rapidocr", "vision", "tesseract"):
        if engines.get(key):
            return key
    raise RuntimeError(
        "没有可用的 OCR 引擎。请联网重跑本脚本以安装 RapidOCR 模型，"
        "或在 macOS 上安装 pyobjc-framework-Vision，或先 brew install tesseract tesseract-lang。"
    )


# --------------------------------------------------------------------------- #
# 图片读取
# --------------------------------------------------------------------------- #

def load_image_bytes(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    rgb = img.convert("RGB")
    arr = np.array(rgb)
    return arr[:, :, ::-1].copy()


def _pil_to_rgb(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


# --------------------------------------------------------------------------- #
# 引擎实现
# --------------------------------------------------------------------------- #

def _load_rapidocr():
    engine = _RAPID_CACHE.get("rapidocr")
    if engine is not None:
        return engine
    last_exc: Optional[Exception] = None
    for module_name in ("rapidocr_onnxruntime", "rapidocr"):
        try:
            mod = __import__(module_name, fromlist=["RapidOCR"])
            cls = getattr(mod, "RapidOCR")
            engine = cls()
            _RAPID_CACHE["rapidocr"] = engine
            return engine
        except Exception as exc:  # pragma: no cover
            last_exc = exc
    raise RuntimeError(f"RapidOCR 初始化失败：{last_exc}")


def _rapidocr_boxes(img: Image.Image) -> List[TextBox]:
    engine = _load_rapidocr()
    # RapidOCR 的 __call__ 直接吃 numpy 数组（BGR 或 RGB 都能识别）；
    # 不要用 to_numpy() 那类接口，它要求传文件路径，传图会崩。
    arr = _pil_to_bgr(img)
    result = engine(arr)
    payload: Any = result
    # 兼容多种返回形态：(list, elapse) / 对象带 .boxes/.txts/.scores / 直接 list
    if isinstance(result, tuple):
        payload = result[0]
    if payload is None:
        return []
    boxes = getattr(payload, "boxes", None)
    txts = getattr(payload, "txts", None)
    scores = getattr(payload, "scores", None)
    if boxes is not None and txts is not None:
        pairs = zip(boxes, txts)
        score_list = list(scores) if scores is not None else [1.0] * len(list(txts))
        out: List[TextBox] = []
        for idx, (box, text) in enumerate(zip(boxes, txts)):
            out.append(_box_from_points(box, text, score_list[idx] if idx < len(score_list) else 1.0))
        return out
    if not isinstance(payload, (list, tuple)):
        return []
    out = []
    for item in payload:
        if item is None:
            continue
        if isinstance(item, dict):
            box = item.get("box") or item.get("boxes") or item.get("dt_box")
            text = item.get("text") or item.get("txt") or item.get("transcription") or ""
            score = item.get("score", item.get("confidence", 1.0)) or 1.0
            out.append(_box_from_points(box, text, score))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            # RapidOCR 1.x: (points, text, score)
            points, text = item[0], item[1]
            score = item[2] if len(item) > 2 else 1.0
            if isinstance(text, (list, tuple)):
                text = text[0] if text else ""
            out.append(_box_from_points(points, text, score))
    return out


def _box_from_points(points: Any, text: Any, score: Any) -> TextBox:
    pts = np.array(points, dtype=float).reshape(-1, 2)
    x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
    x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
    return TextBox(strip_junk(str(text)), x0, y0, x1, y1, float(score or 1.0))


def _vision_boxes(img: Image.Image) -> List[TextBox]:
    import Quartz  # type: ignore
    import Vision  # type: ignore

    rgb = _pil_to_rgb(img)
    height, width = rgb.shape[:2]
    # 用 PNG 编码后的 CFData 建 CGImage：数据由 CoreFoundation 持有，
    # 不会出现 Python bytes 被回收后 CGImage 读野指针（那条路会直接把进程搞崩）。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "vision.png")
        img.convert("RGB").save(path, format="PNG")
        url = Quartz.CFURLCreateWithFileSystemPath(
            None, path, Quartz.kCFURLPOSIXPathStyle, False
        )
        source = Quartz.CGImageSourceCreateWithURL(url, None)
        if source is None:
            raise RuntimeError("Vision 预处理失败：无法读取临时 PNG")
        cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if cg_image is None:
        raise RuntimeError("Vision 预处理失败：无法解码 PNG")

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    try:
        request.setRecognitionLanguages_(["zh-Hans", "en-US"])
    except Exception:
        pass
    try:
        import objc  # type: ignore
        results, _err = handler.performRequests_error_([request], None)
    except Exception:
        handler.performRequests_error_([request], None)

    out: List[TextBox] = []
    observations = request.results() or []
    for obs in observations:
        candidates = obs.topCandidates_(1) or []
        if not candidates:
            continue
        cand = candidates[0]
        text = str(cand.string())
        score = float(cand.confidence())
        bbox = obs.boundingBox()
        origin = bbox.origin
        size = bbox.size
        x0 = float(origin.x) * width
        x1 = (float(origin.x) + float(size.width)) * width
        # Vision 的原点在左下角，转成左上角
        y1 = (1.0 - float(origin.y)) * height
        y0 = (1.0 - float(origin.y) - float(size.height)) * height
        out.append(TextBox(strip_junk(text), x0, y0, x1, y1, score))
    return out


def _tesseract_boxes(img: Image.Image) -> List[TextBox]:
    exe = _find_tesseract()
    if not exe:
        raise RuntimeError("未找到 tesseract")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "page.png")
        img.convert("RGB").save(path)
        proc = subprocess.run(
            [exe, path, "stdout", "-l", "chi_sim+eng", "--psm", "6", "tsv"],
            capture_output=True, text=True,
        )
    lines = proc.stdout.splitlines()
    if not lines:
        raise RuntimeError("tesseract 没有输出")
    header = lines[0].split("\t")
    idx = {name: i for i, name in enumerate(header)}
    out: List[TextBox] = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < len(header):
            continue
        text = parts[idx["text"]].strip()
        if not text:
            continue
        try:
            conf = float(parts[idx["conf"]])
        except ValueError:
            continue
        if conf < 30:
            continue
        x, y = float(parts[idx["left"]]), float(parts[idx["top"]])
        w, h = float(parts[idx["width"]]), float(parts[idx["height"]])
        out.append(TextBox(strip_junk(text), x, y, x + w, y + h, conf / 100.0))
    return out


_ENGINE_IMPL = {
    "rapidocr": _rapidocr_boxes,
    "vision": _vision_boxes,
    "tesseract": _tesseract_boxes,
}


def run_ocr(img: Image.Image, engine: str = "auto") -> Tuple[str, List[TextBox]]:
    """对图片跑 OCR，返回 (实际使用的引擎, 文本框列表)。"""
    resolved = resolve_engine(engine)
    boxes = _ENGINE_IMPL[resolved](img)
    boxes = [b for b in boxes if b.text]
    return resolved, boxes
