# Agent 功能测试问题清单

执行日期：2026-10-22；整理及源码哈希复核：2026-10-23。  
基线：v261022.1 当前源码，包含「本轮参考」新增实现。  
完整覆盖与通过结果见 [复测报告](agent-functional-retest-2026-10-23.md)。本次未修改业务代码或修复以下问题。

## AG-01 · P2 · 资料读取来源漏记，并误报记录完整

**影响：** 用户无法据「本轮参考」判断 Agent 实际获得的全部资料。阅读真实 PDF 或研究文本后，界面仍称「本轮未提供知识资料」，而非提示适配缺失。

**复现：**

1. 在隔离 Workspace 中创建含 `QA-FILE-SOURCE-73` 的文本文件。
2. 让 Agent 调用 `workspace_read` 读取该文件，随后生成回答。
3. 检查服务端工具执行成功，模型第二次 HTTP 请求的工具消息包含该标记。
4. 查询该回答的 sources 接口，打开其「本轮参考」。
5. 使用含 `QA-PDF-SOURCE-73` 的可提取文本 PDF，并经正常文献注册及 `pdf_read` 读取，重复上述检查。

两条链路均复现，第二条同时做了真实宽屏 UI 核验。

**实际结果：**

```json
{
  "recording_status": "complete",
  "provided_source_count": 0,
  "cited_source_count": 0,
  "counts_by_kind": {}
}
```

来源列表与 warnings 为空。工具轨迹分别显示 `workspace_read`、`pdf_read` 执行成功，且实际 HTTP 内容能证明正文已进入模型请求。

**预期：**

- 已适配时：保留文件或 PDF 实体、实际发送片段、版本和位置，按实体计算提供来源。
- 尚未适配时：至少返回 incomplete 及工具覆盖说明，界面显示「来源记录不完整」。
- 不能以 complete + 0 将未采集的资料等同于未提供。

**代码定位：**

- [app/agent_sources.py](../app/agent_sources.py)：`tool_message()` 的适配分支与 `_source_incomplete` 判断。当前没有 `workspace_read`、`pdf_read` 分支，也没有为这两者设置不完整标记。
- [app/agent_research.py](../app/agent_research.py)：两种读取工具确实返回 `content` 或 `pages[].text`；可以作为适配输入。
- 同一完整性判断中使用 `web_read`，实际注册工具为 `web_fetch`。这是代码审查发现的同类风险；本轮未独立进行公开网页端到端验证，不作为第三条实测缺陷计数。

**修复建议：**

1. 先为所有明确返回研究正文、但未适配的读取工具标记 incomplete。
2. 增加 PDF 按页、文件按版本/字符范围的结构化来源映射。
3. 为注册工具声明资料读取/控制/写入类别，使用覆盖契约测试检查所有资料读取工具，避免维护不完整的名称黑名单。

**修复验收：** 两个标记都确实进入真实模型 HTTP；对应来源具备准确快照，或以明确 incomplete 降级。重试、压缩、`evidence_read` 和历史回看不得恢复为虚假的 complete + 0。

证据：[完整 JSON](retest-evidence-agent-2026-10-22/source-coverage-gap.json)、[复现脚本包](retest-evidence-agent-2026-10-22/isolated-http-reproduction-v2.zip)。

![实际 PDF 读取后的错误零来源状态](retest-evidence-agent-2026-10-22/pdf-source-gap-wide.png)

## AG-02 · P2 · self_check 的 HTTP 测试替身签名落后

**分类：** 测试基础设施回归。当前主业务 HTTP 链路已由其他用例验证，不将此项误记为所有 Agent 请求均失败。

**复现命令：**

```powershell
python tools/self_check.py
```

**实际结果：** 退出码 1。进入 Agent 发送检查后抛出：

```text
TypeError: main.<locals>.fake_http() got an unexpected keyword argument 'source_recorder'
```

**原因：**

- [tools/self_check.py](../tools/self_check.py) 中 `fake_http()` 仍只接收到 `extra_headers`。
- [app/agent.py](../app/agent.py) 的 `_http_json()` 已新增 `source_recorder`，而 `_post_chat()` 会传入此命名参数。

**预期与修复：** 更新测试替身的兼容签名，例如显式接收 `source_recorder=None`，并按测试目标处理记录生命周期。重新运行整个 self_check，不能只绕过 Agent 步骤或吞掉异常。

**影响：** 常用的完整自检入口中断，Agent 及后续检查不能由该入口完成；会阻塞依赖此命令的开发验收。

证据：[完整自检日志](retest-evidence-agent-2026-10-22/self-check.log)。
