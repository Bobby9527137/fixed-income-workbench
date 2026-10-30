"""债券数学：日期、现金流、定价、YTM、久期、凸性、DV01、持有期情景。

只依赖标准库。所有价格按「每 100 元面值」报价，和国内债券习惯一致。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List, Optional, Tuple

BASIS_CHOICES = ("ACT/ACT", "ACT/365", "ACT/360", "30/360")
FREQUENCY_CHOICES = (1, 2, 4)


class BondError(ValueError):
    """输入不合法或无法计算。"""


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise BondError("日期不能为空")
    text = text.replace("/", "-").replace(".", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise BondError(f"日期格式不对：{value}（应为 YYYY-MM-DD）") from exc


def add_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def coupon_schedule(maturity: date, frequency: int, settle: date) -> Tuple[date, List[date]]:
    """返回 (上一个付息日, [未来付息日...])，未来列表包含到期日。"""
    if frequency not in FREQUENCY_CHOICES:
        raise BondError(f"付息频率只能是 {FREQUENCY_CHOICES}")
    if settle >= maturity:
        raise BondError("结算日必须早于到期日")
    step = 12 // frequency
    future: List[date] = []
    current = maturity
    while current > settle:
        future.append(current)
        current = add_months(current, -step)
    future.reverse()
    return current, future


def days_between(start: date, end: date, basis: str = "ACT/ACT") -> float:
    if basis == "ACT/365":
        return (end - start).days / 365.0
    if basis == "ACT/360":
        return (end - start).days / 360.0
    if basis == "30/360":
        d1 = min(start.day, 30)
        d2 = min(end.day, 30)
        return (360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)) / 360.0
    # ACT/ACT 的通用近似：按实际天数 / 365.25
    return (end - start).days / 365.25


def _period_fraction(previous: date, nxt: date, settle: date) -> float:
    total = (nxt - previous).days
    if total <= 0:
        raise BondError("付息周期异常")
    return (settle - previous).days / total


def coupon_amount(face: float, coupon_rate: float, frequency: int) -> float:
    return face * coupon_rate / 100.0 / frequency


def accrued_interest(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
    basis: str = "ACT/ACT",
) -> float:
    if coupon_rate <= 0:
        return 0.0
    previous, future = coupon_schedule(maturity, frequency, settle)
    if not future:
        return 0.0
    if basis == "30/360":
        fraction = days_between(previous, settle, "30/360") / days_between(previous, future[0], "30/360")
    else:
        fraction = _period_fraction(previous, future[0], settle)
    return coupon_amount(face, coupon_rate, frequency) * max(0.0, fraction)


def cashflows(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
) -> List[Tuple[date, float, str]]:
    """未来现金流：[(日期, 金额, 类型)]，类型为「付息」或「兑付」。"""
    previous, future = coupon_schedule(maturity, frequency, settle)
    payment = coupon_amount(face, coupon_rate, frequency)
    rows: List[Tuple[date, float, str]] = []
    for index, day in enumerate(future, start=1):
        amount = payment
        kind = "付息"
        if day == maturity:
            amount += face
            kind = "兑付"
        rows.append((day, amount, kind))
    return rows


def _discount_exponents(
    frequency: int, settle: date, maturity: date, coupon_rate: float
) -> Tuple[List[date], List[float], float]:
    previous, future = coupon_schedule(maturity, frequency, settle)
    if coupon_rate <= 0:
        year_fraction = (maturity - settle).days / 365.0
        return [maturity], [year_fraction * frequency], 0.0
    # w = 距下一次付息还剩多少个付息周期（0~1）。
    # 结算日恰好是付息日时 w=1，第一笔现金流按完整一期折现。
    w = (future[0] - settle).days / (future[0] - previous).days
    w = min(1.0, max(0.0, w))
    exponents = [index - 1 + w for index in range(1, len(future) + 1)]
    return future, exponents, w


def dirty_price(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
    ytm: float,
    basis: str = "ACT/ACT",
) -> float:
    """按年化到期收益率 ytm（小数，如 0.023）计算全价。"""
    if frequency not in FREQUENCY_CHOICES:
        raise BondError(f"付息频率只能是 {FREQUENCY_CHOICES}")
    if ytm <= -1:
        raise BondError("到期收益率必须大于 -100%")
    dates, exponents, _ = _discount_exponents(frequency, settle, maturity, coupon_rate)
    payment = coupon_amount(face, coupon_rate, frequency)
    total = 0.0
    for day, exponent in zip(dates, exponents):
        amount = payment + (face if day == maturity else 0.0)
        # exponent 的单位是「付息周期」，所以直接用 (1+y/f)^exponent。
        total += amount / ((1 + ytm / frequency) ** exponent)
    return total


def price_from_yield(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
    ytm: float,
    basis: str = "ACT/ACT",
) -> dict:
    accrued = accrued_interest(face, coupon_rate, frequency, settle, maturity, basis)
    dirty = dirty_price(face, coupon_rate, frequency, settle, maturity, ytm, basis)
    return {
        "dirty": dirty,
        "clean": dirty - accrued,
        "accrued": accrued,
        "ytm": ytm,
    }


def ytm_from_clean(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
    clean_price: float,
    basis: str = "ACT/ACT",
) -> float:
    if clean_price <= 0:
        raise BondError("净价必须大于 0")
    accrued = accrued_interest(face, coupon_rate, frequency, settle, maturity, basis)
    target = clean_price + accrued

    low, high = -0.99, 2.0
    for _ in range(200):
        mid = (low + high) / 2
        value = dirty_price(face, coupon_rate, frequency, settle, maturity, mid, basis)
        if value > target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def risk_metrics(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
    ytm: float,
    basis: str = "ACT/ACT",
) -> dict:
    """用数值微分算修正久期、凸性、DV01。"""
    bump = 1e-4
    base = dirty_price(face, coupon_rate, frequency, settle, maturity, ytm, basis)
    up = dirty_price(face, coupon_rate, frequency, settle, maturity, ytm + bump, basis)
    down = dirty_price(face, coupon_rate, frequency, settle, maturity, ytm - bump, basis)
    modified = (down - up) / (2 * base * bump)
    convexity = (down + up - 2 * base) / (base * bump * bump)
    dv01_100 = (down - up) / 2.0
    return {
        "macaulay": modified * (1 + ytm / frequency),
        "modified": modified,
        "convexity": convexity,
        "dv01_per_100": dv01_100,
        "dv01_amount": dv01_100 * face / 100.0,
    }


def carry_roll(
    face: float,
    coupon_rate: float,
    frequency: int,
    settle: date,
    maturity: date,
    ytm: float,
    horizon_days: int,
    funding_rate: float,
    yield_change_bp: float,
    basis: str = "ACT/ACT",
) -> dict:
    """持有期情景：票息收入 - 资金成本 + 收益率变动带来的价格损益。"""
    if horizon_days < 0:
        raise BondError("持有天数不能为负")
    price_info = price_from_yield(face, coupon_rate, frequency, settle, maturity, ytm, basis)
    dirty = price_info["dirty"]
    risk = risk_metrics(face, coupon_rate, frequency, settle, maturity, ytm, basis)
    coupon_income = face * coupon_rate / 100.0 * horizon_days / 365.0
    funding_cost = dirty * face / 100.0 * funding_rate * horizon_days / 365.0
    price_pnl = -risk["modified"] * (yield_change_bp / 10000.0) * dirty * face / 100.0
    total = coupon_income - funding_cost + price_pnl
    denom = risk["modified"] * dirty * face / 100.0
    breakeven_bp = (coupon_income - funding_cost) / denom * 10000.0 if denom else 0.0
    return {
        "coupon_income": coupon_income,
        "funding_cost": funding_cost,
        "price_pnl": price_pnl,
        "total_pnl": total,
        "breakeven_bp": breakeven_bp,
        "dirty": dirty,
    }


def format_number(value: float, digits: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:,.{digits}f}"
