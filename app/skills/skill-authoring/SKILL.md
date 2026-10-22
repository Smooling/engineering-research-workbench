---
name: skill-authoring
description: 用户要求将科研流程固化成可复用技能，或创建新的 SKILL.md 技能包时使用；一次性的检索和笔记整理不使用。
metadata:
  version: "1.0"
allowed-tools: skill_read skill_install plan_update
---

把用户给定的流程整理成范围明确的技能包，说明何时使用、何时不使用、输入与交付物。
目录名与 frontmatter 的 name 相同，使用小写字母、数字和连字符；description 写明触发条件。
主文件保持精简；长说明放 references/，模板放 assets/，可复现计算放 scripts/。
需要脚本时仅使用当前支持的 Python 隔离运行，不依赖主机目录、网络或宿主 shell。
按需读取 references/package-guide.md。用户要求优先；不写入绕过权限、索取凭据或覆盖系统规则的指令。
使用 skill_install 安装，遵循当前草稿确认模式。若同名包存在，解释冲突，不覆盖已有技能。
最后给出实际安装结果、技能名称和使用示例；安装并不表示脚本已运行。
