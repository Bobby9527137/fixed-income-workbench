# -*- coding: utf-8 -*-
"""模糊匹配的薄封装。

优先用 rapidfuzz（快、准）；万一装不上或公司网络受限，自动退回到
标准库 difflib —— 匹配效果差一点点，但整个工具照样能用，
不会因为一个可选依赖把程序拦在门外。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

try:  # pragma: no cover - 取决于运行环境
    from rapidfuzz import fuzz as _rf

    HAS_RAPIDFUZZ = True
except Exception:  # noqa: BLE001
    _rf = None
    HAS_RAPIDFUZZ = False


_PUNCT_RE = re.compile(r"[\s\(\)\[\]【】（）·・,，.。;；:：/／\\\-_—－]+")


def _clean(text) -> str:
    text = "" if text is None else str(text)
    text = text.upper()
    text = _PUNCT_RE.sub("", text)
    return text


def _difflib_ratio(a, b) -> float:
    aa, bb = _clean(a), _clean(b)
    if not aa or not bb:
        return 0.0
    return SequenceMatcher(None, aa, bb).ratio() * 100.0


def _difflib_partial_ratio(a, b) -> float:
    aa, bb = _clean(a), _clean(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return 100.0
    shorter, longer = (aa, bb) if len(aa) <= len(bb) else (bb, aa)
    window = max(1, len(shorter))
    best = 0.0
    limit = max(1, len(longer) - window + 1)
    for start in range(limit):
        part = longer[start:start + window]
        if not part:
            continue
        best = max(best, SequenceMatcher(None, shorter, part).ratio())
    return best * 100.0


def _difflib_token_set_ratio(a, b) -> float:
    aa, bb = _clean(a), _clean(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return 100.0
    return _difflib_ratio(aa, bb)


if HAS_RAPIDFUZZ:

    def _guarded(fn, fallback):
        def wrapper(a, b) -> float:
            try:
                return float(fn(a, b))
            except Exception:  # noqa: BLE001 - 个别脏文本可能触发上游异常
                return float(fallback(a, b))

        return wrapper

    ratio = _guarded(_rf.ratio, _difflib_ratio)
    partial_ratio = _guarded(_rf.partial_ratio, _difflib_partial_ratio)
    token_set_ratio = _guarded(_rf.token_set_ratio, _difflib_token_set_ratio)

else:

    ratio = _difflib_ratio
    partial_ratio = _difflib_partial_ratio
    token_set_ratio = _difflib_token_set_ratio
