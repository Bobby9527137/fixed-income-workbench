# -*- coding: utf-8 -*-
"""不依赖 OCR 的自检：解析、匹配、成文。

跑法：  python3 selftest.py
只验证「文本行解析 + 表格行匹配 + 文案生成」这条纯逻辑链：不需要 OCR 引擎、
不需要联网，装完依赖想快速确认没坏就用它。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bidbook import rows as R            # noqa: E402
from bidbook.table import TableRow       # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail="") -> None:
    (PASS if ok else FAIL).append((name, detail))
    mark = "  ok   " if ok else "  FAIL "
    print(mark + name + (("   -> " + detail) if (detail and not ok) else ""))


N = chr(10)
SAMPLE_TEXT = N.join([
    "17:30 【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%",
    "【1.5-2.5】，26武清经开MTN008，2.5Y，1.4亿，AA+，10-13 簿记",
    "18:00 【2.0-3.0】26天津城投CP001，1Y，2亿，AAA，10-14 缴款",
    "这是一行说明文字，没有债券",
])

TABLE = [
    TableRow(code="042600007", name="26武清经开MTN007", raw_name="26武清经开MTN007",
             margin_rate=1.81, full_ratio=1.77, edge_ratio=2.0, index=1),
    TableRow(code="042600008", name="26武清经开MTN008", raw_name="26武清经开MTN008",
             margin_rate=1.87, full_ratio=1.55, edge_ratio=1.4, index=2),
    TableRow(code="012600001", name="26天津城投CP001", raw_name="26天津城投CP001",
             margin_rate=2.15, full_ratio=2.3, edge_ratio=3.0, index=3),
]


print("[1] 文本行解析")
inputs = R.parse_input(SAMPLE_TEXT, auto_mode="17:30")
check("识别出 3 只债券", len(inputs) == 3, "实际 %d（说明文字那行会被丢掉）" % len(inputs))
by_name = {i.name: i for i in inputs}
w7 = by_name.get("26武清经开MTN007")
check("简称正确", w7 is not None)
if w7:
    check("区间 -> 【1.3-2.3】", w7.range_text.strip() == "1.3-2.3", w7.range_text)
    check("期限 2Y", w7.tenor_text == "2Y", w7.tenor_text)
    check("规模 1.5亿", w7.scale_text == "1.5亿", w7.scale_text)
    check("评级 AA+", w7.rating_text == "AA+", w7.rating_text)
    check("行首时间 17:30", w7.time_hint == "17:30", w7.time_hint)
    check("前缀文案", w7.prefix().startswith("【1.3-2.3】26武清经开MTN007，2Y，1.5亿，AA+"), w7.prefix())
w8 = by_name.get("26武清经开MTN008")
check("第二只也解析成功", w8 is not None and w8.parsed_ok)
c1 = by_name.get("26天津城投CP001")
check("第三只行首 18:00 被记住", c1 is not None and c1.time_hint == "18:00")

print("[2] 时点判定")
check("17:30 -> 目前边际", R.resolve_mode(None, "17:30")[0] == "目前边际")
check("17:50 -> 目前边际", R.resolve_mode(None, "17:50")[0] == "目前边际")
check("18:00 -> 最终边际", R.resolve_mode(None, "18:00")[0] == "最终边际")
check("18:00 优先于默认值", R.resolve_mode("18:00", "17:30")[0] == "最终边际")
check("乱填的时点不崩", isinstance(R.resolve_mode(None, "20:15")[0], str))

print("[3] 简称匹配")
results = R.match_rows(inputs, TABLE, threshold=0.90)
check("三只都配上", all(r.matched is not None for r in results),
      str([(r.input.name, r.matched.name if r.matched else None) for r in results]))
check("没有重复占行", len({id(r.matched) for r in results if r.matched}) == 3)

print("[4] 生成文案")
text, results = R.format_results(results, default_time="17:30", show_time=False)
lines = text.split(N)
check("三行", len(lines) == 3, repr(text))
check("17:30 用「目前边际」", "目前边际1.81%" in text, text)
check("18:00 用「最终边际」", "最终边际2.15%" in text, text)
expected = ("【1.3-2.3】26武清经开MTN007，2Y，1.5亿，AA+；目前边际1.81%，全场倍数1.77倍，边际倍数2.00倍。"
            + "【来源：截图匹配，匹配度1.00，匹配标的：26武清经开MTN007】")
check("样例行完全一致", lines[0] == expected, lines[0])
with_time, _ = R.format_results(results, default_time="17:30", show_time=True)
check("带时间开关有效", with_time.split(N)[0].find("17:30") >= 0, with_time.split(N)[0])

print("[5] 没对应上的债：照样出一行，缺的数写「待定」")
solo = R.parse_input("【1.0-2.0】，26完全不存在的债XX009，1Y，1亿，AA，10-13 簿记", auto_mode="17:40")
out, rs = R.format_results(R.match_rows(solo, TABLE, threshold=0.90), default_time="17:40")
check("明确标出没配上", rs[0].matched is None, str(rs[0].matched))
check("照样出文案，三个数都写待定",
      out == ("【1.0-2.0】26完全不存在的债XX009，1Y，1亿，AA；目前边际待定，全场倍数待定，边际倍数待定。"
              + "【来源：未匹配】"), out)
check("一个真数都没有时 has_data 为假", rs[0].has_data is False, str(rs[0].has_data))
check("写明「没有对应的数据」", rs[0].review_reason.startswith("没有对应的数据"), rs[0].review_reason)
check("pending 三项都列出来", rs[0].pending == ["margin_rate", "full_ratio", "edge_ratio"], str(rs[0].pending))

print("[6] 人工改数（overrides 的键是表格行号）")
one = R.parse_input("【1.0-2.0】，26武清经开MTN007，1Y，1亿，AA，10-13 簿记", auto_mode="17:30")
shifted = [TableRow(code="042600007", name="26武清经开MTN007", raw_name="26武清经开MTN007",
                    margin_rate=1.81, full_ratio=1.77, edge_ratio=2.0, index=7)]
t_ov, _ = R.format_results(R.match_rows(one, shifted, threshold=0.90), default_time="17:30",
                           overrides={"7": {"margin_rate": "1.99"}})
check("按表格行号覆盖生效（不是粘贴行号）", "目前边际1.99%" in t_ov, t_ov)
t_ov2, _ = R.format_results(R.match_rows(one, shifted, threshold=0.90), default_time="17:30",
                            overrides={"1": {"margin_rate": "1.98"}})
check("退回按粘贴行号也认（兼容命令行）", "目前边际1.98%" in t_ov2, t_ov2)

print("[7] 按电脑时间自动判断（网页上的默认选项）")


def at(hour, minute):
    """造一个固定时刻，方便测「电脑时间」。"""
    return datetime(2026, 4, 20, hour, minute)


check("09:10 → 17:30 / 目前边际", R.clock_mode(at(9, 10)) == ("目前边际", "17:30"), str(R.clock_mode(at(9, 10))))
check("17:25 → 17:30 / 目前边际", R.clock_mode(at(17, 25)) == ("目前边际", "17:30"), str(R.clock_mode(at(17, 25))))
check("17:42 → 17:40 / 目前边际", R.clock_mode(at(17, 42)) == ("目前边际", "17:40"), str(R.clock_mode(at(17, 42))))
check("17:50 → 17:50 / 目前边际", R.clock_mode(at(17, 50)) == ("目前边际", "17:50"), str(R.clock_mode(at(17, 50))))
check("18:00 → 18:00 / 最终边际", R.clock_mode(at(18, 0)) == ("最终边际", "18:00"), str(R.clock_mode(at(18, 0))))
check("18:37 → 18:00 / 最终边际", R.clock_mode(at(18, 37)) == ("最终边际", "18:00"), str(R.clock_mode(at(18, 37))))
check("01:00 也算第一轮 17:30（不另造时点）", R.clock_mode(at(1, 0)) == ("目前边际", "17:30"), str(R.clock_mode(at(1, 0))))
check("23:00 仍是 18:00 / 最终边际", R.clock_mode(at(23, 0)) == ("最终边际", "18:00"), str(R.clock_mode(at(23, 0))))
check("自动判断出来的时点必定是那四个之一",
      all(R.clock_slot(at(h, 0)) in ["17:30", "17:40", "17:50", "18:00"] for h in range(24)),
      str([R.clock_slot(at(h, 0)) for h in range(24)]))
check("auto 落成具体时点", R.resolve_default_time("auto", at(17, 42)) == "17:40", R.resolve_default_time("auto", at(17, 42)))
check("current 手动指定目前边际", R.resolve_default_time("current", at(18, 37)) == "17:50", R.resolve_default_time("current", at(18, 37)))
check("final 手动指定最终边际", R.resolve_default_time("final", at(9, 0)) == "18:00", R.resolve_default_time("final", at(9, 0)))
check("直接传 17:40 原样保留", R.resolve_default_time("17:40", at(9, 0)) == "17:40")
check("now_info 给网页用", set(R.now_info(at(17, 42))) == {"time", "slot", "mode"})

# 注意：format_results 会把算出来的时点写回 input.time_hint，所以每次都要重新解析一份。
AUTO_LINE = "【1.0-2.0】，26武清经开MTN007，1Y，1亿，AA，10-13 簿记"
out_auto, _ = R.format_results(R.match_rows(R.parse_input(AUTO_LINE), TABLE, threshold=0.90),
                               default_time=R.resolve_default_time("auto", at(18, 5)))
check("18:05 自动模式出的是最终边际", "最终边际1.81%" in out_auto, out_auto)
out_auto2, _ = R.format_results(R.match_rows(R.parse_input(AUTO_LINE), TABLE, threshold=0.90),
                                default_time=R.resolve_default_time("auto", at(17, 35)))
check("17:35 自动模式出的是目前边际", "目前边际1.81%" in out_auto2, out_auto2)
mixed = R.parse_input("18:00 【1.0-2.0】，26武清经开MTN007，1Y，1亿，AA")
out_mixed, _ = R.format_results(R.match_rows(mixed, TABLE, threshold=0.90), default_time="17:40")
check("文本行自己写的 18:00 优先", "最终边际" in out_mixed, out_mixed)

print("[8] 第二个窗口（边际数据：截图没有的靠文本也能出数）")
problems = []
vals = R.parse_values(
    "26完全不存在的债XX009 2.30 1.55 3.10" + N
    + "26武清经开MTN007 边际9.99% 全场9.99倍" + N
    + "1.81 1.77 2.00", problems=problems)
check("认出一行一只的三个数", vals and vals[0].values() == {"margin_rate": "2.30", "full_ratio": "1.55", "edge_ratio": "3.10"},
      str(vals[0].values()) if vals else "没认出来")
check("认带标签的写法", len(vals) > 1 and vals[1].margin_rate == "9.99" and vals[1].full_ratio == "9.99",
      str(vals[1].values()) if len(vals) > 1 else "没认出来")
check("没有简称的行会被报出来", problems == ["1.81 1.77 2.00"], str(problems))

NODATA_LINE = "【1.0-2.0】，26完全不存在的债XX009，1Y，1亿，AA，10-13 簿记"
rx = R.match_rows(R.parse_input(NODATA_LINE, auto_mode="17:40"), TABLE, threshold=0.90,
                  value_rows=R.parse_values("26完全不存在的债XX009 2.30 1.55 3.10"))
out_x, rx = R.format_results(rx, default_time="17:40")
check("截图里没有、窗口 2 给数 → 照样出文案",
      out_x == ("【1.0-2.0】26完全不存在的债XX009，1Y，1亿，AA；目前边际2.30%，全场倍数1.55倍，边际倍数3.10倍。"
                + "【来源：窗口2文本，匹配度1.00，匹配标的：26完全不存在的债XX009】"),
      out_x)
check("并标明这一行的数来自窗口 2", rx[0].values_source == "文本", rx[0].values_source)

PERFECT = "【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+"
partial = [TableRow(code="042600007", name="26武清经开MTN007", raw_name="26武清经开MTN007",
                    margin_rate=1.81, full_ratio=None, edge_ratio=2.0, index=1)]
rp = R.match_rows(R.parse_input(PERFECT, auto_mode="17:30"), partial, threshold=0.90,
                  value_rows=R.parse_values("26武清经开MTN007 全场1.55倍"))
out_p, rp = R.format_results(rp, default_time="17:30")
check("截图里缺的那项由窗口 2 补上", "全场倍数1.55倍" in out_p, out_p)
check("数来自「截图+文本」", rp[0].values_source == "截图+文本", rp[0].values_source)

rc = R.match_rows(R.parse_input(PERFECT, auto_mode="17:30"), TABLE, threshold=0.90,
                  value_rows=R.parse_values("26武清经开MTN007 边际9.99%"))
out_c, rc = R.format_results(rc, default_time="17:30")
check("两边都有时以截图为准", "目前边际1.81%" in out_c and "9.99" not in out_c, out_c)
check("打架的地方会提醒", any("和截图不一样" in n for n in rc[0].input.notes), str(rc[0].input.notes))

print("[8b] 文字版：边际利率是范围 → 取上限；缺的项写「待定」")
rng = R.parse_values("26武清经开MTN008 1.75-1.95 1.2~1.3 2.5至3.1")
check("范围取上限（- / ~ / 至 都认）",
      bool(rng) and rng[0].values() == {"margin_rate": "1.95", "full_ratio": "1.3", "edge_ratio": "3.1"},
      str(rng[0].values()) if rng else "没认出来")
rng2 = R.parse_values("26武清经开MTN008 边际1.75-1.95%")
check("带标签的范围也取上限", bool(rng2) and rng2[0].margin_rate == "1.95",
      str(rng2[0].values()) if rng2 else "没认出来")
rng3 = R.parse_values("26武清经开MTN008 【1.75-1.95】")
check("只有【】里的区间时当边际（取上限）", bool(rng3) and rng3[0].margin_rate == "1.95",
      str(rng3[0].values()) if rng3 else "没认出来")
rng4 = R.parse_values("【1.3-2.3】，26武清经开MTN008，2.5Y，1.4亿，AA+，1.75-1.95")
check("整行粘进来时优先认裸着的数（不会错拿【1.3-2.3】）", bool(rng4) and rng4[0].margin_rate == "1.95",
      str(rng4[0].values()) if rng4 else "没认出来")

PART_TABLE = [TableRow(code="042600007", name="26武清经开MTN007", raw_name="26武清经开MTN007",
                       margin_rate=1.81, full_ratio=None, edge_ratio=None, index=1)]
pm = R.match_rows(R.parse_input(PERFECT, auto_mode="17:30"), PART_TABLE, threshold=0.90)
out_m, pm = R.format_results(pm, default_time="17:30")
check("截图里没给的项写「待定」",
      out_m == ("【1.3-2.3】26武清经开MTN007，2Y，1.5亿，AA+；目前边际1.81%，全场倍数待定，边际倍数待定。"
                + "【来源：截图匹配，匹配度1.00，匹配标的：26武清经开MTN007】"), out_m)
check("pending 只列缺的那两项", pm[0].pending == ["full_ratio", "edge_ratio"], str(pm[0].pending))
check("as_dict 里 pending 是中文字段名", pm[0].as_dict()["pending"] == ["全场倍数", "边际倍数"],
      str(pm[0].as_dict()["pending"]))

rx2 = R.match_rows(R.parse_input(NODATA_LINE, auto_mode="17:40"), TABLE, threshold=0.90,
                   value_rows=R.parse_values("26完全不存在的债XX009 2.30"))
out_r2, rx2 = R.format_results(rx2, default_time="17:40")
check("窗口 2 只给一个数，另外两个写待定",
      out_r2 == ("【1.0-2.0】26完全不存在的债XX009，1Y，1亿，AA；目前边际2.30%，全场倍数待定，边际倍数待定。"
                 + "【来源：窗口2文本，匹配度1.00，匹配标的：26完全不存在的债XX009】"), out_r2)

print("[9] 修复回归：路径A（简称别配错）")
# 路径 A：同名不同期数 / 不同年份 / 不同品种一律不许配上（旧代码会硬给 0.88~0.93 的假高分）
for other in ["26武清经开MTN008", "26武清国资MTN001", "25武清经开MTN007", "26武清经开PPN001"]:
    check("不许把 26武清经开MTN007 配成 %s" % other,
          R._name_score("26武清经开MTN007", other) == 0.0,
          str(R._name_score("26武清经开MTN007", other)))
check("简称完全相同还是 1.0", R._name_score("26武清经开MTN007", "26武清经开MTN007") == 1.0)
check("只是子串时只加分、不给高分", R._name_score("26武清经开MTN007", "26武清经开") < 0.90,
      str(R._name_score("26武清经开MTN007", "26武清经开")))
check("关键要素（年份/品种/期数）能解析出来",
      R._bond_keys("26武清经开MTN007") == {"year": "26", "variety": "MTN", "issue": "7"},
      str(R._bond_keys("26武清经开MTN007")))
fake = [TableRow(code="042600009", name="26武清经开MTN009", raw_name="26武清经开MTN009",
                 margin_rate=2.22, full_ratio=1.22, edge_ratio=3.22, index=1)]
bad_in = R.parse_input("【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+", auto_mode="17:30")
out_bad, bad = R.format_results(R.match_rows(bad_in, fake, threshold=0.90), default_time="17:30")
check("路径A：配不上时不抄别人的数",
      bad[0].matched is None and "2.22" not in out_bad and "目前边际待定" in out_bad, out_bad)
check("默认门槛就是 0.90", R.DEFAULT_THRESHOLD == 0.90, str(R.DEFAULT_THRESHOLD))
check("门槛参数不写时用默认值",
      R.match_rows(R.parse_input("【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+", auto_mode="17:30"),
                   fake)[0].matched is None)

print("[9b] 匹配分数偏低时行首挂警告（把门槛调低时给个提醒）")
loose = [TableRow(code="X1", name="26武清经开", raw_name="26武清经开",
                  margin_rate=1.81, full_ratio=1.77, edge_ratio=2.0, index=1)]
lo = R.match_rows(R.parse_input("【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+", auto_mode="17:30"),
                  loose, threshold=0.70)
out_lo, lo = R.format_results(lo, default_time="17:30")
check("门槛调低后配上了但会挂警告", lo[0].matched is not None and "\u26a0" in out_lo[:4], out_lo)
check("行末写清来源与匹配度", "【来源：截图匹配，匹配度" in out_lo, out_lo)

print("[9c] 修复回归：路径B（日期别当成数）")
for tok in ["10-12", "10-13", "10-14", "2025-10-12", "2Y", "1.5亿", "1k"]:
    check("「%s」不解析成数值" % tok, R._number_from_token(tok) is None, str(R._number_from_token(tok)))
check("合法利率范围仍取上限", R._number_from_token("1.75-1.95") == "1.95", str(R._number_from_token("1.75-1.95")))
check("带 % / 倍的范围取上限",
      R._number_from_token("1.75-1.95%") == "1.95" and R._number_from_token("10-20倍") == "20",
      "%s / %s" % (R._number_from_token("1.75-1.95%"), R._number_from_token("10-20倍")))
check("~ 和 至 也认", R._number_from_token("1.2~1.3") == "1.3" and R._number_from_token("2.5至3.1") == "3.1",
      "%s / %s" % (R._number_from_token("1.2~1.3"), R._number_from_token("2.5至3.1")))
FULL_ROW = "【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%"
check("整行簿记文本被认出来（命中「簿记」）", R.check_values_text(FULL_ROW) == "簿记", R.check_values_text(FULL_ROW))
check("正常的一行不会被拦", R.check_values_text("26武清经开MTN007 1.81 1.77 2.00") == "",
      R.check_values_text("26武清经开MTN007 1.81 1.77 2.00"))
vb = []
check("整行簿记文本整段不解析", R.parse_values(FULL_ROW, problems=vb) == [] and bool(vb), str(vb))
check("拒绝原因写得清楚", bool(vb) and "窗口2输入错误" in vb[0] and "簿记" in vb[0], str(vb))
rej = R.match_rows(R.parse_input("【1.0-2.0】，26完全不存在的债XX009，1Y，1亿，AA", auto_mode="17:40"),
                   TABLE, threshold=0.90, value_rows=R.parse_values(FULL_ROW))
out_rej, rej = R.format_results(rej, default_time="17:40")
check("被拒绝时不出「目前边际12.00%」这种假数",
      "12.00%" not in out_rej and "目前边际待定" in out_rej, out_rej)

print("")
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    for name, detail in FAIL:
        print("  - " + name + "：" + detail)
    raise SystemExit(1)
print("逻辑自检全部通过")
