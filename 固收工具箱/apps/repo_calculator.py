# -*- coding: utf-8 -*-
"""回购 / 资金计算器：到期金额、实际资金成本、质押券与杠杆。"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fi_toolbox import bondmath as bm
from fi_toolbox.app import run
from fi_toolbox.excel import build_xlsx

META = {
    "id": "repo_calculator",
    "name": "回购/资金计算器",
    "desc": "质押式回购到期金额、实际资金成本、质押券与杠杆",
    "port": 8515,
}

FIELDS = [
    {"key": "principal", "label": "融资金额（万元）", "type": "number", "default": 10000, "step": 1, "required": True},
    {"key": "rate", "label": "回购利率（%）", "type": "number", "default": 1.85, "step": 0.01, "required": True},
    {"key": "start", "label": "起息日", "type": "date", "default": "2026-11-02", "required": True},
    {"key": "end", "label": "到期日", "type": "date", "default": "2026-11-09", "required": True},
    {"key": "day_count", "label": "计息基准", "type": "select", "default": "ACT/365",
     "options": [{"value": "ACT/365", "label": "ACT/365"}, {"value": "ACT/360", "label": "ACT/360"},
                 {"value": "30/360", "label": "30/360"}]},
    {"key": "fee_bp", "label": "费用（bp，按融资金额）", "type": "number", "default": 0, "step": 0.1},
    {"key": "pledge_ratio", "label": "质押率（质押券面值 / 融资金额）", "type": "number", "default": 1.00, "step": 0.01, "required": True},
]


def sample(seed: int | None = None) -> dict:
    return {
        "principal": 10000,
        "rate": 1.85,
        "start": "2026-11-02",
        "end": "2026-11-09",
        "day_count": "ACT/365",
        "fee_bp": 0,
        "pledge_ratio": 1.00,
    }


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def compute(data: dict) -> dict:
    principal = float(data["principal"])
    rate = float(data["rate"])
    start = data["start"]
    end = data["end"]
    basis = data["day_count"]
    fee_bp = float(data["fee_bp"])
    ratio = float(data["pledge_ratio"])

    if principal <= 0:
        raise ValueError("融资金额必须大于 0")
    if rate < 0:
        raise ValueError("回购利率不能为负")
    if end <= start:
        raise ValueError("到期日必须晚于起息日")
    if ratio <= 0:
        raise ValueError("质押率必须大于 0")

    days = (end - start).days
    year_fraction = bm.days_between(start, end, basis)
    interest = principal * rate / 100.0 * year_fraction
    fee = principal * fee_bp / 10000.0
    maturity = principal + interest - fee
    effective = (maturity / principal - 1) * 365.0 / days * 100.0
    collateral = principal / ratio
    leverage = 1.0 / ratio

    metrics = [
        {"label": "实际天数", "value": str(days), "unit": "天"},
        {"label": "回购利息", "value": _fmt(interest), "unit": "万元"},
        {"label": "费用", "value": _fmt(fee), "unit": "万元"},
        {"label": "到期金额", "value": _fmt(maturity), "unit": "万元"},
        {"label": "实际年化成本", "value": _fmt(effective, 4), "unit": "%"},
        {"label": "需要质押券面值", "value": _fmt(collateral), "unit": "万元"},
        {"label": "杠杆", "value": _fmt(leverage, 2), "unit": "倍"},
    ]

    rows = [
        {"date": start.isoformat(), "item": "融入资金", "amount": _fmt(principal)},
        {"date": end.isoformat(), "item": "到期还款", "amount": _fmt(-maturity)},
        {"date": end.isoformat(), "item": "其中：利息", "amount": _fmt(interest)},
        {"date": end.isoformat(), "item": "其中：费用", "amount": _fmt(fee)},
    ]
    tables = [{
        "title": "资金流水",
        "columns": [{"key": "date", "label": "日期"}, {"key": "item", "label": "项目"},
                    {"key": "amount", "label": "金额（万元）", "type": "number"}],
        "rows": rows,
    }]
    workbook = build_xlsx([{
        "name": "回购计算",
        "columns": [{"key": "item", "label": "项目", "width": 24},
                    {"key": "value", "label": "数值", "width": 18}],
        "rows": [{"item": metric["label"], "value": f"{metric['value']} {metric.get('unit','')}".strip()}
                 for metric in metrics],
    }])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": [],
        "download": {"name": "回购计算.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
