# Windows 启动排障 v2

这份文档记录当前版本在 Windows 下最常见的启动问题。

## 1. `.venv\Scripts\activate` 无法执行

常见报错：

- `PSSecurityException`
- 因为系统禁止执行脚本而无法运行 `Activate.ps1`

原因：

PowerShell 默认会执行 `Activate.ps1`，如果执行策略限制脚本，就会报错。

推荐做法：

不要依赖 `activate`，直接使用虚拟环境里的 Python。

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

## 2. `npm` 无法执行

常见原因：

- 没安装 Node.js
- Node.js 没加入环境变量
- `npm.ps1` 被 PowerShell 执行策略拦住

推荐做法：

直接使用 `npm.cmd`。

```powershell
cd D:\codex_create\frontend
npm.cmd install
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

检查方式：

```powershell
node -v
npm.cmd -v
```

## 3. 后端端口被占用

检查端口：

```powershell
cmd /c netstat -ano | findstr LISTENING | findstr :8002
```

结束旧进程：

```powershell
cmd /c taskkill /PID <pid> /F
```

## 4. 前端端口被占用

建议显式指定端口：

```powershell
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

## 5. 页面提示“连接模型失败”

按这个顺序检查：

1. 后端是否启动

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
```

2. 模型目录是否正常

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
```

3. 是否配置了阿里云 API Key

项目会自动读取：

- `AEGIS_LLM_API_KEY`
- `OPEN_AI_KEY`
- `OPENAI_API_KEY`

## 6. 为什么有时看起来“命令一直在跑”

这通常不代表程序死了，而是：

- `uvicorn` 是常驻进程
- `vite dev` 也是常驻进程
- Windows 下后台启动时，终端有时不会立刻返回

更可靠的判断方式是直接访问接口或页面，而不是只看终端是否退出。

## 7. 当前推荐的稳定命令

### 后端

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

### 前端

```powershell
cd D:\codex_create\frontend
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

### 健康检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
```
