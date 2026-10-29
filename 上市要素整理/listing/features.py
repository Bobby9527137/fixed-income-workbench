"""标量特征表。

每个字段的「长什么样、靠什么词定位、怎么防止误判」都集中在这里。
改识别规则优先改本文件，不要把正则散落到 extract.py。

字段与模版的对应（模版见 README）：

    日期+0 上市要素：
    代码 名称  券面  票面  净价100 XX出给YY  发XX请求
    XX信息
    YY信息
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 债券代码
# ---------------------------------------------------------------------------
# 银行间常见 9 位（102683905.IB），交易所 6 位（24xxxx.SH / .SZ），
# 北交所 .BJ。后缀可省，但省了要提示。
CODE_WITH_SUFFIX = re.compile(r"^(?P<num>\d{6,9})\.(?P<suffix>[A-Za-z]{2})$")
CODE_BARE = re.compile(r"^\d{6,9}$")
ALLOWED_SUFFIXES = ("IB", "SH", "SZ", "BJ")

# ---------------------------------------------------------------------------
# 日期 / 偏移
# ---------------------------------------------------------------------------
# 1029、1029+0、1029+1
DATE_TOKEN = re.compile(r"^(?P<month>\d{2})(?P<day>\d{2})(?:\+(?P<offset>\d{1,2}))?$")
# 10月29日、10月29日+0
DATE_CN = re.compile(r"^(?P<month>\d{1,2})月(?P<day>\d{1,2})日(?:\+(?P<offset>\d{1,2}))?$")
# 单独出现的 +0 / T+1
OFFSET_TOKEN = re.compile(r"^(?:\+|T\+|t\+)(?P<offset>\d{1,2})$")

# ---------------------------------------------------------------------------
# 利率 / 价格
# ---------------------------------------------------------------------------
COUPON_PCT = re.compile(r"^(?P<value>\d+(?:\.\d+)?)%$")
COUPON_BP = re.compile(r"^(?P<value>\d+(?:\.\d+)?)\s*(?:bp|BP|Bp|个bp)$")

# ---------------------------------------------------------------------------
# 联系方式
# ---------------------------------------------------------------------------
# 10 位及以上直接按号码处理；8-9 位可能是号码也可能是债券代码，交给上下文判断
CONTACT_NUMBER = re.compile(r"^\d{10,12}$")
CHANNELS = ("QT", "QQ", "WX", "微信", "电话", "手机", "钉钉", "飞书", "邮件", "邮箱")

# ---------------------------------------------------------------------------
# 机构
# ---------------------------------------------------------------------------
# 长后缀优先，避免「农商银行」被「银行」提前截断（endswith 本身没问题，仅用于可读性）
INSTITUTION_SUFFIXES = (
    "农商银行",
    "村镇银行",
    "农商行",
    "城商行",
    "信用社",
    "农信社",
    "银行",
    "证券",
    "基金",
    "信托",
    "保险资管",
    "保险",
    "资管",
    "资产管理",
    "投资",
    "资本",
    "理财",
    "期货",
    "财务",
    "金控",
    "集团",
)

# 含这些词的 token 不可能是机构简称
_BOND_HINT = re.compile(
    r"(MTN|SCP|CP|PPN|ABN|ABS|PRN|债|永续|次级|中票|短融|超短融)", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# 标签词 / 关系锚点 / 噪音词
# ---------------------------------------------------------------------------
LABELS = {
    "上市要素",
    "代码",
    "债券代码",
    "名称",
    "简称",
    "券面",
    "面值",
    "票面",
    "利率",
    "净价",
    "价格",
    "出给",
    "卖给",
    "转给",
    "售予",
    "请求",
}

ANCHORS = ("出给", "卖给", "转给", "售予", "→", "->", "=>")

# 聊天里的客套话，拼名称时要跳过
NOISE = {
    "帮忙",
    "帮忙整理下",
    "看下",
    "看下这个",
    "看看",
    "谢谢",
    "这个",
    "那个",
    "整理",
    "上市",
    "要素",
    "上市要素如下",
    "转发",
    "转发一下",
    "麻烦",
    "一下",
    "请",
    "的",
    "了",
    "和",
    "与",
}


def is_institution(token: str) -> bool:
    """是否像机构简称：有机构后缀，且不是债券名。"""
    if len(token) < 3 or _BOND_HINT.search(token):
        return False
    return any(token.endswith(suffix) for suffix in INSTITUTION_SUFFIXES)


def is_bond_name(token: str) -> bool:
    """是否像债券简称：含债市关键词。"""
    if len(token) < 3:
        return False
    return bool(_BOND_HINT.search(token))


def is_person(token: str) -> bool:
    """是否像中文人名：2-4 个汉字，且不是机构/债券名/标签。"""
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", token):
        return False
    if token in LABELS or token in NOISE:
        return False
    if is_institution(token) or is_bond_name(token):
        return False
    return True


def is_valid_date(month: str, day: str) -> bool:
    try:
        m, d = int(month), int(day)
    except (TypeError, ValueError):
        return False
    return 1 <= m <= 12 and 1 <= d <= 31


def code_has_suffix(code: str) -> bool:
    return bool(CODE_WITH_SUFFIX.match(code or ""))
