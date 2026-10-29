#!/bin/bash
# 固收工作台 macOS 诊断入口：生成 诊断报告.txt 并在 Finder 中定位。
# 说明：本文件必须保持 LF 换行；CRLF 会让 macOS 的 bash 直接报错。
set -e

cd "$(dirname "$0")"

xattr -rd com.apple.quarantine . 2>/dev/null || true
chmod +x *.command 2>/dev/null || true

# 与“启动工作台.command”保持同一套查找逻辑。这里刻意复制而不是 source：
# 诊断脚本可能被单独拷到别处，不能依赖另一个文件一定还在。
python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  RUNTIME="${WB_RUNTIME_DIR:-$HOME/Library/Application Support/固收工作台/runtime}"
  ARCHIVE="$(ls ./runtime/python/*install_only.tar.gz 2>/dev/null | head -n 1)"

  if [ -n "$ARCHIVE" ]; then
    STEM="${ARCHIVE##*/}"
    STEM="${STEM%.tar.gz}"
    TARGET="$RUNTIME/python/$STEM"
    if [ ! -x "$TARGET/bin/python3" ]; then
      echo "首次启动，正在解压内置 Python（约 1 分钟，请勿关闭窗口）…" >&2
      # 先解到临时目录再整体就位：并发双击时不会互相踩坏半成品。
      STAGE="$TARGET.tmp.$$"
      /bin/rm -rf "$STAGE" 2>/dev/null || true
      mkdir -p "$STAGE" 2>/dev/null || true
      if /usr/bin/tar -xzf "$ARCHIVE" -C "$STAGE" --strip-components=1 2>/dev/null; then
        if [ ! -x "$TARGET/bin/python3" ]; then
          /bin/mv "$STAGE" "$TARGET" 2>/dev/null || true
        fi
      else
        echo "包内 Python 解压失败：$ARCHIVE" >&2
      fi
      /bin/rm -rf "$STAGE" 2>/dev/null || true
    fi
    if [ -x "$TARGET/bin/python3" ] && python_ok "$TARGET/bin/python3"; then
      printf '%s\n' "$TARGET/bin/python3"
      return 0
    fi
  fi

  for candidate in ./runtime/python/*/bin/python3; do
    if [ -x "$candidate" ] && python_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  for candidate in python3.12 python3 /usr/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PY="$(find_python || true)"
# 只取最后一行：即使以后有人把提示写到 stdout，也不会污染 Python 路径。
PY="${PY##*$'\n'}"

if [ -z "$PY" ]; then
  echo "包内 Python 解压失败，且未找到可用的 Python 3.10+，无法生成诊断报告。"
  echo "请把本窗口截图发给维护者。"
  osascript -e 'display dialog "包内 Python 解压失败，无法生成诊断报告。请把本窗口截图发给维护者。" buttons {"好"} default button "好" with icon caution' >/dev/null 2>&1 || true
  read -n 1 -r -s -p "按任意键关闭窗口…" || true
  echo
  exit 1
fi

echo "使用 Python：$PY"

STATUS=0
"$PY" start.py --diagnose "$@" || STATUS=$?

if [ -f "诊断报告.txt" ]; then
  open -R "诊断报告.txt" >/dev/null 2>&1 || true
else
  echo "报告未生成，请截图本窗口并发送给维护者。"
fi

if [ "$STATUS" -ne 0 ]; then
  echo
  echo "诊断失败（退出码 $STATUS）。请把 诊断报告.txt 或本窗口截图发给维护者。"
  read -n 1 -r -s -p "按任意键关闭窗口…" || true
  echo
fi

exit "$STATUS"
