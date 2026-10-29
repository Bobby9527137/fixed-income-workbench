"""随机测试语料生成器。

用途：造出「变量齐全、位置打乱、内容随机」的输入，贴进工具里测解析。
不追求真实业务数据，只保证字段类型和模版一致。
"""

from __future__ import annotations

import random

INSTITUTIONS = (
    "江城银行",
    "龙头证券",
    "华信信托",
    "中金基金",
    "海通资管",
    "瑞丰农商行",
    "东兴证券",
    "国泰保险资管",
    "中原银行",
    "长江证券",
    "建信基金",
    "浙商银行",
)

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜"
GIVEN_NAMES = (
    "子涵",
    "雨桐",
    "思远",
    "嘉怡",
    "昊然",
    "若曦",
    "明轩",
    "晓彤",
    "亦然",
    "静宜",
    "博文",
    "一诺",
    "承泽",
    "书瑶",
)

ISSUERS = (
    "上饶产投",
    "杭州城建",
    "苏州交投",
    "成都高新",
    "宁波海曙",
    "合肥建投",
    "南京江北",
    "无锡产业",
    "绍兴城投",
    "嘉兴国资",
    "常州交通",
    "温州城发",
)

BOND_KINDS = ("MTN001", "MTN002", "SCP001", "SCP002", "CP001", "PPN001", "债01")

SEPARATORS = (" ", "  ", "\n")
NOISE = ("帮忙整理下", "看下这个", "谢谢", "转发一下", "上市要素如下")


def generate(seed: int | None = None, layout: str | None = None) -> tuple[str, dict]:
    """返回 ``(随机文本, 期望字段)``。

    ``layout`` 可选 ``labeled`` / ``shuffled`` / ``chatty`` / ``dense`` / ``fullwidth``；
    不传则随机。
    """
    rng = random.Random(seed)
    fields = _random_fields(rng)
    layout = layout or rng.choice(
        ("labeled", "shuffled", "chatty", "dense", "fullwidth")
    )
    text = _LAYOUTS[layout](rng, fields)
    return text, fields


# ---------------------------------------------------------------------------
# 造字段
# ---------------------------------------------------------------------------
def _random_fields(rng: random.Random) -> dict:
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    offset = rng.choice((0, 0, 0, 1, 2))

    if rng.random() < 0.75:
        code = f"{rng.randint(100000000, 999999999)}.{rng.choice(('IB', 'IB', 'SH', 'SZ'))}"
    else:
        code = f"{rng.randint(100000000, 999999999)}"

    name = f"{rng.choice(('26', '25', '24'))}{rng.choice(ISSUERS)}{rng.choice(BOND_KINDS)}"
    coupon = f"{rng.uniform(1.6, 4.2):.2f}%"
    net = rng.choice(("100", "100", "100", "99.99", "100.01"))

    seller, buyer = rng.sample(INSTITUTIONS, 2)
    seller_contact = _contact(rng, seller)
    buyer_contact = _contact(rng, buyer)
    # 两个号码不重复
    while buyer_contact["number"] == seller_contact["number"]:
        buyer_contact = _contact(rng, buyer)

    return {
        "date": f"{month:02d}{day:02d}",
        "offset": f"+{offset}",
        "code": code,
        "name": name,
        "face": "100",
        "coupon": coupon,
        "net": net,
        "seller": seller,
        "buyer": buyer,
        "seller_contact": seller_contact,
        "buyer_contact": buyer_contact,
        "request_target": seller,
    }


def _contact(rng: random.Random, inst: str) -> dict:
    return {
        "inst": inst,
        "person": rng.choice(SURNAMES) + rng.choice(GIVEN_NAMES),
        "channel": rng.choice(("QT", "QQ", "微信")),
        "number": "2" + "".join(str(rng.randint(0, 9)) for _ in range(9)),
    }


# ---------------------------------------------------------------------------
# 排版
# ---------------------------------------------------------------------------
def _flow_pieces(rng: random.Random, fields: dict) -> list[str]:
    """把字段拆成可打乱的片段，标签随机带或不带。"""
    def label(primary: str, alias: str) -> str:
        return rng.choice((primary, alias))

    pieces = [
        f"{fields['date']}{fields['offset']}",
        fields["code"],
        fields["name"],
        f"{label('券面', '面值')} {fields['face']}",
        f"{label('票面', '利率')} {fields['coupon']}",
        f"{label('净价', '价格')} {fields['net']}",
        f"{fields['seller']}出给{fields['buyer']}",
        f"发{fields['seller']}请求",
    ]
    rng.shuffle(pieces)

    contacts = [
        _contact_text(fields["seller_contact"]),
        _contact_text(fields["buyer_contact"]),
    ]
    if rng.random() < 0.5:
        contacts.reverse()
    return pieces + contacts


def _contact_text(contact: dict) -> str:
    return " ".join(
        [
            contact["inst"],
            contact["person"],
            contact["channel"],
            contact["number"],
        ]
    )


def _labeled(rng: random.Random, fields: dict) -> str:
    pieces = _flow_pieces(rng, fields)
    body = "  ".join(pieces[:6])
    rest = "  ".join(pieces[6:])
    return f"{fields['date']}{fields['offset']} 上市要素：\n{body}\n{rest}"


def _shuffled(rng: random.Random, fields: dict) -> str:
    pieces = _flow_pieces(rng, fields)
    return _join(rng, pieces)


def _chatty(rng: random.Random, fields: dict) -> str:
    pieces = _flow_pieces(rng, fields)
    return "\n".join(
        [
            rng.choice(NOISE),
            _join(rng, pieces),
            rng.choice(NOISE),
        ]
    )


def _dense(rng: random.Random, fields: dict) -> str:
    pieces = _flow_pieces(rng, fields)
    return " ".join(pieces)


def _fullwidth(rng: random.Random, fields: dict) -> str:
    pieces = _flow_pieces(rng, fields)
    text = f"，{rng.choice(SEPARATORS).strip() or '，'}".join(pieces)
    text = text.replace("%", "％")
    return f"{fields['date']}{fields['offset']}上市要素，{text}"


def _join(rng: random.Random, pieces: list[str]) -> str:
    parts: list[str] = []
    for piece in pieces:
        parts.append(piece)
        parts.append(rng.choice(SEPARATORS))
    return "".join(parts).strip()


_LAYOUTS = {
    "labeled": _labeled,
    "shuffled": _shuffled,
    "chatty": _chatty,
    "dense": _dense,
    "fullwidth": _fullwidth,
}
