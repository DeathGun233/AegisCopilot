# AegisCopilot 快速开始

这份文档对应当前可直接运行和演示的版本。

## 当前版本能力

- 真实登录鉴权与管理员后台
- 企业知识库问答与流式回答
- 文档上传、删除、异步索引与重建
- 阿里云 DashScope 模型与 Embedding 接入
- 混合检索、查询理解与澄清判断
- Trace 观测与离线评测

## 推荐启动端口

- 后端：`8002`
- 前端：`5173`

## 启动步骤

### 后端

```powershell
cd D:\codex_create\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

### 前端

```powershell
cd D:\codex_create\frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

### 打开页面

```text
http://127.0.0.1:5173
```

## 默认账号

- 管理员：`admin / admin123`
- 成员：`member / member123`

## 启动后检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
```

正常时你会看到：

- `provider: openai-compatible`
- 当前模型，例如 `qwen3-max`

## 推荐演示顺序

1. 用管理员账号登录并进入知识库后台。
2. 上传一份业务文档，确认文档进入异步索引任务。
3. 在总览页查看向量补建、检索参数和系统统计。
4. 切回聊天工作台，新建会话并发起提问。
5. 观察流式回答、引用片段和底部输入式聊天体验。
6. 进入 Trace 页查看改写、检索与 grounded 结果。
7. 最后运行离线评测，展示工程化闭环。

## 当前主要页面

- 聊天工作台：提问、查看流式回答、管理个人会话
- 管理后台：上传文档、治理索引、查看任务与系统状态
- 观测页：查看问答 trace 与引用证据
- 评测中心：运行样例集并查看离线评测结果

## 继续阅读

- `README.md`
- `docs/12-current-runbook.md`
- `docs/13-windows-troubleshooting-v2.md`
