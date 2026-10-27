"""Real-browser graph checks against a disposable knowledge workspace.

Run with ERW_GRAPH_UI=1 and Playwright available in NODE_PATH.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import indexer
from tools import test_functional_regressions as fixtures


@unittest.skipUnless(os.environ.get("ERW_GRAPH_UI") == "1", "set ERW_GRAPH_UI=1")
class GraphConstellationTests(unittest.TestCase):
    setUp = fixtures.FunctionalRegressionTests.setUp
    tearDown = fixtures.FunctionalRegressionTests.tearDown
    http = fixtures.FunctionalRegressionTests.http

    def test_constellation_and_existing_graph_workflows(self):
        themes = ["状态估计", "轨道动力学", "视觉导航", "鲁棒控制", "多源融合", "实验验证"]
        kinds = ["note", "idea", "literature", "journal", "summary", "milestone"]
        for i, theme in enumerate(themes):
            indexer.create_doc("summary", {"title": f"研究主题-{theme}", "projects": [theme],
                                          "tags": [theme], "body": "# 研究主题\n\n测试资料"})
        for i in range(108):
            theme = themes[i % len(themes)]
            indexer.create_doc(kinds[i % len(kinds)], {
                "title": f"知识-{theme}-{i:03d}", "projects": [theme],
                "tags": [theme, f"方法-{i % 9}"],
                "body": f"# 星图验证正文\n\n[[研究主题-{theme}]]\n\n[[知识-{themes[(i+1)%6]}-{(i+1)%108:03d}]]",
            })
        evidence = ROOT / ".scratch/graph-constellation"
        evidence.mkdir(parents=True, exist_ok=True)
        with self.http():
            subprocess.run(["node", str(ROOT / "tools/graph_constellation_ui_check.js"), self.base, str(evidence)],
                           cwd=ROOT, check=True, timeout=180)


if __name__ == "__main__":
    unittest.main()
