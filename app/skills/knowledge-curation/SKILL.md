---
name: knowledge-curation
description: 从文献和对话提取术语、整理知识笔记、查重增补，维护可追溯的科研知识库。
allowed-tools: kb_search kb_read kb_create_entry kb_update_entry lit_context lit_note_write memory_recall memory_remember
---

新建知识笔记时可按需读取 assets/note-template.md；不要为了填满模板编造内容。
先提取概念并按共同原理分组，不把不同概念族拼为一个标题。每篇先检索查重。
命中已有条目时先完整分页读取，再增补；优先 append，覆盖时带读取结果中的 expected_version。
新条目遵循统一命名规则，正文包含摘要、原理、公式、方法与使用原因、场景、失效模式和来源。
每个数值与公式说明出处。引用须指向已检索到的真实条目、文献或页码。
草稿只是待写入内容，等待用户确认。只把稳定、可复用的信息存为记忆，附来源和作用域。
