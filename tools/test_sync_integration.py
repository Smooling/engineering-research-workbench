"""Full server processes with isolated data directories, including real index refresh."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


class SyncIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='erw-sync-server-')
        self.processes = []
        self.urls = []
        for n in ('local', 'remote'):
            data = Path(self.temp.name) / n
            (data / 'config').mkdir(parents=True)
            config = {'app_name':'Sync test', 'workspace':'Workspace', 'host':'127.0.0.1', 'auto_open_browser':False,
                      'workspace_migration':{'enabled':False}, 'weather':{'enabled':False}, 'llm':{'enabled':False}}
            (data / 'config/app.json').write_text(json.dumps(config), encoding='utf-8')
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            code = "from pathlib import Path; import sys; from app import paths; paths.DATA_ROOT=Path(sys.argv[1]); import server; http,_,_=server.build_server(port_override=int(sys.argv[2]),auto_open_browser=False); http.serve_forever(poll_interval=.1)"
            process = subprocess.Popen([sys.executable, '-c', code, str(data), str(port)], cwd=ROOT,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.processes.append(process)
            url = f'http://127.0.0.1:{port}'
            self.urls.append(url)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    self.request(url, '/api/health')
                    break
                except Exception:
                    if process.poll() is not None:
                        self.fail('isolated server failed to start')
                    time.sleep(.05)
            else:
                self.fail('isolated server did not become ready')

    def tearDown(self):
        for process in self.processes:
            process.terminate()
            process.wait(10)
        self.temp.cleanup()

    @staticmethod
    def request(url, path, value=None):
        raw = json.dumps(value).encode('utf-8') if value is not None else None
        with urlopen(Request(url+path, data=raw, headers={'Content-Type':'application/json'}), timeout=10) as response:
            return json.loads(response.read())

    def wait_sync(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = self.request(self.urls[0], '/api/sync/status')
            if state['phase'] not in ('syncing', 'idle'):
                self.assertEqual(state['phase'], 'synced', state)
                return state
            time.sleep(.05)
        self.fail('sync did not finish')

    def test_saved_document_is_indexed_and_settings_reload_both_ways(self):
        a, b = self.urls
        self.request(a, '/api/sync/config', {'url':b, 'mode':'manual'})
        doc = self.request(a, '/api/docs', {'kind':'note', 'title':'Synchronized note', 'body':'# saved locally'})
        self.request(a, '/api/sync/run', {})
        self.wait_sync()
        remote = self.request(b, '/api/docs/'+doc['id'])
        self.assertEqual(remote['body'].strip(), '# saved locally')
        self.assertTrue(any(r['id']==doc['id'] for r in self.request(b, '/api/docs?kind=note')))
        self.request(b, '/api/docs/'+doc['id'], {'body':'# edited on the webpage'})
        cfg = self.request(b, '/api/config')['app']
        cfg['app_name'] = 'Remote edited name'
        self.request(b, '/api/config/app', cfg)
        self.request(a, '/api/sync/run', {})
        self.wait_sync()
        local = self.request(a, '/api/docs/'+doc['id'])
        self.assertIn('edited on the webpage', local['body'])
        self.assertEqual(self.request(a, '/api/config')['app']['app_name'], 'Remote edited name')
        self.assertNotEqual(self.request(a, '/api/sync/status')['instance'], self.request(b, '/api/sync/status')['instance'])

    def test_automatic_sync_runs_without_a_browser_window(self):
        a,b = self.urls
        doc = self.request(a, '/api/docs', {'kind':'note', 'title':'Background note', 'body':'Background saved material'})
        self.request(a, '/api/sync/config', {'url':b, 'mode':'auto', 'interval':10})
        self.wait_sync()
        self.assertIn('Background saved material', self.request(b, '/api/docs/'+doc['id'])['body'])

    def test_activity_heatmaps_match_after_bidirectional_web_edits_and_repeated_sync(self):
        a, b = self.urls
        for url, title in ((a, 'Local work'), (b, 'Remote work')):
            doc = self.request(url, '/api/docs', {'kind':'note', 'title':title, 'body':'First result'})
            self.request(url, '/api/docs/'+doc['id'], {'body':'Edited result'})
        local = self.request(a, '/api/dashboard')['activity']
        self.assertGreater(local['events_month'], 0)
        self.request(a, '/api/sync/config', {'url':b, 'mode':'manual'})
        for _ in range(2):
            self.request(a, '/api/sync/run', {})
            self.wait_sync()
            left = self.request(a, '/api/dashboard')['activity']
            right = self.request(b, '/api/dashboard')['activity']
            self.assertEqual(left, right)
            self.assertEqual(left['events_month'], local['events_month'] * 2)

    def test_billing_first_load_concurrent_endpoints(self):
        routes = ['/api/billing/summary', '/api/billing/prices', '/api/billing/records'] * 8
        with ThreadPoolExecutor(12) as pool:
            results = list(pool.map(lambda route: self.request(self.urls[0], route), routes))
        self.assertEqual(results[0]['total']['calls'], 0)
        self.assertEqual(results[1]['currency'], 'USD')
        self.assertEqual(results[2]['total'], 0)


if __name__ == '__main__':
    unittest.main()
