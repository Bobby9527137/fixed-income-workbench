# -*- coding: utf-8 -*-
"""random_sample 的回归测试。

运行：``python scripts/test_random_sample.py``
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bondtable import convert_dataframe, load_config, load_tasks
from random_sample import make_demo


def main() -> int:
    config = load_config()
    files = 0
    rows = 0
    for seed in range(200):
        demo = make_demo(seed)
        assert demo, f"seed {seed}: 没有生成文件"
        for name, data in demo:
            tasks = load_tasks(io.BytesIO(data), config, name=name)
            assert tasks, f"seed {seed}: {name} 没有读到工作表"
            for bond, _sheet, frame in tasks:
                assert bond in ("地方债", "信用债"), f"seed {seed}: 债种={bond}"
                result, warnings = convert_dataframe(frame, config, bond)
                assert len(result) > 0, f"seed {seed}: {name} 制表结果为空 {warnings}"
                rows += len(result)
            files += 1
    print(f"全部通过：{files} 个文件，{rows} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
