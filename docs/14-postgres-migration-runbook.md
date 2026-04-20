# Postgres 迁移验收 Runbook

本文档用于收尾 GitHub issue #9：从 JSON 存储迁移到 SQL/Postgres 持久化层。

## 前置条件

- Docker Desktop 或兼容的 Docker Engine 可用。
- Python 3.11 可用。
- 后端依赖已安装：`pip install -e ".[dev]"`。
- 当前工作目录位于仓库根目录。

如果本机没有 Docker，不要关闭 #9。可以先完成代码级验证，但真实 Postgres 验收必须换到具备 Docker/Postgres 的环境执行。

## 1. 检查配置

```powershell
git status -sb
docker compose config
```

期望结果：

- `docker compose config` 正常输出 compose 配置。
- `backend` 服务包含 `AEGIS_DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/aegiscopilot`。
- `postgres` 服务使用 `postgres:16-alpine`。

## 2. 启动 Postgres

```powershell
docker compose up -d postgres
docker compose ps
```

期望结果：

- `postgres` 容器处于 running 状态。
- 端口 `5432` 已映射到本机。

## 3. 安装后端依赖

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic --version
```

期望结果：

- `alembic --version` 能正常输出版本号。
- 如果安装依赖时网络超时，记录失败原因，不要声称已完成 Postgres 验证。

## 4. 执行 Alembic 初始迁移

```powershell
$env:AEGIS_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/aegiscopilot"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

期望结果：

- Alembic 成功升级到 `0001_initial_sql_persistence`。
- Postgres 中存在这些表：`conversations`、`documents`、`chunks`、`document_tasks`、`tasks`、`users`、`sessions`、`runtime_settings`。

可选检查：

```powershell
docker compose exec postgres psql -U postgres -d aegiscopilot -c "\dt"
```

## 5. 准备 JSON 迁移样本

使用已有 `backend/storage` 作为样本，或准备一份包含以下文件的临时目录：

- `conversations.json`
- `documents.json`
- `chunks.json`
- `document_tasks.json`
- `tasks.json`
- `users.json`
- `sessions.json`
- `runtime_model.json`
- `runtime_retrieval.json`

如果某类数据不存在，迁移脚本应报告数量为 `0`，不应失败。

## 6. 先跑 dry-run

```powershell
cd ..
backend\.venv\Scripts\python.exe scripts\migrate_json_to_sql.py `
  --storage-dir backend\storage `
  --database-url "postgresql+psycopg://postgres:postgres@localhost:5432/aegiscopilot" `
  --dry-run `
  --report-path .private\postgres-migration-dry-run-report.json `
  --rollback-sql-path .private\postgres-migration-rollback.sql
```

期望结果：

- 控制台输出每类数据数量。
- report 文件包含 `dry_run: true` 和各类 counts。
- dry-run 不应向 Postgres 写入业务数据。
- rollback SQL 文件包含对应 `DELETE FROM ... WHERE ... IN (...)` 语句。

## 7. 正式迁移

```powershell
backend\.venv\Scripts\python.exe scripts\migrate_json_to_sql.py `
  --storage-dir backend\storage `
  --database-url "postgresql+psycopg://postgres:postgres@localhost:5432/aegiscopilot" `
  --report-path .private\postgres-migration-report.json `
  --rollback-sql-path .private\postgres-migration-rollback.sql
```

期望结果：

- 控制台输出每类数据数量。
- report 文件包含 `dry_run: false` 和各类 counts。
- Postgres 表内行数与 report counts 对得上。

可选检查：

```powershell
docker compose exec postgres psql -U postgres -d aegiscopilot -c "select count(*) from conversations;"
docker compose exec postgres psql -U postgres -d aegiscopilot -c "select count(*) from documents;"
docker compose exec postgres psql -U postgres -d aegiscopilot -c "select count(*) from chunks;"
docker compose exec postgres psql -U postgres -d aegiscopilot -c "select key from runtime_settings order by key;"
```

## 8. 应用级验证

```powershell
$env:AEGIS_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/aegiscopilot"
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

另开一个终端检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health
```

再通过前端或 API 验证：

- 管理员能登录。
- 能创建文档。
- 能索引文档。
- 能发起聊天。
- 重启后端后，已创建的文档和会话仍然存在。

## 9. 回滚演练

只在测试库或确认可回滚窗口内执行：

```powershell
docker compose exec -T postgres psql -U postgres -d aegiscopilot < .private\postgres-migration-rollback.sql
```

期望结果：

- rollback SQL 能执行成功。
- 被迁移的记录从对应表中删除。
- 不应删除不在迁移 report 中的其他记录。

## 10. 关闭 #9 的门槛

满足以下条件后再关闭 #9：

- 本地或 CI：`python -m pytest -q` 通过。
- 本地或 CI：`python scripts/check_placeholder_corruption.py` 通过。
- 有 Docker/Postgres 环境中：`docker compose config` 通过。
- 有 Docker/Postgres 环境中：`alembic upgrade head` 通过。
- dry-run 不写库，且生成 report 与 rollback SQL。
- 正式迁移写入 Postgres，report counts 与数据库行数一致。
- 应用在 Postgres 模式下重启后仍能读取迁移数据。
- 如执行回滚演练，rollback SQL 能删除本次迁移记录。

如果任一 Postgres 验证项无法执行，#9 应继续保持 open，并在 issue 评论中写明阻塞原因。
