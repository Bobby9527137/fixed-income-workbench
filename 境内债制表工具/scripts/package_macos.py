# -*- coding: utf-8 -*-
"""
macOS 分发包打包脚本
====================
把项目打成 **UTF-8 文件名** 的 zip（python zipfile 对非 ASCII 名自动置
UTF-8 标志位，macOS 解压中文文件名不乱码——Windows 系统 tar/Compress-Archive
在中文区域设置下会写成 GBK 编码导致 Mac 上乱码，故必须用本脚本打包）。

排除 Windows 平台相关与生成内容：
  · .venv / .pydeps  —— Windows 虚拟环境与依赖（体积大且 Mac 用不了）
  · __pycache__ / *.pyc / .DS_Store
  · data/输出（生成结果）、dist（历史包）
  · .claude / .agents —— 技能库杂物

输出：dist/境内债制表工具_macOS.zip
运行：python scripts/package_macos.py
"""
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bondtable import PROJECT_ROOT  # noqa: E402

STAGE = os.path.join(os.path.dirname(PROJECT_ROOT), "macOS打包", "境内债制表工具")
OUT = os.path.join(PROJECT_ROOT, "dist", "境内债制表工具_macOS.zip")
EXCLUDE_DIRS = {".venv", ".pydeps", "__pycache__", "输出", "dist", ".claude", ".agents"}
EXCLUDE_FILES = {".DS_Store"}
# data/原始数据 只带测试样本（白名单）：用户放进去的真实数据绝不进分发包（2026-10-09 真实联调后加）
SAMPLE_WHITELIST = {"模拟数据_地方债.xlsx", "模拟数据_信用债.xlsx",
                    "单日样本_地方债.xlsx", "单日样本_信用债.xlsx", "放置说明.txt"}
MUST_HAVE = [
    "境内债制表工具/启动.command",
    "境内债制表工具/首次运行(Mac必读).txt",
    "境内债制表工具/scripts/app.py",
    "境内债制表工具/scripts/requirements.txt",
    "境内债制表工具/config/表头映射.json",
    "境内债制表工具/data/原始数据/单日样本_地方债.xlsx",
    "境内债制表工具/data/原始数据/单日样本_信用债.xlsx",
]


def main() -> int:
    # 1) 暂存干净副本（排除清单见模块 docstring）
    shutil.rmtree(os.path.dirname(STAGE), ignore_errors=True)
    os.makedirs(os.path.dirname(STAGE), exist_ok=True)

    def _ignore(directory, names):
        bad = {n for n in names
               if n in EXCLUDE_DIRS or n in EXCLUDE_FILES or n.endswith(".pyc")
               # 历史上网页上传曾泄漏 tmp*.xlsx 到根目录（已改内存直读，此处兜底排除）
               or (n.startswith("tmp") and n.endswith(".xlsx"))}
        if os.path.normpath(directory).endswith(os.path.join("data", "原始数据")):
            bad |= {n for n in names if n not in SAMPLE_WHITELIST}
        return bad

    shutil.copytree(PROJECT_ROOT, STAGE, ignore=_ignore)

    # 2) 打包（UTF-8 文件名 zip）
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(STAGE):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in sorted(files):
                if f in EXCLUDE_FILES or f.endswith(".pyc"):
                    continue
                p = os.path.join(root, f)
                arc = os.path.relpath(p, os.path.dirname(STAGE)).replace("\\", "/")
                z.write(p, arc)
                n += 1

    # 3) 校验：关键文件在、排除项不在、路径分隔符统一
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        assert all("\\" not in x for x in names), "存在反斜杠路径"
        missing = [m for m in MUST_HAVE if m not in names]
        assert not missing, f"缺少关键文件：{missing}"
        bad = [x for x in names
               if any(k in x for k in (".venv/", ".pydeps/", "__pycache__",
                                        "/输出/", ".claude", ".agents"))]
        assert not bad, f"不应打包的内容：{bad}"
        # 真实数据文件（用户放入 data/原始数据 联调的）绝不允许混入分发包
        leak = [x for x in names if "2026-09-22" in x or "一级发行" in x or "地方政府债" in x]
        assert not leak, f"疑似真实数据混入分发包：{leak}"

    print(f"已打包：{OUT}")
    print(f"文件数：{n}，大小：{os.path.getsize(OUT) / 1024:.1f} KB")
    print("条目名回读（UTF-8 校验）示例：")
    with zipfile.ZipFile(OUT) as z:
        for x in z.namelist():
            if any(k in x for k in ("启动.command", "首次运行", "单日样本", "表头映射", "启动.bat")):
                print("  " + x)

    shutil.rmtree(os.path.dirname(STAGE), ignore_errors=True)
    print("staging 已清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
