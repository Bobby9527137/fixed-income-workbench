from __future__ import annotations

import unittest

from listing.extract import parse
from listing.mock import generate
from listing.render import render

USER_SAMPLE = """1029+0 上市要素：
102683800  26 上饶产投 MTN001  券面 100  票面 2.05%  净价 100  江城银行出给龙头证券  发江城银行请求
江城银行 刘如烟 QT 2555555555
龙头证券 陈默 QT 2555555556"""


class UserSampleTest(unittest.TestCase):
    def test_named_fields(self) -> None:
        result = parse(USER_SAMPLE)
        fields = result.fields
        self.assertEqual(fields["date"], "1029")
        self.assertEqual(fields["offset"], "+0")
        self.assertEqual(fields["code"], "102683800")
        self.assertEqual(fields["name"], "26上饶产投MTN001")
        self.assertEqual(fields["face"], "100")
        self.assertEqual(fields["coupon"], "2.05%")
        self.assertEqual(fields["net"], "100")
        self.assertEqual(fields["seller"], "江城银行")
        self.assertEqual(fields["buyer"], "龙头证券")
        self.assertEqual(fields["seller_contact"]["person"], "刘如烟")
        self.assertEqual(fields["seller_contact"]["channel"], "QT")
        self.assertEqual(fields["seller_contact"]["number"], "2555555555")
        self.assertEqual(fields["buyer_contact"]["person"], "陈默")
        self.assertEqual(fields["buyer_contact"]["number"], "2555555556")

    def test_render_matches_template(self) -> None:
        output = render(parse(USER_SAMPLE).fields)
        self.assertEqual(
            output,
            "\n".join(
                [
                    "1029+0 上市要素：",
                    "102683800  26上饶产投MTN001  券面 100  票面 2.05%  净价 100  江城银行出给龙头证券  发江城银行请求",
                    "江城银行 刘如烟 QT 2555555555",
                    "龙头证券 陈默 QT 2555555556",
                ]
            ),
        )

    def test_missing_suffix_warns(self) -> None:
        warnings = parse(USER_SAMPLE).warnings
        self.assertTrue(any("后缀" in item for item in warnings), warnings)

    def test_round_trip_is_stable(self) -> None:
        first = parse(USER_SAMPLE)
        once = render(first.fields)
        again = parse(once)
        self.assertEqual(render(again.fields), once)


class RandomizedLayoutTest(unittest.TestCase):
    """把生成器的每种排版都跑一遍，确认乱序不影响结果。"""

    FIELDS = ("date", "offset", "code", "name", "face", "coupon", "net", "seller", "buyer")
    CONTACT_FIELDS = ("inst", "person", "channel", "number")

    def test_all_layouts_and_seeds(self) -> None:
        for layout in ("labeled", "shuffled", "chatty", "dense", "fullwidth"):
            for seed in range(12):
                with self.subTest(layout=layout, seed=seed):
                    text, expected = generate(seed=seed, layout=layout)
                    result = parse(text)
                    for key in self.FIELDS:
                        self.assertEqual(
                            result.fields[key], expected[key], f"{layout}/{seed}/{key}\n{text}"
                        )
                    for side in ("seller_contact", "buyer_contact"):
                        for key in self.CONTACT_FIELDS:
                            self.assertEqual(
                                result.fields[side][key],
                                expected[side][key],
                                f"{layout}/{seed}/{side}.{key}\n{text}",
                            )


class NormalizationTest(unittest.TestCase):
    def test_fullwidth_and_chinese_date(self) -> None:
        text = "１０月２９日＋０ 上市要素：１０２６８３９０５．ＩＢ ２６上饶产投ＭＴＮ００１ 券面１００ 票面２．０５％ 净价１００ 江城银行出给龙头证券 发江城银行请求 江城银行 刘如烟 ＱＴ ２５５５５５５５５５ 龙头证券 陈默 ＱＴ ２５５５５５５５５６"
        fields = parse(text).fields
        self.assertEqual(fields["date"], "1029")
        self.assertEqual(fields["offset"], "+0")
        self.assertEqual(fields["code"], "102683905.IB")
        self.assertEqual(fields["coupon"], "2.05%")
        self.assertEqual(fields["seller"], "江城银行")

    def test_chat_noise_before_and_after(self) -> None:
        text = "帮忙整理下\n" + USER_SAMPLE + "\n谢谢"
        fields = parse(text).fields
        self.assertEqual(fields["code"], "102683800")
        self.assertEqual(fields["name"], "26上饶产投MTN001")

    def test_bp_coupon(self) -> None:
        text = USER_SAMPLE.replace("2.05%", "205bp")
        self.assertEqual(parse(text).fields["coupon"], "2.05%")

    def test_attached_labels_and_separate_offset(self) -> None:
        text = "1029 +0 上市要素 102683905.IB 26上饶产投MTN001 券面100 票面2.05% 净价100 江城银行卖给龙头证券 发江城银行请求 江城银行 刘如烟 QT 2555555555 龙头证券 陈默 QT 2555555556"
        fields = parse(text).fields
        self.assertEqual(fields["date"], "1029")
        self.assertEqual(fields["offset"], "+0")
        self.assertEqual(fields["face"], "100")
        self.assertEqual(fields["coupon"], "2.05%")
        self.assertEqual(fields["net"], "100")
        self.assertEqual(fields["seller"], "江城银行")

    def test_arrow_anchor(self) -> None:
        text = USER_SAMPLE.replace("出给", "→")
        fields = parse(text).fields
        self.assertEqual(fields["seller"], "江城银行")
        self.assertEqual(fields["buyer"], "龙头证券")


if __name__ == "__main__":
    unittest.main()
