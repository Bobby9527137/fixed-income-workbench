"""受管工具的进程生命周期、归属模型与健康轮询。

一个 :class:`ToolManager` 对应一次工作台运行：它只负责启动/停止子进程、
把状态汇报给调用方，并在异常退出后把还能连上的残留进程认领回来。
所有写操作都在同一把可重入锁里完成，后台健康轮询线程通过同一把锁
更新状态，因此 :meth:`ToolManager.states` 永远看到一致快照。
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config, ToolSpec
from .ports import pick_free_port, probe_http, tcp_open

HOST = "127.0.0.1"
STARTUP_TIMEOUT = 60.0
POLL_INTERVAL = 0.5
HEALTH_TIMEOUT = 0.5
STOP_GRACE = 5.0
TAIL_LINES = 3
EXTERNAL_DOWN_GRACE = 2.0
EXTERNAL_HTTP_GRACE = 12.0
PIDS_FILENAME = "pids.json"
LOGS_DIRNAME = "logs"

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_STOPPING = "stopping"
STATE_ERROR = "error"

OWNED_NONE = "none"
OWNED_SELF = "self"
OWNED_ORPHAN = "orphan"
OWNED_EXTERNAL = "external"

_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


@dataclass
class _Record:
    """单个工具的易变运行期状态（不对外暴露）。"""

    spec: ToolSpec
    state: str = STATE_STOPPED
    owned: str = OWNED_NONE
    port: int | None = None
    pid: int | None = None
    error: str = ""
    waited: float = 0.0
    started_at: float = 0.0
    process: Any = None
    external_down_since: float = 0.0
    external_http_since: float = 0.0
    thread: threading.Thread | None = field(default=None, repr=False)


class ToolManager:
    """按 ``Config.tools`` 管理子进程；不自动接管残留，需显式调用。"""

    def __init__(
        self,
        config: Config,
        resolve_python: Callable[[str], Path],
        *,
        popen: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._resolve_python = resolve_python
        self._popen = popen or subprocess.Popen
        self._lock = threading.RLock()
        self._records: dict[str, _Record] = {
            tool_id: _Record(spec=spec) for tool_id, spec in config.tools.items()
        }
        self._runtime = Path(config.runtime_dir)
        self._logs_dir = self._runtime / LOGS_DIRNAME
        self._pids_path = self._runtime / PIDS_FILENAME
        # 以磁盘现状为基线维护 pids.json：写回时不会顺手抹掉其他工具尚未接管的条目。
        self._pids: dict[str, dict[str, Any]] = self._read_pids()

    # ------------------------------------------------------------------ 查询
    def states(self) -> list[dict]:
        """返回所有工具的快照；顺带把“子进程已死”折算成 ``error``。"""
        with self._lock:
            snapshots = []
            for record in self._records.values():
                self._reconcile(record)
                snapshots.append(self._snapshot(record))
            return snapshots

    def log_tail(self, tool_id: str, lines: int = 50) -> str:
        """日志文件最后 ``lines`` 行（空行不计），文件不存在返回空串。"""
        self._record(tool_id)
        return self._read_log_tail(tool_id, lines)

    # ------------------------------------------------------------------ 启停
    def start(self, tool_id: str) -> dict:
        """启动工具并立即返回 ``starting``；就绪与否交给后台线程判定。"""
        with self._lock:
            record = self._record(tool_id)
            self._reconcile(record)
            if record.state in (STATE_STARTING, STATE_RUNNING):
                return self._snapshot(record)

            # 已知属于我们的进程还在（例如上一次 stop 失败）：不能再起一个，否则会
            # 覆盖 pid / 句柄 / pids 条目，旧进程彻底失去跟踪。
            if record.pid is not None:
                if not self._tracked_pid_alive(record):
                    self._release_dead_tracking(record)
                else:
                    record.state = STATE_ERROR
                    record.error = "请先停止"
                    return self._snapshot(record)

            spec = record.spec
            preferred = spec.port
            preferred_url = self._url(spec, preferred)
            # 外部探测前先与 pids.json 对账：活跃但尚未接管的残留仍属于我们，
            # 不能因为端口上的服务健康就误判成 external。
            if self._pids_entry_alive(spec.id):
                if self._pids_entry_serving(spec.id):
                    record.state = STATE_ERROR
                    record.error = "请先停止"
                    return self._snapshot(record)
                if self._pids_entry_stale(spec.id):
                    # pid 还活着但端口上已经不是这个工具（PID 被系统复用等）：
                    # 陈旧条目留着会让 start() 永远提示“请先停止”，直接清掉。
                    self._drop_pids_entry(spec.id)
                else:
                    # 刚记下的条目还年轻：可能上一次实例正在启动，先别急着另起一份。
                    record.state = STATE_ERROR
                    record.error = "上一次的实例可能仍在启动，请稍后再试或点『停止』清理后重启"
                    return self._snapshot(record)
            # 只探目标端口：端口上已有健康服务且不是我们起的 → 外部实例。
            if probe_http(preferred_url, timeout=HEALTH_TIMEOUT):
                record.state = STATE_RUNNING
                record.owned = OWNED_EXTERNAL
                record.port = preferred
                record.pid = None
                record.process = None
                record.error = ""
                record.waited = 0.0
                record.external_down_since = 0.0
                record.external_http_since = 0.0
                return self._snapshot(record)

            port = pick_free_port(preferred)
            if port is None:
                record.state = STATE_ERROR
                record.owned = OWNED_NONE
                record.error = (
                    f"端口 {preferred}-{preferred + 19} 都不可用，无法启动 {spec.name}"
                )
                return self._snapshot(record)

            try:
                command = self._command(spec, port)
            except Exception as exc:  # noqa: BLE001 - 明确落到卡片上的错误
                record.state = STATE_ERROR
                record.owned = OWNED_NONE
                record.error = f"无法构造启动命令：{exc}"
                return self._snapshot(record)

            try:
                process = self._spawn(spec, command)
            except OSError as exc:
                record.state = STATE_ERROR
                record.owned = OWNED_NONE
                record.error = f"启动失败：{exc}"
                return self._snapshot(record)

            record.process = process
            record.state = STATE_STARTING
            record.owned = OWNED_SELF
            record.port = port
            record.pid = process.pid
            record.error = ""
            record.waited = 0.0
            record.external_down_since = 0.0
            record.external_http_since = 0.0
            record.started_at = time.time()
            self._pids[spec.id] = {
                "pid": process.pid,
                "port": port,
                "started_at": record.started_at,
            }
            self._write_pids()

            thread = threading.Thread(
                target=self._poll_until_ready,
                args=(record,),
                name=f"wb-health-{spec.id}",
                daemon=True,
            )
            record.thread = thread
            thread.start()
            return self._snapshot(record)

    def stop(self, tool_id: str) -> dict:
        """停止本次启动的或接管的残留进程；外部实例拒绝停止。"""
        with self._lock:
            record = self._record(tool_id)
            self._reconcile(record)

            if record.owned == OWNED_EXTERNAL:
                raise PermissionError("外部实例，不能从工作台停止")

            if record.state == STATE_STOPPED:
                if tool_id in self._pids:
                    self._drop_pids_entry(tool_id)
                return self._snapshot(record)
            if record.state == STATE_STOPPING:
                return self._snapshot(record)

            record.state = STATE_STOPPING
            pid = record.pid
            process = record.process
            ok = True
            message = ""
            if pid is not None:
                if process is not None:
                    ok, message = self._terminate_process(process)
                else:
                    ok, message = self._terminate_pid(pid)

            record.waited = 0.0
            if ok:
                record.process = None
                record.pid = None
                record.port = None
                record.state = STATE_STOPPED
                record.owned = OWNED_NONE
                record.error = ""
                self._pids.pop(tool_id, None)
            else:
                # 没杀掉就保留 pid / 句柄和 pids.json 条目，下一次 stop 还能重试。
                record.state = STATE_ERROR
                record.error = message or "进程未能停止"
            self._write_pids()
            return self._snapshot(record)

    def start_all(self) -> list[dict]:
        """依次启动全部工具；单个失败不影响其他工具。"""
        for tool_id in list(self._records):
            try:
                self.start(tool_id)
            except Exception as exc:  # noqa: BLE001 - 批量启动不中断
                with self._lock:
                    record = self._records[tool_id]
                    record.state = STATE_ERROR
                    record.error = f"启动失败：{exc}"
        return self.states()

    def stop_all(self) -> None:
        """幂等停止；外部实例被跳过，任何单个失败都不阻止继续清理。"""
        for tool_id in list(self._records):
            try:
                self.stop(tool_id)
            except PermissionError:
                continue
            except Exception:
                continue

    def shutdown(self) -> None:
        """停止全部可停的进程并清空 ``pids.json``。"""
        self.stop_all()
        with self._lock:
            self._pids = {}
            self._write_pids()

    # ------------------------------------------------------------------ 接管
    def adopt_orphans(self) -> None:
        """认领上次残留：pid 存活且健康检查通过才保留，否则丢弃条目。"""
        with self._lock:
            raw_tools = self._read_pids()
            # 不属于本配置的条目原样保留；本配置内的条目逐个复验，验不过就丢弃。
            retained = {
                tool_id: entry
                for tool_id, entry in self._pids.items()
                if tool_id not in self._records
            }
            # 内存里正在跑/正在启动的条目必须先保住：pids.json 被人删掉时
            # 不能因为“磁盘上没有”就把跟踪丢了。
            for tool_id, record in self._records.items():
                if record.state in (STATE_STARTING, STATE_RUNNING, STATE_STOPPING):
                    entry = self._pids.get(tool_id)
                    if entry is not None:
                        retained[tool_id] = entry
            for tool_id, entry in raw_tools.items():
                record = self._records.get(tool_id)
                if record is None:
                    retained[tool_id] = entry
                    continue
                # 已经是本次启动/已接管的工具，不降级。
                if record.state in (
                    STATE_STARTING,
                    STATE_RUNNING,
                    STATE_STOPPING,
                ):
                    retained[tool_id] = entry
                    continue
                pid = entry.get("pid")
                port = entry.get("port")
                if (
                    isinstance(pid, bool)
                    or not isinstance(pid, int)
                    or isinstance(port, bool)
                    or not isinstance(port, int)
                    or not 1 <= port <= 65535
                ):
                    continue
                if not _pid_alive(pid):
                    continue
                if not probe_http(self._url(record.spec, port), timeout=HEALTH_TIMEOUT):
                    continue
                started_at = entry.get("started_at", 0.0)
                if isinstance(started_at, bool) or not isinstance(
                    started_at, (int, float)
                ):
                    started_at = 0.0
                record.state = STATE_RUNNING
                record.owned = OWNED_ORPHAN
                record.pid = pid
                record.port = port
                record.process = None
                record.error = ""
                record.waited = 0.0
                record.started_at = float(started_at)
                retained[tool_id] = {
                    "pid": pid,
                    "port": port,
                    "started_at": float(started_at),
                }
            self._pids = retained
            self._write_pids()

    # ------------------------------------------------------------------ 内部
    def _record(self, tool_id: str) -> _Record:
        try:
            return self._records[tool_id]
        except KeyError as exc:
            raise KeyError(f"未知工具：{tool_id}") from exc

    def _snapshot(self, record: _Record) -> dict:
        port = record.port if record.port is not None else record.spec.port
        return {
            "id": record.spec.id,
            "name": record.spec.name,
            "desc": record.spec.desc,
            "state": record.state,
            "port": port,
            "url": self._url(record.spec, port),
            "pid": record.pid,
            "owned": record.owned,
            "error": record.error,
            "waited": round(record.waited, 1),
            "started_at": record.started_at,
            "environment": record.spec.environment,
            "dirs": dict(record.spec.dirs),
        }

    @staticmethod
    def _url(spec: ToolSpec, port: int) -> str:
        return f"http://{HOST}:{port}{spec.health_path}"

    def _reconcile(self, record: _Record) -> None:
        """在 ``states()`` 时把“已经死掉”的进程折算成 error。"""
        if record.state not in (STATE_STARTING, STATE_RUNNING):
            return
        if record.owned == OWNED_SELF and record.process is not None:
            code = record.process.poll()
            if code is not None:
                self._mark_error(record, f"进程已退出（退出码 {code}）")
                record.process = None
                record.pid = None
                self._pids.pop(record.spec.id, None)
                self._write_pids()
        elif record.owned == OWNED_ORPHAN and record.pid is not None:
            if not _pid_alive(record.pid):
                self._mark_error(record, "残留进程已退出")
                record.pid = None
                self._pids.pop(record.spec.id, None)
                self._write_pids()
        elif record.owned == OWNED_EXTERNAL:
            # 外部实例自行退出是正常事件：连续一段时间探测不到就归还为 stopped，
            # 让 start() 重新拉起属于我们的实例，而不是永久卡在 running。
            # 用 TCP 监听 + 时间宽限双重判据，避免外部实例瞬时卡顿被误判成已死，
            # 进而在另一个端口重复起一份、两个实例同时写同一份数据。
            port = record.port if record.port is not None else record.spec.port
            now = time.monotonic()
            if not tcp_open(HOST, port):
                record.external_http_since = 0.0
                if record.external_down_since <= 0.0:
                    record.external_down_since = now
                    return
                if now - record.external_down_since < EXTERNAL_DOWN_GRACE:
                    return
                record.external_down_since = 0.0
                record.state = STATE_STOPPED
                record.owned = OWNED_NONE
                record.port = None
                record.pid = None
                record.process = None
                record.error = ""
                record.waited = 0.0
                return
            record.external_down_since = 0.0
            if probe_http(self._url(record.spec, port), timeout=HEALTH_TIMEOUT):
                record.external_http_since = 0.0
                return
            # 端口还在监听但不是这个工具在响应（被别的程序占用 / 工具自身卡死）：
            # 给足宽限后转成可读的 error，否则卡片永远停在"外部实例"且不能操作。
            if record.external_http_since <= 0.0:
                record.external_http_since = now
                return
            if now - record.external_http_since < EXTERNAL_HTTP_GRACE:
                return
            record.external_http_since = 0.0
            record.state = STATE_ERROR
            record.error = (
                f"端口 {port} 上没有 {record.spec.name} 的响应，可能被其他程序占用；"
                "请关闭占用该端口的程序后重试"
            )

    def _tracked_pid_alive(self, record: _Record) -> bool:
        if record.process is not None:
            return record.process.poll() is None
        return record.pid is not None and _pid_alive(record.pid)

    def _release_dead_tracking(self, record: _Record) -> None:
        """进程已经自己退出时清掉残留跟踪，避免 error 状态永久阻塞 start()。"""
        record.process = None
        record.pid = None
        record.port = None
        record.owned = OWNED_NONE
        record.state = STATE_STOPPED
        record.error = ""
        record.waited = 0.0
        self._pids.pop(record.spec.id, None)
        self._write_pids()

    def _pids_entry_alive(self, tool_id: str) -> bool:
        """只看 pids.json：活跃但尚未 adopt 的残留进程仍然属于我们。"""
        entry = self._read_pids().get(tool_id)
        if entry is None:
            return False
        pid = entry.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return False
        return _pid_alive(pid)

    def _pids_entry_stale(self, tool_id: str) -> bool:
        """条目的 ``started_at`` 无法解析或已超过一次启动窗口，视为陈旧。"""
        entry = self._read_pids().get(tool_id) or {}
        started_at = entry.get("started_at", 0.0)
        if (
            isinstance(started_at, bool)
            or not isinstance(started_at, (int, float))
            or started_at <= 0
        ):
            return True
        delta = time.time() - float(started_at)
        if not math.isfinite(delta) or delta < 0:
            # NaN/inf 或系统时钟回拨：时间戳不可信，按陈旧处理，免得永久卡住启动。
            return True
        return delta > STARTUP_TIMEOUT + STOP_GRACE

    def _pids_entry_serving(self, tool_id: str) -> bool:
        """pids.json 里该工具的端口上是否还有健康的服务。"""
        entry = self._read_pids().get(tool_id) or {}
        port = entry.get("port")
        spec = self._records[tool_id].spec
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return False
        return probe_http(self._url(spec, port), timeout=HEALTH_TIMEOUT)

    def _drop_pids_entry(self, tool_id: str) -> None:
        """只删除一个工具的条目，保留其他工具尚未接管的残留。"""
        self._pids.pop(tool_id, None)
        self._write_pids()

    def _mark_error(self, record: _Record, prefix: str) -> None:
        tail = self._read_log_tail(record.spec.id, TAIL_LINES)
        record.state = STATE_ERROR
        record.error = f"{prefix}\n{tail}" if tail else prefix

    def _poll_until_ready(self, record: _Record) -> None:
        started = time.monotonic()
        deadline = started + STARTUP_TIMEOUT
        while True:
            time.sleep(POLL_INTERVAL)
            with self._lock:
                if record.state != STATE_STARTING:
                    return
                process = record.process
                if process is None:
                    return
                code = process.poll()
                if code is not None:
                    self._mark_error(record, f"进程已退出（退出码 {code}）")
                    record.process = None
                    record.pid = None
                    self._pids.pop(record.spec.id, None)
                    self._write_pids()
                    return

                record.waited = time.monotonic() - started
                if record.port is not None and probe_http(
                    self._url(record.spec, record.port), timeout=HEALTH_TIMEOUT
                ):
                    record.state = STATE_RUNNING
                    record.error = ""
                    return

                if time.monotonic() >= deadline:
                    self._mark_error(
                        record, f"启动超时（{int(STARTUP_TIMEOUT)} 秒）"
                    )
                    # 没就绪的进程留着只会占端口，停止它但保留日志尾。
                    ok, message = self._terminate_process(process)
                    if ok:
                        record.process = None
                        record.owned = OWNED_NONE
                        record.pid = None
                        self._pids.pop(record.spec.id, None)
                    else:
                        # 杀不掉时保留 pid / 句柄，交给 stop() 或 shutdown() 重试。
                        record.error = f"{record.error}\n{message}"
                    self._write_pids()
                    return

    def _command(self, spec: ToolSpec, port: int) -> list[str]:
        python = str(Path(self._resolve_python(spec.environment)))
        entry = Path(spec.entry)
        if not entry.is_absolute():
            entry = Path(spec.root) / entry
        if spec.kind == "streamlit":
            command = [
                python,
                "-m",
                "streamlit",
                "run",
                str(entry),
                "--server.address",
                HOST,
                "--server.port",
                str(port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ]
        else:
            command = [python, str(entry)]
        command.extend(arg.replace("{port}", str(port)) for arg in spec.args)
        return command

    def _spawn(self, spec: ToolSpec, command: list[str]) -> Any:
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._logs_dir / f"{spec.id}.log"
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        # 所有工具统一浅色主题，避免工作台（白）与工具页（跟随系统变黑）割裂。
        environment["STREAMLIT_THEME_BASE"] = "light"
        environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

        options: dict[str, Any] = {
            "cwd": str(spec.root),
            "stdin": subprocess.DEVNULL,
            "env": environment,
        }
        if sys.platform == "win32":
            options["creationflags"] = _CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True

        with open(log_path, "ab", buffering=0) as log_file:
            options["stdout"] = log_file
            options["stderr"] = subprocess.STDOUT
            return self._popen(command, **options)

    def _terminate_process(self, process: Any) -> tuple[bool, str]:
        if process.poll() is not None:
            return True, ""
        if sys.platform == "win32":
            ok, message = self._terminate_pid(process.pid)
            if not ok:
                return ok, message
            # taskkill 之后必须 wait() 回收句柄，否则 Popen 析构会报 ResourceWarning。
            try:
                process.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                return False, "进程未能停止"
            return True, ""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            try:
                process.terminate()
            except OSError:
                return self._terminate_pid(process.pid)
        try:
            process.wait(timeout=STOP_GRACE)
            return True, ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=STOP_GRACE)
                return True, ""
            except subprocess.TimeoutExpired:
                return False, "进程未能停止"

    def _terminate_pid(self, pid: int) -> tuple[bool, str]:
        if not _pid_alive(pid):
            return True, ""
        if sys.platform == "win32":
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=STOP_GRACE + 5,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return False, f"停止失败：{exc}"
            if completed.returncode == 0 or not _pid_alive(pid):
                self._wait_pid_gone(pid)
                return True, ""
            return False, f"停止失败：taskkill 退出码 {completed.returncode}"

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return True, ""
        if self._wait_pid_gone(pid, STOP_GRACE):
            return True, ""
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return True, ""
        if self._wait_pid_gone(pid, STOP_GRACE):
            return True, ""
        return False, "进程未能停止"

    @staticmethod
    def _wait_pid_gone(pid: int, timeout: float = STOP_GRACE) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return True
            time.sleep(0.1)
        return not _pid_alive(pid)

    def _read_log_tail(self, tool_id: str, lines: int) -> str:
        """日志文件最后 ``lines`` 行；只读文件末尾 64KB，避免整文件进内存。"""
        if lines <= 0:
            return ""
        path = self._logs_dir / f"{tool_id}.log"
        tail_bytes = 64 * 1024
        try:
            with path.open("rb") as log:
                log.seek(0, os.SEEK_END)
                size = log.tell()
                log.seek(max(0, size - tail_bytes))
                data = log.read()
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        if size > tail_bytes:
            # 截断点可能落在行中间，丢掉第一个不完整行。
            newline = text.find("\n")
            if newline >= 0:
                text = text[newline + 1 :]
        rows = [row for row in text.splitlines() if row.strip()]
        return "\n".join(rows[-lines:])

    def _read_pids(self) -> dict[str, dict[str, Any]]:
        try:
            text = self._pids_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        tools = data.get("tools")
        if not isinstance(tools, dict):
            return {}
        return {key: value for key, value in tools.items() if isinstance(value, dict)}

    def _write_pids(self) -> None:
        tools: dict[str, dict[str, Any]] = {}
        for tool_id, entry in self._pids.items():
            try:
                tools[tool_id] = {
                    "pid": int(entry["pid"]),
                    "port": int(entry["port"]),
                    "started_at": float(entry.get("started_at", 0.0)),
                }
            except (KeyError, TypeError, ValueError):
                # 手改坏的条目不该让整次写入崩掉，直接丢弃。
                continue
        payload = {"tools": tools}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._pids_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".pids-", suffix=".tmp", dir=str(self._pids_path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._pids_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise


def _pid_alive(pid: int) -> bool:
    """只查询不发送信号：Windows 的 ``os.kill(pid, 0)`` 会杀进程。"""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
