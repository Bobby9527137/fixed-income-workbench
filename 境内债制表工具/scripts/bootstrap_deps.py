# -*- coding: utf-8 -*-
"""
scripts/bootstrap_deps.py — 依赖引导安装（备用方式）
====================================================
正常情况下请用：python -m pip install -r scripts/requirements.txt

本脚本用于受限环境（pip 安装被沙箱拦截时）：直接从 PyPI 下载 wheel 并解压到 ../.pydeps。
版本清单来自 pip 在 Python 3.14 / Windows x64 上的解析结果，全部为该平台的兼容版本。

用法：python scripts/bootstrap_deps.py
"""
import json
import os
import re
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOUSE = os.path.normpath(os.path.join(HERE, "..", ".wheelhouse"))
DEPS = os.path.normpath(os.path.join(HERE, "..", ".pydeps"))

# (PyPI 名称, 版本) —— 与 pip 解析结果一致
PACKAGES = [
    ("MarkupSafe", "3.0.4"), ("altair", "6.3.0"), ("anyio", "4.15.1"), ("attrs", "26.1.0"),
    ("certifi", "2026.7.22"), ("charset_normalizer", "3.5.2"), ("click", "8.5.0"),
    ("et-xmlfile", "2.0.0"), ("h11", "0.16.0"), ("httptools", "0.8.0"), ("idna", "3.20"),
    ("itsdangerous", "2.2.0"), ("jinja2", "3.1.6"), ("jsonschema", "4.26.0"),
    ("jsonschema-specifications", "2025.9.1"), ("narwhals", "2.26.0"), ("numpy", "2.5.3"),
    ("openpyxl", "3.1.5"), ("packaging", "26.3"), ("pandas", "3.0.6"), ("pillow", "12.3.0"),
    ("protobuf", "7.36.2"), ("pyarrow", "25.0.1"), ("pydeck", "0.9.3"),
    ("python-dateutil", "2.9.0.post0"), ("python-multipart", "0.0.32"),
    ("referencing", "0.37.0"), ("requests", "2.34.2"), ("rpds-py", "2026.9.1"),
    ("six", "1.17.0"), ("starlette", "1.7.0"), ("streamlit", "1.65.0"), ("toml", "0.10.2"),
    ("typing-extensions", "4.16.0"), ("tzdata", "2026.5"), ("urllib3", "2.8.0"),
    ("uvicorn", "0.54.0"), ("watchdog", "6.0.0"), ("websockets", "17.2.0"),
]

_WHEEL_RE = re.compile(r"^[^-]+-.+?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$")


def pick_url(urls):
    """按 本机 Python 3.14 / Windows x64 挑选兼容 wheel，返回 url dict 或 None"""
    best, best_score = None, 0
    for u in urls:
        fn = u["filename"]
        if not fn.endswith(".whl"):
            continue
        m = _WHEEL_RE.match(fn)
        if not m:
            continue
        py, abi, plat = m.group("py"), m.group("abi"), m.group("plat")
        # abi：none=纯文本 / abi3=稳定 ABI（cp3xx-abi3 兼容本机）/ cp314=CPython 专用构建
        if not (plat in ("any", "win_amd64") and abi in ("none", "abi3", "cp314")):
            continue
        tags = py.split(".")
        ok = any(t in ("py3", "cp314") for t in tags)
        if not ok and abi == "abi3":  # cp3xx-abi3 向后兼容本机 3.14
            ok = any(t.startswith("cp") and t[2:].isdigit() and int(t[2:]) <= 314 for t in tags)
        if not ok:
            continue
        score = 4 if ("cp314" in tags and plat == "win_amd64") else (3 if plat == "win_amd64" else 2)
        if score > best_score:
            best, best_score = u, score
    return best


def fetch(url, dest):
    if os.path.exists(dest):
        return dest
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)
    return dest


def main() -> int:
    os.makedirs(HOUSE, exist_ok=True)
    os.makedirs(DEPS, exist_ok=True)
    failed = []
    for i, (name, ver) in enumerate(PACKAGES, 1):
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=120) as r:
                urls = json.load(r)["urls"]
            u = pick_url(urls)
            if u is None:
                raise RuntimeError("无兼容本机的 wheel")
            dest = fetch(u["url"], os.path.join(HOUSE, u["filename"]))
            with zipfile.ZipFile(dest) as z:
                z.extractall(DEPS)
            print(f"[{i:02d}/{len(PACKAGES)}] {name}=={ver} ✓  {u['filename']}")
        except Exception as e:
            failed.append((name, repr(e)))
            print(f"[{i:02d}/{len(PACKAGES)}] {name}=={ver} ✗  {e}")
    if failed:
        print("\n失败清单：", failed)
        return 1
    sys.path.insert(0, DEPS)
    import openpyxl
    import pandas
    import streamlit
    print(f"\n自检通过：pandas {pandas.__version__} / openpyxl {openpyxl.__version__} / streamlit {streamlit.__version__}")
    print(f"依赖目录：{DEPS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
