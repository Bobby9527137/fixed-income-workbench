"""从任意排版的文本里抽出模版需要的字段。

思路：**不按位置解析**，先归一化，再按「特征 + 锚点」给每个 token 分类，
最后用关系锚点（出给/卖给/→）和交叉校验组装。顺序乱了也能认。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import features as F
from .normalize import normalize
from .render import render

# 名称拼装到这里就停
_NAME_BOUNDARY = {"label", "institution", "coupon", "date", "number", "channel", "offset", "anchor"}
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass
class ParseResult:
    fields: dict
    warnings: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fields": self.fields,
            "warnings": self.warnings,
            "output": render(self.fields),
            "tokens": self.tokens,
            "kinds": self.kinds,
        }


def parse(text: str) -> ParseResult:
    norm = normalize(text)
    tokens = norm.split()
    kinds = _classify(tokens)
    fields: dict = {}
    warnings: list[str] = []

    _fill_date(tokens, kinds, fields, warnings)
    _fill_code(tokens, kinds, fields, warnings)
    code_idx = next(
        (i for i, token in enumerate(tokens) if token == fields["code"]), None
    )
    fields["name"] = _extract_name(tokens, kinds, code_idx)
    _fill_coupon(tokens, kinds, fields, warnings)
    _fill_price(tokens, kinds, fields, "face", ("券面", "面值"), "100")
    _fill_price(tokens, kinds, fields, "net", ("净价", "价格"), "100")

    seller, buyer = _extract_parties(tokens, kinds)
    contacts = _extract_contacts(tokens, kinds)

    if not seller and contacts:
        seller = contacts[0]["inst"]
    if not buyer and len(contacts) > 1:
        buyer = contacts[1]["inst"]

    seller_contact = _match_contact(contacts, seller)
    buyer_contact = _match_contact(contacts, buyer)
    if seller_contact is None and contacts:
        seller_contact = contacts[0]
    if buyer_contact is None:
        remaining = [c for c in contacts if c is not seller_contact]
        if remaining:
            buyer_contact = remaining[0]

    fields["seller"] = seller or ""
    fields["buyer"] = buyer or ""
    fields["seller_contact"] = seller_contact or _empty_contact()
    fields["buyer_contact"] = buyer_contact or _empty_contact()

    _validate(fields, warnings, tokens, kinds, norm)
    return ParseResult(fields=fields, warnings=warnings, tokens=tokens, kinds=kinds)


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------
def _classify(tokens: list[str]) -> list[str]:
    kinds: list[str] = []
    for token in tokens:
        kinds.append(_classify_token(token))

    # 6-9 位裸数字可能是债券代码，也可能是短号码；只有紧跟渠道词时才当号码
    for i, token in enumerate(tokens):
        if kinds[i] == "unknown" and F.CODE_BARE.match(token):
            near_channel = any(
                kinds[j] == "channel" for j in range(max(0, i - 4), i)
            )
            kinds[i] = "number" if near_channel else "code"
    return kinds


def _classify_token(token: str) -> str:
    if token in F.ANCHORS:
        return "anchor"
    if token in F.LABELS:
        return "label"
    if token.upper() in F.CHANNELS:
        return "channel"
    if F.CODE_WITH_SUFFIX.match(token):
        return "code"
    if F.COUPON_PCT.match(token) or F.COUPON_BP.match(token):
        return "coupon"
    if F.DATE_TOKEN.match(token) and F.is_valid_date(
        F.DATE_TOKEN.match(token).group("month"), F.DATE_TOKEN.match(token).group("day")
    ):
        return "date"
    if F.DATE_CN.match(token):
        return "date"
    if F.OFFSET_TOKEN.match(token):
        return "offset"
    if F.CONTACT_NUMBER.match(token):
        return "number"
    if F.is_institution(token):
        return "institution"
    if F.is_bond_name(token):
        return "bondname"
    return "unknown"


# ---------------------------------------------------------------------------
# 各字段
# ---------------------------------------------------------------------------
def _fill_date(tokens: list[str], kinds: list[str], fields: dict, warnings: list[str]) -> None:
    for i, kind in enumerate(kinds):
        if kind != "date":
            continue
        match = F.DATE_TOKEN.match(tokens[i]) or F.DATE_CN.match(tokens[i])
        if not match:
            continue
        month, day = int(match.group("month")), int(match.group("day"))
        fields["date"] = f"{month:02d}{day:02d}"
        offset = match.group("offset")
        if offset is None:
            for j in (i + 1, i - 1):
                if 0 <= j < len(tokens) and kinds[j] == "offset":
                    offset = F.OFFSET_TOKEN.match(tokens[j]).group("offset")
                    break
        fields["offset"] = f"+{int(offset)}" if offset is not None else ""
        return
    fields["date"] = ""
    fields["offset"] = ""
    warnings.append("未识别到日期（形如 1029 或 10月29日）")


def _fill_code(tokens: list[str], kinds: list[str], fields: dict, warnings: list[str]) -> None:
    codes = [tokens[i] for i, k in enumerate(kinds) if k == "code"]
    suffixes = [c for c in codes if F.code_has_suffix(c)]
    fields["code"] = (suffixes or codes or [""])[0]
    if fields["code"] and not F.code_has_suffix(fields["code"]):
        warnings.append("债券代码没有市场后缀，建议补 .IB / .SH / .SZ")
    elif not fields["code"]:
        warnings.append("未识别到债券代码")


def _extract_name(tokens: list[str], kinds: list[str], code_idx: int | None) -> str:
    if code_idx is not None:
        parts: list[str] = []
        for i in range(code_idx + 1, len(tokens)):
            kind = kinds[i]
            if kind == "bondname":
                parts.append(tokens[i])
                break
            if kind in _NAME_BOUNDARY or not _looks_like_name_part(tokens[i]):
                break
            parts.append(tokens[i])
        joined = "".join(parts)
        if F.is_bond_name(joined):
            return joined
    names = [t for t, k in zip(tokens, kinds) if k == "bondname"]
    return names[0] if names else ""


def _looks_like_name_part(token: str) -> bool:
    if not token or token in F.NOISE or token in F.LABELS:
        return False
    if F.is_institution(token):
        return False
    # 「发X请求」「A出给B」「上市要素」这些不是名称的一部分
    if re.search(r"(请求|出给|卖给|转给|售予|上市要素)", token):
        return False
    return bool(re.fullmatch(r"[0-9A-Za-z\u4e00-\u9fa5]+", token)) and len(token) <= 20


def _fill_coupon(tokens: list[str], kinds: list[str], fields: dict, warnings: list[str]) -> None:
    for i, kind in enumerate(kinds):
        if kind == "coupon":
            token = tokens[i]
            pct = F.COUPON_PCT.match(token)
            bp = F.COUPON_BP.match(token)
            if pct:
                fields["coupon"] = f"{pct.group('value')}%"
            else:
                fields["coupon"] = f"{float(bp.group('value')) / 100:.2f}%"
            return
    # 没有 % 时靠标签兜底：票面 2.05
    for i, token in enumerate(tokens):
        if token in ("票面", "利率"):
            for j in range(i + 1, min(len(tokens), i + 3)):
                if _NUMBER.match(tokens[j]):
                    fields["coupon"] = f"{tokens[j]}%"
                    return
    fields["coupon"] = ""
    warnings.append("未识别到票面利率")


def _fill_price(
    tokens: list[str],
    kinds: list[str],
    fields: dict,
    key: str,
    labels: tuple[str, ...],
    default: str,
) -> None:
    for i, token in enumerate(tokens):
        if token not in labels:
            continue
        for j in range(i + 1, min(len(tokens), i + 3)):
            if _NUMBER.match(tokens[j]):
                fields[key] = tokens[j]
                return
    fields[key] = default


def _extract_parties(tokens: list[str], kinds: list[str]) -> tuple[str, str]:
    for i, token in enumerate(tokens):
        if token not in F.ANCHORS:
            continue
        seller = _nearest(tokens, kinds, i, -1, "institution")
        buyer = _nearest(tokens, kinds, i, +1, "institution")
        if seller and buyer:
            return seller, buyer

    institutions: list[str] = []
    for token, kind in zip(tokens, kinds):
        if kind == "institution" and token not in institutions:
            institutions.append(token)
    if len(institutions) >= 2:
        return institutions[0], institutions[1]
    return (institutions[0] if institutions else ""), ""


def _nearest(tokens: list[str], kinds: list[str], index: int, step: int, wanted: str) -> str:
    limit = 10
    i = index + step
    while 0 <= i < len(tokens) and limit > 0:
        if kinds[i] == wanted:
            return tokens[i]
        i += step
        limit -= 1
    return ""


def _extract_contacts(tokens: list[str], kinds: list[str]) -> list[dict]:
    contacts: list[dict] = []
    for j, kind in enumerate(kinds):
        if kind != "number":
            continue
        channel = ""
        channel_idx = None
        for i in range(j - 1, max(-1, j - 7), -1):
            if kinds[i] == "channel":
                channel = tokens[i]
                channel_idx = i
                break
        inst = ""
        inst_idx = None
        lower = channel_idx if channel_idx is not None else j
        for i in range(lower - 1, max(-1, j - 10), -1):
            if kinds[i] == "institution":
                inst = tokens[i]
                inst_idx = i
                break
        person = ""
        start = inst_idx if inst_idx is not None else max(-1, j - 5)
        for i in range(j - 1, start, -1):
            if kinds[i] == "unknown" and F.is_person(tokens[i]):
                person = tokens[i]
                break
        contacts.append(
            {"inst": inst, "person": person, "channel": channel, "number": tokens[j]}
        )
    return contacts


def _match_contact(contacts: list[dict], inst: str) -> dict | None:
    if not inst:
        return None
    for contact in contacts:
        if contact.get("inst") == inst:
            return contact
    return None


def _empty_contact() -> dict:
    return {"inst": "", "person": "", "channel": "", "number": ""}


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def _validate(
    fields: dict,
    warnings: list[str],
    tokens: list[str],
    kinds: list[str],
    norm: str,
) -> None:
    if not fields.get("name"):
        warnings.append("未识别到债券简称")
    if not fields.get("seller") or not fields.get("buyer"):
        warnings.append("未识别到「谁出给谁」")

    seller_contact = fields.get("seller_contact") or {}
    if not seller_contact.get("number"):
        warnings.append("未识别到卖方联系方式")
    buyer_contact = fields.get("buyer_contact") or {}
    if not buyer_contact.get("number"):
        warnings.append("未识别到买方联系方式")

    target = _request_target(norm)
    if target:
        fields["request_target"] = target
        if fields.get("seller") and target != fields["seller"]:
            warnings.append(f"「发{target}请求」与卖方「{fields['seller']}」不一致，请确认")
    else:
        fields["request_target"] = fields.get("seller", "")


def _request_target(norm: str) -> str:
    patterns = (
        r"发\s*([^\s]{2,20}?)\s*请求",
        r"向\s*([^\s]{2,20}?)\s*发(?:起)?请求",
    )
    for pattern in patterns:
        match = re.search(pattern, norm)
        if match:
            target = match.group(1)
            if F.is_institution(target) or len(target) <= 8:
                return target
    return ""
