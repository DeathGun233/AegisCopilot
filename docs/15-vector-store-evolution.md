# VectorStore 演进说明

本文档对应 GitHub issue #10：抽象向量层并为 Milvus 接入预留演进路径。

## 当前状态

后端已引入 `VectorStore` 协议和 `LocalVectorStore` fallback：

- `DocumentService` 负责切分文档、生成 embedding，并通过 `VectorStore.replace_document_chunks()` 写入向量索引。
- `RetrievalService` 通过 `VectorStore.search_candidates()` 获取候选 chunk，再沿用现有 hybrid scoring 和 rerank 逻辑。
- 文档详情、系统统计、重建索引判断等 chunk 读取入口已切到 `VectorStore`。
- `LocalVectorStore` 仍复用现有 JSON/SQL chunk 存储，保证当前部署不需要额外中间件。

## 接口契约

未来的 `MilvusVectorStore` 需要保持以下语义：

- `replace_document_chunks(document_id, chunks)`：删除同一文档旧 chunk，并写入新 chunk 与向量。
- `delete_document(document_id)`：删除同一文档在向量索引中的所有 chunk。
- `search_candidates(query, query_embedding, limit)`：返回可参与 hybrid rerank 的候选 chunk。
- `list_chunks_for_document(document_id)`：支撑文档详情页展示。
- `count_chunks_for_document(document_id)`、`count_embedded_chunks_for_document(document_id)`、`get_chunk_stats()`：支撑状态页、批量重建和系统统计。

## Milvus 接入路径

推荐后续分三步接入：

1. 新增配置项，例如 `AEGIS_VECTOR_STORE_PROVIDER=local|milvus`、`AEGIS_MILVUS_URI`、`AEGIS_MILVUS_COLLECTION`。
2. 新增 `MilvusVectorStore`，只替换 `deps.Container` 中的向量层装配，保持 API、`DocumentService`、`RetrievalService` 构造方式不变。
3. 为 Milvus 写集成测试或 docker compose profile，覆盖写入、搜索、删除、重建索引和 fallback 回退。

## 注意事项

- Milvus 只负责向量候选召回，不应接管业务文档元数据、用户、会话或任务状态。
- 当前 hybrid scoring 仍在 `RetrievalService` 内完成，Milvus 返回的候选集应包含足够的 chunk 文本、tokens、metadata 和 embedding 版本信息。
- 如果 Milvus 不可用，生产环境应显式失败或降级到 `LocalVectorStore`，不要静默丢索引。

## Milvus 真实接入验收记录

验收时间：2026-04-22，本地 Docker Desktop + Docker Compose v5.1.2。

### 环境准备

1. 移除 `docker-compose.yml` 顶部的 `version` 字段，避免 Compose 输出 obsolete warning。
2. 验证配置解析：

   ```powershell
   docker compose config --quiet
   docker compose --profile milvus config --quiet
   ```

3. 启动 Milvus profile：

   ```powershell
   docker compose --profile milvus up -d milvus-etcd milvus-minio milvus
   docker compose --profile milvus ps
   ```

   本次验收中 `milvus-etcd`、`milvus-minio`、`milvus` 均进入 `Up` 状态，`http://localhost:9091/healthz` 返回 `OK`，Milvus 日志出现 `All components are ready`。

4. 安装后端 Milvus optional dependency：

   ```powershell
   backend\.venv\Scripts\python.exe -m pip install -e ".[milvus,dev]"
   ```

   本次安装得到 `pymilvus-2.6.12`。如果本机配置了 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 指向 `127.0.0.1:7890`，`pymilvus` 连接 `localhost:19530` 可能会长时间等待；运行 Milvus 验收命令前应临时清空这些代理变量，或设置 `NO_PROXY=localhost,127.0.0.1`。

### API 验收链路

后端使用以下关键环境变量启动：

```powershell
$env:AEGIS_VECTOR_STORE_PROVIDER="milvus"
$env:AEGIS_MILVUS_URI="http://localhost:19530"
$env:AEGIS_MILVUS_COLLECTION="aegis_acceptance_<timestamp>"
$env:AEGIS_EMBEDDING_PROVIDER="openai-compatible"
$env:AEGIS_EMBEDDING_BASE_URL="http://127.0.0.1:<mock-port>/v1"
$env:AEGIS_EMBEDDING_API_KEY="acceptance-key"
$env:AEGIS_EMBEDDING_DIMENSIONS="8"
$env:AEGIS_LLM_PROVIDER="mock"
```

为避免依赖外部模型服务，本次使用本地临时 OpenAI-compatible mock embedding 服务生成固定 8 维向量；聊天生成使用 mock provider。验收覆盖：

- `POST /auth/login` 管理员登录成功。
- `POST /documents` 创建验收文档。
- `POST /documents/index` 同步索引，返回 `chunks_created=1`。
- 使用 `pymilvus.MilvusClient.query()` 直接确认目标 collection 中存在该文档 chunk。
- `POST /retrieval/preview` 使用 `blue lantern approval` 查询，候选结果命中该文档。
- `POST /chat` 使用 `What approval is required before vector rollout?` 查询，聊天任务 citation 引用该文档。
- 再次 `POST /documents/index` 验证重建索引不会留下重复 chunk。
- `DELETE /documents/{document_id}` 后再次查询 Milvus，确认该文档残留 chunk 数为 0。

本次验收输出摘要：

```json
{
  "collection": "aegis_acceptance_1776790042",
  "chunks_created": 1,
  "preview_hits": 1,
  "chat_citations": 1,
  "delete_residual_chunks": 0
}
```

### 故障记录

- 首次拉取 Milvus profile 镜像时，Docker Hub 下载 MinIO layer 出现 `EOF`。未清理 volume，直接重试同一条 `docker compose --profile milvus up -d ...` 后拉取和启动成功。
- Milvus 容器刚启动时可能先出现 `no available streaming node`、`channel is not assigned` 等 WARN；本次随后出现 `All components are ready`，并且 `/healthz` 与 `pymilvus` 调用均通过。
- 在代理环境变量指向本地代理时，`pymilvus.MilvusClient(...).list_collections()` 曾超时；清空 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 并设置 `NO_PROXY=localhost,127.0.0.1` 后立即返回。
