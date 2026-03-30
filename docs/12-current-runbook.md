# 当前版本运行与运维手册

这份文档描述当前版本的运行方式、常用接口和日常操作建议。

## 当前能力

- 企业知识库文档上传
- 自动文本抽取与索引
- RAG 问答
- 流式回答
- 模型切换
- 会话管理
- 文档删除与知识库清理
- 用户角色切换
- 离线评估

## 推荐端口

- 后端：`8002`
- 前端：`5177`

## 后端启动

```powershell
cd D:\codex_create\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

## 前端启动

```powershell
cd D:\codex_create\frontend
npm.cmd run dev -- --host 0.0.0.0 --port 5177
```

## 关键健康检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/models
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/system/stats
```

## 关键接口

### 系统

- `GET /health`
- `GET /system/stats`
- `GET /models`
- `POST /models/select`

### 用户

- `GET /users`
- `GET /users/me`

### 会话

- `GET /conversations`
- `POST /conversations`
- `GET /conversations/{conversation_id}`
- `DELETE /conversations/{conversation_id}`

### 知识库

- `GET /documents`
- `GET /documents/{document_id}`
- `POST /documents`
- `POST /documents/upload`
- `POST /documents/index`
- `DELETE /documents/{document_id}`

### 问答

- `POST /chat`
- `POST /chat/stream`

### 评估

- `POST /evaluate/run`
- `GET /tasks/{task_id}`

## 知识库后台使用建议

1. 优先上传正式业务文档，不要把测试垃圾数据长期留在知识库中
2. 如果上传错误，直接在管理后台删除
3. 用搜索、部门筛选和索引状态筛选快速定位文档
4. 演示时可以先展示后台，再展示聊天页，讲清楚“回答来自哪里”

## 模型使用建议

- `qwen3-max`：适合面试演示和复杂问答
- `qwen-max`：适合较强效果和相对稳妥的成本平衡
- `qwen-plus`：适合日常开发和频繁调试
- `qwen-turbo`：适合追求响应速度

## 演示建议

1. 上传一份 PDF 或 DOCX
2. 展示知识库列表和筛选
3. 新建会话并提问
4. 展示流式回答
5. 切换模型
6. 删除错误文档
7. 运行离线评估
