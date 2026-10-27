# Windows 构建验证 · v261023.1

构建日期：2026-10-23。使用 `build_client.bat --no-pause`，复用隔离环境中的 Python 3.12.14 与 PyInstaller 6.22.3。包含 Agent「本轮参考」、AG-01 文件/PDF 来源采集修复及 AG-02 自检兼容修复。

- 桌面生命周期单元回归：19 项通过。
- 来源专项与 Agent 系统回归：此前修复验证中共 83 项通过；完整自检及来源面板浏览器回归通过。
- 直接运行本次打包 EXE：17 项检查通过，包含启动版本、包内来源资源及缓存版本、文件/PDF 真实读取、标记进入本地模拟模型 HTTP、来源数量、完整状态、快照文字、版本与位置。
- ZIP CRC、文件清单及 SHA-256 校验通过。ZIP 仅包含 `ResearchWorkbench.exe`、`使用说明.md` 和 `LICENSE.txt`，程序与说明均与当前产物一致。
- 打包 EXE 的联调在独立数据目录中进行，模型请求仅发往本地模拟服务。验证进程已退出，现有 `config/` 和 `Workspace/` 未被构建或验证改写。
- 本次验证了 EXE 启动及实际 API 链路，未执行完整原生窗口拖动/缩放冒烟，不能据此认定此前记录的原生拖动检查问题已修复。

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| ResearchWorkbench.exe | 24325175 | `367582bd828c35a7b27255b14495b88d330120c3dfb214dc534d0aa237758802` |
| ResearchWorkbench-Windows-x64.zip | 24055395 | `bc800c766caf3c7c22c1e62737b08ecee0dfdf40e62d1d6db5b4aa9813b4c793` |

构建清单：`dist/windows-build.json`。构建日志：`build_client.log`。本机验证证据：`.scratch/verify/exe-v261023.1/20261023-110432/verification.json` 及同目录 `sources.json`。

旧版产物备份：`build/artifact-backup/v261022.1-before-v261023.1-20261023-105956/`。

升级时通过托盘退出旧版，再运行新版，继续使用 EXE 同级现有配置与知识库。
