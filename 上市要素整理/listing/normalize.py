"""文本归一化：把任意输入压成「可以按空格切分」的形态。

这里只做与语义无关的清洗，字段识别在 :mod:`listing.extract`。
"""

from __future__ import annotations

import re
import unicodedata

# 零宽字符、BOM 之类肉眼看不见的东西
_ZERO_WIDTH = {ord(ch): None for ch in "\u200b\u200c\u200d\u2060\ufeff\u00ad"}

# 关系锚点：两侧各加一个空格，方便后续按 token 找「谁出给谁」
_ANCHOR = re.compile(r"(出给|卖给|转给|售予|→|->|=>)")

# 标签和值粘在一起时拆开：净价100 -> 净价 100
_LABEL_VALUE = re.compile(r"(券面|面值|票面|利率|净价|价格|代码|名称|简称)\s*(\d)")

# 日期先于标点处理，避免 10/29 被拆成两个数字
_FULL_DATE = re.compile(r"20\d{2}\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?")
_SHORT_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")

# 各种分隔标点统一成空格（注意：英文句点不能整类替换，小数和后缀要用）
_PUNCT = re.compile(r"[，,、;；|/\\。!！?？\n\r\t]+")
# 只把「不夹在数字中间」的英文句点当分隔符：2.05 / .IB 保留
_LONE_DOT = re.compile(r"(?<!\d)\.(?!\d)")

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """返回归一化后的单行文本。

    - NFKC：全角转半角（％→%、Ａ→A、：→:）
    - 去零宽字符
    - 日期 10/29、2026-10-29 归一成 1029
    - 标点统一成空格
    - 锚点词两侧加空格
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_ZERO_WIDTH)
    text = text.replace("\u3000", " ")
    text = _FULL_DATE.sub(lambda m: f"{int(m.group(1)):02d}{int(m.group(2)):02d}", text)
    text = _SHORT_DATE.sub(lambda m: f"{int(m.group(1)):02d}{int(m.group(2)):02d}", text)
    text = text.replace("：", " ").replace(":", " ")
    text = _PUNCT.sub(" ", text)
    text = _LONE_DOT.sub(" ", text)
    text = _ANCHOR.sub(r" \1 ", text)
    text = _LABEL_VALUE.sub(r"\1 \2", text)
    text = _SPACES.sub(" ", text)
    return text.strip()
