"""端到端自检：等环境就绪 → 起真实工具 → 等 healthy → 停止 → 验证端口释放。

用法（在交付包根目录）：

    python scripts/selftest.py                 # 四个工具全跑
    python scripts/selftest.py --tool wacc     # 只跑一个（可重复）
    python scripts/selftest.py --no-bootstrap  # 跳过环境安装（环境已就绪时更快）

退出码 0 = 全部通过；1 = 有工具失败；2 = 参数/配置错误。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workbench import config as config_mod  # noqa: E402
from workbench import ports  # noqa: E402
from workbench.bootstrap import Bootstrapper  # noqa: E402
from workbench.manager import ToolManager  # noqa: E402

HOST = "127.0.0.1"
BOOTSTRAP_TIMEOUT = 900.0
DEFAULT_TOOL_TIMEOUT = 180.0
POLL_INTERVAL = 0.5


def wait_for_environments(
    bootstrapper: Bootstrapper,
    *,
    timeout: float = BOOTSTRAP_TIMEOUT,
    out: Callable[[str], None] = print,
) -> tuple[bool, list[str]]:
    """等所有 env 就绪；返回 (是否成功, 没就绪的说明)。"""
    bootstrapper.ensure_all_async()
    deadline = time.monotonic() + timeout
    reported: set[str] = set()
    while True:
        statuses = bootstrapper.status()
        env_items = {
            key: value for key, value in statuses.items() if key != "python"
        }
        for key, value in env_items.items():
            detail = str(value.get("detail", ""))
            if value.get("state") in ("installing", "extracting") and key not in reported:
                reported.add(key)
                out(f"环境 {key}：{detail}")
        if all(value.get("state") == "ready" for value in env_items.values()):
            return True, []
        bad = [
            f"{key}：{value.get('detail') or value.get('state')}"
            for key, value in env_items.items()
            if value.get("state") == "error"
        ]
        if bad:
            return False, bad
        if time.monotonic() >= deadline:
            pending = [
                f"{key}：{value.get('detail') or value.get('state')}"
                for key, value in env_items.items()
                if value.get("state") != "ready"
            ]
            return False, pending or ["环境准备超时"]
        time.sleep(POLL_INTERVAL)


def wait_for_state(
    manager: ToolManager,
    tool_id: str,
    wanted: Iterable[str],
    *,
    timeout: float,
) -> dict[str, Any]:
    """轮询到目标状态；超时返回最后一次快照。"""
    wanted_set = set(wanted)
    deadline = time.monotonic() + max(float(timeout), 0.0)
    snapshot: dict[str, Any] = {}
    while True:
        for item in manager.states():
            if item.get("id") == tool_id:
                snapshot = item
                break
        if snapshot.get("state") in wanted_set:
            return snapshot
        if time.monotonic() >= deadline:
            return snapshot
        time.sleep(0.2)


def _snapshot(manager: ToolManager, tool_id: str) -> dict[str, Any]:
    for item in manager.states():
        if item.get("id") == tool_id:
            return item
    return {}


def run(
    config: config_mod.Config,
    manager: ToolManager,
    bootstrapper: Bootstrapper,
    tool_ids: list[str],
    *,
    timeout: float = DEFAULT_TOOL_TIMEOUT,
    skip_bootstrap: bool = False,
    out: Callable[[str], None] = print,
) -> int:
    """逐个工具跑一遍状态机；返回 0 表示全部通过。"""
    if not skip_bootstrap:
        out("正在检查运行环境…")
        ok, problems = wait_for_environments(bootstrapper, out=out)
        if not ok:
            for problem in problems:
                out(f"环境未就绪：{problem}")
            return 1
        out("环境已就绪。")

    failures = 0
    for tool_id in tool_ids:
        spec = config.tools.get(tool_id)
        if spec is None:
            out(f"{tool_id}: 未知工具")
            failures += 1
            continue

        before = _snapshot(manager, tool_id)
        if before.get("state") != "stopped":
            out(f"{tool_id}: 起始状态不是 stopped（{before.get('state')}），先停止")
            try:
                manager.stop(tool_id)
            except Exception as exc:  # noqa: BLE001 - 自检要把原因打出来
                out(f"{tool_id}: 无法停止（{exc}）")
                failures += 1
                continue
            before = wait_for_state(manager, tool_id, {"stopped"}, timeout=30)
            if before.get("state") != "stopped":
                out(f"{tool_id}: 停止失败（{before.get('state')}）")
                failures += 1
                continue

        started = manager.start(tool_id)
        out(f"{tool_id}: 启动请求已接受（{started.get('state')}，端口 {started.get('port')}）")
        running = wait_for_state(manager, tool_id, {"running", "error"}, timeout=timeout)
        if running.get("state") != "running":
            out(f"{tool_id}: 未就绪（{running.get('state')}）")
            detail = str(running.get("error") or "").strip()
            if detail:
                out(detail[-1500:])
            failures += 1
            try:
                manager.stop(tool_id)
            except Exception:  # noqa: BLE001 - 尽力清理
                pass
            continue

        port = int(running.get("port") or spec.port)
        out(f"{tool_id}: 已就绪（{running.get('owned')}，端口 {port}）")
        manager.stop(tool_id)
        stopped = wait_for_state(manager, tool_id, {"stopped"}, timeout=30)
        if stopped.get("state") != "stopped":
            out(f"{tool_id}: 停止超时（{stopped.get('state')}）")
            failures += 1
            continue
        if ports.tcp_open(HOST, port, timeout=0.3):
            out(f"{tool_id}: 停止后端口 {port} 仍在监听")
            failures += 1
            continue

        out(f"{tool_id}: stopped -> starting -> running -> stopped")
    return 0 if failures == 0 else 1


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="固收工作台端到端自检")
    parser.add_argument(
        "--tool",
        action="append",
        default=None,
        help="只测指定工具（可重复），默认全部",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TOOL_TIMEOUT, help="单个工具的就绪超时（秒）"
    )
    parser.add_argument(
        "--no-bootstrap", action="store_true", help="跳过环境安装（环境必须已就绪）"
    )
    parser.add_argument("--runtime", default=None, help="覆盖 runtime 目录（默认用户目录）")
    parser.add_argument("--base", default=None, help="交付包根目录（默认脚本上一级）")
    args = parser.parse_args(argv)

    base = Path(args.base).expanduser() if args.base else PROJECT_ROOT
    runtime = Path(args.runtime).expanduser() if args.runtime else None
    try:
        config = config_mod.load_config(base, runtime)
    except config_mod.ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    tool_ids = args.tool or list(config.tools)
    unknown = [tool for tool in tool_ids if tool not in config.tools]
    if unknown:
        print(f"未知工具：{', '.join(unknown)}", file=sys.stderr)
        return 2

    bootstrapper = Bootstrapper(config)
    manager = ToolManager(config, bootstrapper.venv_python)
    try:
        manager.adopt_orphans()
        return run(
            config,
            manager,
            bootstrapper,
            tool_ids,
            timeout=args.timeout,
            skip_bootstrap=args.no_bootstrap,
        )
    finally:
        try:
            manager.shutdown()
        except Exception as exc:  # noqa: BLE001 - 清理失败不掩盖自检结果
            print(f"清理失败：{exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
