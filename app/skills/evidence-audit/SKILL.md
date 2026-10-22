---
name: evidence-audit
description: 审核研究回答、笔记、公式、实验数字或职责分工是否被原文支持。适用于纠错、溯源、口径核查；普通闲聊不使用。
metadata:
  version: "1.0"
allowed-tools: kb_search kb_read lit_context pdf_read evidence_read plan_update
---

先定位待核查的断言和原始来源；只有笔记节选时不能声称读过原文。
按需读取 references/checklist.md，逐条建立“断言、原文证据、页码、判定、修正”表。
准确标题优先 kb_read，沿 links 找原文，PDF 每次最多五页；分批读取所需页码。
区分原文直接支持、跨来源推断、工程建议和证据不足，不把二手笔记当成作者结论。
核查公式的单位、基准和假设；区分可行动作、可行状态和最终工程有效性。
不得把超时、不收敛或计算失败直接解释为不可行；模型生成候选也不是物理校验通过。
交付具体修正和可点击的 [[真实标题]] 及页码。默认只说明问题，不修改知识库；用户要求修订时再走写入流程。
