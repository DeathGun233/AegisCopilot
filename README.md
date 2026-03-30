# AegisCopilot

AegisCopilot 是一个面向企业知识库问答的 AIAgent 学习项目。当前版本已经可以作为求职作品和面试演示项目使用，覆盖了知识库上传、RAG 问答、流式回答、模型切换、会话管理、知识库治理、用户角色切换和离线评估。

## 当前已实现功能

- 企业知识库问答
- 文档上传并自动抽取文本
- 文档自动建立索引
- 新建会话与删除历史会话
- 删除知识库文档并同步清理索引
- 流式回答
- 阿里云 DashScope OpenAI 兼容 API 接入
- 前端切换模型
- 轻量用户角色切换
- 知识库后台筛选与管理视图
- 文档详情与后台筛选型接口
- 离线评估

## 目录结构

- `backend/`
  FastAPI 后端，负责对话、文档、索引、模型切换、流式输出、评估接口
- `frontend/`
  React + Vite 前端，负责聊天页、知识库页、评估页、模型切换
- `evaluation/`
  离线评估脚本与样例问答集
- `docs/`
  项目背景、架构设计、部署说明、面试讲解材料

## 推荐启动端口

- 后端：`8002`
- 前端：`5177`

## 环境要求

- Python 3.11
- Node.js LTS
- 阿里云 DashScope API Key

项目会自动读取以下任意一个环境变量：

- `AEGIS_LLM_API_KEY`
- `OPEN_AI_KEY`
- `OPENAI_API_KEY`

## 关键环境变量

参考 [.env.example](D:/codex_create/.env.example)：

```env
AEGIS_ENV=local
AEGIS_TOP_K=5
AEGIS_MIN_GROUNDING_SCORE=0.18
AEGIS_LLM_PROVIDER=openai-compatible
AEGIS_LLM_MODEL=qwen3-max
AEGIS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AEGIS_LLM_API_KEY=
```

## 快速启动

### 后端

```powershell
cd D:\codex_create\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

启动后先验证：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
```

### 前端

```powershell
cd D:\codex_create\frontend
npm.cmd install
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

浏览器打开：

```text
http://localhost:5177
```

## 当前支持的模型

- `qwen3-max`
- `qwen-max`
- `qwen-plus`
- `qwen-turbo`

推荐：

- 面试演示：`qwen3-max`
- 平时开发：`qwen-plus`
- 追求速度：`qwen-turbo`

当前模型选择会持久化保存在：

```text
backend/storage/runtime_model.json
```

## 知识库说明

### 支持上传的文件

- `txt`
- `md`
- `markdown`
- `pdf`
- `docx`

上传后后端会自动抽取文本并建立索引。

### 删除文档

如果上传错文档，知识库页现在支持直接删除。

删除时会同步清理：

- 文档元数据
- 对应 chunk
- 检索链路中的相关内容

这样可以避免脏数据持续污染知识库。

## 关键接口

- `GET /health`
- `GET /system/stats`
- `GET /models`
- `POST /models/select`
- `GET /documents`
- `POST /documents/upload`
- `DELETE /documents/{document_id}`
- `GET /conversations`
- `POST /conversations`
- `DELETE /conversations/{conversation_id}`
- `POST /chat`
- `POST /chat/stream`
- `POST /evaluate/run`

## 推荐演示流程

1. 打开管理后台并上传一份业务文档
2. 说明系统支持自动抽取 PDF / DOCX / Markdown
3. 展示知识库筛选、用户身份切换和后台治理能力
4. 切到聊天页，新建对话
5. 提一个制度类问题，展示流式回答
6. 切换模型到 `qwen3-max`
7. 删除一份错误文档，展示知识库治理能力
8. 最后运行离线评估，讲系统化验证思路

## 常见问题

### PowerShell 无法执行 `Activate.ps1`

这不是虚拟环境损坏，而是 PowerShell 执行策略限制。推荐直接使用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

### PowerShell 里 `npm` 不可用

优先使用：

```powershell
npm.cmd install
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

### 页面提示“连接模型失败”

优先检查：

- 后端是否启动
- `OPEN_AI_KEY` 是否存在
- `http://127.0.0.1:8002/health` 是否正常
- `http://127.0.0.1:8002/models` 是否能返回模型目录

## 文档导航

- [快速开始](D:/codex_create/QUICKSTART.md)
- [当前版本运行与运维手册](D:/codex_create/docs/12-current-runbook.md)
- [Windows 启动排障 v2](D:/codex_create/docs/13-windows-troubleshooting-v2.md)
- [历史快速启动与运维手册](D:/codex_create/docs/10-quickstart-and-ops.md)
- [历史 Windows 启动排障](D:/codex_create/docs/11-windows-startup-troubleshooting.md)
- [项目背景](D:/codex_create/docs/01-project-background.md)
- [整体架构](D:/codex_create/docs/02-architecture.md)
- [RAG 设计](D:/codex_create/docs/03-rag-design.md)
- [Agent 工作流](D:/codex_create/docs/04-agent-workflow.md)
- [评估说明](D:/codex_create/docs/05-evaluation.md)
