# -*- coding: utf-8 -*-
"""wacc_core 单元测试。

既可用 pytest 运行（``python -m pytest tests``），也可直接运行
（``python tests/test_wacc_core.py``），便于没有 pytest 的环境自检。
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wacc_core import WaccError, batch_compute, compute_one, resolve_rate, to_float  # noqa: E402


def _approx(a, b, tol=1e-9):
    assert a is not None and b is not None, f"{a!r} / {b!r} 不应为 None"
    assert math.isclose(a, b, rel_tol=0, abs_tol=tol), f"{a!r} != {b!r}"


def test_to_float_basic():
    assert to_float("1,234.5") == 1234.5
    assert to_float(" 25% ") == 25.0
    assert to_float("") is None
    assert to_float("N/A") is None
    assert to_float(None) is None
    assert to_float(float("nan")) is None


def test_to_float_raises_chinese():
    try:
        to_float("abc", "E")
    except WaccError as exc:
        assert "E" in str(exc) and "无法解析" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛出 WaccError")


def test_resolve_rate_modes():
    _approx(resolve_rate(5.0, "auto"), 0.05)
    _approx(resolve_rate(0.05, "auto"), 0.05)
    _approx(resolve_rate(5.0, "percent"), 0.05)
    _approx(resolve_rate(0.05, "decimal"), 0.05)


def test_wacc_with_e_and_d():
    # E=600, D=400 -> wE=0.6 wD=0.4; Re=10% Rd=5% Tc=25%
    # WACC = 0.6*0.10 + 0.4*0.05*0.75 = 0.06 + 0.015 = 0.075
    r = compute_one(E=600, D=400, Re=10, Rd=5, Tc=25)
    _approx(r["V=E+D"], 1000)
    _approx(r["E/V"], 0.6)
    _approx(r["D/V"], 0.4)
    _approx(r["Re"], 0.10)
    _approx(r["税后Rd"], 0.05 * 0.75)
    _approx(r["WACC"], 0.075)


def test_wacc_with_de_ratio_only():
    # 仅给 D/E=0.5 -> E=1, D=0.5, V=1.5
    r = compute_one(DE=0.5, Re=0.10, Rd=0.05, Tc=0.25, pct_mode="decimal")
    _approx(r["E/V"], 1 / 1.5)
    _approx(r["D/V"], 0.5 / 1.5)
    _approx(r["WACC"], (1 / 1.5) * 0.10 + (0.5 / 1.5) * 0.05 * 0.75)
    assert "D/E" in r["备注"]


def test_capm_path():
    # Rf=3% β=1.2 ERP=5% -> Re=0.03+1.2*0.05=0.09
    r = compute_one(E=100, D=100, Rf=3, beta=1.2, ERP=5, Rd=4, Tc=25)
    _approx(r["Re"], 0.09)
    _approx(r["WACC"], 0.5 * 0.09 + 0.5 * 0.04 * 0.75)


def test_re_takes_priority_over_capm():
    r = compute_one(E=100, D=100, Re=8, Rf=3, beta=1.2, ERP=5, Rd=4, Tc=25)
    _approx(r["Re"], 0.08)


def test_missing_structure_raises():
    try:
        compute_one(E=100, Re=10, Rd=5, Tc=25)
    except WaccError as exc:
        assert "资本结构" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛出 WaccError")


def test_missing_re_raises():
    try:
        compute_one(E=100, D=100, Rf=3, Rd=5, Tc=25)
    except WaccError as exc:
        assert "股权成本" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛出 WaccError")


def test_zero_equity_and_debt_raises():
    try:
        compute_one(E=0, D=0, Re=10, Rd=5, Tc=25)
    except WaccError as exc:
        assert "大于 0" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛出 WaccError")


def test_negative_equity_raises():
    try:
        compute_one(E=-100, D=100, Re=10, Rd=5, Tc=25)
    except WaccError as exc:
        assert "负数" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛出 WaccError")


def test_batch_skips_bad_rows_without_crashing():
    rows = [
        {"sample_id": "A", "E": 600, "D": 400, "Re": 10, "Rd": 5, "Tc": 25},
        {"sample_id": "B", "E": "abc", "D": 400, "Re": 10, "Rd": 5, "Tc": 25},
        {"sample_id": "C", "E": 100, "D": 0, "Re": "10", "Rd": 5, "Tc": 25},
        {"sample_id": "D", "E": 100, "D": 100, "Re": 10, "Rd": 5, "Tc": 200},
    ]
    ok, errors = batch_compute(rows)
    assert len(ok) == 2
    assert [e[0] for e in errors] == [2, 4]
    assert all(isinstance(e[2], str) and e[2] for e in errors)
    assert ok[0]["样本标识"] == "A"
    assert ok[1]["样本标识"] == "C"


def test_blank_is_missing_not_error():
    r = compute_one(E=100, D=100, Re=10, Rd=5, Tc=25, Rf=None)
    assert r["Rf"] is None


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
