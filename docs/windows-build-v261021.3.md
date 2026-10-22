# Windows 构建验证 · v261021.3

构建日期：2026-10-21。包含两轮功能修复，构建工具为隔离环境中的 Python 3.12.14 与 PyInstaller 6.22.3。

- 原生 EXE 桌面冒烟测试：73 项通过，包含 WebView2、托盘、缩放、保存保护、通知与快速重启。
- 直接访问打包 EXE 的 HTTP 服务：7 项通过，核验版本、修订冲突、完成别名、BibTeX 元数据导出、待办校验、Agent 排期 schema 及前端冲突处理。
- ZIP 完整性、清单及 SHA-256 校验通过；仅包含 EXE、使用说明和许可证。
- 使用独立测试数据目录；测试进程已清理。源代码回归记录见两份功能修复报告。

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| ResearchWorkbench.exe | 24276013 | `63cb2d84bdfc9dd3adf3283eb8a38e4a2363f0100c219ddc930b3928a38a94e7` |
| ResearchWorkbench-Windows-x64.zip | 24005750 | `4db2c18938cc502e64dc2f671be520821f41976d12f0e8e99385309876c57b16` |

构建清单：`dist/windows-build.json`。本机验证证据保存在 `.scratch/verify/exe-v261021.3/`；旧构建产物备份保存在 `build/artifact-backup/`。
