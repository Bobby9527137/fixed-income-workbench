# -*- coding: utf-8 -*-
"""造一张「和投标系统截图长得一样」的表格图片，用来端到端自测。

它只依赖 Pillow，不需要任何 OCR 模型；配合 tests/run_tests.py 可以在
没网、没模型的机器上验证整条管线（框线切格 -> 认列 -> 取三列 -> 配简称 -> 出文案）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    print("需要 Pillow：pip install Pillow")
    raise SystemExit(2)

HEADERS = ["操作提示", "债券代码", "债券简称", "债券全称", "是否中标",
           "本机构投标量（万元）", "本机构中标量（万元）", "交款日", "总投单量（万元）",
           "边际利率/价格", "边际投单量（万元）", "全场倍数", "边际倍数",
           "簿记过程信息更新时间", "簿记过程信息更新频率（分钟）"]

ROWS = [
    ["", "042600007", "26武清经开MTN007", "天津武清经济技术开发区有限公司2026年度第七期中期票据",
     "否", "3000", "0", "10-13", "3000", "1.81%", "1000", "1.77", "2.00", "10-12 17:30", "10"],
    ["", "042600008", "26武清经开MTN008", "天津武清经济技术开发区有限公司2026年度第八期中期票据",
     "否", "2500", "0", "10-13", "2500", "1.87%", "900", "1.55", "1.40", "10-12 17:30", "10"],
    ["", "042600009", "26武清经开MTN009", "天津武清经济技术开发区有限公司2026年度第九期中期票据",
     "否", "4000", "0", "10-14", "4000", "1.95%", "1500", "2.30", "3.10", "10-12 17:30", "10"],
    ["", "012600001", "26天津城投CP001", "天津城市基础设施建设投资集团有限公司2026年度第一期短期融资券",
     "是", "5000", "5000", "10-14", "5000", "2.15%", "5000", "1.20", "1.00", "10-12 17:30", "10"],
]

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def find_font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


# 版式常量（tests/run_tests.py 会读这些值来模拟 OCR 文字框）
PAD = 24
HEADER_H = 34
ROW_H = 30
COL_W = [90, 100, 160, 260, 90, 150, 150, 90, 130, 110, 130, 90, 90, 190, 190]


def layout(scale: int = 1) -> dict:
    """按 scale 缩放后的版式。scale=2 模拟 Retina 截图的像素密度。"""
    s = max(1, int(scale))
    return {
        "scale": s,
        "pad": PAD * s,
        "header_h": HEADER_H * s,
        "row_h": ROW_H * s,
        "col_w": [w * s for w in COL_W],
        "font": 15 * s,
    }


def build(path: str = "sample_table.png", *, scale: int = 1) -> str:
    lay = layout(scale)
    pad, header_h, row_h = lay["pad"], lay["header_h"], lay["row_h"]
    col_w = lay["col_w"]
    body_font = find_font(lay["font"])
    head_font = find_font(lay["font"])
    width = pad * 2 + sum(col_w)
    height = pad * 2 + header_h + row_h * len(ROWS)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # 外框 + 表头
    top = pad
    bottom = top + header_h + row_h * len(ROWS)
    # 整张表一圈外框（真实截图就是这样，外框贯穿全表；只框表头的话外框会太短）
    draw.rectangle([pad, top, width - pad, bottom], outline="black", width=2)
    x = pad
    for idx, name in enumerate(HEADERS):
        right = x + col_w[idx]
        if idx:
            draw.line([x, top, x, top + header_h + row_h * len(ROWS)], fill="black", width=2)
        draw.text((x + 4, top + 6), name, fill="black", font=head_font)
        x = right
    # 横线
    for r in range(len(ROWS) + 1):
        y = top + header_h + row_h * r
        draw.line([pad, y, width - pad, y], fill="black", width=2)
    # 单元格文字
    for r, cells in enumerate(ROWS):
        y = top + header_h + row_h * r
        x = pad
        for c, text in enumerate(cells):
            if text:
                draw.text((x + 4, y + 5), str(text), fill="black", font=body_font)
            x += col_w[c]

    img.save(path)
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "sample_table.png")
    print("已生成样图：" + build(out))
