#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投标簿记信息提取工具 —— 唯一入口。

直接执行：
    python3 app.py             # 首次自动建 .venv 装依赖，然后打开网页
    python3 app.py --doctor    # 只做环境自检（该修的自己修）
    python3 app.py --reinstall # 环境坏了，删掉 .venv 重装
    python3 app.py --port 8899 --no-browser
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fix_console_encoding() -> None:
    """Windows 控制台默认不是 UTF-8，避免中文输出乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def find_free_port(host: str, start: int, tries: int = 12) -> int:
    for offset in range(tries):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    return start


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="把投标量表格截图 + 债券文本行，合成固定格式的簿记文案",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只开本机）")
    parser.add_argument("--port", type=int, default=8765, help="端口（默认 8765，占了会自动往后找）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--doctor", action="store_true", help="只做环境自检与修复，不起服务")
    parser.add_argument("--reinstall", action="store_true", help="删掉 .venv 重新安装依赖")
    parser.add_argument("--no-warmup", action="store_true", help="启动时不预加载 OCR 模型（启动更快）")
    parser.add_argument("--selftest", action="store_true", help="只跑逻辑自检（解析/匹配/成文）")
    parser.add_argument("--version", action="store_true", help="显示版本号")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _fix_console_encoding()
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        from bidbook import __version__

        print("投标簿记信息提取工具 v" + __version__)
        return 0

    from bidbook import envcheck

    bootstrap_code = envcheck.ensure_environment(force_reinstall=args.reinstall)
    if bootstrap_code != 0:
        return bootstrap_code

    if args.doctor:
        return envcheck.doctor()

    if args.selftest:
        import subprocess

        print("[i] 逻辑自检（不调用 OCR，不需要联网）")
        return subprocess.run([sys.executable, "-u", str(ROOT / "selftest.py")], cwd=str(ROOT)).returncode

    try:
        from bidbook import ocr as ocr_mod

        if not any(e.get("available") for e in ocr_mod.available_engines()):
            print("[!] 现在没有任何可用的 OCR 引擎：网页能打开，但「识别表格」会失败。")
            print("    修一下：bash run.sh --doctor")
    except Exception:  # noqa: BLE001
        pass

    from bidbook.web import run

    port = args.port
    if port_in_use(args.host, port):
        print("[i] " + str(port) + " 端口已被占用", end="")
        port = find_free_port(args.host, port)
        print("，改用 " + str(port))

    try:
        run(host=args.host, port=port, open_browser=not args.no_browser, warmup=not args.no_warmup)
    except KeyboardInterrupt:
        print("\n[i] 已停止")
        return 130
    except OSError as exc:
        print("[✗] 启动失败：" + str(exc))
        print("    端口被占可以换一个：python3 app.py --port 8899")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
