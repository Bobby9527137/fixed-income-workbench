"""``tools.json`` 的读取、校验与路径解析。

所有平台相关的路径都在这里一次性解析成绝对 :class:`~pathlib.Path`：
运行期其他模块只见 Path，不再关心 ``sys.platform``、相对路径或
``{"darwin": …, "win32": …}`` 形式的映射。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APP_DIR_NAME = "固收工作台"
TOOLS_FILENAME = "tools.json"
RUNTIME_DIR_ENV = "WB_RUNTIME_DIR"
SUPPORTED_PLATFORMS = ("darwin", "win32")
KNOWN_KINDS = ("streamlit", "python-entry")

_MISSING = object()  # 区分“键缺失”与“显式 null”


class ConfigError(Exception):
    """tools.json 缺失、格式错误，或与磁盘上的实际目录不一致。"""


@dataclass
class ToolSpec:
    """一个受管工具（制表 / 簿记 / WACC）。"""

    id: str
    name: str
    desc: str
    root: Path
    kind: str
    entry: str
    args: tuple[str, ...]
    environment: str
    port: int
    health_path: str
    dirs: dict[str, str]


@dataclass
class EnvSpec:
    """一套 Python 环境（离线 wheelhouse + 钉版依赖）。"""

    id: str
    requirements: Path
    wheelhouse: Path
    probe: tuple[str, ...]


@dataclass
class Config:
    """一次解析完成的完整配置。"""

    base_dir: Path
    runtime_dir: Path
    workbench_port: int
    python_archive: Path | None
    tools: dict[str, ToolSpec]
    environments: dict[str, EnvSpec]


def default_runtime_dir() -> Path:
    """返回用户目录下的运行期根目录（可被 ``WB_RUNTIME_DIR`` 覆盖）。"""
    override = os.environ.get(RUNTIME_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME / "runtime"
    if sys.platform == "win32":
        if _uses_windows_store_python():
            # Microsoft Store 版 Python 运行在 AppContainer 里，写入
            # ``%LOCALAPPDATA%`` 会被重定向进包私有目录，导致建出来的 venv
            # 找不到 pyvenv.cfg（``No pyvenv.cfg file``，退出码 106）。
            # 放到用户主目录即可绕开这层重定向。
            return Path.home() / APP_DIR_NAME / "runtime"
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_DIR_NAME / "runtime"
    raise ConfigError(f"不支持的平台：{sys.platform}")


def _uses_windows_store_python() -> bool:
    """当前解释器是否来自 Microsoft Store（``WindowsApps`` 下的别名）。"""
    try:
        executable = str(Path(sys.executable).resolve())
    except OSError:
        executable = str(sys.executable)
    lowered = executable.lower()
    return "windowsapps" in lowered


def load_config(base_dir: Path, runtime_dir: Path | None = None) -> Config:
    """读取 ``<base_dir>/tools.json`` 并解析成 :class:`Config`。

    ``base_dir`` 是交付包根目录，``tools.json`` 里的相对路径都相对它解析。
    ``runtime_dir`` 为空时使用 :func:`default_runtime_dir`。
    """
    base = _absolute(Path(base_dir).expanduser())
    source = base / TOOLS_FILENAME
    data = _read_json(source)
    platform_key = _current_platform()

    workbench = _expect_mapping(data.get("workbench", {}), "workbench")
    workbench_port = _expect_port(workbench.get("port"), "workbench.port")

    python_archive = _load_python_archive(base, data.get("platform"), platform_key)
    environments = _load_environments(base, data.get("environments"), platform_key)
    tools = _load_tools(base, data.get("tools", _MISSING), environments)

    runtime_path = default_runtime_dir() if runtime_dir is None else Path(runtime_dir).expanduser()
    runtime = _absolute(runtime_path)

    return Config(
        base_dir=base,
        runtime_dir=runtime,
        workbench_port=workbench_port,
        python_archive=python_archive,
        tools=tools,
        environments=environments,
    )


def _current_platform() -> str:
    if sys.platform not in SUPPORTED_PLATFORMS:
        raise ConfigError(f"不支持的平台：{sys.platform}")
    return sys.platform


def _absolute(path: Path) -> Path:
    """补全为绝对路径，但不解析符号链接/短文件名（保持与调用方传入的路径一致）。"""
    return path if path.is_absolute() else path.absolute()


def _resolve_from(base: Path, raw: str, where: str) -> Path:
    text = _expect_str(raw, where)
    candidate = Path(text).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在：{path}") from exc
    except OSError as exc:
        raise ConfigError(f"配置文件无法读取：{path}（{exc}）") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法的 JSON：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是 JSON 对象：{path}")
    return data


def _load_python_archive(base: Path, raw_platform: Any, platform_key: str) -> Path | None:
    """当前平台没配 ``pythonArchive``（或显式 null）时返回 None，表示用系统 Python。"""
    if raw_platform is None:
        return None
    platform_cfg = _expect_mapping(raw_platform, "platform")
    platform_values = platform_cfg.get(platform_key)
    if platform_values is None:
        return None
    values = _expect_mapping(platform_values, f"platform.{platform_key}")
    raw_archive = values.get("pythonArchive")
    if raw_archive is None:
        return None
    return _resolve_from(base, raw_archive, f"platform.{platform_key}.pythonArchive")


def _load_environments(base: Path, raw_envs: Any, platform_key: str) -> dict[str, EnvSpec]:
    if raw_envs is None:
        return {}
    envs = _expect_mapping(raw_envs, "environments")
    result: dict[str, EnvSpec] = {}
    for env_id, raw_env in envs.items():
        result[env_id] = _build_env(base, env_id, raw_env, platform_key)
    return result


def _build_env(base: Path, env_id: str, raw: Any, platform_key: str) -> EnvSpec:
    where = f"环境 {env_id}"
    env = _expect_mapping(raw, where)
    requirements = _resolve_from(
        base,
        _platform_entry(env.get("requirements"), platform_key, f"{where} 的 requirements"),
        f"{where} 的 requirements.{platform_key}",
    )
    wheelhouse = _resolve_from(
        base,
        _platform_entry(env.get("wheelhouse"), platform_key, f"{where} 的 wheelhouse"),
        f"{where} 的 wheelhouse.{platform_key}",
    )
    probe = _expect_str_tuple(env.get("probe", ()), f"{where} 的 probe")
    return EnvSpec(id=env_id, requirements=requirements, wheelhouse=wheelhouse, probe=probe)


def _load_tools(
    base: Path, raw_tools: Any, environments: dict[str, EnvSpec]
) -> dict[str, ToolSpec]:
    # tools 是四个交付工具的唯一事实来源，缺失/为空一律报错，避免加载出“空工作台”。
    if raw_tools is _MISSING or raw_tools is None or raw_tools == []:
        raise ConfigError("tools 缺失或为空")
    if not isinstance(raw_tools, list):
        raise ConfigError("tools 必须是数组")
    result: dict[str, ToolSpec] = {}
    for index, raw_tool in enumerate(raw_tools):
        tool = _build_tool(base, raw_tool, index)
        if tool.id in result:
            raise ConfigError(f"工具 id 重复：{tool.id}")
        if tool.environment not in environments:
            raise ConfigError(f"工具 {tool.id} 引用了未定义的环境：{tool.environment}")
        result[tool.id] = tool
    return result


def _build_tool(base: Path, raw: Any, index: int) -> ToolSpec:
    entry = _expect_mapping(raw, f"tools[{index}]")
    tool_id = _expect_str(entry.get("id"), f"tools[{index}].id")
    where = f"工具 {tool_id}"

    root = _resolve_from(base, entry.get("root"), f"{where} 的 root")
    if not root.is_dir():
        raise ConfigError(f"工具 {tool_id} 的目录不存在：{root}")

    kind = _expect_str(entry.get("kind"), f"{where} 的 kind")
    if kind not in KNOWN_KINDS:
        raise ConfigError(f"{where} 的 kind 不受支持：{kind}（可选：{', '.join(KNOWN_KINDS)}）")

    health_path = _expect_str(entry.get("healthPath"), f"{where} 的 healthPath")
    if not health_path.startswith("/"):
        raise ConfigError(f"{where} 的 healthPath 必须以 / 开头：{health_path}")

    desc = entry.get("desc", "")
    if desc is None:
        desc = ""
    if not isinstance(desc, str):
        raise ConfigError(f"{where} 的 desc 必须是字符串")

    return ToolSpec(
        id=tool_id,
        name=_expect_str(entry.get("name"), f"{where} 的 name"),
        desc=desc,
        root=root,
        kind=kind,
        entry=_expect_str(entry.get("entry"), f"{where} 的 entry"),
        args=_expect_str_tuple(entry.get("args", ()), f"{where} 的 args"),
        environment=_expect_str(entry.get("environment"), f"{where} 的 environment"),
        port=_expect_port(entry.get("port"), f"{where} 的 port"),
        health_path=health_path,
        dirs=_expect_str_map(entry.get("dirs", {}), f"{where} 的 dirs"),
    )


def _platform_entry(raw: Any, platform_key: str, where: str) -> str:
    if not isinstance(raw, dict):
        raise ConfigError(f'{where} 必须是 {{"darwin": …, "win32": …}} 形式的对象')
    if platform_key not in raw:
        raise ConfigError(f"{where} 缺少 {platform_key} 平台的配置")
    return raw[platform_key]


def _expect_mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} 必须是 JSON 对象")
    return value


def _expect_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} 必须是非空字符串")
    return value


def _expect_port(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigError(f"{where} 必须是 1-65535 之间的整数：{value!r}")
    return value


def _expect_str_tuple(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where} 必须是字符串数组")
    return tuple(_expect_str(item, f"{where} 的每一项") for item in value)


def _expect_str_map(value: Any, where: str) -> dict[str, str]:
    mapping = _expect_mapping(value, where)
    return {
        _expect_str(key, f"{where} 的键"): _expect_str(item, f"{where}.{key}")
        for key, item in mapping.items()
    }
