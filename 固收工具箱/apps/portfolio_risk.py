# -*- coding: utf-8 -*-
"""组合风险快照：加权久期、DV01、评级/行业集中度、利率情景。"""

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
    "id": "portfolio_risk",
    "name": "组合风险快照",
    "desc": "加权久期、总 DV01、评级/行业集中度、±利率情景",
    "port": 8517,
}

COLUMNS = [
    {"key": "code", "label": "代码", "type": "text", "width": 14},
    {"key": "name", "label": "名称", "type": "text", "width": 22},
    {"key": "market_value", "label": "市值(万元)", "type": "number", "width": 14},
    {"key": "modified_duration", "label": "修正久期", "type": "number", "width": 10},
    {"key": "rating", "label": "评级", "type": "text", "width": 8},
    {"key": "industry", "label": "行业", "type": "text", "width": 12},
]

FIELDS = [
    {"key": "shock_bp", "label": "利率情景（bp）", "type": "number", "default": 25, "step": 1, "required": True},
    {"key": "holdings", "label": "持仓", "type": "table", "columns": COLUMNS, "min_rows": 1,
     "default_rows": [
         {"code": "2405253.IB", "name": "24浙江债07", "market_value": 5000, "modified_duration": 7.2,
          "rating": "AAA", "industry": "地方政府债"},
     ]},
]


def sample(seed: int | None = None) -> dict:
    return {
        "shock_bp": 25,
        "holdings": [
            {"code": "2405253.IB", "name": "24浙江债07", "market_value": 5000, "modified_duration": 7.20,
             "rating": "AAA", "industry": "地方政府债"},
            {"code": "102683905.IB", "name": "26上饶产投MTN001", "market_value": 3000, "modified_duration": 3.10,
             "rating": "AA+", "industry": "城投"},
            {"code": "212480001.IB", "name": "26宁波银行债01", "market_value": 2000, "modified_duration": 2.80,
             "rating": "AAA", "industry": "金融"},
            {"code": "012480090.IB", "name": "26中石化SCP004", "market_value": 1500, "modified_duration": 0.80,
             "rating": "AAA", "industry": "产业"},
            {"code": "102280012.IB", "name": "26杭城投MTN002", "market_value": 1000, "modified_duration": 4.60,
             "rating": "AA+", "industry": "城投"},
        ],
    }


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _distribution(holdings, total, key):
    grouped = defaultdict(float)
    for item in holdings:
        grouped[item.get(key) or "未分类"] += item["market_value"]
    rows = []
    for name, value in sorted(grouped.items(), key=lambda pair: -pair[1]):
        rows.append({"name": name, "value": _fmt(value), "pct": _fmt(value / total * 100, 2) if total else "0.00"})
    return rows


def compute(data: dict) -> dict:
    shock = float(data["shock_bp"])
    holdings = []
    warnings = []
    for index, item in enumerate(data["holdings"], start=1):
        mv = item.get("market_value")
        duration = item.get("modified_duration")
        if mv is None or duration is None:
            warnings.append(f"第 {index} 行市值或久期为空，已跳过")
            continue
        mv = float(mv)
        duration = float(duration)
        if mv <= 0:
            warnings.append(f"第 {index} 行市值必须大于 0，已跳过")
            continue
        if duration < 0:
            warnings.append(f"第 {index} 行久期不能为负，已跳过")
            continue
        holdings.append({**item, "market_value": mv, "modified_duration": duration})

    if not holdings:
        raise ValueError("没有有效持仓，请至少填一行市值和久期")

    total = sum(item["market_value"] for item in holdings)
    weighted_duration = sum(item["market_value"] * item["modified_duration"] for item in holdings) / total
    dv01 = sum(item["market_value"] * item["modified_duration"] * 0.0001 for item in holdings)
    up_pnl = -dv01 * shock
    down_pnl = dv01 * shock
    top = sorted(holdings, key=lambda item: -item["market_value"])[:5]

    metrics = [
        {"label": "持仓只数", "value": str(len(holdings)), "unit": "只"},
        {"label": "总市值", "value": _fmt(total), "unit": "万元"},
        {"label": "加权修正久期", "value": _fmt(weighted_duration, 4), "unit": "年"},
        {"label": "总 DV01", "value": _fmt(dv01, 2), "unit": "万元/bp"},
        {"label": f"利率 +{shock:g}bp", "value": _fmt(up_pnl, 2), "unit": "万元"},
        {"label": f"利率 -{shock:g}bp", "value": _fmt(down_pnl, 2), "unit": "万元"},
    ]

    holding_rows = []
    for item in sorted(holdings, key=lambda row: -row["market_value"]):
        holding_rows.append({
            "code": item.get("code") or "",
            "name": item.get("name") or "",
            "mv": _fmt(item["market_value"]),
            "duration": _fmt(item["modified_duration"], 4),
            "dv01": _fmt(item["market_value"] * item["modified_duration"] * 0.0001, 2),
            "weight": _fmt(item["market_value"] / total * 100, 2),
            "rating": item.get("rating") or "",
            "industry": item.get("industry") or "",
        })

    tables = [
        {"title": "持仓明细", "columns": [
            {"key": "code", "label": "代码"}, {"key": "name", "label": "名称"},
            {"key": "mv", "label": "市值(万元)", "type": "number"},
            {"key": "duration", "label": "修正久期", "type": "number"},
            {"key": "dv01", "label": "DV01(万元/bp)", "type": "number"},
            {"key": "weight", "label": "占比(%)", "type": "number"},
            {"key": "rating", "label": "评级"}, {"key": "industry", "label": "行业"},
        ], "rows": holding_rows},
        {"title": "评级分布", "columns": [
            {"key": "name", "label": "评级"}, {"key": "value", "label": "市值(万元)", "type": "number"},
            {"key": "pct", "label": "占比(%)", "type": "number"},
        ], "rows": _distribution(holdings, total, "rating")},
        {"title": "行业分布", "columns": [
            {"key": "name", "label": "行业"}, {"key": "value", "label": "市值(万元)", "type": "number"},
            {"key": "pct", "label": "占比(%)", "type": "number"},
        ], "rows": _distribution(holdings, total, "industry")},
        {"title": "前五大持仓", "columns": [
            {"key": "name", "label": "名称"}, {"key": "mv", "label": "市值(万元)", "type": "number"},
            {"key": "weight", "label": "占比(%)", "type": "number"},
        ], "rows": [{"name": item.get("name") or item.get("code"), "mv": _fmt(item["market_value"]),
                     "weight": _fmt(item["market_value"] / total * 100, 2)} for item in top]},
    ]

    workbook = build_xlsx([
        {"name": "持仓", "columns": [
            {"key": "code", "label": "代码", "width": 16}, {"key": "name", "label": "名称", "width": 24},
            {"key": "mv", "label": "市值(万元)", "width": 14}, {"key": "duration", "label": "修正久期", "width": 10},
            {"key": "dv01", "label": "DV01", "width": 12}, {"key": "weight", "label": "占比%", "width": 10},
            {"key": "rating", "label": "评级", "width": 8}, {"key": "industry", "label": "行业", "width": 14},
        ], "rows": holding_rows},
        {"name": "评级分布", "columns": [{"key": "name", "label": "评级"}, {"key": "value", "label": "市值(万元)"},
                                          {"key": "pct", "label": "占比%"}],
         "rows": _distribution(holdings, total, "rating")},
        {"name": "行业分布", "columns": [{"key": "name", "label": "行业"}, {"key": "value", "label": "市值(万元)"},
                                          {"key": "pct", "label": "占比%"}],
         "rows": _distribution(holdings, total, "industry")},
    ])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": warnings,
        "download": {"name": "组合风险快照.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
