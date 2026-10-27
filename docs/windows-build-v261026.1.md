# Windows 构建验证 · v261026.1

构建日期：2026-10-26。执行 `build_client.bat --no-pause`，复用 `build/.venv` 中的 Python 3.12.14 与 PyInstaller 6.22.3。包含紧凑参考面板、统一 Agent 设置入口和悬浮球贴边修复。

- 桌面生命周期单元回归：19 项通过。首次沙箱运行受临时目录写入和本地端口权限限制，沙箱外重跑全部通过。
- 实际打包 EXE：25 项检查通过，包含启动版本、六份关键前端资源与当前源码逐字节一致、统一设置入口、贴边样式与焦点修复，以及文件/PDF 读取、来源快照和本地模拟模型 API 链路。
- ZIP CRC、文件清单、SHA-256 校验通过；ZIP 中的 exe 与根目录产物一致，使用说明与当前文档一致。
- 验证使用独立数据目录和本地模拟模型；测试进程已退出。未执行完整原生窗口拖动/缩放冒烟，不据此对原生窗口交互作额外结论。
- 前端贴边专项已在此次源码修复中验证：资料面板关闭、桌面停靠与窄屏抽屉模式下的左右贴边、悬停展开、移开收起、键盘聚焦和可见半球点击区域均通过。

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| ResearchWorkbench.exe | 24325507 | `041308ca86bcea2807f8160cdc0849efde8abd893b91a15780c0bbe40d90ad56` |
| ResearchWorkbench-Windows-x64.zip | 24056321 | `c8bd15f0909fbce12c52bbbf80e7b75a7d104781a2b7cb59ded30457b46e94d9` |

构建清单：`dist/windows-build.json`。构建日志：`build_client.log`。本地验证结果：`.scratch/verify/exe-v261026.1/20261026-165859/verification.json`。

旧产物备份：`build/artifact-backup/v261023.1-before-v261026.1-20261026-165637/`。

日常源码更新后运行 `build_client.bat` 即可重建，无需为编译修改程序代码。升级时先通过托盘退出旧版，再运行新版；沿用 exe 同级的 `config/` 与 `Workspace/`。
