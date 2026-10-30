"""自检与标准 bug 报告。

原则：
- 能自动修的（目录、默认配置、临时文件）直接修；
- 修不了的生成一份 Markdown 报告，放在本机报告目录；
- 报告只在本机，不联网、不自动发送；用户看过再决定是否转发。
"""

from __future__ import annotations

import base64
import json
import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __version__
from .schema import json_safe, normalize, validate_fields

REPORT_ENV = "FI_REPORT_DIR"


def report_dir() -> Path:
    raw = os.environ.get(REPORT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "固收工作台报告"


def _report_payload(path: Optional[Path]) -> Optional[dict]:
    if path is None:
        return None
    data = path.read_bytes()
    return {
        "path": str(path),
        "name": path.name,
        "base64": base64.b64encode(data).decode("ascii"),
    }


def run_checks(
    *,
    tool_id: str,
    meta: dict,
    fields: List[dict],
    sample: Callable[..., dict],
    compute: Callable[[dict], dict],
    fix: bool = True,
) -> dict:
    checks: List[dict] = []
    fatal: List[str] = []

    def add(name: str, ok: bool, detail: str = "", fixed: bool = False) -> None:
        status = "failed" if not ok else ("fixed" if fixed else "ok")
        checks.append({"name": name, "status": status, "detail": detail})
        if not ok:
            fatal.append(f"{name}：{detail}")

    add("Python 版本", sys.version_info >= (3, 10),
        f"{platform.python_version()}（需要 3.10+）")

    try:
        import openpyxl  # noqa: F401
        add("Excel 依赖", True, f"openpyxl {openpyxl.__version__}")
    except Exception as exc:  # noqa: BLE001
        add("Excel 依赖", False, f"无法 import openpyxl：{exc}")

    folder = report_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add("报告目录可写", True, str(folder))
    except Exception as exc:  # noqa: BLE001
        add("报告目录可写", False, f"{folder}：{exc}")

    schema_problems = validate_fields(fields)
    add("字段定义", not schema_problems, "；".join(schema_problems) if schema_problems else "正常")

    sample_error = ""
    sample_result = {}
    try:
        payload = sample(999)
        data, errors = normalize(fields, payload)
        if errors:
            sample_error = "；".join(errors)
        else:
            result = compute(data)
            if not isinstance(result, dict):
                sample_error = "compute 没有返回字典"
            else:
                sample_result = result
    except Exception:  # noqa: BLE001
        sample_error = traceback.format_exc()
    add("示例数据可计算", not sample_error, sample_error or "示例跑通")

    ok = not fatal
    report = None
    if not ok:
        report = write_report(
            tool_id=tool_id,
            meta=meta,
            checks=checks,
            error="\n".join(fatal),
            context={"sample": sample_result},
        )
    return {"ok": ok, "checks": checks, "report": _report_payload(report)}


def write_report(
    *,
    tool_id: str,
    meta: dict,
    checks: List[dict],
    error: str = "",
    context: Optional[dict] = None,
) -> Path:
    folder = report_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{tool_id}-bug-{stamp}.md"

    lines: List[str] = []
    lines.append(f"# 固收工作台 · 问题报告 · {meta.get('name') or tool_id}")
    lines.append("")
    lines.append("> 本报告只保存在本机。请先自行查看，确认无误后再转发给维护者。")
    lines.append("")
    lines.append("## 1. 概要")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 工具 | {meta.get('name') or tool_id}（{tool_id}） |")
    lines.append(f"| 工具版本 | {meta.get('version') or __version__} |")
    lines.append(f"| 时间 | {datetime.now().isoformat(timespec='seconds')} |")
    lines.append(f"| 系统 | {platform.platform()} |")
    lines.append(f"| Python | {platform.python_version()} |")
    lines.append(f"| 解释器 | {sys.executable} |")
    lines.append(f"| 工作目录 | {Path.cwd()} |")
    lines.append("")
    lines.append("## 2. 自检结果")
    lines.append("")
    lines.append("| 检查项 | 状态 | 说明 |")
    lines.append("|---|---|---|")
    for check in checks:
        detail = str(check.get("detail", "")).replace("\n", " ")[:300]
        lines.append(f"| {check.get('name')} | {check.get('status')} | {detail} |")
    lines.append("")
    if error:
        lines.append("## 3. 错误信息")
        lines.append("")
        lines.append("```text")
        lines.append(error.strip()[:8000])
        lines.append("```")
        lines.append("")
    if context:
        lines.append("## 4. 上下文")
        lines.append("")
        lines.append("```json")
        try:
            text = json.dumps(json_safe(context), ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            text = repr(context)
        lines.append(text[:8000])
        lines.append("```")
        lines.append("")
    lines.append("## 5. 复现步骤")
    lines.append("")
    lines.append("1. 打开该工具；")
    lines.append("2. 点「随机示例」或填入自己的数据；")
    lines.append("3. 点「计算」；")
    lines.append("4. 点「自检」，导出本报告。")
    lines.append("")
    lines.append("## 6. 期望")
    lines.append("")
    lines.append("页面正常显示结果；如果失败，请把本报告和截图一起发给维护者。")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def exception_report(*, tool_id: str, meta: dict, error: BaseException, context: dict) -> dict:
    checks = [{
        "name": "运行期异常",
        "status": "failed",
        "detail": f"{type(error).__name__}: {error}",
    }]
    path = write_report(
        tool_id=tool_id,
        meta=meta,
        checks=checks,
        error=traceback.format_exc(),
        context=context,
    )
    return _report_payload(path) or {}
