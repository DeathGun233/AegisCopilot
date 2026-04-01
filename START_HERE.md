# AegisCopilot 当前版本入口

这份文档是当前版本最短上手说明，适合你每次启动项目时先看一遍。

## 现在已经具备的能力

- 真实登录态与管理员权限控制
- 企业知识库问答与流式回答
- 文档上传、异步索引、重建与删除
- 阿里云 DashScope 模型与 Embedding 接入
- 查询理解、混合检索与引用回答
- Trace 观测与离线评测

## 推荐启动端口

- 后端：`8002`
- 前端：`5173`

## 后端启动

```powershell
cd D:\codex_create\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

验证：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
```

## 前端启动

```powershell
cd D:\codex_create\frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

打开：

```text
http://127.0.0.1:5173
```

## 默认账号

- 管理员：`admin / admin123`
- 成员：`member / member123`

## 推荐体验路线

1. 用管理员账号登录。
2. 进入知识库后台上传文档。
3. 等待异步索引完成，确认任务状态正常。
4. 打开聊天页，体验底部输入式对话。
5. 再到 Trace 页查看一次完整问答链路。

## 你接下来最该看的文档

- [快速启动与运维手册](D:/codex_create/docs/10-quickstart-and-ops.md)
- [Windows 启动排障](D:/codex_create/docs/11-windows-startup-troubleshooting.md)
- [项目背景](D:/codex_create/docs/01-project-background.md)
- [整体架构](D:/codex_create/docs/02-architecture.md)
