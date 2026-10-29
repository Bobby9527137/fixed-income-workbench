#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上市要素整理 · 唯一入口（纯标准库，零第三方依赖）。

    python app.py                      # 起服务并打开浏览器
    python app.py --port 8513
    python app.py --no-browser
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing.extract import parse  # noqa: E402
from listing.mock import generate  # noqa: E402
from listing.render import render  # noqa: E402

WEB_DIR = ROOT / "listing" / "web"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """浏览器关闭标签页会直接掐断 keep-alive 连接，这类断连不算服务错误。"""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, ConnectionError):
            return
        super().handle_error(request, client_address)


def _reconfigure() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "ListingElements/0.1"

    # ------------------------------------------------------------------ 基础
    def log_message(self, fmt: str, *args) -> None:  # 安静一点
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
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"请求不是合法 JSON：{exc}") from exc
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._json(403, {"error": "host not allowed"})
            return

        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._json(200, {"ok": True})
            return
        if path == "/api/mock":
            query = parse_qs(parsed.query)
            seed = query.get("seed", [None])[0]
            try:
                seed_value = int(seed) if seed is not None else None
            except ValueError:
                seed_value = None
            text, _ = generate(seed=seed_value)
            self._json(200, {"text": text})
            return

        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        name = path.lstrip("/")
        if "/" in name or name.startswith("."):
            self._json(404, {"error": "not found"})
            return
        self._static(name)

    def _static(self, name: str) -> None:
        target = (WEB_DIR / name).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._json(404, {"error": "not found"})
            return
        if not target.is_file():
            self._json(404, {"error": "not found"})
            return
        content_type = STATIC_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), content_type)

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._json(403, {"error": "host not allowed"})
            return

        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return

        if path == "/api/parse":
            text = payload.get("text") or ""
            if not isinstance(text, str):
                self._json(400, {"error": "text 必须是字符串"})
                return
            self._json(200, parse(text).as_dict())
            return

        if path == "/api/render":
            fields = payload.get("fields")
            if not isinstance(fields, dict):
                self._json(400, {"error": "fields 必须是对象"})
                return
            self._json(200, {"output": render(fields)})
            return

        self._json(404, {"error": "not found"})


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


def main(argv: list[str] | None = None) -> int:
    _reconfigure()
    parser = argparse.ArgumentParser(description="上市要素整理")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8513)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    port = find_free_port(args.host, args.port)
    url = f"http://{args.host}:{port}/"
    httpd = QuietThreadingHTTPServer((args.host, port), Handler)
    print(f"上市要素整理已启动：{url}")
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


if __name__ == "__main__":
    raise SystemExit(main())
