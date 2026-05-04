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
{"status":"ok","provider":"openai-compatible","model":"qwen3-max"}
```

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

## 6. Qwen rerank 默认配置

当前 rerank 默认使用 Qwen `qwen3-vl-rerank`。启动后端前建议设置 DashScope API Key：

```powershell
$env:AEGIS_RERANK_PROVIDER = "qwen"
$env:AEGIS_RERANK_MODEL = "qwen3-vl-rerank"
$env:AEGIS_RERANK_API_KEY = "<你的 DashScope API Key>"
```

然后再启动后端：

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

如果没有设置 `AEGIS_RERANK_API_KEY`，系统会保留启动能力，并在 rerank 阶段 fallback 到本地 heuristic；这只是降级兜底，不再是默认设计。

如果确实需要临时禁用 Qwen rerank，可以显式设置：

```powershell
$env:AEGIS_RERANK_PROVIDER = "heuristic"
```
