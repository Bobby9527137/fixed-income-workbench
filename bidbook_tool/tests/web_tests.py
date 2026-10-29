# -*- coding: utf-8 -*-
"""网页层自测：自己起一个本地服务，打真实的 HTTP 请求，确认接口没坏。

跑法（项目根目录下）：
    python3 tests/web_tests.py

它会挑一个空闲端口启动 app.py，测完把它关掉。需要 fastapi/uvicorn（requirements.txt 里有），
不需要 OCR 引擎：识别那一步允许失败，但必须返回结构正确的 JSON，而不是 500。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import make_sample  # noqa: E402

PASSED = []
FAILED = []

PASTE = chr(10).join([
    "17:30 【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%",
    "17:40 【1.4-2.4】，26武清经开MTN008，2Y，1.6亿，AA+，10-12 簿记，10-13 缴款",
    "17:50 【1.5-2.5】，26武清经开MTN009，2Y，1.7亿，AA+，10-12 簿记，10-13 缴款",
    "18:00 【1.6-2.6】，26天津城投CP001，1Y，2.0亿，AAA，10-12 簿记，10-14 缴款，10-15 上市",
])

ROWS = [
    {"index": 1, "code": "042600007", "name": "26武清经开MTN007", "raw_name": "26武清经开MTN007",
     "margin_rate": 1.81, "full_ratio": 1.77, "edge_ratio": 2.00},
    {"index": 2, "code": "042600008", "name": "26武清经开MTN008", "raw_name": "26武清经开MTN008",
     "margin_rate": 1.87, "full_ratio": 1.55, "edge_ratio": 1.40},
    {"index": 3, "code": "042600009", "name": "26武清经开MTN009", "raw_name": "26武清经开MTN009",
     "margin_rate": 1.95, "full_ratio": 2.30, "edge_ratio": 3.10},
    {"index": 4, "code": "012600001", "name": "26天津城投CP001", "raw_name": "26天津城投CP001",
     "margin_rate": 2.15, "full_ratio": 1.20, "edge_ratio": 1.00},
]

# 没有时间前缀的粘贴文本，用来测「按电脑时间自动判断」和手动指定
PASTE_NO_TIME = chr(10).join([
    "【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，10-12 簿记，10-13 缴款",
    "【1.6-2.6】，26天津城投CP001，1Y，2.0亿，AAA，10-12 簿记，10-14 缴款",
])

# 每行末尾都会跟上来源说明（【来源：截图匹配，匹配度…，匹配标的：…】）
LINE_FIRST = ("【1.3-2.3】26武清经开MTN007，2Y，1.5亿，AA+；目前边际1.81%，全场倍数1.77倍，边际倍数2.00倍。"
              + "【来源：截图匹配，匹配度1.00，匹配标的：26武清经开MTN007】")
LINE_LAST = ("【1.6-2.6】26天津城投CP001，1Y，2.0亿，AAA；最终边际2.15%，全场倍数1.20倍，边际倍数1.00倍。"
             + "【来源：截图匹配，匹配度1.00，匹配标的：26天津城投CP001】")


def check(name, ok, detail=""):
    if ok:
        PASSED.append(name)
        print("  ok   " + name)
    else:
        FAILED.append(name)
        print("  FAIL " + name + (("   -> " + str(detail)) if detail else ""))


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def wait_port(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def http(method: str, url: str, payload=None, timeout: float = 90.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def body_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def main() -> int:
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    log = tempfile.NamedTemporaryFile(prefix="bidbook-web-", suffix=".log", delete=False)
    print("[1] 启动服务 %s" % base)
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py", "--host", "127.0.0.1", "--port", str(port),
         "--no-browser", "--no-warmup"],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    sample_dir = None
    try:
        if not wait_port(port):
            proc.terminate()
            print("服务没起来，日志：")
            print(Path(log.name).read_text(encoding="utf-8", errors="replace")[-3000:])
            return 1

        print("[2] 首页与配置")
        status, html = http("GET", base + "/")
        check("GET / 返回 200", status == 200, status)
        check("首页里有交互元素", ("债券简称" in html) and ("<select" in html or "select" in html), len(html))

        status, raw = http("GET", base + "/api/config")
        cfg = body_json(raw) or {}
        check("GET /api/config 返回 JSON", status == 200 and bool(cfg), status)
        check("15 列表头齐全", len(cfg.get("headers") or []) == 15, cfg.get("headers"))
        check("需要 3 列", list(cfg.get("needed") or []) == ["边际利率/价格", "全场倍数", "边际倍数"], cfg.get("needed"))
        check("四个时点", list(cfg.get("time_slots") or []) == ["17:30", "17:40", "17:50", "18:00"], cfg.get("time_slots"))
        check("18:00 是最终时点", cfg.get("final_slot") == "18:00", cfg.get("final_slot"))
        check("时点选择是三项（自动/目前/最终）",
              [c.get("key") for c in (cfg.get("time_choices") or [])] == ["auto", "current", "final"],
              cfg.get("time_choices"))
        check("配置里带了电脑时间与判断结果",
              (cfg.get("server_time") or {}).get("mode") in ("目前边际", "最终边际"), cfg.get("server_time"))
        check("默认就是自动", cfg.get("default_time_choice") == "auto", cfg.get("default_time_choice"))
        check("默认匹配门槛是 0.90", cfg.get("default_threshold") == 0.90, cfg.get("default_threshold"))
        check("门槛滑块范围 0.70~0.98",
              cfg.get("threshold_min") == 0.70 and cfg.get("threshold_max") == 0.98,
              (cfg.get("threshold_min"), cfg.get("threshold_max")))
        check("窗口 2 的黑名单里含「簿记」",
              "簿记" in (cfg.get("value_blacklist") or []), cfg.get("value_blacklist"))
        check("拒绝提示文案不是空的", bool(cfg.get("value_reject_message")), cfg.get("value_reject_message"))

        print("[3] POST /api/build 拼文案")
        status, raw = http("POST", base + "/api/build", {
            "text": PASTE, "rows": ROWS, "default_time": "17:30", "overrides": {}, "threshold": 0.90,
        })
        data = body_json(raw) or {}
        check("build 返回 200 且 ok", status == 200 and data.get("ok") is True, raw[:300])
        lines = str(data.get("text") or "").split(chr(10))
        check("输出 4 行", len(lines) == 4 and data.get("count") == 4, lines)
        check("第一行逐字符正确", lines[0] == LINE_FIRST if lines else False, lines[0] if lines else "")
        check("第四行用最终边际", lines[3] == LINE_LAST if len(lines) > 3 else False, lines[3] if len(lines) > 3 else "")
        got = [(r.get("table") or {}).get("index") for r in (data.get("results") or [])]
        check("全部匹配到表格行", all(r.get("table") for r in (data.get("results") or [])), got)
        check("配对到正确的表格行号", got == [1, 2, 3, 4], got)

        print("[3c] 没有一一对应的数据 / 第二个窗口（边际数据）")
        EXTRA = "【9.9-9.9】，26根本不在表里的ZZ999，1Y，1亿，AA，10-13 簿记"
        text_extra = PASTE + chr(10) + EXTRA
        status, raw = http("POST", base + "/api/build", {
            "text": text_extra, "rows": ROWS, "default_time": "17:30", "threshold": 0.90,
        })
        data = body_json(raw) or {}
        out = str(data.get("text") or "")
        check("没配上的也出一行，三个数写待定",
              "【9.9-9.9】26根本不在表里的ZZ999，1Y，1亿，AA；目前边际待定，全场倍数待定，边际倍数待定。" in out,
              out[-220:])
        check("count 数所有成文的行", data.get("count") == 5, data.get("count"))
        check("no_data_count 报出没配上的行数", data.get("no_data_count") == 1, data.get("no_data_count"))
        check("pending_count 报出有待定的行数", data.get("pending_count") == 1, data.get("pending_count"))
        reasons = [r.get("review_reason") for r in (data.get("results") or [])]
        check("写明「没有对应的数据」", any("没有对应的数据" in str(x) for x in reasons), reasons)
        pends = [r.get("pending") for r in (data.get("results") or [])]
        check("pending 报出缺的是哪几项", ["边际利率/价格", "全场倍数", "边际倍数"] in pends, pends)
        check("配上的那行照样输出", LINE_FIRST in out, out[:160])

        status, raw = http("POST", base + "/api/build", {
            "text": text_extra, "rows": ROWS, "default_time": "17:30", "threshold": 0.90,
            "values_text": "26根本不在表里的ZZ999 3.30 1.11 5.00",
        })
        data = body_json(raw) or {}
        out = str(data.get("text") or "")
        check("窗口 2 给数后这行也成文",
              "【9.9-9.9】26根本不在表里的ZZ999，1Y，1亿，AA；目前边际3.30%，全场倍数1.11倍，边际倍数5.00倍。" in out,
              out[-200:])
        check("count 变成 5、没有缺数据的行了",
              data.get("count") == 5 and data.get("no_data_count") == 0
              and data.get("pending_count") == 0,
              (data.get("count"), data.get("no_data_count"), data.get("pending_count")))
        status, raw = http("POST", base + "/api/build", {
            "text": text_extra, "rows": ROWS, "default_time": "17:30", "threshold": 0.90,
            "values_text": "26根本不在表里的ZZ999 1.75-1.95",
        })
        data = body_json(raw) or {}
        out = str(data.get("text") or "")
        check("窗口 2 给的是范围 → 取上限，没给的写待定",
              "【9.9-9.9】26根本不在表里的ZZ999，1Y，1亿，AA；目前边际1.95%，全场倍数待定，边际倍数待定。" in out,
              out[-220:])
        check("这行只缺两项", data.get("pending_count") == 1, data.get("pending_count"))
        check("value_count 报出窗口 2 认出的行数", data.get("value_count") == 1, data.get("value_count"))
        srcs = [r.get("values_source") for r in (data.get("results") or [])]
        check("并标明这行的数来自窗口 2", "文本" in srcs, srcs)

        status, raw = http("POST", base + "/api/build", {
            "text": text_extra, "rows": ROWS, "default_time": "17:30", "threshold": 0.90,
            "values_text": "26武清经开MTN007 边际9.99% 全场1.77倍 边际倍数2.00倍" + chr(10) + "1.81 1.77 2.00",
        })
        data = body_json(raw) or {}
        out = str(data.get("text") or "")
        check("两边都有时以截图为准", "目前边际1.81%" in out and "9.99" not in out, out[:160])
        notes = [str(n) for r in (data.get("results") or [])
                 for n in ((r.get("input") or {}).get("notes") or [])]
        check("打架会在结果里提醒", any("和截图不一样" in n for n in notes), notes)
        check("窗口 2 里没简称的行会被报出来",
              list(data.get("value_problems") or []) == ["1.81 1.77 2.00"], data.get("value_problems"))

        print("[3d] 修复回归：简称别配错（路径A）")
        status, raw = http("POST", base + "/api/build", {
            "text": "【1.3-2.3】，26武清经开MTN099，2Y，1.5亿，AA+，10-12 簿记", "rows": ROWS,
            "default_time": "17:30", "threshold": 0.90,
        })
        data = body_json(raw) or {}
        out = str(data.get("text") or "")
        res0 = (data.get("results") or [{}])[0]
        check("表里没有的期数不许配到别人的行（路径A）",
              res0.get("table") is None and "目前边际待定" in out and "1.95" not in out, out)
        check("行末写明来源", "【来源：" in out, out)

        print("[3e] 修复回归：整段簿记文本别当边际数据（路径B）")
        full_row = ("【1.3-2.3】，26武清经开MTN007，2Y，1.5亿，AA+，"
                    "10-12 簿记，10-13 缴款，10-14 上市，1k，1.81 10%")
        status, raw = http("POST", base + "/api/build", {
            "text": text_extra, "rows": ROWS, "default_time": "17:30", "threshold": 0.90,
            "values_text": full_row,
        })
        data = body_json(raw) or {}
        out = str(data.get("text") or "")
        check("后端点名拒绝窗口 2 的整段簿记文本", data.get("values_rejected") == "簿记", raw[:200])
        check("并给出可读的拒绝原因",
              "窗口" in str(data.get("values_error") or ""), data.get("values_error"))
        check("窗口 2 一行都没解析", data.get("value_count") == 0, data.get("value_count"))
        check("不出日期假数（12.00% / 13.00）", "12.00%" not in out and "13.00" not in out, out[-220:])
        check("该行照样出、写待定", "目前边际待定" in out, out[-220:])

        print("[3b] 时点：按电脑时间自动 / 手动指定")
        status, raw = http("POST", base + "/api/build", {
            "text": PASTE_NO_TIME, "rows": ROWS, "default_time": "auto", "threshold": 0.90,
        })
        data = body_json(raw) or {}
        check("auto 返回实际用的时点", data.get("time_slot") in ["17:30", "17:40", "17:50", "18:00"], raw[:200])
        check("auto 的模式跟着时点走",
              (data.get("mode") == "最终边际") == (data.get("time_slot") == "18:00"), data.get("mode"))

        status, raw = http("POST", base + "/api/build", {
            "text": PASTE_NO_TIME, "rows": ROWS, "default_time": "final", "threshold": 0.90,
        })
        data = body_json(raw) or {}
        check("手动选最终边际 → 18:00", data.get("time_slot") == "18:00" and data.get("mode") == "最终边际", raw[:200])
        check("文案里写的是最终边际", "最终边际1.81%" in str(data.get("text") or ""), str(data.get("text"))[:120])

        status, raw = http("POST", base + "/api/build", {
            "text": PASTE_NO_TIME, "rows": ROWS, "default_time": "current", "threshold": 0.90,
        })
        data = body_json(raw) or {}
        check("手动选目前边际（永远不是 18:00）",
              data.get("mode") == "目前边际" and data.get("time_slot") in ["17:30", "17:40", "17:50"],
              data.get("time_slot"))
        check("文案里写的是目前边际", "目前边际1.81%" in str(data.get("text") or ""), str(data.get("text"))[:120])

        print("[4] 人工改数（overrides 用表格行号）")
        status, raw = http("POST", base + "/api/build", {
            "text": PASTE, "rows": ROWS, "default_time": "17:30",
            "overrides": {"1": {"margin_rate": "1.99", "full_ratio": "9.99"}}, "threshold": 0.90,
        })
        data = body_json(raw) or {}
        first = (str(data.get("text") or "").split(chr(10)) or [""])[0]
        check("改数生效", "目前边际1.99%" in first and "全场倍数9.99倍" in first, first)

        print("[5] 垃圾文本要被挡住")
        status, raw = http("POST", base + "/api/build", {"text": "这是一行说明文字，没有债券", "rows": ROWS})
        check("没有债券行时返回 400", status == 400, status)

        print("[6] POST /api/recognize 走一遍上传")
        sample_dir = Path(tempfile.mkdtemp(prefix="bidbook_webtest_"))
        sample = sample_dir / "bidbook_web_sample.png"
        make_sample.build(str(sample))
        b64 = base64.b64encode(sample.read_bytes()).decode("ascii")
        status, raw = http("POST", base + "/api/recognize", {
            "engine": "auto", "guess_columns": True,
            "images": [{"name": "sample_table.png", "data_url": "data:image/png;base64," + b64}],
        })
        data = body_json(raw) or {}
        check("recognize 返回 200 且 ok", status == 200 and data.get("ok") is True, raw[:300])
        imgs = data.get("images") or [{}]
        item = imgs[0] if imgs else {}
        if item.get("ok"):
            cols = [c.get("header_map") for c in (item.get("table", {}).get("columns") or [])]
            check("识别出表格结构", bool(item.get("table")), item.get("engine"))
            check("认出了边际/倍数三列",
                  set(item.get("table", {}).get("header_map") or []) >= {"边际利率/价格", "全场倍数", "边际倍数"},
                  item.get("table", {}).get("header_map"))
            print("       （本机 OCR 引擎：" + str(item.get("engine")) + "，文字块 " + str(item.get("text_count")) + " 个）")
        else:
            print("       本机没有可用的 OCR 引擎，跳过结构检查：" + str(item.get("error")))
            check("没引擎时给出可读错误而不是 500", status == 200 and bool(item.get("error")), raw[:200])

        print("[7] 整条链路：识别结果直接喂给 /api/build")
        if item.get("ok") and (item.get("table") or {}).get("rows"):
            ocr_rows = []
            for n, r in enumerate(item["table"]["rows"], start=1):
                ocr_rows.append({
                    "index": r.get("index") or n,
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "raw_name": r.get("raw_name"),
                    "margin_rate": r.get("margin_rate"),
                    "full_ratio": r.get("full_ratio"),
                    "edge_ratio": r.get("edge_ratio"),
                })
            status, raw = http("POST", base + "/api/build", {
                "text": PASTE, "rows": ocr_rows, "default_time": "17:30",
            })
            data = body_json(raw) or {}
            lines2 = str(data.get("text") or "").split(chr(10))
            check("整条链路出 4 行", len(lines2) == 4 and data.get("count") == 4, lines2)
            check("整条链路文案逐字符正确",
                  bool(lines2) and lines2[0] == LINE_FIRST and len(lines2) > 3 and lines2[3] == LINE_LAST, lines2)
        else:
            print("       本机识别没成功，跳过整链路检查")

        print("[8] 坏图片要被接住")
        status, raw = http("POST", base + "/api/recognize", {"images": ["数据不是base64"]})
        data = body_json(raw) or {}
        imgs = data.get("images") or [{}]
        check("坏图片返回 200 + 每图 error", status == 200 and data.get("ok") is True and bool((imgs[0] or {}).get("error")), raw[:200])
    finally:
        if sample_dir is not None:
            shutil.rmtree(sample_dir, ignore_errors=True)
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    print("")
    print("网页层自测：通过 %d 项，失败 %d 项" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("失败项：" + " / ".join(FAILED))
        print("服务日志：" + log.name)
        return 1
    # Windows 上子进程刚被杀掉时会短暂占用这个继承过去的句柄，
    # 所以关掉自己的句柄后再重试几次再放弃（删不掉也不影响测试结果）。
    for _ in range(10):
        try:
            log.close()
            os.unlink(log.name)
            break
        except OSError:
            time.sleep(0.2)
    print("网页层自测全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
