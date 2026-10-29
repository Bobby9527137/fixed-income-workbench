"""离线自举：解压内置 Python、创建 venv、从本地 wheelhouse 安装依赖。

运行期不联网，也不要求用户预装 Python：

* 内置 Python（macOS）解压到 ``<runtime>/python/<archive 主名>/``，解压失败
  才回退系统 Python，并把降级原因写进 :meth:`Bootstrapper.status`。
* 每套环境建在 ``<runtime>/envs/<env_id>/``，依赖只用
  ``pip --no-index --find-links`` 从随包的 wheelhouse 安装。
* 环境是否可用由三件事共同决定：``.stamp`` 与当前材料一致、venv 解释器存在、
  ``probe`` 里的模块都能导入。任何一项不满足都视为损坏并自动重建。

安装过程串行化到 per-env 锁，状态更新只占一把很短的状态锁，因此
:meth:`Bootstrapper.status` 在安装期间也能随时读取。
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .config import Config, EnvSpec

STAMP_FILENAME = ".stamp"
PYTHON_DIRNAME = "python"
ENVS_DIRNAME = "envs"
LOGS_DIRNAME = "logs"
TAIL_LINES = 3

STATE_MISSING = "missing"
STATE_EXTRACTING = "extracting"
STATE_INSTALLING = "installing"
STATE_READY = "ready"
STATE_ERROR = "error"

VENV_TIMEOUT = 300.0
PIP_TIMEOUT = 1800.0
PROBE_TIMEOUT = 120.0
VERSION_TIMEOUT = 60.0
PYTHON_VALIDATE_TIMEOUT = 60.0
PYTHON_RETRY_COOLDOWN = 60.0
EXTRACT_LOCK_TIMEOUT = 180.0
EXTRACT_LOCK_STALE = 600.0

TAIL_BYTES = 64 * 1024
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP_BYTES = 1024 * 1024

# _check_ready 的三种结论：就绪 / 可重建 / 材料读不到（不能删环境）。
_VERDICT_READY = "ready"
_VERDICT_STALE = "stale"
_VERDICT_MATERIAL = "material"

_logger = logging.getLogger(__name__)


class BootstrapError(RuntimeError):
    """自举过程中可预期的失败（材料缺失、命令退出码非零、依赖校验失败）。"""


@contextmanager
def _extract_lock(dest: Path, timeout: float = EXTRACT_LOCK_TIMEOUT):
    """跨进程独占锁：``dest`` 同级的 ``.lock`` 文件，``O_EXCL`` 创建。

    锁文件 mtime 超过 :data:`EXTRACT_LOCK_STALE` 视为僵尸锁可回收。
    超时抛 :class:`TimeoutError`；退出时只删除自己创建的锁。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lock_path = dest.with_name(dest.name + ".lock")
    deadline = time.monotonic() + max(timeout, 0.0)
    token = f"{os.getpid()}:{time.time_ns()}\n"
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            except OSError:
                age = 0.0
            if age > EXTRACT_LOCK_STALE:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"等待内置 Python 解压锁超时（{int(timeout)} 秒）：{lock_path}"
                )
            time.sleep(0.05)
    try:
        try:
            os.write(fd, token.encode("ascii"))
        except OSError:
            pass
        yield lock_path
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            if lock_path.read_text(encoding="ascii") == token:
                lock_path.unlink()
        except OSError:
            pass


def extract_python_archive(archive: Path, dest: Path) -> Path:
    """把 ``archive`` 解压到 ``dest``，剥掉发行包顶层的 ``python/`` 目录。

    先解到 ``dest`` 旁边的唯一临时目录，成功后再 :func:`os.replace` 成
    ``dest``；任何异常都会删掉临时目录后原样抛出。整个过程由
    :func:`_extract_lock` 做跨进程互斥，因此并发调用不会互相踩掉 staging。
    """
    archive = Path(archive)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _extract_lock(dest):
        staging = Path(
            tempfile.mkdtemp(prefix=dest.name + ".", dir=str(dest.parent))
        )
        try:
            with tarfile.open(archive, "r:*") as bundle:
                bundle.extractall(staging, filter=_python_member_filter)
            # 上次成功解压的旧目录（例如内容损坏后重解）先让位；Windows 上
            # os.replace 不能覆盖非空目录。
            if dest.exists() or dest.is_symlink():
                _remove_path_quietly(dest)
            os.replace(staging, dest)
        except BaseException:
            _remove_path_quietly(staging)
            raise
    return dest


def _python_member_filter(
    member: tarfile.TarInfo, dest_path: str
) -> tarfile.TarInfo | None:
    """在 ``tarfile`` 的 data filter 之上剥掉顶层 ``python/``。"""
    member = tarfile.data_filter(member, dest_path)
    if member is None:
        return None
    parts = _split_member_name(member.name)
    if parts and parts[0] == PYTHON_DIRNAME:
        parts = parts[1:]
    if not parts:
        # 顶层 ``python/`` 目录本身，跳过即可；文件成员会自动建出父目录。
        return None
    member.name = "/".join(parts)
    if member.islnk():
        link_parts = _split_member_name(member.linkname)
        if link_parts and link_parts[0] == PYTHON_DIRNAME:
            member.linkname = "/".join(link_parts[1:])
    return member


def _split_member_name(name: str | None) -> list[str]:
    if not name:
        return []
    return [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]


def _remove_path(path: Path) -> None:
    """删除文件或目录；不存在时静默。删除失败照常抛出。"""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _remove_path_quietly(path: Path) -> None:
    try:
        _remove_path(path)
    except OSError:
        pass


def _fingerprint(path: Path) -> tuple[int, int] | None:
    """解释器文件的 (mtime_ns, size)：用来发现“被替换/被截断但仍存在”。"""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


class Bootstrapper:
    """一套工作台实例对应一个 Bootstrapper；内部状态线程安全。"""

    def __init__(
        self,
        config: Config,
        *,
        system_python: Path | None = None,
        python_validator: Callable[[Path], tuple[bool, str]] | None = None,
    ) -> None:
        self._config = config
        self._system_python = Path(system_python) if system_python is not None else None
        self._runtime = Path(config.runtime_dir)
        self._state_lock = threading.Lock()
        self._locks_guard = threading.Lock()
        self._env_locks: dict[str, threading.Lock] = {}
        self._python_lock = threading.Lock()
        self._version_lock = threading.Lock()
        self._python_exe: Path | None = None
        self._python_fingerprint: tuple[int, int] | None = None
        self._python_failed_at: float | None = None
        self._python_last_error = ""
        self._validator = python_validator or self._validate_python
        self._versions: dict[str, str] = {}
        self._states: dict[str, dict[str, Any]] = {
            "python": self._initial_python_state()
        }
        for env_id in config.environments:
            self._states[env_id] = self._entry(env_id, STATE_MISSING, "未安装", 0)

    # ------------------------------------------------------------------ 查询
    def python_exe(self) -> Path:
        """返回建 venv 用的基础解释器。

        没配内置包时直接用 ``system_python``（缺省为当前解释器）。配了内置包
        则按需解压并**真正跑一次** ``-c "import sys; print(sys.version)"`` 校验；
        已有 dest 校验不过会删掉重解，解压后再校验，仍不过才回退系统 Python。
        失败后 60 秒冷却，冷却结束自动重试；``rebuild()`` 会立即清掉冷却。
        """
        archive = self._config.python_archive
        if archive is None:
            return self._fallback_python()
        archive = self._resolve_archive(Path(archive))

        with self._python_lock:
            if (
                self._python_exe is not None
                and self._python_exe.is_file()
                and _fingerprint(self._python_exe) == self._python_fingerprint
            ):
                return self._python_exe
            # 缓存失效（被替换/被删/指纹变了）：先当做没有，下面按需校验或重解压。
            self._python_exe = None
            self._python_fingerprint = None

            now = time.monotonic()
            if (
                self._python_failed_at is not None
                and now - self._python_failed_at < PYTHON_RETRY_COOLDOWN
            ):
                return self._fallback_python()
            self._python_failed_at = None
            self._python_last_error = ""

            dest = self._python_dest(archive)
            exe = dest / self._python_install_exe()
            if exe.is_file():
                self._set("python", STATE_EXTRACTING, f"正在校验 {exe.name}", 30)
                ok, message = self._validator(exe)
                if ok:
                    return self._python_ready(exe)
                reason = f"已有内置 Python 校验失败：{message}"
                _logger.warning("%s，删除后重新解压", reason)
                self._append_python_log(reason)
                _remove_path_quietly(dest)

            last_error = "内置 Python 解压失败"
            for attempt in (1, 2):
                self._set(
                    "python",
                    STATE_EXTRACTING,
                    f"正在解压 {archive.name}（第 {attempt} 次）",
                    10 * attempt,
                )
                try:
                    extract_python_archive(archive, dest)
                except Exception as exc:  # noqa: BLE001 - 解压失败要回退
                    last_error = f"解压失败：{type(exc).__name__}: {exc}"
                    _logger.warning(
                        "内置 Python 解压失败（第 %s 次）：%s", attempt, last_error
                    )
                    _remove_path_quietly(dest)
                    continue
                if not exe.is_file():
                    last_error = f"解压完成但缺少解释器：{exe}"
                    _logger.warning("%s", last_error)
                    _remove_path_quietly(dest)
                    continue
                self._set("python", STATE_EXTRACTING, "正在校验内置 Python", 60)
                ok, message = self._validator(exe)
                if ok:
                    return self._python_ready(exe)
                last_error = f"内置 Python 校验失败：{message}"
                _logger.warning("%s", last_error)
                self._append_python_log(last_error)
                _remove_path_quietly(dest)

            return self._fallback_after_failure(last_error)

    def venv_python(self, env_id: str) -> Path:
        """``<runtime>/envs/<env_id>`` 里的解释器路径（不保证存在）。"""
        self._spec(env_id)
        return self._env_dir(env_id) / self._venv_rel_python()

    def status(self) -> dict[str, dict]:
        """所有环境 + ``python`` 的只读快照；安装进行中也能立即返回。"""
        with self._state_lock:
            return {key: dict(value) for key, value in self._states.items()}

    # -------------------------------------------------------------- 安装流程
    def ensure_env(self, env_id: str) -> dict:
        """确保环境可用；同一环境并发调用只会安装一次。"""
        spec = self._spec(env_id)
        with self._env_lock(env_id):
            return self._ensure_locked(spec)

    def rebuild(self, env_id: str) -> dict:
        """删掉环境目录后重新安装（仍只使用本地 wheelhouse）。

        同时清空内置 Python 的失败冷却并立即重试解压：用户点“重建”就是想要
        一次干净的重来。材料缺失时保留现有环境，只报错。
        """
        spec = self._spec(env_id)
        with self._env_lock(env_id):
            self._clear_python_failure()
            if self._config.python_archive is not None:
                self.python_exe()
            problem = self._material_problem(spec)
            if problem:
                self._append_log(env_id, problem)
                self._set(
                    env_id,
                    STATE_ERROR,
                    self._log_tail(env_id) or problem,
                    0,
                )
                return self._snapshot(env_id)
            try:
                _remove_path(self._env_dir(env_id))
            except OSError as exc:
                _logger.warning("环境 %s 删除失败：%s", env_id, exc)
                self._append_log(env_id, f"无法删除旧环境：{exc}")
                detail = self._log_tail(env_id) or f"无法删除旧环境：{exc}"
                self._set(env_id, STATE_ERROR, detail, 0)
                return self._snapshot(env_id)
            self._set(env_id, STATE_MISSING, "已删除旧环境，准备重建", 0)
            return self._ensure_locked(spec)

    def ensure_all_async(self) -> threading.Thread:
        """后台依次安装所有环境；线程内的异常折算成对应环境的状态。"""
        thread = threading.Thread(
            target=self._ensure_all, name="workbench-bootstrap", daemon=True
        )
        thread.start()
        return thread

    # ---------------------------------------------------------------- 内部实现
    def _ensure_all(self) -> None:
        for env_id in list(self._config.environments):
            try:
                self.ensure_env(env_id)
            except Exception as exc:  # noqa: BLE001 - 线程里的失败不能外泄
                _logger.exception("环境 %s 自举失败", env_id)
                self._set(env_id, STATE_ERROR, f"自举失败：{exc}", 0)

    def _ensure_locked(self, spec: EnvSpec) -> dict:
        env_id = spec.id
        problem = self._material_problem(spec)
        if problem:
            # 材料读不到时绝不删已有环境：那是用户唯一的可用副本。
            self._append_log(env_id, problem)
            self._set(env_id, STATE_ERROR, self._log_tail(env_id) or problem, 0)
            return self._snapshot(env_id)

        verdict, reason = self._check_ready(spec)
        if verdict == _VERDICT_READY:
            self._set(env_id, STATE_READY, "已就绪", 100)
            return self._snapshot(env_id)
        if verdict == _VERDICT_MATERIAL:
            self._append_log(env_id, reason)
            self._set(env_id, STATE_ERROR, self._log_tail(env_id) or reason, 0)
            return self._snapshot(env_id)

        log_path = self._log_path(env_id)
        try:
            self._prepare_log_dir()
            env_dir = self._env_dir(env_id)
            if env_dir.exists() or env_dir.is_symlink():
                self._append_log(env_id, f"环境不可用（{reason}），删除后重建")
            # 删除前再确认一次材料，避免删完才发现 requirements 刚被移走。
            problem = self._material_problem(spec)
            if problem:
                self._append_log(env_id, problem)
                self._set(env_id, STATE_ERROR, self._log_tail(env_id) or problem, 0)
                return self._snapshot(env_id)
            _remove_path(env_dir)
            self._set(env_id, STATE_INSTALLING, "准备安装", 5)
            with self._open_log(log_path) as log:
                self._install_steps(spec, log)
        except Exception as exc:  # noqa: BLE001 - 失败要变成状态而不是异常
            _logger.warning("环境 %s 安装失败：%s", env_id, exc)
            self._append_log(env_id, f"失败：{type(exc).__name__}: {exc}")
            detail = self._log_tail(env_id) or f"环境安装失败：{exc}"
            self._set(env_id, STATE_ERROR, detail, 0)
            return self._snapshot(env_id)

        self._set(env_id, STATE_READY, "已就绪", 100)
        return self._snapshot(env_id)

    def _check_ready(self, spec: EnvSpec) -> tuple[str, str]:
        """stamp、解释器、probe 三者都通过才算就绪。

        返回 ``(verdict, reason)``：材料读不到时返回 ``material``，调用方只报错
        而不删环境；stamp 不匹配或 probe 失败才返回 ``stale``（可重建）。
        """
        problem = self._material_problem(spec)
        if problem:
            return _VERDICT_MATERIAL, problem
        if not self.venv_python(spec.id).is_file():
            return _VERDICT_STALE, "环境不存在"
        stamp_path = self._env_dir(spec.id) / STAMP_FILENAME
        if not stamp_path.is_file():
            return _VERDICT_STALE, "缺少 stamp"
        try:
            saved = stamp_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return _VERDICT_MATERIAL, f"无法读取 stamp：{exc}"
        try:
            expected = self._stamp_digest(spec)
        except OSError as exc:
            return _VERDICT_MATERIAL, f"无法读取安装材料：{exc}"
        if saved != expected:
            return _VERDICT_STALE, "依赖、平台或 Python 版本已变更"
        ok, message = self._run_probe(spec)
        if not ok:
            return _VERDICT_STALE, message or "依赖校验失败"
        return _VERDICT_READY, ""

    def _material_problem(self, spec: EnvSpec) -> str | None:
        if not spec.requirements.is_file():
            return f"requirements 文件不存在：{spec.requirements}"
        if not spec.wheelhouse.is_dir():
            return f"wheelhouse 目录不存在：{spec.wheelhouse}"
        return None

    def _install_steps(self, spec: EnvSpec, log: Any) -> None:
        env_id = spec.id
        log.write(
            f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} 安装环境 {env_id} ===\n"
        )
        if not spec.requirements.is_file():
            raise BootstrapError(f"requirements 文件不存在：{spec.requirements}")
        if not spec.wheelhouse.is_dir():
            raise BootstrapError(f"wheelhouse 目录不存在：{spec.wheelhouse}")

        base_python = self.python_exe()
        env_dir = self._env_dir(env_id)
        env_dir.parent.mkdir(parents=True, exist_ok=True)

        log.write(f"基础解释器：{base_python}\n")
        self._set(env_id, STATE_INSTALLING, "创建虚拟环境", 20)
        self._run_logged(
            log,
            [str(base_python), "-m", "venv", str(env_dir)],
            VENV_TIMEOUT,
        )
        # venv 命令成功不代表解释器可用：Windows 上 Store 版 Python 会把
        # %LOCALAPPDATA% 重定向进包私有目录，venv\Scripts\python.exe 存在但
        # 启动时报 “No pyvenv.cfg file”（退出码 106）。这里先真跑一次。
        try:
            self._run_logged(
                log,
                [str(self.venv_python(env_id)), "-c", "import sys"],
                60.0,
            )
        except BootstrapError as exc:
            raise BootstrapError(
                f"{exc}\n虚拟环境创建失败：解释器无法启动"
                f"（当前 runtime：{self._runtime}）。"
                "如果 Windows 上的 Python 来自 Microsoft Store（路径含 WindowsApps），"
                "请设置 WB_RUNTIME_DIR=%USERPROFILE%\\固收工作台\\runtime 后重试。"
            ) from exc

        self._set(env_id, STATE_INSTALLING, "安装本地依赖", 50)
        self._run_logged(
            log,
            [
                str(self.venv_python(env_id)),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(spec.wheelhouse),
                "--disable-pip-version-check",
                "--no-input",
                "-r",
                str(spec.requirements),
            ],
            PIP_TIMEOUT,
        )

        self._set(env_id, STATE_INSTALLING, "校验依赖", 90)
        ok, message = self._run_probe(spec, log)
        if not ok:
            raise BootstrapError(message)

        self._write_stamp(env_id, self._stamp_digest(spec))

    def _run_logged(
        self, log: Any, cmd: list[str], timeout: float
    ) -> subprocess.CompletedProcess:
        """跑一条会写进日志的命令；非零退出折算成 :class:`BootstrapError`。"""
        log.write(f"$ {shlex.join(cmd)}\n")
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self._config.base_dir),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=self._child_env(),
                timeout=timeout,
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            log.write(f"命令超时（{int(timeout)} 秒）\n")
            log.flush()
            raise BootstrapError(f"命令超时（{int(timeout)} 秒）：{cmd[0]}") from exc
        except OSError as exc:
            log.write(f"命令无法启动：{exc}\n")
            log.flush()
            raise BootstrapError(f"命令无法启动：{exc}") from exc
        log.flush()
        if proc.returncode != 0:
            raise BootstrapError(f"命令退出码 {proc.returncode}：{cmd[0]}")
        return proc

    def _run_probe(
        self, spec: EnvSpec, log: Any | None = None
    ) -> tuple[bool, str]:
        """跑 ``python -c "import a, b"``；输出同时写进日志。"""
        if not spec.probe:
            return True, ""
        cmd = [
            str(self.venv_python(spec.id)),
            "-c",
            "import " + ", ".join(spec.probe),
        ]
        if log is not None:
            log.write(f"$ {shlex.join(cmd)}\n")
            log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self._config.base_dir),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=self._child_env(),
                timeout=PROBE_TIMEOUT,
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired:
            message = f"依赖校验超时（{int(PROBE_TIMEOUT)} 秒）"
            if log is not None:
                log.write(message + "\n")
                log.flush()
            return False, message
        except OSError as exc:
            message = f"无法启动环境 Python：{exc}"
            if log is not None:
                log.write(message + "\n")
                log.flush()
            return False, message

        output = (proc.stdout or "") + (proc.stderr or "")
        if log is not None and output:
            log.write(output)
            if not output.endswith("\n"):
                log.write("\n")
            log.flush()
        if proc.returncode != 0:
            message = f"依赖校验失败（退出码 {proc.returncode}）：{output.strip()}"
            return False, message
        return True, output

    def _validate_python(self, exe: Path) -> tuple[bool, str]:
        """真正跑一次 ``-c "import sys; print(sys.version)"`` 校验解释器。"""
        try:
            proc = subprocess.run(
                [str(exe), "-c", "import sys; print(sys.version)"],
                cwd=str(self._config.base_dir),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=self._child_env(),
                timeout=PYTHON_VALIDATE_TIMEOUT,
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired:
            return False, f"校验超时（{int(PYTHON_VALIDATE_TIMEOUT)} 秒）"
        except OSError as exc:
            return False, f"无法启动解释器：{exc}"
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return False, output.strip() or f"退出码 {proc.returncode}"
        if not (proc.stdout or "").strip():
            return False, "没有版本输出"
        return True, proc.stdout.strip()

    def _child_env(self) -> dict[str, str]:
        """子进程环境：固定 UTF-8，抹掉 pip 网络变量与 Python 路径污染。"""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["PIP_NO_INPUT"] = "1"
        env["PIP_NO_INDEX"] = "1"
        for key in (
            "PIP_INDEX_URL",
            "PIP_EXTRA_INDEX_URL",
            "PIP_FIND_LINKS",
            "PYTHONHOME",
            "PYTHONPATH",
            "VIRTUAL_ENV",
        ):
            env.pop(key, None)
        return env

    def _stamp_digest(self, spec: EnvSpec) -> str:
        wheel_names = sorted(
            path.name for path in spec.wheelhouse.iterdir() if path.is_file()
        )
        material = b"\0".join(
            (
                spec.requirements.read_bytes(),
                _platform_key().encode("utf-8"),
                self._python_version(self.python_exe()).encode("utf-8"),
                "\n".join(wheel_names).encode("utf-8"),
                "\n".join(spec.probe).encode("utf-8"),
            )
        )
        return hashlib.sha256(material).hexdigest()

    def _python_version(self, exe: Path) -> str:
        key = str(exe)
        with self._version_lock:
            cached = self._versions.get(key)
        if cached is not None:
            return cached
        version = "unknown"
        try:
            proc = subprocess.run(
                [
                    str(exe),
                    "-c",
                    "import sys; print('%d.%d.%d' % sys.version_info[:3])",
                ],
                cwd=str(self._config.base_dir),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=self._child_env(),
                timeout=VERSION_TIMEOUT,
                creationflags=_creation_flags(),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                version = proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            version = "unknown"
        with self._version_lock:
            self._versions[key] = version
        return version

    def _write_stamp(self, env_id: str, digest: str) -> None:
        path = self._env_dir(env_id) / STAMP_FILENAME
        staging = path.with_name(path.name + ".tmp")
        staging.write_text(digest + "\n", encoding="utf-8")
        os.replace(staging, path)

    # ------------------------------------------------------------------ 路径
    def _spec(self, env_id: str) -> EnvSpec:
        try:
            return self._config.environments[env_id]
        except KeyError:
            raise KeyError(f"未定义的环境：{env_id}") from None

    def _env_dir(self, env_id: str) -> Path:
        return self._runtime / ENVS_DIRNAME / env_id

    def _python_dest(self, archive: Path) -> Path:
        return self._runtime / PYTHON_DIRNAME / _archive_stem(Path(archive))

    def _resolve_archive(self, archive: Path) -> Path:
        """配置里的归档名对不上时，按 ``*install_only*.tar.*`` 在目录里找。

        交付包里的归档名带 ``+日期``，容易与手写的 tools.json 不同步；
        只要文件名是唯一的，就按实际文件走。
        """
        if archive.is_file():
            return archive
        folder = archive.parent
        if not folder.is_dir():
            return archive
        patterns = ("*install_only*.tar.gz", "*install_only*.tar.xz", "*install_only*.tar.bz2")
        for pattern in patterns:
            matches = sorted(folder.glob(pattern))
            if len(matches) == 1:
                _logger.warning(
                    "配置的内置 Python 归档不存在（%s），改用目录里的 %s",
                    archive.name,
                    matches[0].name,
                )
                return matches[0]
        return archive


    @staticmethod
    def _venv_rel_python() -> Path:
        if sys.platform == "win32":
            return Path("Scripts") / "python.exe"
        return Path("bin") / "python"

    @staticmethod
    def _python_install_exe() -> Path:
        if sys.platform == "win32":
            return Path("python.exe")
        return Path("bin") / "python3"

    def _fallback_python(self) -> Path:
        return self._system_python or Path(sys.executable)

    def _python_ready(self, exe: Path) -> Path:
        self._python_exe = exe
        self._python_fingerprint = _fingerprint(exe)
        self._python_failed_at = None
        self._python_last_error = ""
        self._set("python", STATE_READY, f"内置 Python：{exe}", 100)
        return exe

    def _clear_python_failure(self) -> None:
        with self._python_lock:
            self._python_failed_at = None
            self._python_last_error = ""
            # 重建必须让下一次 python_exe() 重新校验/解压，否则坏的 exe 会被缓存继续用。
            self._python_exe = None
            self._python_fingerprint = None

    def _fallback_after_failure(self, reason: str) -> Path:
        self._python_failed_at = time.monotonic()
        self._python_last_error = reason
        detail = f"内置 Python 解压失败，可点重建重试（已回退系统 Python）：{reason}"
        self._append_python_log(detail)
        self._set("python", STATE_ERROR, detail, 0)
        return self._fallback_python()

    def _initial_python_state(self) -> dict[str, Any]:
        archive = self._config.python_archive
        if archive is None:
            return self._entry(
                "python", STATE_READY, f"使用系统 Python：{self._fallback_python()}", 100
            )
        # 仅凭文件存在不能算 ready：第一次真正用到时必须先跑校验。
        return self._entry("python", STATE_MISSING, "内置 Python 待校验", 0)

    # ------------------------------------------------------------------ 状态
    def _entry(
        self, entry_id: str, state: str, detail: str, progress: int
    ) -> dict[str, Any]:
        return {
            "id": entry_id,
            "state": state,
            "detail": detail,
            "progress": int(progress),
        }

    def _set(self, entry_id: str, state: str, detail: str, progress: int) -> None:
        with self._state_lock:
            self._states[entry_id] = self._entry(entry_id, state, detail, progress)

    def _snapshot(self, env_id: str) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._states[env_id])

    def _env_lock(self, env_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._env_locks.get(env_id)
            if lock is None:
                lock = threading.Lock()
                self._env_locks[env_id] = lock
            return lock

    # -------------------------------------------------------------------- 日志
    def _prepare_log_dir(self) -> None:
        (self._runtime / LOGS_DIRNAME).mkdir(parents=True, exist_ok=True)

    def _log_path(self, env_id: str) -> Path:
        safe = env_id.replace("/", "_").replace("\\", "_")
        return self._runtime / LOGS_DIRNAME / f"bootstrap-{safe}.log"

    def _open_log(self, path: Path):
        """以追加方式打开日志；超过 :data:`LOG_MAX_BYTES` 先截断到尾部。"""
        self._prepare_log_dir()
        self._shrink_log(path)
        return path.open("a", encoding="utf-8")

    def _shrink_log(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size <= LOG_MAX_BYTES:
            return
        try:
            with path.open("rb") as log:
                log.seek(max(0, size - LOG_KEEP_BYTES))
                data = log.read()
            newline = data.find(b"\n")
            if newline >= 0:
                data = data[newline + 1 :]
            path.write_bytes(data)
        except OSError:
            pass

    def _append_log(self, env_id: str, text: str) -> None:
        try:
            with self._open_log(self._log_path(env_id)) as log:
                log.write(text.rstrip("\n") + "\n")
        except OSError:
            pass

    def _log_tail(self, env_id: str) -> str:
        path = self._log_path(env_id)
        try:
            with path.open("rb") as log:
                log.seek(0, os.SEEK_END)
                size = log.tell()
                log.seek(max(0, size - TAIL_BYTES))
                data = log.read()
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        if size > TAIL_BYTES:
            # 截断点可能落在行中间，丢掉第一个不完整行。
            newline = text.find("\n")
            if newline >= 0:
                text = text[newline + 1 :]
        rows = [row for row in text.splitlines() if row.strip()]
        return "\n".join(rows[-TAIL_LINES:])

    def _append_python_log(self, text: str) -> None:
        try:
            path = self._runtime / LOGS_DIRNAME / "bootstrap-python.log"
            with self._open_log(path) as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text.rstrip()}\n")
        except OSError:
            pass


def _platform_key() -> str:
    """stamp 里的平台标识：OS + CPU 架构，避免不同 ABI 的 wheelhouse 混用。"""
    return f"{sys.platform}-{platform.machine().lower()}"


def _creation_flags() -> int:
    """Windows 下隐藏 venv/pip 的控制台窗口；其他平台为 0。"""
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _archive_stem(archive: Path) -> str:
    name = archive.name
    lowered = name.lower()
    for suffix in (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar"):
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return archive.stem
