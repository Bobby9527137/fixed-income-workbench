# -*- coding: utf-8 -*-
"""生成示例 Excel（examples/示例数据.xlsx）。

运行：``python tools/make_example_data.py``
仅依赖 pandas + openpyxl。
"""

from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "examples")
OUT_FILE = os.path.join(OUT_DIR, "示例数据.xlsx")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    full = pd.DataFrame(
        {
            "样本标识": ["甲公司", "乙公司", "丙公司", "丁公司", "戊公司"],
            "股权价值E": [6000, 2500, 800, 12000, 1500],
            "债务价值D": [4000, 1500, 200, 3000, 500],
            "股权成本Re": [10, 12, 9.5, 8, 15],
            "债务成本Rd": [5, 6.5, 4.8, 5.2, 7],
            "所得税率Tc": [25, 25, 15, 20, 25],
        }
    )

    capm = pd.DataFrame(
        {
            "样本标识": ["A项目", "B项目", "C项目"],
            "股权价值E": [1000, 2000, 500],
            "债务价值D": [500, 800, 100],
            "无风险利率Rf": [3, 3, 2.5],
            "贝塔β": [1.2, 0.9, 1.6],
            "市场风险溢价ERP": [5, 5.5, 6],
            "债务成本Rd": [4.5, 5, 6],
            "所得税率Tc": [25, 25, 15],
        }
    )

    ratio_only = pd.DataFrame(
        {
            "样本标识": ["按比值-1", "按比值-2", "按比值-3"],
            "债务权益比D/E": [0.5, 1.0, 1.8],
            "股权成本Re": [11, 10, 13],
            "债务成本Rd": [5, 5.5, 6],
            "所得税率Tc": [25, 25, 25],
        }
    )

    dirty = pd.DataFrame(
        {
            "样本标识": ["正常", "坏数据", "缺税率", "股权为负", "全空"],
            "股权价值E": [1000, "abc", 800, -500, None],
            "债务价值D": [500, 400, 200, 300, None],
            "股权成本Re": [10, 11, 9, 12, None],
            "债务成本Rd": [5, 5, 5, 5, None],
            "所得税率Tc": [25, 25, None, 25, None],
        }
    )

    notes = pd.DataFrame(
        {
            "工作表": ["完整参数", "CAPM", "仅D/E比值", "含异常行", "说明"],
            "用途": [
                "E、D、Re、Rd、Tc 全部给齐，最常用",
                "用 Rf、β、ERP 通过 CAPM 计算 Re",
                "只给 D/E，工具自动按 E=1 换算权重",
                "故意混入坏数据，用于验证异常行会被跳过而不崩溃",
                "本说明页",
            ],
        }
    )

    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        full.to_excel(writer, index=False, sheet_name="完整参数")
        capm.to_excel(writer, index=False, sheet_name="CAPM")
        ratio_only.to_excel(writer, index=False, sheet_name="仅D-E比值")
        dirty.to_excel(writer, index=False, sheet_name="含异常行")
        notes.to_excel(writer, index=False, sheet_name="说明")
    print(f"已生成：{OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
