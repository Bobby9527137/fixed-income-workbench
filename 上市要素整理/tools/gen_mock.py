#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随机生成「上市要素」测试文本。

    python tools/gen_mock.py                # 1 条，直接复制走
    python tools/gen_mock.py -n 5           # 5 条
    python tools/gen_mock.py --copy         # 顺便放剪贴板
    python tools/gen_mock.py --layout dense # 指定排版
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing.mock import generate  # noqa: E402


def _reconfigure() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def copy_to_clipboard(text: str) -> bool:
    """尽量把文本放进剪贴板；失败返回 False。"""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:  # noqa: BLE001
        pass

    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
            return True
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def main(argv: list[str] | None = None) -> int:
    _reconfigure()
    parser = argparse.ArgumentParser(description="生成随机上市要素测试文本")
    parser.add_argument("-n", "--count", type=int, default=1, help="生成条数，默认 1")
    parser.add_argument("--seed", type=int, default=None, help="固定随机种子")
    parser.add_argument(
        "--layout",
        choices=("labeled", "shuffled", "chatty", "dense", "fullwidth"),
        default=None,
        help="指定排版；默认每条随机",
    )
    parser.add_argument("--copy", action="store_true", help="把最后一条放进剪贴板")
    args = parser.parse_args(argv)

    texts: list[str] = []
    for index in range(max(1, args.count)):
        seed = None if args.seed is None else args.seed + index
        text, _ = generate(seed=seed, layout=args.layout)
        texts.append(text)

    print("\n\n".join(texts))

    if args.copy:
        ok = copy_to_clipboard(texts[-1])
        print("\n[已复制到剪贴板]" if ok else "\n[复制失败，请手动选择文本]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
