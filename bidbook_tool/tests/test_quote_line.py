# -*- coding: utf-8 -*-
"""报价要素生成工具的逻辑测试（不跑真实 OCR、不联网）。

跑法（在固收工作台目录）：
    py -3.11 ../bidbook_tool/tests/test_quote_line.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quoteline import ocr_fields, parse, selfcheck  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_sample_fields(self) -> None:
        fields = parse.parse_trade_text(parse.SAMPLE_TEXT)
        self.assertEqual(fields["term"], "3D")
        self.assertEqual(fields["code"], "012681631.IB")
        self.assertEqual(fields["name"], "26济南城建SCP004")
        self.assertEqual(fields["price"], "1.80")
        self.assertEqual(fields["volume"], "3000w")

    def test_sample_line(self) -> None:
        result = parse.generate(parse.SAMPLE_TEXT, parse.SAMPLE_OCR, has_image=True)
        self.assertEqual(result["line"], parse.SAMPLE_EXPECTED)
        self.assertEqual(result["sources"]["offering"], "ocr")
        self.assertEqual(result["sources"]["price"], "text")

    def test_volume_units(self) -> None:
        cases = {
            "3000w": "3000w",
            "3000万": "3000w",
            "3,000万": "3000w",
            "1.5亿": "15000w",
            "0.35亿": "3500w",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse.find_volume(text), expected)

    def test_price_rounding_and_star(self) -> None:
        self.assertEqual(parse.find_price("1.8*"), "1.80")
        self.assertEqual(parse.find_price("1.805"), "1.81")
        self.assertEqual(parse.find_price("102.68"), "102.68")
        self.assertEqual(parse.find_price("OFR 1.8 3000w"), "1.80")

    def test_cbt_never_reads_csi(self) -> None:
        self.assertEqual(parse.find_cbt("中证估值 2.1885/102.6824"), "")
        self.assertEqual(parse.find_cbt("中债估值 --/--"), "--")
        self.assertEqual(parse.find_cbt("中债估值 2.3456/99.1234"), "2.3456")
        self.assertEqual(parse.find_cbt("中债估值 10-26"), "")

    def test_ratings(self) -> None:
        cases = {
            "AAA/--": ("AAA", "--"),
            "AAA/AAA": ("AAA", "AAA"),
            "主体AAA 债项AA+": ("AAA", "AA+"),
            "--/AAA": ("--", "AAA"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse.find_ratings(text), expected)

    def test_code_suffix_is_not_invented(self) -> None:
        self.assertEqual(parse.find_code("26测试债 012345"), "012345")
        self.assertEqual(parse.find_code("26测试债 012345.IB"), "012345.IB")
        self.assertEqual(parse.find_code("20260707"), "")

    def test_missing_fields_use_dash(self) -> None:
        line = parse.build_line({})
        self.assertTrue(line.startswith("-- -- -- -- --/-- --/-- --/-- 昨日中债 -- 票面 -- --"), line)


class OcrFieldTest(unittest.TestCase):
    def test_cropped_header(self) -> None:
        fields = ocr_fields.extract_fields(ocr_fields.SAMPLE_BOXES_CROPPED, 2130, 238)
        self.assertEqual(fields["code"], "012681631.IB")
        self.assertEqual(fields["name"], "26济南城建SCP004")
        self.assertEqual(fields["offering"], "公募")
        self.assertEqual(fields["term"], "3D")
        self.assertEqual(fields["coupon"], "1.3600%")
        self.assertEqual(fields["cbt"], "--")
        self.assertEqual(fields["rating_main"], "AAA")
        self.assertNotIn("rating_bond", fields)

    def test_full_window_does_not_pick_tab_or_csi(self) -> None:
        fields = ocr_fields.extract_fields(ocr_fields.SAMPLE_BOXES_FULL, 2260, 470)
        self.assertEqual(fields["code"], "102682458.IB")
        self.assertEqual(fields["name"], "26深圳地铁MTN007B")
        self.assertEqual(fields["offering"], "公募")
        self.assertEqual(fields["term"], "9.69Y")
        self.assertEqual(fields["coupon"], "2.5000%")
        self.assertEqual(fields["cbt"], "--")
        self.assertEqual(fields["rating_main"], "AAA")
        self.assertEqual(fields["rating_bond"], "AAA")

    def test_full_window_line(self) -> None:
        fields = ocr_fields.extract_fields(ocr_fields.SAMPLE_BOXES_FULL, 2260, 470)
        text = "26深圳地铁MTN007B 102682458.IB 9.69Y 1.80* 3000w"
        line = parse.generate(text, fields, has_image=True)["line"]
        self.assertEqual(
            line,
            "9.69Y 102682458.IB 26深圳地铁MTN007B 公募 --/1.80* --/3000w "
            "AAA/AAA 昨日中债 -- 票面 2.5000% 3000w",
        )


class SelfcheckTest(unittest.TestCase):
    def test_all_checks_pass(self) -> None:
        result = selfcheck.run_checks()
        failed = [item for item in result["checks"] if not item["ok"]]
        self.assertTrue(result["ok"], failed)
        self.assertEqual(len(result["checks"]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
