#!/bin/bash
# 固收工作台 macOS 双击启动器
# 说明：本文件必须保持 LF 换行；CRLF 会让 macOS 的 bash 直接报错。
set -e

cd "$(dirname "$0")"

# 自愈：去掉浏览器/网盘加上的隔离标记，补回执行位（zip 解压后常丢失）。
xattr -rd com.apple.quarantine . 2>/dev/null || true
chmod +x *.command 2>/dev/null || true

# 只接受 3.10+：排除 Xcode 命令行工具桩和过旧的系统 Python。
python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  RUNTIME="${WB_RUNTIME_DIR:-$HOME/Library/Application Support/固收工作台/runtime}"
  ARCHIVE="$(ls ./runtime/python/*install_only.tar.gz 2>/dev/null | head -n 1)"

  # 干净 Mac 第一次双击时包内只有 tar.gz，没有 bin/python3。
  # 先用 macOS 自带 bsdtar 解压到与 bootstrap.py 相同的目录：
  #   <runtime>/python/<archive 主名>/
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

  # 兼容已经解压好的交付包（目录名不固定）。
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
  echo "包内 Python 解压失败，且未找到可用的 Python 3.10+。"
  echo "请把本窗口截图发给维护者。"
  osascript -e 'display dialog "包内 Python 解压失败，请把本窗口截图发给维护者。" buttons {"好"} default button "好" with icon caution' >/dev/null 2>&1 || true
  read -n 1 -r -s -p "按任意键关闭窗口…" || true
  echo
  exit 1
fi

echo "使用 Python：$PY"

if [ -t 0 ]; then
  # 终端里双击：不用 exec，失败时保留窗口让用户看到错误。
  STATUS=0
  "$PY" start.py "$@" || STATUS=$?
  if [ "$STATUS" -ne 0 ]; then
    echo
    echo "启动失败（退出码 $STATUS）。请把上面的错误信息或 诊断报告.txt 发给维护者。"
    read -n 1 -r -s -p "按任意键关闭窗口…" || true
    echo
  fi
  exit "$STATUS"
else
  # 从脚本/CI 调用：exec 把进程交给 Python，信号与退出码原样传递。
  exec "$PY" start.py "$@"
fi
