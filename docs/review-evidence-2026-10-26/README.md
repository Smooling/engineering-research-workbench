# 2026-10-26 功能审查证据

主报告：[全面功能审查](../functional-review-2026-10-26.md)。所有测试写入使用临时工作区或静态模拟接口，没有向个人 Workspace 添加测试资料。

## 新增复现

- `supplemental-review.py`：创建临时配置和工作区，启动真实 HTTP 服务，运行六类资料、项目、文献、存储迁移等检查，并启动浏览器补充检查。退出时关闭测试服务、清理临时工作区。
- `supplemental-ui.cjs`：两个真实 Edge 页面检查文献信息并发覆盖、批注草稿与显式保存；使用上一脚本的真实后端。
- `supplemental-results.json`：61 条断言和 1 条迁移响应观测。8 条失败断言。
- `supplemental-ui-results.json`：7 条断言。3 条失败断言。
- `supplemental.log`：最终运行日志；`supplemental-initial.log` 为较早运行，包含已修正的批注创建 200/201 预期错误，不能用于最终统计。
- 三张 PNG：文献信息覆盖及批注页签切换前后。PDF 为本次生成的四页空白合成测试文件。

在仓库根目录运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
build/.venv/Scripts/python.exe docs/review-evidence-2026-10-26/supplemental-review.py
```

需要项目现有 Python 环境、pypdf、Playwright 和 Edge。脚本使用当前 Windows 用户目录下的 Codex bundled Playwright 路径，可按环境调整。此脚本逐项记录结果并继续执行；**退出 0 不代表全部断言通过**，应检查输出 JSON 的 `pass` 字段。重复运行会覆盖本目录最终日志之外的结果 JSON 和截图。

## 现有套件

`python-tests.log`：229 项通过，无跳过。运行时设定：

```powershell
$env:NODE_PATH='C:\Users\Smoothing\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:ERW_FUNCTIONAL_UI='1'
$env:ERW_PLANNING_UI='1'
$env:ERW_ENTRY_UI='1'
$env:ERW_HOVER_UI='1'
build/.venv/Scripts/python.exe -m unittest discover -s tools -p 'test_*.py' -v
```

其他日志分别对应项目自检、工作台 UI、Agent UI、来源 UI、文献、规划、PDF 质量、概览和引用专项。测试中的模型行为来自模拟响应或本机服务，未调用个人付费模型。

引用专项首跑失败、原脚本重跑通过；`prepare-reference-diagnostic.py` 仅给临时副本添加越界时的坐标输出、800ms 后复查和截图，原断言仍保留。诊断副本也通过，没有生成越界截图，不能据此认定已定位首次失败原因。

`performance.json` 为 3,000 篇合成资料的性能抽样。`source-snapshot.json` 记录审查结束时关键源码的 SHA-256；审查前后已有 Git 差异统计一致。

本目录和主报告受仓库现有白名单式 `.gitignore` 忽略，仅作为本地审查交付物保存；本轮未修改忽略规则、暂存或提交文件。个人数据、已有未提交改动和业务源码均未为审查结果作修改。
