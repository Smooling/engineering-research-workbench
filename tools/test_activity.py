"""Activity union must preserve local work during background imports."""
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import activity


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_import_and_local_actions_lose_nothing_and_do_not_duplicate(self):
        remote = [{'id':f'{n:032x}', 'type':'doc_update', 'timestamp':'2026-10-01T10:00:00', 'weight':2}
                  for n in range(20)]
        def work(n):
            if n % 2:
                activity.record('doc_update', timestamp='2026-10-02T10:00:00', root=self.root)
            else:
                activity.merge_events(remote, root=self.root)
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(work, range(40)))
        events = activity.list_events(root=self.root)
        self.assertEqual(len(events), 40)
        self.assertEqual(sum(e.get('weight', 1) for e in events), 60)
        self.assertEqual(activity.merge_events(remote, root=self.root), 0)

    def test_truncated_utf8_tail_does_not_block_sync_or_corrupt_next_action(self):
        path = self.root / 'System/activity.jsonl'
        path.parent.mkdir()
        old = {'timestamp':'2026-10-01T10:00:00', 'type':'doc_create'}
        path.write_bytes((json.dumps(old)+'\n').encode() + b'{"title":"\xe7')
        self.assertEqual(len(activity.list_events(root=self.root)), 1)
        imported = {'id':'f'*32, 'timestamp':'2026-10-02T10:00:00', 'type':'todo_done'}
        self.assertEqual(activity.merge_events([imported], root=self.root), 1)
        self.assertEqual(len(activity.list_events(root=self.root)), 2)
        activity.record('doc_update', root=self.root)
        self.assertEqual(len(activity.list_events(root=self.root)), 3)

    def test_invalid_batch_is_rejected_before_any_history_is_appended(self):
        event = {'id':'f'*32, 'timestamp':'2026-10-02T10:00:00', 'type':'doc_create'}
        with self.assertRaises(ValueError):
            activity.merge_events([event, dict(event, timestamp='invalid')], root=self.root)
        self.assertEqual(activity.list_events(root=self.root), [])
        activity.merge_events([event], root=self.root)
        with self.assertRaises(ValueError):
            activity.merge_events([dict(event, type='changed')], root=self.root)
        self.assertEqual(activity.list_events(root=self.root), [event])


if __name__ == '__main__':
    unittest.main()
