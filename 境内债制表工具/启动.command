#!/bin/bash
# ============================================================
#  境内债制表工具 · macOS 一键启动（带自愈）
#  双击本文件即可：检测/创建虚拟环境 → 首次自动装依赖 → 启动网页界面
#
#  关于 macOS 信任（重要，请先读）：
#    经浏览器/微信/压缩包等途径传来的文件，首次双击可能被系统拦下
#    （提示"无法验证的开发者"或双击无反应）——这是 macOS 对所有外来
#    脚本的通用安全策略，并非本工具的问题。
#    只要用任意方式成功运行一次，本脚本会自动完成【自愈】：
#      · 清除整个项目目录的隔离标记（com.apple.quarantine）
#      · 补齐所有 .command 的可执行权限
#    之后双击永久正常，不再需要任何终端操作。
#    最有保障的一次性方法（100% 有效，约 10 秒）：
#      打开「终端」→ 输入 bash 加一个空格 → 把本文件拖进窗口 → 回车
# ============================================================

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

# ---- ⓪ 自愈（静默执行，只需成功运行一次，之后双击永久正常） ----
if command -v xattr >/dev/null 2>&1; then
  xattr -rd com.apple.quarantine "$ROOT" >/dev/null 2>&1
fi
chmod +x "$ROOT/"*.command >/dev/null 2>&1

echo "=================================================="
echo "  境内债制表工具 · 一键启动（macOS）"
echo "=================================================="

# ---- [1/5] 检测 Python ----
echo ""
echo "[1/5] 检测 Python 环境 …"
if ! command -v python3 >/dev/null 2>&1; then
  echo "      [出错] 未检测到 python3。"
  echo "             请先安装 Python 3.9+（任选其一）："
  echo "               · 官网安装包：https://www.python.org/downloads/"
  echo "               · Homebrew： brew install python"
  echo "             安装完成后，再次双击本文件即可。"
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
echo "      [完成] 已找到 $(python3 --version 2>&1)"

# ---- [2/5] 准备虚拟环境 ----
echo ""
echo "[2/5] 准备虚拟环境 .venv …"
if [ -e ".venv" ] && ! [ -x ".venv/bin/python3" ]; then
  echo "      [提示] 发现残留的旧 .venv（缺少 python3），正在重建 …"
  rm -rf .venv
fi
if [ -x ".venv/bin/python3" ] && ! .venv/bin/python3 --version >/dev/null 2>&1; then
  echo "      [提示] 现有 .venv 无法运行（基座 Python 可能已升级/卸载），正在重建 …"
  rm -rf .venv
fi
if [ -x ".venv/bin/python3" ]; then
  echo "      [完成] 虚拟环境已就绪（自动检测通过，跳过创建）"
else
  echo "      首次运行：正在创建虚拟环境 .venv（约 10 秒）…"
  python3 -m venv .venv || {
    echo "      [出错] 创建虚拟环境失败，请把本窗口的报错截图发给维护者。"
    read -n 1 -s -r -p "按任意键关闭…"
    exit 1
  }
  echo "      [完成] 虚拟环境创建成功"
fi

# ---- [3/5] 检测依赖 ----
echo ""
echo "[3/5] 检测依赖（pandas / openpyxl / streamlit）…"
if ! .venv/bin/python3 -c "import streamlit, pandas, openpyxl" >/dev/null 2>&1; then
  echo "      [提示] 首次运行：正在联网安装依赖（约 1-3 分钟，窗口会显示下载进度）…"
  .venv/bin/python3 -m pip install --upgrade pip -q
  .venv/bin/python3 -m pip install -r scripts/requirements.txt || {
    echo "      [出错] 依赖安装失败：请检查网络后重新双击本文件。"
    echo "             如反复失败，请截图本窗口发给维护者。"
    read -n 1 -s -r -p "按任意键关闭…"
    exit 1
  }
  echo "      [完成] 依赖安装完成"
else
  echo "      [完成] 依赖已就绪（自动检测通过，跳过安装）"
fi

# ---- [4/5] 启动网页界面 ----
echo ""
echo "[4/5] 启动网页界面 …"
echo "      [完成] 正在启动 Streamlit，浏览器将自动打开 http://localhost:8501"
echo "             如终端出现 Email 提示，直接按回车即可（仅首次）"

# ---- [5/5] 运行中 ----
echo ""
echo "[5/5] 工具运行中 —— 请保持本窗口开启"
echo "      · 停止工具：关闭本窗口，或按 Ctrl+C"
echo "--------------------------------------------------"
exec .venv/bin/python3 -m streamlit run scripts/app.py --browser.gatherUsageStats false
