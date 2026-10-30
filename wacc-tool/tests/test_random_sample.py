# -*- coding: utf-8 -*-
"""random_sample 的回归测试：任意种子都应生成可计算的数据。

运行：``python tests/test_random_sample.py``
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from random_sample import generate
from wacc_core import batch_compute


def test_all_seeds_compute():
    for seed in range(500):
        rows = generate(seed)
        assert rows, f"seed {seed}: empty"
        ok, errors = batch_compute(rows)
        assert not errors, f"seed {seed}: {errors}"
        assert len(ok) == len(rows), f"seed {seed}: count mismatch"


def test_covers_three_input_modes():
    seen = {"re": False, "capm": False, "de": False}
    for seed in range(50):
        for row in generate(seed):
            if "DE" in row:
                seen["de"] = True
            elif "Rf" in row:
                seen["capm"] = True
            else:
                seen["re"] = True
    assert all(seen.values()), seen


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL  {name}: {exc}")
    print(f"\n{'全部通过' if failures == 0 else f'{failures} 个失败'}")
    sys.exit(1 if failures else 0)
