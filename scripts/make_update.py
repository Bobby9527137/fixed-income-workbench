#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成增量更新包：只包含相对 base 版本改动过的文件。

用法（在仓库根目录或任意位置执行）：

    python3 scripts/make_update.py \
        --base v0.1.2 --target HEAD \
        --version 0.1.3 --base-version 0.1.2 \
        --out dist/fixed-income-workbench-update-v0.1.3.zip

产物没有顶层目录，解压后直接覆盖到原工作台文件夹即可；
runtime/（内置 Python 与 wheelhouse）不在包里，原样保留。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

README_NAME = "更新说明.txt"
MANIFEST_NAME = "update-manifest.json"

README_TEMPLATE = """固收工作台 更新包 v{version}（从 v{base_version} 升级）

使用方法
--------
1. 先退出正在运行的工作台（关闭终端窗口）。
2. 解压本更新包。
3. 把解压出来的所有文件拖进原来的工作台文件夹，选择「替换 / 合并」。
4. 重新双击「启动工作台.command」。

说明
----
- 本包只包含本次改动的 {count} 个文件，不包含内置 Python 与依赖。
- 原来的 runtime/ 目录会保留，不需要重新下载几百 MB。
- 如果更新后异常，重新下载完整包即可。
"""


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8")


def changed_files(base: str, target: str) -> tuple[list[str], list[str]]:
    files: list[str] = []
    deleted: list[str] = []
    output = git("diff", "--name-status", base, target)
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("D"):
            deleted.append(parts[1])
        elif status.startswith("R") or status.startswith("C"):
            deleted.append(parts[1])
            files.append(parts[2])
        else:
            files.append(parts[1])
    # 去重并保持顺序
    files = list(dict.fromkeys(files))
    deleted = list(dict.fromkeys(deleted))
    return files, deleted


def add_file(archive: zipfile.ZipFile, path: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(path)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    info.date_time = datetime.now().timetuple()[:6]
    archive.writestr(info, data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成固收工作台的增量更新包")
    parser.add_argument("--base", required=True, help="基线版本（tag / commit）")
    parser.add_argument("--target", default="HEAD", help="目标版本（默认 HEAD）")
    parser.add_argument("--version", required=True, help="目标版本号，如 0.1.3")
    parser.add_argument("--base-version", default="", help="基线版本号，如 0.1.2")
    parser.add_argument("--out", required=True, help="输出 zip 路径")
    args = parser.parse_args(argv)

    files, deleted = changed_files(args.base, args.target)
    if not files:
        print("没有文件差异，未生成更新包。", file=sys.stderr)
        return 1
    if deleted:
        print(
            "警告：以下文件在目标版本中已删除，更新包不会自动删除它们：\n  "
            + "\n  ".join(deleted),
            file=sys.stderr,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    with zipfile.ZipFile(out, "w") as archive:
        for path in files:
            # 必须从目标 commit 取内容，不能读工作区：工作区可能已经比目标版本新。
            data = subprocess.run(
                ["git", "show", f"{args.target}:{path}"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            mode = 0o755 if path.endswith((".command", ".sh")) else 0o644
            add_file(archive, path, data, mode)
            manifest_files.append(
                {
                    "path": path,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )

        readme = README_TEMPLATE.format(
            version=args.version,
            base_version=args.base_version or args.base,
            count=len(files),
        )
        add_file(archive, README_NAME, readme.encode("utf-8"), 0o644)

        manifest = {
            "product": "固收工作台",
            "version": args.version,
            "base_version": args.base_version or args.base,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": manifest_files,
            "deleted": deleted,
        }
        add_file(
            archive,
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            0o644,
        )

    print(f"更新包已生成：{out}")
    print(f"版本：{args.base_version or args.base} -> {args.version}")
    print(f"文件：{len(files)} 个，{out.stat().st_size / 1024:.1f} KB")
    for item in manifest_files:
        print(f"  {item['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
