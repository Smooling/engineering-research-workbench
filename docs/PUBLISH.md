# 发布到 GitHub · 检查清单与命令

本文是**上传前的操作手册**。工作台本身的用法见 [`../README.md`](../README.md) 与
[`manual/`](manual/README.md)；结构与决策见 [`OVERVIEW.md`](OVERVIEW.md)。

## 一、上传前会自动检查什么（已在本仓库做过，结果如下）

| 检查 | 结论 |
| --- | --- |
| 是否跟踪密钥 / `config/` | ✅ `config/` **完全未跟踪**（`secrets.json` 从未入库）；跟踪文件里无 `sk-…` 形态的密钥 |
| 历史里最大的对象 | ✅ **2.45 MB**（`web/vendor/mermaid.min.js`）；无 >50 MB 对象（GitHub 单文件上限 100 MB） |
| `.git` 体积 | ✅ **约 10 MB**，430 个被跟踪文件 |
| 用户数据是否被跟踪 | ✅ 当前 **0 个** `Workspace/` 文件（`.gitignore` 里 `Workspace/`） |
| 构建产物 / 大备份 | ✅ `*.exe`、`build/`、`*.zip` 都不入库（手工备份已移出仓库到同级 `engineering-research-workbench-archive/`） |

### ⚠️ 一个需要你决定的历史残留
`git` **历史里**仍有 **11 个** `Workspace/` 对象（合计 **0.24 MB**）：1 张 Agent 会话附件截图（244 KB）
与 `todos.json` / `activity.jsonl` / `migration.json` / `README.md`。它们是**早期**（`.gitignore` 加
`Workspace/` 规则之前）提交的，现在已不再跟踪，但**仍在历史里**。
另有 4 个历史 `config/*.json`（约 5 KB，只有设置项，**无密钥值**）。

- 若仓库设为 **private**：可以不动。
- 若**公开**：建议先清历史（下面第三条），否则 clone 的人能翻到那张截图与待办内容。

## 二、最简上传（保留全部历史）

```powershell
cd D:\Project\engineering-research-workbench
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git branch -M main
git push -u origin main
```

> push 前确认 `.gitignore` 生效：`git status --short` 里不应出现 `Workspace/`、`config/`、`*.zip`、`*.exe`。

## 三、清掉历史里的用户数据（公开仓库建议做）

**先备份**（可回滚；备份 `.git` 等价于备份全部历史）：

```powershell
# 1) 备份当前仓库（含 .git）
git bundle create ..\erw-backup-$(Get-Date -Format yyyyMMdd).bundle --all

# 2) 从所有提交里移除 Workspace/ 与 config/（工作区文件**不动**，只改历史）
git filter-branch --force --index-filter `
  "git rm -r --cached --ignore-unmatch Workspace config" `
  --prune-empty --tag-name-filter cat -- --all

# 3) 清理引用与垃圾
git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 4) 复核：应输出 0
(git rev-list --objects --all | Select-String '^.* Workspace/').Count
```

注意：`filter-branch` 会**重写所有提交 SHA**（本地无远端，代价仅为 SHA 变化）。
如装了 [`git-filter-repo`](https://github.com/newren/git-filter-repo)（更快、更安全），等价命令：

```powershell
git filter-repo --path Workspace --path config --invert-paths
```

## 四、上传后本地怎么用（不影响日常）

- CI（`.github/workflows/ci.yml`）只跑**不依赖本机数据**的部分：静态闸门（`kb_smoke` /
  `web_check` / `web_manifest --check` / `plugin_check` / `core.plugins verify` / `mcp.server --selftest`）
  与 13 个纯逻辑用例；
- **需要浏览器与真实知识库的 25 个用例**在本地跑完整档：

```powershell
python tools/run_tests.py            # 全量（含 25 个浏览器用例，约 4 分钟）
python tools/run_tests.py --fast     # 纯逻辑（13 个，约 13 秒）
python tools/performance_benchmark.py --assert-budget   # 热路径预算（防 /api/docs 退化）
```

## 五、发布前最后一眼

- [ ] `python tools/run_tests.py` 全绿（本机）
- [ ] `python -m core.doctor` error = 0
- [ ] `git status --short` 没有 `Workspace/`、`config/`、大文件
- [ ] README 顶部链接可达（`docs/OVERVIEW.md`、`docs/manual/README.md`）
- [ ] 仓库可见性（public/private）与第三条的取舍一致
- [ ] LICENSE 与你的发布意图一致（当前为 `LICENSE.txt`）
