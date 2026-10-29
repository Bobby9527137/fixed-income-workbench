#!/bin/bash
# 投标簿记信息提取工具 —— macOS 一键启动
# 用法（推荐）：在「终端」里 cd 到本文件夹，执行   bash run.sh
#      或者： chmod +x run.sh 之后执行   ./run.sh
#      或者：在 Finder 里双击「启动.command」（首次可能要先 chmod +x）

set -u
cd "$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo "  投标簿记信息提取工具 · 一键启动"
echo "============================================================"

# 挑一个 3.9 以上的 Python（3.11/3.12 的 OCR 轮子最全）
pick_python() {
  for candidate in python3.12 python3.11 python3.13 python3.10 python3.9 python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1 || continue
    echo "$candidate"
    return 0
  done
  return 1
}

PY="$(pick_python || true)"
if [ -n "$PY" ]; then
  ver="$("$PY" -c "import sys;print("%d.%d.%d" % sys.version_info[:3])" 2>/dev/null)"
  echo "[i] 找到 Python ${ver}（${PY}）"
fi

if [ -z "$PY" ]; then
  echo "[i] 没有找到 Python 3.9 以上版本，尝试用 Homebrew 装一个…"
  if command -v brew >/dev/null 2>&1; then
    brew install python@3.12 || true
    prefix="$(brew --prefix 2>/dev/null || true)"
    for candidate in "${prefix}/bin/python3.12" python3.12; do
      if [ -n "$candidate" ] && command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
      fi
    done
  fi
fi

if [ -z "$PY" ]; then
  echo "[!] 还是没有可用的 Python 3.9+。"
  echo "    · 装 Homebrew（https://brew.sh），然后执行：brew install python@3.12"
  echo "    · 或到 https://www.python.org/downloads/macos/ 下载安装 Python 3.12"
  echo "    装好以后重新运行本脚本即可。"
  read -r -p "按回车关闭…" _ || true
  exit 1
fi

echo "[i] 接下来会自动建好虚拟环境、装好依赖（第一次几分钟，之后几秒钟）。"
exec "$PY" -u app.py "$@"
