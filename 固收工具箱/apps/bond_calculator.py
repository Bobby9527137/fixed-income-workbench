# -*- coding: utf-8 -*-
"""债券计算器：净价/全价、YTM、久期、凸性、DV01、持有期情景。"""

from __future__ import annotations

import base64
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fi_toolbox import bondmath as bm
from fi_toolbox.app import run
from fi_toolbox.excel import build_xlsx

META = {
    "id": "bond_calculator",
    "name": "债券计算器",
    "desc": "净价 / 全价 / 应计利息 / YTM / 久期 / 凸性 / DV01 / 持有期情景",
    "port": 8514,
}

FIELDS = [
    {"key": "face", "label": "面值（每 100 元报价）", "type": "number", "default": 100, "step": 0.01, "required": True},
    {"key": "coupon", "label": "票面利率（%）", "type": "number", "default": 2.50, "step": 0.01, "required": True},
    {"key": "frequency", "label": "付息频率", "type": "select", "default": 1,
     "options": [{"value": 1, "label": "年付"}, {"value": 2, "label": "半年付"}, {"value": 4, "label": "季付"}]},
    {"key": "maturity", "label": "到期日", "type": "date", "default": "2036-10-15", "required": True},
    {"key": "settle", "label": "结算日", "type": "date", "default": "2026-11-02", "required": True},
    {"key": "day_count", "label": "计息基准", "type": "select", "default": "ACT/ACT",
     "options": [{"value": value, "label": value} for value in bm.BASIS_CHOICES]},
    {"key": "mode", "label": "计算方向", "type": "select", "default": "yield",
     "options": [{"value": "yield", "label": "按收益率算价格"}, {"value": "price", "label": "按净价算收益率"}],
     "hint": "选「按收益率算价格」时用下面的到期收益率；选「按净价算收益率」时用净价。"},
    {"key": "ytm", "label": "到期收益率（%）", "type": "number", "default": 2.30, "step": 0.01},
    {"key": "clean_price", "label": "净价（按净价算收益率时使用）", "type": "number", "default": 100.00, "step": 0.0001},
    {"key": "position", "label": "持仓面额（万元，用于 DV01 / 盈亏）", "type": "number", "default": 10000, "step": 1, "required": True},
    {"key": "horizon_days", "label": "持有天数", "type": "number", "default": 90, "step": 1, "integer": True},
    {"key": "funding_rate", "label": "资金成本（%）", "type": "number", "default": 1.80, "step": 0.01},
    {"key": "yield_change_bp", "label": "持有期收益率变动（bp）", "type": "number", "default": 0, "step": 0.1},
]


def sample(seed: int | None = None) -> dict:
    return {
        "face": 100,
        "coupon": 2.50,
        "frequency": 1,
        "maturity": "2036-10-15",
        "settle": "2026-11-02",
        "day_count": "ACT/ACT",
        "mode": "yield",
        "ytm": 2.30,
        "clean_price": 100.00,
        "position": 10000,
        "horizon_days": 90,
        "funding_rate": 1.80,
        "yield_change_bp": 0,
    }


def _fmt(value: float, digits: int = 4) -> str:
    return f"{value:,.{digits}f}"


def compute(data: dict) -> dict:
    face = float(data["face"])
    coupon = float(data["coupon"])
    frequency = int(data["frequency"])
    settle = data["settle"]
    maturity = data["maturity"]
    basis = data["day_count"]
    position = float(data["position"])

    if face <= 0:
        raise ValueError("面值必须大于 0")
    if coupon < 0:
        raise ValueError("票面利率不能为负")
    if settle >= maturity:
        raise ValueError("结算日必须早于到期日")

    warnings = []
    if data["mode"] == "price":
        clean_input = float(data["clean_price"])
        ytm = bm.ytm_from_clean(face, coupon, frequency, settle, maturity, clean_input, basis)
        price = bm.price_from_yield(face, coupon, frequency, settle, maturity, ytm, basis)
    else:
        ytm = float(data["ytm"]) / 100.0
        price = bm.price_from_yield(face, coupon, frequency, settle, maturity, ytm, basis)

    risk = bm.risk_metrics(face, coupon, frequency, settle, maturity, ytm, basis)
    carry = bm.carry_roll(
        face, coupon, frequency, settle, maturity, ytm,
        int(data["horizon_days"]), float(data["funding_rate"]) / 100.0,
        float(data["yield_change_bp"]), basis,
    )
    face_factor = position * 10000.0 / 100.0  # 每 100 元价格 -> 持仓金额

    metrics = [
        {"label": "净价", "value": _fmt(price["clean"]), "unit": "元"},
        {"label": "全价", "value": _fmt(price["dirty"]), "unit": "元"},
        {"label": "应计利息", "value": _fmt(price["accrued"]), "unit": "元"},
        {"label": "到期收益率", "value": _fmt(ytm * 100), "unit": "%"},
        {"label": "麦考利久期", "value": _fmt(risk["macaulay"]), "unit": "年"},
        {"label": "修正久期", "value": _fmt(risk["modified"]), "unit": "年"},
        {"label": "凸性", "value": _fmt(risk["convexity"]), "unit": ""},
        {"label": "DV01（每 100 元）", "value": _fmt(risk["dv01_per_100"]), "unit": "元"},
        {"label": "DV01（持仓）", "value": _fmt(risk["dv01_amount"] * face_factor / 10000.0, 2), "unit": "万元/bp"},
        {"label": "持有期票息", "value": _fmt(carry["coupon_income"] * face_factor / 10000.0, 2), "unit": "万元"},
        {"label": "资金成本", "value": _fmt(carry["funding_cost"] * face_factor / 10000.0, 2), "unit": "万元"},
        {"label": "价格损益（情景）", "value": _fmt(carry["price_pnl"] * face_factor / 10000.0, 2), "unit": "万元"},
        {"label": "持有期合计", "value": _fmt(carry["total_pnl"] * face_factor / 10000.0, 2), "unit": "万元"},
        {"label": "盈亏平衡收益率变动", "value": _fmt(carry["breakeven_bp"], 2), "unit": "bp"},
    ]

    flows = bm.cashflows(face, coupon, frequency, settle, maturity)
    flow_rows = []
    for day, amount, kind in flows:
        flow_rows.append({
            "date": day.isoformat(),
            "kind": kind,
            "amount": _fmt(amount),
            "position_amount": _fmt(amount * face_factor / 10000.0, 2),
        })

    tables = [{
        "title": "未来现金流",
        "columns": [
            {"key": "date", "label": "日期"},
            {"key": "kind", "label": "类型"},
            {"key": "amount", "label": "每 100 元", "type": "number"},
            {"key": "position_amount", "label": "持仓（万元）", "type": "number"},
        ],
        "rows": flow_rows,
        "note": f"结算日 {settle.isoformat()}，到期日 {maturity.isoformat()}；金额按面值 {face:g} 计算。",
    }]

    if settle == bm.coupon_schedule(maturity, frequency, settle)[0]:
        warnings.append("结算日恰好是付息日，应计利息按 0 处理。")

    sheet_metrics = [
        {"label": "净价", "value": _fmt(price["clean"])},
        {"label": "全价", "value": _fmt(price["dirty"])},
        {"label": "应计利息", "value": _fmt(price["accrued"])},
        {"label": "到期收益率(%)", "value": _fmt(ytm * 100)},
        {"label": "麦考利久期", "value": _fmt(risk["macaulay"])},
        {"label": "修正久期", "value": _fmt(risk["modified"])},
        {"label": "凸性", "value": _fmt(risk["convexity"])},
        {"label": "DV01(每100元)", "value": _fmt(risk["dv01_per_100"])},
        {"label": "DV01(持仓万元/bp)", "value": _fmt(risk["dv01_amount"] * face_factor / 10000.0, 2)},
        {"label": "持有期合计(万元)", "value": _fmt(carry["total_pnl"] * face_factor / 10000.0, 2)},
    ]
    workbook = build_xlsx([
        {"name": "指标", "columns": [{"key": "label", "label": "指标", "width": 26},
                                      {"key": "value", "label": "数值", "width": 18}],
         "rows": sheet_metrics},
        {"name": "现金流", "columns": [
            {"key": "date", "label": "日期", "width": 14},
            {"key": "kind", "label": "类型", "width": 10},
            {"key": "amount", "label": "每100元", "width": 14},
            {"key": "position_amount", "label": "持仓(万元)", "width": 16},
        ], "rows": flow_rows},
    ])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": warnings,
        "download": {"name": "债券计算.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
