"""双击启动入口：单实例、端口顺延、后台自举与诊断报告。

交付包里的 ``启动工作台.command``（macOS）与 ``启动工作台.bat``
（Windows）最终都执行这里；手工排障时也可以直接跑::

    python start.py
    python start.py --no-browser
    python start.py --port 8790
    python start.py --diagnose

设计要点：

* **单实例**：先读 ``<runtime>/workbench.lock`` 并 ``/api/ping`` 复验；
  命中就只打开已有页面，绝不起第二份。
* **锁的生命周期**：只在真正要起服务时写锁，``finally`` 里清理；
  ``--diagnose`` 不写锁，也不启动任何进程。
* **自举不挡门**：``ensure_all_async()`` 在后台线程里装环境，HTTP
  服务先起来，页面能立刻显示进度。
* 只用标准库；所有输出显式 UTF-8，Windows 下尽量把控制台也切到 UTF-8。
"""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from workbench import server
from workbench.bootstrap import Bootstrapper
from workbench.config import default_runtime_dir, load_config
from workbench.diagnostics import build_report
from workbench.instance import (
    acquire_launch_lock,
    clear_lock,
    find_running,
    release_launch_lock,
    write_lock,
)
from workbench.manager import ToolManager
from workbench.ports import pick_free_port

APP_NAME = "固收工作台"
DIAGNOSE_FILENAME = "诊断报告.txt"
START_LOG_FILENAME = "start.log"
PORT_TRIES = 20
LAUNCH_RELEASE_TIMEOUT = 30.0
START_LOG_MAX_BYTES = 5 * 1024 * 1024
START_LOG_KEEP_BYTES = 1024 * 1024
SHORTCUT_ENV = "WB_NO_DESKTOP_SHORTCUT"
SHORTCUT_MARKER = "# 由固收工作台自动生成"


def main(argv: list[str] | None = None) -> int:
    """入口；永远返回退出码，不向调用方抛异常。"""
    _configure_stdio()
    try:
        args = _parse_args(argv)
    except SystemExit as exc:  # argparse 的 --help / 参数错误
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1

    if args.diagnose:
        return _diagnose(args)
    return _launch(args)


# --------------------------------------------------------------------- 参数
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="start.py", description="固收工作台启动器"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="只起服务，不自动打开浏览器"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="首选端口（被占用时自动顺延）"
    )
    parser.add_argument(
        "--diagnose", action="store_true", help="只生成诊断报告，不启动服务"
    )
    parser.add_argument(
        "--diagnose-out",
        default=None,
        help=argparse.SUPPRESS,  # 测试/排障用：把报告写到指定路径
    )
    args = parser.parse_args(argv)
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error(f"--port 必须在 1-65535 之间：{args.port}")
    return args


# --------------------------------------------------------------------- 启动
def _launch(args: argparse.Namespace) -> int:
    base = _base_dir()
    runtime: Path | None = None
    try:
        config = load_config(base)
        runtime = Path(config.runtime_dir)
        preferred = args.port if args.port is not None else config.workbench_port

        # 并发双击时只有一个启动器能进入「检查 → 占端口 → 写锁」临界区。
        launch_lock = acquire_launch_lock(runtime)
        if launch_lock is None:
            raise RuntimeError(
                "另一个启动器正在启动，等待 30 秒仍未完成，请稍后重试"
            )
        try:
            # 拿到启动锁后再看一眼：等锁期间别人可能已经把服务起好了。
            running = find_running(runtime, preferred)
            if running is not None:
                _announce_running(running, open_browser=not args.no_browser)
                ensure_desktop_shortcut(base)
                return 0

            port = pick_free_port(preferred, tries=PORT_TRIES)
            if port is None:
                raise RuntimeError(
                    f"端口 {preferred}-{_port_range_end(preferred)} 范围内"
                    "没有可用端口，请关闭占用端口的程序后重试"
                )

            bootstrapper = Bootstrapper(config)
            manager = ToolManager(config, bootstrapper.venv_python)
            try:
                manager.adopt_orphans()
            except Exception:  # noqa: BLE001 - 接管失败不阻止工作台启动
                print("提示：上次残留进程识别失败，工作台仍会继续启动。", flush=True)

            _install_cleanup(manager)
            write_lock(runtime, os.getpid(), port)
            # 服务真正可 ping 后再放启动锁，避免等待方误判「没起来」而双开。
            _release_when_serving(runtime, launch_lock, port)

            try:
                bootstrapper.ensure_all_async()
            except Exception:  # noqa: BLE001 - 后台自举失败不挡 HTTP
                print("提示：环境自举线程启动失败，可稍后在页面里重试。", flush=True)

            shortcut = ensure_desktop_shortcut(base)
            if shortcut is not None:
                print(f"已在桌面放置快捷方式：{shortcut}", flush=True)

            print(f"正在启动{APP_NAME}：http://127.0.0.1:{port}/", flush=True)
            code = server.run_workbench(
                config,
                open_browser=not args.no_browser,
                port=port,
                manager=manager,
                bootstrapper=bootstrapper,
            )
            return int(code or 0)
        finally:
            # 先摘 workbench.lock，再放启动锁：等待方拿到锁时不会看到半退出实例。
            clear_lock(runtime, pid=os.getpid())
            release_launch_lock(launch_lock)
    except KeyboardInterrupt:
        print("\n已取消启动。", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - 用户只看人话，堆栈进日志
        _report_failure(runtime or _fallback_runtime(base), exc)
        return 1


def _port_range_end(preferred: int) -> int:
    """实际尝试的最后一个端口（不超过 65535），用于错误文案。"""
    return min(int(preferred) + PORT_TRIES - 1, 65535)


def ensure_desktop_shortcut(
    base_dir: Path, *, home: Path | None = None
) -> Path | None:
    """macOS：在桌面放一个直达启动器的快捷方式（幂等）。

    生成的是一个小 ``.command`` 包装脚本（由本程序创建，不带 quarantine，
    双击即可）；已经存在且内容一致时不重写。Windows 上直接返回 ``None``。

    设置环境变量 ``WB_NO_DESKTOP_SHORTCUT=1`` 可关闭该行为。
    """
    if sys.platform != "darwin":
        return None
    if os.environ.get(SHORTCUT_ENV, "").strip() not in ("", "0", "false", "False"):
        return None

    desktop = (Path(home) if home is not None else Path.home()) / "Desktop"
    target = desktop / f"{APP_NAME}.command"
    bundle = Path(base_dir).resolve()
    launcher = bundle / "启动工作台.command"
    content = (
        "#!/bin/bash\n"
        f"{SHORTCUT_MARKER}，删除本文件不会影响工作台。\n"
        f'cd "{bundle}" || {{ echo "找不到工作台目录：{bundle}"; read -n 1 -r -s -p "按任意键关闭…"; exit 1; }}\n'
        'exec bash "启动工作台.command" "$@"\n'
    )
    try:
        if target.is_file():
            try:
                if target.read_text(encoding="utf-8") == content:
                    return target
            except (OSError, UnicodeDecodeError):
                pass
            try:
                previous = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                previous = ""
            if SHORTCUT_MARKER not in previous:
                # 用户自己放的同名文件：不覆盖，只提示。
                print(f"提示：桌面上已有同名文件，未覆盖：{target}", flush=True)
                return None
        if not launcher.is_file():
            return None
        desktop.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        target.chmod(0o755)
        return target
    except OSError as exc:
        print(f"提示：桌面快捷方式创建失败（{exc}），不影响使用。", flush=True)
        return None



def _announce_running(port: int, *, open_browser: bool) -> None:
    url = f"http://127.0.0.1:{int(port)}"
    print(f"{APP_NAME}已在运行：{url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url + "/")
        except Exception:  # noqa: BLE001 - 没有浏览器也必须正常退出
            pass


# --------------------------------------------------------------------- 清理
def _make_signal_handler(manager):
    """返回幂等的信号处理器：只 shutdown 一次，然后 SystemExit 让 finally 清锁。"""
    fired = threading.Event()

    def handler(signum, frame):  # noqa: ARG001 - signal 接口约定
        if not fired.is_set():
            fired.set()
            try:
                manager.shutdown()
            except Exception:  # noqa: BLE001 - 退出路径不能再抛回去
                pass
        raise SystemExit(0)

    return handler


def _install_cleanup(manager) -> None:
    """正常退出靠 atexit，kill/关终端靠 SIGTERM/SIGHUP/SIGBREAK。"""
    atexit.register(manager.shutdown)
    handler = _make_signal_handler(manager)
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, handler)
        except (OSError, RuntimeError, ValueError):
            # 非主线程/平台不支持时只保留 atexit 兜底。
            pass


def _release_when_serving(runtime: Path, lock: Path, port: int) -> None:
    """后台等 /api/ping 成功后再释放启动锁；失败时由调用方 finally 释放。"""

    def wait() -> None:
        deadline = time.monotonic() + LAUNCH_RELEASE_TIMEOUT
        while time.monotonic() < deadline:
            try:
                if find_running(runtime, port) == port:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.05)
        release_launch_lock(lock)

    thread = threading.Thread(
        target=wait, name="workbench-launch-release", daemon=True
    )
    thread.start()


# --------------------------------------------------------------------- 诊断
def _diagnose(args: argparse.Namespace) -> int:
    base = _base_dir()
    out = Path(args.diagnose_out) if args.diagnose_out else base / DIAGNOSE_FILENAME
    try:
        config = load_config(base)
        # 只构造对象：不写锁、不启动服务、不装环境、不接管进程。
        bootstrapper = Bootstrapper(config)
        manager = ToolManager(config, bootstrapper.venv_python)
        text = build_report(config, manager, bootstrapper)
    except Exception as exc:  # noqa: BLE001 - 诊断失败也要留下可读报告
        text = _failure_report(exc)
        if _write_text(out, text):
            print(f"诊断生成失败：{_short_error(exc)}", file=sys.stderr, flush=True)
            print(f"已写入简化报告：{out}", file=sys.stderr, flush=True)
        return 1

    if not _write_text(out, text):
        return 1
    print(f"诊断报告已生成：{out}", flush=True)
    return 0


def _failure_report(exc: BaseException) -> str:
    return "\n".join(
        [
            f"{APP_NAME} 诊断报告",
            "=" * 48,
            "",
            f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S %z')}",
            "",
            "[诊断生成失败]",
            f"{type(exc).__name__}: {exc}",
            "",
            "[调试信息]",
            traceback.format_exc().rstrip(),
            "",
        ]
    )


def _write_text(path: Path, text: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    except OSError as exc:
        print(f"无法写入文件：{path}（{exc}）", file=sys.stderr, flush=True)
        return False


# --------------------------------------------------------------------- 错误
def _report_failure(runtime: Path, exc: BaseException) -> None:
    message = _short_error(exc)
    print(f"启动失败：{message}", file=sys.stderr, flush=True)
    log = _write_failure_log(runtime, exc)
    if log is not None:
        print(f"详细信息已写入：{log}", file=sys.stderr, flush=True)


def _write_failure_log(runtime: Path, exc: BaseException) -> Path | None:
    path = Path(runtime) / "logs" / START_LOG_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _shrink_start_log(path)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S %z')} ===\n"
            )
            handle.write(
                "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
            )
        return path
    except OSError:
        return None


def _shrink_start_log(path: Path) -> None:
    """start.log 超过 5MB 时只保留最后约 1MB，避免无限增长。"""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= START_LOG_MAX_BYTES:
        return
    with path.open("rb") as handle:
        handle.seek(max(0, size - START_LOG_KEEP_BYTES))
        data = handle.read()
    # 截断点可能落在行中间，丢掉第一个不完整行。
    newline = data.find(b"\n")
    if newline >= 0:
        data = data[newline + 1 :]
    path.write_bytes(data)


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    return text.splitlines()[-1].strip()


def _fallback_runtime(base: Path) -> Path:
    try:
        return default_runtime_dir()
    except Exception:  # noqa: BLE001
        return Path(base) / "runtime"


# --------------------------------------------------------------------- 杂项
def _base_dir() -> Path:
    """交付包根目录；单独成函数便于测试替换。"""
    return Path(__file__).resolve().parent


def _configure_stdio() -> None:
    """Windows 控制台尽量用 UTF-8，避免中文报错变问号。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
