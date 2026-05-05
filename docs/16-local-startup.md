# 本地启动指令

这份文档记录当前项目在 Windows PowerShell 下的本地启动方式。默认端口保持为：

- 后端 API：`http://127.0.0.1:8002`
- 前端页面：`http://127.0.0.1:5173`

前端默认会请求 `http://127.0.0.1:8002`，所以建议后端固定使用 `8002`。

## 1. 启动后端

在一个新的 PowerShell 窗口运行：

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

如果是第一次启动，或虚拟环境不存在，先执行：

```powershell
cd D:\codex_create\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

后端启动后验证：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
```

正常会返回类似：

```json
{"status":"ok","provider":"mock","model":"qwen3-max"}
```

`provider` 和 `model` 会随当前环境变量变化；本地快速启动默认使用 `mock`，不会调用外部 LLM。

## 2. 启动前端

在另一个新的 PowerShell 窗口运行：

```powershell
cd D:\codex_create\frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

如果是第一次启动，或 `node_modules` 不存在，先执行：

```powershell
cd D:\codex_create\frontend
npm.cmd install
```

前端启动后打开：

```text
http://127.0.0.1:5173
```

## 3. 登录账号

- 管理员：`admin / admin123`
- 普通成员：`member / member123`

## 4. 常用检查

查看端口是否被占用：

```powershell
Get-NetTCPConnection -LocalPort 8002,5173 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess
```

检查前端页面是否能访问：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173
```

检查后端接口是否能访问：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
```

## 5. 关闭服务

在启动后端或前端的 PowerShell 窗口按 `Ctrl+C` 即可关闭。

如果窗口已经关闭但端口仍被占用，先找到进程：

```powershell
Get-NetTCPConnection -LocalPort 8002,5173 -ErrorAction SilentlyContinue |
  Select-Object LocalPort,OwningProcess
```

再按实际 PID 结束进程：

```powershell
Stop-Process -Id <PID>
```

## 6. Milvus 可选启动

`.env.example` 默认使用本地向量存储，适合快速启动和离线验证。如果需要 Milvus，需要先启动 Docker Compose 中的 Milvus 依赖，并安装 Milvus 可选依赖：

```powershell
cd D:\codex_create
docker compose up -d postgres milvus-etcd milvus-minio milvus

cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m pip install -e .[milvus]
```

Milvus 检索还需要启用 embedding provider 并配置可用的 embedding key，例如：

```powershell
$env:AEGIS_VECTOR_STORE_PROVIDER = "milvus"
$env:AEGIS_EMBEDDING_PROVIDER = "openai-compatible"
$env:AEGIS_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:AEGIS_EMBEDDING_API_KEY = "<你的 DashScope API Key>"
```

Milvus 索引和查询参数可以显式配置，并会在 `/system/status` 的 vector provider detail 中展示：

```powershell
$env:AEGIS_MILVUS_METRIC_TYPE = "COSINE"
$env:AEGIS_MILVUS_INDEX_TYPE = "FLAT"
$env:AEGIS_MILVUS_INDEX_PARAMS = '{}'
$env:AEGIS_MILVUS_SEARCH_PARAMS = '{}'
```

## 7. Qwen rerank 配置

纯文本 RAG 推荐使用 Qwen `qwen3-rerank`。`qwen3-vl-rerank` 保留为可配置模型，用于未来多模态检索。启动后端前可以显式设置 DashScope rerank key：

```powershell
$env:AEGIS_RERANK_PROVIDER = "qwen"
$env:AEGIS_RERANK_MODEL = "qwen3-rerank"
$env:AEGIS_RERANK_API_KEY = "<你的 DashScope API Key>"
```

然后再启动后端：

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

如果没有设置 `AEGIS_RERANK_API_KEY` 或 `DASHSCOPE_API_KEY`，系统会保留启动能力，并在 rerank 阶段 fallback 到本地 heuristic，不会复用 `OPENAI_API_KEY` 或 `AEGIS_LLM_API_KEY` 发起 DashScope rerank 请求。

如果确实需要临时禁用 Qwen rerank，可以显式设置：

```powershell
$env:AEGIS_RERANK_PROVIDER = "heuristic"
```

## 8. DOCX/PDF 表格与 OCR

DOCX 表格会按 Markdown 表格写入索引文本；PDF 抽取会保留 `【第 N 页】` 页码标记，并对空格分隔的表格行做启发式 Markdown 表格转换。

图片 OCR 默认关闭。需要本地 OCR 时安装可选依赖和 Tesseract 运行时，然后启用：

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m pip install -e .[ocr]

$env:AEGIS_OCR_ENABLED = "true"
$env:AEGIS_OCR_LANGUAGES = "chi_sim+eng"
```

未启用或不可用时，系统会在抽取文本中保留图片占位标记，避免图片内容静默丢失。

## 9. 评测参数扫描

跨境物流黄金评测集位于 `evaluation/logistics_qa.json`，当前覆盖 80+ 条问题。可以用参数扫描脚本比较不同检索参数：

```powershell
cd D:\codex_create
.\backend\.venv\Scripts\python.exe evaluation\scan_parameters.py `
  --top-k 3,5,7 `
  --candidate-k 12,20,30 `
  --output evaluation\parameter_scan_report.json
```

报告会写出每组参数的 `retrieval_citation_accuracy`、`answer_citation_accuracy`、`recall_at_k`、`mrr`、`table_exact_match` 和 `version_accuracy` 等指标，并按指定 metric 标记最佳组合。
