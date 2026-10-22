"""插件运行时（内核侧）。

当前阶段只做**发现 / 校验 / 依赖解析 / 状态报告**：`plugin.json` 的契约在
``manifest.py``，发现与状态机在 ``registry.py``，CLI 在 ``__main__.py``。

尚未实现（等第一个真插件落地）：`core_api` 门面、`register(ctx)` 执行、路由/MCP 工具/前端面板
的挂载与卸载、隔离不变量 I3/I4/I8/I10 的运行期校验。在那之前状态只报 `available`，
不谎报 `enabled`（见 ``registry.STATE_LABELS``）。

规范：[docs/PLUGIN_SPEC.md](../../docs/PLUGIN_SPEC.md) 与 [docs/REFACTOR_PLAN.md](../../docs/REFACTOR_PLAN.md) §6。
"""
