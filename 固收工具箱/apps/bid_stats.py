# -*- coding: utf-8 -*-
"""投标/中标统计：按债券汇总投标量、加权利率、中标量与中标率。"""

from __future__ import annotations

import base64
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fi_toolbox.app import run
from fi_toolbox.excel import build_xlsx

META = {
    "id": "bid_stats",
    "name": "投标/中标统计",
    "desc": "按债券汇总投标量、加权利率、中标量与中标率",
    "port": 8519,
}

COLUMNS = [
    {"key": "bond", "label": "债券", "type": "text", "width": 20},
    {"key": "bid_amount", "label": "投标量(万元)", "type": "number", "width": 14},
    {"key": "bid_rate", "label": "投标利率(%)", "type": "number", "width": 12},
    {"key": "allocation", "label": "中标量(万元)", "type": "number", "width": 14},
]

FIELDS = [
    {"key": "bids", "label": "投标明细", "type": "table", "columns": COLUMNS, "min_rows": 1,
     "default_rows": [
         {"bond": "26上饶产投MTN001", "bid_amount": 3000, "bid_rate": 2.35, "allocation": 1000},
     ]},
]


def sample(seed: int | None = None) -> dict:
    return {
        "bids": [
            {"bond": "26上饶产投MTN001", "bid_amount": 3000, "bid_rate": 2.35, "allocation": 1000},
            {"bond": "26上饶产投MTN001", "bid_amount": 2000, "bid_rate": 2.38, "allocation": 500},
            {"bond": "26上饶产投MTN001", "bid_amount": 1500, "bid_rate": 2.32, "allocation": 800},
            {"bond": "26宁波银行债01", "bid_amount": 2000, "bid_rate": 1.95, "allocation": 1000},
            {"bond": "26宁波银行债01", "bid_amount": 1000, "bid_rate": 1.98, "allocation": 200},
        ],
    }


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def compute(data: dict) -> dict:
    grouped = defaultdict(lambda: {"bid": 0.0, "rate_amount": 0.0, "allocation": 0.0})
    warnings = []
    total_bid = 0.0
    total_allocation = 0.0
    total_rate_amount = 0.0

    for index, row in enumerate(data["bids"], start=1):
        bond = (row.get("bond") or "").strip()
        bid = row.get("bid_amount")
        rate = row.get("bid_rate")
        allocation = row.get("allocation") or 0
        if not bond:
            warnings.append(f"第 {index} 行没有债券名称，已跳过")
            continue
        if bid is None or rate is None:
            warnings.append(f"第 {index} 行投标量或利率为空，已跳过")
            continue
        bid = float(bid)
        rate = float(rate)
        allocation = float(allocation)
        if bid <= 0:
            warnings.append(f"第 {index} 行投标量必须大于 0，已跳过")
            continue
        if allocation < 0:
            warnings.append(f"第 {index} 行中标量不能为负，已跳过")
            continue
        if allocation > bid:
            warnings.append(f"第 {index} 行中标量大于投标量，请核对")
        item = grouped[bond]
        item["bid"] += bid
        item["rate_amount"] += bid * rate
        item["allocation"] += allocation
        total_bid += bid
        total_allocation += allocation
        total_rate_amount += bid * rate

    if not grouped:
        raise ValueError("没有有效投标明细")

    rows = []
    for bond, item in sorted(grouped.items(), key=lambda pair: -pair[1]["bid"]):
        weighted = item["rate_amount"] / item["bid"] if item["bid"] else 0.0
        hit = item["allocation"] / item["bid"] * 100.0 if item["bid"] else 0.0
        rows.append({
            "bond": bond,
            "bid": _fmt(item["bid"]),
            "rate": _fmt(weighted, 4),
            "allocation": _fmt(item["allocation"]),
            "hit": _fmt(hit, 2),
        })

    overall_rate = total_rate_amount / total_bid if total_bid else 0.0
    overall_hit = total_allocation / total_bid * 100.0 if total_bid else 0.0
    metrics = [
        {"label": "投标总量", "value": _fmt(total_bid), "unit": "万元"},
        {"label": "中标总量", "value": _fmt(total_allocation), "unit": "万元"},
        {"label": "整体中标率", "value": _fmt(overall_hit, 2), "unit": "%"},
        {"label": "加权投标利率", "value": _fmt(overall_rate, 4), "unit": "%"},
        {"label": "债券只数", "value": str(len(grouped)), "unit": "只"},
    ]
    tables = [{
        "title": "按债券汇总",
        "columns": [
            {"key": "bond", "label": "债券"}, {"key": "bid", "label": "投标量(万元)", "type": "number"},
            {"key": "rate", "label": "加权利率(%)", "type": "number"},
            {"key": "allocation", "label": "中标量(万元)", "type": "number"},
            {"key": "hit", "label": "中标率(%)", "type": "number"},
        ],
        "rows": rows,
    }]
    workbook = build_xlsx([{
        "name": "投标统计",
        "columns": [{"key": "bond", "label": "债券", "width": 24},
                    {"key": "bid", "label": "投标量(万元)", "width": 14},
                    {"key": "rate", "label": "加权利率(%)", "width": 14},
                    {"key": "allocation", "label": "中标量(万元)", "width": 14},
                    {"key": "hit", "label": "中标率(%)", "width": 12}],
        "rows": rows,
    }])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": warnings,
        "download": {"name": "投标统计.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
