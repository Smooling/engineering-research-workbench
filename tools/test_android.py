"""Exercise the embedded backend with private data, actual HTTP and a restart."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen, ProxyHandler, build_opener

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "android/app/src/main/python")]
import android_runtime


class AndroidRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.url = android_runtime.start(str(cls.root), str(REPO))
        cls.http = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        android_runtime._server.shutdown()
        android_runtime._thread.join(timeout=3)
        android_runtime._server.server_close()
        cls.temp.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with self.http.open(request, timeout=10) as response:
            return json.load(response)

    def test_private_data_and_packaged_assets(self):
        self.assertEqual(self.url, "http://127.0.0.1:8765")
        self.assertEqual(android_runtime.start("unused", "unused"), self.url)
        self.assertTrue(self.request("/api/health")["ok"])
        self.assertTrue((self.root / "Workspace/System").is_dir())
        self.assertFalse(self.request("/api/config")["app"]["auto_open_browser"])
        for path in ("/", "/android.js", "/android.css", "/vendor/pdf.min.js", "/vendor/pdf.worker.min.js"):
            with self.http.open(self.url + path, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_billing_parallel_first_open(self):
        # The mobile dashboard loads these together before a prices file exists.
        paths = ['/api/billing/summary', '/api/billing/prices', '/api/billing/records'] * 3
        with ThreadPoolExecutor(max_workers=9) as pool:
            results = list(pool.map(self.request, paths))
        self.assertTrue(all(isinstance(result, dict) for result in results))
        self.assertTrue(self.request('/api/billing/prices')['models'])

    def test_edit_restart_and_backup_preserve_metadata_without_keys(self):
        doc = self.request("/api/docs", {"kind": "note", "title": "Android 离线验证", "body": "手机本地笔记"})
        self.assertEqual(self.request("/api/docs/" + doc["id"])["body"].strip(), "手机本地笔记")
        matches = self.request("/api/docs?kind=note&q=" + quote("手机本地"))
        self.assertEqual(matches[0]["id"], doc["id"])
        self.request("/api/system/restart", {})
        deadline = time.monotonic() + 5
        while True:
            try:
                self.assertTrue(self.request("/api/health")["ok"])
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        self.assertEqual(self.request("/api/docs/" + doc["id"])["title"], "Android 离线验证")
        metadata = self.root / "Workspace/Knowledge/Literature/Index/library.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text('{"items":[]}', encoding="utf-8")
        secret = self.root / "config/secret.json"
        secret.write_text('{"api_key":"test-excluded"}', encoding="utf-8")
        destination = self.root / "backup.zip"
        android_runtime.export_backup(str(destination))
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
            self.assertIn("Workspace/Knowledge/Literature/Index/library.json", names)
            self.assertIn("config/app.json", names)
            self.assertFalse(any("secret" in name or "System/Cache/" in name or "System/Sync/" in name for name in names))
            self.assertTrue(any(name.endswith(".md") and "手机本地笔记" in archive.read(name).decode() for name in names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
