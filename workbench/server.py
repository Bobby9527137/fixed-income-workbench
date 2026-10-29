"""本地 HTTP 服务：静态工作台页面 + JSON API。

只监听 ``127.0.0.1``，不鉴权；用 ``Host`` 头校验挡住 DNS rebinding。
所有 API 响应统一 ``{"ok": true, "data": …}`` /
``{"ok": false, "error": "…"}``，并显式写 ``Content-Length``（不发 chunked）。

单实例检查与锁文件不在这里做：那属于 ``start.py``。本模块只负责
「拿到 server 对象」和「跑起来直到退出」。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .diagnostics import build_report
from .ports import probe_http

HOST = "127.0.0.1"
WEB_DIR = Path(__file__).resolve().parent / "web"
LEGACY_HEALTH_URL = "http://127.0.0.1:8501/_stcore/health"
LEGACY_TIMEOUT = 0.3
LOG_DEFAULT_LINES = 200
LOG_MAX_LINES = 2000
SHUTDOWN_DELAY = 0.2
APP_NAME = "固收工作台"
MAX_BODY_BYTES = 1024 * 1024

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}

_logger = logging.getLogger(__name__)


class _HttpError(Exception):
    """可预期的 HTTP 错误：直接转成 JSON 错误响应。"""

    def __init__(
        self,
        status: int,
        message: str,
        *,
        allow: str | None = None,
        close: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.allow = allow
        self.close = close


class WorkbenchHTTPServer(ThreadingHTTPServer):
    """携带 config / manager / bootstrapper 的 ThreadingHTTPServer。"""

    daemon_threads = True
    # Windows 的 SO_REUSEADDR 允许第二个进程绑同一端口，正好破坏单实例；
    # macOS 保留默认行为，方便退出后立刻重启。
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address: tuple[str, int], config: Any, manager: Any,
                 bootstrapper: Any) -> None:
        self.config = config
        self.manager = manager
        self.bootstrapper = bootstrapper
        super().__init__(address, _Handler)


def make_server(
    config: Any,
    manager: Any,
    bootstrapper: Any,
    port: int,
) -> ThreadingHTTPServer:
    """在 ``127.0.0.1:<port>`` 起服务；``port=0`` 时由系统分配。"""
    httpd = WorkbenchHTTPServer((HOST, int(port)), config, manager, bootstrapper)
    # 诊断报告需要“实际绑定端口”（port=0 / 顺延后与配置值可能不同）。
    try:
        config.bound_port = int(httpd.server_address[1])
    except Exception:  # noqa: BLE001 - 挂不上也不影响服务
        _logger.debug("无法记录实际端口", exc_info=True)
    return httpd


def run_workbench(
    config: Any,
    *,
    open_browser: bool = True,
    port: int | None = None,
    manager: Any = None,
    bootstrapper: Any = None,
) -> int:
    """启动工作台并阻塞，直到 ``/api/shutdown`` 或 Ctrl+C；退出时停全部子进程。

    ``manager`` / ``bootstrapper`` 省略时自行构造（便于独立运行）；``start.py``
    会传入已经 ``adopt_orphans()`` / ``ensure_all_async()`` 的实例。
    单实例锁的写入与清理仍由调用方负责。
    """
    if bootstrapper is None:
        from .bootstrap import Bootstrapper

        bootstrapper = Bootstrapper(config)
    if manager is None:
        from .manager import ToolManager

        manager = ToolManager(config, bootstrapper.venv_python)
        try:
            manager.adopt_orphans()
        except Exception:  # noqa: BLE001 - 接管失败不阻止工作台启动
            _logger.exception("接管上次残留进程失败")
        try:
            bootstrapper.ensure_all_async()
        except Exception:  # noqa: BLE001
            _logger.exception("启动自举线程失败")

    listen_port = config.workbench_port if port is None else int(port)
    httpd: ThreadingHTTPServer | None = None
    try:
        httpd = make_server(config, manager, bootstrapper, listen_port)
        actual_port = httpd.server_address[1]
        if open_browser:
            try:
                webbrowser.open(f"http://{HOST}:{actual_port}/")
            except Exception:  # noqa: BLE001 - 没有浏览器也必须继续服务
                _logger.exception("无法打开浏览器")
        try:
            httpd.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    finally:
        if httpd is not None:
            try:
                httpd.server_close()
            except Exception:  # noqa: BLE001
                _logger.exception("关闭 HTTP 服务失败")
        try:
            manager.shutdown()
        except Exception:  # noqa: BLE001
            _logger.exception("退出时停止子进程失败")
    return 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Workbench/1.0"
    sys_version = ""
    # 声明了 Content-Length 却只发一半的客户端不能把工作线程永久挂住。
    timeout = 30

    # ------------------------------------------------------------ HTTP 入口
    def do_GET(self) -> None:  # noqa: N802 - http.server 的约定
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle("GET", head=True)

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._send_json(
            405,
            {"ok": False, "error": "不支持的请求方法"},
            extra_headers={"Allow": "GET, POST"},
            close=True,
        )

    def _handle(self, method: str, *, head: bool = False) -> None:
        self._head_request = head
        try:
            if not self._host_allowed():
                # 没读 body 就回 403：关连接，避免残留 body 被当成下一条请求。
                self._send_json(
                    403, {"ok": False, "error": "Host 头不被允许"}, close=True
                )
                return
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if method == "POST":
                # 有界读走并丢弃 body，否则 keep-alive 下一条请求会被拼成 "{}GET"。
                self._consume_body()
                self._check_origin()
                self._route_post(path, query)
            else:
                self._route_get(path, query)
        except _HttpError as exc:
            extra = {"Allow": exc.allow} if exc.allow else None
            self._send_json(
                exc.status,
                {"ok": False, "error": exc.message},
                extra_headers=extra,
                close=exc.close,
            )
        except Exception:  # noqa: BLE001 - 不把堆栈回给浏览器
            _logger.exception("处理请求失败：%s %s", method, self.path)
            self._send_json(500, {"ok": False, "error": "内部错误"}, close=True)

    def log_message(self, format: str, *args: Any) -> None:
        _logger.debug("%s - %s", self.address_string(), format % args)

    # --------------------------------------------------------------- 路由
    def _route_get(self, path: str, query: dict[str, list[str]]) -> None:
        segments = _segments(path)

        if path in ("/", "/index.html"):
            self._serve_static("index.html")
            return
        if path == "/api/state":
            self._send_json(200, {"ok": True, "data": self._state_data()})
            return
        if path == "/api/ping":
            self._send_ping()
            return
        if path == "/api/files/recent":
            self._send_json(200, {"ok": True, "data": self._recent_files()})
            return
        if path == "/api/diagnostics":
            self._send_text(
                200, build_report(self.config, self.manager, self.bootstrapper)
            )
            return
        if len(segments) == 3 and segments[:2] == ["api", "logs"]:
            self._send_logs(segments[2], query)
            return
        if len(segments) == 4 and segments[:2] == ["api", "dirs"]:
            self._send_dir(segments[2], segments[3])
            return

        if _is_post_only(path, segments):
            raise _HttpError(
                405, f"该接口只接受 POST：{path}", allow="POST"
            )
        if path.startswith("/api/"):
            raise _HttpError(404, f"未知接口：{path}")
        self._serve_static(path.lstrip("/"))

    def _route_post(self, path: str, query: dict[str, list[str]]) -> None:
        segments = _segments(path)

        if path == "/api/tools/start-all":
            statuses = self.bootstrapper.status()
            ready = {
                tool_id
                for tool_id, spec in self.config.tools.items()
                if (statuses.get(spec.environment) or {}).get("state") == "ready"
            }
            if not ready:
                raise _HttpError(409, "运行环境还没准备好，请稍候再试")
            for tool_id in self.config.tools:
                if tool_id not in ready:
                    continue
                try:
                    self.manager.start(tool_id)
                except Exception:  # noqa: BLE001 - 单个失败不影响其他
                    pass
            self._send_json(200, {"ok": True, "data": self.manager.states()})
            return
        if path == "/api/tools/stop-all":
            self.manager.stop_all()
            self._send_json(200, {"ok": True, "data": self.manager.states()})
            return
        if path == "/api/shutdown":
            self._start_shutdown()
            return
        if len(segments) == 4 and segments[:2] == ["api", "tools"]:
            tool_id, action = segments[2], segments[3]
            if action in ("start", "stop"):
                self._send_tool_action(tool_id, action)
                return
            if action == "reveal":
                self._send_reveal(tool_id, query)
                return
        if (
            len(segments) == 4
            and segments[:2] == ["api", "envs"]
            and segments[3] == "rebuild"
        ):
            self._send_env_rebuild(segments[2])
            return

        if _is_get_only(path, segments):
            raise _HttpError(
                405, f"该接口只接受 GET：{path}", allow="GET"
            )
        raise _HttpError(404, f"未知接口：{path}")

    # ----------------------------------------------------------- API 实现
    def _state_data(self) -> dict[str, Any]:
        legacy = probe_http(LEGACY_HEALTH_URL, timeout=LEGACY_TIMEOUT)
        return {
            "workbench": {
                "version": __version__,
                "pid": os.getpid(),
                "port": self.server.server_address[1],
            },
            "environments": self.bootstrapper.status(),
            "tools": self.manager.states(),
            "legacy_streamlit": bool(legacy),
        }

    def _send_ping(self) -> None:
        payload = {
            "app": APP_NAME,
            "pid": os.getpid(),
            "port": self.server.server_address[1],
        }
        # 顶层字段供 instance.find_running 直接读取；data 保持统一响应形状。
        self._send_json(200, {"ok": True, **payload, "data": dict(payload)})

    def _send_tool_action(self, tool_id: str, action: str) -> None:
        if tool_id not in self.config.tools:
            raise _HttpError(404, f"未知工具：{tool_id}")
        if action == "start":
            env_id = self.config.tools[tool_id].environment
            env_status = self.bootstrapper.status().get(env_id) or {}
            if env_status.get("state") != "ready":
                detail = env_status.get("detail") or env_status.get("state") or "未知"
                raise _HttpError(
                    409,
                    f"{self.config.tools[tool_id].name} 的运行环境还没准备好"
                    f"（{detail}），请稍候再试",
                )
            data = self.manager.start(tool_id)
        else:
            try:
                data = self.manager.stop(tool_id)
            except PermissionError as exc:
                raise _HttpError(409, str(exc)) from exc
        self._send_json(200, {"ok": True, "data": data})

    def _send_env_rebuild(self, env_id: str) -> None:
        if env_id not in self.config.environments:
            raise _HttpError(404, f"未知环境：{env_id}")
        self._send_json(
            200, {"ok": True, "data": self.bootstrapper.rebuild(env_id)}
        )

    def _send_logs(self, tool_id: str, query: dict[str, list[str]]) -> None:
        if tool_id not in self.config.tools:
            raise _HttpError(404, f"未知工具：{tool_id}")
        lines = _parse_lines(query)
        self._send_text(200, self.manager.log_tail(tool_id, lines))

    def _send_dir(self, tool_id: str, key: str) -> None:
        tool = self.config.tools.get(tool_id)
        if tool is None:
            raise _HttpError(404, f"未知工具：{tool_id}")
        if key not in tool.dirs:
            raise _HttpError(404, f"未知目录：{key}")
        path = self._tool_dir(tool, key)
        self._send_json(200, {"ok": True, "data": {"path": str(path)}})

    def _tool_dir(self, tool: Any, key: str) -> Path:
        path = Path(tool.dirs[key])
        if not path.is_absolute():
            path = Path(tool.root) / path
        try:
            return path.resolve()
        except OSError:
            return path

    def _inside(self, path: Path, roots: list[Path]) -> bool:
        for root in roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _send_reveal(self, tool_id: str, query: dict[str, list[str]]) -> None:
        """在 Finder / 资源管理器里定位输出目录、日志或某个产物文件。"""
        tool = self.config.tools.get(tool_id)
        if tool is None:
            raise _HttpError(404, f"未知工具：{tool_id}")
        what = (query.get("what") or ["output"])[0]
        name = (query.get("name") or [""])[0]
        runtime = Path(self.config.runtime_dir).resolve()
        roots = [Path(tool.root).resolve(), runtime]

        target: Path
        select = False
        if what == "log":
            target = runtime / "logs" / f"{tool_id}.log"
            select = target.is_file()
            if not target.exists():
                target = target.parent
        elif what == "data":
            target = Path(tool.root).resolve()
        elif what == "output":
            keys = [key for key in tool.dirs if "输出" in key]
            if not keys:
                raise _HttpError(404, "该工具没有配置输出目录")
            target = self._tool_dir(tool, keys[0])
            if name:
                safe = Path(name).name
                if safe != name or name in (".", ".."):
                    raise _HttpError(400, "文件名不合法")
                candidate = target / safe
                if candidate.is_file():
                    target = candidate.resolve()
                    select = True
        else:
            raise _HttpError(400, f"未知的定位类型：{what}")

        if not self._inside(target, roots):
            raise _HttpError(403, "路径不在允许的范围内")
        opened = self._reveal_path(target, select=select)
        self._send_json(
            200,
            {"ok": True, "data": {"path": str(target), "opened": opened}},
        )

    @staticmethod
    def _reveal_path(path: Path, *, select: bool = False) -> bool:
        """调用系统文件管理器；失败只返回 False，不影响接口。"""
        try:
            if sys.platform == "darwin":
                cmd = ["open", "-R", str(path)] if select else ["open", str(path)]
            elif sys.platform == "win32":
                cmd = (
                    ["explorer", f"/select,{path}"] if select else ["explorer", str(path)]
                )
            else:
                cmd = ["xdg-open", str(path.parent if select else path)]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            return False


    def _recent_files(self) -> dict[str, Any]:
        """每个工具有输出目录时各取最近 8 个 xlsx；同时保留全局 Top8 兼容旧前端。"""
        by_tool: dict[str, dict[str, Any]] = {}
        flat: list[dict[str, Any]] = []

        for tool in self.config.tools.values():
            keys = [key for key in tool.dirs if "输出" in key]
            if not keys:
                continue
            found: list[tuple[dict[str, Any], Path]] = []
            first_existing: Path | None = None
            for key in keys:
                directory = self._tool_dir(tool, key)
                if first_existing is None and directory.is_dir():
                    first_existing = directory
                if not directory.is_dir():
                    continue
                try:
                    entries = list(directory.iterdir())
                except OSError:
                    entries = []
                for entry in entries:
                    if entry.name.startswith(("~$", ".")):
                        continue
                    if entry.suffix.lower() != ".xlsx":
                        continue
                    try:
                        if not entry.is_file():
                            continue
                        stat = entry.stat()
                    except OSError:
                        continue
                    found.append(
                        (
                            {
                                "name": entry.name,
                                "size": int(stat.st_size),
                                "mtime": float(stat.st_mtime),
                            },
                            directory,
                        )
                    )

            found.sort(key=lambda item: (-item[0]["mtime"], item[0]["name"]))
            found = found[:8]
            chosen_dir = found[0][1] if found else first_existing
            by_tool[tool.id] = {
                "name": tool.name,
                "dir": str(chosen_dir) if chosen_dir is not None else None,
                "files": [item for item, _directory in found],
            }
            flat.extend(item for item, _directory in found)

        flat.sort(key=lambda item: (-item["mtime"], item["name"]))
        flat = flat[:8]
        chosen = next(
            (entry["dir"] for entry in by_tool.values() if entry["files"]),
            next((entry["dir"] for entry in by_tool.values() if entry["dir"]), None),
        )
        return {"files": flat, "dir": chosen, "by_tool": by_tool}

    # ------------------------------------------------------------- 静态文件
    def _serve_static(self, relative: str) -> None:
        if "\x00" in relative or "\\" in relative:
            raise _HttpError(404, "文件不存在")
        parts = relative.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise _HttpError(404, "文件不存在")

        root = WEB_DIR.resolve()
        try:
            target = (root / relative).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            raise _HttpError(404, "文件不存在") from None

        mime = MIME_TYPES.get(target.suffix.lower())
        if mime is None or not target.is_file():
            raise _HttpError(404, "文件不存在")
        try:
            body = target.read_bytes()
        except OSError:
            raise _HttpError(404, "文件不存在") from None
        self._send(200, mime, body)

    # --------------------------------------------------------------- 请求体
    def _consume_body(self) -> None:
        """按 Content-Length 有界读取并丢弃 body，保持 keep-alive 帧对齐。"""
        if self.headers.get("Transfer-Encoding"):
            raise _HttpError(400, "不支持分块请求体", close=True)
        raw = self.headers.get("Content-Length")
        if raw is None:
            return
        try:
            length = int(raw)
        except (TypeError, ValueError):
            raise _HttpError(400, "Content-Length 非法", close=True) from None
        if length < 0:
            raise _HttpError(400, "Content-Length 非法", close=True)
        if length > MAX_BODY_BYTES:
            raise _HttpError(413, "请求体过大", close=True)
        if length:
            data = self.rfile.read(length)
            if len(data) != length:
                raise _HttpError(400, "请求体不完整", close=True)

    def _check_origin(self) -> None:
        """POST 的 Origin（若存在）必须是本机工作台；curl/脚本无 Origin 放行。"""
        origin = self.headers.get("Origin")
        if origin is None:
            return
        if not self._origin_allowed(origin):
            raise _HttpError(403, "Origin 不被允许")

    def _origin_allowed(self, origin: str) -> bool:
        value = origin.strip().lower()
        port = self.server.server_address[1]
        return value in (
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        )

    # --------------------------------------------------------------- 退出
    def _start_shutdown(self) -> None:
        manager = self.manager
        server = self.server
        # 先让浏览器拿到 200，再在后台真正停子进程 / 关服务。
        self._send_json(200, {"ok": True, "data": {"stopping": True}})

        def stop() -> None:
            try:
                manager.shutdown()
            except Exception:  # noqa: BLE001
                _logger.exception("退出时停止子进程失败")
            finally:
                try:
                    server.shutdown()
                except Exception:  # noqa: BLE001
                    _logger.exception("关闭 HTTP 服务失败")

        timer = threading.Timer(SHUTDOWN_DELAY, stop)
        timer.daemon = True
        timer.start()

    # --------------------------------------------------------------- 响应
    def _host_allowed(self) -> bool:
        header = self.headers.get("Host")
        if not header:
            return False
        host = header.strip().lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
        close: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(
            status,
            "application/json; charset=utf-8",
            body,
            extra_headers=extra_headers,
            close=close,
        )

    def _send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8", errors="replace")
        self._send(status, "text/plain; charset=utf-8", body)

    def _send(
        self,
        status: int,
        content_type: str,
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
        close: bool = False,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            # HEAD 与 GET 共用路由/Content-Length，但不写 body。
            if body and not getattr(self, "_head_request", False):
                self.wfile.write(body)
        except OSError:
            # 客户端提前断开：记一条日志即可，避免刷 500。
            _logger.debug("响应写入失败：%s %s", self.command, self.path)

    # 便于类型检查；实际属性挂在 server 上。
    @property
    def config(self) -> Any:
        return self.server.config

    @property
    def manager(self) -> Any:
        return self.server.manager

    @property
    def bootstrapper(self) -> Any:
        return self.server.bootstrapper


def _segments(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


_POST_ONLY_EXACT = {
    "/api/tools/start-all",
    "/api/tools/stop-all",
    "/api/shutdown",
}
_GET_ONLY_EXACT = {
    "/api/state",
    "/api/ping",
    "/api/files/recent",
    "/api/diagnostics",
}


def _is_post_only(path: str, segments: list[str]) -> bool:
    if path in _POST_ONLY_EXACT:
        return True
    if (
        len(segments) == 4
        and segments[:2] == ["api", "tools"]
        and segments[3] in ("start", "stop")
    ):
        return True
    return (
        len(segments) == 4
        and segments[:2] == ["api", "envs"]
        and segments[3] == "rebuild"
    )


def _is_get_only(path: str, segments: list[str]) -> bool:
    if path in _GET_ONLY_EXACT:
        return True
    if len(segments) == 3 and segments[:2] == ["api", "logs"]:
        return True
    return len(segments) == 4 and segments[:2] == ["api", "dirs"]


def _parse_lines(query: dict[str, list[str]]) -> int:
    raw_values = query.get("lines") or []
    raw = raw_values[0] if raw_values else ""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return LOG_DEFAULT_LINES
    return max(1, min(LOG_MAX_LINES, value))
