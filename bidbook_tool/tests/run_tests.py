# -*- coding: utf-8 -*-
"""端到端自测：样图 -> 框线切格 -> 认列 -> 取三列 -> 配简称 -> 出文案。

跑法（在项目根目录，用虚拟环境里的 python）：
    python3 tests/run_tests.py
没装 OCR 引擎也能跑：脚本会用样图自带的文字坐标模拟一次 OCR 结果，
所以它验证的是「切格 + 认列 + 匹配 + 成文」这条链路（OCR 那一步靠真机截图验）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from bidbook import rows as R
from bidbook import table as T
from bidbook.ocr import TextBox
from tests import make_sample

PASS, FAIL = [], []

# 样图版式（跟着 make_sample.layout 走，scale=1 时和原来一样）
# 想验证 Retina 那种高像素密度截图：BIDBOOK_TEST_SCALE=2 python3 tests/run_tests.py
SCALE = max(1, int(os.environ.get("BIDBOOK_TEST_SCALE", "1") or 1))
LAY = make_sample.layout(SCALE)
PAD, HEADER_H, ROW_H, COL_W = LAY["pad"], LAY["header_h"], LAY["row_h"], LAY["col_w"]


def check(name, ok, detail="") -> None:
    (PASS if ok else FAIL).append((name, detail))
    print(("  ok   " if ok else "  FAIL ") + name + (("   -> " + detail) if (detail and not ok) else ""))


def boxes_from_layout() -> list:
    """按 make_sample 的排版造出「文字框」，模拟 OCR 结果。"""
    pad, header_h, row_h = PAD, HEADER_H, ROW_H
    boxes = []
    xs, x = [], pad
    for w in COL_W:
        xs.append(x)
        x += w
    size = LAY["font"]
    def width(col: int, text: str) -> float:
        # 估一下文字宽度，但绝不越过本列右边界（真实的文字框不会跨列）
        return max(12.0, min(len(text) * size * 0.95, COL_W[col] - 8.0))

    for c, name in enumerate(make_sample.HEADERS):
        boxes.append(TextBox(name, xs[c] + 4, pad + 6, xs[c] + 4 + width(c, name), pad + 26))
    for r, cells in enumerate(make_sample.ROWS):
        y = pad + header_h + row_h * r
        for c, text in enumerate(cells):
            if not text:
                continue
            boxes.append(TextBox(text, xs[c] + 4, y + 5, xs[c] + 4 + width(c, str(text)), y + 22))
    return boxes


def cell(pi: float, pj: float) -> tuple:
    """把相对坐标 (列宽单位, 行高单位) 换算成像素矩形，用来给样图补「文字框」。"""
    pad, header_h, row_h = PAD, HEADER_H, ROW_H
    xs, x = [], pad
    for w in COL_W:
        xs.append(x)
        x += w
    ci, ri = int(pi), int(pj)
    x0 = xs[ci] + 6
    y0 = pad + header_h + row_h * ri + 6
    return (x0, y0, x0 + COL_W[ci] - 12, y0 + int(row_h * 0.6))


def main() -> int:
    png = ROOT / "tests" / "sample_table.png"
    make_sample.build(str(png), scale=SCALE)
    bgr = np.array(Image.open(png).convert("RGB"))[:, :, ::-1].copy()

    print("[1] 框线检测")
    grid = T.detect_grid(bgr)
    check("检测到完整框线", grid is not None, "表格线没认出来")
    if grid:
        check("列数接近 15", 12 <= len(grid["cols"]) <= 17, "实际 %d 列线" % len(grid["cols"]))
        check("行数接近 5", 4 <= len(grid["rows"]) <= 9, "实际 %d 条横线" % len(grid["rows"]))

    print("[2] 整表重建（用模拟的 OCR 文字框）")
    boxes = boxes_from_layout()
    rendered = T.parse_table(bgr, boxes, prefer_grid=True)
    check("走的是框线方案", rendered.method == "grid", rendered.method)
    header_texts = " | ".join(t for t in rendered.column_texts if t)
    print("      认出的表头：" + (header_texts[:160] or "(空)"))
    mapped = [v for v in rendered.header_map.values() if v]
    check("表头至少认出 8 列", len(set(mapped)) >= 8, "认出 %d 列：%s" % (len(set(mapped)), sorted(set(mapped))))
    for need in ("债券简称", "边际利率/价格", "全场倍数", "边际倍数"):
        check("认出「%s」" % need, need in mapped)

    print("[3] 取行")
    table_rows = T.extract_rows(rendered, guess_columns=True)
    check("取出 4 行数据", len(table_rows) == 4, "实际 %d 行" % len(table_rows))
    names = [t.name for t in table_rows]
    print("      " + str(names))
    check("简称都在", all(n for n in names), str(names))
    if table_rows:
        first = table_rows[0]
        check("第一行边际利率 1.81", first.margin_rate == 1.81, str(first.margin_rate))
        check("第一行全场倍数 1.77", first.full_ratio == 1.77, str(first.full_ratio))
        check("第一行边际倍数 2.00", first.edge_ratio == 2.0, str(first.edge_ratio))

    print("[4] 文本行 + 表格 -> 最终文案")
    text = "\n".join([
        "17:30 【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记",
        "【1.5-2.5】，26武清经开MTN008，2.5Y，1.4亿，AA+，10-12 簿记",
        "【2.0-3.0】，26武清经开MTN009，3Y，1.8亿，AA+，10-12 簿记",
        "18:00 【1.8-2.8】，26天津城投CP001，1Y，2亿，AAA，10-14 缴款",
    ])
    inputs = R.parse_input(text, auto_mode="17:30")
    results = R.match_rows(inputs, table_rows, threshold=0.90)
    out, results = R.format_results(results, default_time="17:30", show_time=False)
    print("------ 输出样例 ------")
    print(out)
    print("----------------------")
    check("四行都有结果", out.count("；") == 4, out)
    check("三只都能配上表格", all(r.matched is not None for r in results),
          str([(r.input.name, r.matched.name if r.matched else None) for r in results]))
    check("18:00 那只是最终边际", "最终边际" in out.split("\n")[-1], out.split("\n")[-1])

    print("[5] 没对应上的债：照样出一行，缺的数写「待定」")
    extra_text = text + "\n【9.9-9.9】，26根本不在表里的ZZ999，1Y，1亿，AA，10-13 簿记"
    extra = R.parse_input(extra_text, auto_mode="17:30")
    with_values = R.match_rows(extra, table_rows, threshold=0.90,
                               value_rows=R.parse_values("26根本不在表里的ZZ999 1.75-1.95 1.11 5.00"))
    out_v, with_values = R.format_results(with_values, default_time="17:30")
    check("窗口 2 补上数后照样出文案（范围取上限）",
          "目前边际1.95%，全场倍数1.11倍，边际倍数5.00倍" in out_v, out_v)
    plain = R.match_rows(R.parse_input(extra_text, auto_mode="17:30"), table_rows, threshold=0.90)
    out_n, plain = R.format_results(plain, default_time="17:30")
    check("两处都没有也出一行，三个数写待定",
          "【9.9-9.9】26根本不在表里的ZZ999，1Y，1亿，AA；目前边际待定，全场倍数待定，边际倍数待定。" in out_n
          and out_n.count("；") == 5, out_n)
    check("并写明「没有对应的数据」",
          any(str(r.review_reason).startswith("没有对应的数据") for r in plain),
          str([r.review_reason for r in plain]))
    check("pending 三项都列出来",
          any(r.pending == ["margin_rate", "full_ratio", "edge_ratio"] for r in plain),
          str([r.pending for r in plain]))

    print("[6] 修复回归：简称别配错 / 日期别当成数（用真 OCR 出来的表格）")
    wrong = R.parse_input("【1.3-2.3】，26武清经开MTN099，2Y，1.5亿，AA+，10-12 簿记", auto_mode="17:30")
    wr = R.match_rows(wrong, table_rows, threshold=0.90)
    out_w, wr = R.format_results(wr, default_time="17:30")
    check("表里没有的期数不许配到别人的行上", wr[0].matched is None and "目前边际待定" in out_w, out_w)
    check("行末写明来源", "【来源：" in out_w, out_w)
    full_row = "【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%"
    vp = []
    vrows = R.parse_values(full_row, problems=vp)
    check("整行簿记文本被窗口 2 拒绝", vrows == [] and bool(vp), str(vp))
    bad = R.match_rows(R.parse_input("【9.9-9.9】，26根本不在表里的ZZ999，1Y，1亿，AA", auto_mode="17:40"),
                       table_rows, threshold=0.90, value_rows=vrows)
    out_b, bad = R.format_results(bad, default_time="17:40")
    check("被拒绝后不出「12.00%」这种日期假数", "12.00%" not in out_b and "待定" in out_b, out_b)

    print("")
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        for name, detail in FAIL:
            print("  - " + name + "：" + detail)
        return 1
    print("端到端自测全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
