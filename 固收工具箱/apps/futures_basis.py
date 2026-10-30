# -*- coding: utf-8 -*-
"""国债期货基差 / IRR / DV01 对冲。"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fi_toolbox.app import run
from fi_toolbox.excel import build_xlsx

META = {
    "id": "futures_basis",
    "name": "国债期货基差",
    "desc": "CTD 基差、净基差、IRR、DV01 对冲手数",
    "port": 8518,
}

FIELDS = [
    {"key": "ctd_code", "label": "CTD 代码", "type": "text", "default": "250010.IB"},
    {"key": "ctd_clean", "label": "CTD 净价", "type": "number", "default": 101.2345, "step": 0.0001, "required": True},
    {"key": "ctd_accrued", "label": "CTD 应计利息", "type": "number", "default": 0.8500, "step": 0.0001, "required": True},
    {"key": "conversion_factor", "label": "转换因子 CF", "type": "number", "default": 0.9123, "step": 0.0001, "required": True},
    {"key": "futures_price", "label": "期货价格", "type": "number", "default": 111.2000, "step": 0.0001, "required": True},
    {"key": "ctd_dv01", "label": "CTD DV01（每 100 元）", "type": "number", "default": 0.0750, "step": 0.0001, "required": True},
    {"key": "repo_rate", "label": "资金利率（%）", "type": "number", "default": 1.80, "step": 0.01, "required": True},
    {"key": "days", "label": "距交割天数", "type": "number", "default": 30, "step": 1, "integer": True, "required": True},
    {"key": "coupon_income", "label": "持有期票息（每 100 元）", "type": "number", "default": 0.0, "step": 0.0001},
    {"key": "portfolio_dv01", "label": "组合 DV01（元/bp，可选）", "type": "number", "default": 0, "step": 1},
]


def sample(seed: int | None = None) -> dict:
    return {
        "ctd_code": "250010.IB",
        "ctd_clean": 101.2345,
        "ctd_accrued": 0.85,
        "conversion_factor": 0.9123,
        "futures_price": 111.20,
        "ctd_dv01": 0.075,
        "repo_rate": 1.80,
        "days": 30,
        "coupon_income": 0.0,
        "portfolio_dv01": 50000,
    }


def _fmt(value: float, digits: int = 4) -> str:
    return f"{value:,.{digits}f}"


def compute(data: dict) -> dict:
    clean = float(data["ctd_clean"])
    accrued = float(data["ctd_accrued"])
    cf = float(data["conversion_factor"])
    futures = float(data["futures_price"])
    ctd_dv01 = float(data["ctd_dv01"])
    repo = float(data["repo_rate"])
    days = int(data["days"])
    coupon_income = float(data["coupon_income"] or 0)
    portfolio_dv01 = float(data["portfolio_dv01"] or 0)

    if cf <= 0:
        raise ValueError("转换因子必须大于 0")
    if days <= 0:
        raise ValueError("距交割天数必须大于 0")
    if clean <= 0 or futures <= 0:
        raise ValueError("价格必须大于 0")

    invoice = futures * cf + accrued
    basis = clean - futures * cf
    funding = (clean + accrued) * repo / 100.0 * days / 365.0
    carry = coupon_income - funding
    net_basis = basis - carry
    coupon_cash = clean + accrued
    irr = (invoice + coupon_income - coupon_cash) / coupon_cash * 365.0 / days * 100.0
    futures_dv01 = ctd_dv01 / cf * 10000.0  # 合约面值 100 万 -> 每 100 元 * 10000
    lots = portfolio_dv01 / futures_dv01 if portfolio_dv01 and futures_dv01 else 0.0

    metrics = [
        {"label": "发票价格", "value": _fmt(invoice), "unit": "元"},
        {"label": "基差", "value": _fmt(basis), "unit": "元"},
        {"label": "持有收益", "value": _fmt(carry), "unit": "元"},
        {"label": "净基差", "value": _fmt(net_basis), "unit": "元"},
        {"label": "IRR", "value": _fmt(irr, 4), "unit": "%"},
        {"label": "期货 DV01", "value": _fmt(futures_dv01, 2), "unit": "元/bp/手"},
        {"label": "对冲手数", "value": _fmt(lots, 2), "unit": "手"},
    ]
    rows = [
        {"item": "CTD 净价", "value": _fmt(clean)},
        {"item": "CTD 应计", "value": _fmt(accrued)},
        {"item": "期货价格 × CF", "value": _fmt(futures * cf)},
        {"item": "基差", "value": _fmt(basis)},
        {"item": "资金成本", "value": _fmt(funding)},
        {"item": "票息收入", "value": _fmt(coupon_income)},
        {"item": "持有收益", "value": _fmt(carry)},
        {"item": "净基差", "value": _fmt(net_basis)},
        {"item": "IRR(%)", "value": _fmt(irr, 4)},
    ]
    tables = [{
        "title": "基差拆解",
        "columns": [{"key": "item", "label": "项目"}, {"key": "value", "label": "数值", "type": "number"}],
        "rows": rows,
    }]
    workbook = build_xlsx([{
        "name": "基差",
        "columns": [{"key": "item", "label": "项目", "width": 24},
                    {"key": "value", "label": "数值", "width": 18}],
        "rows": rows,
    }])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": [] if portfolio_dv01 else ["未填组合 DV01，未计算对冲手数。"],
        "download": {"name": "国债期货基差.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
