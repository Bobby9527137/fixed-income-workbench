# -*- coding: utf-8 -*-
"""随机示例的回归测试：生成的表格行 / 文本行必须能解析、匹配并出文案。

运行：``python tests/test_sample.py``
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bidbook import rows, sample
from bidbook.table import TableRow


def main() -> int:
    for seed in range(300):
        data = sample.generate(seed)
        inputs = rows.parse_input(data["pasted"], auto_mode="17:30")
        assert len(inputs) == len(data["bonds"]), f"seed {seed}: 文本行数不对"

        values = rows.parse_values(data["values"])
        table = [
            TableRow(
                code=item["code"],
                name=item["name"],
                raw_name=item["name"],
                margin_rate=item["margin_rate"],
                full_ratio=item["full_ratio"],
                edge_ratio=item["edge_ratio"],
                index=index,
            )
            for index, item in enumerate(data["rows"], start=1)
        ]
        matched = rows.match_rows(inputs, table, threshold=0.9, value_rows=values)
        text, formatted = rows.format_results(matched, default_time="17:30")
        assert text.strip(), f"seed {seed}: 文案为空"
        missing = [r.input.name for r in formatted if not r.has_data]
        assert not missing, f"seed {seed}: 没有数据 {missing}"
        assert "待定" not in text, f"seed {seed}: 出现待定\n{text}"

    print("全部通过：300 个种子")
    return 0


if __name__ == "__main__":
    sys.exit(main())
