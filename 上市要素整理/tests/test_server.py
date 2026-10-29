from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import app


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str) -> tuple[int, bytes]:
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.read()

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health(self) -> None:
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_index(self) -> None:
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("上市要素整理".encode("utf-8"), body)

    def test_parse_endpoint(self) -> None:
        status, data = self._post(
            "/api/parse",
            {"text": "1029+0 上市要素：\n102683905.IB 26上饶产投MTN001 券面 100 票面 2.05% 净价 100 江城银行出给龙头证券 发江城银行请求\n江城银行 刘如烟 QT 2555555555\n龙头证券 陈默 QT 2555555556"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["fields"]["seller"], "江城银行")
        self.assertIn("发江城银行请求", data["output"])

    def test_mock_endpoint(self) -> None:
        status, body = self._get("/api/mock?seed=1")
        self.assertEqual(status, 200)
        text = json.loads(body)["text"]
        self.assertTrue("上市要素" in text or "出给" in text, text)

    def test_render_endpoint(self) -> None:
        fields = {
            "date": "1029",
            "offset": "+0",
            "code": "102683905.IB",
            "name": "26上饶产投MTN001",
            "face": "100",
            "coupon": "2.05%",
            "net": "100",
            "seller": "江城银行",
            "buyer": "龙头证券",
            "seller_contact": {"person": "刘如烟", "channel": "QT", "number": "2555555555"},
            "buyer_contact": {"person": "陈默", "channel": "QT", "number": "2555555556"},
        }
        status, data = self._post("/api/render", {"fields": fields})
        self.assertEqual(status, 200)
        self.assertTrue(data["output"].startswith("1029+0 上市要素："))


if __name__ == "__main__":
    unittest.main()
