# Agent 复测证据

测试执行于 2026-10-22，报告整理及关键源码哈希复核于 2026-10-23。

- [完整报告](../agent-functional-retest-2026-10-23.md)
- [独立问题清单](../agent-functional-test-issues-2026-10-23.md)
- `final-audit-results.json`：最终 143 个独立补充断言，141 通过、2 失败；两条失败为同一来源覆盖缺陷的文件/PDF 分支。
- `source-coverage-gap.json`：来源缺陷的任务/回答定位、工具轨迹、请求与来源视图。
- `source-snapshot.json`：测试版本及 8 个关键文件 SHA-256。
- `all-python-tests.log`：全量 224 项，222 通过、2 默认跳过。
- `real-ui-integrations.log`：显式开启浏览器的 26 项检查，含两项默认跳过用例，全部通过。
- `agent-python-tests.log`、`agent-system-ui.log`、`agent-sources-ui.log`、`workbench-ui.log`：专项及界面回归。
- `self-check.log`：自检入口失败的完整堆栈。
- `manual-ui-results.json` 及 PNG：实际宽屏浏览器观测，全部使用隔离数据。

阶段性的 `http-initial-results.json`、`reviewed-results.json`、`final-results.json`、`final-reviewed-results.json` 保留脚本误报及复核过程。最终结论以 `final-audit-results.json` 为准；不能用来源覆盖补查前的全通过结果替代最终结果。

## 复现包

使用 [isolated-http-reproduction-v2.zip](isolated-http-reproduction-v2.zip)。旧的 v1 包保留执行历史，缺少最后补查文件/PDF 来源的脚本，不作为完整复现包。

v2 包包含真实出站请求记录（仅本地合成服务及数据）、脚本和各阶段输出，不包含用户真实知识库或模型凭据。

复现需当前仓库、项目 Python 依赖，并将脚本解压到一个新的同层目录，例如仓库下 `.scratch/verify/agent-functional-review-repro/`。脚本依赖该层级推导仓库根路径。不要直接在本次已有合成 Workspace 上重新运行初始数据导入，以免同名条目影响断言。

在第一个终端从仓库根启动：

```powershell
$env:PYTHONIOENCODING='utf-8'
python -u .scratch/verify/agent-functional-review-repro/serve_review.py
```

它创建独立数据根、本机模型/MCP 服务和当前源码工作台，端口写入同目录 `server-info.json`。在另一个终端按顺序运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
python -u .scratch/verify/agent-functional-review-repro/http_checks.py
python -u .scratch/verify/agent-functional-review-repro/supplement_checks.py
python -u .scratch/verify/agent-functional-review-repro/final_checks.py
python -u .scratch/verify/agent-functional-review-repro/long_context_review.py
python -u .scratch/verify/agent-functional-review-repro/unadapted_sources_review.py
```

脚本分阶段输出并保存断言结果，失败断言未必表现为非零进程退出码，应读取最后的 JSON 总结与 `final-audit-results.json`。中间阶段包含报告已说明的脚本修正与预算/有界模型复核，不把中间误报视为产品问题。

普通全量与 UI 命令详见项目 Agent 文档。浏览器执行需要 Playwright；设置 `NODE_PATH` 指向可用依赖，并使用 Edge。界面截图为真实页面，不是设计图。
