# -*- coding: utf-8 -*-
"""交易行文本解析、字段合并与报价行拼装（纯标准库，不依赖 OCR）。

这里只做两件事：
1. 从交易行文本里尽量认出报价要素；
2. 把「交易行」和「DM 截图识别结果」按固定优先级合并，拼成一行报价。

字段优先级（按用户约定）：
- 交易行优先：剩余期限、债券代码、债券简称、OFR 价格、带量；
- 截图优先：公募/私募、主体评级、债项评级、中债估值、票面利率；
- 缺什么补什么，最后仍然缺的写 ``--``，并在 warnings 里说明。
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

FIELD_ORDER: Tuple[str, ...] = (
    "term",
    "code",
    "name",
    "offering",
    "price",
    "volume",
    "rating_main",
    "rating_bond",
    "cbt",
    "coupon",
)

FIELD_LABELS: Dict[str, str] = {
    "term": "剩余期限",
    "code": "债券代码",
    "name": "债券简称",
    "offering": "公募/私募",
    "price": "OFR 价格",
    "volume": "带量",
    "rating_main": "主体评级",
    "rating_bond": "债项评级",
    "cbt": "中债估值",
    "coupon": "票面利率",
}

# 截图优先的字段：DM 上能看到，通常比交易行里的口述更准。
OCR_FIRST = frozenset({"offering", "rating_main", "rating_bond", "cbt", "coupon"})

# --------------------------------------------------------------------------- #
# 文本归一化
# --------------------------------------------------------------------------- #

_FULL2HALF: Dict[int, str] = {
    # 全角 ASCII（！ 到 ～）
    0xFF01 + i: chr(0x21 + i) for i in range(0x5E)
}
_FULL2HALF.update(
    {
        0x3000: " ",  # 全角空格
        0x3001: " ",  # 、
        0x3002: " ",  # 。
        0x2018: "'",
        0x2019: "'",
        0x201C: '"',
        0x201D: '"',
        0x2013: "-",  # –
        0x2014: "-",  # —
        0x2212: "-",  # −
    }
)

_ZERO_WIDTH = ("\u200b", "\ufeff", "\u200e", "\u200f")


def normalize_input(text: str) -> str:
    """统一全角/半角、去零宽字符、合并空白；保留 ``*``、``%``、``/``。"""
    if not text:
        return ""
    s = str(text).translate(_FULL2HALF)
    for ch in _ZERO_WIDTH:
        s = s.replace(ch, "")
    # 千分位逗号先去掉，避免把 3,000 拆成两个数
    s = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", s)
    s = re.sub(r"[\t\r\n]+", " ", s)
    s = re.sub(r"[，,；;、。|]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _tokens(text: str) -> List[str]:
    return [token for token in re.split(r"\s+", text) if token]


def _token_spans(text: str) -> List[Tuple[str, int]]:
    return [(match.group(0), match.start()) for match in re.finditer(r"\S+", text)]


def _normalize_dash(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("—", "-").replace("–", "-").replace("－", "-").replace("−", "-")
    if value in ("--", "-", "——", "无", "/", ""):
        return "--" if value else ""
    return value


# --------------------------------------------------------------------------- #
# 债券代码 / 简称
# --------------------------------------------------------------------------- #

_CODE_RE = re.compile(
    r"(?<![0-9A-Za-z])(\d{6,9}(?:\s*\.\s*(?:IB|SH|SZ|BJ|CF))?)(?![0-9A-Za-z])",
    re.IGNORECASE,
)

_BOND_SUFFIX_RE = re.compile(
    r"(SCP|MTN|CP|PPN|GN|PRN|次级|永续|转债|可转|私募债|公司债|企业债)",
    re.IGNORECASE,
)

_LABEL_WORDS = (
    "公募",
    "私募",
    "票面",
    "中债",
    "中证",
    "估值",
    "评级",
    "主体",
    "债项",
    "昨日",
    "今日",
    "带量",
    "价格",
    "代码",
    "简称",
    "期限",
    "剩余",
    "收益率",
    "净价",
    "全价",
    "流动性",
    "隐含",
)

_KEYWORDS = frozenset(
    {
        "ofr",
        "of",
        "offer",
        "bid",
        "ofr价",
        "bid价",
        "卖",
        "买",
        "报",
        "报价",
        "万",
        "亿",
        "量",
        "w",
        "y",
        "d",
    }
)


def _looks_like_date(value: str) -> bool:
    """8 位纯数字且像 YYYYMMDD 的，不当成债券代码。"""
    if not re.fullmatch(r"\d{8}", value):
        return False
    year, month, day = int(value[:4]), int(value[4:6]), int(value[6:8])
    return 1990 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def normalize_code(value: str) -> str:
    """去掉代码里的空格，后缀统一大写；没写后缀就不补。"""
    if not value:
        return ""
    code = re.sub(r"\s*\.\s*", ".", str(value).strip())
    code = re.sub(r"\s+", "", code)
    return code.upper()


def find_code(text: str) -> str:
    """从文本里找债券代码；有后缀的优先，没后缀的原样保留。"""
    text = normalize_input(text)
    if not text:
        return ""
    matches = [m.group(1) for m in _CODE_RE.finditer(text)]
    if not matches:
        return ""
    with_suffix = [m for m in matches if "." in m]
    pool = with_suffix or matches
    # 同一段文字里出现多个代码时，取最长的那个（通常是完整代码）
    code = max(pool, key=lambda item: (len(item), item))
    code = normalize_code(code)
    if "." not in code and _looks_like_date(code):
        return ""
    return code


def _strip_code(text: str) -> str:
    cleaned = _CODE_RE.sub("", text or "")
    cleaned = cleaned.strip("()（）[]【】{}<>")
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def _name_score(raw: str, index: int, code_index: Optional[int]) -> int:
    score = 0
    if re.match(r"^\d{2}[\u4e00-\u9fff]", raw):
        score += 5
    if _BOND_SUFFIX_RE.search(raw):
        score += 4
    if code_index is not None and abs(index - code_index) <= 1:
        score += 3
    if len(raw) >= 4:
        score += 1
    if raw.lower() in _KEYWORDS:
        score -= 10
    if raw in ("公募", "私募", "公开", "非公开"):
        score -= 10
    if any(word in raw for word in _LABEL_WORDS):
        score -= 8
    if re.fullmatch(r"[\d.]+", raw):
        score -= 10
    if not re.search(r"[\u4e00-\u9fff]", raw):
        score -= 20
    return score


def find_name(text: str) -> str:
    """从交易行里找债券简称（如 ``26济南城建SCP004``）。"""
    text = normalize_input(text)
    if not text:
        return ""
    tokens = _tokens(text)
    if not tokens:
        return ""

    code_index: Optional[int] = None
    for idx, token in enumerate(tokens):
        if find_code(token):
            code_index = idx
            break

    best = ""
    best_score = -999
    for idx, token in enumerate(tokens):
        raw = _strip_code(token)
        if not raw:
            continue
        score = _name_score(raw, idx, code_index)
        if score > best_score:
            best_score = score
            best = raw

    if best_score <= 0:
        return ""

    # 简称被空格拆开时（26济南城建 SCP004），把紧挨着的债券后缀拼回去。
    if not _BOND_SUFFIX_RE.search(best):
        for idx, token in enumerate(tokens):
            if _strip_code(token) != best:
                continue
            for neighbor in (idx - 1, idx + 1):
                if 0 <= neighbor < len(tokens):
                    part = _strip_code(tokens[neighbor])
                    if re.fullmatch(r"(SCP|MTN|CP|PPN|GN|PRN)\d{0,4}[A-Z]?", part, re.I):
                        merged = best + part if neighbor > idx else part + best
                        return merged
    return best


# --------------------------------------------------------------------------- #
# 剩余期限 / 价格 / 带量
# --------------------------------------------------------------------------- #

_TERM_RE = re.compile(
    r"(?<![0-9A-Za-z])(\d{1,3}(?:\.\d{1,3})?)\s*(D|Y|M|天|年|月)(?![0-9A-Za-z])",
    re.IGNORECASE,
)


def _format_term(number: str, unit: str) -> str:
    unit = unit or ""
    if unit.upper() in ("D", "Y", "M"):
        unit = unit.upper()
    return f"{number}{unit}"


def find_term(text: str) -> str:
    text = normalize_input(text)
    if not text:
        return ""
    match = _TERM_RE.search(text)
    if not match:
        return ""
    return _format_term(match.group(1), match.group(2))


_PRICE_TOKEN_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,4})?)(\*{0,3})$")
_VOLUME_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:w|W|万|萬|亿|億)$")


def _is_price_token(token: str) -> bool:
    return bool(_PRICE_TOKEN_RE.match(token or ""))


def _is_volume_token(token: str) -> bool:
    return bool(_VOLUME_TOKEN_RE.match(token or ""))


def _near_keyword(text: str, start: int, keywords: Sequence[str], window: int = 12) -> bool:
    prefix = text[max(0, start - window):start].lower()
    return any(word.lower() in prefix for word in keywords)


def _format_price(value: str) -> str:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:  # noqa: BLE001 - 非法数字直接当没认出来
        return ""


def find_price(text: str) -> str:
    """找 OFR 价格；输出两位小数，星号不在这里处理（拼装时统一加）。"""
    text = normalize_input(text)
    if not text:
        return ""
    candidates: List[Tuple[int, int, str]] = []
    tokens = _token_spans(text)
    for idx, (token, start) in enumerate(tokens):
        match = _PRICE_TOKEN_RE.match(token)
        if not match:
            continue
        if find_code(token):
            continue
        if _near_keyword(text, start, ("票面", "中债", "中证", "估值", "收益率", "净价", "全价")):
            continue
        number = match.group(1)
        try:
            value = float(number)
        except ValueError:
            continue
        if not 0.05 <= value <= 1000:
            continue
        score = 0
        if match.group(2):
            score += 4
        if "." in number:
            score += 2
            decimals = number.split(".", 1)[1]
            if len(decimals) >= 2:
                score += 1
        else:
            score -= 2
        if idx + 1 < len(tokens) and _is_volume_token(tokens[idx + 1][0]):
            score += 3
        if _near_keyword(text, start, ("OFR", "OFFER", "OF", "卖", "报")):
            score += 3
        candidates.append((score, idx, number))

    if not candidates:
        # 「1.80/1.85」这种双边报价：只取左边，且不能是中债/中证的估值对。
        pair = re.search(
            r"(?<![\d.])(\d{1,3}\.\d{1,4})\s*/\s*(\d{1,3}\.\d{1,4})(?![\d.])", text
        )
        if pair and not _near_keyword(text, pair.start(), ("中债", "中证", "估值")):
            return _format_price(pair.group(1))
        return ""

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return _format_price(candidates[0][2])


_VOLUME_RE = re.compile(
    r"(?<![0-9A-Za-z])(\d+(?:\.\d+)?)\s*(w|W|万|萬|亿|億)(?![0-9A-Za-z])"
)


def _format_volume(number: float, unit: str) -> str:
    unit = unit or ""
    if unit in ("亿", "億"):
        number *= 10000.0
    if abs(number - round(number)) < 1e-9:
        text = str(int(round(number)))
    else:
        text = f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{text}w"


def find_volume(text: str) -> str:
    """带量统一成 ``w``：3000万 → 3000w，1.5亿 → 15000w。"""
    text = normalize_input(text)
    if not text:
        return ""
    matches = list(_VOLUME_RE.finditer(text))
    if matches:
        preferred = None
        for match in matches:
            prefix = text[max(0, match.start() - 8):match.start()]
            if any(word in prefix for word in ("带量", "量", "成交")):
                preferred = match
                break
        match = preferred or matches[-1]
        try:
            number = float(match.group(1))
        except ValueError:
            return ""
        return _format_volume(number, match.group(2))

    # 没写单位，但前面有「带量 / 量」时，按 w 处理。
    fallback = re.search(r"(?:带量|成交量|量)\s*[:：]?\s*(\d+(?:\.\d+)?)", text)
    if fallback:
        try:
            return _format_volume(float(fallback.group(1)), "w")
        except ValueError:
            return ""
    return ""


# --------------------------------------------------------------------------- #
# 公募/私募、评级、票面、中债估值
# --------------------------------------------------------------------------- #

_RATINGS = (
    "AAA",
    "AA+",
    "AA-",
    "AA",
    "A+",
    "A-",
    "A",
    "BBB+",
    "BBB-",
    "BBB",
    "BB+",
    "BB-",
    "BB",
    "B+",
    "B-",
    "B",
    "CCC",
    "CC",
    "C",
    "D",
)
_RATING_ALT = "|".join(re.escape(item) for item in sorted(_RATINGS, key=len, reverse=True))
_RATING_SEARCH_RE = re.compile(
    rf"(?<![A-Za-z0-9+])({_RATING_ALT})(?![A-Za-z0-9+])"
)
_RATING_PAIR_RE = re.compile(
    rf"(?<![A-Za-z0-9+])({_RATING_ALT}|--|—|－)\s*/\s*"
    rf"({_RATING_ALT}|--|—|－)(?![A-Za-z0-9+])"
)
_MAIN_LABEL_RE = re.compile(
    rf"主体(?:评级)?\s*[:：]?\s*({_RATING_ALT}|--|—|－)"
)
_BOND_LABEL_RE = re.compile(
    rf"债项(?:评级)?\s*[:：]?\s*({_RATING_ALT}|--|—|－)"
)


def normalize_rating(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("—", "-").replace("–", "-").replace("－", "-").replace("−", "-")
    if value in ("--", "-", "——", "无", "/", ""):
        return "--" if value else ""
    upper = value.upper()
    return upper if upper in _RATINGS else ""


def find_ratings(text: str) -> Tuple[str, str]:
    """返回 (主体评级, 债项评级)；认不出的返回空串。"""
    text = normalize_input(text)
    if not text:
        return "", ""
    main = ""
    bond = ""
    main_match = _MAIN_LABEL_RE.search(text)
    if main_match:
        main = normalize_rating(main_match.group(1))
    bond_match = _BOND_LABEL_RE.search(text)
    if bond_match:
        bond = normalize_rating(bond_match.group(1))
    if main or bond:
        return main, bond

    pair = _RATING_PAIR_RE.search(text)
    if pair:
        return normalize_rating(pair.group(1)), normalize_rating(pair.group(2))

    single = _RATING_SEARCH_RE.search(text)
    if single:
        main = normalize_rating(single.group(1))
    return main, bond


def find_offering(text: str) -> str:
    text = normalize_input(text)
    if not text:
        return ""
    if "非公开" in text:
        return "私募"
    if "公募" in text:
        return "公募"
    if "私募" in text:
        return "私募"
    if "公开" in text:
        return "公募"
    return ""


_COUPON_LABEL_RE = re.compile(
    r"票面(?:利率)?\s*[:：]?\s*(\d{1,2}(?:\.\d{1,4})?)\s*%?"
)
_PERCENT_RE = re.compile(r"(?<![0-9A-Za-z])(\d{1,2}(?:\.\d{1,4})?)\s*%")


def find_coupon(text: str) -> str:
    text = normalize_input(text)
    if not text:
        return ""
    match = _COUPON_LABEL_RE.search(text)
    if match:
        return f"{match.group(1)}%"
    match = _PERCENT_RE.search(text)
    if match:
        return f"{match.group(1)}%"
    return ""


_CBT_RE = re.compile(
    r"(?:昨日)?中债(?:估值)?\s*[:：]?\s*"
    r"(--|—|－|\d+(?:\.\d+)?)"
    r"(?:\s*/\s*(?:--|—|－|\d+(?:\.\d+)?))?"
)


def find_cbt(text: str) -> str:
    """只认「中债估值」，绝不读「中证估值」；有 ``--/--`` 时取第一个。"""
    text = normalize_input(text)
    if not text:
        return ""
    match = _CBT_RE.search(text)
    if not match:
        return ""
    value = _normalize_dash(match.group(1))
    if value == "--":
        return "--"
    # 防止把「中债估值 10-26」这种日期当成估值
    tail = text[match.start(1) + len(match.group(1)):]
    if value.isdigit() and re.match(r"^\s*-\s*\d{2}\b", tail):
        return ""
    return value


# --------------------------------------------------------------------------- #
# 交易行解析
# --------------------------------------------------------------------------- #

def parse_trade_text(text: str) -> Dict[str, str]:
    """解析交易行文本，只返回认出来的字段。"""
    normalized = normalize_input(text)
    if not normalized:
        return {}
    rating_main, rating_bond = find_ratings(normalized)
    values = {
        "term": find_term(normalized),
        "code": find_code(normalized),
        "name": find_name(normalized),
        "offering": find_offering(normalized),
        "price": find_price(normalized),
        "volume": find_volume(normalized),
        "rating_main": rating_main,
        "rating_bond": rating_bond,
        "cbt": find_cbt(normalized),
        "coupon": find_coupon(normalized),
    }
    return {key: value for key, value in values.items() if value}


# --------------------------------------------------------------------------- #
# 合并 + 拼装
# --------------------------------------------------------------------------- #

def merge_fields(
    text_fields: Optional[Dict[str, str]],
    ocr_fields: Optional[Dict[str, str]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """按约定优先级合并；返回 (字段, 来源)。来源：text / ocr / default。"""
    text_fields = text_fields or {}
    ocr_fields = ocr_fields or {}
    fields: Dict[str, str] = {}
    sources: Dict[str, str] = {}

    for key in FIELD_ORDER:
        text_value = (text_fields.get(key) or "").strip()
        ocr_value = (ocr_fields.get(key) or "").strip()
        if key in OCR_FIRST:
            if ocr_value:
                fields[key] = ocr_value
                sources[key] = "ocr"
            elif text_value:
                fields[key] = text_value
                sources[key] = "text"
            else:
                fields[key] = ""
                sources[key] = "default"
        else:
            if text_value:
                fields[key] = text_value
                sources[key] = "text"
            elif ocr_value:
                fields[key] = ocr_value
                sources[key] = "ocr"
            else:
                fields[key] = ""
                sources[key] = "default"

    # 评级缺一半时，默认 --（DM 上债项评级经常就是 --）。
    if not fields.get("rating_main"):
        fields["rating_main"] = "--"
        sources["rating_main"] = "default"
    if not fields.get("rating_bond"):
        fields["rating_bond"] = "--"
        sources["rating_bond"] = "default"
    return fields, sources


def build_line(fields: Dict[str, str]) -> str:
    """按固定模板拼一行报价。"""
    fields = fields or {}
    term = fields.get("term") or "--"
    code = fields.get("code") or "--"
    name = fields.get("name") or "--"
    offering = fields.get("offering") or "--"

    price = (fields.get("price") or "").strip().rstrip("*")
    price_part = f"--/{price}*" if price else "--/--"

    volume = (fields.get("volume") or "").strip()
    if volume and not volume.lower().endswith("w"):
        volume = f"{volume}w"
    volume_part = f"--/{volume}" if volume else "--/--"
    tail_volume = volume or "--"

    rating_main = fields.get("rating_main") or "--"
    rating_bond = fields.get("rating_bond") or "--"
    cbt = fields.get("cbt") or "--"
    coupon = fields.get("coupon") or "--"

    return " ".join(
        [
            term,
            code,
            name,
            offering,
            price_part,
            volume_part,
            f"{rating_main}/{rating_bond}",
            "昨日中债",
            cbt,
            "票面",
            coupon,
            tail_volume,
        ]
    )


def _same_name(left: str, right: str) -> bool:
    if not left or not right:
        return True
    def _clean(value: str) -> str:
        return re.sub(r"[\s()（）\[\]【】<>《》\-_/]+", "", value).upper()
    a, b = _clean(left), _clean(right)
    return bool(a and b and (a in b or b in a))


def build_warnings(
    text_fields: Dict[str, str],
    ocr_fields: Dict[str, str],
    fields: Dict[str, str],
    sources: Dict[str, str],
    *,
    has_image: bool,
) -> List[str]:
    warnings: List[str] = []

    if not text_fields and not ocr_fields:
        warnings.append("没有可解析的内容：请粘贴交易行文本，或上传 DM 截图。")
        return warnings

    if not has_image:
        warnings.append("没有上传 DM 截图：公募/私募、票面、中债估值、评级只能从交易行文本里取。")

    for key in ("term", "code", "name", "price", "volume"):
        if not fields.get(key):
            warnings.append(f"交易行里没找到{FIELD_LABELS[key]}。")

    if sources.get("offering") == "default":
        warnings.append("没识别到公募/私募，已写 --。")
    if sources.get("cbt") == "default":
        warnings.append("截图和交易行里都没找到中债估值，已写 --。")
    if sources.get("coupon") == "default":
        warnings.append("截图和交易行里都没找到票面利率，已写 --。")
    if sources.get("rating_main") == "default" and sources.get("rating_bond") == "default":
        warnings.append("截图和交易行里都没找到评级，已写 --/--。")

    text_code = text_fields.get("code") or ""
    ocr_code = ocr_fields.get("code") or ""
    if text_code and ocr_code and normalize_code(text_code) != normalize_code(ocr_code):
        warnings.append(
            f"交易行代码（{normalize_code(text_code)}）和截图（{normalize_code(ocr_code)}）不一致，已按交易行输出。"
        )

    text_name = text_fields.get("name") or ""
    ocr_name = ocr_fields.get("name") or ""
    if text_name and ocr_name and not _same_name(text_name, ocr_name):
        warnings.append(
            f"交易行简称（{text_name}）和截图（{ocr_name}）不一致，已按交易行输出。"
        )

    return warnings


def generate(
    trade_text: str,
    ocr_fields: Optional[Dict[str, str]] = None,
    *,
    has_image: bool = False,
) -> Dict[str, object]:
    """完整流程：解析交易行 → 合并截图字段 → 拼报价行 → 收集提示。"""
    text_fields = parse_trade_text(trade_text)
    ocr_fields = dict(ocr_fields or {})
    fields, sources = merge_fields(text_fields, ocr_fields)
    line = build_line(fields)
    warnings = build_warnings(
        text_fields,
        ocr_fields,
        fields,
        sources,
        has_image=has_image,
    )
    return {
        "line": line,
        "fields": fields,
        "sources": sources,
        "warnings": warnings,
        "text_fields": text_fields,
        "ocr_fields": ocr_fields,
    }


# --------------------------------------------------------------------------- #
# 自检用的固定样例
# --------------------------------------------------------------------------- #

SAMPLE_TEXT = "26济南城建SCP004 012681631.IB 3D 1.80* 3000w"
SAMPLE_OCR = {
    "code": "012681631.IB",
    "name": "26济南城建SCP004",
    "offering": "公募",
    "term": "3D",
    "coupon": "1.3600%",
    "cbt": "--",
    "rating_main": "AAA",
}
SAMPLE_EXPECTED = (
    "3D 012681631.IB 26济南城建SCP004 公募 --/1.80* --/3000w "
    "AAA/-- 昨日中债 -- 票面 1.3600% 3000w"
)
