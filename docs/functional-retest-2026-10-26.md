# 全面功能复测 · 2026-10-26

复测对象为 `v261026.1` 当前源码工作区及现有未提交修改。本轮未修改业务源码；测试前后校验了 123 个源码、测试与版本文件，内容无变化。测试使用隔离数据目录和临时 HTTP 服务。

**结论：FR-01、03、04、05、06、07、08 的原始问题均已通过复测；FR-02 按要求保留，仍可复现。另确认 1 项本轮新发现的问题 FR-09：直接附件文献重建关联后，已保存批注不再显示。** 因此不能判定所有功能问题已清零。FR-09 不等同于已经修复的“共享 PDF 原件被移动”问题；本轮未对修复前代码执行该场景，不能断言它由此次修改引入。

## 原问题逐项复验

| 编号 | 结论 | 本轮验证 |
| --- | --- | --- |
| FR-01 | 通过 | 同名不同内容拒绝迁移，原内容与配置保留；同名相同内容复用；复制中断、文档回写失败、配置提交失败和模拟不可写均有恢复用例 |
| FR-02 | 保留 | 真实双窗口中 A 保存新题名，B 仅修改作者后保存，题名仍回退为旧值 `audit` |
| FR-03 | 通过 | 草稿进入未保存检查；切换页签/批注、收起编辑器、取消离开、保存后离开、丢弃、保存失败、Ctrl+S、刷新保护通过；另测删除带草稿的批注能清除未保存状态 |
| FR-04 | 通过 | PDF 迁移更新所有附件引用；文档附件接口和阅读器均返回原字节；迁移后重建仍可读 |
| FR-05 | 通过 | 单篇、全量、重复重建后共享原文件保留，其他引用可读；同名但不同路径的附件不会错误合并 |
| FR-06 | 通过 | 直接附件、导入、绑定旧文献三种路径保留阅读位置；配置重载、索引重建后保留；直接附件登记后继承页码 |
| FR-07 | 通过 | 非法项目名、状态、显示状态均不发生部分更新；目录改名、任务及 registry 写入失败可恢复目录与关联 |
| FR-08 | 通过 | 置顶与收藏双向一致，取消置顶后不再被 registry 旧收藏值覆盖 |

原始审查脚本沿用原断言复跑，未删除 FR-02 的失败断言，也未放宽修复项的预期。新增正式回归的 11 个测试包含在 240 个测试总数内。

## FR-09 · P2：重建关联后已保存批注不可见

位置：[app/literature.py:424](E:/PyProgram/workbench_test/engineering-research-workbench/app/literature.py:424)，`rebuild_registry()` 生成新的 `paper_id`；批注读取仍按 [annotation_path()](E:/PyProgram/workbench_test/engineering-research-workbench/app/literature.py:784) 的文献 ID 定位。

复现步骤：

1. 创建文献，附件直接指向现有 PDF，尚未登记进 PDF registry；此时阅读器使用 `entry-<doc_id>`。
2. 在阅读器保存一条批注，确认可见。
3. 在“设置 → 文献 / PDF”点击“重建关联”并确认；接口成功返回 200。
4. 重新打开该文献，批注页显示“当前已加载页面暂无批注”。

实际结果：登记后的文献获得新的 UUID，查询新 ID 的批注返回空数组。旧 `entry-*` 的批注数据仍在，查询旧 ID 还能读到原批注。PDF 字节与文档 ID 保持不变，阅读页码已正确继承；配置重载、索引重建和再次登记不能恢复批注可见性。已分别通过单篇重建接口和设置页的全量重建操作确认。

原因：重建迁移了 PDF 附件路径，并补充了阅读位置继承，但没有迁移或映射旧 ID 下的批注。界面所承诺的“批注与笔记不受影响”在这个场景不成立。这里确认的是批注关联丢失，未证明底层批注文件被删除。

建议：登记时保持文献侧的稳定批注身份，或原子迁移旧 `entry-*` 批注及相关预览引用到新 ID；兼容已经发生登记的旧数据。不要只复制阅读页码。验收需覆盖单篇、全量、重复重建、重启后读取，以及带截图批注的图片引用。

证据：[重建前](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/lifecycle-before-rebuild.png)、[重建后](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/lifecycle-after-rebuild.png)、[接口结果](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/lifecycle-results.json)、[真实浏览器结果](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/lifecycle-ui-results.json)。截图中 PDF 页面为空白是四页合成测试文件的设计。

## 完整执行结果

| 测试 | 结果 | 证据 |
| --- | --- | --- |
| Python 全量测试 | **240 / 240 通过**，254.170 秒，无跳过；启用功能、排期、条目导航、悬停预览浏览器开关 | [python-tests.log](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/python-tests.log) |
| 自检 | **15 组通过**，包含 Python/JavaScript 语法检查 | [self-check.log](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/self-check.log) |
| 独立界面专项 | **8 / 8 通过**：工作台、Agent、来源、文献、排期、引用、PDF 显示、概览 | [ui-summary.json](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/ui-summary.json) |
| 原始补充 HTTP 复现 | **61 / 61 断言通过**，另有 1 条迁移响应观测；结果文件共 62 行记录 | [supplemental-results.json](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/supplemental-results.json) |
| 原始补充浏览器复现 | **6 / 7 通过**；唯一失败为明确保留的 FR-02 | [supplemental-ui-results.json](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/supplemental-ui-results.json) |
| 新增连续操作检查 | HTTP **8 / 10**，浏览器 **5 / 7**；4 条失败均归于 FR-09，另有 1 条浏览器脚本完成状态记录 | [lifecycle.log](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/lifecycle.log) |

本轮引用预览专项一次通过，未重现上轮的边界断言波动。浏览器专项按顺序执行；全量测试与部分独立专项时间重叠。补充复现脚本记录失败后继续执行，因此其退出码 0 只表示检查执行完成，不能替代 JSON 中的断言结果。

覆盖范围包括六类资料 CRUD、修订冲突、类型转换与导航、检索与图谱、项目与待办、排期、文献导入/阅读/批注/笔记/存储、Agent 流式任务与来源、计费、专注、设置、同步冲突与附件传输、桌面退出保护。Agent 外部模型和天气等依赖按测试夹具模拟或隔离；未验收真实付费模型效果、跨机器生产同步、Docker 部署和打包 EXE 的人工操作。

## 性能抽样

隔离生成 3,000 篇文档、9,000 条关系，热操作各测 3 次；下列为中位数，冷初始化仅测一次。该抽样用于发现明显阻塞，不是受控版本性能对比。

| 操作 | 毫秒 |
| --- | ---: |
| 冷初始化 | 4,937.59 |
| 50 条分页 | 11.41 |
| 按 ID 打开 | 8.15 |
| 全文搜索 | 81.01 |
| 概览 | 120.13 |
| 初始 300 节点图 | 49.32 |
| 保存单文档 | 45.16 |
| 无变化文件同步 | 335.96 |

结果：[performance.json](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/performance.json)。运行命令、脚本和全部日志见[证据索引](E:/PyProgram/workbench_test/engineering-research-workbench/docs/retest-evidence-functional-2026-10-26/README.md)。
