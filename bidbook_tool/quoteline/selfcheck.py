# -*- coding: utf-8 -*-
"""逻辑自检：不跑 OCR、不联网，只验证解析/合并/拼装和字段定位。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from . import ocr_fields, parse


def _run(name: str, func: Callable[[], str]) -> Dict[str, Any]:
    try:
        detail = func() or ""
        return {"name": name, "ok": True, "detail": detail}
    except Exception as exc:  # noqa: BLE001 - 自检要把失败原因带出来
        return {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _expect(condition: bool, message: str) -> str:
    if not condition:
        raise AssertionError(message)
    return message


def check_sample_parse() -> str:
    fields = parse.parse_trade_text(parse.SAMPLE_TEXT)
    expected = {
        "term": "3D",
        "code": "012681631.IB",
        "name": "26济南城建SCP004",
        "price": "1.80",
        "volume": "3000w",
    }
    for key, value in expected.items():
        _expect(fields.get(key) == value, f"{key} 应为 {value}，实际 {fields.get(key)!r}")
    return "交易行 5 个字段全部认出"


def check_sample_line() -> str:
    line = parse.generate(parse.SAMPLE_TEXT, parse.SAMPLE_OCR, has_image=True)["line"]
    _expect(line == parse.SAMPLE_EXPECTED, f"输出不一致：{line}")
    return parse.SAMPLE_EXPECTED


def check_volume_units() -> str:
    cases = {
        "3000w": "3000w",
        "3000万": "3000w",
        "3,000万": "3000w",
        "1.5亿": "15000w",
        "0.35亿": "3500w",
    }
    for text, expected in cases.items():
        actual = parse.find_volume(text)
        _expect(actual == expected, f"{text} → {actual}，应为 {expected}")
    return "万/亿/千分位都转成 w"


def check_price_format() -> str:
    cases = {
        "1.8*": "1.80",
        "1.805": "1.81",
        "102.68": "102.68",
        "OFR 1.8 3000w": "1.80",
    }
    for text, expected in cases.items():
        actual = parse.find_price(text)
        _expect(actual == expected, f"{text} → {actual}，应为 {expected}")
    return "价格两位小数、四舍五入、星号不重复"


def check_cbt_only_csi_ignored() -> str:
    _expect(parse.find_cbt("中证估值 2.1885/102.6824") == "", "中证估值不应被读成中债")
    _expect(parse.find_cbt("中债估值 --/--") == "--", "中债估值 --/-- 应取 --")
    _expect(parse.find_cbt("中债估值 2.3456/99.1234") == "2.3456", "中债估值应只取第一个值")
    _expect(parse.find_cbt("中债估值 10-26") == "", "日期不应被当成估值")
    return "只读中债、只取第一个值、排除日期"


def check_ratings() -> str:
    cases = {
        "AAA/--": ("AAA", "--"),
        "AAA/AAA": ("AAA", "AAA"),
        "主体AAA 债项AA+": ("AAA", "AA+"),
        "--/AAA": ("--", "AAA"),
    }
    for text, expected in cases.items():
        actual = parse.find_ratings(text)
        _expect(actual == expected, f"{text} → {actual}，应为 {expected}")
    return "主体/债项评级拆分正确"


def check_code_no_suffix() -> str:
    _expect(parse.find_code("26测试债 012345") == "012345", "没写后缀不应补后缀")
    _expect(parse.find_code("26测试债 012345.IB") == "012345.IB", "有后缀应保留")
    _expect(parse.find_code("20260707") == "", "8 位日期不应被当成代码")
    return "代码后缀原样保留，日期不误判"


def check_ocr_cropped() -> str:
    fields = ocr_fields.extract_fields(ocr_fields.SAMPLE_BOXES_CROPPED, 2130, 238)
    expected = {
        "code": "012681631.IB",
        "name": "26济南城建SCP004",
        "offering": "公募",
        "term": "3D",
        "coupon": "1.3600%",
        "cbt": "--",
        "rating_main": "AAA",
    }
    for key, value in expected.items():
        _expect(fields.get(key) == value, f"{key} 应为 {value}，实际 {fields.get(key)!r}")
    _expect(fields.get("rating_bond", "") == "", "裁切图里债项评级应为空（上层默认 --）")
    return "裁切头部：代码/简称/公募/期限/票面/中债/主体评级"


def check_ocr_full() -> str:
    fields = ocr_fields.extract_fields(ocr_fields.SAMPLE_BOXES_FULL, 2260, 470)
    expected = {
        "code": "102682458.IB",
        "name": "26深圳地铁MTN007B",
        "offering": "公募",
        "term": "9.69Y",
        "coupon": "2.5000%",
        "cbt": "--",
        "rating_main": "AAA",
        "rating_bond": "AAA",
    }
    for key, value in expected.items():
        _expect(fields.get(key) == value, f"{key} 应为 {value}，实际 {fields.get(key)!r}")
    return "整窗截图：标题行不取上方标签页，中证/隐含/流动性不串字段"


def check_missing_line() -> str:
    line = parse.build_line({})
    _expect(line.startswith("-- -- -- -- --/-- --/-- --/-- 昨日中债 -- 票面 -- --"), line)
    return line


def run_checks() -> Dict[str, Any]:
    checks = [
        _run("交易行解析", check_sample_parse),
        _run("样例整行输出", check_sample_line),
        _run("带量单位", check_volume_units),
        _run("价格格式", check_price_format),
        _run("中债估值", check_cbt_only_csi_ignored),
        _run("评级", check_ratings),
        _run("代码后缀", check_code_no_suffix),
        _run("截图字段（裁切）", check_ocr_cropped),
        _run("截图字段（整窗）", check_ocr_full),
        _run("缺字段占位", check_missing_line),
    ]
    return {"ok": all(item["ok"] for item in checks), "checks": checks}
