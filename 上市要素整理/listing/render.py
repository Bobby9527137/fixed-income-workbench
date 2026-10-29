"""按固定模版渲染。

    1029+0 上市要素：
    102683905.IB  26上饶产投MTN001  券面 100  票面 2.05%  净价 100  江城银行出给龙头证券  发江城银行请求
    江城银行 刘如烟 QT 2555555555
    龙头证券 陈默 QT 2555555556
"""

from __future__ import annotations


def render(fields: dict) -> str:
    date = fields.get("date", "") or ""
    offset = fields.get("offset", "") or ""
    code = fields.get("code", "") or ""
    name = fields.get("name", "") or ""
    face = fields.get("face", "") or "100"
    coupon = fields.get("coupon", "") or ""
    net = fields.get("net", "") or "100"
    seller = fields.get("seller", "") or ""
    buyer = fields.get("buyer", "") or ""

    head = f"{date}{offset} 上市要素：".strip()
    body = "  ".join(
        [
            code,
            name,
            f"券面 {face}",
            f"票面 {coupon}".rstrip(),
            f"净价 {net}",
            f"{seller}出给{buyer}",
            f"发{seller}请求" if seller else "",
        ]
    ).strip()
    lines = [head, body]

    seller_contact = fields.get("seller_contact") or {}
    buyer_contact = fields.get("buyer_contact") or {}
    lines.append(_contact_line(seller_contact, seller))
    lines.append(_contact_line(buyer_contact, buyer))
    return "\n".join(lines)


def _contact_line(contact: dict, fallback_inst: str) -> str:
    inst = fallback_inst or contact.get("inst") or ""
    parts = [
        inst,
        contact.get("person", "") or "",
        contact.get("channel", "") or "",
        contact.get("number", "") or "",
    ]
    return " ".join(part for part in parts if part)
