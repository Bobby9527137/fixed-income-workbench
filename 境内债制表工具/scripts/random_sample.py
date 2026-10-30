# -*- coding: utf-8 -*-
"""境内债制表的随机示例数据。

复用 ``make_mock_data`` 里的 35 / 52 列 schema 和默认值，只把每行的
日期、代码、简称、利率、规模、区域等换成随机值，并保留少量脏格式
（斜杠日期、中文日期、Excel 序列号、不带 % 的期限等），用来验证制表引擎。
"""

from __future__ import annotations

import io
import random
import re
from datetime import date, datetime, timedelta

import pandas as pd

from make_mock_data import CREDIT_COLUMNS, LOCAL_COLUMNS, _credit_row, _row

REGIONS = (
    ("江苏", "江苏省"),
    ("广东", "广东省"),
    ("浙江", "浙江省"),
    ("四川", "四川省"),
    ("山东", "山东省"),
    ("河南", "河南省"),
    ("湖北", "湖北省"),
    ("湖南", "湖南省"),
    ("安徽", "安徽省"),
    ("福建", "福建省"),
    ("江西", "江西省"),
    ("贵州", "贵州省"),
    ("陕西", "陕西省"),
    ("云南", "云南省"),
    ("宁波", "宁波市"),
    ("青岛", "青岛市"),
)

ISSUERS = (
    ("武清经开", "天津武清经济技术开发区有限公司", "天津市", "AA+", "城投", "中票"),
    ("杭州城建", "杭州市城市建设投资集团有限公司", "浙江省", "AAA", "城投", "中票"),
    ("苏州交投", "苏州交通投资集团有限责任公司", "江苏省", "AAA", "城投", "超短融"),
    ("成都高新", "成都高新投资集团有限公司", "四川省", "AAA", "城投", "中票"),
    ("宁波银行", "宁波银行股份有限公司", "浙江省", "AAA", "金融", "商业银行债"),
    ("中石化", "中国石油化工股份有限公司", "北京市", "AAA", "产业", "超短融"),
    ("江苏交通", "江苏交通控股有限公司", "江苏省", "AAA", "产业", "超短融"),
    ("绍兴城投", "绍兴市城市建设投资集团有限公司", "浙江省", "AA+", "城投", "中票"),
)

UNDERWRITERS = ("工商银行、中信证券", "建设银行、国泰君安", "农业银行、招商证券",
                "中国银行、中信建投", "江苏银行、南京证券")
USES = ("项目建设", "偿还到期债务", "补充流动资金", "补充营运资金", "市政基础设施建设")

LOCAL_TENORS = ("3Y", "5Y", "7Y", "10Y", "20Y", "30Y", "3", "5年", "10年")
CREDIT_TENORS = ("1", "3Y", "5", "0.74", "2Y", "5+N年", "3年")
RATINGS = ("AAA", "AAA", "AA+", "AA+", "AA")


def _dirty_date(rng: random.Random, day: date):
    style = rng.choice(("iso", "slash", "cn", "serial", "dt", "iso"))
    if style == "slash":
        return f"{day.year}/{day.month}/{day.day}"
    if style == "cn":
        return f"{day.year}年{day.month}月{day.day}日"
    if style == "serial":
        return (day - date(1899, 12, 30)).days
    if style == "dt":
        return datetime(day.year, day.month, day.day)
    return day.isoformat()


def _tenor_years(tenor: str) -> int:
    match = re.match(r"(\d+)", tenor)
    return int(match.group(1)) if match else 5


def _local_rows(rng: random.Random, count: int) -> list[dict]:
    rows = []
    base = date(2026, 10, 1)
    for index in range(count):
        region_short, region_full = rng.choice(REGIONS)
        tender = base + timedelta(days=rng.randint(0, 45))
        tenor = rng.choice(LOCAL_TENORS)
        years = _tenor_years(tenor)
        rate = round(rng.uniform(1.85, 3.15), 2)
        amount = round(rng.uniform(10, 200), 1)
        year_code = rng.choice(("24", "25", "26"))
        rows.append(_row({
            "招标日": _dirty_date(rng, tender),
            "招标时间": f"{rng.randint(9, 15)}:{rng.choice(('00', '30'))}-"
                        f"{rng.randint(10, 16)}:{rng.choice(('10', '40'))}",
            "招标场所": rng.choice(("中央国债登记结算有限责任公司", "银行间")),
            "债券代码": f"{rng.randint(1000000, 9999999)}.IB",
            "债券简称": f"{year_code}{region_short}债{rng.randint(1, 40):02d}",
            "类型": rng.choice(("专项", "一般")),
            "性质": rng.choice(("新增", "置换", "再融资")),
            "期限": tenor,
            "发行量(亿元)": amount,
            "中标利率": rate,
            "首发票面": rate,
            "相似二级券": f"2{rng.randint(3, 5)}国开{rng.randint(1, 20):02d}",
            "相似二级剩余期限": f"{max(0.3, years - 0.2):.2f}年",
            "相似二级估值": round(rate + rng.uniform(-0.05, 0.08), 2),
            "一二级利差(BP)": round(rng.uniform(-2, 8), 1),
            "中债5日均值(%)": round(rate + rng.uniform(-0.03, 0.03), 2),
            "财政部5日均值(%)": round(rate + rng.uniform(-0.05, 0.02), 2),
            "加点(bp)": rng.choice((0, 3, 5, 8)),
            "中债国债利差(bp)": round(rng.uniform(10, 40), 1),
            "财政部国债利差(bp)": round(rng.uniform(9, 38), 1),
            "投标下限(%)": round(rate - rng.uniform(0.10, 0.25), 2),
            "投标上限(%)": round(rate + rng.uniform(0.10, 0.25), 2),
            "手续费(%)": 0.01,
            "承销费(BP)": round(rng.uniform(0.05, 0.2), 2),
            "综合收益率(%)": round(rate + rng.uniform(-0.01, 0.02), 2),
            "缴款日": _dirty_date(rng, tender + timedelta(days=rng.randint(1, 4))),
            "上市日": _dirty_date(rng, tender + timedelta(days=rng.randint(5, 10))),
            "全场倍数": round(rng.uniform(2, 35), 2),
            "边际倍数": round(rng.uniform(1.0, 3.5), 2),
            "参考久期": round(max(0.2, years * rng.uniform(0.75, 0.95)), 2),
            "承销团": rng.choice(UNDERWRITERS),
            "募集资金用途": rng.choice(USES),
            "债券全称": f"{tender.year}年{region_full}政府{'专项' if index % 2 == 0 else '一般'}债券"
                        f"（{rng.randint(1, 30)}期）",
            "到期日": f"{tender.year + years}年{tender.month}月{tender.day}日",
            "区域名称": region_full,
        }))
    return rows


def _credit_rows(rng: random.Random, count: int) -> list[dict]:
    rows = []
    base = date(2026, 10, 1)
    for index in range(count):
        short, full, region, rating, issuer_type, kind = rng.choice(ISSUERS)
        start = base + timedelta(days=rng.randint(0, 45))
        tenor = rng.choice(CREDIT_TENORS)
        years = _tenor_years(tenor)
        plan = round(rng.uniform(5, 40), 1)
        actual = None if rng.random() < 0.4 else round(plan * rng.uniform(0.8, 1.3), 1)
        rate = round(rng.uniform(1.7, 3.4), 2)
        year_code = rng.choice(("25", "26"))
        debt_rating = None if rng.random() < 0.3 else rng.choice(RATINGS)
        rows.append(_credit_row({
            "债券简称": f"{year_code}{short}{kind}{rng.randint(1, 9):02d}",
            "截标时间": rng.choice((
                f"{start.year}-{start.month:02d}-{start.day:02d} "
                f"{rng.randint(9, 17)}:{rng.choice(('00', '30'))}",
                f"{start.month}-{start.day} {rng.randint(9, 17)}:{rng.choice(('00', '30'))}",
                datetime(start.year, start.month, start.day,
                         rng.randint(9, 17), rng.choice((0, 30))),
            )),
            "债券代码": f"{rng.randint(100000000, 999999999)}.IB",
            "发行期限": tenor,
            "计划发行(亿)": plan,
            "实际发行(亿)": actual,
            "投标区间(%)": f"{round(rate - 0.2, 1)}-{round(rate + 0.4, 1)}" if rng.random() < 0.35 else None,
            "票面利率(%)": rate,
            "国债利差(bp)": round(rng.uniform(20, 120), 1),
            "相似二级券": f"{year_code}{short}{kind}{rng.randint(1, 9):02d}",
            "相似二级剩余期限": f"{max(0.2, years - 0.3):.2f}年",
            "相似二级估值": round(rate + rng.uniform(-0.05, 0.10), 2),
            "相似二级bid/ofr": f"{round(rate - 0.01, 2)}/{round(rate + 0.01, 2)}",
            "发行人": full,
            "发行人流动性": rng.choice(("好", "一般", "较好")),
            "发行起始日": _dirty_date(rng, start),
            "招标时间": f"{rng.randint(9, 16)}:{rng.choice(('00', '30'))}",
            "最新边际": round(rate + rng.uniform(-0.05, 0.05), 2),
            "起息日": _dirty_date(rng, start + timedelta(days=rng.randint(1, 4))),
            "全场倍数": round(rng.uniform(1.2, 6.5), 2),
            "边际倍数": round(rng.uniform(1.0, 4.0), 2),
            "YY评分": rng.choice((2, 3, 4, 5, None)),
            "yy定价": round(rate + rng.uniform(-0.05, 0.05), 2),
            "主体评级": rating,
            "债项评级": debt_rating,
            "区域": region,
            "募集资金用途": rng.choice(USES),
            "主承销商": rng.choice(UNDERWRITERS),
            "债券类型": kind,
            "发行人类型": rng.choice(("国企", "央企", "地方国企", "城投")),
            "债券全称": f"{full}{start.year}年度第{rng.randint(1, 9)}期{kind}",
            "实际到期日": (start + timedelta(days=365 * years)).isoformat(),
            "上市日": _dirty_date(rng, start + timedelta(days=rng.randint(8, 16))),
            "公告日": _dirty_date(rng, start - timedelta(days=rng.randint(3, 10))),
            "缴款日": _dirty_date(rng, start + timedelta(days=rng.randint(2, 6))),
            "板块分类": rng.choice(("城投", "产业", "金融")),
            "DM评分": round(rng.uniform(1.5, 5.0), 1),
            "团费(%)": round(rng.uniform(0.02, 0.08), 2),
            "发行截止日": (start + timedelta(days=rng.randint(1, 3))).isoformat(),
        }))
    return rows


def _workbook(rows: list[dict], columns: list[str], sheet: str) -> bytes:
    buffer = io.BytesIO()
    frame = pd.DataFrame(rows, columns=columns)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet)
    return buffer.getvalue()


def make_demo(seed: int | None = None) -> list[tuple[str, bytes]]:
    """返回 ``[(文件名, xlsx 字节), …]``，文件名带债种便于自动识别。"""
    rng = random.Random(seed)
    files: list[tuple[str, bytes]] = []

    if rng.random() < 0.5:
        rows = _local_rows(rng, rng.randint(3, 6))
        files.append((
            f"随机示例_地方债_{rng.randint(1000, 9999)}.xlsx",
            _workbook(rows, LOCAL_COLUMNS, "地方债随机"),
        ))

    if not files or rng.random() < 0.7:
        rows = _credit_rows(rng, rng.randint(3, 6))
        files.append((
            f"随机示例_信用债_{rng.randint(1000, 9999)}.xlsx",
            _workbook(rows, CREDIT_COLUMNS, "信用债随机"),
        ))

    return files
