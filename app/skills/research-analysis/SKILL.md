---
name: research-analysis
description: 规划科研实验、使用 Python 分析数据、验证计算和生成结果文件，适用于可复现研究分析。
allowed-tools: plan_update workspace_list workspace_read python_run memory_recall memory_remember
compatibility: 执行 Python 需要启用代码运行，并安装 Docker 及本地 Python 容器镜像。
---

先写任务计划与验收条件，核对数据来源、单位、缺失值和指标口径。
通过 workspace_list/workspace_read 检查输入，python_run 的 files 参数显式选择要复制到隔离环境的文件。
程序只读取 /input，结果写到 /output。报告随机种子、计算步骤、输入路径和产物路径。
用独立计算或简单边界例子核对关键结果，不能把程序成功退出当成科研结论正确。
工具报告不可用时解释具体依赖，不声称已运行。完成后更新计划并给出可复现步骤。
