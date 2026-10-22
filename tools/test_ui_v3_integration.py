"""UI V3 merge regressions against a real, disposable server; no screenshots."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(data: Path) -> None:
    from app import paths
    paths.DATA_ROOT = data
    from server import build_server
    httpd, _, _ = build_server(auto_open_browser=False)
    try:
        httpd.serve_forever(poll_interval=0.1)
    finally:
        httpd.server_close()


class UiV3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socket
        from playwright.sync_api import sync_playwright
        from tools.ui_smoke import find_browser

        scratch = ROOT / '.scratch/verify'
        scratch.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='ui-v3-', dir=scratch)
        cls.data = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        config_dir = cls.data / 'config'
        config_dir.mkdir()
        (config_dir / 'app.json').write_text(json.dumps({
            'workspace': 'Workspace', 'port': port, 'auto_open_browser': False,
            'workspace_migration': {'enabled': False}, 'llm': {'enabled': False},
        }), encoding='utf-8')
        cls.url = f'http://127.0.0.1:{port}'
        cls.log = (cls.data / 'server.log').open('w', encoding='utf-8')
        cls.process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()),
                                       '--serve-data', str(cls.data)], cwd=ROOT,
                                      stdout=cls.log, stderr=subprocess.STDOUT,
                                      env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        cls.addClassCleanup(cls.close_server)
        for _ in range(100):
            try:
                with urlopen(cls.url + '/api/health', timeout=0.3):
                    break
            except OSError:
                if cls.process.poll() is not None:
                    raise RuntimeError((cls.data / 'server.log').read_text(encoding='utf-8'))
                time.sleep(0.1)
        else:
            raise RuntimeError('Disposable server did not become ready')
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True, executable_path=find_browser())
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def close_server(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.log.close()
        import shutil
        logs = ROOT / '.scratch/logs'
        logs.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cls.data / 'server.log', logs / 'ui-v3-integration.log')
        cls.temp.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1280, 'height': 800})
        self.addCleanup(self.page.close)

    def docs(self):
        with urlopen(self.url + '/api/docs?kind=note') as response:
            return json.load(response)

    def choose(self, choice):
        self.page.locator(f'[data-dialog-result="{choice}"]').click()
        self.page.locator('#workbench-dialog').wait_for(state='detached')

    def test_concurrent_billing_initialization(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        barrier = threading.Barrier(8)
        def read(index):
            barrier.wait(timeout=5)
            endpoint = 'prices' if index % 2 else 'summary'
            with urlopen(self.url + '/api/plugins/billing/' + endpoint, timeout=10) as response:
                return json.load(response)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(len(list(pool.map(read, range(8)))), 8)

    def test_draft_guards_failed_save_and_inflight_edits(self):
        p = self.page
        p.goto(self.url + '/#notes', wait_until='networkidle')
        p.locator('#new-doc').click()
        p.locator('[data-doc-draft]').wait_for()
        self.assertEqual(self.docs(), [])
        p.locator('#doc-save').click()
        self.assertEqual(self.docs(), [])
        p.locator('#f-title').fill('知识-方法-合并验收')
        p.locator('#md-input').fill('# 合并验收\n\n第一版')
        p.locator('[data-route="projects"]').click()
        self.choose('cancel')
        self.assertTrue(p.locator('#md-input').is_visible())
        self.assertEqual(self.docs(), [])
        p.locator('[data-route="projects"]').click()
        self.choose('save')
        p.wait_for_function("location.hash === '#projects'")
        self.assertEqual(len(self.docs()), 1)

        if not p.locator('[data-route="notes"]').is_visible():
            p.locator('[data-group-toggle="research"]').click()
        p.locator('[data-route="notes"]').click()
        p.locator('#md-input').wait_for()
        p.locator('#md-input').fill('保留未保存内容')
        p.route('**/api/docs/*', lambda route: route.fulfill(
            status=500, content_type='application/json', body='{"error":"injected failure"}')
            if route.request.method == 'POST' else route.continue_())
        p.locator('[data-route="projects"]').click()
        self.choose('save')
        p.wait_for_function("!document.querySelector('#doc-save').disabled")
        self.assertEqual(p.locator('#md-input').input_value(), '保留未保存内容')
        self.assertEqual(p.evaluate('location.hash'), '#notes')
        p.unroute('**/api/docs/*')

        p.locator('#md-input').fill('请求发出时的内容')
        held = []
        def delay(route):
            if route.request.method == 'POST':
                held.append(route)
            else:
                route.continue_()
        p.route('**/api/docs/*', delay)
        p.locator('#doc-save').click()
        p.wait_for_timeout(100)
        self.assertEqual(len(held), 1)
        p.locator('#md-input').fill('请求期间继续输入的内容')
        held[0].continue_()
        p.wait_for_function("!document.querySelector('#doc-save').disabled")
        self.assertEqual(p.locator('#md-input').input_value(), '请求期间继续输入的内容')
        self.assertTrue(p.evaluate('ERWDesktop.hasUnsavedChanges()'))
        p.unroute('**/api/docs/*')
        p.locator('[data-route="projects"]').click()
        self.choose('discard')
        p.wait_for_function("location.hash === '#projects'")
        self.assertEqual(len(self.docs()), 1)

    def test_native_bridge_chrome_theme_and_exit_guard(self):
        p = self.page
        p.add_init_script("""window.__nativeCalls=[];
          const state={title:'Test Workbench',maximized:false,hidden:false,close_action:'hide',tray_available:true};
          window.pywebview={api:{
            desktop_get_state:async()=>state,
            desktop_set_theme:async theme=>{window.__nativeCalls.push(['theme',theme]);return state},
            desktop_resolve_exit:async(...args)=>window.__nativeCalls.push(['exit',...args]),
            desktop_focus_state:async()=>({running:false,remaining:1500,total:1500,mode:'focus'})
          }};""")
        p.goto(self.url + '/#notes', wait_until='networkidle')
        p.wait_for_function("document.documentElement.dataset.desktop === 'true'")
        self.assertEqual(p.locator('#desktop-titlebar').count(), 1)
        self.assertEqual(p.locator('#desktop-titlebar #page-title').count(), 1)
        p.evaluate("document.documentElement.dataset.theme='dark'")
        p.wait_for_function("window.__nativeCalls.some(c=>c[0]==='theme'&&c[1]==='dark')")
        p.locator('#new-doc').click()
        p.locator('#md-input').fill('退出前需要确认的草稿')
        p.evaluate("void ERWDesktop.requestExit('test-token')")
        self.choose('cancel')
        p.wait_for_function("window.__nativeCalls.some(c=>c[0]==='exit'&&c[1]==='test-token'&&c[2]===false)")
        self.assertTrue(p.evaluate('ERWDesktop.hasUnsavedChanges()'))

    def test_routes_and_lazy_libraries(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/ui_smoke.py'),
                                 '--base-url', self.url, '--strict', '--json'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        print(json.dumps({'routes_checked': report['routes_checked'],
                          'console_errors': report['console_errors'],
                          'failed_requests': report['failed_requests'],
                          'heavy_libs_on_first_screen': report['heavy_libs_on_first_screen']}, ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve-data':
        serve(Path(sys.argv[2]).resolve())
    else:
        unittest.main()
