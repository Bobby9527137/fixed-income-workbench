# -*- coding: utf-8 -*-
"""表格重建：把散落的 OCR 文本框还原成「行 × 列」的表格，并认列。

思路（对固定表头的投标量表格非常稳）：
1. 用 OpenCV 形态学检测表格框线，得到列分隔线与行分隔线；
2. 若截图有水印、框线断了，退化到「按文字横坐标聚类」推列；
3. 表头行的文字按列合并后，用模糊匹配认到固定表头清单上
   （本机构投标量（万元）/ 边际利率/价格 / 全场倍数 / 边际倍数 …）；
4. 需要的三列就是「边际利率/价格、全场倍数、边际倍数」，其余列保留但不参与输出。

完全没有框线、也没有可辨认表头时，会给出候选列让用户在网页上手工指定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import fuzzy as fuzz
from .ocr import TextBox, first_number, normalise_text

# --------------------------------------------------------------------------- #
# 固定表头清单（用户给的原始表头）
# --------------------------------------------------------------------------- #

CANONICAL_HEADERS: List[str] = [
    "操作提示",
    "债券代码",
    "债券简称",
    "债券全称",
    "是否中标",
    "本机构投标量（万元）",
    "本机构中标量（万元）",
    "交款日",
    "总投单量（万元）",
    "边际利率/价格",
    "边际投单量（万元）",
    "全场倍数",
    "边际倍数",
    "簿记过程信息更新时间",
    "簿记过程信息更新频率（分钟）",
]

# 字段别名：OCR 结果 / 表头措辞与固定清单的常见差异
HEADER_ALIASES: Dict[str, List[str]] = {
    "操作提示": ["操作提示", "提示", "操作"],
    "债券代码": ["债券代码", "代码", "债券编码", "证券代码"],
    "债券简称": ["债券简称", "简称", "债券名称", "证券简称", "债券缩写"],
    "债券全称": ["债券全称", "全称"],
    "是否中标": ["是否中标", "中标", "是否"],
    "本机构投标量（万元）": ["本机构投标量（万元）", "本机构投标量", "投标量（万元）", "投标量", "本机构投标（万元）"],
    "本机构中标量（万元）": ["本机构中标量（万元）", "本机构中标量", "中标量（万元）", "中标量"],
    "交款日": ["交款日", "缴款日", "交款日期"],
    "总投单量（万元）": ["总投单量（万元）", "总投单量", "总投标量（万元）", "总投标量", "总投单"],
    "边际利率/价格": ["边际利率/价格", "边际利率/价", "边际利率", "边际价格", "目前边际", "当前边际", "边际"],
    "边际投单量（万元）": ["边际投单量（万元）", "边际投单量", "边际量（万元）", "边际量"],
    "全场倍数": ["全场倍数", "全场", "全场倍数（倍）"],
    "边际倍数": ["边际倍数", "边际", "边际倍数（倍）"],
    "簿记过程信息更新时间": ["簿记过程信息更新时间", "更新时间", "簿记更新时间"],
    "簿记过程信息更新频率（分钟）": ["簿记过程信息更新频率（分钟）", "更新频率", "频率（分钟）", "更新频率（分钟）"],
}

# 输出真正需要的三列
NEEDED_FIELDS = ["边际利率/价格", "全场倍数", "边际倍数"]

CODE_RE = re.compile(r"[A-Z0-9]{3,}")
NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
MONEYISH_RE = re.compile(r"^[\d,\.]+(?:万|亿|万元|亿元)?$")


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #

@dataclass
class RenderedCell:
    text: str
    box: Optional[TextBox] = None


@dataclass
class RenderedRow:
    y0: float
    y1: float
    cells: List[RenderedCell] = field(default_factory=list)

    def text_at(self, col: int) -> str:
        if col < 0 or col >= len(self.cells):
            return ""
        return self.cells[col].text

    @property
    def joined(self) -> str:
        return " ".join(c.text for c in self.cells if c.text)


@dataclass
class RenderedTable:
    rows: List[RenderedRow]
    columns: List[Tuple[float, float]]          # (x0, x1)
    column_texts: List[str]                     # 表头行每列的原始文字
    header_row: int
    header_map: Dict[int, str]                  # 列号 -> 固定表头名
    method: str                                 # grid | cluster
    image_width: int
    image_height: int
    grid_bbox: Optional[Tuple[float, float, float, float]] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class TableRow:
    """一行数据（表格里的一个债券）。"""

    code: str = ""
    name: str = ""
    raw_name: str = ""
    margin_rate: Optional[float] = None
    full_ratio: Optional[float] = None
    edge_ratio: Optional[float] = None
    index: int = 0
    row_y: float = 0.0
    missing: List[str] = field(default_factory=list)
    extra: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "raw_name": self.raw_name,
            "margin_rate": self.margin_rate,
            "full_ratio": self.full_ratio,
            "edge_ratio": self.edge_ratio,
            "index": self.index,
            "row_y": round(self.row_y, 1),
            "missing": list(self.missing),
            "extra": dict(self.extra),
        }


# --------------------------------------------------------------------------- #
# 框线检测
# --------------------------------------------------------------------------- #

def _to_gray(bgr: np.ndarray) -> np.ndarray:
    import cv2

    if bgr.ndim == 2:
        return bgr
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _find_lines(binary_inv: np.ndarray, axis: str, min_len: int, thickness: int = 2) -> np.ndarray:
    import cv2

    if axis == "h":
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1))
        opened = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel)
        dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len // 2 if min_len > 2 else 1, thickness))
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_len))
        opened = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel)
        dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (thickness, min_len // 2 if min_len > 2 else 1))
    return cv2.dilate(opened, dilate, iterations=1)


def _projection_lines(proj: np.ndarray, threshold: float) -> Tuple[List[int], List[int]]:
    """把投影曲线里超过阈值的连续段合并成中心线。"""
    strong = proj > threshold
    segs: List[Tuple[int, int]] = []
    start = None
    for i, s in enumerate(strong):
        if s and start is None:
            start = i
        elif not s and start is not None:
            segs.append((start, i - 1))
            start = None
    if start is not None:
        segs.append((start, len(strong) - 1))
    centres = [int(round((a + b) / 2)) for a, b in segs]
    widths = [(b - a + 1) for a, b in segs]
    return centres, widths


def detect_grid(bgr: np.ndarray) -> Optional[dict]:
    """检测表格框线。返回 cols/rows/bounds/method，检测不到返回 None。"""
    import cv2

    gray = _to_gray(bgr)
    h, w = gray.shape[:2]
    # 自适应二值化后再取反，兼容浅色框线
    # 注意 C 必须是正数：C 是「局部均值 - C」里的那个 C。写成负数（如 -2）时，
    # 大面积纯白区域（页边距、空单元格）会被判成墨迹，整片空白会被当成一条贯穿
    # 全表的长线，凭空多出好几列/好几行。C=10 表示「至少比局部背景暗 10 灰阶」才算墨。
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )
    _, binary_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.bitwise_or(binary, binary_otsu)
    # 去掉最外圈 2 像素：自适应阈值在图片边缘会产生一条贯穿全高的假「竖线」，
    # 那会被当成一列边界，把整张表的列切开。
    if binary.shape[0] > 8 and binary.shape[1] > 8:
        binary[:2, :] = 0
        binary[-2:, :] = 0
        binary[:, :2] = 0
        binary[:, -2:] = 0

    min_h = max(20, int(w * 0.25))
    min_v = max(20, int(h * 0.10))
    horiz = _find_lines(binary, "h", min_h)
    vert = _find_lines(binary, "v", min_v)

    def strongest_axis(mask: np.ndarray, axis: str) -> Optional[dict]:
        if mask is None or mask.sum() == 0:
            return None
        proj = mask.sum(axis=1 if axis == "h" else 0).astype(float)
        # 横线：proj 是每行的横向跨度（上限 = 图宽）。竖线：proj 是每列的纵向跨度（上限 = 图高）。
        # 这里以前写反了，导致「又宽又矮」的表格（截图常见）竖线全被阈值滤掉、退化成 cluster 方案。
        length = w if axis == "h" else h
        thr = max(0.25 * (length * 255), 0.05 * proj.max())
        centres, widths = _projection_lines(proj, thr)
        if len(centres) < 2:
            # 阈值太狠，退一步：只要线段占到图长 10%、且不是明显的小碎块就算线。
            # （不能再用 0.5*proj.max()：表里总有一两条长线，那样退一步等于没退）
            thr = max(0.10 * (length * 255), 0.3 * proj.max())
            centres, widths = _projection_lines(proj, thr)
        if len(centres) < 2:
            return None
        return {"centres": centres, "widths": widths, "extent": float((mask > 0).sum())}

    hz = strongest_axis(horiz, "h")
    vt = strongest_axis(vert, "v")
    if not hz or not vt:
        return None

    rows = _dedup_positions(hz["centres"], tol=max(3, int(h * 0.004)))
    cols = _dedup_positions(vt["centres"], tol=max(3, int(w * 0.004)))
    if len(rows) < 3 or len(cols) < 4:
        return None

    bounds = (float(cols[0]), float(rows[0]), float(cols[-1]), float(rows[-1]))
    return {"cols": cols, "rows": rows, "bounds": bounds, "method": "grid"}


def _dedup_positions(values: Sequence[int], tol: int) -> List[int]:
    out: List[int] = []
    for v in sorted(values):
        if out and abs(v - out[-1]) <= tol:
            continue
        out.append(int(v))
    return out


def _cluster_columns(boxes: Sequence[TextBox], y0: float, y1: float, width: int) -> List[Tuple[float, float]]:
    """无框线退化方案：按表头行文字的横坐标聚类成列。"""
    header_boxes = [b for b in boxes if b.cy >= y0 and b.cy <= y1]
    if not header_boxes:
        header_boxes = list(boxes)
    items = sorted(header_boxes, key=lambda b: b.cx)
    groups: List[List[TextBox]] = []
    gap_limit = max(12.0, width * 0.02)
    for b in items:
        if groups and b.x0 - groups[-1][-1].x1 <= gap_limit * 0.6:
            groups[-1].append(b)
        else:
            groups.append([b])
    columns: List[Tuple[float, float]] = []
    for g in groups:
        columns.append((min(b.x0 for b in g), max(b.x1 for b in g)))
    # 相邻列重叠就合并
    merged: List[Tuple[float, float]] = []
    for c in columns:
        if merged and c[0] < merged[-1][1] - 2:
            merged[-1] = (merged[-1][0], max(merged[-1][1], c[1]))
        else:
            merged.append(c)
    return merged


def _column_spans(boundaries: Sequence[float], min_width: float) -> List[Tuple[float, float]]:
    spans: List[Tuple[float, float]] = []
    for a, b in zip(boundaries, boundaries[1:]):
        if b - a >= min_width:
            spans.append((float(a), float(b)))
    return spans


# --------------------------------------------------------------------------- #
# 把文本框塞进行列
# --------------------------------------------------------------------------- #

def _assign_to_bands(boxes: Sequence[TextBox], edges: Sequence[float]) -> List[List[TextBox]]:
    bands: List[List[TextBox]] = [[] for _ in range(max(0, len(edges) - 1))]
    for b in boxes:
        placed = False
        for idx in range(len(bands)):
            if edges[idx] <= b.cy < edges[idx + 1]:
                bands[idx].append(b)
                placed = True
                break
        if not placed:
            # 落在表格上下边缘外：贴到最近的一条带
            if bands:
                idx = 0 if b.cy < edges[0] else len(bands) - 1
                bands[idx].append(b)
    for band in bands:
        band.sort(key=lambda b: b.x0)
    return bands


def _merge_texts(items: Sequence[TextBox]) -> str:
    if not items:
        return ""
    ordered = sorted(items, key=lambda b: (round(b.x0 / 3.0), b.x0))
    return normalise_text("".join(b.text for b in ordered))


def _column_limits(spans: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """每一列允许接纳文字框的横向窗口。

    底线是「列宽 ±18%」的容差（OCR 的文字框经常比格子略窄/略偏），但这个窗口
    必须在相邻两列的中间线上截断——否则同一段文字会被塞进左右两列，
    表头文字因此粘连（例如「债券全称是否中标」这种）。
    """
    limits: List[Tuple[float, float]] = []
    for i, (a, b) in enumerate(spans):
        slack = max(4.0, (b - a) * 0.18)
        lo, hi = a - slack, b + slack
        if i > 0:
            lo = max(lo, (spans[i - 1][1] + a) / 2.0)
        if i + 1 < len(spans):
            hi = min(hi, (b + spans[i + 1][0]) / 2.0)
        limits.append((lo, hi))
    return limits


def _cell_in_column(
    items: Sequence[TextBox],
    span: Tuple[float, float],
    limits: Optional[Tuple[float, float]] = None,
) -> List[TextBox]:
    x0, x1 = span
    if limits is not None:
        lo, hi = limits
    else:
        width = max(1.0, x1 - x0)
        slack = max(4.0, width * 0.18)
        lo, hi = x0 - slack, x1 + slack
    return [b for b in items if lo <= b.cx <= hi]


_HEADER_ALIAS_FLAT: List[str] = sorted(
    {alias for aliases in HEADER_ALIASES.values() for alias in aliases},
    key=len,
    reverse=True,
)


def _overlapped_columns(box: TextBox, spans: Sequence[Tuple[float, float]]) -> List[int]:
    """这个文字块横跨了哪几列（只按几何位置算）。"""
    hit: List[int] = []
    for i, (a, b) in enumerate(spans):
        if box.x1 > a + 1.0 and box.x0 < b - 1.0:
            hit.append(i)
    return hit


def _split_header_box(box: TextBox, spans: Sequence[Tuple[float, float]]) -> List[TextBox]:
    """把「横跨多列的表头文字块」按已知表头名出现的位置切开。

    OCR 经常把相邻两三个表头粘成一个文字块（窄列截图尤其常见），这个块的
    整体中心只落在某一列上，旁边的列就永远拿不到自己的表头，列含义随之整体
    错位。这里用「已知表头名在文字里的出现位置」按字符比例估算每一段的横向范围。
    """
    if len(_overlapped_columns(box, spans)) < 2:
        return []
    text = box.text or ""
    n = len(text)
    if n < 2:
        return []
    pieces: List[Tuple[int, int, str]] = []
    pos = 0
    while pos < n:
        hit = ""
        for alias in _HEADER_ALIAS_FLAT:
            if alias and text.startswith(alias, pos):
                hit = alias
                break
        if hit:
            pieces.append((pos, pos + len(hit), hit))
            pos += len(hit)
        else:
            pos += 1
    if len(pieces) < 2:
        return []
    width = box.x1 - box.x0
    out: List[TextBox] = []
    for start, end, alias in pieces:
        out.append(TextBox(
            text=alias,
            x0=box.x0 + width * (start / float(n)),
            y0=box.y0,
            x1=box.x0 + width * (end / float(n)),
            y1=box.y1,
            score=box.score,
        ))
    return out


def _split_spanning_boxes(
    items: Sequence[TextBox],
    spans: Sequence[Tuple[float, float]],
) -> List[TextBox]:
    """表头行专用：把粘在一起的表头拆开，其余文字原样返回。"""
    out: List[TextBox] = []
    for box in items:
        pieces = _split_header_box(box, spans)
        out.extend(pieces if pieces else [box])
    return out


def _best_header_index(band: Sequence[TextBox], span: Tuple[float, float]) -> float:
    """表头行的打分：整行铺满程度 + 首列是否有可辨认的列名。"""
    if not band:
        return -1.0
    x0, x1 = min(b.x0 for b in band), max(b.x1 for b in band)
    coverage = (x1 - x0) / max(1.0, span[1] - span[0])
    hits = 0
    for b in band:
        score = _header_score(b.text)
        if score >= 0.62:
            hits += 1
    if hits == 0:
        return coverage * 0.4
    return coverage + min(hits, 6) * 0.12


def _alias_score(text: str, alias_n: str) -> float:
    """正文与某个别名有多像。

    单纯的 partial_ratio 会虚高：别名「边际」在「边际倍数」「边际利率」里都能拿满分，
    于是「边际倍数」这列可能被算成「边际利率/价格」。这里再乘一个长度接近度
    （短名字匹配长别名要打折），把这种「只对上一两个字」的情况压下去。
    """
    if text == alias_n:
        return 1.0
    base = max(
        fuzz.ratio(text, alias_n),
        fuzz.partial_ratio(text, alias_n),
        fuzz.token_set_ratio(text, alias_n) if len(text) > 3 else 0,
    ) / 100.0
    shorter = min(len(text), len(alias_n))
    longer = max(len(text), len(alias_n)) or 1
    return base * (0.6 + 0.4 * shorter / longer)


def _header_score(text: str) -> float:
    t = _strip_header_noise(text)
    if not t:
        return 0.0
    best = 0.0
    for aliases in HEADER_ALIASES.values():
        for alias in aliases:
            alias_n = _strip_header_noise(alias)
            if alias_n:
                best = max(best, _alias_score(t, alias_n))
    return best


def _strip_header_noise(text: str) -> str:
    t = normalise_text(text)
    t = re.sub(r"^\s*\d{1,2}[:：]\d{2}\s*", "", t)
    t = re.sub(r"^[\-\u2014\u2013:：]+", "", t)
    t = t.replace("（", "(").replace("）", ")")
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%/\.\(\)]", "", t)
    return t


def _match_header(column_text: str) -> Tuple[str, float]:
    t = _strip_header_noise(column_text)
    if not t:
        return ("", 0.0)
    best_name, best_score = "", 0.0
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            alias_n = _strip_header_noise(alias)
            if not alias_n:
                continue
            score = _alias_score(t, alias_n)
            if score > best_score + 1e-9:
                best_name, best_score = canonical, score
    if best_score < 0.55:
        return ("", best_score)
    return (best_name, best_score)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def parse_table(
    bgr: np.ndarray,
    boxes: Sequence[TextBox],
    *,
    prefer_grid: bool = True,
) -> RenderedTable:
    h, w = bgr.shape[:2]
    warnings: List[str] = []
    grid = detect_grid(bgr) if prefer_grid else None

    if grid:
        rows_edges = grid["rows"]
        cols = _column_spans(grid["cols"], min_width=max(8.0, w * 0.006))
        method = "grid"
        bounds = grid["bounds"]
    else:
        # 退化：按整体文字的纵向聚类分行，按表头行横坐标聚类分列
        method = "cluster"
        bounds = (0.0, 0.0, float(w), float(h))
        if not boxes:
            return RenderedTable([], [], [], 0, {}, method, w, h, bounds, ["没有识别到任何文字"])
        warnings.append("没检测到表格框线，已按文字坐标重建（请在网页上核对列对应关系）")
        rows_edges = _cluster_row_edges(boxes, h)
        # 先用最像表头的一条带估计列
        bands = _assign_to_bands(boxes, rows_edges)
        probe = max(bands, key=lambda b: _best_header_index(b, bounds)) if bands else []
        probe_span = (min((b.x0 for b in probe), default=0.0), max((b.x1 for b in probe), default=float(w)))
        cols = _cluster_columns(probe, probe_span[1], probe_span[1] + 1, w)

    if not cols:
        return RenderedTable([], [], [], 0, {}, method, w, h, bounds, warnings + ["没能划分出任何列"])

    bands = _assign_to_bands(boxes, rows_edges)
    while bands and not any(_cell_in_column(band, cols[0]) for band in [bands[0]]):
        bands.pop(0)
        warnings.append("表格上方有非表格文字，已跳过一行")

    cell_limits = _column_limits(cols)
    rows: List[RenderedRow] = []
    for idx, band in enumerate(bands):
        band = _split_spanning_boxes(band, cols)
        spans = [
            _cell_in_column(band, span, cell_limits[i]) for i, span in enumerate(cols)
        ]
        if not any(spans):
            continue
        rows.append(RenderedRow(
            y0=rows_edges[idx] if idx < len(rows_edges) else 0.0,
            y1=rows_edges[idx + 1] if idx + 1 < len(rows_edges) else float(h),
            cells=[RenderedCell(_merge_texts(items), items[0] if items else None) for items in spans],
        ))
    if not rows:
        return RenderedTable([], [], [], 0, {}, method, w, h, bounds, warnings + ["没有解析出表格行"])

    header_row = _pick_header_row(rows, bounds)
    header_texts = [r.text_at(c) for r in [rows[header_row]] for c in range(len(cols))]
    header_row, header_texts = _absorb_multiline_header(rows, header_row, cols, header_texts)
    header_map = _map_columns(header_texts)

    detected = sum(1 for v in header_map.values() if v)
    if detected == 0:
        warnings.append("表头文字与固定表头清单对不上，请手工指定各列含义")
    elif detected < len(cols) * 0.5:
        warnings.append("只有部分列认出来了，请核对列对应关系")

    data_rows = [r for i, r in enumerate(rows) if i > header_row]
    data_rows = _drop_empty_and_tail(data_rows, header_map)

    table = RenderedTable(
        rows=data_rows,
        columns=cols,
        column_texts=header_texts,
        header_row=header_row,
        header_map=header_map,
        method=method,
        image_width=w,
        image_height=h,
        grid_bbox=bounds,
        warnings=warnings,
    )
    return table


def _cluster_row_edges(boxes: Sequence[TextBox], height: int) -> List[float]:
    """无框线时按文字块的纵向间距切行。"""
    if not boxes:
        return [0.0, float(height)]
    heights = sorted(b.h for b in boxes)
    median_h = heights[len(heights) // 2] if heights else 20.0
    tol = max(6.0, median_h * 0.6)
    tops = sorted(b.cy for b in boxes)
    groups: List[List[float]] = []
    for v in tops:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    centres = [sum(g) / len(g) for g in groups]
    edges = [0.0]
    for a, b in zip(centres, centres[1:]):
        edges.append((a + b) / 2)
    edges.append(float(height))
    return edges


def _pick_header_row(rows: Sequence[RenderedRow], bounds: Tuple[float, float, float, float]) -> int:
    """表头行 = 最像「一整行都是列名」的那一行（标题行一般会被比下去）。"""
    best_idx, best_score = 0, -1.0
    for idx, row in enumerate(rows):
        if not row.joined:
            continue
        score = 0.0
        for cell in row.cells:
            if cell.text and _header_score(cell.text) >= 0.62:
                score += 1.0
        if score == 0:
            continue
        # 同一行命中多个列名，且行内有数字吗（数据行一般有）
        digit_ratio = sum(1 for c in row.cells if re.search(r"\d", c.text)) / max(1, len(row.cells))
        score -= digit_ratio * 0.5
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx


def _absorb_multiline_header(
    rows: Sequence[RenderedRow], header_row: int, cols: Sequence[Tuple[float, float]], header_texts: List[str]
) -> Tuple[int, List[str]]:
    """表头折行（如「本机构投标量」+「（万元）」）时，把下一行并进来。"""
    if header_row + 1 >= len(rows):
        return header_row, header_texts
    nxt = rows[header_row + 1]
    cur_texts = list(header_texts)
    merged_texts = [
        (cur_texts[i] + nxt.text_at(i)) if i < len(cur_texts) else nxt.text_at(i)
        for i in range(len(cols))
    ]
    cur_hits = sum(1 for t in cur_texts if _match_header(t)[0])
    merged_hits = sum(1 for t in merged_texts if _match_header(t)[0])
    # 下一行几乎没有数字、且合并后更像表头，就合并
    next_digits = sum(1 for c in nxt.cells if re.search(r"\d", c.text))
    if merged_hits > cur_hits and next_digits <= 1:
        return header_row + 1, merged_texts
    return header_row, header_texts


def _map_columns(header_texts: Sequence[str]) -> Dict[int, str]:
    """把每一列认到固定表头清单上（贪心、一对一）。"""
    scored: List[Tuple[float, int, str]] = []
    for col, text in enumerate(header_texts):
        name, score = _match_header(text)
        if name:
            scored.append((score, col, name))
    scored.sort(reverse=True)
    used_cols: set = set()
    used_names: set = set()
    mapping: Dict[int, str] = {}
    for score, col, name in scored:
        if col in used_cols or name in used_names:
            continue
        used_cols.add(col)
        used_names.add(name)
        mapping[col] = name
    for col in range(len(header_texts)):
        mapping.setdefault(col, "")
    return mapping


def _drop_empty_and_tail(rows: Sequence[RenderedRow], header_map: Dict[int, str]) -> List[RenderedRow]:
    """去掉空行与表格下方的合计/说明行。"""
    out: List[RenderedRow] = []
    name_cols = [c for c, n in header_map.items() if n in ("债券简称", "债券代码", "债券全称")]
    for row in rows:
        texts = [c.text for c in row.cells if c.text]
        if not texts:
            continue
        joined = "".join(texts)
        if len(joined) < 3:
            continue
        if re.search(r"(合计|小计|总计|备注|说明|共\s*\d+\s*只)", joined):
            continue
        # 债券简称列必须有中文，否则视为无效行
        if name_cols:
            has_name = any(NAME_RE.search(row.text_at(c) or "") for c in name_cols)
            if not has_name:
                continue
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# 行 → 结构化数据
# --------------------------------------------------------------------------- #

def _column_of(header_map: Dict[int, str], field: str, fallback: int) -> int:
    for col, name in header_map.items():
        if name == field:
            return col
    return fallback


def extract_rows(table: RenderedTable, *, guess_columns: bool = True) -> List[TableRow]:
    """把重建好的表格行转成结构化数据。"""
    header_map = table.header_map
    col_code = _column_of(header_map, "债券代码", 0)
    col_name = _column_of(header_map, "债券简称", 1)
    col_margin = _column_of(header_map, "边际利率/价格", -1)
    col_full = _column_of(header_map, "全场倍数", -1)
    col_edge = _column_of(header_map, "边际倍数", -1)

    header_names = [table.header_map.get(c, "") for c in range(len(table.columns))]
    result: List[TableRow] = []
    for row in table.rows:
        code_col, name_col = col_code, col_name
        if guess_columns:
            code_col, name_col = _guess_identity_columns(row, code_col, name_col)
        code = row.text_at(code_col)
        name = row.text_at(name_col)
        if not name and not code:
            continue
        raw_name = name
        clean_name = _clean_bond_name(name)

        margin_col = col_margin
        full_col = col_full
        edge_col = col_edge
        if guess_columns:
            margin_col, full_col, edge_col = _guess_numeric_columns(row, [margin_col, full_col, edge_col])

        margin_text = row.text_at(margin_col) if margin_col >= 0 else ""
        full_text = row.text_at(full_col) if full_col >= 0 else ""
        edge_text = row.text_at(edge_col) if edge_col >= 0 else ""

        missing: List[str] = []
        margin_rate = first_number(margin_text)
        full_ratio = first_number(full_text)
        edge_ratio = first_number(edge_text)
        if margin_rate is None:
            missing.append("边际利率/价格")
        if full_ratio is None:
            missing.append("全场倍数")
        if edge_ratio is None:
            missing.append("边际倍数")

        cols: List[str] = []
        for idx in range(len(table.columns)):
            text = row.text_at(idx)
            cols.append(text if text else "")

        result.append(TableRow(
            code=normalise_text(code),
            name=clean_name or normalise_text(name),
            raw_name=raw_name,
            margin_rate=margin_rate,
            full_ratio=full_ratio,
            edge_ratio=edge_ratio,
            index=len(result) + 1,
            row_y=row.y0,
            missing=missing,
            extra={
                "cells": cols,
                "__cols": cols,
                "headers": header_names,
                "col_code": str(code_col),
                "col_name": str(name_col),
                "col_margin": str(margin_col),
                "col_full": str(full_col),
                "col_edge": str(edge_col),
            },
        ))
    return result


def _guess_identity_columns(row: RenderedRow, code_col: int, name_col: int) -> Tuple[int, int]:
    """列没认出来时，猜哪一列是代码、哪一列是简称。"""
    if row.text_at(name_col) and NAME_RE.search(row.text_at(name_col)):
        return code_col, name_col
    best_name = name_col
    best_score = -1.0
    for idx, cell in enumerate(row.cells):
        t = cell.text
        if not t:
            continue
        score = 0.0
        if NAME_RE.search(t):
            score += 2.0
        if CODE_RE.search(t):
            score += 1.0
        if MONEYISH_RE.match(t):
            score -= 2.0
        if score > best_score:
            best_score, best_name = score, idx
    best_code = code_col
    for idx, cell in enumerate(row.cells):
        t = normalise_text(cell.text)
        if re.fullmatch(r"[A-Z]{0,6}\d{3,}[A-Z0-9]*", t) and idx != best_name:
            best_code = idx
            break
    return best_code, best_name


def _guess_numeric_columns(row: RenderedRow, candidates: Sequence[int]) -> Tuple[int, int, int]:
    """三列都没认出来时，用「行内数值区从右往左」的常识兜底。

    投标量表格里，债券简称右边剩下的纯数值列依次是：
    本机构投标量 / 中标量 / 总投单量 / 边际利率 / 边际投单量 / 全场倍数 / 边际倍数 …
    所以取右侧最后三个「像小数」的列。这只在完全没有表头时才用。
    """
    margin, full, edge = candidates
    if margin >= 0 and full >= 0 and edge >= 0:
        return margin, full, edge

    numeric_cols: List[int] = []
    for idx, cell in enumerate(row.cells):
        t = cell.text
        if not t:
            continue
        if re.search(r"\d", t) and not NAME_RE.search(t):
            numeric_cols.append(idx)
    # 带 % 的优先当边际利率
    if margin < 0:
        for idx in numeric_cols:
            if "%" in row.text_at(idx):
                margin = idx
                break
    remaining = [c for c in numeric_cols if c != margin]
    if edge < 0 and remaining:
        edge = remaining[-1]
        remaining = remaining[:-1]
    if full < 0 and remaining:
        full = remaining[-1]
    return margin, full, edge


def _clean_bond_name(text: str) -> str:
    """去掉 OCR 带来的代码前缀/括号噪点，留下债券简称。"""
    t = normalise_text(text)
    if not t:
        return ""
    t = re.sub(r"^[\-\u2014:：]+", "", t)
    t = t.replace("(", "").replace(")", "")
    t = re.sub(r"^\d{4,6}(?=[\u4e00-\u9fff])", "", t)
    return t


def parse_image(
    bgr: np.ndarray,
    boxes: Sequence[TextBox],
    *,
    prefer_grid: bool = True,
    guess_columns: bool = True,
) -> Tuple[RenderedTable, List[TableRow]]:
    table = parse_table(bgr, boxes, prefer_grid=prefer_grid)
    rows = extract_rows(table, guess_columns=guess_columns)
    return table, rows
