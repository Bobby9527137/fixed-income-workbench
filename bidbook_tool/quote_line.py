#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报价要素生成工具 —— 唯一入口。

把交易行文本和 DM 截图合成一行固定格式的报价：

    [剩余期限] [债券代码] [债券简称] [公募/私募] --/[OFR价格]* --/[带量]w
    [主体评级]/[债项评级] 昨日中债 [中债估值] 票面 [票面利率] [带量]w

直接执行：
    python3 quote_line.py              # 打开网页
    python3 quote_line.py --port 8899 --no-browser
    python3 quote_line.py --selftest   # 只跑逻辑自检（不调用 OCR）
    python3 quote_line.py --version
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
        description="把交易行文本 + DM 截图，合成固定格式的报价行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只开本机）")
    parser.add_argument("--port", type=int, default=8766, help="端口（默认 8766，占了会自动往后找）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--no-warmup", action="store_true", help="启动时不预加载 OCR 模型（启动更快）")
    parser.add_argument("--selftest", action="store_true", help="只跑逻辑自检（解析/合并/拼装）")
    parser.add_argument("--version", action="store_true", help="显示版本号")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _fix_console_encoding()
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        from quoteline import __version__

        print("报价要素生成工具 v" + __version__)
        return 0

    if args.selftest:
        from quoteline import selfcheck

        result = selfcheck.run_checks()
        for check in result["checks"]:
            mark = "✓" if check["ok"] else "✗"
            print(f"{mark} {check['name']}：{check['detail']}")
        return 0 if result["ok"] else 1

    try:
        from bidbook import ocr as ocr_mod

        if not any(e.get("available") for e in ocr_mod.available_engines()):
            print("[!] 现在没有任何可用的 OCR 引擎：网页能打开，但截图识别会失败。")
            print("    只贴交易行文本仍然可以生成报价。")
    except Exception:  # noqa: BLE001
        pass

    from quoteline.web import run

    port = args.port
    if port_in_use(args.host, port):
        print("[i] " + str(port) + " 端口已被占用", end="")
        port = find_free_port(args.host, port)
        print("，改用 " + str(port))

    try:
        run(
            host=args.host,
            port=port,
            open_browser=not args.no_browser,
            warmup=not args.no_warmup,
        )
    except KeyboardInterrupt:
        print("\n[i] 已停止")
        return 130
    except OSError as exc:
        print("[✗] 启动失败：" + str(exc))
        print("    端口被占可以换一个：python3 quote_line.py --port 8899")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
