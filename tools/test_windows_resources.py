"""Portable resource regressions, without building an EXE or touching user data."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_windows import stage_resources
from core.plugins.registry import default_roots
from app import paths
from app.windows_runtime import CLR_CONFIG, ensure_clr_config
import core_api


class WindowsResourcesTests(unittest.TestCase):
    def test_portable_clr_config_created_without_overwriting_existing_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "ResearchWorkbench.exe"
            target = ensure_clr_config(executable)
            self.assertEqual(target.name, "ResearchWorkbench.exe.config")
            self.assertEqual(target.read_text(encoding="utf-8"), CLR_CONFIG)
            custom = '<configuration><runtime /></configuration>'
            target.write_text(custom, encoding="utf-8")
            ensure_clr_config(executable)
            self.assertEqual(target.read_text(encoding="utf-8"), custom)

    def test_resource_allowlist_keeps_plugins_manual_and_vendor(self):
        with tempfile.TemporaryDirectory() as folder:
            root, out = Path(folder) / "source", Path(folder) / "out"
            keep = ("plugins/focus/plugin.json", "plugins/focus/web/panel.js",
                    "plugins/rss/backend.py", "web/vendor/pdfjs/cmaps/Uni.bcmap",
                    "web/vendor/pdfjs/build/pdf.min.js",
                    "web/vendor/pdfjs/standard_fonts/font.pfb", "docs/manual/01-intro.md")
            exclude = ("plugins/focus/data/state.json", "plugins/focus/.cache/secret.json",
                       "plugins/focus/config/secrets.json", "plugins/.template/plugin.json",
                       "config/secret.json", "Workspace/private.md", "web/_preview_test.html")
            for name in (*keep, *exclude):
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("fixture", encoding="utf-8")
            stage_resources(root, out)
            self.assertEqual({str(p.relative_to(out)).replace('\\', '/')
                              for p in out.rglob('*') if p.is_file()}, set(keep))

    def test_frozen_plugins_use_assets_and_custom_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            asset, data = Path(folder).resolve() / "assets", Path(folder).resolve() / "data"
            (asset / "plugins/focus").mkdir(parents=True)
            (data / "plugins/custom").mkdir(parents=True)
            with patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, '_MEIPASS', str(asset), create=True), \
                 patch.object(paths, 'DATA_ROOT', data), \
                 patch.object(paths, 'ASSET_ROOT', asset):
                self.assertEqual(default_roots(data), [('bundled', asset / 'plugins'), ('user', data / 'plugins')])
                self.assertEqual(core_api.plugin_dir('focus'), asset / 'plugins/focus')
                self.assertEqual(core_api.plugin_dir('custom'), data / 'plugins/custom')
                self.assertEqual(core_api.cache_db('focus'), data / 'Workspace/System/Cache/focus.sqlite')

    def test_source_custom_data_keeps_bundled_plugins(self):
        with tempfile.TemporaryDirectory() as folder:
            asset, data = Path(folder).resolve() / 'assets', Path(folder).resolve() / 'data'
            (asset / 'plugins/focus').mkdir(parents=True)
            with patch.object(paths, 'DATA_ROOT', data), patch.object(paths, 'ASSET_ROOT', asset):
                self.assertEqual(default_roots(data, asset_root=asset),
                                 [('bundled', asset / 'plugins'), ('user', data / 'plugins')])
                self.assertEqual(core_api.plugin_dir('focus'), asset / 'plugins/focus')


if __name__ == '__main__':
    unittest.main()
