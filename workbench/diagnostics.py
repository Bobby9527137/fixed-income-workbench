"""生成纯文本诊断报告：给维护者远程定位问题用，不允许本身抛异常。

报告逐段生成，单段失败只写「读取失败：…」，其余内容照常输出。
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from . import __version__
from .ports import probe_http

LEGACY_HEALTH_URL = "http://127.0.0.1:8501/_stcore/health"
LEGACY_TIMEOUT = 0.3
LOG_TAIL_LINES = 20
LOG_DIRNAME = "logs"


def build_report(config: Any, manager: Any, bootstrapper: Any) -> str:
    """返回 UTF-8 纯文本报告；任何内部异常都折算成文本。"""
    lines: list[str] = []
    try:
        _build(lines, config, manager, bootstrapper)
    except Exception as exc:  # noqa: BLE001 - 报告生成器本身绝不能崩
        lines.append("")
        lines.append(f"报告生成中断：{_describe(exc)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- 内部
def _build(lines: list[str], config: Any, manager: Any, bootstrapper: Any) -> None:
    lines.append("固收工作台 诊断报告")
    lines.append("=" * 48)

    lines.append(f"生成时间：{_now()}")
    _section(lines, "运行环境", lambda: _system_lines(config))
    _section(lines, "工作台", lambda: _workbench_lines(config))
    _section(lines, "环境状态", lambda: _environment_lines(bootstrapper))
    _section(lines, "环境材料", lambda: _material_lines(config))

    try:
        states = manager.states()
        if not isinstance(states, list):
            raise TypeError(f"manager.states() 返回 {type(states).__name__}")
        tool_error = ""
    except Exception as exc:  # noqa: BLE001
        states = []
        tool_error = _describe(exc)

    _section(lines, "工具状态", lambda: _tool_lines(states, tool_error))
    _section(lines, "旧实例探测（8501）", _legacy_lines)
    _section(
        lines,
        f"工具日志（每个工具最后 {LOG_TAIL_LINES} 行）",
        lambda: _log_lines(config, manager, states),
    )


def _section(
    lines: list[str], title: str, producer: Callable[[], Iterable[str]]
) -> None:
    """追加一段；``producer`` 抛出的异常折算成「读取失败」。"""
    lines.append("")
    lines.append(f"[{title}]")
    try:
        rows = producer()
        if isinstance(rows, str):
            rows = [rows]
        for row in rows:
            lines.append(str(row))
    except Exception as exc:  # noqa: BLE001 - 单段失败不能拖垮整份报告
        lines.append(f"读取失败：{_describe(exc)}")


def _system_lines(config: Any) -> list[str]:
    rows = [
        f"操作系统：{platform.platform()}",
        f"系统：{platform.system()} {platform.release()}（{platform.version()}）",
        f"机器架构：{platform.machine()}",
        f"Python：{platform.python_version()}",
        f"解释器：{sys.executable}",
        f"工作台版本：{__version__}",
    ]
    try:
        rows.append(f"runtime 目录：{Path(config.runtime_dir)}")
        rows.append(f"交付目录：{Path(config.base_dir)}")
        rows.append(f"工作台配置端口：{config.workbench_port}")
        archive = config.python_archive
        rows.append(
            f"内置 Python 包：{archive or '未配置（使用系统 Python）'}"
        )
    except Exception as exc:  # noqa: BLE001
        rows.append(f"配置读取失败：{_describe(exc)}")
    return rows


def _workbench_lines(config: Any) -> list[str]:
    rows = [f"进程 pid：{os.getpid()}"]
    bound = getattr(config, "bound_port", None)
    if isinstance(bound, bool) or not isinstance(bound, int):
        rows.append("实际端口：未知")
    else:
        rows.append(f"实际端口：{bound}")
    try:
        rows.append(f"配置端口：{config.workbench_port}")
    except Exception as exc:  # noqa: BLE001
        rows.append(f"配置端口：读取失败：{_describe(exc)}")
    rows.extend(_lock_lines(config))
    rows.extend(_pids_lines(config))
    return rows


def _lock_lines(config: Any) -> list[str]:
    path = Path(config.runtime_dir) / "workbench.lock"
    if not path.is_file():
        return [f"workbench.lock：{path}（无）"]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"workbench.lock：读取失败：{_describe(exc)}"]
    try:
        data = json.loads(text)
    except ValueError:
        return [f"workbench.lock：{path}", f"  内容无法解析：{text.strip()[:200]}"]
    if not isinstance(data, dict):
        return [f"workbench.lock：{path}", f"  内容类型异常：{type(data).__name__}"]
    return [
        f"workbench.lock：{path}",
        f"  pid={data.get('pid')} port={data.get('port')} "
        f"started_at={data.get('started_at')}",
    ]


def _pids_lines(config: Any) -> list[str]:
    path = Path(config.runtime_dir) / "pids.json"
    if not path.is_file():
        return [f"pids.json：{path}（无）"]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"pids.json：读取失败：{_describe(exc)}"]
    try:
        data = json.loads(text)
    except ValueError:
        return [f"pids.json：{path}", f"  内容无法解析：{text.strip()[:200]}"]
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, dict):
        return [f"pids.json：{path}", "  内容缺少 tools 对象"]
    rows = [f"pids.json：{path}（{len(tools)} 个条目）"]
    if not tools:
        rows.append("  （无条目）")
    for tool_id, entry in tools.items():
        if not isinstance(entry, dict):
            rows.append(f"  {tool_id}: {entry!r}")
            continue
        rows.append(
            f"  {tool_id}: pid={entry.get('pid')} port={entry.get('port')} "
            f"started_at={entry.get('started_at')}"
        )
    return rows


def _material_lines(config: Any) -> list[str]:
    environments = config.environments
    if not isinstance(environments, dict) or not environments:
        return ["（没有环境）"]
    rows = []
    for env_id, spec in environments.items():
        try:
            requirements = Path(spec.requirements)
            wheelhouse = Path(spec.wheelhouse)
        except Exception as exc:  # noqa: BLE001
            rows.append(f"{env_id}: 读取失败：{_describe(exc)}")
            continue
        requirements_ok = requirements.is_file()
        wheelhouse_ok = wheelhouse.is_dir()
        rows.append(
            f"{env_id}: requirements="
            f"{'存在' if requirements_ok else '缺失'}（{requirements}）"
        )
        rows.append(
            f"{env_id}: wheelhouse="
            f"{'存在' if wheelhouse_ok else '缺失'}（{wheelhouse}）"
        )
    return rows


def _environment_lines(bootstrapper: Any) -> list[str]:
    status = bootstrapper.status()
    if not isinstance(status, dict) or not status:
        return ["（没有环境信息）"]
    rows = []
    for env_id, entry in status.items():
        if not isinstance(entry, dict):
            rows.append(f"{env_id}: {entry!r}")
            continue
        rows.append(
            f"{env_id}: state={entry.get('state', '?')} "
            f"detail={entry.get('detail', '')} "
            f"progress={entry.get('progress', '?')}"
        )
    return rows


def _tool_lines(states: list[Any], tool_error: str) -> list[str]:
    if tool_error:
        return [f"读取失败：{tool_error}"]
    if not states:
        return ["（没有工具信息）"]
    rows = []
    for entry in states:
        if not isinstance(entry, dict):
            rows.append(f"{entry!r}")
            continue
        rows.append(
            f"{entry.get('id', '?')}: "
            f"state={entry.get('state', '?')} "
            f"owned={entry.get('owned', '?')} "
            f"port={entry.get('port', '?')} "
            f"pid={entry.get('pid')} "
            f"url={entry.get('url', '')}"
        )
        error = str(entry.get("error") or "").strip()
        if error:
            for row in error.splitlines():
                rows.append(f"    error: {row}")
    return rows


def _legacy_lines() -> list[str]:
    alive = probe_http(LEGACY_HEALTH_URL, timeout=LEGACY_TIMEOUT)
    if alive:
        return [
            f"{LEGACY_HEALTH_URL}：有响应"
            "（可能是手动开的旧实例，建议关闭后从工作台统一启动）"
        ]
    return [f"{LEGACY_HEALTH_URL}：无响应"]


def _log_lines(config: Any, manager: Any, states: list[Any]) -> list[str]:
    tool_ids: list[str] = []
    for entry in states:
        if isinstance(entry, dict) and entry.get("id"):
            tool_ids.append(str(entry["id"]))
    if not tool_ids:
        try:
            tool_ids = [str(tool_id) for tool_id in config.tools]
        except Exception:  # noqa: BLE001
            tool_ids = []

    runtime = Path(config.runtime_dir)
    rows: list[str] = []
    for tool_id in tool_ids:
        path = runtime / LOG_DIRNAME / f"{tool_id}.log"
        rows.append(f"--- {tool_id}（{path}）")
        if not path.is_file():
            rows.append("（无日志）")
            continue
        try:
            text = manager.log_tail(tool_id, LOG_TAIL_LINES)
        except Exception as exc:  # noqa: BLE001
            rows.append(f"读取失败：{_describe(exc)}")
            continue
        rows.append(text if text.strip() else "（空日志）")
    if not rows:
        rows.append("（没有可读取的工具）")
    return rows


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z")


def _describe(exc: BaseException) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
