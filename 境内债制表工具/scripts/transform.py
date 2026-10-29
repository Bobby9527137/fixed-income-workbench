# -*- coding: utf-8 -*-
"""
命令行批量制表入口
==================
用法（在项目根目录 境内债制表工具/ 下运行）：
    python scripts/transform.py --input data/原始数据
    python scripts/transform.py --input data/原始数据/模拟数据_地方债.xlsx
    python scripts/transform.py --input <文件或文件夹> --outdir data/输出

债种自动按文件名 / 工作表名中的“地方债 / 信用债”识别；识别不到的工作表会跳过并提示。
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from bondtable import DEFAULT_OUT_DIR, load_config, load_tasks, process_task


def collect_paths(input_path: str):
    if os.path.isdir(input_path):
        paths = sorted(
            glob.glob(os.path.join(input_path, "*.xlsx"))
            + glob.glob(os.path.join(input_path, "*.xls"))
        )
        return [p for p in paths if not os.path.basename(p).startswith("~$")]
    return [input_path]


def main() -> int:
    ap = argparse.ArgumentParser(description="境内债制表工具 — 命令行批处理")
    ap.add_argument("--input", required=True, help="原始 xlsx/xls 文件或文件夹")
    ap.add_argument("--outdir", default=DEFAULT_OUT_DIR, help="输出文件夹（默认 data/输出）")
    args = ap.parse_args()

    config = load_config()
    paths = collect_paths(args.input)
    if not paths:
        print("未找到可处理的 Excel 文件")
        return 1

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    pd.set_option("display.unicode.east_asian_width", True)

    done, skipped = 0, 0
    for path in paths:
        print(f"\n===== 处理：{os.path.basename(path)} =====")
        try:
            tasks = load_tasks(path, config)
        except Exception as e:
            print(f"  [失败] {e}")
            continue
        for bond_type, sheet, df in tasks:
            if bond_type is None:
                print(f"  [跳过] 工作表《{sheet}》：无法识别债种（文件名/工作表名需含“地方债”或“信用债”）")
                skipped += 1
                continue
            out_path, result, warnings = process_task(df, bond_type, config, args.outdir)
            for w in warnings:
                print(f"  [警告] {w}")
            print(f"  [完成] {bond_type} ← 《{sheet}》原始 {len(df)} 行 → 输出 {len(result)} 行：{os.path.basename(out_path)}")
            if len(result):
                print(result.to_string(index=False))
            done += 1

    print(f"\n汇总：成功 {done} 张，跳过 {skipped} 张 → 输出目录：{os.path.abspath(args.outdir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
