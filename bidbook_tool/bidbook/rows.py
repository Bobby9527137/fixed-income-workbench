# -*- coding: utf-8 -*-
"""文本行的解析、与表格数据的匹配、以及最终文案的生成。

输入（用户给的原始文本，一行一个债券）：
    【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%

输出（按固定顺序拼接，行间用回车隔开）：
    17:30/17:40/17:50 → 【1.3-2.3】26武清经开MTN007，2Y，1.5亿，AA+；目前边际1.81%，全场倍数1.77倍，边际倍数2.00倍。
    18:00             → 【1.3-2.3】26武清经开MTN007，2Y，1.5亿，AA+；最终边际1.87%，全场倍数1.77倍，边际倍数2.00倍。

每一行都出文案（一行一只）；哪一项截图和窗口 2 都没给，那一项就写「待定」——不丢行、也不猜数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import fuzzy as fuzz

from .ocr import first_number, format_number, normalise_text
from .table import TableRow

# --------------------------------------------------------------------------- #
# 正则
# --------------------------------------------------------------------------- #

RANGE_RE = re.compile(r"[【\[]\s*([\-−~～至]?\s*[\d]+(?:\.\d+)?\s*[\-−~～至]\s*[\d]+(?:\.\d+)?%?)\s*[】\]]")
TIME_PREFIX_RE = re.compile(r"^\s*\d{1,2}\s*[:：]\s*\d{2}\s*")
TIME_ANY_RE = re.compile(r"\b\d{1,2}\s*[:：]\s*\d{2}\b")
TENOR_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(Y|y|年|M|m|月)$")
SCALE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(亿|万亿|万|万元|亿元)?$")
RATING_RE = re.compile(r"^(AAA|AA\+|AA-|AA|A\+|A-|A|BBB\+|BBB|BB|B|CCC|CC|C|D)$", re.IGNORECASE)
SCHEDULE_RE = re.compile(r"(簿记|缴款|交款|上市|起息|发行|截止|建档|定价)")
BOND_CODE_RE = re.compile(r"[A-Z]{2,6}\d{2,6}[A-Z0-9]*|\d{4,6}\.[A-Z]{2}")
GARBAGE_RE = re.compile(r"^[\-\u2014\u2013\s:：;；,，.。/]+$")

# OCR / 手误常见异体字与全角问题
CHAR_FIX = str.maketrans({
    "淲": "武", "斌": "武", "诚": "城", "诚": "城", "缄": "城",
    "圓": "圆", "圆": "圆", "産": "产", "業": "业", "國": "国",
    "開": "开", "發": "发", "債": "债", "券": "券", "証": "证",
})


@dataclass
class InputRow:
    """用户文本里的一行。"""

    raw: str
    index: int
    code: str = ""
    name: str = ""
    display_name: str = ""
    tenor_text: str = ""
    scale_text: str = ""
    rating_text: str = ""
    schedule_text: str = ""
    range_text: str = ""
    time_hint: str = ""
    parsed_ok: bool = True
    notes: List[str] = field(default_factory=list)

    def prefix(self) -> str:
        """【区间】简称，期限，规模，评级  —— 输出里分号前的那一段。"""
        range_part = f"【{self.range_text}】" if self.range_text else ""
        parts = [self.display_name or self.name]
        for value in (self.tenor_text, self.scale_text, self.rating_text):
            if value:
                parts.append(value)
        return range_part + "，".join(parts)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "raw": self.raw,
            "code": self.code,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "tenor_text": self.tenor_text,
            "scale_text": self.scale_text,
            "rating_text": self.rating_text,
            "schedule_text": self.schedule_text,
            "range_text": self.range_text,
            "time_hint": self.time_hint,
            "parsed_ok": self.parsed_ok,
            "notes": list(self.notes),
        }


@dataclass
class RowResult:
    """一行输入 + 匹配到的表格数据 + 最终文案。"""

    input: InputRow
    matched: Optional[TableRow] = None
    score: float = 0.0
    mode: str = "目前边际"
    line: str = ""
    review: bool = False
    review_reason: str = ""
    overrides: Dict[str, str] = field(default_factory=dict)
    # 第二个窗口（边际数据文本）里配到的数：截图里没有的可以靠它出数
    text_values: Dict[str, str] = field(default_factory=dict)
    values_score: float = 0.0
    values_source: str = ""   # 截图 / 文本 / 截图+文本 / 人工改数
    has_data: bool = False    # 三列里至少有一个数是真数（其余可能是「待定」）
    pending: List[str] = field(default_factory=list)  # 哪些项没有数、文案里写的是「待定」
    # 来源与提醒（写进输出行）：窗口 2 配到的标的、截图里最相似但没配上的标的
    values_name: str = ""
    best_name: str = ""
    source_note: str = ""
    warn_text: str = ""

    def as_dict(self) -> dict:
        return {
            "input": self.input.as_dict(),
            "table": self.matched.as_dict() if self.matched else None,
            "match_score": round(self.score, 3),
            "mode": self.mode,
            "line": self.line,
            "review": self.review,
            "review_reason": self.review_reason,
            "text_values": dict(self.text_values),
            "values_score": round(self.values_score, 3),
            "values_source": self.values_source,
            "has_data": self.has_data,
            "pending": [VALUE_NAMES.get(k, k) for k in self.pending],
            "values_name": self.values_name,
            "best_name": self.best_name,
            "source_note": self.source_note,
            "warn_text": self.warn_text,
        }


def normalise_angle_text(text: str) -> str:
    """规范到「可比较」的形态：去空白、去括号、统一全角、修正异体字。"""
    t = normalise_text(text or "")
    t = t.translate(CHAR_FIX)
    t = re.sub(r"[\s\u3000]+", "", t)
    t = t.replace("（", "(").replace("）", ")")
    t = re.sub(r"[·・\.\-_—–]", "", t)
    return t.upper()


def match_key(text: str) -> str:
    """债券简称的匹配键：去掉常见品种后缀再比较。"""
    t = normalise_angle_text(text)
    t = re.sub(r"(MTN|PPN|SCP|CP|GN|PR|DFI|ABN|债|债券)$", "", t)
    return t


# --------------------------------------------------------------------------- #
# 文本解析
# --------------------------------------------------------------------------- #

def parse_input(
    text: str,
    *,
    auto_mode: Optional[str] = None,
    strict: bool = True,
    skipped: Optional[List[str]] = None,
) -> List[InputRow]:
    """把用户粘贴的多行文本拆成 InputRow 列表。

    auto_mode 用于在没有时间提示时给默认值（'17:30' 或 '18:00'）。
    strict=True 时会丢掉明显不是债券的行（纯说明文字），并记进 skipped，
    这样结果里不会混进「这是一行说明」这种假数据。
    """
    rows: List[InputRow] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for piece in _split_records(line):
            row = _parse_one(piece, len(rows) + 1, auto_mode=auto_mode)
            if row is None:
                continue
            if strict and not looks_like_bond_name(row.display_name or row.name):
                if skipped is not None:
                    skipped.append(piece.strip())
                continue
            rows.append(row)
    return rows


def _split_records(line: str) -> List[str]:
    """一行里可能塞了多只债（比如两只都用全角逗号隔开），按【…】出现位置切分。"""
    matches = list(RANGE_RE.finditer(line))
    if len(matches) <= 1:
        return [line]
    cuts = [m.start() for m in matches]
    if cuts[0] != 0:
        cuts = [0] + cuts
    pieces = []
    for a, b in zip(cuts, cuts[1:] + [len(line)]):
        chunk = line[a:b].strip().strip("，,;；")
        if chunk:
            pieces.append(chunk)
    return pieces


# 品种词：出现在债券简称里的常见后缀/关键字
BOND_HINT_RE = re.compile(r"(MTN|PPN|SCP|CP|GN|PR|债|存单|国债|票据|中期|短期|超短|公司债|企业债|金融债)", re.IGNORECASE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def looks_like_bond_name(text: str) -> bool:
    """判断一段文字像不像债券简称。

    债券简称几乎都是「中文 + 数字/字母」（26武清经开MTN007）；
    纯中文的说明文字（这是一行说明）会被挡掉，避免混进结果里。
    """
    t = (text or "").strip()
    if len(t) < 4:
        return False
    if not CJK_RE.search(t):
        return False
    if re.search(r"\d", t) or re.search(r"[A-Za-z]", t) or BOND_HINT_RE.search(t):
        return True
    return False


def _parse_one(line: str, index: int, *, auto_mode: Optional[str] = None) -> Optional[InputRow]:
    original = line.rstrip()
    line = line.strip().strip("，,;；")
    if not line or GARBAGE_RE.match(line):
        return None

    row = InputRow(raw=original, index=index)

    # 时间提示：行首的 17:30 / 18:00
    m = TIME_PREFIX_RE.match(line)
    if m:
        row.time_hint = m.group(0).strip()
        line = TIME_PREFIX_RE.sub("", line, count=1).lstrip("，,;；:：-— ")
    if not row.time_hint:
        found = TIME_ANY_RE.search(line)
        if found:
            row.time_hint = found.group(0)
    if not row.time_hint and auto_mode:
        row.time_hint = auto_mode

    # 区间
    m = RANGE_RE.search(line)
    if m:
        row.range_text = m.group(1).replace("−", "-").replace("～", "-").replace("~", "-").replace("至", "-")
        row.range_text = re.sub(r"\s*-\s*", "-", row.range_text)
        line = line[: m.start()] + " " + line[m.end():]

    segments = [s.strip() for s in re.split(r"[，,；;]", line) if s.strip()]
    leftover: List[str] = []
    for seg in segments:
        seg = seg.strip(" 。.")
        if not seg:
            continue
        seg = TIME_PREFIX_RE.sub("", seg).strip()
        if not seg:
            continue
        if RATING_RE.match(seg) and not row.rating_text:
            row.rating_text = seg.upper()
            continue
        if SCHEDULE_RE.search(seg):
            row.schedule_text = (row.schedule_text + "；" + seg) if row.schedule_text else seg
            continue
        m_tenor = TENOR_RE.match(seg)
        if m_tenor and not row.tenor_text:
            unit = m_tenor.group(2).upper()
            row.tenor_text = f"{m_tenor.group(1)}{'Y' if unit in ('Y', '年') else 'M'}"
            continue
        m_scale = SCALE_RE.match(seg)
        if m_scale and not row.scale_text and ("亿" in seg or "万" in seg):
            row.scale_text = normalize_scale(seg)
            continue
        # 债券代码：26武清经开MTN007 这种（年份+简称+品种+编号）
        m_code = re.search(r"(?<![A-Z0-9])(\d{2})([A-Za-z0-9]*[\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff]*)$", seg)
        leftover.append(seg)

    # 从 leftover 里挑债券简称：优先含中文且含字母/数字的
    if leftover:
        best = max(leftover, key=lambda s: (bool(re.search(r"[\u4e00-\u9fff]", s)), len(s)))
        row.display_name = best.strip()
        code_match = re.search(r"(\d{2}[A-Za-z0-9]*[\u4e00-\u9fff]+[A-Za-z]*\d*)", best)
        if code_match:
            row.code = normalise_angle_text(code_match.group(1))
        else:
            m_bond = re.search(r"[A-Za-z0-9]*[\u4e00-\u9fff]+[A-Za-z0-9]*", best)
            row.code = normalise_angle_text(m_bond.group(0)) if m_bond else normalise_angle_text(best)
        row.name = row.code

    if not row.name:
        row.parsed_ok = False
        row.notes.append("没能从这一行里认出债券简称，请检查格式")

    return row


def normalize_scale(text: str) -> str:
    """1.5亿 / 1.5 亿元 / 15000万 → 统一成带单位的最短写法。"""
    t = normalise_text(text)
    m = re.match(r"^(\d+(?:\.\d+)?)(亿|万亿|万|万元|亿元)?", t)
    if not m:
        return text.strip()
    value, unit = m.group(1), m.group(2) or ""
    if unit in ("万元", "亿"):
        unit = {"万元": "万", "亿": "亿"}.get(unit, unit)
    if unit in ("亿元",):
        unit = "亿"
    return f"{value}{unit}"


# --------------------------------------------------------------------------- #
# 第二个窗口：边际数据文本（截图里没有的，靠这里的文本也能出数）
# --------------------------------------------------------------------------- #
# 一行一只债：先写债券简称，再写数。带标签最准：
#     26武清经开MTN007 边际1.81% 全场1.77倍 边际倍数2.00倍
# 不带标签就按顺序认：第 1 个 = 边际利率/价格，第 2 个 = 全场倍数，第 3 个 = 边际倍数
#     26武清经开MTN007 1.81 1.77 2.00
VALUE_KEYS: Tuple[str, ...] = ("margin_rate", "full_ratio", "edge_ratio")
VALUE_NAMES: Dict[str, str] = {
    "margin_rate": "边际利率/价格",
    "full_ratio": "全场倍数",
    "edge_ratio": "边际倍数",
}
VALUE_LABELS: Dict[str, Tuple[str, ...]] = {
    "margin_rate": ("边际利率", "边际价格", "票面利率", "边际", "票面", "利率"),
    "full_ratio": ("全场倍数", "全场倍", "全场"),
    "edge_ratio": ("边际倍数", "边际倍", "边倍数", "边倍"),
}
# 标签从长到短排：先认「边际倍数」，才不会把它认成「边际」
LABEL_PAIRS: List[Tuple[str, str]] = sorted(
    ((label, key) for key, labels in VALUE_LABELS.items() for label in labels),
    key=lambda pair: len(pair[0]),
    reverse=True,
)
VALUE_SPLIT_RE = re.compile(r"[\s,，;；\t|/]+")
PLAIN_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
# 边际利率经常给的是一个范围（1.81-1.95 / 1.81~1.95 / 1.81至1.95），按上限输出。
# 注意变量名别和上面那个 RANGE_RE（认【】里的利率区间）撞车，撞了会把前缀认丢。
V_NUM = r"\d+(?:\.\d+)?"
V_RANGE_SEP = r"[-~～—–―至到]"
V_RANGE_RE = re.compile(r"^(" + V_NUM + r")\s*(?:%|倍)?\s*" + V_RANGE_SEP + r"\s*(" + V_NUM + r")\s*(?:%|倍)?$")
# 「10-12」这种两位-两位的写法是缴款/上市日期，不是数值范围：只有带 % 或倍、
# 或者上下限落在业务合理区间里（利率 0.1~9.0；倍数 0.1~100）才当范围取上限。
V_DATE_LIKE_RE = re.compile(r"^\d{1,2}\s*" + V_RANGE_SEP + r"\s*\d{1,2}$")
RATE_WINDOW: Tuple[float, float] = (0.1, 9.0)
RATIO_WINDOW: Tuple[float, float] = (0.1, 100.0)
# 窗口 2 只收「债券简称 + 边际利率/倍数」，粘整段簿记文本一律不解析（里面的日期会被误当数）
VALUE_BLACKLIST: Tuple[str, ...] = (
    "簿记", "缴款", "交款", "上市", "起息", "发行", "截止", "建档", "定价",
)
VALUE_REJECT_MESSAGE = "该窗口仅接受「债券简称+边际利率/倍数」，请勿粘贴完整簿记文本，请清理内容后重试"
# 匹配分数低于这个值就在输出行前面挂 ⚠，提醒核对是不是配错了
WARN_SCORE = 0.90
# 全局默认匹配门槛（match_rows 默认参数 / 接口默认值 / 网页滑块三处同步）
DEFAULT_THRESHOLD = 0.90


def _in_window(low: float, high: float, window: Tuple[float, float]) -> bool:
    return window[0] <= low <= window[1] and window[0] <= high <= window[1]


def _number_from_token(token: str, kind: Optional[str] = None) -> Optional[str]:
    """从一段文本里认出「一个数」：写成范围就取上限，认不出返回 None。

    kind = 这一项属于哪一列（VALUE_KEYS 里的键；None 表示还不知道要填哪一列，
    比如不带标签、只能按顺序认的情形）。

    范围取上限只在满足下面任一条时才做，免得把「10-12」这种日期解析成数：
      ① 片段里带 % 或 倍；
      ② 上下限落在业务合理区间（利率 0.1~9.0 / 倍数 0.1~100）——两位-两位又没带
         单位的（10-12 / 10-13 / 10-14）一律不当范围，跳过。
    """
    text = str(token or "").strip().strip(" .,，。;；:：、()（）[]【】")
    if not text:
        return None
    m = V_RANGE_RE.match(text)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        upper, lower = m.group(2), m.group(1)
        has_unit = ("%" in text) or ("倍" in text)
        rate_ok = _in_window(low, high, RATE_WINDOW)
        ratio_ok = _in_window(low, high, RATIO_WINDOW)
        if has_unit:
            ok = True
        elif kind == "margin_rate":
            ok = rate_ok
        elif kind in ("full_ratio", "edge_ratio"):
            ok = ratio_ok
        elif rate_ok:
            ok = True
        else:
            ok = ratio_ok and not V_DATE_LIKE_RE.match(text)
        if not ok:
            return None
        return upper if high >= low else lower
    if PLAIN_NUMBER_RE.match(text.rstrip("%倍")):
        return text.rstrip("%倍")
    return None


@dataclass
class ValueRow:
    """第二个窗口里的一行：一只债 + 它提供的数。"""

    raw: str
    index: int
    name: str = ""
    margin_rate: str = ""
    full_ratio: str = ""
    edge_ratio: str = ""
    notes: List[str] = field(default_factory=list)

    def values(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key in VALUE_KEYS:
            value = getattr(self, key, "")
            if value not in (None, ""):
                out[key] = str(value)
        return out

    def as_dict(self) -> dict:
        data = {"index": self.index, "raw": self.raw, "name": self.name, "notes": list(self.notes)}
        data.update(self.values())
        return data


def check_values_text(text: str) -> str:
    """窗口 2 的文本是不是整段簿记文本：返回命中的关键词，没有命中返回空串。"""
    blob = str(text or "")
    for word in VALUE_BLACKLIST:
        if word in blob:
            return word
    return ""


def parse_values(text: str, problems: Optional[List[str]] = None) -> List[ValueRow]:
    """把第二个窗口的文本拆成 ValueRow 列表；认不出来的行记进 problems。

    整段簿记文本（含缴款/上市这类黑名单词）一律不解析、直接返回空列表：
    那种文本里的日期会被误当成边际数据。
    """
    hit = check_values_text(text)
    if hit:
        if problems is not None:
            problems.append("窗口2输入错误（出现「%s」）：%s" % (hit, VALUE_REJECT_MESSAGE))
        return []
    rows: List[ValueRow] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        row = _parse_value_line(line, len(rows) + 1)
        if row is None or not row.values():
            if problems is not None:
                problems.append(line)
            continue
        rows.append(row)
    return rows


def _parse_value_line(line: str, index: int) -> Optional[ValueRow]:
    row = ValueRow(raw=line, index=index)
    work = line
    # 1) 带标签的数：「标签 + 数字（可带 % / 倍）」整段抠掉
    for label, key in LABEL_PAIRS:
        if getattr(row, key):
            continue
        pattern = re.compile(
            re.escape(label)
            + r"\s*[:：=]?\s*("
            + V_NUM
            + r"(?:\s*(?:%|倍)?\s*"
            + V_RANGE_SEP
            + r"\s*"
            + V_NUM
            + r")?)\s*(?:%|倍)?"
        )
        m = pattern.search(work)
        if not m:
            continue
        value = _number_from_token(m.group(1), kind=key)
        if value is None:
            continue
        setattr(row, key, value)
        work = work[: m.start()] + " " + work[m.end():]
    # 2) 剩下的片段：认简称，认没带标签的数
    numbers: List[str] = []      # 裸着的数：第 1/2/3 个按顺序就是那三项
    bracketed: List[str] = []    # 带【】/（）的：多半是利率区间，只有没有别的数时才用
    for raw_token in VALUE_SPLIT_RE.split(work):
        token = raw_token.strip()
        if not token:
            continue
        value = _number_from_token(token)
        if value is not None:
            if token == token.strip(" .,，。;；:：、()（）[]【】"):
                numbers.append(value)
            else:
                bracketed.append(value)
        elif not row.name and looks_like_bond_name(token):
            row.name = token
        else:
            row.notes.append(f"没看懂的片段「{token}」")
    if not row.name:
        return None
    if not numbers:
        numbers = bracketed
    if numbers:
        for key, value in zip(VALUE_KEYS, numbers):
            if not getattr(row, key):
                setattr(row, key, value)
        extra = numbers[len(VALUE_KEYS):]
        if extra:
            row.notes.append("多出来的数没用上：" + "、".join(extra))
    return row


# 简称里的关键要素：发行年份 / 品种 / 期数。两边都认出来且不一样 → 直接判 0 分。
BOND_YEAR_RE = re.compile(r"^(\d{4}|\d{2})(?!\d)")
BOND_VARIETY_RE = re.compile(r"(SCP|MTN|PPN|CP|GN|ABN|PR)", re.IGNORECASE)
BOND_ISSUE_RE = re.compile(r"(\d{1,4})(?!\d)\D*$")


def _bond_keys(text: str) -> Dict[str, str]:
    """从简称里抠出能用来强过滤的要素：年份、品种、期数；抠不出来就不放那个键。

    任意一侧没解析出来（比如 OCR 把品种/期数认花了）就不拿它过滤，
    只有两边都认出来、且对不上，才判定是两只不同的债。
    """
    raw = normalise_angle_text(str(text or "")).upper()
    keys: Dict[str, str] = {}
    m = BOND_YEAR_RE.match(raw)
    if m:
        keys["year"] = m.group(1)[-2:]
    m = BOND_VARIETY_RE.search(raw)
    if m:
        keys["variety"] = m.group(1).upper()
    m = BOND_ISSUE_RE.search(raw)
    # 从 0 位置开始的数字串是开头的年份（26武清经开），不是期数，别拿它去过滤
    if m and m.start(1) > 0:
        keys["issue"] = str(int(m.group(1)))
    return keys


def _name_score(left: str, right: str) -> float:
    """两个债券简称有多像（0~1）。"""
    a, b = match_key(left), match_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # 关键要素强过滤：年份 / 品种 / 期数 两边都认出来且不相等，就是两只不同的债，不给分
    keys_a, keys_b = _bond_keys(left), _bond_keys(right)
    for field in ("year", "variety", "issue"):
        if field in keys_a and field in keys_b and keys_a[field] != keys_b[field]:
            return 0.0
    base = fuzz.ratio(a, b) / 100.0
    # 只做加分，不再把分数直接顶到 0.93 / 0.88（那会让不同期数、不同年份、不同主体的债误匹配）
    if a in b or b in a:
        base = min(1.0, base + 0.03)
    if any(len(a) >= n and a[:n] in b for n in (3, 4)):
        base = min(1.0, base + 0.05)
    return base


def _attach_values(
    results: Sequence[RowResult], value_rows: Sequence[ValueRow], threshold: float
) -> None:
    """给每行输入配一条第二个窗口的数据（同样是一对一、先到先得）。"""
    if not value_rows:
        return
    used: set = set()
    for r in results:
        best_idx, best_score = -1, 0.0
        for i, value_row in enumerate(value_rows):
            if i in used:
                continue
            score = _name_score(r.input.name or r.input.display_name, value_row.name)
            if score > best_score + 1e-9:
                best_idx, best_score = i, score
        if best_idx >= 0 and best_score >= threshold:
            used.add(best_idx)
            r.text_values = value_rows[best_idx].values()
            r.values_score = best_score
            r.values_name = value_rows[best_idx].name or ""


# --------------------------------------------------------------------------- #
# 匹配
# --------------------------------------------------------------------------- #

def match_rows(
    inputs: Sequence[InputRow],
    table_rows: Sequence[TableRow],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    value_rows: Optional[Sequence[ValueRow]] = None,
) -> List[RowResult]:
    """把每行输入配到表格里的某一行，一对一分配（先到先得）。

    value_rows 是第二个窗口（边际数据）解析出来的行：截图里没有的，
    可以靠它出数（同样按简称一对一配）。
    """
    used: set = set()
    results: List[RowResult] = []
    for row in inputs:
        best_idx, best_score = -1, 0.0
        for t_idx, t_row in enumerate(table_rows):
            score = _pair_score(row, t_row)
            if score > best_score + 1e-9:
                best_idx, best_score = t_idx, score
        # 首选没被占用；被占用了就找备选
        if best_idx >= 0 and best_idx in used:
            alt_idx, alt_score = -1, 0.0
            for t_idx, t_row in enumerate(table_rows):
                if t_idx in used:
                    continue
                score = _pair_score(row, t_row) * 0.99
                if score > alt_score:
                    alt_idx, alt_score = t_idx, score
            if alt_idx >= 0 and alt_score >= threshold:
                best_idx, best_score = alt_idx, alt_score
        matched = table_rows[best_idx] if best_idx >= 0 and best_score >= threshold else None
        if matched is not None:
            used.add(best_idx)
        results.append(RowResult(
            input=row,
            matched=matched,
            score=best_score,
            best_name=((table_rows[best_idx].name or table_rows[best_idx].raw_name or "")
                       if best_idx >= 0 else ""),
            review_reason="" if matched else "没有在表格里找到对应的债券简称",
            review=matched is None,
        ))
    _attach_values(results, list(value_rows or []), threshold)
    _flag_outliers(results)
    return results


def _pair_score(row: InputRow, t_row: TableRow) -> float:
    base = _name_score(row.name, t_row.name)
    if base <= 0:
        return 0.0
    # 期限/规模一致时加权
    if row.tenor_text:
        t_tenor = re.search(r"(\d+(?:\.\d+)?)", t_row.raw_name or "") or re.search(r"(\d+(?:\.\d+)?)", t_row.name or "")
        if t_tenor and abs(float(t_tenor.group(1)) - float(re.sub(r"[^\d\.]", "", row.tenor_text) or 0)) < 0.01:
            base = min(1.0, base + 0.03)
    return base


def _flag_outliers(results: Sequence[RowResult]) -> None:
    """同一批里边际利率离群且有 OCR 疑点的行，标出来让人工看一眼。"""
    values = [r.matched.margin_rate for r in results if r.matched and r.matched.margin_rate is not None]
    if len(values) < 3:
        return
    ordered = sorted(values)
    median = ordered[len(ordered) // 2]
    if median <= 0:
        return
    for r in results:
        if not r.matched or r.matched.margin_rate is None:
            continue
        if abs(r.matched.margin_rate - median) / median > 0.35:
            r.review = True
            r.review_reason = f"边际利率 {r.matched.margin_rate:g}% 与同批中位数 {median:g}% 偏离较大，建议核对截图"


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #

TIME_SLOTS = ["17:30", "17:40", "17:50", "18:00"]
FINAL_SLOT = "18:00"

# 网页上的时点选择：auto = 按电脑时间，current = 目前边际，final = 最终边际；
# 也兼容直接传具体时点（"17:40"）。文本行自己带的 17:30/18:00 优先级更高。
DEFAULT_TIME_CHOICE = "auto"
TIME_CHOICES: List[Dict[str, str]] = [
    {"key": "auto", "label": "自动（按电脑时间）"},
    {"key": "current", "label": "目前边际"},
    {"key": "final", "label": "最终边际"},
]
# 只有这四个时点，没有别的。


def _slot_minutes(slot: str) -> int:
    hour, minute = slot.split(":")
    return int(hour) * 60 + int(minute)


def clock_slot(now: Optional[datetime] = None) -> str:
    """按电脑时间在 17:30 / 17:40 / 17:50 / 18:00 这四个时点里取一个。

    规则：取不晚于电脑时间的最近一个时点；还没到 17:30（包括凌晨、早上）算第一轮 17:30，
    过了 18:00 就一直是 18:00（最终边际）。四个时点之外不会凭空造出别的时间。
    """
    t = now or datetime.now()
    minutes = t.hour * 60 + t.minute
    for slot in reversed(TIME_SLOTS):
        if minutes >= _slot_minutes(slot):
            return slot
    return TIME_SLOTS[0]


def clock_mode(now: Optional[datetime] = None) -> Tuple[str, str]:
    """按电脑时间判断 (模式名, 时点)，例如 ("目前边际", "17:40") / ("最终边际", "18:00")。"""
    slot = clock_slot(now)
    return ("最终边际" if slot == FINAL_SLOT else "目前边际"), slot


def now_info(now: Optional[datetime] = None) -> Dict[str, str]:
    """给网页看的「电脑时间 → 该用哪个边际」。"""
    t = now or datetime.now()
    mode, slot = clock_mode(t)
    return {"time": t.strftime("%H:%M"), "slot": slot, "mode": mode}


def resolve_default_time(
    default_time: str = DEFAULT_TIME_CHOICE,
    now: Optional[datetime] = None,
) -> str:
    """把网页传来的选择（auto/current/final）落成一个具体时点字符串。"""
    value = (default_time or DEFAULT_TIME_CHOICE).strip()
    key = value.lower()
    if key in ("auto", "clock", "now", "自动"):
        return clock_slot(now)
    if key in ("current", "目前边际", "目前"):
        slot = clock_slot(now)
        return "17:50" if slot == FINAL_SLOT else slot
    if key in ("final", "最终边际", "最终"):
        return FINAL_SLOT
    return value


def resolve_mode(time_hint: str, default_time: str = "17:30") -> Tuple[str, str, List[str]]:
    """返回 (模式名, 生效的时间, 提醒列表)。18:00 才是最终边际。"""
    notes: List[str] = []
    t = (time_hint or default_time or "17:30").strip().replace("：", ":")
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        notes.append(f"时间「{time_hint}」看不懂，已按 {default_time} 处理")
        t = default_time
    else:
        t = f"{int(m.group(1)):02d}:{m.group(2)}"
    if t == FINAL_SLOT:
        return ("最终边际", t, notes)
    if t in TIME_SLOTS:
        return ("目前边际", t, notes)
    notes.append(f"{t} 不在 17:30/17:40/17:50/18:00 四个时点里，已按「目前边际」处理")
    return ("目前边际", t, notes)


def build_line(
    row: InputRow,
    matched: Optional[TableRow],
    mode: str,
    *,
    overrides: Optional[Dict[str, str]] = None,
    show_time: bool = False,
    warn_text: str = "",
    source_note: str = "",
) -> str:
    """拼出最终文案。overrides 可覆盖 边际/全场/边际倍数 的显示值。

    warn_text 是行首的 ⚠ 提醒（疑似匹配不准）；source_note 是行末的来源说明
    （来源 / 匹配度 / 实际匹配到的标的名称）。
    """
    overrides = overrides or {}
    rate = overrides.get("margin_rate")
    full = overrides.get("full_ratio")
    edge = overrides.get("edge_ratio")

    if rate is None and matched is not None and matched.margin_rate is not None:
        rate = f"{matched.margin_rate:.2f}"
    if full is None and matched is not None and matched.full_ratio is not None:
        full = f"{matched.full_ratio:.2f}"
    if edge is None and matched is not None and matched.edge_ratio is not None:
        edge = f"{matched.edge_ratio:.2f}"

    label = "最终边际" if mode == "最终边际" else "目前边际"
    # 三列都写全：没有数的那列写「待定」，绝不伪造数据，也不静默少写一项
    tail_parts = [
        f"{label}{_clean_num(rate)}%" if rate not in (None, "") else f"{label}待定",
        f"全场倍数{_clean_num(full)}倍" if full not in (None, "") else "全场倍数待定",
        f"边际倍数{_clean_num(edge)}倍" if edge not in (None, "") else "边际倍数待定",
    ]

    head = row.prefix()
    time_part = f"{row.time_hint} " if (show_time and row.time_hint) else ""
    return f"{warn_text}{time_part}{head}；" + "，".join(tail_parts) + "。" + (source_note or "")


def _clean_num(value: str) -> str:
    t = str(value).strip().replace("%", "").replace("倍", "")
    try:
        return f"{float(t):.2f}"
    except ValueError:
        return t


def format_results(
    rows: Sequence[RowResult],
    *,
    default_time: str = "17:30",
    show_time: bool = False,
    separator: str = "\n",
    overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> Tuple[str, List[RowResult]]:
    """给每一行算出生效模式与文案，返回 (拼接好的文本, 更新后的结果)。

    每一行都出文案（一行一只，不静默丢行）：数从截图里对应那行来，或者从第二个窗口
    （边际数据）配到的那行来；哪一项两处都没有，那一项就写「待定」，绝不猜数。
    """
    overrides = overrides or {}
    lines: List[str] = []
    for r in rows:
        mode, slot, notes = resolve_mode(r.input.time_hint, default_time)
        r.input.time_hint = slot
        r.mode = mode
        r.input.notes = [n for n in r.input.notes if not n.startswith("时间「")]
        for note in notes:
            if note not in r.input.notes:
                r.input.notes.append(note)
        # 人工改数是在「表格行」上改的，所以先用被匹配到的表格行号去找；
        # 找不到再退回粘贴文本的行号（命令行直接传 overrides 时用得上）。
        r.overrides = {}
        for key in (str(r.matched.index) if r.matched is not None else None, str(r.input.index)):
            if key is not None and key in overrides:
                r.overrides = overrides[key]
                break
        picked, from_text, conflicts = _pick_values(r, r.overrides)
        r.has_data = any(picked.get(key) not in (None, "") for key in VALUE_KEYS)
        r.pending = [key for key in VALUE_KEYS if picked.get(key) in (None, "")]
        _mark_source(r, from_text, conflicts)
        # 来源说明 + 匹配分数偏低的 ⚠ 提醒：一眼能看出这行的数是从哪来的、像不像配错
        r.source_note = _source_note(r)
        r.warn_text = _warn_text(r)
        # 没有数也照样出一行，缺的那项写「待定」：一行一只，不静默丢行、也不伪造数据
        r.line = build_line(r.input, r.matched, mode, overrides=picked, show_time=show_time,
                            warn_text=r.warn_text, source_note=r.source_note)
        lines.append(r.line)
        if r.pending:
            reason = _pending_reason(r)
            if r.matched is not None and r.review and r.review_reason:
                # 别把「边际利率偏离较大」这类提醒盖掉，两条都留着
                reason = r.review_reason + "；" + reason
            r.review = True
            r.review_reason = reason
        elif not r.review and r.matched is not None and r.matched.missing:
            r.review = True
            r.review_reason = "截图里这几列没识别到：" + "、".join(r.matched.missing)
    return separator.join(lines), list(rows)


def _to_float(value: str) -> float:
    try:
        return float(str(value).replace("%", "").replace("倍", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _pick_values(
    r: RowResult, overrides: Dict[str, str]
) -> Tuple[Dict[str, str], List[str], List[str]]:
    """定下这一行最终用的三个数：人工改的 > 截图 > 第二个窗口。

    返回 (三个数, 哪些项是第二个窗口补的, 第二个窗口和截图不一致的项)。
    """
    picked: Dict[str, str] = {}
    from_text: List[str] = []
    conflicts: List[str] = []
    for key in VALUE_KEYS:
        override = overrides.get(key)
        if override not in (None, ""):
            picked[key] = str(override)
            continue
        image = getattr(r.matched, key, None) if r.matched is not None else None
        text = r.text_values.get(key)
        if image is not None:
            picked[key] = f"{image:.2f}"
            if text not in (None, "") and abs(_to_float(text) - float(image)) >= 0.005:
                conflicts.append(key)
        elif text not in (None, ""):
            picked[key] = str(text)
            from_text.append(key)
    return picked, from_text, conflicts


def _mark_source(r: RowResult, from_text: Sequence[str], conflicts: Sequence[str]) -> None:
    """记下这一行的数是从哪来的，并把跟截图打架的地方提醒出来。"""
    if r.overrides:
        r.values_source = "人工改数"
    elif r.matched is not None and from_text:
        r.values_source = "截图+文本"
    elif r.matched is not None:
        r.values_source = "截图"
    elif from_text:
        r.values_source = "文本"
    else:
        r.values_source = ""
    for key in conflicts:
        note = f"边际数据窗口里的「{VALUE_NAMES[key]}」和截图不一样，以截图为准"
        if note not in r.input.notes:
            r.input.notes.append(note)


def _source_note(r: RowResult) -> str:
    """这一行的数是从哪来的：来源 + 匹配度 + 实际配到的标的名称。"""
    bits: List[str] = []
    if r.overrides:
        bits.append("人工改数")
    if r.matched is not None:
        bits.append(f"截图匹配，匹配度{r.score:.2f}，匹配标的：{r.matched.name or r.matched.raw_name}")
    if r.text_values:
        bits.append(f"窗口2文本，匹配度{r.values_score:.2f}，匹配标的：{r.values_name or r.input.name}")
    if not bits:
        if r.best_name:
            return f"【来源：未匹配，最相似标的：{r.best_name}，匹配分数：{r.score:.2f}】"
        return "【来源：未匹配】"
    return "【来源：" + "；".join(bits) + "】"


def _warn_text(r: RowResult) -> str:
    """匹配分数低于 WARN_SCORE 时，行首挂个 ⚠，把最相似的标的和分数写出来。

    有截图匹配就盯截图那一行；只有窗口 2 的数据就盯窗口 2 配到的行；
    两处都没配上就报截图里最相似的那个标的，方便人工核对。
    """
    if r.matched is not None:
        score, name = r.score, (r.matched.name or r.matched.raw_name)
    elif r.text_values:
        score, name = r.values_score, (r.values_name or r.input.name)
    else:
        score, name = r.score, r.best_name
    if score and name and score < WARN_SCORE:
        return f"⚠️疑似匹配不准，最相似标的：{name}，匹配分数：{score:.2f} "
    return ""


def _pending_reason(r: RowResult) -> str:
    """哪些项没有数、文案里写成了「待定」，写清楚让人一眼能核对。"""
    names = "、".join(VALUE_NAMES.get(key, key) for key in r.pending)
    if r.matched is None:
        return "没有对应的数据（截图里没找到这个简称），写的是待定：" + names
    if r.matched.missing:
        return "截图里这几列没识别到，写的是待定：" + names
    return "这几项没有数，写的是待定：" + names
