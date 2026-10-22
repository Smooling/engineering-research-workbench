# 技能包契约

SKILL.md：YAML frontmatter 包含 name、description，可含 allowed-tools（空格分隔或数组）、metadata.version、license、compatibility。其后为 Markdown 工作流程。

agents/openai.yaml 可选：interface.display_name、short_description、default_prompt；policy.allow_implicit_invocation 为 false 时只允许用户通过 $名称 明确调用。

所有资源路径相对技能根目录。单文件最多 2 MB，最多 128 文件，总计最多 20 MB。
脚本入口在 scripts/ 下；skill_run 的 args 是字符串数组；输入位于 /input、资源位于 /input/skill、产物位于 /output。

验收覆盖：明确调用、匹配任务自动加载、无关任务不加载、能力关闭、缺少依赖、资源路径越界、失败不误报完成。
