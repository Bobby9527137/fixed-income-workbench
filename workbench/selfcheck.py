"""工作台自检：检查配置、目录、环境、锁、端口；能修的直接修，修不了出报告。"""

from __future__ import annotations

import base64
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import diagnostics, instance, ports


def _add(checks: list[dict], name: str, ok: bool, detail: str = "", fixed: bool = False) -> None:
    checks.append({
        "name": name,
        "status": "ok" if ok and not fixed else ("fixed" if fixed else "failed"),
        "detail": detail,
    })


def run(config: Any, manager: Any, bootstrapper: Any, fix: bool = True) -> dict:
    checks: list[dict] = []
    _add(checks, "配置文件", bool(config.tools),
         f"{len(config.tools)} 个工具 / {len(config.environments)} 套环境" if config.tools else "没有工具配置")

    for tool_id, spec in config.tools.items():
        _add(checks, f"工具目录：{spec.name}", spec.root.is_dir(), str(spec.root))
        _add(checks, f"工具入口：{spec.name}", (spec.root / spec.entry).is_file(), spec.entry)

    for name in ("logs", "envs", "reports"):
        folder = config.runtime_dir / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _add(checks, f"运行目录：{name}", True, str(folder))
        except Exception as exc:  # noqa: BLE001
            _add(checks, f"运行目录：{name}", False, f"{folder}：{exc}")

    try:
        statuses = bootstrapper.status()
    except Exception as exc:  # noqa: BLE001
        statuses = {}
        _add(checks, "环境状态读取", False, str(exc))
    for env_id in config.environments:
        status = statuses.get(env_id) or {}
        state = str(status.get("state") or "unknown")
        detail = str(status.get("detail") or state)
        _add(checks, f"环境：{env_id}", state in ("ready", "installing"), f"{state} · {detail}")

    lock = instance._read_lock(config.runtime_dir)
    if lock:
        alive = instance._pid_alive(lock["pid"])
        if not alive and fix:
            instance.clear_lock(config.runtime_dir, pid=lock["pid"])
            _add(checks, "工作台锁", True, "已清理上次残留的锁", fixed=True)
        else:
            _add(checks, "工作台锁", alive, f"pid={lock['pid']} port={lock['port']}")
    else:
        _add(checks, "工作台锁", True, "无锁")

    launch = instance.launch_lock_path(config.runtime_dir)
    if launch.exists():
        try:
            age = datetime.now().timestamp() - launch.stat().st_mtime
        except OSError:
            age = 0
        if fix and age > 900:
            instance.release_launch_lock(launch)
            _add(checks, "启动锁", True, "已清理超过 15 分钟的启动锁", fixed=True)
        else:
            _add(checks, "启动锁", True, f"存在（{int(age)} 秒）")
    else:
        _add(checks, "启动锁", True, "无锁")

    try:
        if fix:
            manager.adopt_orphans()
        states = manager.states()
    except Exception as exc:  # noqa: BLE001
        states = []
        _add(checks, "工具状态读取", False, str(exc))
    for state in states:
        ok = state.get("state") != "error"
        _add(checks, f"工具：{state.get('name')}", ok,
             f"{state.get('state')} · {state.get('error') or state.get('port')}")

    for tool_id, spec in config.tools.items():
        state = next((item for item in states if item.get("id") == tool_id), None)
        actual_port = int((state or {}).get("port") or spec.port)
        is_running = (state or {}).get("state") in ("running", "starting")
        busy = ports.tcp_open("127.0.0.1", actual_port)
        if is_running:
            _add(checks, f"端口：{spec.name}", busy, f"{actual_port}（运行中）")
        elif busy:
            _add(checks, f"端口：{spec.name}", True, f"{actual_port} 被占用（启动时会顺延）")
        else:
            _add(checks, f"端口：{spec.name}", True, f"{actual_port} 可用")

    ok = all(check["status"] != "failed" for check in checks)
    report = None
    if not ok:
        report = write_report(config, manager, bootstrapper, checks)
    return {"ok": ok, "checks": checks, "report": report}


def write_report(config: Any, manager: Any, bootstrapper: Any, checks: list[dict]) -> dict:
    folder = config.runtime_dir / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"workbench-selfcheck-{stamp}.md"
    lines = [
        "# 固收工作台 · 自检报告",
        "",
        "> 本报告只保存在本机。请先自行查看，确认无误后再转发给维护者。",
        "",
        "## 概要",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 时间 | {datetime.now().isoformat(timespec='seconds')} |",
        f"| 系统 | {platform.platform()} |",
        f"| Python | {platform.python_version()} |",
        f"| 解释器 | {sys.executable} |",
        f"| 根目录 | {config.base_dir} |",
        "",
        "## 自检结果",
        "",
        "| 检查项 | 状态 | 说明 |",
        "|---|---|---|",
    ]
    for check in checks:
        lines.append(f"| {check['name']} | {check['status']} | {check['detail']} |")
    lines.extend(["", "## 诊断报告", "", "```text"])
    lines.append(diagnostics.build_report(config, manager, bootstrapper).strip())
    lines.append("```")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "path": str(path),
        "name": path.name,
        "base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
