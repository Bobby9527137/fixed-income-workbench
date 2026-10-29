# -*- coding: utf-8 -*-
"""真机 OCR 端到端冒烟：生成一张样图 -> 真的跑 OCR -> 真的重建表格 -> 核对三列数值。

跑法（项目根目录）：
    python3 tests/ocr_smoke.py

需要装好一个 OCR 引擎（RapidOCR / macOS Vision / tesseract 任一）。没有引擎时会跳过而不是报错，
因为「没有引擎」本身已经在普通自检里覆盖了（网页会给出中文提示）。首次运行要加载模型，慢一点是正常的。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from bidbook import ocr as ocr_mod  # noqa: E402
from bidbook import table as table_mod  # noqa: E402
from tests import make_sample  # noqa: E402

EXPECT = {
    "26武清经开MTN007": (1.81, 1.77, 2.00),
    "26武清经开MTN008": (1.87, 1.55, 1.40),
    "26武清经开MTN009": (1.95, 2.30, 3.10),
    "26天津城投CP001": (2.15, 1.20, 1.00),
}


def main() -> int:
    engines = ocr_mod.available_engines()
    ready = [e["key"] for e in engines if e.get("available")]
    print("[i] 可用引擎：" + (", ".join(ready) if ready else "无"))
    if not ready:
        print("[~] 本机没有可用的 OCR 引擎，跳过真机冒烟测试。")
        return 0

    scale = int(__import__("os").environ.get("BIDBOOK_TEST_SCALE", "2"))
    img_path = Path(tempfile.gettempdir()) / "bidbook_ocr_smoke.png"
    make_sample.build(str(img_path), scale=scale)
    img = Image.open(img_path)
    print("[i] 样图 %s  尺寸 %s  缩放 %d" % (img_path, img.size, scale))

    engine, boxes = ocr_mod.run_ocr(img, engine="auto")
    print("[i] 引擎 %s，识别到 %d 个文字块" % (engine, len(boxes)))
    if boxes:
        print("    前几个：" + " / ".join(b.text for b in boxes[:6]))

    bgr = np.array(img.convert("RGB"))[:, :, ::-1].copy()
    table, rows = table_mod.parse_image(bgr, boxes, guess_columns=True)
    print("[i] 表格方式 %s，列数 %d，行数 %d" % (table.method, len(table.columns), len(rows)))
    print("    表头识别：" + " | ".join(t or "?" for t in table.column_texts))

    bad = []
    if len(rows) != 4:
        bad.append("行数不是 4（实际 %d）" % len(rows))
    for need in table_mod.NEEDED_FIELDS:
        if need not in (table.header_map or {}).values():
            bad.append("没认出列：" + need)

    seen = 0
    for row in rows:
        want = None
        for key, val in EXPECT.items():
            if key and row.name and (row.name in key or key in row.name):
                want = val
                break
        line = "    %-18s 边际=%s 全场=%s 边际倍数=%s" % (
            row.name, row.margin_rate, row.full_ratio, row.edge_ratio)
        print(line)
        if want is None:
            bad.append("没见过的行：" + str(row.name))
            continue
        seen += 1
        got = (row.margin_rate, row.full_ratio, row.edge_ratio)
        for idx, label in enumerate(("边际利率", "全场倍数", "边际倍数")):
            a, b = got[idx], want[idx]
            if a is None or abs(a - b) > 0.005:
                bad.append("%s 的%s 应该是 %s，实际 %s" % (row.name, label, b, a))

    if seen != 4:
        bad.append("只有 %d 行对上了预期" % seen)

    if bad:
        print("")
        print("真机 OCR 冒烟：失败")
        for item in bad:
            print("  - " + item)
        return 1

    print("")
    print("真机 OCR 冒烟：4 行三列数值全部正确（引擎 " + engine + "，缩放 " + str(scale) + "）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
