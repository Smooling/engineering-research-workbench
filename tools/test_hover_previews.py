"""Browser regressions using a disposable workspace and the real HTTP service.

Run with ERW_HOVER_UI=1 and Playwright available in NODE_PATH.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import test_functional_regressions as regressions


class HoverPreviewTests(unittest.TestCase):
    setUp = regressions.FunctionalRegressionTests.setUp
    tearDown = regressions.FunctionalRegressionTests.tearDown
    http = regressions.FunctionalRegressionTests.http

    @unittest.skipUnless(os.environ.get("ERW_HOVER_UI") == "1", "requires browser opt-in")
    def test_hover_previews_in_actual_application(self):
        with self.http():
            subprocess.run(["node", str(ROOT / "tools/hover_preview_ui_check.js"), self.base],
                           cwd=ROOT, check=True, timeout=150)


if __name__ == "__main__":
    unittest.main()
