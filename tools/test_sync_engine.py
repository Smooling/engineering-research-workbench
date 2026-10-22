"""Two real HTTP workspaces: bidirectional edits, CAS, recovery and scope isolation."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sync_engine import SyncEngine, atomic_json, read_json, digest, normalized_url
from app.store import _frontmatter_dump, _frontmatter_parse
from server import Handler
from app import activity


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.a = SyncEngine(root / 'a/Workspace', root / 'a')
        self.b = SyncEngine(root / 'b/Workspace', root / 'b')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.server.sync_engine = self.b
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.a.configure({'url': self.url, 'mode': 'manual'})

    def tearDown(self):
        self.a.stop()
        self.b.stop()
        if self.a._thread:
            self.a._thread.join(3)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.temp.cleanup()

    @staticmethod
    def doc(engine, text='initial', doc_id='one', name=None):
        path = engine.root / 'Knowledge/Notes' / ((name or doc_id) + '.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_frontmatter_dump({'id': doc_id, 'kind': 'note', 'title': doc_id}) + text, encoding='utf-8')
        return path

    def sync(self):
        status = self.a.synchronize()
        self.assertNotEqual(status['phase'], 'error', status['error'])
        return status

    def conflict(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.a, 'local edit')
        self.doc(self.b, 'server edit')
        self.assertEqual(self.sync()['conflicts'], 1)
        return self.a.conflict_detail('doc:one')

    def test_upload_pull_and_no_retransfer(self):
        p = self.doc(self.a)
        self.assertEqual(self.sync()['phase'], 'synced')
        remote = self.b.root / p.relative_to(self.a.root)
        self.assertEqual(remote.read_bytes(), p.read_bytes())
        self.assertEqual(self.sync()['transferred'], 0)
        self.doc(self.b, 'web edit')
        self.sync()
        self.assertIn('web edit', p.read_text())

    def test_activity_two_device_union_keeps_same_second_actions_and_original_dates(self):
        for engine in (self.a, self.b):
            activity.record('doc_update', ref='same-doc', title='same action', weight=2,
                            timestamp='2026-10-12T10:00:00', root=engine.root)
        self.assertEqual(self.sync()['phase'], 'synced')
        a, b = activity.list_events(root=self.a.root), activity.list_events(root=self.b.root)
        self.assertEqual({e['id'] for e in a}, {e['id'] for e in b})
        self.assertEqual(len(a), 2)
        self.assertEqual(sum(e['weight'] for e in b), 4)
        self.assertEqual({e['timestamp'] for e in b}, {'2026-10-12T10:00:00'})
        before = (self.b.root / 'System/activity.jsonl').read_bytes()
        for _ in range(2):
            self.assertEqual(self.sync()['phase'], 'synced')
        self.assertEqual((self.b.root / 'System/activity.jsonl').read_bytes(), before)
        self.a = SyncEngine(self.a.root, self.a.data_root)
        self.assertEqual(self.sync()['phase'], 'synced')
        self.assertEqual(len(activity.list_events(root=self.a.root)), 2)

    def test_legacy_activity_shared_history_is_deduplicated_without_rewriting(self):
        event = {'timestamp':'2026-10-01T09:00:00', 'type':'doc_update', 'ref':'old', 'weight':3}
        raw = (json.dumps(event) + '\n').encode()
        for engine, repeats in ((self.a, 2), (self.b, 1)):
            path = engine.root / 'System/activity.jsonl'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw * repeats)
        self.assertEqual(self.sync()['phase'], 'synced')
        for engine in (self.a, self.b):
            events = activity.list_events(root=engine.root)
            self.assertEqual(len(events), 2)
            self.assertEqual(sum(e['weight'] for e in events), 6)
        self.assertEqual((self.a.root / 'System/activity.jsonl').read_bytes(), raw * 2)
        self.assertEqual(self.sync()['phase'], 'synced')
        self.assertEqual(len(activity.list_events(root=self.b.root)), 2)

    def test_activity_converges_on_a_third_device_and_respects_records_scope(self):
        activity.record('todo_done', root=self.a.root)
        self.a.configure({'url':self.url, 'mode':'manual', 'scopes':['documents']})
        self.sync()
        self.assertFalse(activity.list_events(root=self.b.root))
        self.a.configure({'url':self.url, 'mode':'manual', 'scopes':['records']})
        self.sync()
        third = SyncEngine(self.a.data_root.parent / 'c/Workspace', self.a.data_root.parent / 'c')
        third.configure({'url':self.url, 'mode':'manual', 'scopes':['records']})
        activity.record('doc_create', root=third.root)
        self.assertEqual(third.synchronize()['phase'], 'synced')
        self.sync()
        for engine in (self.a, self.b, third):
            self.assertEqual(len(activity.list_events(root=engine.root)), 2)

    def test_activity_cannot_be_overwritten_or_deleted_through_sync(self):
        activity.record('doc_create', root=self.a.root)
        row = self.a.manifest(['records'])['resources'][0]
        self.sync()
        remote = self.b.refresh()[row['key']]
        change = self.b._change(remote, remote['version'])
        change['descriptor'] = {**remote['descriptor'], 'value':{**remote['descriptor']['value'], 'title':'tampered'}}
        self.assertTrue(self.b.apply_many([change])['failed'])
        change = self.b._change(remote, remote['version'])
        change['deleted'] = True
        self.assertTrue(self.b.apply_many([change])['failed'])
        self.assertEqual(activity.list_events(root=self.a.root), activity.list_events(root=self.b.root))

    def test_old_sync_protocol_has_actionable_upgrade_error(self):
        with patch.object(self.a, '_request', return_value={'protocol':1, 'instance':'old-server', 'resources':[]}):
            with self.assertRaisesRegex(ValueError, '客户端和服务器端'):
                self.a.test_connection(self.url)

    def test_first_sync_preserves_two_different_versions(self):
        self.doc(self.a, 'local')
        self.doc(self.b, 'remote')
        self.assertEqual(self.sync()['conflicts'], 1)
        self.assertIn('local', (self.a.root / 'Knowledge/Notes/one.md').read_text())

    def test_independent_record_changes_merge(self):
        a = self.a.root / 'System/todos.json'
        b = self.b.root / 'System/todos.json'
        atomic_json(a, [{'id': 't1', 'title': 'first'}, {'id': 't2', 'title': 'second'}])
        self.sync()
        atomic_json(a, [{'id': 't1', 'title': 'local change'}, {'id': 't2', 'title': 'second'}])
        atomic_json(b, [{'id': 't1', 'title': 'first'}, {'id': 't2', 'title': 'web change'}])
        self.assertEqual(self.sync()['conflicts'], 0)
        self.assertEqual(sorted(read_json(a, []), key=lambda v:v['id']), sorted(read_json(b, []), key=lambda v:v['id']))
        self.assertEqual({r['title'] for r in read_json(a, [])}, {'local change', 'web change'})

    def test_deletion_recoverable_and_not_resurrected(self):
        path = self.doc(self.a)
        self.sync()
        path.unlink()
        self.assertEqual(self.a.status(scan=True)['changes'][0]['code'], 'D')
        self.sync()
        self.assertFalse((self.b.root / 'Knowledge/Notes/one.md').exists())
        self.assertTrue(list((self.b.root / 'System/Trash/Sync').rglob('one.md')))
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_delete_vs_edit_conflict(self):
        path = self.doc(self.a)
        self.sync()
        path.unlink()
        self.doc(self.b, 'server still editing')
        self.assertEqual(self.sync()['conflicts'], 1)
        self.assertFalse(path.exists())

    def test_same_edit_on_both_sides_converges(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.a, 'same')
        self.doc(self.b, 'same')
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_remote_cas_prevents_overwrite(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.a, 'local')
        original = self.a._request
        def racing(url, route, payload=None, method=None):
            if route == '/api/sync/apply':
                self.doc(self.b, 'edited after manifest')
            return original(url, route, payload, method)
        with patch.object(self.a, '_request', side_effect=racing):
            self.assertEqual(self.sync()['conflicts'], 1)
        self.assertIn('edited after manifest', (self.b.root / 'Knowledge/Notes/one.md').read_text())

    def test_local_cas_prevents_racing_pull(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.b, 'server')
        original = self.a._download_blob
        def racing(url, desc):
            original(url, desc)
            self.doc(self.a, 'saved while downloading')
        with patch.object(self.a, '_download_blob', side_effect=racing):
            self.assertEqual(self.sync()['conflicts'], 1)
        self.assertIn('saved while downloading', (self.a.root / 'Knowledge/Notes/one.md').read_text())

    def test_dirty_editor_defers_remote_changes(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.b, 'incoming')
        self.a.guard_editor('ui', 'one', True)
        status = self.sync()
        self.assertEqual(status['download'], 1)
        self.assertEqual(status['conflicts'], 0)
        self.assertIn('initial', (self.a.root / 'Knowledge/Notes/one.md').read_text())
        self.a.guard_editor('ui', 'one', False)
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_remote_dirty_editor_defers_push(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.a, 'outgoing')
        self.b.guard_editor('web', 'one', True)
        self.sync()
        self.assertIn('initial', (self.b.root / 'Knowledge/Notes/one.md').read_text())
        self.b.guard_editor('web', 'one', False)
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_restart_keeps_offline_pending_and_peer_baseline(self):
        self.doc(self.a)
        self.sync()
        self.doc(self.a, 'offline edit')
        root, data = self.a.root, self.a.data_root
        instance = self.a.instance
        self.a.stop()
        self.a = SyncEngine(root, data)
        self.assertEqual(self.a.instance, instance)
        self.assertEqual(self.a.status(scan=True)['upload'], 1)
        self.a.configure({'url': 'http://127.0.0.1:1', 'mode': 'manual'})
        self.assertEqual(self.a.synchronize()['phase'], 'error')
        self.a.configure({'url': self.url, 'mode': 'manual'})
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_scope_secrets_and_local_paths_remain_local(self):
        atomic_json(self.a.data_root / 'config/app.json', {'host':'127.0.0.1', 'port':8765, 'workspace':'D:/mine', 'llm':{'api_key':'secret'}, 'literature':{'pdf_dir':'D:/PDF'}, 'ui':{'theme':'dark'}, 'app_name':'Mine'})
        atomic_json(self.b.data_root / 'config/app.json', {'port':9999, 'llm':{'api_key':'remote secret'}})
        self.a.save_preferences({'theme':'dark'})
        self.sync()
        target = read_json(self.b.data_root / 'config/app.json', {})
        self.assertEqual(target['port'], 9999)
        self.assertEqual(target['llm']['api_key'], 'remote secret')
        self.assertNotIn('workspace', target)
        self.assertNotIn('literature', target)
        self.assertEqual(target['ui']['theme'], 'dark')
        self.assertEqual(read_json(self.b.preferences_path, {})['theme'], 'dark')

    def test_disabled_scope_does_not_upload_and_off_does_nothing(self):
        self.doc(self.a)
        asset = self.a.root / 'Knowledge/file.pdf'
        asset.write_bytes(b'PDF')
        self.a.configure({'url': self.url, 'mode': 'manual', 'scopes':['documents']})
        self.sync()
        self.assertFalse((self.b.root / 'Knowledge/file.pdf').exists())
        self.a.configure({'url': self.url, 'mode': 'off'})
        self.doc(self.a, 'not uploaded')
        self.a.synchronize()
        self.assertNotIn('not uploaded', (self.b.root / 'Knowledge/Notes/one.md').read_text())

    def test_keep_local_remote_and_both(self):
        d = self.conflict()
        self.a.resolve({**d, 'choice':'both'})
        self.assertIn('server edit', (self.a.root / 'Knowledge/Notes/one.md').read_text())
        copies = list((self.a.root / 'Knowledge/Notes').glob('*本地副本*'))
        self.assertEqual(len(copies), 1)
        meta, body = _frontmatter_parse(copies[0].read_text(encoding='utf-8'))
        self.assertNotEqual(meta['id'], 'one')
        self.assertIn('local edit', body)
        self.assertEqual(self.sync()['conflicts'], 0)
        self.doc(self.a, 'another local edit')
        self.doc(self.b, 'another remote edit')
        self.sync()
        self.a.resolve({**self.a.conflict_detail('doc:one'), 'choice':'local'})
        self.assertIn('another local edit', (self.b.root / 'Knowledge/Notes/one.md').read_text())
        self.doc(self.a, 'new local')
        self.doc(self.b, 'new remote')
        self.sync()
        self.a.resolve({**self.a.conflict_detail('doc:one'), 'choice':'remote'})
        self.assertIn('new remote', (self.a.root / 'Knowledge/Notes/one.md').read_text())

    def test_merge_and_stale_resolution(self):
        detail = self.conflict()
        self.doc(self.b, 'changed again')
        with self.assertRaisesRegex(ValueError, '新修改'):
            self.a.resolve({**detail, 'choice':'local'})
        detail = self.a.conflict_detail('doc:one')
        merged = _frontmatter_dump({'id':'one', 'kind':'note', 'title':'merged'}) + 'both changes merged'
        self.a.resolve({**detail, 'choice':'merge', 'text':merged})
        self.assertEqual((self.a.root / 'Knowledge/Notes/one.md').read_bytes(), (self.b.root / 'Knowledge/Notes/one.md').read_bytes())

    def test_blob_resume_and_corruption_detection(self):
        value = b'large-ish PDF' * 100
        sha = hashlib.sha256(value).hexdigest()
        self.assertEqual(self.b.receive_blob(sha, value[:100], 0, len(value))['offset'], 100)
        self.assertEqual(self.b.receive_blob(sha, value[100:], 0, len(value))['offset'], 100)
        self.assertTrue(self.b.receive_blob(sha, value[100:], 100, len(value))['ready'])
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.b.receive_blob('0' * 64, b'invalid', 0, 7)

    def test_identical_blob_can_be_reused_while_a_reader_holds_it_open(self):
        first = self.doc(self.a)
        sha, size = self.a._store_blob(first)
        second = self.a.root / 'Knowledge/Notes/copy.md'
        second.write_bytes(first.read_bytes())
        cached = self.a._blob_path(sha)
        before = cached.stat().st_mtime_ns
        with cached.open('rb') as reader:
            self.assertEqual(self.a._store_blob(second), (sha, size))
            self.assertEqual(reader.read(), first.read_bytes())
        self.assertEqual(cached.stat().st_mtime_ns, before)
        self.assertEqual(list(self.a.blobs.glob('*.tmp')), [])

    def test_parallel_publishers_do_not_replace_each_other(self):
        data = b'Identical saved attachment\n' * 10000
        paths = [self.a.root / ('Knowledge/asset-' + str(i) + '.txt') for i in range(2)]
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        for path in paths:
            path.write_bytes(data)
        barrier = threading.Barrier(2)
        operation = 'rename' if os.name == 'nt' else 'link'
        original = getattr(os, operation)
        def racing(source, target):
            barrier.wait(timeout=3)
            return original(source, target)
        with patch('app.sync_engine.os.' + operation, side_effect=racing):
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(self.a._store_blob, paths))
        self.assertEqual(values[0], values[1])
        self.assertEqual(self.a._blob_path(values[0][0]).read_bytes(), data)
        self.assertEqual(list(self.a.blobs.glob('*.tmp')), [])

    def test_commit_reuses_blob_created_after_the_existence_check(self):
        source = self.doc(self.a)
        handles = []
        operation = 'rename' if os.name == 'nt' else 'link'
        def racing(temp, target):
            target.write_bytes(temp.read_bytes())
            handles.append(target.open('rb'))
            error = PermissionError('A reader holds the existing blob')
            error.winerror = 5
            raise error
        try:
            with patch('app.sync_engine.os.' + operation, side_effect=racing) as publish:
                sha, size = self.a._store_blob(source)
            publish.assert_called_once()
            self.assertEqual(self.a._blob_path(sha).stat().st_size, size)
            self.assertEqual(handles[0].read(), source.read_bytes())
        finally:
            for handle in handles:
                handle.close()

    def test_temporary_new_blob_lock_retries_without_touching_source(self):
        source = self.doc(self.a)
        data = source.read_bytes()
        operation = 'rename' if os.name == 'nt' else 'link'
        original = getattr(os, operation)
        calls = []
        def busy(temp, target):
            calls.append(True)
            if len(calls) < 3:
                error = PermissionError('Temporary scanner lock')
                error.winerror = 5
                raise error
            return original(temp, target)
        with patch('app.sync_engine.os.' + operation, side_effect=busy), patch('app.sync_engine.time.sleep') as sleep:
            sha, _ = self.a._store_blob(source)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(self.a._blob_path(sha).read_bytes(), data)

    def test_permanent_blob_access_failure_preserves_documents(self):
        source = self.doc(self.a)
        data = source.read_bytes()
        error = PermissionError('Persistent access failure')
        error.winerror = 5
        operation = 'rename' if os.name == 'nt' else 'link'
        with patch('app.sync_engine.os.' + operation, side_effect=error) as publish, patch('app.sync_engine.time.sleep'):
            self.assertEqual(self.a.synchronize()['phase'], 'error')
        self.assertEqual(publish.call_count, 5)
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(list(self.a.blobs.glob('*.tmp')), [])
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_finished_partial_upload_is_finalized_on_retry(self):
        source = self.doc(self.a)
        row = self.a.manifest()['resources'][0]
        desc = row['descriptor']
        part = self.b._blob_path(desc['blob']).with_suffix('.part')
        part.write_bytes(source.read_bytes())
        self.assertFalse(self.b.blob_info(desc['blob'])['ready'])
        self.a._upload_blob(self.url, desc)
        self.assertTrue(self.b.blob_info(desc['blob'])['ready'])
        self.assertFalse(part.exists())

    def test_concurrent_downloads_share_one_partial_writer(self):
        self.doc(self.b)
        row = self.b.manifest()['resources'][0]
        desc = row['descriptor']
        import app.sync_engine as engine_module
        original = engine_module.urlopen
        downloads = []
        def observe(request, **kwargs):
            downloads.append(request.full_url)
            return original(request, **kwargs)
        with patch('app.sync_engine.urlopen', side_effect=observe):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.a._download_blob, self.url, desc) for _ in range(2)]
                for future in futures:
                    future.result(timeout=5)
        self.assertEqual(len(downloads), 1)
        self.assertEqual(self.a._blob_path(desc['blob']).read_bytes(), self.b._blob_path(desc['blob']).read_bytes())
        self.assertEqual(list(self.a.blobs.glob('*.part')), [])

    def test_file_rename_by_stable_id(self):
        p = self.doc(self.a)
        self.sync()
        p.rename(p.with_name('renamed.md'))
        self.assertEqual(self.sync()['phase'], 'synced')
        self.assertFalse((self.b.root / 'Knowledge/Notes/one.md').exists())
        self.assertTrue((self.b.root / 'Knowledge/Notes/renamed.md').exists())

    def test_no_unwritten_drafts_and_duplicate_ids_stop_safely(self):
        self.assertFalse(any(r['scope']=='documents' for r in self.a.manifest()['resources']))
        self.doc(self.a)
        self.doc(self.a, name='duplicate')
        self.assertEqual(self.a.synchronize()['phase'], 'error')
        self.assertFalse((self.b.root / 'Knowledge/Notes/one.md').exists())

    def test_path_validation_and_self_connection(self):
        for path in ['../escape', 'Knowledge/../../oops', 'System/Sync/state.sqlite', 'Knowledge/Trash/no.md', 'Knowledge/a:stream', 'Knowledge/CON.md']:
            with self.assertRaises(ValueError, msg=path):
                self.a._path(path)
        with self.assertRaisesRegex(ValueError, '当前工作台'):
            self.b.test_connection(self.url)
        self.assertEqual(normalized_url('127.0.0.1:8765/'), 'http://127.0.0.1:8765')

    def test_server_endpoints_work_when_server_mode_off(self):
        self.doc(self.b)
        self.assertEqual(self.b.config()['mode'], 'off')
        self.assertTrue(self.a.test_connection(self.url)['ok'])
        self.assertEqual(self.sync()['phase'], 'synced')

    def test_auto_worker_and_manual_does_not_contact_server(self):
        self.doc(self.a)
        with patch.object(self.a, '_fetch_manifest', wraps=self.a._fetch_manifest) as calls:
            self.a.start()
            time.sleep(.12)
            self.assertEqual(calls.call_count, 0)
            self.a.configure({'url':self.url, 'mode':'auto', 'interval':10})
            deadline = time.monotonic() + 5
            while not (self.b.root / 'Knowledge/Notes/one.md').exists() and time.monotonic() < deadline:
                time.sleep(.03)
            self.assertTrue((self.b.root / 'Knowledge/Notes/one.md').exists())
            self.assertGreater(calls.call_count, 0)


if __name__ == '__main__':
    unittest.main()
