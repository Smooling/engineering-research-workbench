# 功能复测证据 · 2026-10-26

对应报告：[完整复测报告](E:/PyProgram/workbench_test/engineering-research-workbench/docs/functional-retest-2026-10-26.md)。全部数据来自隔离临时目录，业务源码未修改。

- `python-tests.log`：240 个正式测试通过，包含本次修复加入的 11 个回归测试。
- `self-check.log`：15 组自检通过。
- `ui-summary.json`、8 个 `*-ui.log`：8 组界面专项全部通过。
- `supplemental-review.py`、`supplemental-ui.cjs`：上轮原始补充复现脚本，复制后原样执行。
- `supplemental-results.json`：61 个断言全部通过，另有 1 条响应观测。
- `supplemental-ui-results.json`：6 / 7 通过，失败项对应按要求保留的 FR-02。
- `lifecycle-checks.py`、`lifecycle-ui.cjs`：独立检查直接附件登记前后的阅读位置、PDF 哈希和批注，以及草稿删除后的保护状态；通过实际设置页触发重建。
- `lifecycle-results.json`：10 个 HTTP/状态断言中 8 个通过，2 个失败均为重建后的批注不可见；另含 1 条浏览器脚本完成状态。
- `lifecycle-ui-results.json`：7 个浏览器断言中 5 个通过，2 个失败同属 FR-09。
- `lifecycle-before-rebuild.png`、`lifecycle-after-rebuild.png`：新问题截图；其他 PNG 为原始复现截图。
- `performance.json`：3,000 文档、9,000 关系的隔离性能抽样。
- `baseline-status.txt`、`baseline-diff.txt`：复测开始时已有的用户修改。
- `source-before.json`、`source-verification.json`：123 个源码/测试/版本文件的校验结果，无内容变化。

补充脚本会记录失败后继续，退出码 0 不等于断言全通过。FR-02 和 FR-09 的失败断言保留为真实证据。

在仓库根目录使用 PowerShell 复现：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:NODE_PATH='C:\Users\Smoothing\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:ERW_FUNCTIONAL_UI='1'
$env:ERW_PLANNING_UI='1'
$env:ERW_ENTRY_UI='1'
$env:ERW_HOVER_UI='1'
build/.venv/Scripts/python.exe -m unittest discover -s tools -p 'test_*.py' -v
build/.venv/Scripts/python.exe tools/self_check.py
node tools/ui_usability_check.js
node tools/agent_system_ui_check.js
node tools/agent_sources_ui_check.js
node tools/ui_usability_check.js --literature-only
node tools/ui_usability_check.js --planning-only
node tools/ui_usability_check.js --references-only
node tools/ui_usability_check.js --pdf-quality-only
node tools/ui_usability_check.js --overview-only
build/.venv/Scripts/python.exe docs/retest-evidence-functional-2026-10-26/supplemental-review.py
build/.venv/Scripts/python.exe docs/retest-evidence-functional-2026-10-26/lifecycle-checks.py
build/.venv/Scripts/python.exe tools/performance_benchmark.py --synthetic 3000 --repeat 3
```
