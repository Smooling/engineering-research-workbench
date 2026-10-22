"""Presentation metadata must preserve source identity and avoid overstating evidence."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import evidence, projects, agent_runtime


class ResearchPresentationTests(unittest.TestCase):
    def test_display_alias_preserves_official_project_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def ensure(name):
                path = root / 'Projects' / name
                path.mkdir(parents=True, exist_ok=True)
                return path
            with patch.object(projects, 'ensure_workspace', return_value=root), patch.object(projects, 'ensure_project', side_effect=ensure):
                record = projects.create_project('Full official research title')
                source = root / 'source.md'
                source.write_text('Original research source\n', encoding='utf-8')
                with patch.object(projects, '_rename_legacy_associations') as rename:
                    updated = projects.update_project(record['id'], {'display_name': '简称'})
                    rename.assert_not_called()
                self.assertEqual(updated['name'], record['name'])
                self.assertEqual(updated['display_name'], '简称')
                self.assertTrue((root / 'Projects' / record['name']).is_dir())
                self.assertEqual(source.read_text(encoding='utf-8'), 'Original research source\n')
                with self.assertRaises(ValueError):
                    projects.update_project(record['id'], {'name': 'Must not rename', 'display_name': 'x' * 33})
                self.assertEqual(projects._load_registry()[0]['name'], record['name'])
                self.assertEqual(projects.update_project(record['id'], {'display_name': ''})['display_name'], '')

    def test_reading_status_never_implies_verified_original(self):
        for status in ('已精读', '阅读中', '待阅读'):
            self.assertEqual(evidence.describe({'kind': 'literature', 'status': status})['level'], 'catalog')
        self.assertEqual(evidence.describe({'kind': 'literature', 'attachment': 'missing.pdf', 'attachment_exists': False})['level'], 'catalog')
        self.assertEqual(evidence.describe({'kind': 'literature', 'tags': ['摘要可检索']})['level'], 'abstract')
        self.assertEqual(evidence.describe({'kind': 'literature', 'attachment_exists': True})['level'], 'pdf')
        self.assertEqual(evidence.describe({'body': '- 证据级别：已核对原文\n'})['level'], 'verified')
        self.assertEqual(evidence.describe({'body': '- 证据级别：摘要，不声称已核对原文\n'})['level'], 'abstract')
        for declaration in ('尚无摘要', '未读取摘要', '摘要不可用'):
            self.assertEqual(evidence.describe({'kind': 'literature', 'body': '证据范围：' + declaration})['level'], 'catalog')
        self.assertEqual(evidence.describe({'source': 'unstructured legacy source'})['level'], 'note')

    def test_public_task_summary_hides_internal_request_and_state(self):
        run = {'id': 'run-internal', 'request': {'message': '  比较\n供电恢复方法  ', 'context': {'private': 'not public'}}, 'state': {'secret': 'not public'}}
        result = agent_runtime.public_run(run)
        self.assertEqual(result['summary'], '比较 供电恢复方法')
        self.assertNotIn('request', result)
        self.assertNotIn('state', result)
        self.assertEqual(run['request']['message'], '  比较\n供电恢复方法  ')


if __name__ == '__main__':
    unittest.main()
