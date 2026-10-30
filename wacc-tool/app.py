# -*- coding: utf-8 -*-
"""WACC 批量计算工具 —— Streamlit 网页界面。

启动方式（无需手敲命令）：
- macOS   ：双击 ``macOS/启动WACC工具.command``
- Windows ：双击 ``Windows/启动WACC工具.bat``

界面共三种模式：
- 模式一：上传 .xlsx / .xls / .csv，选工作表后用下拉框把各参数“连线”到列；
- 模式二：用可编辑表格直接录入多组参数；
- 模式三：随机示例，自动生成一组参数并计算，用于快速检查输出是否正常。
"""

from __future__ import annotations

import hashlib
import io
import random
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from wacc_core import (
    PERCENT_COLUMNS,
    RESULT_COLUMNS,
    WaccError,
    batch_compute,
)

from random_sample import generate as generate_random_rows

st.set_page_config(page_title="WACC 批量计算工具", page_icon="📊", layout="wide")


def _stretch(func, *args, **kwargs):
    """让控件占满容器宽度，同时兼容新旧 Streamlit 的参数名。"""
    try:
        return func(*args, width="stretch", **kwargs)
    except Exception:  # 旧版本不认识 width
        return func(*args, use_container_width=True, **kwargs)


def display_safe(df: pd.DataFrame) -> pd.DataFrame:
    """把“同一列里混了数字和文字”的列统一转成文本。

    Streamlit 用 Arrow 展示表格时，object 列混类型会转换失败（虽然会自动兜底，
    但日志里会留下报错）。这里提前处理，避免噪音与旧版本可能的报错。
    """
    out = df.copy()
    for col in out.columns:
        series = out[col]
        if not pd.api.types.is_object_dtype(series):
            continue
        non_null = series.dropna()
        if non_null.empty:
            continue
        kinds = {type(v) for v in non_null}
        if len(kinds) > 1:
            out[col] = series.map(
                lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            )
    return out

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
NOT_USED = "—（不使用）"
MANUAL = "✏️ 手动输入固定值"
AUTO_ID = "自动编号（行号）"

PCT_MODE_LABELS = {
    "自动识别（推荐）": "auto",
    "按小数解读（0.05 = 5%）": "decimal",
    "按百分比解读（5 = 5%）": "percent",
}

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1")

# 参数定义。
# required=True 为“必填”，required=False 为“可选”（其中 D/E 与 Rf+β+ERP 是可替代必填项的可选组合）。
# unit 只用于界面提示：WACC 只取决于 E 与 D 的比例，金额单位本身不影响结果。
PARAM_DEFS: List[Dict[str, Any]] = [
    {"key": "E", "label": "股权价值 E", "unit": "金额", "required": True,
     "manual": True, "manual_default": 0.0,
     "help": "与 D 一起决定资本结构权重。金额单位只要与 D 一致即可（如都按百万元填）。"},
    {"key": "D", "label": "债务价值 D", "unit": "金额", "required": True,
     "manual": True, "manual_default": 0.0,
     "help": "与 E 一起决定资本结构权重。金额单位与 E 保持一致。"},
    {"key": "DE", "label": "债务权益比 D/E", "unit": "倍数", "required": False,
     "manual": True, "manual_default": 0.0,
     "help": "可选替代项：没有 E、D 时用它替代「E + D」，工具会自动按 E=1 换算权重。"},
    {"key": "Re", "label": "股权成本 Re", "unit": "年化收益率", "required": True,
     "manual": True, "manual_default": 0.0,
     "help": "与下面的 CAPM 组合二选一；直接给出 Re 时优先使用。"},
    {"key": "Rf", "label": "无风险利率 Rf", "unit": "年化收益率", "required": False,
     "manual": True, "manual_default": 0.0,
     "help": "CAPM 组合之一：Re = Rf + β × ERP。"},
    {"key": "beta", "label": "贝塔 β", "unit": "倍数（无量纲）", "required": False,
     "manual": True, "manual_default": 1.0,
     "help": "CAPM 组合之一；不参与百分比换算。"},
    {"key": "ERP", "label": "市场风险溢价 ERP", "unit": "年化收益率", "required": False,
     "manual": True, "manual_default": 0.0,
     "help": "CAPM 组合之一。"},
    {"key": "Rd", "label": "债务成本 Rd", "unit": "年化利率（税前）", "required": True,
     "manual": True, "manual_default": 0.0,
     "help": "必填。"},
    {"key": "Tc", "label": "所得税率 Tc", "unit": "如 25% 或 0.25", "required": True,
     "manual": True, "manual_default": 0.25,
     "help": "必填，按小数或百分比均可（自动识别）。"},
]

PARAM_BY_KEY: Dict[str, Dict[str, Any]] = {d["key"]: d for d in PARAM_DEFS}

PARAM_DISPLAY: Dict[str, str] = {
    "sample_id": "样本标识",
    "E": "股权价值 E", "D": "债务价值 D", "DE": "债务权益比 D/E",
    "Re": "股权成本 Re", "Rf": "无风险利率 Rf", "beta": "贝塔 β",
    "ERP": "市场风险溢价 ERP", "Rd": "债务成本 Rd", "Tc": "所得税率 Tc",
}

# 自动识别列名用的关键词。按 GUESS_ORDER 顺序抢占列，先到先得，避免一列被重复分配。
GUESS_ORDER: Tuple[str, ...] = (
    "sample_id", "DE", "Re", "Rf", "ERP", "beta", "Rd", "Tc", "E", "D",
)
GUESS_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "sample_id": ("样本标识", "样本编号", "样本", "序号", "编号", "证券代码", "股票代码",
                  "代码", "公司名称", "公司", "名称", "id", "name", "ticker", "code"),
    "DE": ("债务权益比", "债务股权比", "产权比率", "d/e", "de比率", "deratio"),
    "Re": ("股权成本", "权益成本", "股权资本成本", "cost of equity", "re"),
    "Rf": ("无风险利率", "无风险", "risk-free", "riskfree", "rf"),
    "ERP": ("市场风险溢价", "风险溢价", "erp", "mrp", "市场溢价"),
    "beta": ("贝塔", "beta", "β"),
    "Rd": ("债务成本", "税前债务成本", "债务利息率", "借款利率", "贷款利率", "cost of debt", "rd"),
    "Tc": ("所得税率", "所得税", "税率", "taxrate", "tax", "tc"),
    "E": ("股权价值", "权益价值", "股权市值", "股东权益", "所有者权益", "equity", "e"),
    "D": ("债务价值", "负债价值", "债务市值", "有息负债", "负债合计", "debt", "d"),
}
# 太短或太通用的英文关键词，必须与列名完全相同才算命中（避免 "re" 误配到别的词里）
_EXACT_ONLY_KEYWORDS = {"re", "rd", "rf", "tc", "erp", "id", "e", "d"}

COMPONENT_GLOSSARY = """
| 符号 | 含义 | 单位 |
| --- | --- | --- |
| E | 股权价值 | 金额，如百万元 |
| D | 债务价值 | 金额，与 E 同单位 |
| V | 资本总额 = E + D | 同 E |
| E/V | 股权权重 | — |
| D/V | 债务权重 | — |
| Re | 股权成本 | 年化收益率 |
| Rf | 无风险利率 | 年化收益率 |
| β | 贝塔（系统性风险） | 倍数，无量纲 |
| ERP | 市场风险溢价 | 年化收益率 |
| Rd | 债务成本（税前） | 年化利率 |
| Tc | 所得税率 | 如 25% 或 0.25 |
| D/E | 债务权益比 | 倍数 |

**股权成本二选一**：直接给 `Re`；或给出 `Rf`、`β`、`ERP`，用 CAPM 算 `Re = Rf + β×ERP`。

**资本结构二选一**：给出 `E` 与 `D`；或只给 `D/E`（自动按 E=1 换算权重）。
"""


def param_label(defn: Dict[str, Any], amount_unit: str = "百万元") -> str:
    """拼出带「必填/可选」与单位提示的控件标题。"""
    key = defn["key"]
    unit = f"金额，如：{amount_unit}" if key in ("E", "D") else defn["unit"]
    mark = "【必填】" if defn["required"] else "【可选】"
    return f"{mark}{defn['label']}（{unit}）"


def _norm_header(text: Any) -> str:
    return str(text).strip().lower().replace(" ", "").replace("\u3000", "")


def _keyword_hits(column_norm: str, keyword: str) -> bool:
    kw = keyword.lower()
    if kw in _EXACT_ONLY_KEYWORDS:
        return column_norm == kw
    return kw in column_norm


def guess_mapping(columns: List[str]) -> Dict[str, str]:
    """按列名猜测“哪一列是哪个参数”，用作下拉框的默认选中项。

    先猜到的列会被占用，避免同一列被重复分配；猜不出来就不猜，交给手动选择。
    """
    used = set()
    result: Dict[str, str] = {}
    for key in GUESS_ORDER:
        for col in columns:
            if col in used:
                continue
            norm = _norm_header(col)
            if not norm:
                continue
            if any(_keyword_hits(norm, kw) for kw in GUESS_KEYWORDS[key]):
                result[key] = col
                used.add(col)
                break
    return result


# --------------------------------------------------------------------------- #
# 读取上传文件
# --------------------------------------------------------------------------- #
def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """把空列名 / Unnamed 列名替换为可读名称，并保证列名唯一。"""
    df = df.copy()
    seen: Dict[str, int] = {}
    new_cols: List[str] = []
    for i, col in enumerate(df.columns):
        name = str(col).strip()
        if name == "" or name.lower() in ("nan", "none") or name.startswith("Unnamed:"):
            name = f"第{i + 1}列"
        if name in seen:
            seen[name] += 1
            name = f"{name}({seen[name]})"
        else:
            seen[name] = 0
        new_cols.append(name)
    df.columns = new_cols
    return df


def list_sheets(filename: str, data: bytes) -> List[str]:
    """返回文件内的工作表名；CSV 只有一张。"""
    if filename.lower().endswith(".csv"):
        return ["（CSV 文件）"]
    try:
        with pd.ExcelFile(io.BytesIO(data)) as xls:
            return [str(s) for s in xls.sheet_names]
    except ImportError as exc:
        raise WaccError(f"缺少读取该表格所需的组件：{exc}") from None
    except Exception as exc:  # noqa: BLE001
        raise WaccError(f"无法读取该表格：{exc}") from None


def read_table(filename: str, data: bytes, sheet: Optional[str], header_row: int = 0) -> pd.DataFrame:
    """读取指定工作表 / CSV 为 DataFrame。"""
    if filename.lower().endswith(".csv"):
        return _read_csv(data, header_row)
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=header_row)
    except ImportError as exc:
        raise WaccError(f"缺少读取该表格所需的组件：{exc}") from None
    except Exception as exc:  # noqa: BLE001
        raise WaccError(f"读取工作表「{sheet}」失败：{exc}") from None
    if isinstance(df, dict):  # 理论上不会发生，防御性处理
        df = next(iter(df.values()))
    return _normalize_columns(df)


def _read_csv(data: bytes, header_row: int) -> pd.DataFrame:
    last_error: Optional[Exception] = None
    for enc in CSV_ENCODINGS:
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=enc, header=header_row,
                             sep=None, engine="python")
            return _normalize_columns(df)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise WaccError(f"读取 CSV 失败（已尝试常见编码）：{last_error}")


def _non_empty_cells(row: List[Any]) -> List[Any]:
    out = []
    for value in row:
        if value is None:
            continue
        text = str(value).strip()
        if text in ("", "nan", "NaN", "None", "NaT"):
            continue
        out.append(value)
    return out


def _looks_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _read_raw_rows(filename: str, data: bytes, sheet: Optional[str], nrows: int = 12) -> List[List[Any]]:
    """按「原始网格」读前几行（不做表头处理），用于猜表头在第几行。"""
    if filename.lower().endswith(".csv"):
        for enc in CSV_ENCODINGS:
            try:
                df = pd.read_csv(io.BytesIO(data), encoding=enc, header=None, nrows=nrows,
                                 sep=None, engine="python")
                return df.values.tolist()
            except Exception:  # noqa: BLE001
                continue
        return []
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None, nrows=nrows)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(df, dict):  # 防御性处理
        df = next(iter(df.values()))
    return df.values.tolist()


def detect_header_row(filename: str, data: bytes, sheet: Optional[str]) -> int:
    """猜「表头（列名）在第几行」（从 1 开始）；猜不出来返回 1。

    依据：表头行**几乎全是文字**，而且它下面紧邻的一行宽度与它接近（那是数据行）。
    这样能自动跳过表头上方的**标题行 / 序号行**，并在没有这类行时稳妥地返回 1。
    """
    rows = _read_raw_rows(filename, data, sheet)
    if len(rows) < 2:
        return 1

    best_row, best_score = 1, None
    for idx in range(min(len(rows) - 1, 9)):  # 只在前 10 行里找
        cells = _non_empty_cells(rows[idx])
        if len(cells) < 2:
            continue
        text_count = sum(1 for c in cells if not _looks_numeric(c))
        if text_count < max(2, (len(cells) + 1) // 2):  # 表头应以文字为主
            continue
        follow: List[Any] = []
        for j in (idx + 1, idx + 2):  # 允许表头与数据之间空一行
            if j >= len(rows):
                break
            follow = _non_empty_cells(rows[j])
            if len(follow) >= 2:
                break
        if len(follow) < 2:
            continue
        width_match = 1 if abs(len(follow) - len(cells)) <= 1 else 0
        score = (width_match, text_count, len(cells))
        if best_score is None or score > best_score:
            best_score, best_row = score, idx + 1
    return best_row


# --------------------------------------------------------------------------- #
# 参数连线控件
# --------------------------------------------------------------------------- #
def render_mapping(defn: Dict[str, Any], columns: List[str], default_column: Optional[str] = None,
                   amount_unit: str = "百万元", scope: str = "") -> Tuple[str, Any]:
    """渲染一个参数的下拉映射控件。

    :param default_column: 自动识别出来的列名，作为下拉框的默认选中项。
    :param scope: 上下文的短标识（文件名 + 工作表），换文件后控件会重新回到自动识别的默认值。
    :returns: ``(kind, value)``，kind ∈ {"none", "col", "manual"}。
    """
    key = defn["key"]
    label = param_label(defn, amount_unit)
    options = [NOT_USED] + list(columns) + [MANUAL]
    index = 0
    if default_column and default_column in columns:
        index = options.index(default_column)
    widget_key = f"map__{key}" + (f"__{scope}" if scope else "")
    c1, c2 = st.columns([3, 2])
    with c1:
        choice = st.selectbox(label, options, index=index, key=widget_key, help=defn["help"])
    with c2:
        if choice == MANUAL:
            fixed = st.number_input(
                f"{defn['label']} 固定值", value=float(defn["manual_default"]),
                key=f"fixed__{key}" + (f"__{scope}" if scope else ""), format="%.6g",
            )
            return "manual", fixed
        st.caption("　")
    if choice == NOT_USED:
        return "none", None
    return "col", choice


def render_id_mapping(columns: List[str], default_column: Optional[str] = None,
                      scope: str = "") -> Tuple[str, Any]:
    options = [AUTO_ID] + list(columns)
    index = 0
    if default_column and default_column in columns:
        index = options.index(default_column)
    choice = st.selectbox("样本标识（可选）", options, index=index,
                          key="map__sample_id" + (f"__{scope}" if scope else ""),
                          help="用于在结果里标记每条样本；默认使用行号。")
    if choice == AUTO_ID:
        return "none", None
    return "col", choice


# --------------------------------------------------------------------------- #
# 结果整理与导出
# --------------------------------------------------------------------------- #
def build_results_df(ok_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(ok_rows)
    for col in RESULT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[list(RESULT_COLUMNS)]


def percent_text_df(df: pd.DataFrame) -> pd.DataFrame:
    """把百分比列转成 “8.50%” 文本，用于 CSV 导出与阅读。"""
    out = df.copy()
    for col in PERCENT_COLUMNS:
        if col in out.columns:
            out[col] = out[col].map(
                lambda v: "" if pd.isna(v) else f"{float(v) * 100:.2f}%"
            )
    return out


def results_to_excel_bytes(df: pd.DataFrame, pct_mode_label: str) -> bytes:
    """导出 Excel：百分比列使用真正的单元格百分比格式。"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="WACC结果")
        ws = writer.sheets["WACC结果"]
        for col in PERCENT_COLUMNS:
            if col in df.columns:
                col_idx = list(df.columns).index(col) + 1
                for row_idx in range(2, len(df) + 2):
                    ws.cell(row=row_idx, column=col_idx).number_format = "0.00%"
        notes = pd.DataFrame(
            {
                "项目": [
                    "公式",
                    "资本结构",
                    "股权成本",
                    "债务成本",
                    "数值格式设置",
                    "生成工具",
                ],
                "说明": [
                    "WACC = (E/V)×Re + (D/V)×Rd×(1−Tc)，V = E + D",
                    "优先使用 E 与 D；仅给 D/E 时按 E=1 换算权重",
                    "直接给出 Re 时优先；否则用 CAPM：Re = Rf + β×ERP",
                    "税后债务成本 = Rd × (1 − Tc)",
                    pct_mode_label,
                    "WACC 批量计算工具",
                ],
            }
        )
        notes.to_excel(writer, index=False, sheet_name="说明")
    return buf.getvalue()


def show_results(df: pd.DataFrame, pct_mode_label: str, key_prefix: str) -> None:
    st.subheader("📈 计算结果")
    st.caption(f"共 {len(df)} 条样本完成计算。数值格式：{pct_mode_label}")

    column_config = {}
    for col in df.columns:
        if col in PERCENT_COLUMNS:
            column_config[col] = st.column_config.NumberColumn(col, format="percent")
    safe_df = display_safe(df)
    try:
        _stretch(st.dataframe, safe_df, hide_index=True, column_config=column_config)
    except Exception:  # 旧版本不支持 percent 列格式时的兜底
        _stretch(st.dataframe, safe_df, hide_index=True)

    with st.expander("🔍 查看计算中间过程（公式拆解）", expanded=False):
        st.markdown(
            "对每一行：`V = E + D`；`E/V`、`D/V` 为权重；"
            "`Re = Rf + β×ERP`（未直接给出 Re 时）；"
            "`税后Rd = Rd×(1−Tc)`；`WACC = (E/V)×Re + (D/V)×税后Rd`。"
        )
        _stretch(st.dataframe, percent_text_df(df), hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        csv_bytes = percent_text_df(df).to_csv(index=False).encode("utf-8-sig")
        _stretch(
            st.download_button, "⬇️ 导出 CSV", data=csv_bytes,
            file_name="WACC计算结果.csv", mime="text/csv", key=f"{key_prefix}_csv",
        )
    with c2:
        try:
            xlsx_bytes = results_to_excel_bytes(df, pct_mode_label)
            _stretch(
                st.download_button, "⬇️ 导出 Excel", data=xlsx_bytes,
                file_name="WACC计算结果.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key_prefix}_xlsx",
            )
        except Exception as exc:  # noqa: BLE001
            st.info(f"Excel 导出暂不可用（{exc}），可先导出 CSV。")


def show_errors(errors: List[Tuple[int, Dict[str, Any], str]]) -> None:
    if not errors:
        return
    with st.expander(f"⚠️ 已跳过 {len(errors)} 条异常样本（不影响其它样本）", expanded=True):
        for row_no, row, message in errors:
            sample = row.get("sample_id") or f"第 {row_no} 行"
            st.markdown(f"- **{sample}**：{message}")


# --------------------------------------------------------------------------- #
# 模式一：上传表格
# --------------------------------------------------------------------------- #
def _scope_id(*parts: Any) -> str:
    """给控件 key 加一段“随文件变化”的后缀：换文件后映射控件回到自动识别的默认值。"""
    raw = "|".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def mode_upload(pct_mode: str, pct_mode_label: str, amount_unit: str) -> None:
    st.markdown("### 第 1 步 · 上传表格")
    uploaded = st.file_uploader(
        "支持 .xlsx / .xls / .csv", type=["xlsx", "xls", "csv"], key="uploader"
    )
    if uploaded is None:
        st.info("请上传一个表格文件，或切换到左侧「模式二」手动录入。")
        return

    data = uploaded.getvalue()
    filename = uploaded.name

    try:
        sheets = list_sheets(filename, data)
    except WaccError as exc:
        st.error(str(exc))
        return

    file_scope = _scope_id(filename)
    st.markdown("### 第 2 步 · 选择工作表与数据范围")
    sheet = sheets[0]
    if len(sheets) > 1:
        sheet = st.selectbox("选择要计算的工作表", sheets, key=f"sheet_choice__{file_scope}")
    else:
        st.caption(f"该文件只有 1 个工作表，已自动选中：{sheet}")

    header_key = f"header_row__{_scope_id(filename, sheet)}"
    header_kwargs: Dict[str, Any] = {}
    if header_key in st.session_state:
        suggested = 0  # 已定过就别再猜，尊重用户选择
    else:
        suggested = detect_header_row(filename, data, sheet)
        header_kwargs["value"] = suggested or 1

    header_row = st.number_input(
        "表头（列名）所在的第几行：从 1 开始数。若第 1 行是大标题、第 2 行才是列名，就填 2",
        min_value=1, max_value=1000, step=1, key=header_key, **header_kwargs,
    ) - 1
    if suggested > 1:
        st.info(
            f"🔎 检测到上面 {suggested - 1} 行像是标题 / 序号行，已自动把表头设为**第 {suggested} 行**"
            f"（也就是列名所在的那一行）。如果不对，直接改上面的数字即可。"
        )

    try:
        df = read_table(filename, data, sheet, header_row)
    except WaccError as exc:
        st.error(str(exc))
        return

    total_rows = len(df)
    if total_rows == 0:
        st.warning("这张表没有读到任何数据行，请确认上面的「表头所在行」是否正确。")
        return

    scope = _scope_id(filename, sheet, header_row)
    st.markdown("### 第 3 步 · 核对数据并连线参数")
    st.caption(
        f"实际读到：**{total_rows} 行**数据（不含表头）、**{len(df.columns)} 列**。"
        "下面把每一行都列出来了，请对着文件核对一遍。"
    )

    c1, c2 = st.columns(2)
    with c1:
        start_row = st.number_input(
            "从第几行开始计算（数据行，不含表头）",
            min_value=1, max_value=total_rows, value=1, step=1, key=f"start_row__{scope}",
        )
    with c2:
        end_row = st.number_input(
            "算到第几行结束（含这一行）",
            min_value=1, max_value=total_rows, value=total_rows, step=1, key=f"end_row__{scope}",
        )

    if end_row < start_row:
        st.error("「算到第几行结束」不能小于「从第几行开始」，请调整。")
        return

    if start_row > 1 or end_row < total_rows:
        st.info(
            f"本次只使用第 {start_row} ~ {end_row} 行，共 {end_row - start_row + 1} 行；"
            f"其余 {total_rows - (end_row - start_row + 1)} 行会被忽略。"
        )
    else:
        st.success(f"本次使用全部 {total_rows} 行数据。")

    st.caption("如果表里多出一行「序号 / 合计 / 小计 / 备注」，把「算到第几行结束」改成少一行，就能把它排除在外。")

    # 主动提醒：表内混进了“序号 / 合计 / 小计”这类非样本行
    marker_words = ("序号", "合计", "小计", "总计", "平均")
    flagged: List[int] = []
    for i, (_, record) in enumerate(df.iterrows(), start=1):
        for value in record.values:
            text = str(value).strip()
            if 0 < len(text) <= 10 and any(w in text for w in marker_words):
                flagged.append(i)
                break
    if flagged:
        shown_rows = "、".join(str(i) for i in flagged[:10])
        if len(flagged) > 10:
            shown_rows += " 等"
        st.warning(
            f"注意到第 {shown_rows} 行里出现了「序号 / 合计 / 小计」这类字样，"
            "它们可能不是样本数据。若确实不是，请用上面的「从第几行开始」或「算到第几行结束」把它们排除。"
        )

    preview = df.iloc[start_row - 1:end_row].reset_index(drop=True)
    preview.insert(0, "行号", range(start_row, end_row + 1))
    with st.expander(f"📋 展开查看将要计算的全部 {len(preview)} 行原始数据", expanded=False):
        _stretch(st.dataframe, display_safe(preview), hide_index=True)

    cols = [str(c) for c in df.columns]
    guessed = guess_mapping(cols)

    if guessed:
        shown = "、".join(f"{PARAM_DISPLAY.get(k, k)} → 「{v}」" for k, v in guessed.items())
        st.info(f"🔎 已按列名自动识别：{shown}。如果认得不对，下面的下拉框可以随时改成别的列。")
    else:
        st.warning("没能从列名自动识别出参数列，请在下拉框里手动选择每一列。")

    st.markdown("**把参数连到对应的列**（【必填】必须提供；【可选】用来替代）")
    st.caption("每个参数都可选择某一列，或选择「✏️ 手动输入固定值」（整批用同一个数值）。")

    selections: Dict[str, Tuple[str, Any]] = {}
    with st.expander("① 资本结构：E + D，或代替品 D/E", expanded=True):
        st.caption("两选一：「股权价值 E」与「债务价值 D」；或只给「债务权益比 D/E」。")
        for key in ("E", "D", "DE"):
            selections[key] = render_mapping(
                PARAM_BY_KEY[key], cols, guessed.get(key), amount_unit, scope
            )

    with st.expander("② 股权成本：Re，或代替组合 Rf + β + ERP", expanded=True):
        st.caption("两选一：「股权成本 Re」；或把「Rf」「β」「ERP」三个一起给，用 CAPM 算 Re。")
        for key in ("Re", "Rf", "beta", "ERP"):
            selections[key] = render_mapping(
                PARAM_BY_KEY[key], cols, guessed.get(key), amount_unit, scope
            )

    with st.expander("③ 债务成本与所得税率（两项都必填）", expanded=True):
        for key in ("Rd", "Tc"):
            selections[key] = render_mapping(
                PARAM_BY_KEY[key], cols, guessed.get(key), amount_unit, scope
            )

    id_kind, id_col = render_id_mapping(cols, guessed.get("sample_id"), scope)

    problems, status = analyze_selection(selections)
    st.markdown("**参数检查结果**")
    st.markdown("\n".join(
        f"- {'✅' if state == 'ok' else '⚠️'} **{name}**：{note}" for name, state, note in status
    ))
    if problems:
        st.error("还缺少必选参数，暂时无法计算：\n\n" + "\n".join(f"- {p}" for p in problems))
        return

    st.markdown("### 第 4 步 · 开始计算")
    chosen = df.iloc[start_row - 1:end_row]
    signature = (
        filename, sheet, header_row, start_row, end_row, pct_mode, id_kind, str(id_col),
        tuple(sorted((k, str(v)) for k, v in selections.items())),
    )
    if st.button("🚀 批量计算 WACC", type="primary", key="calc_upload"):
        rows = []
        for i, (_, record) in enumerate(chosen.iterrows()):
            row_input: Dict[str, Any] = {}
            if id_kind == "col":
                row_input["sample_id"] = record.get(id_col)
            else:
                row_input["sample_id"] = f"第{start_row + i}行"
            for key in ("E", "D", "DE", "Re", "Rf", "beta", "ERP", "Rd", "Tc"):
                row_input[key] = _cell_value(record, selections[key])
            rows.append(row_input)

        ok, errors = batch_compute(rows, pct_mode=pct_mode)
        st.session_state["upload_ok"] = ok
        st.session_state["upload_errors"] = errors
        st.session_state["upload_sig"] = signature

    # 只在“当前设置和上次计算时一致”才展示结果，改了映射或行范围就不会再显示旧结果
    if (st.session_state.get("upload_sig") == signature
            and st.session_state.get("upload_ok") is not None):
        show_errors(st.session_state.get("upload_errors", []))
        ok = st.session_state["upload_ok"]
        if ok:
            show_results(build_results_df(ok), pct_mode_label, "up")
        else:
            st.error("所有样本都因数据异常被跳过，请检查输入内容与数值格式设置。")


def _cell_value(record: pd.Series, selection: Tuple[str, Any]) -> Any:
    kind, value = selection
    if kind == "col":
        return record.get(value)
    if kind == "manual":
        return value
    return None


def analyze_selection(
    selections: Dict[str, Tuple[str, Any]],
) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    """检查参数组合是否够算 WACC。

    :returns: ``(缺失提示列表, 状态列表)``；状态元素为 ``(名称, "ok"/"missing", 说明)``。
    """
    used = {k: (v[0] != "none") for k, v in selections.items()}
    problems: List[str] = []
    status: List[Tuple[str, str, str]] = []

    # 资本结构：必填为 E + D；可选替代为 D/E
    if used["E"] and used["D"]:
        status.append(("资本结构", "ok", "由「E + D」提供"))
    elif used["DE"]:
        note = "（E、D 与 D/E 同时给出时，以 E、D 为准）" if (used["E"] or used["D"]) else ""
        status.append(("资本结构", "ok", f"由「D/E」替代提供，自动按 E=1 换算权重{note}"))
    else:
        status.append(("资本结构", "missing", "必填：需要「E」与「D」，或用「D/E」替代"))
        problems.append("资本结构：请映射「股权价值 E」与「债务价值 D」，或映射「债务权益比 D/E」")

    # 股权成本：必填为 Re；可选替代为 Rf + β + ERP
    if used["Re"]:
        status.append(("股权成本 Re", "ok", "由「Re」直接提供"))
    elif used["Rf"] and used["beta"] and used["ERP"]:
        status.append(("股权成本 Re", "ok", "由「Rf + β × ERP」经 CAPM 计算"))
    else:
        lack = "、".join(
            name for name, key in (("Rf", "Rf"), ("β", "beta"), ("ERP", "ERP")) if not used[key]
        )
        status.append(("股权成本 Re", "missing", f"必填：需要「Re」，或用 Rf+β+ERP 替代（当前还缺：{lack}）"))
        problems.append("股权成本：请映射「股权成本 Re」，或同时映射「Rf」「β」「ERP」（CAPM）")

    for key, name in (("Rd", "债务成本 Rd"), ("Tc", "所得税率 Tc")):
        if used[key]:
            status.append((name, "ok", "已提供"))
        else:
            status.append((name, "missing", "必填，请映射"))
            problems.append(f"{name}：必填，请映射")

    return problems, status


def validate_selection(selections: Dict[str, Tuple[str, Any]]) -> List[str]:
    """返回缺失必选参数的中文提示列表；为空表示校验通过。（``analyze_selection`` 的简版）"""
    return analyze_selection(selections)[0]


# --------------------------------------------------------------------------- #
# 模式二：手动录入
# --------------------------------------------------------------------------- #
def mode_manual(pct_mode: str, pct_mode_label: str, amount_unit: str) -> None:
    st.markdown("### 在表格里直接录入多组参数")
    st.caption("点击最后一行下方的“＋”可增加行；「样本标识」留空会自动编号。"
               "标【必填】的必须填；标【可选】的用来替代必填项。")
    st.caption(
        "资本结构二选一：① 填 `E` 与 `D`；② 只填 `D/E`。　"
        "股权成本二选一：① 填 `Re`；② 填 `Rf`、`β`、`ERP`（CAPM）。"
    )

    blank = {
        "样本标识": "", "E": None, "D": None, "D/E": None,
        "Re": None, "Rf": None, "β": None, "ERP": None, "Rd": None, "Tc": None,
    }
    base = pd.DataFrame([dict(blank) for _ in range(5)])

    money = f"金额，如：{amount_unit}"
    edited = _stretch(
        st.data_editor,
        base, num_rows="dynamic", hide_index=True,
        key="manual_editor",
        column_config={
            "样本标识": st.column_config.TextColumn("样本标识（可选）", width="small"),
            "E": st.column_config.NumberColumn(f"【必填】股权价值 E（{money}）", format="%.4f"),
            "D": st.column_config.NumberColumn(f"【必填】债务价值 D（{money}）", format="%.4f"),
            "D/E": st.column_config.NumberColumn("【可选】债务权益比 D/E（倍数）", format="%.4f"),
            "Re": st.column_config.NumberColumn("【必填】股权成本 Re（年化收益率）", format="%.4f"),
            "Rf": st.column_config.NumberColumn("【可选】无风险利率 Rf（年化收益率）", format="%.4f"),
            "β": st.column_config.NumberColumn("【可选】贝塔 β（倍数，无量纲）", format="%.4f"),
            "ERP": st.column_config.NumberColumn("【可选】市场风险溢价 ERP（年化收益率）", format="%.4f"),
            "Rd": st.column_config.NumberColumn("【必填】债务成本 Rd（年化利率，税前）", format="%.4f"),
            "Tc": st.column_config.NumberColumn("【必填】所得税率 Tc（如 25% 或 0.25）", format="%.4f"),
        },
    )

    if st.button("🚀 批量计算 WACC", type="primary", key="calc_manual"):
        rows = []
        for i, record in edited.iterrows():
            values = {k: record.get(k) for k in ("E", "D", "D/E", "Re", "Rf", "β", "ERP", "Rd", "Tc")}
            if all(pd.isna(v) for v in values.values()):
                continue  # 整行空白，忽略
            sample = record.get("样本标识")
            rows.append({
                "sample_id": sample if not pd.isna(sample) and str(sample).strip() else f"第{i + 1}行",
                "E": values["E"], "D": values["D"], "DE": values["D/E"],
                "Re": values["Re"], "Rf": values["Rf"], "beta": values["β"],
                "ERP": values["ERP"], "Rd": values["Rd"], "Tc": values["Tc"],
            })
        if not rows:
            st.warning("还没有录入任何数据，请至少填写一行的参数。")
        else:
            ok, errors = batch_compute(rows, pct_mode=pct_mode)
            st.session_state["manual_ok"] = ok
            st.session_state["manual_errors"] = errors

    ok = st.session_state.get("manual_ok")
    if ok is not None:
        show_errors(st.session_state.get("manual_errors", []))
        if ok:
            show_results(build_results_df(ok), pct_mode_label, "mn")
        else:
            st.error("所有样本都因数据异常被跳过，请检查输入内容与数值格式设置。")


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
def mode_random(pct_mode: str, pct_mode_label: str) -> None:
    """随机生成一组参数并立即计算，用于快速检查输出是否正常。"""
    st.markdown("### 随机示例")
    st.caption("每次生成一组随机但合理的参数，自动计算一遍；换一组就再点一次。")

    if "random_seed" not in st.session_state:
        st.session_state["random_seed"] = random.randrange(1, 1_000_000)

    c1, c2 = st.columns([1, 3])
    if c1.button("🎲 重新生成", type="primary", key="random_regen"):
        st.session_state["random_seed"] = random.randrange(1, 1_000_000)
    seed = st.session_state["random_seed"]
    rows = generate_random_rows(seed)
    c2.caption(f"随机种子：{seed} · {len(rows)} 行 · 每次点按钮都会换一组")

    preview = pd.DataFrame(rows)
    with st.expander("📋 查看随机生成的参数", expanded=True):
        _stretch(st.dataframe, display_safe(preview), hide_index=True)

    ok, errors = batch_compute(rows, pct_mode=pct_mode)
    show_errors(errors)
    if ok:
        show_results(build_results_df(ok), pct_mode_label, "rand")
    else:
        st.error("本次随机数据都没通过校验，请再点一次「重新生成」。")


def main() -> None:
    st.title("📊 WACC 批量计算工具")
    st.caption("加权平均资本成本批量估算 · 上传表格或手动录入 · 结果可导出 CSV / Excel")

    with st.sidebar:
        st.header("📐 计算公式")
        st.latex(r"WACC = \frac{E}{V}R_e + \frac{D}{V}R_d(1-T_c)")
        st.caption("V = E + D（资本总额）；税后债务成本 = Rd × (1 − Tc)。")
        st.markdown(COMPONENT_GLOSSARY)
        st.divider()
        st.header("⚙️ 数值格式与单位")
        pct_label = st.radio(
            "利率 / 税费率的输入格式",
            list(PCT_MODE_LABELS.keys()),
            index=0,
            help="「自动识别」会在数值绝对值大于 1 时按百分比处理（÷100）；"
                 "E、D、D/E、β 永不参与换算。",
        )
        pct_mode = PCT_MODE_LABELS[pct_label]
        amount_unit = st.text_input(
            "金额单位（只影响界面文字）",
            value="百万元",
            key="amount_unit",
            help="WACC 只取决于 E 与 D 的比例，与金额单位无关；这里填的单位只会显示在参数名称里，"
                 "方便你对照自己的表格（例如填「百万元」「万元」「亿元」）。",
        ).strip() or "百万元"
        st.divider()
        st.caption("界面语言：中文 · 全程无需命令行")

    mode = st.radio(
        "选择使用模式",
        ["模式一：上传表格批量计算", "模式二：手动录入批量计算", "模式三：随机示例（自动生成）"],
        horizontal=True, key="mode",
    )
    st.divider()

    if mode.startswith("模式一"):
        mode_upload(pct_mode, pct_label, amount_unit)
    elif mode.startswith("模式二"):
        mode_manual(pct_mode, pct_label, amount_unit)
    else:
        mode_random(pct_mode, pct_label)


if __name__ == "__main__":
    main()
