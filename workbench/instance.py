"""单实例锁：记录「哪个 pid 在哪个端口上跑工作台」，并用 ``/api/ping`` 复验。

锁文件是 ``<runtime>/workbench.lock``，内容为
``{"pid": …, "port": …, "started_at": …}``。写入走「同目录临时文件 +
:func:`os.replace`」，因此读方永远看不到半截 JSON。

本模块只负责「写锁、删锁、判断是否已有实例」，**不删别人的锁**：
锁是否过期、要不要清理，由调用方（``start.py``）决定。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

LOCK_FILENAME = "workbench.lock"
LAUNCH_LOCK_FILENAME = "launch.lock"
LAUNCH_LOCK_STALE = 600.0
LAUNCH_LOCK_POLL = 0.05
APP_NAME = "固收工作台"
PING_PATH = "/api/ping"
PING_TIMEOUT = 1.0
_MAX_PING_BYTES = 64 * 1024
_RETRY_ATTEMPTS = 5
_RETRY_DELAY = 0.01


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """单实例心跳禁止重定向：302 到别处绝不能当成“我们的工作台”。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# 显式禁用代理：单实例探测只允许访问本机回环，不能被 http_proxy 劫持。
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect()
)


def lock_path(runtime_dir: Path) -> Path:
    """返回 runtime 目录下的锁文件路径。"""
    return Path(runtime_dir) / LOCK_FILENAME


def launch_lock_path(runtime_dir: Path) -> Path:
    """返回「正在启动」互斥文件路径（与 workbench.lock 生命周期不同）。"""
    return Path(runtime_dir) / LAUNCH_LOCK_FILENAME


def write_lock(runtime_dir: Path, pid: int, port: int) -> None:
    """原子写入锁文件；目录不存在会先创建。"""
    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": int(pid),
        "port": int(port),
        "started_at": time.time(),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    target = lock_path(runtime)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".workbench-lock-", suffix=".tmp", dir=str(runtime)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def acquire_launch_lock(
    runtime_dir: Path, timeout: float = 30.0
) -> Path | None:
    """抢占启动互斥锁，成功返回锁文件路径，超时返回 ``None``。

    只保护「从检查已有实例到 HTTP 服务真正可 ping」这一段：并发双击时
    只有一个启动器能往下走，其余等待。锁内容含 pid 与创建时间；mtime 超过
    :data:`LAUNCH_LOCK_STALE` 视为上次崩溃留下的僵尸锁，可回收。

    调用方必须在 ``finally`` 里 :func:`release_launch_lock`。
    """
    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    target = launch_lock_path(runtime)
    deadline = time.monotonic() + max(float(timeout), 0.0)
    payload = (
        json.dumps(
            {"pid": os.getpid(), "created_at": time.time()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    while True:
        try:
            descriptor = os.open(
                target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
        except FileExistsError:
            if _launch_lock_is_stale(target):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                return None
            time.sleep(LAUNCH_LOCK_POLL)
            continue
        try:
            os.write(descriptor, payload)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                target.unlink()
            except OSError:
                pass
            raise
        os.close(descriptor)
        return target


def release_launch_lock(path: Path) -> None:
    """只删除自己 pid 持有的启动锁；文件不存在或已被回收时静默。"""
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return
    if not isinstance(data, dict) or data.get("pid") != os.getpid():
        return
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def clear_lock(runtime_dir: Path, pid: int | None = None) -> None:
    """删除锁文件；文件不存在或 Windows 上短暂被占用时静默（幂等）。

    传 ``pid`` 时只删内容里 pid 匹配的锁，避免启动失败方把赢家的锁删掉。
    """
    if pid is not None:
        current = _read_lock(runtime_dir)
        if current is None or current["pid"] != pid:
            return
    target = lock_path(runtime_dir)
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            target.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == _RETRY_ATTEMPTS - 1:
                return
            time.sleep(_RETRY_DELAY)


def find_running(runtime_dir: Path, preferred_port: int) -> int | None:
    """返回已经在运行的工作台端口，没有则返回 ``None``。

    判定顺序：

    1. 读锁；有锁就只认锁里的端口，且 ``/api/ping`` 的 ``app`` 与 ``pid``
       都要对得上。对不上（服务死了、pid 变了、端口被别的程序占了）返回
       ``None``，**不回退**到 ``preferred_port``，也不删锁——避免把「锁坏了」
       误判成「没有实例」而双开。
    2. 没有锁（或锁损坏到读不出）时，直接探 ``preferred_port``；上面有我们
       的 ``/api/ping`` 就说明锁丢了但实例还在，返回它。
    """
    lock = _read_lock(runtime_dir)
    if lock is not None:
        payload = _ping(lock["port"])
        if _is_ours(payload, expected_pid=lock["pid"]):
            return lock["port"]
        return None

    if not _valid_port(preferred_port):
        return None
    payload = _ping(preferred_port)
    if _is_ours(payload, expected_pid=None):
        return preferred_port
    return None


# --------------------------------------------------------------------- 内部
def _launch_lock_is_stale(path: Path) -> bool:
    """启动锁的持有者已退出（或锁太老）→ 上次崩溃留下的僵尸锁。"""
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if age > LAUNCH_LOCK_STALE:
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        # 空文件通常是 O_EXCL 之后、写入之前被杀：看年龄决定，宁短勿长。
        return age > 5.0
    pid = data.get("pid") if isinstance(data, dict) else None
    if not _valid_pid(pid):
        return True
    return not _pid_alive(int(pid))


def _replace_with_retry(source: str, target: Path) -> None:
    """Windows 上并发替换/杀毒扫描可能短暂 PermissionError，重试几次。"""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_RETRY_DELAY)


def _read_lock(runtime_dir: Path) -> dict[str, Any] | None:
    try:
        text = lock_path(runtime_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    port = data.get("port")
    if not _valid_pid(pid) or not _valid_port(port):
        return None
    started_at = data.get("started_at", 0.0)
    if isinstance(started_at, bool) or not isinstance(started_at, (int, float)):
        started_at = 0.0
    return {"pid": pid, "port": port, "started_at": float(started_at)}


def _ping(port: int) -> dict[str, Any] | None:
    """``GET /api/ping``；任何失败都折算成 ``None``。"""
    url = f"http://127.0.0.1:{int(port)}{PING_PATH}"
    try:
        with _OPENER.open(url, timeout=PING_TIMEOUT) as response:
            if response.status != 200:
                return None
            raw = response.read(_MAX_PING_BYTES)
    except Exception:  # noqa: BLE001 - 连接失败/超时/非法 URL 都视为没有实例
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_ours(payload: dict[str, Any] | None, *, expected_pid: int | None) -> bool:
    if not payload:
        return False
    # 兼容统一响应 {ok, data: {...}} 与扁平响应 {app, pid, port}。
    app = payload.get("app")
    pid = payload.get("pid")
    data = payload.get("data")
    if isinstance(data, dict):
        if app is None:
            app = data.get("app")
        if pid is None:
            pid = data.get("pid")
    if app != APP_NAME or not _valid_pid(pid):
        return False
    return expected_pid is None or pid == expected_pid


def _valid_pid(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _pid_alive(pid: int) -> bool:
    """只查存活，不发信号（Windows 的 ``os.kill`` 会真的杀进程）。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
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


def _valid_port(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 1 <= value <= 65535
    )
