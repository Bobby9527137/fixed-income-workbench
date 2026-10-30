# -*- coding: utf-8 -*-
"""投标簿记的随机示例数据。

生成一套互相对应的：
- 表格行（模拟 OCR 成功后的结果）；
- 窗口 1 的债券文本行；
- 窗口 2 的边际数据行（给最后一只债，验证“截图里没有、文本里有”的路径）。
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any, Dict, List

ISSUERS = (
    ("武清经开", "MTN"),
    ("天津城投", "CP"),
    ("杭州城建", "MTN"),
    ("苏州交投", "SCP"),
    ("成都高新", "PPN"),
    ("宁波银行", "MTN"),
    ("绍兴城投", "CP"),
    ("江苏交通", "SCP"),
)

RATINGS = ("AAA", "AAA", "AA+", "AA+", "AA")
TENORS = ("1Y", "2Y", "3Y", "5Y")


def _md(day: date) -> str:
    return f"{day.month:02d}-{day.day:02d}"


def generate(seed: int | None = None) -> Dict[str, Any]:
    if seed is None:
        seed = random.randrange(1, 1_000_000)
    rng = random.Random(seed)
    count = rng.randint(4, 7)
    base = date(2026, 10, 1)

    bonds: List[Dict[str, Any]] = []
    for index in range(count):
        short, kind = rng.choice(ISSUERS)
        year = rng.choice(("25", "26"))
        name = f"{year}{short}{kind}{rng.randint(1, 9):03d}"
        low = round(rng.uniform(1.2, 2.4), 1)
        high = round(low + rng.uniform(0.3, 1.0), 1)
        tenor = rng.choice(TENORS)
        scale = round(rng.uniform(0.5, 5.0), 1)
        rating = rng.choice(RATINGS)
        book = base + timedelta(days=rng.randint(0, 18))
        pay = book + timedelta(days=1)
        listing = pay + timedelta(days=1)
        bonds.append({
            "name": name,
            "range": f"{low}-{high}",
            "tenor": tenor,
            "scale": scale,
            "rating": rating,
            "book": book,
            "pay": pay,
            "listing": listing,
            "margin": round(rng.uniform(1.4, 3.2), 2),
            "full": round(rng.uniform(1.0, 5.0), 2),
            "edge": round(rng.uniform(1.0, 4.0), 2),
        })

    # 表格里放前 n-1 只；最后一只只给窗口 2，验证“没有截图也能出数”
    table_bonds = bonds[:-1]
    value_bond = bonds[-1]

    pasted = "\n".join(
        f"【{b['range']}】，{b['name']}，{b['tenor']}，{b['scale']}亿，{b['rating']}，"
        f"{_md(b['book'])} 簿记，{_md(b['pay'])} 缴款，{_md(b['listing'])} 上市"
        for b in bonds
    )

    values = (
        f"{value_bond['name']} 边际{value_bond['margin']}% "
        f"全场{value_bond['full']}倍 边际倍数{value_bond['edge']}倍"
    )

    rows = [
        {
            "code": b["name"],
            "name": b["name"],
            "raw_name": b["name"],
            "tenor_text": b["tenor"],
            "scale_text": f"{b['scale']}亿",
            "rating_text": b["rating"],
            "margin_rate": b["margin"],
            "full_ratio": b["full"],
            "edge_ratio": b["edge"],
            "missing": [],
        }
        for b in table_bonds
    ]

    return {
        "seed": seed,
        "rows": rows,
        "pasted": pasted,
        "values": values,
        "bonds": [
            {key: (value.isoformat() if isinstance(value, date) else value)
             for key, value in bond.items()}
            for bond in bonds
        ],
    }
