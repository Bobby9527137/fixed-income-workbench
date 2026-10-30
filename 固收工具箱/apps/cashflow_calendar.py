# -*- coding: utf-8 -*-
"""持仓现金流 / 付息日历。"""

from __future__ import annotations

import base64
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fi_toolbox import bondmath as bm
from fi_toolbox.app import run
from fi_toolbox.excel import build_xlsx

META = {
    "id": "cashflow_calendar",
    "name": "现金流/付息日历",
    "desc": "从持仓表生成未来付息、兑付、应计利息和年度汇总",
    "port": 8516,
}

HOLDING_COLUMNS = [
    {"key": "code", "label": "代码", "type": "text", "width": 14},
    {"key": "name", "label": "名称", "type": "text", "width": 20},
    {"key": "face", "label": "面额(万元)", "type": "number", "width": 14},
    {"key": "coupon", "label": "票面(%)", "type": "number", "width": 10},
    {"key": "frequency", "label": "频率", "type": "number", "width": 8},
    {"key": "maturity", "label": "到期日", "type": "date", "width": 14},
    {"key": "next_coupon", "label": "下次付息日(可空)", "type": "date", "width": 16},
]

FIELDS = [
    {"key": "start", "label": "统计开始日", "type": "date", "default": "2026-11-01", "required": True},
    {"key": "end", "label": "统计结束日", "type": "date", "default": "2035-12-31", "required": True},
    {"key": "basis", "label": "计息基准", "type": "select", "default": "ACT/ACT",
     "options": [{"value": value, "label": value} for value in bm.BASIS_CHOICES]},
    {"key": "holdings", "label": "持仓", "type": "table", "columns": HOLDING_COLUMNS, "min_rows": 1,
     "default_rows": [
         {"code": "2405253.IB", "name": "24浙江债07", "face": 5000, "coupon": 2.36, "frequency": 1,
          "maturity": "2034-06-05", "next_coupon": "2027-06-05"},
     ]},
]


def sample(seed: int | None = None) -> dict:
    return {
        "start": "2026-11-01",
        "end": "2035-12-31",
        "basis": "ACT/ACT",
        "holdings": [
            {"code": "2405253.IB", "name": "24浙江债07", "face": 5000, "coupon": 2.36,
             "frequency": 1, "maturity": "2034-06-05", "next_coupon": "2027-06-05"},
            {"code": "102683905.IB", "name": "26上饶产投MTN001", "face": 3000, "coupon": 2.05,
             "frequency": 1, "maturity": "2029-10-29", "next_coupon": ""},
            {"code": "212480001.IB", "name": "26宁波银行债01", "face": 2000, "coupon": 1.95,
             "frequency": 1, "maturity": "2029-09-28", "next_coupon": ""},
        ],
    }


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _next_coupon(holding: dict, start) -> tuple:
    maturity = holding["maturity"]
    frequency = int(holding["frequency"] or 1)
    explicit = holding.get("next_coupon")
    if explicit:
        current = explicit
        if current <= start:
            step = 12 // frequency
            while current <= start:
                current = bm.add_months(current, step)
        return current
    if maturity <= start:
        return None
    _previous, future = bm.coupon_schedule(maturity, frequency, start)
    return future[0] if future else None


def compute(data: dict) -> dict:
    start = data["start"]
    end = data["end"]
    if end <= start:
        raise ValueError("统计结束日必须晚于开始日")

    rows = []
    warnings = []
    annual = defaultdict(lambda: {"coupon": 0.0, "principal": 0.0})
    total_coupon = 0.0
    total_principal = 0.0

    for index, holding in enumerate(data["holdings"], start=1):
        code = holding.get("code") or f"第{index}行"
        name = holding.get("name") or ""
        face = holding.get("face")
        coupon = holding.get("coupon")
        frequency = holding.get("frequency")
        maturity = holding.get("maturity")
        if not face or not maturity or coupon is None or not frequency:
            warnings.append(f"{code}：面额/票面/频率/到期日不完整，已跳过")
            continue
        face = float(face)
        coupon = float(coupon)
        frequency = int(frequency)
        if face <= 0:
            warnings.append(f"{code}：面额必须大于 0，已跳过")
            continue
        if frequency not in (1, 2, 4):
            warnings.append(f"{code}：付息频率只能是 1/2/4，已跳过")
            continue
        if maturity <= start:
            warnings.append(f"{code}：到期日早于统计开始日，已跳过")
            continue

        if coupon <= 0:
            if start <= maturity <= end:
                annual[maturity.year]["principal"] += face
                total_principal += face
                rows.append({"date": maturity.isoformat(), "code": code, "name": name,
                             "kind": "兑付", "amount": _fmt(face), "note": "零息"})
            continue

        current = _next_coupon(holding, start)
        if current is None:
            warnings.append(f"{code}：无法推算下次付息日，已跳过")
            continue
        step = 12 // frequency
        payment = face * coupon / 100.0 / frequency
        while current <= end and current <= maturity:
            amount = payment
            kind = "付息"
            if current == maturity:
                amount += face
                kind = "付息+兑付"
            annual[current.year]["coupon"] += payment
            if current == maturity:
                annual[current.year]["principal"] += face
            total_coupon += payment
            if current == maturity:
                total_principal += face
            rows.append({"date": current.isoformat(), "code": code, "name": name,
                         "kind": kind, "amount": _fmt(amount), "note": ""})
            current = bm.add_months(current, step)

    rows.sort(key=lambda item: (item["date"], item["code"]))
    annual_rows = []
    grand_total = 0.0
    for year in sorted(annual):
        item = annual[year]
        total = item["coupon"] + item["principal"]
        grand_total += total
        annual_rows.append({"year": str(year), "coupon": _fmt(item["coupon"]),
                            "principal": _fmt(item["principal"]), "total": _fmt(total)})

    metrics = [
        {"label": "现金流笔数", "value": str(len(rows)), "unit": "笔"},
        {"label": "票息合计", "value": _fmt(total_coupon), "unit": "万元"},
        {"label": "本金兑付", "value": _fmt(total_principal), "unit": "万元"},
        {"label": "合计", "value": _fmt(total_coupon + total_principal), "unit": "万元"},
    ]
    tables = [
        {"title": "未来现金流", "columns": [
            {"key": "date", "label": "日期"}, {"key": "code", "label": "代码"},
            {"key": "name", "label": "名称"}, {"key": "kind", "label": "类型"},
            {"key": "amount", "label": "金额（万元）", "type": "number"},
            {"key": "note", "label": "备注"},
        ], "rows": rows},
        {"title": "年度汇总", "columns": [
            {"key": "year", "label": "年份"}, {"key": "coupon", "label": "票息（万元）", "type": "number"},
            {"key": "principal", "label": "本金（万元）", "type": "number"},
            {"key": "total", "label": "合计（万元）", "type": "number"},
        ], "rows": annual_rows},
    ]
    workbook = build_xlsx([
        {"name": "现金流", "columns": [
            {"key": "date", "label": "日期", "width": 14}, {"key": "code", "label": "代码", "width": 16},
            {"key": "name", "label": "名称", "width": 24}, {"key": "kind", "label": "类型", "width": 12},
            {"key": "amount", "label": "金额(万元)", "width": 14}, {"key": "note", "label": "备注", "width": 16},
        ], "rows": rows},
        {"name": "年度汇总", "columns": [
            {"key": "year", "label": "年份", "width": 10}, {"key": "coupon", "label": "票息(万元)", "width": 14},
            {"key": "principal", "label": "本金(万元)", "width": 14}, {"key": "total", "label": "合计(万元)", "width": 14},
        ], "rows": annual_rows},
    ])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": warnings,
        "download": {"name": "现金流日历.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
