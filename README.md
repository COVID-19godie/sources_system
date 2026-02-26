# 教学资源库系统 Demo

一个可直接运行的学校落地演示版本，包含：

- FastAPI 后端（JWT 登录、资源上传、审核流程）
- React 前端（按章节聚合浏览、上传、审核）
- PostgreSQL + MinIO（支持主从读写分离与对象存储）
- Docker Compose 一键启动

## 快速启动

1. 复制环境变量（已默认创建）：

```bash
cp .env.example .env
```

2. 启动服务：

```bash
docker-compose up --build
```

3. 访问地址：

- 前端：http://localhost:8080
- 后端接口文档：http://localhost:8000/docs
- MinIO Console：http://localhost:9001

## 本地部署端口总览（全量含预留）

| 服务 | Host 端口 | Container 端口 | 是否当前启用 | 是否必须 | 用途 | 备注（冲突替代端口） |
| --- | --- | --- | --- | --- | --- | --- |
| 前端 Web | 8080 | 80 | 是 | 是 | 用户访问页面 | 可改为 `8081:80` |
| 后端 API | 8000 | 8000 | 是 | 是 | 接口与文档 | 可改为 `8010:8000` |
| PostgreSQL 主库 | 5432 | 5432 | 是 | 是 | 主库写入/主连接 | 可改为 `15432:5432` |
| PostgreSQL 从库 | 5433 | 5432 | 是 | 否 | 只读副本查询 | 可改为 `15433:5432` |
| MinIO S3 API | 9000 | 9000 | 是 | 是 | 资源文件对象存储 | 可改为 `19000:9000` |
| MinIO Console | 9001 | 9001 | 是 | 否 | MinIO 管理控制台 | 可改为 `19001:9001` |
| Ollama API（本地 AI 默认） | 11434 | 11434 | 预留/按需启用 | AI 功能必需 | 本地推理服务（OpenAI 兼容接入） | 未启用则 AI 功能不可用 |
| Vite Dev Server | 5173 | - | 预留 | 否 | 前端开发热更新端口 | CORS 已放行 |
| 前端备用开发端口 | 3000 | - | 预留 | 否 | 前端备用本地开发端口 | CORS 已放行 |
| vLLM 备用推理端口 | 8001 | 8001 | 预留 | 否 | 备用本地推理服务 | 可替代 Ollama |
| Qdrant 备用向量库 HTTP | 6333 | 6333 | 预留 | 否 | 未来 RAG 向量检索（HTTP） | 当前未启用 |
| Qdrant 备用向量库 gRPC | 6334 | 6334 | 预留 | 否 | 未来 RAG 向量检索（gRPC） | 当前未启用 |

## 本地 AI（Ollama）接入（默认方案）

后端当前按 OpenAI 兼容协议调用 AI，核心路径为：

- `/chat/completions`
- `/embeddings`

本地 Ollama 推荐配置（`.env`）：

```bash
OPENAI_BASE_URL=http://host.docker.internal:11434/v1
OPENAI_API_KEY=ollama-local
AI_CHAT_MODEL=qwen2.5:7b
AI_EMBEDDING_MODEL=nomic-embed-text
```

说明：

- `OPENAI_API_KEY` 在当前后端实现中必须非空，本地可填任意非空值（如 `ollama-local`）。
- Mac/Windows（Docker Desktop）使用 `host.docker.internal` 访问宿主机 Ollama。
- Linux 若将 Ollama 以 Compose 服务接入，改为 `OPENAI_BASE_URL=http://ollama:11434/v1`。
- Ollama 启动后可先验证：`curl http://localhost:11434/api/tags`。

## 端口冲突处理

1. 只修改 `docker-compose.yml` 左侧 Host 端口，右侧 Container 端口不变。  
示例：`8080:80` 改为 `8081:80`。
2. 端口变更后，同步更新本 README 的端口表，避免文档与环境不一致。
3. 变更后执行连通性验证：

```bash
docker ps
curl http://localhost:8000/api/health
curl http://localhost:11434/api/tags
```

## 本次文档更新影响

- 后端 API：无新增、无删除、无行为变更。
- 前端路由：无变更。
- 数据库 schema：无变更。
- 环境变量：无新增变量，仅补充本地 AI 推荐值写法。

## 默认账号

- 管理员账号：`admin`
- 管理员密码：`admin123`

可在 `.env` 中修改 `ADMIN_EMAIL` / `ADMIN_PASSWORD`。

## Demo 功能

- 教师注册与登录（JWT）
- 资源上传（支持章节、动态板块、难度等元数据）
- 上传进度条（前端实时显示）
- 章节资源页：同一章节下按板块动态分区展示
- 资源预览：Markdown / HTML / PDF / 视频 / Word / Excel / PPT 在线预览
- 搜索与筛选：关键词 + 格式 + 板块 + 章节
- AI 自动标签与总结（上传/审核后自动富化）
- AI 语义搜索 + RAG 问答（发现页可直接使用）
- 管理员审核（通过/驳回/删除）
- 管理员章节管理：新增 / 编辑 / 启停
- 管理员板块管理：新增 / 编辑 / 启停 / 排序
- 同一资源支持多章节索引（资源-章节映射）
- MinerU 官方任务流对齐：
  - `POST /api/mineru/file-urls/batch`
  - `GET /api/mineru/extract-results/batch/{batch_id}`
  - 业务任务：`/api/mineru/jobs`（创建 / 刷新 / 转资源）

## 数据库迁移（旧库升级）

后端升级后执行：

```bash
python scripts/migrate_db_storage_fields.py
python scripts/migrate_library_phase1.py
python scripts/migrate_dynamic_sections_and_mineru.py
python scripts/migrate_ai_fields.py
```

如需迁移历史本地文件到 MinIO，再执行：

```bash
python scripts/migrate_local_uploads_to_minio.py
```

## MinerU 配置

在 `.env` 中配置：

```bash
MINERU_API_BASE_URL=https://mineru.net/api/v4
MINERU_API_TOKEN=你的token
MINERU_MODEL_VERSION=MinerU-HTML
MINERU_POLL_INTERVAL_SECONDS=2
MINERU_POLL_TIMEOUT_SECONDS=180
MINERU_HTTP_TIMEOUT_SECONDS=60
```

兼容接口：`POST /api/resources/text-to-md`  
官方透传：`POST /api/mineru/file-urls/batch`、`GET /api/mineru/extract-results/batch/{batch_id}`  
业务任务：`POST /api/mineru/jobs`、`POST /api/mineru/jobs/{id}/refresh`、`POST /api/mineru/jobs/{id}/materialize`

## AI 配置

在 `.env` 中配置：

```bash
OPENAI_API_KEY=你的key
OPENAI_BASE_URL=https://api.openai.com/v1
AI_CHAT_MODEL=gpt-4o-mini
AI_EMBEDDING_MODEL=text-embedding-3-small
AI_HTTP_TIMEOUT_SECONDS=60
AI_AUTO_ENRICH=true
AI_MAX_SOURCE_CHARS=12000
AI_RAG_TOP_K=5
STRICT_PEP_CATALOG=true
```

AI相关接口：  
`POST /api/resources/semantic-search`（语义检索 + RAG回答）  
`POST /api/resources/{resource_id}/ai-enrich`（管理员手动重建AI标签/总结/向量）  
`POST /api/resources/ai-reindex?limit=50`（管理员批量补全历史资源向量）

## 目录结构

```text
.
├── backend
├── frontend
├── docker-compose.yml
└── .env
```
