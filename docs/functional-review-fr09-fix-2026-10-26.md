# FR-09：重建关联后批注不可见的修复

直接附件文献登记时保留 `entry-<doc_id>`，不再为同一篇文献生成新的批注身份。已经登记的文献继续保留原 ID；重新登记附件时更新原记录，避免为同一文档增加重复 registry 条目。

兼容已经出现问题的历史数据：打开 UUID 文献的批注时，检查相同 `doc_id` 的旧 `entry-*` 文件。两个文件均有批注时按批注 ID 合并，当前 UUID 文件中的同 ID 记录优先，其他记录全部保留；重复编号会重新分配。合并文件以临时文件替换的方式提交，随后把旧 JSON 原样备份到 `Knowledge/Literature/Annotations/Legacy/`。截图文件及 `preview_path` 不移动、不改写，已有图片地址和笔记引用继续有效。

旧 `entry-*` 接口与 UUID 接口指向同一批注存储。恢复后的修改、添加和删除都通过这份数据完成，旧备份不会被重新读取，避免已删除批注在重复重建后复活。读取、合并和写入在同一进程内串行执行。保存或归档失败时返回错误并保留可重试的数据；不会用空数组覆盖无法解析的历史文件。

设置页说明同步改为“复制 PDF 并保留来源文件”，并说明打开文献时会自动恢复历史遗留批注。原审查报告、复现脚本、截图和结果文件均未覆盖，FR-02 保持原处理范围。

正式回归位于 `tools/test_review_regressions.py`，新增 FR-09 的七项后端测试和一项真实 Edge 测试；真实浏览器脚本为 `tools/literature_lifecycle_ui_check.js`。PDF 副本的文件名与稳定文献 ID 分开生成，另有专项确认已有同名文件不会被覆盖。

已验证：

- 单篇、全量及重复重建后，文献 ID、批注 ID、已保存文字和截图路径保持可用，PDF 两个下载入口的 SHA-256 一致，阅读页码和笔记正文保留。
- 使用全新 Python 进程重新读取，确认状态不依赖内存缓存。
- 历史 UUID 文件不存在、为空或已保存新批注时，旧批注均能恢复；同 ID 记录不重复，当前记录不被旧意见覆盖。
- 新旧 ID 并发保存、合并写入失败、旧文件归档失败及历史文件损坏；失败保留数据，重试不重复，删除后不复活。
- 两篇文献共享同一 PDF 时，重建保留各自独立的批注。
- 真实设置页点击“重建关联”、确认、刷新、批注截图加载、截图加入笔记并保存，以及历史批注恢复后继续编辑和刷新。

验证结果：

- 全量回归开启四个浏览器开关：**247/247 通过，无跳过**（249.995 秒）。
- 最后补齐同名文件检查后的问题专项：**19/19 通过，无跳过**（41.822 秒，含两项真实 Edge 测试）。
- 最终源码的项目 self-check 通过，包括 Python / JavaScript 语法检查。

运行日志：`.scratch/fr09-python-tests.log`、`.scratch/fr09-targeted-final-tests.log`、`.scratch/fr09-self-check.log`。首次专项的 18 项通过日志另存于 `.scratch/fr09-targeted-tests.log`。

复测命令（仓库根目录 PowerShell）：

```powershell
$env:NODE_PATH='C:\Users\Smoothing\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:ERW_FUNCTIONAL_UI='1'
build/.venv/Scripts/python.exe -m unittest tools.test_review_regressions -v
```

所有新增验证写入临时工作区和临时配置。未对个人 Workspace 执行恢复或导入测试数据；已有历史批注的恢复由修改后的读取逻辑在打开文献时完成。
