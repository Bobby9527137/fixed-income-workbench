# -*- coding: utf-8 -*-
"""交易要素提取：把聊天/邮件里的债券交易文本整理成结构化台账。"""

from __future__ import annotations

import base64
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fi_toolbox.app import run
from fi_toolbox.excel import build_xlsx

META = {
    "id": "trade_extract",
    "name": "交易要素提取",
    "desc": "把交易聊天文本整理成结构化台账，并导出 Excel",
    "port": 8520,
}

FIELDS = [
    {"key": "text", "label": "交易文本（一行一笔）", "type": "textarea", "rows": 10,
     "placeholder": "买入 102683905.IB 26上饶产投MTN001 5000万 2.35% T+1 江城银行",
     "required": True},
]

SAMPLE_TEXT = """买入 102683905.IB 26上饶产投MTN001 5000万 2.35% T+1 江城银行
卖出 102683800.IB 26杭州城建MTN002 3000万 净价100.12 T+0 龙头证券
买入 26宁波银行债01 2000万 1.95% T+1 华信信托
卖出 102280012.IB 26杭城投MTN002 1500万 净价100.45 T+2 中金基金
买入 012480090.IB 26中石化SCP004 8000万 2.00% T+0 国泰保险资管"""

CODE_RE = re.compile(r"(?<![A-Za-z0-9])(\d{6,9})(?:\.(IB|SH|SZ|BJ))?(?![A-Za-z0-9])", re.IGNORECASE)
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万亿|亿元|亿|万元|万)")
PRICE_RE = re.compile(r"(?:净价|价格)\s*[:：]?\s*(\d+(?:\.\d+)?)")
YIELD_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
SETTLE_RE = re.compile(r"\bT\s*\+\s*\d+\b|\b\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?\b", re.IGNORECASE)
CP_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,20}(?:农商行|城商行|银行|证券|基金|信托|资管|保险))")
NAME_RE = re.compile(r"\d{2}(?=[\u4e00-\u9fa5A-Za-z0-9]*[\u4e00-\u9fa5])[\u4e00-\u9fa5A-Za-z0-9]+")


def sample(seed: int | None = None) -> dict:
    return {"text": SAMPLE_TEXT}


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _parse_line(raw: str, index: int) -> dict:
    line = unicodedata.normalize("NFKC", raw).strip()
    line = re.sub(r"\s+", " ", line)
    row = {
        "direction": "", "code": "", "name": "", "amount": "", "yield": "",
        "price": "", "settlement": "", "counterparty": "", "raw": raw.strip(),
        "warnings": [],
    }
    if not line:
        return row

    direction = ""
    if re.search(r"买入|买", line):
        direction = "买入"
    elif re.search(r"卖出|卖", line):
        direction = "卖出"
    row["direction"] = direction

    code_match = CODE_RE.search(line)
    if code_match:
        row["code"] = code_match.group(1) + (("." + code_match.group(2).upper()) if code_match.group(2) else "")
        line = line[: code_match.start()] + " " + line[code_match.end():]

    amount_match = AMOUNT_RE.search(line)
    if amount_match:
        value = float(amount_match.group(1))
        unit = amount_match.group(2)
        amount = value * 10000 if unit in ("亿", "亿元", "万亿") else value
        if unit == "万亿":
            amount = value * 100000000
        row["amount"] = _fmt(amount)
        line = line[: amount_match.start()] + " " + line[amount_match.end():]

    price_match = PRICE_RE.search(line)
    if price_match:
        row["price"] = price_match.group(1)
        line = line[: price_match.start()] + " " + line[price_match.end():]

    yield_match = YIELD_RE.search(line)
    if yield_match:
        row["yield"] = yield_match.group(1)
        line = line[: yield_match.start()] + " " + line[yield_match.end():]

    settle_match = SETTLE_RE.search(line)
    if settle_match:
        row["settlement"] = settle_match.group(0).replace(" ", "")
        line = line[: settle_match.start()] + " " + line[settle_match.end():]

    # 先认债券简称，再认对手方：避免「26宁波银行债01」里的“银行”被当成对手方。
    name_matches = list(NAME_RE.finditer(line))
    if name_matches:
        best = max(name_matches, key=lambda match: len(match.group(0)))
        row["name"] = best.group(0)
        line = line[: best.start()] + " " + line[best.end():]

    for cp_match in CP_RE.finditer(line):
        if cp_match.start() > 0 and line[cp_match.start() - 1].isdigit():
            continue
        row["counterparty"] = cp_match.group(1)
        break

    if not row["code"] and not row["name"]:
        row["warnings"].append("没有认出债券代码/简称")
    if not row["amount"]:
        row["warnings"].append("没有认出金额")
    if not row["direction"]:
        row["warnings"].append("没有认出买入/卖出")
    return row


def compute(data: dict) -> dict:
    text = str(data.get("text") or "")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("请至少粘贴一行交易文本")

    rows = [_parse_line(line, index) for index, line in enumerate(lines, start=1)]
    warnings = []
    for row in rows:
        for warning in row["warnings"]:
            warnings.append(f"第 {rows.index(row) + 1} 行：{warning}")

    buy_total = sum(float(row["amount"].replace(",", "")) for row in rows
                    if row["direction"] == "买入" and row["amount"])
    sell_total = sum(float(row["amount"].replace(",", "")) for row in rows
                     if row["direction"] == "卖出" and row["amount"])
    parsed = sum(1 for row in rows if row["code"] or row["name"])
    metrics = [
        {"label": "文本行数", "value": str(len(rows)), "unit": "行"},
        {"label": "识别成功", "value": str(parsed), "unit": "行"},
        {"label": "买入合计", "value": _fmt(buy_total), "unit": "万元"},
        {"label": "卖出合计", "value": _fmt(sell_total), "unit": "万元"},
        {"label": "净买入", "value": _fmt(buy_total - sell_total), "unit": "万元"},
    ]
    display_rows = []
    for row in rows:
        display_rows.append({
            "direction": row["direction"], "code": row["code"], "name": row["name"],
            "amount": row["amount"], "yield": row["yield"], "price": row["price"],
            "settlement": row["settlement"], "counterparty": row["counterparty"],
            "raw": row["raw"],
        })
    tables = [{
        "title": "交易台账",
        "columns": [
            {"key": "direction", "label": "方向"}, {"key": "code", "label": "代码"},
            {"key": "name", "label": "名称"}, {"key": "amount", "label": "金额(万元)", "type": "number"},
            {"key": "yield", "label": "收益率(%)", "type": "number"},
            {"key": "price", "label": "净价", "type": "number"},
            {"key": "settlement", "label": "结算"}, {"key": "counterparty", "label": "对手方"},
            {"key": "raw", "label": "原文"},
        ],
        "rows": display_rows,
        "note": "金额统一换算成万元；收益率和净价按原文识别，未做取舍。",
    }]
    workbook = build_xlsx([{
        "name": "交易台账",
        "columns": [
            {"key": "direction", "label": "方向", "width": 8}, {"key": "code", "label": "代码", "width": 16},
            {"key": "name", "label": "名称", "width": 24}, {"key": "amount", "label": "金额(万元)", "width": 14},
            {"key": "yield", "label": "收益率(%)", "width": 12}, {"key": "price", "label": "净价", "width": 10},
            {"key": "settlement", "label": "结算", "width": 10}, {"key": "counterparty", "label": "对手方", "width": 18},
            {"key": "raw", "label": "原文", "width": 50},
        ], "rows": display_rows,
    }])
    return {
        "metrics": metrics,
        "tables": tables,
        "warnings": warnings,
        "download": {"name": "交易台账.xlsx", "base64": base64.b64encode(workbook).decode("ascii")},
    }


if __name__ == "__main__":
    raise SystemExit(run(META, FIELDS, compute, sample))
