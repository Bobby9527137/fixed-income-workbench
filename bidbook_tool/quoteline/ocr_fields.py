# -*- coding: utf-8 -*-
"""从 DM 截图里提取报价需要补全的字段。

不依赖固定坐标：先用「剩余期限 / 票面利率 / 中债估值 / 债项评级 / 主体评级」
这些标签定位，再在标签正下方（或同一行右侧）找值。这样整窗截图和只裁
顶部条都能用。

只读「中债估值」，绝不读「中证估值」；债项评级识别不到时留给上层默认 ``--``。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageOps

from .parse import (
    find_code,
    find_coupon,
    find_name,
    find_offering,
    find_ratings,
    find_term,
    normalize_input,
    normalize_rating,
)


# --------------------------------------------------------------------------- #
# 内部结构
# --------------------------------------------------------------------------- #

@dataclass
class _Box:
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


def _prepare(boxes: Iterable[Any]) -> List[_Box]:
    prepared: List[_Box] = []
    for item in boxes:
        text = normalize_input(getattr(item, "text", ""))
        if not text:
            continue
        prepared.append(
            _Box(
                text=text,
                x0=float(getattr(item, "x0", 0.0)),
                y0=float(getattr(item, "y0", 0.0)),
                x1=float(getattr(item, "x1", 0.0)),
                y1=float(getattr(item, "y1", 0.0)),
                score=float(getattr(item, "score", 1.0) or 1.0),
            )
        )
    prepared.sort(key=lambda box: (box.y0, box.x0))
    return prepared


# --------------------------------------------------------------------------- #
# 标签与取值
# --------------------------------------------------------------------------- #

def _label_kind(text: str) -> str:
    """判断一段文字是哪种标签；不是标签返回空串。"""
    text = normalize_input(text)
    if not text:
        return ""
    if "剩余期限" in text or ("剩余" in text and "期限" in text):
        return "term"
    if "票面利率" in text or ("票面" in text and ("利率" in text or "率" in text)):
        return "coupon"
    if (
        "中债" in text
        and ("估值" in text or "值" in text or "价" in text)
        and "中证" not in text
        and "中証" not in text
    ):
        return "cbt"
    if "债项" in text and "评级" in text and "变化" not in text:
        return "bond_rating"
    if "主体" in text and "评级" in text and "变化" not in text:
        return "main_rating"
    return ""


def _trailing_value(text: str, kind: str) -> str:
    """标签和值挤在一个框里时（如「中债估值--」），把标签去掉。"""
    text = normalize_input(text)
    if not text:
        return ""
    patterns = {
        "term": (r"^.*?剩余期限",),
        "coupon": (r"^.*?票面利率", r"^.*?票面"),
        "cbt": (r"^.*?中债估值", r"^.*?中债"),
        "bond_rating": (r"^.*?债项评级", r"^.*?债项"),
        "main_rating": (r"^.*?主体评级", r"^.*?主体"),
    }
    for pattern in patterns.get(kind, ()):
        new_text = re.sub(pattern, "", text)
        if new_text != text:
            return new_text.strip()
    return ""


def _value_term(text: str) -> str:
    return find_term(text)


def _value_coupon(text: str) -> str:
    return find_coupon(text)


def _value_cbt(text: str) -> str:
    text = normalize_input(text)
    if not text:
        return ""
    part = re.split(r"[/|]", text, 1)[0].strip()
    part = part.replace("—", "-").replace("–", "-").replace("－", "-").replace("−", "-")
    if part in ("--", "-", "——", "无"):
        return "--"
    # 「10-26」这种是日期，不是估值
    if re.fullmatch(r"\d{2}-\d{2}", part):
        return ""
    match = re.search(r"\d+(?:\.\d+)?", part)
    return match.group(0) if match else ""


def _value_rating(text: str) -> str:
    text = normalize_input(text)
    if not text:
        return ""
    if text in ("--", "-", "——", "无"):
        return "--"
    main, bond = find_ratings(text)
    return main or bond


def _value_offering(text: str) -> str:
    return find_offering(text)


_VALIDATORS = {
    "term": _value_term,
    "coupon": _value_coupon,
    "cbt": _value_cbt,
    "bond_rating": _value_rating,
    "main_rating": _value_rating,
}


# --------------------------------------------------------------------------- #
# 位置匹配
# --------------------------------------------------------------------------- #

def _find_label(boxes: Sequence[_Box], kind: str) -> Optional[_Box]:
    matches = [box for box in boxes if _label_kind(box.text) == kind]
    if not matches:
        return None
    return min(matches, key=lambda box: (box.y0, box.x0))


def _horizontal_match(label: _Box, candidate: _Box) -> bool:
    overlap = min(label.x1, candidate.x1) - max(label.x0, candidate.x0)
    if overlap >= max(4.0, 0.15 * min(label.w, candidate.w)):
        return True
    return label.x0 - 0.3 * label.w <= candidate.cx <= label.x1 + 0.3 * label.w


def _pick_value(label: _Box, boxes: Sequence[_Box], validator) -> str:
    """优先标签正下方，其次同一行右侧；只接受能通过字段校验的框。"""
    max_gap = max(60.0, label.h * 4.0)

    below: List[Tuple[float, _Box]] = []
    for box in boxes:
        if box is label or _label_kind(box.text):
            continue
        gap = box.y0 - label.y1
        if gap < -4.0 or gap > max_gap:
            continue
        if not _horizontal_match(label, box):
            continue
        value = validator(box.text)
        if not value:
            continue
        score = max(0.0, gap) + 0.2 * abs(box.cx - label.cx)
        below.append((score, box))
    if below:
        return validator(min(below, key=lambda item: item[0])[1].text)

    right: List[Tuple[float, _Box]] = []
    for box in boxes:
        if box is label or _label_kind(box.text):
            continue
        if abs(box.cy - label.cy) > max(6.0, label.h * 0.6):
            continue
        if box.x0 < label.x1 - 2.0:
            continue
        if box.x0 - label.x1 > max(40.0, label.w * 3.0):
            continue
        value = validator(box.text)
        if not value:
            continue
        score = (box.x0 - label.x1) + 0.1 * abs(box.cy - label.cy)
        right.append((score, box))
    if right:
        return validator(min(right, key=lambda item: item[0])[1].text)
    return ""


def _header_y(boxes: Sequence[_Box], height: float) -> float:
    for kind in ("term", "coupon", "cbt", "bond_rating"):
        matches = [box for box in boxes if _label_kind(box.text) == kind]
        if matches:
            return min(box.y0 for box in matches)
    if height:
        return height * 0.25
    return max((box.y1 for box in boxes), default=0.0)


def _title_fields(boxes: Sequence[_Box], header_y: float) -> Tuple[str, str]:
    """标题行是「紧挨着表头、最靠下」的那条带代码的框，不是上方标签页。"""
    above = [
        box for box in boxes if find_code(box.text) and box.y1 <= header_y + 8.0
    ]
    candidates = above or [box for box in boxes if find_code(box.text)]
    if not candidates:
        return "", ""
    title = max(candidates, key=lambda box: (box.y1, -box.x0))
    code = find_code(title.text)
    name = find_name(title.text)
    if not name:
        left = [
            box
            for box in boxes
            if abs(box.cy - title.cy) <= max(8.0, title.h * 0.8)
            and box.x1 <= title.x0 + 8.0
            and find_name(box.text)
        ]
        if left:
            name = find_name(max(left, key=lambda box: box.x1).text)
    return code, name


# --------------------------------------------------------------------------- #
# 主提取
# --------------------------------------------------------------------------- #

def extract_fields(
    boxes: Iterable[Any],
    width: float = 0.0,
    height: float = 0.0,
) -> Dict[str, str]:
    """从 OCR 文本框里提取字段；只返回认出来的键。"""
    prepared = _prepare(boxes)
    if not prepared:
        return {}

    header_y = _header_y(prepared, height)
    limit_y = header_y + max(120.0, height * 0.12)

    result: Dict[str, str] = {}

    code, name = _title_fields(prepared, header_y)
    if code:
        result["code"] = code
    if name:
        result["name"] = name

    offering_boxes = [
        box for box in prepared if box.y0 <= limit_y and _value_offering(box.text)
    ]
    if offering_boxes:
        offering = min(offering_boxes, key=lambda box: (box.y0, box.x0))
        result["offering"] = _value_offering(offering.text)

    specs = (
        ("term", "term"),
        ("coupon", "coupon"),
        ("cbt", "cbt"),
        ("bond_rating", "rating_bond"),
        ("main_rating", "rating_main"),
    )
    for kind, key in specs:
        label = _find_label(prepared, kind)
        if label is None:
            continue
        validator = _VALIDATORS[kind]
        trailing = _trailing_value(label.text, kind)
        value = validator(trailing) if trailing else ""
        if not value:
            value = _pick_value(label, prepared, validator)
        if value:
            result[key] = value

    return result


# --------------------------------------------------------------------------- #
# 跑 OCR（含反色兜底）
# --------------------------------------------------------------------------- #

def run_fields(
    img: Image.Image,
    engine: str = "auto",
    *,
    second_pass: bool = True,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """对 DM 截图跑 OCR 并提取字段，返回 (字段, 识别元信息)。"""
    from bidbook import ocr as ocr_mod

    rgb = img.convert("RGB")
    width, height = rgb.size
    crop_height = min(height, max(320, int(height * 0.32)))
    crop = rgb.crop((0, 0, width, crop_height))

    started = time.time()
    used_engine, boxes = ocr_mod.run_ocr(crop, engine=engine)
    fields = extract_fields(boxes, width, crop_height)
    attempts: List[Dict[str, Any]] = [
        {
            "variant": "original",
            "engine": used_engine,
            "text_count": len(boxes),
        }
    ]

    key_fields = ("code", "name", "term", "coupon", "cbt", "rating_main")
    missing = [key for key in key_fields if not fields.get(key)]
    if second_pass and missing:
        try:
            alt = ImageOps.autocontrast(ImageOps.invert(crop))
            if alt.width < 1400:
                alt = alt.resize((alt.width * 2, alt.height * 2), Image.LANCZOS)
            alt_engine, alt_boxes = ocr_mod.run_ocr(alt, engine=engine)
            alt_fields = extract_fields(alt_boxes, alt.width, alt.height)
            for key, value in alt_fields.items():
                if value and not fields.get(key):
                    fields[key] = value
            attempts.append(
                {
                    "variant": "inverted",
                    "engine": alt_engine,
                    "text_count": len(alt_boxes),
                    "filled": sorted(
                        key for key in alt_fields if not fields.get(key) or alt_fields[key] == fields.get(key)
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 反色只是兜底，失败不影响主结果
            attempts.append(
                {
                    "variant": "inverted",
                    "engine": engine,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    meta = {
        "engine": used_engine,
        "elapsed": round(time.time() - started, 2),
        "text_count": len(boxes),
        "crop": [width, crop_height],
        "attempts": attempts,
        "texts": [box.text for box in boxes][:200],
    }
    return fields, meta


# --------------------------------------------------------------------------- #
# 自检用的合成文本框（不依赖 OCR 引擎）
# --------------------------------------------------------------------------- #

def _box(text: str, x0: float, y0: float, x1: float, y1: float) -> _Box:
    return _Box(text=text, x0=x0, y0=y0, x1=x1, y1=y1)


SAMPLE_BOXES_CROPPED = [
    _box("26济南城建SCP004（012681631.IB）", 32, 26, 465, 56),
    _box("公募", 636, 24, 690, 54),
    _box("主体评级", 1988, 75, 2087, 102),
    _box("剩余期限", 21, 86, 123, 117),
    _box("修正久期", 231, 87, 331, 116),
    _box("票面利率", 406, 88, 504, 116),
    _box("中债估值--", 580, 87, 701, 116),
    _box("中证估值11-03", 982, 88, 1148, 115),
    _box("流动性评分", 1383, 87, 1505, 116),
    _box("债项评级", 1557, 87, 1657, 116),
    _box("隐含评级", 1717, 86, 1818, 116),
    _box("AAA", 1986, 118, 2046, 149),
    _box("3D", 19, 131, 62, 162),
    _box("1.3600%", 406, 133, 514, 159),
    _box("1.4187/99.9958", 982, 133, 1188, 159),
    _box("A", 1395, 140, 1406, 155),
    _box("AA+中证", 1717, 170, 1839, 202),
]

SAMPLE_BOXES_FULL = [
    _box("26溧水03（284247.SH)", 1001, 150, 1212, 179),
    _box("26深圳地铁MTN007B（102682458.IB）", 25, 211, 383, 236),
    _box("公募☆国", 484, 207, 608, 236),
    _box("主体评级", 1526, 246, 1607, 270),
    _box("DM评分", 1623, 245, 1697, 272),
    _box("剩余期限", 14, 255, 97, 282),
    _box("修正久期", 175, 255, 257, 282),
    _box("票面利率", 309, 255, 391, 282),
    _box("中债估值--", 443, 255, 539, 282),
    _box("流动性评分", 1059, 255, 1158, 282),
    _box("债项评级", 1194, 255, 1276, 282),
    _box("隐含评级", 1318, 255, 1400, 282),
    _box("中证估值10-26", 753, 258, 885, 280),
    _box("AAA", 1194, 288, 1244, 317),
    _box("**", 1318, 288, 1348, 311),
    _box("AAA", 1524, 279, 1577, 307),
    _box("9.69Y", 15, 291, 75, 316),
    _box("2.5000%", 309, 290, 400, 317),
    _box("--/--", 444, 291, 492, 315),
    _box("2.1885/102.6824", 752, 290, 928, 316),
    _box("B", 1063, 290, 1090, 316),
    _box("AAA中证", 1319, 320, 1418, 347),
    _box("公募", 841, 387, 889, 413),
]
