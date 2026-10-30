# -*- coding: utf-8 -*-
"""WACC 随机示例：生成一组随机但合理的参数。

只依赖标准库，方便被 ``app.py`` 直接 import。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List


def generate(seed: int | None = None, count: int | None = None) -> List[Dict[str, Any]]:
    """返回 ``batch_compute`` 可直接使用的行列表。

    混合三种输入方式，覆盖工具的三条计算路径：

    - 直接给 ``Re``；
    - 给 ``Rf + β + ERP``，走 CAPM；
    - 只给 ``D/E``，由工具按 E=1 换算权重。
    """
    rng = random.Random(seed)
    total = count if count is not None else rng.randint(6, 10)
    rows: List[Dict[str, Any]] = []

    for index in range(total):
        mode = rng.choice(("re", "re", "re", "capm", "de"))
        row: Dict[str, Any] = {"sample_id": f"随机{index + 1:02d}"}

        if mode == "de":
            row["DE"] = round(rng.uniform(0.2, 2.0), 2)
        else:
            row["E"] = float(round(rng.uniform(500, 20000), 0))
            row["D"] = float(round(rng.uniform(100, 10000), 0))

        if mode == "capm":
            row["Rf"] = round(rng.uniform(2.0, 4.0), 2)
            row["beta"] = round(rng.uniform(0.6, 1.8), 2)
            row["ERP"] = round(rng.uniform(4.0, 8.0), 2)
        else:
            row["Re"] = round(rng.uniform(7.0, 18.0), 2)

        row["Rd"] = round(rng.uniform(3.0, 8.0), 2)
        row["Tc"] = rng.choice((15.0, 20.0, 25.0))
        rows.append(row)

    return rows
