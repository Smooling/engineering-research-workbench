"""Billing initialization and Windows handle races, with disposable price tables."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import billing


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = patch.object(billing, '_dir', return_value=self.root)
        self.directory.start()
        self.cache = patch.object(billing, '_PRICE_CACHE', {'signature': None, 'data': None})
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        self.directory.stop()
        self.temp.cleanup()

    def test_first_page_parallel_reads_initialize_only_once(self):
        original = billing._write_json
        def delayed(path, value):
            time.sleep(.02)
            original(path, value)
        with patch.object(billing, '_write_json', side_effect=delayed) as write, ThreadPoolExecutor(12) as pool:
            calls = [pool.submit(fn) for fn in [billing.summary, billing.load_prices, billing.records] * 12]
            for call in calls:
                call.result(timeout=8)
            self.assertEqual(write.call_count, 1)
        self.assertEqual(json.loads(billing.prices_path().read_text(encoding='utf-8'))['currency'], 'USD')
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_parallel_saves_and_reads_preserve_ledger(self):
        ledger = b'{"ts":"2026-10-19","session_id":"s","model":"test","priced":true,"cost_usd":1.25}\n'
        billing.ledger_path().write_bytes(ledger)
        def operation(n):
            if n % 3 == 0:
                value = billing.default_prices()
                value['note'] = f'custom {n}'
                billing.save_prices(value)
            else:
                self.assertEqual(billing.summary()['total']['cost_usd'], 1.25)
        with ThreadPoolExecutor(12) as pool:
            list(pool.map(operation, range(60)))
        self.assertEqual(billing.ledger_path().read_bytes(), ledger)
        self.assertTrue(billing.load_prices()['note'].startswith('custom '))
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_cache_does_not_leak_across_equal_timestamp_workspaces(self):
        first = billing.load_prices()
        second = self.root / 'other'
        second.mkdir()
        value = dict(first, note='Different workspace')
        (second / 'prices.json').write_text(json.dumps(value), encoding='utf-8')
        stat = billing.prices_path().stat()
        os.utime(second / 'prices.json', ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with patch.object(billing, '_dir', return_value=second):
            self.assertEqual(billing.load_prices()['note'], value['note'])

    def test_transient_windows_share_error_retries_without_losing_previous_table(self):
        billing.load_prices()
        replace = os.replace
        attempts = []
        def locked_once(source, target):
            attempts.append(source)
            if len(attempts) == 1:
                error = PermissionError('sharing violation')
                error.winerror = 32
                raise error
            replace(source, target)
        with patch.object(billing.os, 'replace', side_effect=locked_once):
            billing.save_prices(dict(billing.default_prices(), note='Saved after retry'))
        self.assertEqual(billing.load_prices()['note'], 'Saved after retry')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_real_open_reader_can_finish_before_save_retries(self):
        billing.load_prices()
        reader = billing.prices_path().open('rb')
        closed = threading.Event()
        def release():
            time.sleep(.07)
            reader.close()
            closed.set()
        thread = threading.Thread(target=release)
        thread.start()
        try:
            billing.save_prices(dict(billing.default_prices(), note='Handle released'))
        finally:
            thread.join(3)
            reader.close()
        self.assertTrue(closed.is_set())
        self.assertEqual(billing.load_prices()['note'], 'Handle released')

    def test_persistent_write_failure_keeps_previous_prices_and_cleans_temp(self):
        previous = billing.load_prices()
        raw = billing.prices_path().read_bytes()
        error = PermissionError('still in use')
        error.winerror = 32
        with patch.object(billing.os, 'replace', side_effect=error), patch.object(billing.time, 'sleep'):
            with self.assertRaises(PermissionError):
                billing.save_prices(dict(previous, note='Not saved'))
        self.assertEqual(billing.prices_path().read_bytes(), raw)
        self.assertEqual(billing.load_prices(), previous)
        self.assertEqual(list(self.root.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
