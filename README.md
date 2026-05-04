# AegisCopilot

本地启动请优先看：[本地启动指令](docs/16-local-startup.md)。

AegisCopilot 是一个面向企业知识库问答的 RAG Agent 学习项目。当前版本已经具备真实登录鉴权、知识库治理、混合检索、DashScope Embedding、查询理解、Trace 观测、离线评测和异步索引等能力，适合作为求职作品与面试演示项目。

## 当前能力

- 真实登录态与管理员权限控制
- 企业知识库问答与流式回答
- 文档上传、手动录入、删除与重建索引
- 阿里云 DashScope OpenAI 兼容模型接入
- 真实 Embedding 向量检索与混合召回
- 查询改写、扩展召回与澄清判断
- 文档详情、任务状态与向量版本治理
- Trace 观测后台与离线评测
- 异步索引任务与批量向量补建

## 目录结构

- `backend/`
  FastAPI 后端，负责鉴权、对话、检索、索引、评测与后台接口
- `frontend/`
  React + Vite 前端，负责聊天工作台、知识库后台、观测页与评测页
- `evaluation/`
  离线评测样例与输出报告
- `docs/`
  项目背景、架构设计、部署说明与面试讲解材料

## 推荐启动端口

- 后端：`8002`
- 前端：`5173`

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
AEGIS_EMBEDDING_PROVIDER=dashscope
AEGIS_EMBEDDING_MODEL=text-embedding-v4
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
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开：

```text
http://127.0.0.1:5173
```

## 默认演示账号

- 管理员：`admin / admin123`
- 成员：`member / member123`

## 核心页面

- 聊天工作台：发起提问、查看流式回答、管理个人会话
- 知识库后台：上传文档、筛选文档、查看详情、重建索引
- 检索总览：调整召回参数、批量补建向量、查看系统统计
- Trace 观测：排查问答过程、查看引用与推理链路
- 评测中心：运行样例集并查看离线评测结果

## 当前支持的模型

- `qwen3-max`
- `qwen-max`
- `qwen-plus`
- `qwen-turbo`

推荐：

- 面试演示：`qwen3-max`
- 日常开发：`qwen-plus`
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

上传后系统会自动抽取文本并进入异步索引队列。索引完成后，文档片段会写入知识库并补齐向量。

### 向量与索引治理

- 后台支持单篇重建索引
- 支持批量补建缺失向量
- 支持批量升级过期向量版本
- 文档详情页可查看最近任务、片段数量和向量版本状态

## 关键接口

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /system/stats`
- `GET /models`
- `POST /models/select`
- `GET /documents`
- `POST /documents/upload`
- `POST /documents/{document_id}/reindex`
- `POST /documents/reindex-batch`
- `GET /documents/upload/tasks/{task_id}`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `POST /chat`
- `POST /chat/stream`
- `POST /evaluate/run`

## 推荐演示流程

1. 先用管理员账号登录，进入知识库后台。
2. 上传一份业务文档，展示异步索引与任务状态。
3. 在总览页展示向量补建、检索参数与当前 Embedding 版本。
4. 切到聊天页，新建会话并提一个制度类问题。
5. 展示流式回答、引用片段和底部输入式对话体验。
6. 切到 Trace 页，说明查询改写、检索与 grounded 判断。
7. 最后运行离线评测，说明系统化验证思路。

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
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

### 页面提示“连接模型失败”

优先检查：

- 后端是否启动
- `OPEN_AI_KEY` 或 `AEGIS_LLM_API_KEY` 是否存在
- `http://127.0.0.1:8002/health` 是否正常
- `http://127.0.0.1:8002/models` 是否能返回模型目录
