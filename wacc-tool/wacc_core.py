# -*- coding: utf-8 -*-
"""WACC 批量计算核心逻辑（纯函数，无界面 / 无文件 I/O 依赖）。

设计原则
--------
1. 纯函数，便于单元测试与复用。
2. 所有面向用户的错误消息均为中文，通过 :class:`WaccError` 抛出。
3. 单条样本出错不影响其它样本：由 :func:`batch_compute` 负责逐行捕获。

公式
----
V     = E + D
E/V   = 股权权重
D/V   = 债务权重
Re    = Rf + β × ERP           （CAPM，仅在未直接给出 Re 时使用）
税后Rd = Rd × (1 − Tc)
WACC  = (E/V) × Re + (D/V) × Rd × (1 − Tc)
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 视为“空值”的文本记号
_NA_TOKENS = {"", "-", "--", "---", "—", "–", "na", "n/a", "nan", "null", "none", "无", "空"}

# 需要“利率/税费率”换算的参数（可被 pct_mode 影响）
RATE_FIELDS: Tuple[str, ...] = ("Re", "Rf", "ERP", "Rd", "Tc")
# 输入展示用中文名 → 内部字段名
FIELD_LABELS: Dict[str, str] = {
    "sample_id": "样本标识",
    "E": "股权价值 E",
    "D": "债务价值 D",
    "DE": "债务权益比 D/E",
    "Re": "股权成本 Re",
    "Rf": "无风险利率 Rf",
    "beta": "贝塔 β",
    "ERP": "市场风险溢价 ERP",
    "Rd": "债务成本 Rd",
    "Tc": "所得税率 Tc",
}

# 输出列顺序（内部字段名）
RESULT_COLUMNS: Tuple[str, ...] = (
    "样本标识",
    "E",
    "D",
    "D/E",
    "V=E+D",
    "E/V",
    "D/V",
    "Re",
    "Rf",
    "β",
    "ERP",
    "Rd",
    "Tc",
    "税后Rd",
    "WACC",
    "备注",
)

# 结果表中应显示为百分比的列
PERCENT_COLUMNS: Tuple[str, ...] = ("E/V", "D/V", "Re", "Rf", "ERP", "Rd", "Tc", "税后Rd", "WACC")


class WaccError(ValueError):
    """单条样本无法计算时抛出，message 为中文提示。"""


def _with_field(field: str, text: str) -> str:
    label = FIELD_LABELS.get(field, field)
    return f"{label}：{text}" if label else text


def to_float(value: Any, field: str = "") -> Optional[float]:
    """把单元格内容转换为 float。

    - 空值 / 记号（如 ``-``、``N/A``）返回 ``None``；
    - 允许千分位逗号、全角逗号和百分号（会被去掉，仅取数值部分）；
    - 无法解析时抛出中文 :class:`WaccError`。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise WaccError(_with_field(field, f"「{value}」不是有效数字"))
    if isinstance(value, (int, float)):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return None
        return num

    text = str(value).strip()
    if text.lower() in _NA_TOKENS:
        return None

    cleaned = (
        text.replace(",", "")
        .replace("，", "")
        .replace("％", "")
        .replace("%", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    try:
        return float(cleaned)
    except ValueError:
        raise WaccError(_with_field(field, f"「{text}」无法解析为数字")) from None


def resolve_rate(value: Optional[float], pct_mode: str = "auto") -> Optional[float]:
    """把利率 / 税费率统一换算为小数形式（5% → 0.05）。

    ``pct_mode`` 取值：

    - ``"auto"``    ：``abs(value) > 1`` 时视为百分比（÷100），否则视为小数；
    - ``"percent"`` ：一律视为百分比（÷100）；
    - ``"decimal"`` ：一律视为小数，不做换算。
    """
    if value is None:
        return None
    if pct_mode == "percent":
        return value / 100.0
    if pct_mode == "decimal":
        return value
    return value / 100.0 if abs(value) > 1.0 else value


def _resolve_weights(
    E: Optional[float],
    D: Optional[float],
    de: Optional[float],
) -> Tuple[float, float, float, List[str]]:
    """返回 (股权价值, 债务价值, V, 备注列表)。

    规则：优先使用 E 与 D；否则用 D/E 与其中一项互相推导；仅给 D/E 时取 E=1。
    """
    notes: List[str] = []
    if E is not None and D is not None:
        return E, D, E + D, notes
    if E is not None and de is not None:
        D_eff = E * de
        notes.append("由 E 与 D/E 推算 D")
        return E, D_eff, E + D_eff, notes
    if D is not None and de is not None:
        if de == 0:
            raise WaccError(_with_field("DE", "D/E 为 0，无法反推 E"))
        E_eff = D / de
        notes.append("由 D 与 D/E 推算 E")
        return E_eff, D, E_eff + D, notes
    if de is not None:
        E_eff, D_eff = 1.0, float(de)
        notes.append("仅提供 D/E，已按 E=1 换算权重")
        return E_eff, D_eff, E_eff + D_eff, notes
    raise WaccError("缺少资本结构：需要提供 E 与 D，或提供 D/E")


def compute_one(
    sample_id: Any = "",
    E: Any = None,
    D: Any = None,
    DE: Any = None,
    Re: Any = None,
    Rf: Any = None,
    beta: Any = None,
    ERP: Any = None,
    Rd: Any = None,
    Tc: Any = None,
    pct_mode: str = "auto",
) -> Dict[str, Any]:
    """计算单条样本的 WACC。

    返回一个 dict，键与 :data:`RESULT_COLUMNS` 对齐。无法计算时抛出
    :class:`WaccError`（中文消息）。
    """
    notes: List[str] = []

    e_val = to_float(E, "E")
    d_val = to_float(D, "D")
    de_val = to_float(DE, "DE")
    beta_val = to_float(beta, "beta")

    # 资本结构
    if e_val is not None and e_val < 0:
        raise WaccError(_with_field("E", "股权价值不能为负数"))
    if d_val is not None and d_val < 0:
        raise WaccError(_with_field("D", "债务价值不能为负数"))
    e_use, d_use, v_val, weight_notes = _resolve_weights(e_val, d_val, de_val)
    notes.extend(weight_notes)

    if v_val <= 0:
        raise WaccError("E + D 必须大于 0，无法计算资本结构权重")

    w_e = e_use / v_val
    w_d = d_use / v_val

    # 债务成本与税率
    rd_val = resolve_rate(to_float(Rd, "Rd"), pct_mode)
    if rd_val is None:
        raise WaccError(_with_field("Rd", "必填，但为空"))
    tc_val = resolve_rate(to_float(Tc, "Tc"), pct_mode)
    if tc_val is None:
        raise WaccError(_with_field("Tc", "必填，但为空"))
    if tc_val < 0 or tc_val > 1:
        raise WaccError(_with_field("Tc", f"换算后为 {tc_val:.4f}，应在 0~1 之间（0~100%）"))

    # 股权成本：优先直接给出的 Re，其次 CAPM
    re_input = to_float(Re, "Re")
    rf_input = to_float(Rf, "Rf")
    erp_input = to_float(ERP, "ERP")

    if re_input is not None:
        re_val = resolve_rate(re_input, pct_mode)
    elif rf_input is not None and beta_val is not None and erp_input is not None:
        re_val = resolve_rate(rf_input, pct_mode) + beta_val * resolve_rate(erp_input, pct_mode)
        notes.append("Re 由 CAPM（Rf + β×ERP）计算")
    else:
        raise WaccError("缺少股权成本：需要直接给出 Re，或同时给出 Rf、β、ERP")

    rd_after_tax = rd_val * (1.0 - tc_val)
    wacc = w_e * re_val + w_d * rd_after_tax

    return {
        "样本标识": sample_id if sample_id not in (None, "") else "",
        "E": e_use,
        "D": d_use,
        "D/E": (d_use / e_use) if e_use else None,
        "V=E+D": v_val,
        "E/V": w_e,
        "D/V": w_d,
        "Re": re_val,
        "Rf": rf_input,
        "β": beta_val,
        "ERP": erp_input,
        "Rd": rd_val,
        "Tc": tc_val,
        "税后Rd": rd_after_tax,
        "WACC": wacc,
        "备注": "；".join(notes),
    }


def batch_compute(
    rows: Iterable[Dict[str, Any]],
    pct_mode: str = "auto",
) -> Tuple[List[Dict[str, Any]], List[Tuple[int, Dict[str, Any], str]]]:
    """逐行计算。

    :param rows: 每项为 ``compute_one`` 的关键字参数字典。
    :returns: ``(成功结果列表, 失败列表)``；失败列表元素为
              ``(行号(从 1 开始), 原始输入, 中文错误信息)``。
    """
    ok: List[Dict[str, Any]] = []
    errors: List[Tuple[int, Dict[str, Any], str]] = []
    for idx, row in enumerate(rows, start=1):
        try:
            ok.append(compute_one(**row, pct_mode=pct_mode))
        except WaccError as exc:
            errors.append((idx, row, str(exc)))
        except Exception as exc:  # 防御性兜底，绝不因单行数据崩溃
            errors.append((idx, row, f"未预期的错误：{exc}"))
    return ok, errors


def results_to_dataframe_columns() -> Tuple[str, ...]:
    """结果表的列顺序（供界面层直接使用）。"""
    return RESULT_COLUMNS
