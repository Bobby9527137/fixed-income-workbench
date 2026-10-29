"""境内债制表：25 类输入材料的验收矩阵。

每个用例写一个 xlsx → load_tasks → convert_dataframe，
断言目标 11 列、关键字段取值、行序与播报文本。

运行：
    <streamlit venv python> scripts/acceptance/bondtable_matrix.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT.parent / "境内债制表工具"
sys.path.insert(0, str(TOOL / "scripts"))

import bondtable  # noqa: E402

CONFIG = bondtable.load_config()
TMP = Path(tempfile.mkdtemp(prefix="wb-accept-bondtable-"))

LOCAL_HEADERS = CONFIG["bond_types"]["地方债"]["source_headers"]
CREDIT_HEADERS = CONFIG["bond_types"]["信用债"]["source_headers"]
LOCAL_TARGET = CONFIG["bond_types"]["地方债"]["target_headers"]
CREDIT_TARGET = CONFIG["bond_types"]["信用债"]["target_headers"]


def local_row(**over):
    row = {
        "招标日": "2026-10-13",
        "招标时间": "9:30",
        "招标场所": "中央国债登记结算有限责任公司",
        "债券代码": "2600101",
        "债券简称": "26广东债47",
        "类型": "专项",
        "性质": "新增",
        "期限": "5",
        "发行量(亿元)": 90.1234,
        "中标利率": 2.15,
        "首发票面": None,
        "相似二级券": None,
        "相似二级剩余期限": None,
        "相似二级估值": None,
        "一二级利差(BP)": None,
        "中债5日均值(%)": None,
        "财政部5日均值(%)": None,
        "加点(bp)": None,
        "中债国债利差(bp)": None,
        "财政部国债利差(bp)": None,
        "投标下限(%)": None,
        "投标上限(%)": None,
        "手续费(%)": None,
        "承销费(BP)": None,
        "综合收益率(%)": None,
        "缴款日": "2026-10-15",
        "上市日": "2026-10-16",
        "全场倍数": None,
        "边际倍数": None,
        "参考久期": None,
        "承销团": None,
        "募集资金用途": "交通基础设施",
        "债券全称": "2026年广东省政府专项债券（四十七期）",
        "到期日": "2031-10-16",
        "区域名称": "广东省",
    }
    row.update(over)
    return row


def credit_row(**over):
    row = {h: None for h in CREDIT_HEADERS}
    row.update(
        {
            "债券简称": "26武清经开MTN007",
            "截标时间": "2026-10-12 17:00",
            "债券代码": "102601234",
            "发行期限": "2",
            "计划发行(亿)": 1.5,
            "实际发行(亿)": 1.5,
            "投标区间(%)": "1.3-2.3",
            "主体评级": "AA+",
            "债项评级": "AA+",
            "发行人": "天津武清经济技术开发区有限公司",
            "YY评分": "4",
            "发行起始日": "2026-10-14",
            "招标时间": "17:00",
            "缴款日": "2026-10-15",
            "公告日": "2026-10-10",
        }
    )
    row.update(over)
    return row


def write_book(rows, filename, sheet="Sheet1", title_rows=0):
    path = TMP / filename
    frame = pd.DataFrame(rows, columns=list(rows[0].keys()))
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if title_rows:
            pad = pd.DataFrame([["标题"] + [None] * (len(frame.columns) - 1)] * title_rows)
            pad.to_excel(writer, sheet_name=sheet, header=False, index=False)
            frame.to_excel(writer, sheet_name=sheet, index=False, startrow=title_rows)
        else:
            frame.to_excel(writer, sheet_name=sheet, index=False)
    return path


def convert(path, sheet):
    tasks = bondtable.load_tasks(str(path), CONFIG)
    for bond_type, sheet_name, df in tasks:
        if sheet_name == sheet:
            return bond_type, bondtable.convert_dataframe(df, CONFIG, bond_type)
    raise AssertionError(f"没有读到工作表 {sheet}")


def check(name, path, sheet, *, bond_type, expects, warnings_expect=0, text_check=None):
    try:
        detected, (df, warnings) = convert(path, sheet)
        assert detected == bond_type, f"债种识别 {detected} != {bond_type}"
        assert list(df.columns) == (
            LOCAL_TARGET if bond_type == "地方债" else CREDIT_TARGET
        ), f"目标列不对：{list(df.columns)}"
        assert len(warnings) == warnings_expect, f"警告数 {len(warnings)}：{warnings}"
        for row_idx, col, expected in expects:
            actual = df.iloc[row_idx][col]
            if isinstance(expected, float):
                assert abs(float(actual) - expected) < 1e-6, f"{col} 行{row_idx}: {actual!r} != {expected!r}"
            else:
                assert str(actual) == str(expected), f"{col} 行{row_idx}: {actual!r} != {expected!r}"
        if text_check:
            text = (
                bondtable.make_local_text(df)
                if bond_type == "地方债"
                else bondtable.make_credit_text(df)
            )
            for needle in text_check:
                assert needle in text, f"播报缺少 {needle!r}：\n{text}"
        return {"case": name, "ok": True, "detail": f"{bond_type} / {len(df)} 行 / {len(warnings)} 警告"}
    except Exception as exc:  # noqa: BLE001
        return {"case": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def main():
    results = []
    base = [local_row(), local_row(债券简称="26江苏债12", 债券代码="2600202", 期限="10", **{"发行量(亿元)": 120.5})]

    # 1 基线
    p = write_book(base, "地方债_基线.xlsx")
    results.append(check("1 地方债基线", p, "Sheet1", bond_type="地方债", expects=[
        (0, "发行日", "2026-10-13"), (0, "发行时间", "09:30"), (0, "期限", "5Y"),
        (0, "发行量(亿)", 90.1234), (0, "缴款日", "2026-10-15"),
    ], text_check=["广东90.1234亿", "5Y"]))

    # 2 标题行
    p = write_book(base, "地方债_标题行.xlsx", title_rows=1)
    results.append(check("2 表头上方有标题行", p, "Sheet1", bond_type="地方债", expects=[(0, "债券简称", "26广东债47")]))

    # 3 两行标题
    p = write_book(base, "地方债_两行标题.xlsx", title_rows=2)
    results.append(check("3 表头上方两行标题", p, "Sheet1", bond_type="地方债", expects=[(0, "发行日", "2026-10-13")]))

    # 4 列顺序打乱
    shuffled = {k: base[0][k] for k in reversed(list(base[0].keys()))}
    p = write_book([shuffled], "地方债_列乱序.xlsx")
    results.append(check("4 源列顺序打乱", p, "Sheet1", bond_type="地方债", expects=[(0, "债券代码", "2600101")]))

    # 5 多余列
    extra = [dict(r, **{"备注": "x", "来源": "DM"}) for r in base]
    p = write_book(extra, "地方债_多余列.xlsx")
    results.append(check("5 多余未知列", p, "Sheet1", bond_type="地方债", expects=[(0, "债券简称", "26广东债47")]))

    # 6 datetime 日期
    p = write_book([local_row(招标日=datetime(2026, 10, 13), 缴款日=date(2026, 10, 15), 上市日=date(2026, 10, 16))],
                   "地方债_datetime.xlsx")
    results.append(check("6 日期为 datetime 单元格", p, "Sheet1", bond_type="地方债", expects=[
        (0, "发行日", "2026-10-13"), (0, "缴款日", "2026-10-15")]))

    # 7 斜杠日期
    p = write_book([local_row(招标日="2026/9/4", 缴款日="2026.10.8", 上市日="2026年10月9日")],
                   "地方债_斜杠日期.xlsx")
    results.append(check("7 日期写成斜杠/点/中文", p, "Sheet1", bond_type="地方债", expects=[
        (0, "发行日", "2026-09-04"), (0, "缴款日", "2026-10-08"), (0, "上市日", "2026-10-09")]))

    # 8 Excel 序列号
    serial = (datetime(2026, 10, 13) - datetime(1899, 12, 30)).days
    p = write_book([local_row(招标日=serial)], "地方债_序列号.xlsx")
    results.append(check("8 日期为 Excel 序列号", p, "Sheet1", bond_type="地方债", expects=[(0, "发行日", "2026-10-13")]))

    # 9 缺失缴款/上市
    p = write_book([local_row(缴款日=None, 上市日=None)], "地方债_缺日期.xlsx")
    results.append(check("9 缴款日/上市日为空", p, "Sheet1", bond_type="地方债", expects=[
        (0, "缴款日", ""), (0, "上市日", "")]))

    # 10 金额千分位
    p = write_book([local_row(**{"发行量(亿元)": "1,200.50"})], "地方债_金额千分位.xlsx")
    results.append(check("10 发行量带千分位", p, "Sheet1", bond_type="地方债", expects=[(0, "发行量(亿)", 1200.5)]))

    # 11 期限写法
    rows = [local_row(债券简称=f"26测试债{i}", 期限=v) for i, v in enumerate(["5", "5年", "5y", "5+NY"], 1)]
    p = write_book(rows, "地方债_期限写法.xlsx")
    results.append(check("11 期限 5/5年/5y/5+NY", p, "Sheet1", bond_type="地方债", expects=[
        (0, "期限", "5Y"), (1, "期限", "5Y"), (2, "期限", "5Y"), (3, "期限", "5+NY")]))

    # 12 简称含续发
    p = write_book([local_row(债券简称="26广东债40(续发)")], "地方债_续发.xlsx")
    results.append(check("12 简称含（续发）", p, "Sheet1", bond_type="地方债", expects=[(0, "债券简称", "26广东债40(续发)")],
                         text_check=["广东"]))

    # 13 空发行日排序
    rows = [local_row(招标日="2026-10-14", 债券简称="26浙江债01"),
            local_row(招标日=None, 债券简称="26待定债01"),
            local_row(招标日="2026-10-12", 债券简称="26山东债01")]
    p = write_book(rows, "地方债_空发行日.xlsx")
    results.append(check("13 空发行日排最后", p, "Sheet1", bond_type="地方债", expects=[
        (0, "债券简称", "26山东债01"), (1, "债券简称", "26浙江债01"), (2, "发行日", "")]))

    # 14 时间格式
    rows = [local_row(债券简称=f"26时间债{i}", 招标时间=v) for i, v in enumerate(["9:30", "09:30:00", "9:30-10:10"], 1)]
    p = write_book(rows, "地方债_时间格式.xlsx")
    results.append(check("14 招标时间多种写法", p, "Sheet1", bond_type="地方债", expects=[
        (0, "发行时间", "09:30"), (1, "发行时间", "09:30"), (2, "发行时间", "09:30-10:10")]))

    # 15 表头含空格/换行
    spaced = {("招标日\n" if k == "招标日" else "发行量 (亿元)" if k == "发行量(亿元)" else k): v
              for k, v in base[0].items()}
    p = write_book([spaced], "地方债_表头空格换行.xlsx")
    results.append(check("15 表头含空格/换行", p, "Sheet1", bond_type="地方债", expects=[(0, "发行量(亿)", 90.1234)]))

    # 16 信用债基线
    p = write_book([credit_row()], "信用债_基线.xlsx")
    results.append(check("16 信用债基线", p, "Sheet1", bond_type="信用债", expects=[
        (0, "截标时间", "10-12 17:00"), (0, "发行日", "2026-10-14"), (0, "期限", "2Y"),
        (0, "发行量(亿)", 1.5), (0, "申购区间", "1.3-2.3"), (0, "主/债评级", "AA+/AA+"),
        (0, "YY评级", "4"),
    ], text_check=["26武清经开MTN007 1.5亿（2Y）"]))

    # 17 信用债标题行
    p = write_book([credit_row()], "信用债_标题行.xlsx", title_rows=2)
    results.append(check("17 信用债表头上方标题", p, "Sheet1", bond_type="信用债", expects=[(0, "债券简称", "26武清经开MTN007")]))

    # 18 信用债列乱序
    sh = {k: credit_row()[k] for k in reversed(CREDIT_HEADERS)}
    p = write_book([sh], "信用债_列乱序.xlsx")
    results.append(check("18 信用债列顺序打乱", p, "Sheet1", bond_type="信用债", expects=[(0, "截标时间", "10-12 17:00")]))

    # 19 实际发行优先
    p = write_book([credit_row(**{"实际发行(亿)": 1.8, "计划发行(亿)": 1.5})], "信用债_实际优先.xlsx")
    results.append(check("19 实际发行优先于计划", p, "Sheet1", bond_type="信用债", expects=[(0, "发行量(亿)", 1.8)]))

    # 20 实际为空取计划
    p = write_book([credit_row(**{"实际发行(亿)": None, "计划发行(亿)": 2.2})], "信用债_计划兜底.xlsx")
    results.append(check("20 实际为空回退计划", p, "Sheet1", bond_type="信用债", expects=[(0, "发行量(亿)", 2.2)]))

    # 21 评级组合
    rows = [credit_row(债券简称="26A", 主体评级="AAA", 债项评级=None),
            credit_row(债券简称="26B", 主体评级=None, 债项评级=None)]
    p = write_book(rows, "信用债_评级组合.xlsx")
    results.append(check("21 评级单边/双空", p, "Sheet1", bond_type="信用债", expects=[
        (0, "主/债评级", "AAA/"), (1, "主/债评级", "")]))

    # 22 截标时间 datetime
    p = write_book([credit_row(截标时间=datetime(2026, 10, 12, 17, 30))], "信用债_截标datetime.xlsx")
    results.append(check("22 截标时间为 datetime", p, "Sheet1", bond_type="信用债", expects=[(0, "截标时间", "10-12 17:30")]))

    # 23 双工作表
    path = TMP / "双品种.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([local_row()]).to_excel(writer, sheet_name="地方债", index=False)
        pd.DataFrame([credit_row()]).to_excel(writer, sheet_name="信用债", index=False)
    tasks = bondtable.load_tasks(str(path), CONFIG)
    results.append({
        "case": "23 一个文件两个品种工作表",
        "ok": [t[0] for t in tasks] == ["地方债", "信用债"] and len(tasks) == 2,
        "detail": f"{[(t[0], t[1], len(t[2])) for t in tasks]}",
    })

    # 24 文件名别名识别
    p = write_book([local_row()], "地方政府债 2026-09-22.xlsx", sheet="导出数据")
    results.append(check("24 文件名用『地方政府债』别名", p, "导出数据", bond_type="地方债", expects=[(0, "发行日", "2026-10-13")]))

    # 25 无法识别债种：表头按并集解析，用户手动指定后仍可制表
    p = write_book([local_row()], "未命名导出.xlsx", sheet="Sheet1")
    tasks = bondtable.load_tasks(str(p), CONFIG)
    detected = tasks[0][0] if tasks else "NO-TASK"
    converted = bondtable.convert_dataframe(tasks[0][2], CONFIG, "地方债")[0]
    results.append({
        "case": "25 文件名/表名无法识别债种",
        "ok": detected is None and list(converted.columns) == LOCAL_TARGET,
        "detail": f"detected={detected}, 手动指定后可输出 {len(converted)} 行",
    })

    print(json.dumps(results, ensure_ascii=False, indent=1))
    passed = sum(1 for r in results if r["ok"])
    print(f"\nPASS {passed}/{len(results)}")
    (TMP / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
