# AegisCopilot 快速开始

这份文档对应当前可直接运行和演示的版本。

## 当前版本功能

- 企业知识库问答
- 文档上传并自动抽取文本
- 自动建立知识库索引
- 新建会话与删除历史会话
- 删除错误文档并同步清理索引
- 流式回答
- 阿里云 DashScope OpenAI 兼容模型接入
- 模型切换
- 轻量用户角色切换
- 知识库后台管理
- 离线评估

## 推荐启动端口

- 后端：`8002`
- 前端：`5177`

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
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

### 打开页面

```text
http://localhost:5177
```

## 启动后检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
```

正常时你会看到：

- `provider: openai-compatible`
- 当前模型，例如 `qwen3-max`

## 推荐使用顺序

1. 进入管理后台上传一份业务文档
2. 确认文档已经进入知识库列表
3. 切回聊天工作台，新建会话
4. 选择模型，推荐 `qwen3-max`
5. 提一个制度类问题，观察流式回答
6. 删除一份错误文档，验证知识库治理能力
7. 运行离线评估，展示工程化闭环

## 当前主要页面

- 聊天工作台：提问、流式回答、会话管理
- 管理后台：上传文档、删除文档、知识库筛选、身份切换
- 评估中心：查看离线评估结果

## 支持的模型

- `qwen3-max`
- `qwen-max`
- `qwen-plus`
- `qwen-turbo`

推荐：

- 面试演示：`qwen3-max`
- 日常开发：`qwen-plus`
- 追求速度：`qwen-turbo`

## 继续阅读

- `README.md`
- `docs/12-current-runbook.md`
- `docs/13-windows-troubleshooting-v2.md`
