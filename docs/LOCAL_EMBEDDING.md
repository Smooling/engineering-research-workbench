# 本地 Embedding 部署（RAG 语义检索）

> 用途：给工作台「设置 → RAG」提供本地 `/v1/embeddings` 接口，不需要外部 API、不产生费用。
> 当前部署：**BAAI/bge-small-zh-v1.5**（fastembed ONNX 版，512 维），实测在 RTX 4060 的机器上 CPU 推理即可。

## 一、为什么选这个模型

| 指标 | bge-small-zh-v1.5 |
| --- | --- |
| 参数量 | 24M（ONNX 文件约 91 MB） |
| 向量维数 | 512 |
| 语言 | 中文优化（中文科研笔记/文献题录匹配好） |
| 推理 | CPU 足够：706 个分块建索引约 30 秒；单次检索 1–3 ms |
| 依赖 | 只需要 `fastembed`（onnxruntime），不需要 torch / CUDA |

RTX 4060 8GB 跑它当然没问题，但没必要占显存；以后换更大的模型（bge-base-zh 768 维、bge-m3 1024 维）时再用 GPU。

## 二、安装与启动

```bash
# 只需一次
pip install fastembed

# 启动服务（默认 127.0.0.1:8800）
python tools/embedding_server.py --port 8800
```

- 模型缓存：`D:/Project/.models/fastembed`（约 91 MB，不会被临时目录清理；可用 `--cache-dir` 改）
- 首次启动会下载模型（约 10 秒），之后启动即加载
- 健康检查：`GET http://127.0.0.1:8800/health`

## 三、工作台配置（设置 → RAG）

| 字段 | 值 |
| --- | --- |
| 检索方式 | **混合（关键词 + 语义）**；纯语义可选 `semantic` |
| Embedding Base URL | `http://127.0.0.1:8800/v1` |
| Embedding 模型名称 | `BAAI/bge-small-zh-v1.5` |
| 向量维数 | `512` |
| 分块长度 / 重叠 | 1600 / 200（默认即可） |

保存后点「连接检查」→「更新资料索引」。当前实测：**230 份来源 / 706 个分块，约 30 秒**；之后资料改动只需「更新」，未变分块会复用已有向量。

## 四、验证

```bash
# 直接测服务
curl -X POST http://127.0.0.1:8800/v1/embeddings -H "Content-Type: application/json" \
  -d '{"model":"BAAI/bge-small-zh-v1.5","input":["红外暗弱目标检测"]}'

# 通过工作台检索（hybrid）
curl -X POST http://127.0.0.1:8765/api/agent/rag/search -H "Content-Type: application/json" \
  -d '{"query":"红外暗弱目标检测方法"}'
```

实测返回 8 条、score 0.73–0.76（文献题录 + 知识条目），「知识库条目怎么归类」能命中《知识-原理-知识库全局说明》。

## 五、注意事项

1. **服务要常驻**：工作台 RAG 依赖它；关掉服务后语义检索会失败（关键词模式仍可用）。可以把它加到开机启动，或用任务计划程序在登录时运行。
2. **端口**：默认 8800；被占用时换端口，并同步改工作台里的 Base URL。
3. **换模型**：模型名/维数变了要重新建索引（工作台会提示「配置已变化，请更新索引」）。
4. **PDF 正文**：RAG 设置里有「同时索引文献 PDF 正文」，需要时可打开（会多花一些建索引时间）。
5. 模型文件与缓存不在 git 里，换机器需要重新下载。
