# -*- coding: utf-8 -*-
"""环境管理：建虚拟环境、装依赖、自检、坏了自动修。

macOS 上没有任何 Python 时，直接跑 run.sh 会自动尝试 homebrew；
Python 3.14 等太新的版本装不上 onnxruntime 也完全没关系，程序会退回
macOS 原生 Vision 引擎（同样离线、免费）。
"""

from __future__ import annotations

import collections
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

MIN_PY = (3, 9)
PREFERRED_PY = ["3.12", "3.11", "3.13", "3.10", "3.9"]
VENV_DIRNAME = ".venv"
STAMP_FILENAME = ".env-stamp.json"

# 运行必须的包（缺任何一个都不能继续）
REQUIRED_PACKAGES: List[Tuple[str, str]] = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("multipart", "python-multipart"),   # 缺它 FastAPI 定义 File() 路由时会直接报错
    ("numpy", "numpy"),
    ("PIL", "Pillow"),
    ("cv2", "opencv-python-headless"),
    ("rapidfuzz", "rapidfuzz"),
]

# 可选的 OCR 引擎（缺了只是少一条路线）。
# 每项是 (import 名，多个用 | 分隔且只要有一个在就算可用, 对应的 pip 包名, 只在哪个平台提示)。
# 注意 rapidocr 与 rapidocr_onnxruntime 是同一套模型的两个包名，不能当成两条独立路线报缺失。
OPTIONAL_PACKAGES: List[Tuple[str, str, str]] = [
    ("rapidocr_onnxruntime|rapidocr", "rapidocr-onnxruntime", "any"),
    ("Vision", "pyobjc-framework-Vision", "darwin"),
    ("Quartz", "pyobjc-framework-Quartz", "darwin"),
]


def optional_missing_list() -> List[str]:
    """还没有满足的 OCR 路线（只报与本机平台有关、且同一组里全都没装的）。"""
    missing: List[str] = []
    for modules, spec, platform in OPTIONAL_PACKAGES:
        if platform != "any" and sys.platform != platform:
            continue
        if any(package_installed(name) for name in modules.split("|")):
            continue
        missing.append(spec)
    return missing


# --------------------------------------------------------------------------- #
# 下载源：国内网络直连 pypi.org 常常慢到装不动，默认走清华镜像；
# 镜像不通或没有某个包时自动回退官方源，绝不因为换源而装不上。
# 想固定用别的源，设置环境变量即可，例如：
#   export BIDBOOK_MIRROR=https://mirrors.aliyun.com/pypi/simple/
#   export BIDBOOK_MIRROR=off          # 只用官方源
# --------------------------------------------------------------------------- #

MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
OFFICIAL_URL = "https://pypi.org/simple"


def mirror_url() -> Optional[str]:
    env = (os.environ.get("BIDBOOK_MIRROR") or "").strip()
    if env:
        if env.lower() in ("off", "none", "0", "no", "false"):
            return None
        return env if "://" in env else "https://" + env
    pip_env = (os.environ.get("PIP_INDEX_URL") or "").strip()
    if pip_env:
        return None  # 用户已经自己配了源，尊重他的选择
    return MIRROR_URL


def _index_args(url: Optional[str]) -> List[str]:
    if not url:
        return []
    args = ["-i", url]
    try:
        host = url.split("://", 1)[1].split("/", 1)[0]
        if host:
            args += ["--trusted-host", host]
    except IndexError:
        pass
    return args


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_dir() -> Path:
    return project_root() / VENV_DIRNAME


def venv_python(venv: Optional[Path] = None) -> Path:
    venv = venv or venv_dir()
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def package_installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def interpreter_version(exe: str) -> Optional[Tuple[int, int, int]]:
    try:
        out = subprocess.run(
            [exe, "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", (out.stdout or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def candidate_interpreters() -> List[str]:
    """按「兼容性优先」的顺序找 Python。"""
    found: List[str] = []
    for name in PREFERRED_PY:
        exe = shutil.which(f"python{name}")
        if exe:
            found.append(exe)
    for name in ("python3", "python"):
        exe = shutil.which(name)
        if exe and exe not in found:
            found.append(exe)
    return found


def pick_interpreter() -> Optional[str]:
    usable: List[Tuple[Tuple[int, int, int], str]] = []
    for exe in candidate_interpreters():
        version = interpreter_version(exe)
        if not version:
            continue
        if version[:2] < MIN_PY:
            continue
        usable.append((version, exe))
    if not usable:
        return None
    # 优先 3.11 / 3.12（onnxruntime 与 opencv 的轮子最齐全）
    def rank(item: Tuple[Tuple[int, int, int], str]) -> int:
        version = item[0]
        if version[:2] in ((3, 11), (3, 12)):
            return 0
        if version[:2] in ((3, 10), (3, 13), (3, 9)):
            return 1
        return 2
    usable.sort(key=lambda item: (rank(item), -item[0][0], -item[0][1]))
    return usable[0][1]


def install_homebrew_python() -> Optional[str]:
    """macOS 上没有 Python 时，尝试用 homebrew 装一个。"""
    if sys.platform != "darwin":
        return None
    brew = shutil.which("brew") or ("/opt/homebrew/bin/brew" if os.path.exists("/opt/homebrew/bin/brew") else None)
    if not brew:
        return None
    print("[i] 没找到 Python，正在用 Homebrew 安装 python@3.12（可能要几分钟）…")
    try:
        subprocess.run([brew, "install", "python@3.12"], check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[!] Homebrew 安装失败：{exc}")
        return None
    exe = shutil.which("python3.12") or "/opt/homebrew/bin/python3.12"
    return exe if shutil.which("python3.12") or os.path.exists(exe) else None


# --------------------------------------------------------------------------- #
# 虚拟环境
# --------------------------------------------------------------------------- #

def create_venv(base_python: str, *, force: bool = False) -> bool:
    venv = venv_dir()
    if force and venv.exists():
        print(f"[i] 删除旧虚拟环境：{venv}")
        shutil.rmtree(venv, ignore_errors=True)
    if venv_python(venv).exists():
        return True
    print(f"[i] 创建虚拟环境：{venv}")
    result = subprocess.run([base_python, "-m", "venv", str(venv)])
    if result.returncode != 0 or not venv_python(venv).exists():
        print("[!] 虚拟环境创建失败，改用系统 Python 直接安装（不推荐但能用）")
        return False
    return True


# 单次 pip install 的上限。超过就认为这一次尝试废了，换源重试；绝不无限等下去
# （曾经遇到过 pip 写缓存时静默卡死十几分钟，所以下面还固定加 --no-cache-dir）。
INSTALL_TIMEOUT = 600

# pip 自己的网络参数：单次请求别等太久，卡住就断开重连，别让整个过程看着像死了。
PIP_NET_ARGS = ["--timeout", "20", "--retries", "2"]

# 实时显示进度时，如果连续这么久一行输出都没有，就认为这次连接卡死了，直接放弃
# （镜像站在本机出现过「连接被对端关闭后 pip 一直等、不再有任何输出」的情况）。
IDLE_TIMEOUT = 240


def _pip_once(
    exe: str,
    args: Sequence[str],
    index_url: Optional[str],
    *,
    quiet: bool = True,
    extra: Sequence[str] = (),
    echo: bool = False,
    timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """跑一次 pip install，返回 (是否成功, 失败原因)。

    echo=True：把 pip 的输出实时打出来（第一次装依赖时用，用户能看到进度），
    同时保留最后几十行，失败时用来解释原因。
    """
    limit = timeout or INSTALL_TIMEOUT
    cmd = [exe, "-u", "-m", "pip", "install", "--disable-pip-version-check"]
    if quiet:
        cmd.append("-q")
    cmd += _index_args(index_url)
    # 固定绕开 pip 的 HTTP 缓存：本机踩过「写缓存时静默卡死」，缓存对安装没有价值
    cmd.append("--no-cache-dir")
    cmd += PIP_NET_ARGS
    cmd += list(extra)
    cmd += list(args)

    if not echo:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            return False, "安装超时（超过 %d 分钟没有任何结果）" % (limit // 60)
        except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "").strip()
        return True, ""

    tail: "collections.deque[str]" = collections.deque(maxlen=40)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(project_root()),
        )
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        return False, str(exc)

    alive = {"at": time.monotonic()}

    def _pump() -> None:
        stream = proc.stdout
        if stream is None:
            return
        for raw in stream:
            line = raw.rstrip()
            if not line:
                continue
            alive["at"] = time.monotonic()
            tail.append(line)
            print("    " + line)

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()

    # 一边等一边看有没有「卡住」：pip 还在吐字就继续等，长时间一声不吭就杀掉重试。
    deadline = time.monotonic() + limit
    while True:
        code = proc.poll()
        if code is not None:
            break
        now = time.monotonic()
        if now > deadline:
            proc.kill()
            pump.join(timeout=3)
            return False, "安装超时（超过 %d 分钟还没装完）" % (limit // 60)
        if now - alive["at"] > IDLE_TIMEOUT:
            proc.kill()
            pump.join(timeout=3)
            return False, "安装卡住了：连续 %d 秒没有任何进度输出（多半是源连不通）" % IDLE_TIMEOUT
        time.sleep(0.5)
    pump.join(timeout=5)
    if code != 0:
        return False, "\n".join(tail)
    return True, ""


def _source_label(url: Optional[str]) -> str:
    if not url:
        return "官方源"
    if "tuna" in url:
        return "清华镜像"
    return url.split("://", 1)[-1].split("/", 1)[0]


def _spec_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[]", spec, 1)[0].strip() or spec


def pip_install(
    exe: str,
    args: Sequence[str],
    *,
    quiet: bool = True,
    echo: bool = False,
) -> bool:
    """装包。镜像源（快）-> 官方源（稳），每个源试一次。

    每次都带 --no-cache-dir：本机遇到过 pip 写 HTTP 缓存时静默卡死。
    echo=True 时把 pip 的输出实时显示出来（第一次装依赖，用户能看到进度）。
    """
    mirror = mirror_url()
    attempts: List[Optional[str]] = ([mirror] if mirror else []) + [None]

    last_err = ""
    for idx, url in enumerate(attempts):
        if idx:
            print("[~] 这个源没装上，换个源重试…")
        print("[i] 正在安装（%s，%d 个包）：%s" % (
            _source_label(url), len(args), "、".join(_spec_name(a) for a in args)))
        print("    pip 的输出会实时显示在下面；下载大包（opencv 等）时会安静一会儿。")
        started = time.time()
        ok, err = _pip_once(exe, args, url, quiet=quiet, echo=echo)
        if ok:
            print("[✓] 安装完成，用了 %.0f 秒" % (time.time() - started))
            return True
        last_err = err
        print("[!] 这次没成功，用了 %.0f 秒" % (time.time() - started))
    tail = last_err.strip().splitlines()
    print("[!] 安装失败：" + ("\n    ".join(tail[-8:]) if tail else "未知错误"))
    return False


def _pip_version(exe: str) -> Optional[Tuple[int, ...]]:
    """读这个解释器里 pip 的版本号；读不到就返回 None。"""
    try:
        result = subprocess.run([exe, "-u", "-m", "pip", "--version"],
                                capture_output=True, text=True, timeout=60,
                                cwd=str(project_root()))
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"pip\s+(\d+)\.(\d+)(?:\.(\d+))?", result.stdout or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def upgrade_pip(exe: str, *, timeout: int = 60) -> None:
    """升级 pip/setuptools/wheel。不是必需步骤：失败或超时就跳过，绝不卡住启动。"""
    url = mirror_url()
    started = time.time()
    print("[i] 升级 pip/setuptools/wheel（可选步骤，最多等 %d 秒）…" % timeout)
    cmd = [exe, "-u", "-m", "pip", "install", "--disable-pip-version-check", "-q",
           "--no-cache-dir", "--timeout", "20", "--retries", "2",
           "--upgrade", "pip", "setuptools", "wheel"]
    cmd += _index_args(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                cwd=str(project_root()))
    except (OSError, subprocess.SubprocessError):
        print("[i] pip 没升级成功（不影响安装，继续）")
        return
    if result.returncode == 0:
        print("[i] pip 升级完成，用了 %.0f 秒" % (time.time() - started))
    else:
        print("[i] pip 没升级成功（不影响安装，继续）")


def read_requirements() -> List[str]:
    """读 requirements.txt，顺手把注释和行内注释去掉。

    注意：这个文件必须保持纯 ASCII。Windows/部分中文 locale 下 pip 会用
    GBK 解码 requirements.txt，文件里只要有中文注释就会直接报
    UnicodeDecodeError: 'gbk' codec can't decode ...（实测踩过）。
    注释一律写英文。
    """
    path = project_root() / "requirements.txt"
    specs: List[str] = []
    if not path.exists():
        return specs
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    for raw in raw_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # 去掉行内注释：spec 里的 # 只可能出现在注释里，环境标记用 ';' 不受影响
        line = re.sub(r"\s+#.*$", "", line).strip()
        if line:
            specs.append(line)
    return specs


def env_report() -> Dict[str, object]:
    required_missing = [spec for module, spec in REQUIRED_PACKAGES if not package_installed(module)]
    optional_missing = optional_missing_list()
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "venv": str(venv_dir()),
        "in_venv": in_venv(),
        "required_missing": required_missing,
        "optional_missing": optional_missing,
    }


PIP_TEMP_PATTERNS = (
    "pip-build-tracker-*",
    "pip-install-*",
    "pip-unpack-*",
    "pip-download-*",
    "pip-ephem-wheel-cache-*",
    "pip-req-build-*",
    "pip-modern-metadata-*",
)


def sweep_pip_temp(*, min_age: float = 20.0) -> int:
    """清掉 pip 留在项目目录里的临时文件夹，返回删掉几个。

    pip 的临时目录本该自己删，但 Windows 上常常被占着删不掉（杀毒软件还开着文件）；
    而某些环境里 %TEMP% 对子进程不可写，Python 会把临时目录退到「当前目录」，
    也就是项目根。只删 20 秒没被动过的，免得误删正在跑的 pip 的目录。
    """
    root = project_root()
    now = time.time()
    removed = 0
    for pattern in PIP_TEMP_PATTERNS:
        for path in root.glob(pattern):
            try:
                if not path.is_dir() or now - path.stat().st_mtime < min_age:
                    continue
                shutil.rmtree(path)
                removed += 1
            except OSError:
                continue
    return removed


def install_dependencies(exe: str, *, verbose: bool = False) -> bool:
    specs = read_requirements()
    if not specs:
        specs = [spec for _, spec in REQUIRED_PACKAGES]
    # 只有自带 pip 太老（比如 Python 3.9 里的 pip 20.2.3）才值得升；新版 Python 自带的
    # pip 已经够用，这一步又慢又容易卡在源上，能省就省。
    current = _pip_version(exe)
    if current is not None and current < (23, 0):
        print("[i] 自带的 pip 有点老（%s），先升级一下…" % ".".join(str(p) for p in current))
        upgrade_pip(exe)
    ok = True
    # 先装必须的，再单独试可选的（网络受限时不要连累必须的）
    required = [spec for spec in specs if not _is_optional_spec(spec)]
    optional = [spec for spec in specs if _is_optional_spec(spec)]

    if required and not pip_install(exe, required, quiet=False, echo=True):
        print("[!] 一次性安装没成功，改成逐个装，看看到底是哪个包的问题")
        ok = False
        for spec in required:
            if pip_install(exe, [spec], quiet=False, echo=True):
                if not any(not package_installed(module) for module, _ in REQUIRED_PACKAGES):
                    ok = True
    for spec in optional:
        if not pip_install(exe, [spec]):
            print(f"[~] 可选依赖 {spec} 没装上，跳过（会自动使用其他 OCR 引擎）")
    gone = sweep_pip_temp()
    if gone:
        print("[i] 顺手清理了 %d 个 pip 临时文件夹" % gone)
    return ok


def _is_optional_spec(spec: str) -> bool:
    name = re.split(r"[<>=!~;\[]", spec, 1)[0].strip().lower()
    return name in {
        "rapidocr-onnxruntime", "rapidocr", "onnxruntime",
        "pyobjc-framework-vision", "pyobjc-framework-quartz", "pytesseract",
    }


def touch_stamp() -> None:
    try:
        import json

        stamp = project_root() / STAMP_FILENAME
        stamp.write_text(json.dumps({
            "python": sys.version.split()[0],
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def ensure_environment(*, force_reinstall: bool = False, quiet: bool = False) -> int:
    """确保当前正在一个依赖齐全的虚拟环境里跑。返回进程退出码（0 = 继续）。"""
    if not in_venv():
        return _bootstrap_into_venv(force_reinstall=force_reinstall)

    report = env_report()
    if not quiet:
        print(f"[i] Python {report['python']} @ {report['executable']}")

    missing = report["required_missing"]
    needs_install = force_reinstall or bool(missing)
    if missing:
        print("[!] 缺少运行依赖：" + "、".join(missing))

    if needs_install:
        if not install_dependencies(sys.executable, verbose=True):
            print("[!] 依赖没装全，仍会尝试启动（功能可能不全）")
        touch_stamp()
        report = env_report()
        missing = report["required_missing"]
        if missing:
            print("[✗] 这些依赖还是没装上：" + "、".join(missing))
            print("    常见原因：网络不通 / 公司代理拦截。可以手动执行：")
            print(f"    {sys.executable} -m pip install -r {project_root() / 'requirements.txt'}")
            return 2
        print("[✓] 依赖已就绪")

    if not quiet:
        try:
            from bidbook import ocr as ocr_mod

            print("[i] OCR 引擎：" + ocr_mod.resolve_engine("auto"))
        except Exception:  # noqa: BLE001
            print("[!] 现在没有任何可用的 OCR 引擎，识别表格会失败。")
            print("    自动修一下：bash run.sh --doctor")
    # 以前跑失败的 pip 可能在项目目录里留下 pip-xxxx 临时文件夹，顺手收拾掉
    sweep_pip_temp()
    return 0


def _bootstrap_into_venv(*, force_reinstall: bool) -> int:
    """不在虚拟环境里时：找/建 venv，然后用 venv 里的 Python 重新跑自己。"""
    venv = venv_dir()
    exe = venv_python(venv)
    if force_reinstall or not exe.exists():
        base = sys.executable if sys.version_info[:2] >= MIN_PY else (pick_interpreter() or "")
        if not base:
            base = install_homebrew_python() or ""
        if not base:
            print("[✗] 没找到可用的 Python（需要 3.9 及以上）。")
            print("    macOS 上可以执行：brew install python@3.12")
            print("    或者到 https://www.python.org/downloads/macos/ 下载安装。")
            return 3
        version = interpreter_version(base)
        print(f"[i] 使用解释器：{base}（{(version and '.'.join(map(str, version))) or '未知版本'}）")
        if not create_venv(base, force=force_reinstall):
            print("[!] 没有虚拟环境，直接用当前解释器继续")
            return ensure_environment(force_reinstall=force_reinstall)
    else:
        print(f"[i] 复用已有虚拟环境：{venv}")

    if not exe.exists():
        return ensure_environment(force_reinstall=force_reinstall)

    print("[i] 在虚拟环境里重新启动…")
    args = [str(exe), "-u", str(project_root() / "app.py"), *sys.argv[1:]]
    env = dict(os.environ)
    env["BIDBOOK_CHILD"] = "1"
    try:
        completed = subprocess.run(args, env=env, cwd=str(project_root()))
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        # 典型情形：.venv 是用另一个版本的 Python 建的，或者被系统清理工具删了半截。
        # 自己修一次：删掉重建，不行再报错让人工介入。
        print(f"[!] 虚拟环境里的 Python 起不来（{exc}），自动重建一次…")
        if not create_venv(sys.executable, force=True):
            print("[✗] 虚拟环境重建失败。")
            print(f"    请手动删掉 {venv_dir()} 这个文件夹，然后重新运行本脚本。")
            return 4
        print("[i] 重建完成，再启动一次…")
        try:
            completed = subprocess.run(args, env=env, cwd=str(project_root()))
        except OSError as exc2:
            print(f"[✗] 重建后仍然起不来：{exc2}")
            print(f"    请手动删掉 {venv_dir()} 这个文件夹，然后重新运行本脚本。")
            return 4
    return completed.returncode


def repair_ocr_engines(*, verbose: bool = True) -> bool:
    """一个 OCR 引擎都没有时，自己试着装一个（能修就修）。"""
    from bidbook import ocr as ocr_mod

    try:
        ocr_mod.resolve_engine("auto")
        return True
    except Exception:  # noqa: BLE001
        pass

    if verbose:
        print("[i] 还没有可用的 OCR 引擎，尝试自动安装 RapidOCR 中文模型…")
    specs = ["rapidocr-onnxruntime>=1.3.24,<2", "onnxruntime>=1.17,<2"]
    if sys.platform == "darwin":
        specs += ["pyobjc-framework-Vision>=10.0,<12", "pyobjc-framework-Quartz>=10.0,<12"]
    pip_install(sys.executable, specs, quiet=False, echo=True)
    try:
        resolved = ocr_mod.resolve_engine("auto")
        if verbose:
            print(f"[✓] 已装好，会自动使用：{resolved}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 自动安装没成功：{exc}")
        return False


def doctor() -> int:
    """自检 + 自动修复。"""
    print("=" * 58)
    print("  投标簿记工具 · 环境自检")
    print("=" * 58)
    report = env_report()
    if not report["in_venv"]:
        print("[!] 当前不在虚拟环境里，请先用 run.sh 启动；下面按系统环境自检。")
    print(f"Python      : {report['python']}  ({report['executable']})")
    print(f"虚拟环境    : {report['venv']}（{'已启用' if report['in_venv'] else '未启用'}）")
    code = ensure_environment()
    if code != 0:
        return code

    from bidbook import ocr as ocr_mod

    print("\nOCR 引擎状态：")
    for engine in ocr_mod.available_engines():
        mark = "✓" if engine["available"] else "✗"
        print(f"  {mark} {engine['label']}  —— {engine['note']}")
    try:
        resolved = ocr_mod.resolve_engine("auto")
        print(f"\n[✓] 会自动使用：{resolved}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[✗] 没有可用 OCR 引擎：{exc}")
        if not repair_ocr_engines():
            print("    也可以手工装：")
            print("      brew install tesseract tesseract-lang     （macOS）")
            print("      pip install rapidocr-onnxruntime onnxruntime")
            return 4

    print("\n配置：")
    try:
        import cv2

        print(f"  opencv {cv2.__version__}")
    except Exception:  # noqa: BLE001
        pass
    print("  四个输出时点：17:30 / 17:40 / 17:50 / 18:00（18:00 记为最终边际）")
    print("\n[✓] 自检通过")
    return 0
