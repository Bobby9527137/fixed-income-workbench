from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from fi_toolbox import selfcheck
from fi_toolbox.app import ToolApplication, _Server

ROOT = Path(__file__).resolve().parent.parent


def load_app(name: str):
    path = ROOT / "apps" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"server_app_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = load_app("bond_calculator")
        cls.module = module
        cls.app = ToolApplication(module.META, module.FIELDS, module.compute, module.sample)
        cls.httpd = _Server(("127.0.0.1", 0), cls.app)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.status, response.read()

    def post(self, path: str, payload: dict):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_meta(self) -> None:
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, body = self.get("/api/meta")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["meta"]["name"], "债券计算器")

    def test_sample_and_run(self) -> None:
        status, body = self.get("/api/sample")
        sample = json.loads(body)["data"]
        status, result = self.post("/api/run", sample)
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertTrue(result["metrics"])

    def test_invalid_input(self) -> None:
        sample = self.module.sample()
        sample["settle"] = "2040-01-01"
        status, result = self.post("/api/run", sample)
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertIn("结算日必须早于到期日", result["errors"])

    def test_selfcheck(self) -> None:
        status, body = self.get("/api/selfcheck?fix=1")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_excel_import(self) -> None:
        module = load_app("cashflow_calendar")
        app = ToolApplication(module.META, module.FIELDS, module.compute, module.sample)
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["代码", "名称", "面额(万元)", "票面(%)", "频率", "到期日", "下次付息日(可空)"])
        sheet.append(["2405253.IB", "24浙江债07", 5000, 2.36, 1, "2034-06-05", "2027-06-05"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        result = app.import_payload({
            "filename": "holdings.xlsx",
            "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "columns": module.FIELDS[-1]["columns"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["code"], "2405253.IB")


class ReportTest(unittest.TestCase):
    def test_report_is_written_locally(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, {selfcheck.REPORT_ENV: folder}):
                path = selfcheck.write_report(
                    tool_id="demo", meta={"name": "演示工具"},
                    checks=[{"name": "示例", "status": "failed", "detail": "坏了"}],
                    error="Traceback: boom",
                    context={"input": {"x": 1}},
                )
                self.assertTrue(path.is_file())
                text = path.read_text(encoding="utf-8")
                self.assertIn("问题报告", text)
                self.assertIn("本报告只保存在本机", text)
                self.assertIn("Traceback: boom", text)


if __name__ == "__main__":
    unittest.main()
