"""七个工具共用的本地 HTTP 服务与页面入口。"""

from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib.parse import parse_qs, urlparse

from . import __version__
from .excel import ExcelError, read_table
from .schema import default_payload, json_safe, normalize
from .selfcheck import exception_report, run_checks

WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
MAX_BODY = 32 * 1024 * 1024


class ToolApplication:
    def __init__(self, meta: dict, fields: List[dict], compute: Callable, sample: Callable):
        self.meta = meta
        self.fields = fields
        self.compute = compute
        self.sample = sample

    def meta_payload(self) -> dict:
        return {
            "ok": True,
            "meta": {**self.meta, "version": self.meta.get("version") or __version__},
            "fields": self.fields,
            "defaults": default_payload(self.fields),
        }

    def sample_payload(self, seed: int | None) -> dict:
        return {"ok": True, "data": json_safe(self.sample(seed))}

    def run_payload(self, payload: dict) -> dict:
        data, errors = normalize(self.fields, payload)
        if errors:
            return {"ok": False, "errors": errors}
        try:
            result = self.compute(data)
        except (ValueError, ExcelError) as exc:
            return {"ok": False, "errors": [str(exc)]}
        except Exception as exc:  # noqa: BLE001
            report = exception_report(
                tool_id=self.meta.get("id", "tool"),
                meta=self.meta,
                error=exc,
                context={"input": data},
            )
            return {
                "ok": False,
                "errors": ["计算时发生内部错误，已生成报告，请先查看再决定是否转发。"],
                "report": report,
            }
        return {"ok": True, **json_safe(result)}

    def selfcheck_payload(self, fix: bool) -> dict:
        return run_checks(
            tool_id=self.meta.get("id", "tool"),
            meta=self.meta,
            fields=self.fields,
            sample=self.sample,
            compute=self.compute,
            fix=fix,
        )

    def import_payload(self, payload: dict) -> dict:
        filename = str(payload.get("filename") or "")
        encoded = str(payload.get("data_base64") or "")
        columns = payload.get("columns")
        if not filename or not encoded:
            return {"ok": False, "errors": ["缺少文件名或文件内容"]}
        if not isinstance(columns, list):
            return {"ok": False, "errors": ["缺少列定义"]}
        try:
            data = base64.b64decode(encoded, validate=True)
            rows, warnings = read_table(filename, data, columns)
        except (ValueError, ExcelError) as exc:
            return {"ok": False, "errors": [str(exc)]}
        return {"ok": True, "rows": json_safe(rows), "warnings": warnings}


class _Handler(BaseHTTPRequestHandler):
    server_version = "FIToolbox/0.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return True
        if host.startswith("["):
            return host.split("]")[0].lstrip("[") in ALLOWED_HOSTS or host in ALLOWED_HOSTS
        return host.split(":")[0] in ALLOWED_HOSTS

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("请求过大")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"请求不是合法 JSON：{exc}") from exc
        return payload if isinstance(payload, dict) else {}

    def _static(self, name: str) -> None:
        target = (WEB_DIR / name).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._json(404, {"ok": False, "errors": ["not found"]})
            return
        if not target.is_file():
            self._json(404, {"ok": False, "errors": ["not found"]})
            return
        self._send(200, target.read_bytes(), STATIC_TYPES.get(target.suffix, "application/octet-stream"))

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._json(403, {"ok": False, "errors": ["host not allowed"]})
            return
        app: ToolApplication = self.server.app
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path in ("/app.js", "/style.css"):
            self._static(path.lstrip("/"))
            return
        if path == "/api/health":
            self._json(200, {"ok": True, "tool": app.meta.get("id"), "version": __version__})
            return
        if path == "/api/meta":
            self._json(200, app.meta_payload())
            return
        if path == "/api/sample":
            seed = parse_qs(parsed.query).get("seed", [None])[0]
            try:
                value = int(seed) if seed is not None else None
            except ValueError:
                value = None
            self._json(200, app.sample_payload(value))
            return
        if path == "/api/selfcheck":
            fix = parse_qs(parsed.query).get("fix", ["1"])[0] != "0"
            self._json(200, app.selfcheck_payload(fix))
            return
        self._json(404, {"ok": False, "errors": ["not found"]})

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._json(403, {"ok": False, "errors": ["host not allowed"]})
            return
        app: ToolApplication = self.server.app
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._json(400, {"ok": False, "errors": [str(exc)]})
            return
        if path == "/api/run":
            self._json(200, app.run_payload(payload))
            return
        if path == "/api/import":
            self._json(200, app.import_payload(payload))
            return
        self._json(404, {"ok": False, "errors": ["not found"]})


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app: ToolApplication):
        self.app = app
        super().__init__(address, _Handler)

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, ConnectionError):
            return
        super().handle_error(request, client_address)


def find_free_port(host: str, start: int, tries: int = 20) -> int:
    for offset in range(tries):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"端口 {start} 起 {tries} 个都被占用")


def run(meta: dict, fields: List[dict], compute: Callable, sample: Callable) -> int:
    parser = argparse.ArgumentParser(description=meta.get("name") or "固收工具箱")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(meta.get("port") or 8600))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    port = find_free_port(args.host, args.port)
    app = ToolApplication(meta, fields, compute, sample)
    httpd = _Server((args.host, port), app)
    url = f"http://{args.host}:{port}/"
    print(f"{meta.get('name') or '固收工具箱'}已启动：{url}")
    print("按 Ctrl-C 停止。")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
