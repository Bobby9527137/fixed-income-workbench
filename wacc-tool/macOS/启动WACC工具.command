#!/bin/bash
# ============================================================================
#  WACC 批量计算工具 · macOS 一键启动脚本
#
#  使用方法：在 Finder 里双击本文件即可（无需任何命令行操作）。
#  首次运行会自动创建虚拟环境并安装依赖；之后每次运行只做自检，缺失才补装。
#  任何环节出错，重新双击本文件即可自动修复（重建环境 / 补依赖 / 换端口）。
# ============================================================================
set -u

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"

APP_NAME="WACC 计算工具"
VENV_DIR="$ROOT/.venv-macos"
PY_BIN="$VENV_DIR/bin/python"
LOG_FILE="$ROOT/launcher-macos.log"
REQ_FILE="$ROOT/requirements.txt"
STAMP_FILE="$VENV_DIR/.requirements.stamp"
APP_FILE="$ROOT/app.py"
SUPPORT_PY="$ROOT/launcher_support.py"
PID_FILE="$ROOT/.wacc-macos.pid"
PORT_FILE="$ROOT/.wacc-macos.port"
START_PORT=8501

SYS_PY=""
SERVER_PID=""
STARTED_BY_US="0"

say() { printf '%s\n' "$*"; printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE" 2>/dev/null; }
warn() { say "⚠️  $*"; }

# 弹窗文本先去掉会破坏 AppleScript 的引号和反斜杠
alert() {
  local msg
  msg="$(printf '%s' "$1" | tr -d '\\"' 2>/dev/null)"
  osascript -e "display dialog \"$msg\" buttons {\"好\"} default button \"好\" with icon caution with title \"$APP_NAME\"" >/dev/null 2>&1 || true
}

fail() {
  say ""
  say "❌ $*"
  alert "$*"
  say ""
  say "详情见日志：$LOG_FILE"
  say "按回车键关闭此窗口…"
  read -r _ || true
  exit 1
}

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  if [ "$STARTED_BY_US" = "1" ]; then
    rm -f "$PID_FILE" "$PORT_FILE" 2>/dev/null || true
  fi
}
# 关窗口（SIGHUP）时也要把服务一起带走，避免端口被占住
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

# ---------------------------------------------------------------------------
# 1. 定位可用的 Python 3
#    优先找“不会弹出安装提示”的版本；只有确认装过命令行工具才去碰系统自带 python3
# ---------------------------------------------------------------------------
find_system_python() {
  local cand candidates resolved
  candidates="/usr/local/bin/python3 /opt/homebrew/bin/python3"

  # python.org 安装版（框架式，可能不在 PATH 里）
  for cand in /Library/Frameworks/Python.framework/Versions/*/bin/python3; do
    candidates="$candidates $cand"
  done

  # PATH 里的 python3；若它就是系统占位符且没装命令行工具，跳过以免弹出安装窗口
  resolved="$(command -v python3 2>/dev/null || true)"
  if [ -n "$resolved" ]; then
    if [ "$resolved" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then
      :
    else
      candidates="$candidates $resolved"
    fi
  fi

  # 系统自带 python3（macOS 上需要命令行工具；已确认装好才使用）
  if xcode-select -p >/dev/null 2>&1; then
    candidates="$candidates /usr/bin/python3"
  fi

  for cand in $candidates; do
    [ -x "$cand" ] || continue
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

venv_ok() {
  [ -x "$PY_BIN" ] || return 1
  "$PY_BIN" -c 'import sys' >/dev/null 2>&1 || return 1
  # 只有 pip 也能用才算健康；否则补依赖必定失败
  "$PY_BIN" -m pip --version >/dev/null 2>&1 || return 1
  return 0
}

create_venv() {
  local sp="$1"
  rm -rf "$VENV_DIR" 2>/dev/null || true
  say "正在创建虚拟环境（仅首次，约 1 分钟）…"
  "$sp" -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1 || return 1
  # 少数系统的 venv 不自带 pip，用 ensurepip 补上
  if ! "$PY_BIN" -m pip --version >/dev/null 2>&1; then
    "$PY_BIN" -m ensurepip --upgrade >>"$LOG_FILE" 2>&1 || true
  fi
  if ! "$PY_BIN" -m pip --version >/dev/null 2>&1; then
    return 1
  fi
  "$PY_BIN" -m pip install --quiet --upgrade pip >>"$LOG_FILE" 2>&1 || true
  return 0
}

# 需要时才去找 Python，避免每次启动都做无谓探测
ensure_python() {
  if [ -z "$SYS_PY" ]; then SYS_PY="$(find_system_python || true)"; fi
  [ -n "$SYS_PY" ]
}

# ---------------------------------------------------------------------------
# 2. 依赖自检：只安装缺失项，绝不全量重装
# ---------------------------------------------------------------------------
ensure_deps() {
  local missing stamp_now stamp_old
  missing="$("$PY_BIN" "$SUPPORT_PY" check-deps 2>/dev/null | tr -d '\r')" \
    || missing="streamlit pandas openpyxl xlrd"

  stamp_now=""
  if [ -f "$REQ_FILE" ]; then
    # macOS 自带 shasum；没有时用 sha256sum 兜底
    if command -v shasum >/dev/null 2>&1; then
      stamp_now="$(shasum -a 256 "$REQ_FILE" 2>/dev/null | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
      stamp_now="$(sha256sum "$REQ_FILE" 2>/dev/null | awk '{print $1}')"
    fi
  fi
  stamp_old=""
  if [ -f "$STAMP_FILE" ]; then
    stamp_old="$(cat "$STAMP_FILE" 2>/dev/null)"
  fi

  if [ -z "$missing" ] && [ "$stamp_now" = "$stamp_old" ]; then
    say "环境自检：依赖完整，跳过安装。"
    return 0
  fi

  say "环境自检：发现需要补齐的依赖，开始安装（只补缺失项）…"
  if [ -n "$missing" ]; then
    # shellcheck disable=SC2086
    "$PY_BIN" -m pip install --quiet $missing >>"$LOG_FILE" 2>&1 || return 1
  fi
  if [ -f "$REQ_FILE" ]; then
    "$PY_BIN" -m pip install --quiet -r "$REQ_FILE" >>"$LOG_FILE" 2>&1 || true
  fi

  missing="$("$PY_BIN" "$SUPPORT_PY" check-deps 2>/dev/null | tr -d '\r')" || missing="?"
  if [ -n "$missing" ]; then return 1; fi

  if [ -n "$stamp_now" ]; then printf '%s' "$stamp_now" >"$STAMP_FILE"; fi
  say "环境自检：依赖已就绪。"
  return 0
}

# ---------------------------------------------------------------------------
# 3. 选端口 / 启动 / 打开浏览器
# ---------------------------------------------------------------------------
pick_port() {
  "$PY_BIN" "$SUPPORT_PY" free-port "$START_PORT" 2>/dev/null | tr -d '\r'
}

start_server() {
  local port="$1"
  "$PY_BIN" -m streamlit run "$APP_FILE" \
    --server.port "$port" \
    --server.address 127.0.0.1 \
    --server.headless true \
    --browser.gatherUsageStats false >>"$LOG_FILE" 2>&1 &
  SERVER_PID=$!
  STARTED_BY_US="1"
}

wait_for_server() {
  local port="$1" i
  for i in $(seq 1 90); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      return 1
    fi
    if curl -fsS "http://127.0.0.1:$port/_stcore/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

# 已经有一个在跑的实例？返回它的端口
find_running_instance() {
  local old_pid old_port
  [ -f "$PID_FILE" ] || return 1
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  old_port="$(cat "$PORT_FILE" 2>/dev/null || true)"
  if [ -n "$old_pid" ] && [ -n "$old_port" ] \
     && kill -0 "$old_pid" 2>/dev/null \
     && curl -fsS "http://127.0.0.1:$old_port/_stcore/health" >/dev/null 2>&1; then
    printf '%s' "$old_port"
    return 0
  fi
  rm -f "$PID_FILE" "$PORT_FILE" 2>/dev/null || true
  return 1
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
  : >"$LOG_FILE" 2>/dev/null || true
  say "==================== WACC 计算工具启动 ===================="
  say "项目目录：$ROOT"

  if [ ! -f "$APP_FILE" ]; then
    fail "找不到 app.py，请确认本文件与 app.py 在同一个项目文件夹里。"
  fi
  if [ ! -f "$SUPPORT_PY" ]; then
    fail "找不到 launcher_support.py，请确认本项目文件夹完整。"
  fi

  # 虚拟环境
  if ! venv_ok; then
    if [ -d "$VENV_DIR" ]; then warn "检测到虚拟环境不完整，正在自动重建…"; fi
    if ! ensure_python; then
      open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
      fail "未找到可用的 Python 3。请先安装 Python 3.9 或更高版本（已为你打开下载页），安装完成后再次双击本文件。"
    fi
    create_venv "$SYS_PY" || fail "创建虚拟环境失败（常见原因：系统 Python 缺少 venv / ensurepip 组件）。建议改用 Python 官方网站版本后重试，日志：$LOG_FILE"
  fi
  say "虚拟环境：$VENV_DIR（Python $("$PY_BIN" -c 'import platform; print(platform.python_version())' 2>/dev/null)）"

  # 依赖
  if ! ensure_deps; then
    warn "依赖安装未成功，正在重建虚拟环境后重试…"
    if ! ensure_python; then fail "未找到可用的 Python 3，无法重建环境。"; fi
    create_venv "$SYS_PY" || fail "重建虚拟环境失败，请查看日志。"
    ensure_deps || fail "依赖仍不完整，请检查网络后重试（日志：$LOG_FILE）。"
  fi

  # 已经开着就直接打开，不重复起第二个服务
  local running_port
  running_port="$(find_running_instance || true)"
  if [ -n "$running_port" ]; then
    open "http://127.0.0.1:$running_port" >/dev/null 2>&1 || true
    say "检测到工具已经在运行，已为你打开页面：http://127.0.0.1:$running_port"
    exit 0
  fi

  # 启动（失败自动换端口重试）
  local attempt port
  for attempt in 1 2 3; do
    port="$(pick_port)"
    if [ -z "$port" ]; then
      fail "找不到可用端口（已尝试 $START_PORT 起的 50 个端口），请关闭部分程序后重试。"
    fi
    say "正在启动网页服务（端口 $port，第 $attempt 次尝试）…"
    start_server "$port"
    if wait_for_server "$port"; then
      printf '%s' "$SERVER_PID" >"$PID_FILE" 2>/dev/null || true
      printf '%s' "$port" >"$PORT_FILE" 2>/dev/null || true
      open "http://127.0.0.1:$port" >/dev/null 2>&1 || true
      say ""
      say "✅ 已启动！浏览器会自动打开：http://127.0.0.1:$port"
      say "   如未自动打开，请手动在浏览器访问上面的地址。"
      say "   关闭本终端窗口即可停止工具。"
      wait "$SERVER_PID"
      exit 0
    fi
    warn "本次启动未成功，自动换端口重试…"
    kill "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""
    sleep 1
  done

  fail "启动失败。请查看日志：$LOG_FILE"
}

main "$@"
