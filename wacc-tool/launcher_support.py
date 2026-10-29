#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动脚本共用的辅助小工具（仅用标准库，不依赖第三方包）。

用法：
    python launcher_support.py check-deps        # 打印缺失的依赖（空格分隔）
    python launcher_support.py free-port 8501    # 打印一个从 8501 起的空闲端口

之所以单独放一个文件，是为了避免在 Windows PowerShell 里用
``python -c "多行脚本"`` 时被参数引号处理搞坏。
"""

from __future__ import annotations

import importlib
import socket
import sys

# (import 名, 包名)
PACKAGES = [
    ("streamlit", "streamlit"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("xlrd", "xlrd"),
]

PORT_SCAN_RANGE = 50


def cmd_check_deps() -> int:
    missing = []
    for module, package in PACKAGES:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(package)
    sys.stdout.write(" ".join(missing))
    return 0


def cmd_free_port(start: int) -> int:
    for port in range(start, start + PORT_SCAN_RANGE):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                sys.stdout.write(str(port))
                return 0
            except OSError:
                continue
    sys.stdout.write("")
    return 0


def main(argv) -> int:
    if len(argv) >= 2 and argv[1] == "check-deps":
        return cmd_check_deps()
    if len(argv) >= 3 and argv[1] == "free-port":
        try:
            start = int(argv[2])
        except ValueError:
            start = 8501
        return cmd_free_port(start)
    sys.stderr.write("用法: launcher_support.py check-deps | free-port <起始端口>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
