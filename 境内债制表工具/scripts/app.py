# -*- coding: utf-8 -*-
"""
境内债制表工具 — Streamlit 可视化界面
====================================
启动（在项目根目录 境内债制表工具/ 下）：
    python -m streamlit run scripts/app.py
"""
import io
import os
import random
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bondtable import (DEFAULT_OUT_DIR, convert_dataframe, load_config, load_tasks,
                       make_credit_text, make_local_text, write_output)
from random_sample import make_demo


class _MemoryUpload:
    """把内存里的 xlsx 伪装成 st.file_uploader 的返回值。"""

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    @property
    def size(self) -> int:
        return len(self._data)

    def getbuffer(self):
        return memoryview(self._data)


def _start_demo() -> None:
    seed = random.randrange(1, 1_000_000)
    st.session_state["demo"] = {"seed": seed, "files": make_demo(seed)}
    st.session_state["auto_run"] = True
    st.session_state.pop("results", None)


def _clear_demo() -> None:
    st.session_state["demo"] = None
    st.session_state.pop("results", None)
    st.session_state.pop("auto_run", None)


def run_conversion(tasks, blurb_word: str) -> None:
    results = []
    for task in tasks:
        result, warnings = convert_dataframe(task["df"], config, task["choice"])
        out_name = f"{task['choice']}_制表结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        out_path = write_output(result, os.path.join(DEFAULT_OUT_DIR, out_name))
        results.append({"choice": task["choice"], "file": task["file"], "sheet": task["sheet"],
                        "result": result, "warnings": warnings, "out": out_path})
    st.session_state["results"] = results

st.set_page_config(page_title="境内债制表工具", page_icon="📊", layout="wide")

st.title("📊 境内债制表工具")
st.caption("地方债 / 信用债原始表 → 各自的标准 11 列表格 · 映射分品种配置于 `config/表头映射.json`，改映射不用改代码")

config = load_config()


def show_df(df, height=None, **kwargs):
    """表格显示：新版 streamlit 用 width='stretch'，旧版回退 use_container_width"""
    try:
        return st.dataframe(df, width="stretch", height=height, **kwargs)
    except Exception:
        return st.dataframe(df, use_container_width=True, height=height, **kwargs)


with st.sidebar:
    st.header("当前表头映射（分品种）")
    for bond_name, bt in config.get("bond_types", {}).items():
        rows = []
        for i, col in enumerate(bt["target_headers"]):
            item = bt["column_mapping"].get(col, {})
            src = item.get("source") or "、".join(item.get("sources") or [])
            rows.append((i + 1, col, src or "（留空占位）"))
        with st.expander(f"{bond_name}（{len(bt['target_headers'])} 列）", expanded=(bond_name == "地方债")):
            show_df(pd.DataFrame(rows, columns=["#", "目标列", "取自原表列"]),
                    height=280, hide_index=True)
    st.caption("信用债口径：截标时间直取并归一为“月-日 时:分”；发行量=实际发行优先、空则取计划；申购区间有则填、无则空；主/债评级=主体/债项评级合成。")

demo = st.session_state.get("demo")
c_demo, c_clear, c_note = st.columns([1, 1, 4])
c_demo.button("🎲 随机示例", on_click=_start_demo,
              help="随机生成地方债 / 信用债原始表，自动跑一遍制表，用来检查输出是否正常")
if demo:
    c_clear.button("清除示例", on_click=_clear_demo, key="clear_demo")
    names = "、".join(name for name, _ in demo["files"])
    c_note.caption(f"正在使用随机示例 · 种子 {demo['seed']} · {names}")

if demo:
    uploaded = [_MemoryUpload(name, data) for name, data in demo["files"]]
else:
    uploaded = st.file_uploader("① 上传原始数据表（可多选，.xlsx）",
                                type=["xlsx", "xls"], accept_multiple_files=True)

if not uploaded:
    st.info("👆 请上传原始数据表；也可以把文件放进 `data/原始数据/`，用命令行批处理："
            "`python scripts/transform.py --input data/原始数据`")
    st.stop()

# 换了一批上传文件时，清除上一批的制表结果
sig = [(f.name, f.size) for f in uploaded]
if st.session_state.get("sig") != sig:
    st.session_state["sig"] = sig
    st.session_state.pop("results", None)

# ---- 读取与债种识别 ----
tasks, errors = [], []
for file in uploaded:
    try:  # 内存直读（BytesIO），不落盘——旧版写临时文件曾致项目根目录累积 tmp*.xlsx 泄漏
        for bond, sheet, df in load_tasks(io.BytesIO(file.getbuffer()), config, name=file.name):
            tasks.append({"file": file.name, "bond": bond, "sheet": sheet, "df": df})
    except Exception as e:
        errors.append(f"《{file.name}》读取失败：{e}")

for e in errors:
    st.error(e)

if not tasks:
    st.warning("没有读到可处理的工作表，请确认文件内容")
    st.stop()

st.divider()
st.header("② 核对债券品种")
bond_options = list(config.get("bond_types", {}))
for i, t in enumerate(tasks):
    c1, c2 = st.columns([3, 2])
    c1.markdown(f"**{t['file']}** · 工作表《{t['sheet']}》 · 原始 {len(t['df'])} 行")
    default_idx = bond_options.index(t["bond"]) if t["bond"] in bond_options else 0
    t["choice"] = c2.selectbox(
        "债券品种",
        bond_options,
        index=default_idx,
        key=f"bond_{i}",
        help=f"按文件名/工作表名自动识别：{t['bond'] or '未识别，请手动确认'}",
    )
    with st.expander(f"预览《{t['sheet']}》原始数据（前 10 行）", expanded=(i == 0)):
        show_df(t["df"].head(10), height=280)

st.divider()
st.header("③ 制表")
blurb_word = st.radio(
    "播报头行文案（“一键制作文本”用）",
    ["本周", "今日"],
    horizontal=True,
    help="生成播报文本时头行的用词：*本周/今日 + 债种 + 待发行*；可随时切换，不影响制表结果",
)
auto_run = st.session_state.pop("auto_run", False)
if st.button("🚀 一键制表", type="primary") or auto_run:
    run_conversion(tasks, blurb_word)

results = st.session_state.get("results")
if results:
    st.success(f"完成 {len(results)} 张制表，结果已同步保存到 `data/输出/` 目录")
    for r in results:
        st.subheader(f"{r['choice']}（来自 {r['file']} · 《{r['sheet']}》）")
        for w in r["warnings"]:
            st.warning(w)
        show_df(r["result"], height=320)
        with open(r["out"], "rb") as f:
            st.download_button(
                f"⬇️ 下载 {os.path.basename(r['out'])}",
                data=f.read(),
                file_name=os.path.basename(r["out"]),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{r['choice']}_{r['file']}_{r['sheet']}",
            )
        txt = make_local_text(r["result"], word=blurb_word) if r["choice"] == "地方债" else \
            make_credit_text(r["result"], word=blurb_word) if r["choice"] == "信用债" else None
        if txt:
            st.markdown("**📝 一键制作文本（待发行播报）**")
            st.caption("地方债：同日同地区合并一行（地区短名+当日合计 4 位小数+期限集合）；"
                       "商金债：每行=债券简称+发行量（期限）；均按发行日 M/D 分组；"
                       "点代码块右上角图标可一键复制")
            st.code(txt, language=None)
            st.download_button(
                "⬇️ 下载播报文本（.txt）",
                data=txt,
                file_name=f"{r['choice']}_本周播报.txt",
                mime="text/plain",
                key=f"txt_{r['choice']}_{r['file']}_{r['sheet']}",
            )
