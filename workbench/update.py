"""自动更新：检查 GitHub Release、下载更新包、校验、覆盖、回滚。

设计原则：
- 只访问公开的 GitHub Release API 和资产地址；
- 只下载带 `update` 的增量包，不下载完整包；
- 校验 GitHub 提供的 SHA256 和包内 manifest；
- 覆盖前备份，失败自动回滚；
- 覆盖后需要重启工作台，由界面提示。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__

DEFAULT_REPO = "Bobby9527137/fixed-income-workbench"
API_TMPL = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = "gushou-workbench-updater/1.0"
CHECK_TTL = 6 * 3600
MANIFEST_NAME = "update-manifest.json"
NOTES_NAME = "更新说明.txt"
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "codeload.github.com",
}


class UpdateError(RuntimeError):
    pass


def version_key(value: Any) -> tuple[int, int, int, int]:
    parts = re.findall(r"\d+", str(value or ""))
    numbers = [int(part) for part in parts[:4]]
    while len(numbers) < 3:
        numbers.append(0)
    numbers = (numbers + [0, 0, 0, 0])[:4]
    return tuple(numbers)  # type: ignore[return-value]


def is_newer(latest: Any, current: Any) -> bool:
    return version_key(latest) > version_key(current)


def settings(config: Any) -> dict:
    raw: dict = {}
    try:
        data = json.loads((config.base_dir / "tools.json").read_text(encoding="utf-8"))
        raw = data.get("update") or {}
    except (OSError, ValueError, TypeError):
        raw = {}
    enabled = bool(raw.get("enabled", True))
    if os.environ.get("WB_NO_UPDATE", "").strip() in ("1", "true", "yes", "on"):
        enabled = False
    return {
        "enabled": enabled,
        "repo": str(raw.get("repo") or DEFAULT_REPO).strip(),
        "check_on_start": bool(raw.get("checkOnStart", True)),
    }


def _cache_path(config: Any) -> Path:
    return config.runtime_dir / "update-check.json"


def _load_cache(config: Any) -> dict:
    try:
        data = json.loads(_cache_path(config).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(config: Any, data: dict) -> None:
    try:
        config.runtime_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(config).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _require_https(url: str) -> None:
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme != "https":
        raise UpdateError("更新地址必须是 HTTPS")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"更新地址不在允许的域名内：{parsed.hostname}")


def _urllib_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _curl_bytes(url: str, timeout: float) -> bytes:
    curl = shutil.which("curl")
    if not curl and Path("/usr/bin/curl").is_file():
        curl = "/usr/bin/curl"
    if not curl:
        raise UpdateError("系统没有 curl，无法检查更新")
    result = subprocess.run(
        [
            curl, "-fsSL", "--max-time", str(int(timeout)),
            "--proto", "=https", "--tlsv1.2",
            "-H", "Accept: application/vnd.github+json",
            "-H", f"User-Agent: {USER_AGENT}",
            url,
        ],
        capture_output=True,
        timeout=timeout + 5,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[:300]
        raise UpdateError(f"下载失败（curl 退出码 {result.returncode}）：{detail}")
    return result.stdout


def _fetch_json(url: str, timeout: float = 10.0) -> dict:
    _require_https(url)
    try:
        return _urllib_json(url, timeout)
    except Exception as first:  # noqa: BLE001
        try:
            return json.loads(_curl_bytes(url, timeout).decode("utf-8"))
        except Exception as second:  # noqa: BLE001
            raise UpdateError(f"网络请求失败：{first}；curl 兜底也失败：{second}") from second


def _fetch_bytes(url: str, timeout: float = 120.0) -> bytes:
    _require_https(url)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            final = response.geturl()
            _require_https(final)
            return response.read()
    except Exception as first:  # noqa: BLE001
        try:
            return _curl_bytes(url, timeout)
        except Exception as second:  # noqa: BLE001
            raise UpdateError(f"下载失败：{first}；curl 兜底也失败：{second}") from second


def pick_update_asset(assets: list[dict], platform: str) -> dict | None:
    candidates = [
        asset for asset in assets
        if isinstance(asset, dict) and "update" in str(asset.get("name", "")).lower()
    ]
    if platform == "darwin":
        mac = [asset for asset in candidates if "macos" in asset["name"].lower()]
        generic = [asset for asset in candidates if "windows" not in asset["name"].lower()]
        pool = mac or generic
        return pool[0] if pool else None
    if platform == "win32":
        win = [asset for asset in candidates if "windows" in asset["name"].lower()]
        return win[0] if win else None
    return None


def check(config: Any, force: bool = False) -> dict:
    cfg = settings(config)
    current = __version__
    if not cfg["enabled"]:
        return {"status": "disabled", "current": current, "message": "未开启更新检查"}

    cached = _load_cache(config)
    if (
        not force
        and cached.get("current") == current
        and time.time() - float(cached.get("checked_at") or 0) < CHECK_TTL
    ):
        return cached

    try:
        data = _fetch_json(API_TMPL.format(repo=cfg["repo"]), timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "current": current,
            "message": f"检查更新失败：{exc}",
            "checked_at": time.time(),
        }

    tag = str(data.get("tag_name") or "").strip()
    latest = tag[1:] if tag.lower().startswith("v") else tag
    if data.get("prerelease") or not latest:
        result = {"status": "up_to_date", "current": current, "latest": current,
                  "message": "暂无更新", "checked_at": time.time()}
        _save_cache(config, result)
        return result

    if not is_newer(latest, current):
        result = {"status": "up_to_date", "current": current, "latest": latest,
                  "message": "暂无更新", "checked_at": time.time()}
        _save_cache(config, result)
        return result

    asset = pick_update_asset(list(data.get("assets") or []), sys.platform)
    if asset is None:
        result = {
            "status": "no_asset",
            "current": current,
            "latest": latest,
            "message": "当前系统暂无可用的更新包",
            "checked_at": time.time(),
        }
        _save_cache(config, result)
        return result

    result = {
        "status": "available",
        "current": current,
        "latest": latest,
        "tag": tag,
        "name": data.get("name") or f"v{latest}",
        "notes": str(data.get("body") or "")[:6000],
        "published_at": data.get("published_at") or "",
        "asset": {
            "name": asset.get("name"),
            "size": asset.get("size"),
            "url": asset.get("browser_download_url"),
            "digest": asset.get("digest"),
        },
        "checked_at": time.time(),
    }
    _save_cache(config, result)
    return result


def _safe_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(str(relative))
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise UpdateError(f"更新包路径非法：{relative}")
    if pure.parts[0] in ("runtime", ".git"):
        raise UpdateError(f"更新包不能修改运行期目录：{relative}")
    target = (root / Path(*pure.parts)).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents:
        raise UpdateError(f"更新包路径越界：{relative}")
    return target


def download_asset(asset: dict, dest: Path) -> Path:
    url = str(asset.get("url") or "")
    _require_https(url)
    data = _fetch_bytes(url)
    expected_size = asset.get("size")
    if isinstance(expected_size, int) and expected_size >= 0 and len(data) != expected_size:
        raise UpdateError(f"更新包大小不符：期望 {expected_size}，实际 {len(data)}")
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:"):
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest.split(":", 1)[1].lower():
            raise UpdateError("更新包 SHA256 校验失败，已拒绝覆盖")
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(dest.suffix + ".part")
    temp.write_bytes(data)
    os.replace(temp, dest)
    return dest


def apply_update(config: Any, result: dict) -> dict:
    if result.get("status") != "available":
        raise UpdateError("当前没有可应用的更新")
    current = __version__
    latest = str(result.get("latest") or "")
    if not is_newer(latest, current):
        raise UpdateError(f"目标版本 {latest} 不高于当前版本 {current}")

    asset = result.get("asset") or {}
    name = str(asset.get("name") or "update.zip")
    folder = config.runtime_dir / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    zip_path = folder / name
    download_asset(asset, zip_path)
    return apply_zip(zip_path, config, current, latest)


def apply_zip(zip_path: Path, config: Any, current: str, expected: str) -> dict:
    root = config.base_dir
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"更新包无法打开：{exc}") from exc

    with archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, ValueError) as exc:
            raise UpdateError("更新包缺少合法的 update-manifest.json") from exc
        version = str(manifest.get("version") or "")
        if not is_newer(version, current):
            raise UpdateError(f"更新包版本 {version} 不高于当前 {current}")
        if expected and version_key(version) != version_key(expected):
            raise UpdateError(f"更新包版本 {version} 与检查结果 {expected} 不一致")

        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise UpdateError("更新包 manifest 没有文件列表")
        allowed = {MANIFEST_NAME, NOTES_NAME}
        entries: list[tuple[str, Path, bytes, int]] = []
        for item in files:
            if not isinstance(item, dict):
                raise UpdateError("manifest 文件项格式错误")
            relative = str(item.get("path") or "")
            target = _safe_target(root, relative)
            try:
                data = archive.read(relative)
            except KeyError as exc:
                raise UpdateError(f"更新包缺少文件：{relative}") from exc
            expected_hash = str(item.get("sha256") or "")
            if expected_hash and hashlib.sha256(data).hexdigest() != expected_hash:
                raise UpdateError(f"文件校验失败：{relative}")
            info = archive.getinfo(relative)
            mode = (info.external_attr >> 16) & 0o777
            if mode == 0:
                mode = 0o755 if relative.endswith((".command", ".sh")) else 0o644
            entries.append((relative, target, data, mode))
            allowed.add(relative)

        for name in archive.namelist():
            if name.endswith("/"):
                continue
            if name not in allowed:
                raise UpdateError(f"更新包包含未声明文件：{name}")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = config.runtime_dir / "update-backup" / timestamp
        backup.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        backed_up: list[Path] = []
        try:
            for relative, target, data, mode in entries:
                if target.exists():
                    relative_backup = backup / Path(*PurePosixPath(relative).parts)
                    relative_backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, relative_backup)
                    backed_up.append(target)
                else:
                    created.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(target.suffix + ".update-tmp")
                temp.write_bytes(data)
                os.replace(temp, target)
                try:
                    os.chmod(target, mode)
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            for target in created:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            for relative, target, _data, _mode in entries:
                if target not in backed_up:
                    continue
                relative_backup = backup / Path(*PurePosixPath(relative).parts)
                if relative_backup.is_file():
                    try:
                        shutil.copy2(relative_backup, target)
                    except OSError:
                        pass
            raise UpdateError(f"覆盖失败，已回滚：{exc}") from exc

    state = {
        "version": version,
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "backup": str(backup),
        "files": len(entries),
    }
    try:
        (config.runtime_dir / "update-applied.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    return {"ok": True, **state}
