"""投标簿记工具：25 类「表格截图 + 文本」输入材料的验收矩阵。

生成不同版式/字号/表头别名/数字写法的截图，真实跑 RapidOCR →
parse_image → parse_input/match_rows/format_results，断言取数与成文。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT.parent / "bidbook_tool"
sys.path.insert(0, str(TOOL))

from bidbook import ocr, rows as rows_mod, table as table_mod  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="wb-accept-bidbook-"))
FONTS = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    path = next((p for p in FONTS[index:] + FONTS[:index] if p.exists()), None)
    if path is None:
        raise RuntimeError("找不到中文字体（msyh.ttc / simhei.ttf / simsun.ttc）")
    return ImageFont.truetype(str(path), size)


BASE_HEADERS = ["债券简称", "债券代码", "边际利率/价格", "全场倍数", "边际倍数"]
BASE_ROWS = [
    ["26武清经开MTN007", "102601234", "2.30", "1.55", "3.10"],
    ["26武清经开MTN008", "102601235", "2.45", "1.80", "2.60"],
    ["26天津城投CP001", "042600123", "2.10", "2.05", "4.20"],
]
TEXT = (
    "17:30 【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市\n"
    "【1.5-2.5】，26武清经开MTN008，2.5Y，1.4亿，AA+，10-13 簿记\n"
    "【1.8-2.6】，26天津城投CP001，1Y，3亿，AAA，10-13 簿记\n"
)


def draw_table(
    headers,
    data,
    *,
    size=26,
    font_index=0,
    grid=True,
    header_fill=None,
    zebra=False,
    pad_x=16,
    pad_y=10,
    margin=24,
    title=None,
    scale=1.0,
    header_two_rows=False,
):
    f = font(size, font_index)
    f_head = font(size, font_index)
    widths = []
    for i in range(len(headers)):
        cells = [headers[i]] + [row[i] if i < len(row) else "" for row in data]
        widths.append(max(int(f.getlength(str(c))) for c in cells) + pad_x * 2)
    row_h = size + pad_y * 2
    width = sum(widths) + margin * 2
    title_h = (size + 20) if title else 0
    header_rows = 2 if header_two_rows else 1
    height = margin * 2 + title_h + row_h * (header_rows + len(data))
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = margin
    if title:
        d.text((margin, y), title, font=font(size + 2, font_index), fill="#202020")
        y += title_h

    def cell_box(x, yy, w, h):
        if grid:
            d.rectangle([x, yy, x + w, yy + h], outline="#8a8a8a", width=2)

    if header_two_rows:
        # 第一行合并「簿记信息」，第二行才是真正的列名
        d.rectangle([margin, y, margin + sum(widths), y + row_h], fill=header_fill or "#e8eef7",
                    outline="#8a8a8a", width=2)
        d.text((margin + 8, y + pad_y), "簿记信息", font=f_head, fill="#202020")
        y += row_h
    x = margin
    for i, h in enumerate(headers):
        if header_fill:
            d.rectangle([x, y, x + widths[i], y + row_h], fill=header_fill)
        if grid:
            d.rectangle([x, y, x + widths[i], y + row_h], outline="#8a8a8a", width=2)
        tw = f_head.getlength(str(h))
        d.text((x + (widths[i] - tw) / 2, y + pad_y), str(h), font=f_head, fill="#202020")
        x += widths[i]
    y += row_h
    for r_i, row in enumerate(data):
        x = margin
        if zebra and r_i % 2 == 1:
            d.rectangle([margin, y, margin + sum(widths), y + row_h], fill="#f2f2f2")
        for i, value in enumerate(row):
            cell_box(x, y, widths[i], row_h)
            tw = f.getlength(str(value))
            d.text((x + (widths[i] - tw) / 2, y + pad_y), str(value), font=f, fill="#111111")
            x += widths[i]
        y += row_h
    if scale != 1.0:
        img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    return img


def run(image: Image.Image, text: str = TEXT, values_text: str = ""):
    engine, boxes = ocr.run_ocr(image, engine="rapidocr")
    bgr = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    _, table_rows = table_mod.parse_image(bgr, boxes)
    inputs = rows_mod.parse_input(text)
    values = rows_mod.parse_values(values_text)
    results = rows_mod.match_rows(inputs, table_rows, value_rows=values)
    output, _ = rows_mod.format_results(results, show_time=False)
    return table_rows, results, output


def check(name, image, expects, *, text=TEXT, values_text="", output_contains=()):
    """expects: {简称: {"margin": 2.30, "full": 1.55, "edge": 3.10}}"""
    try:
        table_rows, results, output = run(image, text, values_text)
        for key, want in expects.items():
            hit = next((r for r in results if key in (r.input.display_name or "")), None)
            if hit is None:
                raise AssertionError(f"结果里没有 {key}；输入={[r.input.display_name for r in results]}")
            if hit.matched is None:
                raise AssertionError(f"{key} 没有匹配到表格行；表格={[(t.name, t.code) for t in table_rows]}")
            for field, value in want.items():
                attr = {"margin": "margin_rate", "full": "full_ratio", "edge": "edge_ratio"}[field]
                # 窗口 2 的数优先（与 format_results 的取值顺序一致）。
                text_value = hit.text_values.get(attr)
                if text_value not in (None, ""):
                    got = float(str(text_value).replace("%", "").replace("倍", ""))
                else:
                    got = getattr(hit.matched, attr)
                if value is None:
                    assert got is None, f"{key}.{attr} 期望空，实际 {got}"
                else:
                    assert got is not None and abs(got - value) < 0.011, f"{key}.{attr} = {got} != {value}"
        for needle in output_contains:
            assert needle in output, f"成文缺少 {needle!r}：\n{output}"
        return {"case": name, "ok": True, "detail": f"OCR {len(table_rows)} 行 / 成文 {len(results)} 行"}
    except Exception as exc:  # noqa: BLE001
        return {"case": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def main():
    results = []
    base_expect = {"26武清经开MTN007": {"margin": 2.30, "full": 1.55, "edge": 3.10},
                   "26天津城投CP001": {"margin": 2.10, "full": 2.05, "edge": 4.20}}

    # 1 基线
    results.append(check("1 基线 5 列带框线", draw_table(BASE_HEADERS, BASE_ROWS),
                         base_expect, output_contains=["目前边际2.30%", "全场倍数1.55倍"]))

    # 2 无框线
    results.append(check("2 无框线（仅表头下划线）", draw_table(BASE_HEADERS, BASE_ROWS, grid=False),
                         base_expect))

    # 3 表头底色
    results.append(check("3 灰色表头底色", draw_table(BASE_HEADERS, BASE_ROWS, header_fill="#e8e8e8"),
                         base_expect))

    # 4 蓝色表头
    results.append(check("4 浅蓝表头", draw_table(BASE_HEADERS, BASE_ROWS, header_fill="#dbe7f5"),
                         base_expect))

    # 5 斑马纹
    results.append(check("5 交替行底色", draw_table(BASE_HEADERS, BASE_ROWS, zebra=True),
                         base_expect))

    # 6 黑体
    results.append(check("6 黑体字体", draw_table(BASE_HEADERS, BASE_ROWS, font_index=1),
                         base_expect))

    # 7 小字号
    results.append(check("7 字号 22", draw_table(BASE_HEADERS, BASE_ROWS, size=22),
                         base_expect))

    # 8 大字号
    results.append(check("8 字号 32", draw_table(BASE_HEADERS, BASE_ROWS, size=32),
                         base_expect))

    # 9 表头别名
    aliases = ["简称", "债券代码", "边际", "全场", "边际倍数"]
    results.append(check("9 表头用别名", draw_table(aliases, BASE_ROWS), base_expect))

    # 10 列顺序打乱
    order = [3, 0, 4, 1, 2]
    shuffled_headers = [BASE_HEADERS[i] for i in order]
    shuffled_rows = [[row[i] for i in order] for row in BASE_ROWS]
    results.append(check("10 列顺序打乱", draw_table(shuffled_headers, shuffled_rows), base_expect))

    # 11 多一列操作提示
    headers = BASE_HEADERS[:1] + ["操作提示"] + BASE_HEADERS[1:]
    data = [[row[0], "查看"] + row[1:] for row in BASE_ROWS]
    results.append(check("11 多一列操作提示", draw_table(headers, data), base_expect))

    # 12 数字带 %
    data = [row[:2] + [row[2] + "%", row[3], row[4]] for row in BASE_ROWS]
    results.append(check("12 边际写成 2.30%", draw_table(BASE_HEADERS, data), base_expect))

    # 13 数字带「倍」
    data = [row[:3] + [row[3] + "倍", row[4] + "倍"] for row in BASE_ROWS]
    results.append(check("13 倍数写成 1.55倍", draw_table(BASE_HEADERS, data), base_expect))

    # 14 边际为空（横线）
    data = [row[:2] + ["—", row[3], row[4]] for row in BASE_ROWS]
    results.append(check("14 边际为空显示横线", draw_table(BASE_HEADERS, data),
                         {"26武清经开MTN007": {"margin": None, "full": 1.55}}))

    # 15 全场为空
    data = [row[:3] + ["", row[4]] for row in BASE_ROWS]
    results.append(check("15 全场倍数为空", draw_table(BASE_HEADERS, data),
                         {"26武清经开MTN007": {"margin": 2.30, "full": None}}))

    # 16 六行
    six = BASE_ROWS + [
        ["26江苏交控MTN001", "102601236", "2.55", "1.90", "2.20"],
        ["26浙江能源SCP002", "012600456", "2.05", "2.30", "3.50"],
        ["26山东高速MTN003", "102601237", "2.65", "1.70", "2.90"],
    ]
    six_text = TEXT + (
        "【1.9-2.6】，26江苏交控MTN001，3Y，2亿，AAA\n"
        "【2.0-2.4】，26浙江能源SCP002，0.5Y，4亿，AAA\n"
        "【2.6-3.0】，26山东高速MTN003，5Y，1亿，AAA\n"
    )
    results.append(check("16 六行数据", draw_table(BASE_HEADERS, six),
                         {**base_expect, "26山东高速MTN003": {"margin": 2.65, "full": 1.70, "edge": 2.90}},
                         text=six_text))

    # 17 两行
    results.append(check("17 两行数据", draw_table(BASE_HEADERS, BASE_ROWS[:2]),
                         {"26武清经开MTN007": {"margin": 2.30},
                          "26武清经开MTN008": {"margin": 2.45}}))

    # 18 2 倍分辨率
    results.append(check("18 高分辨率截图", draw_table(BASE_HEADERS, BASE_ROWS, scale=2.0), base_expect))

    # 19 0.75 倍分辨率
    results.append(check("19 低分辨率截图", draw_table(BASE_HEADERS, BASE_ROWS, scale=0.75), base_expect))

    # 20 带标题与留白
    results.append(check("20 表格上方有标题", draw_table(BASE_HEADERS, BASE_ROWS, title="簿记过程信息表"),
                         base_expect))

    # 21 两行表头
    results.append(check("21 两行表头", draw_table(BASE_HEADERS, BASE_ROWS, header_two_rows=True),
                         base_expect))

    # 22 长简称
    long_rows = [
        ["26中国华能集团有限公司MTN001", "102601238", "2.35", "1.60", "3.00"],
        ["26国家电网有限公司SCP001", "012600789", "2.00", "2.40", "4.50"],
    ]
    long_text = ("【1.4-2.4】，26中国华能集团有限公司MTN001，3Y，2亿，AAA\n"
                 "【1.9-2.1】，26国家电网有限公司SCP001，0.5Y，5亿，AAA\n")
    results.append(check("22 超长债券简称", draw_table(BASE_HEADERS, long_rows, size=20),
                         {"26中国华能集团有限公司MTN001": {"margin": 2.35},
                          "26国家电网有限公司SCP001": {"full": 2.40}},
                         text=long_text))

    # 23 代码在名称前
    headers = ["债券代码", "债券简称", "边际利率", "全场倍数", "边际倍数"]
    data = [[r[1], r[0], r[2], r[3], r[4]] for r in BASE_ROWS]
    results.append(check("23 代码列在简称前", draw_table(headers, data), base_expect))

    # 24 窗口 2 补数（截图里没有边际）
    data = [row[:2] + ["", row[3], ""] for row in BASE_ROWS]
    values = "26武清经开MTN007 边际1.77% 全场1.66倍 边际倍数5.55\n26天津城投CP001 2.22 2.11 3.33\n"
    results.append(check("24 窗口2补充边际数据", draw_table(BASE_HEADERS, data),
                         {"26武清经开MTN007": {"margin": 1.77, "full": 1.66, "edge": 5.55},
                          "26天津城投CP001": {"margin": 2.22, "full": 2.11, "edge": 3.33}},
                         values_text=values,
                         output_contains=["目前边际1.77%", "边际倍数5.55倍"]))

    # 25 多行文本 / 一行两只债
    results.append(check("25 一行塞两只债", draw_table(BASE_HEADERS, BASE_ROWS[:2]),
                         {"26武清经开MTN007": {"margin": 2.30},
                          "26武清经开MTN008": {"margin": 2.45}},
                         text="【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+；【1.5-2.5】，26武清经开MTN008，2.5Y，1.4亿，AA+"))

    print(json.dumps(results, ensure_ascii=False, indent=1))
    passed = sum(1 for r in results if r["ok"])
    print(f"\nPASS {passed}/{len(results)}")
    (TMP / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
