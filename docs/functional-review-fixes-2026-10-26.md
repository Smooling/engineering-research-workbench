# 2026-10-26 功能审查问题修复

修复范围：FR-01、FR-03、FR-04、FR-05、FR-06、FR-07、FR-08。按要求保留 FR-02 的文献信息并发保存行为。未修改原审查报告、复现结果或截图；原有未提交改动保留。

| 问题 | 修改后的行为 |
| --- | --- |
| FR-01 / FR-04 | PDF 目录切换前检查整批同名冲突；相同内容复用，不同内容拒绝。复制后校验 SHA-256，按移动前收集的引用更新 Markdown，最后提交配置。复制中断、附件更新及配置保存失败时恢复原文档和配置，保留可用原文件。配置成功后再清理旧副本；无法清理的副本通过响应的 `retained` 计数报告。 |
| FR-03 | 按文献和批注 ID 保留意见草稿，切换页签、批注卡片或收起编辑器后可以恢复。切换文献和离开检查提供保存、丢弃和取消；保存会处理该文献的全部批注草稿，失败保留输入。窗口关闭检查与 Ctrl+S 同样包含批注。 |
| FR-05 | 重建关联复制 PDF 并保留来源，其他共享引用继续可读。匹配已有 PDF 使用真实路径，避免同名文件误关联。单篇、全量及重复重建均有回归覆盖。 |
| FR-06 | 直接附件文献的页码和页数按稳定文档 ID 独立保存到磁盘，读取和重建索引后恢复；显式登记 PDF 时继承该状态。导入及补充 PDF 的原有保存路径保留。 |
| FR-07 | 请求中的状态、简称、名称和目标目录先校验。改名期间文件写入失败时恢复目录、文档原始字节、待办及项目 registry。 |
| FR-08 | Markdown 明确提供 `pinned` 时，其值决定文献 `favorite`；缺失该字段时保留旧 registry 的兼容行为。 |

新增正式回归：`tools/test_review_regressions.py`（11 项），以及 `tools/review_regression_ui_check.js`（真实 Edge 与真实临时后端）。新增脚本已经加入 Git 白名单。测试使用临时配置和工作区，不向个人 Workspace 写入测试资料。

验证结果：

- 全量 Python 回归，开启四个浏览器测试开关：**240/240 通过，无跳过**，205.434 秒。
- 最后调整后的问题专项及项目显示回归：**14/14 通过**，21.583 秒，包括真实浏览器批注操作。
- 项目 self-check：通过，包括 Python / JavaScript 语法检查。
- 迁移回归同时对照文献 PDF 接口、文档附件接口的 SHA-256，并在重建索引后再次检查；覆盖同名不同内容、同名同内容、模拟目标不可写、复制中断、文档写入失败和配置提交失败。
- 项目失败回归覆盖目录改名失败、待办写入后失败及 registry 提交后失败，并对照原文件字节和索引读取结果。

本地日志保存在 `.scratch/review-fixes-python-tests.log`、`.scratch/review-fixes-targeted-tests.log` 和 `.scratch/review-fixes-self-check.log`，受临时目录清理规则管理。

复测命令（仓库根目录 PowerShell）：

```powershell
$env:NODE_PATH='C:\Users\Smoothing\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:ERW_FUNCTIONAL_UI='1'
$env:ERW_PLANNING_UI='1'
$env:ERW_ENTRY_UI='1'
$env:ERW_HOVER_UI='1'
build/.venv/Scripts/python.exe -m unittest discover -s tools -p 'test_*.py' -v
build/.venv/Scripts/python.exe tools/self_check.py
```

未覆盖打包 EXE 或强制断电后的文件系统恢复。迁移使用先复制后提交的顺序保留来源，但不宣称跨文件断电事务。
