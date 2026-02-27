# 教学资源库系统（高中物理）

本项目是一个面向高中物理教学场景的资源管理与检索系统，覆盖资源上传、审核发布、结构化归档、AI 语义检索和 RAG 问答。  
后端基于 FastAPI，前端基于 React，数据层采用 PostgreSQL（主从）+ MinIO，并集成 OnlyOffice 在线预览能力。  
系统提供教师与管理员双角色工作流，适合校内教学资源沉淀、教研协作与内容治理。  
当前仓库定位为可部署、可扩展的迭代型 Demo。

## 功能总览（用户视角）

- 教师侧
  - 上传文件或外链资源，支持自动判章、标签与描述补充
  - 预览 Markdown/HTML/PDF/音视频/Office 资源
  - 在发现页按章节、板块、难度、格式与语义搜索查找资源
- 管理员侧
  - 资源审核（通过/驳回/隐藏/删除到回收站）
  - 章节、板块、标签、知识点关系管理
  - 存储管理与回收站管理（恢复/清理）
- AI 与检索
  - 资源语义检索与可选 RAG 回答
  - 来源链接采集、来源文档语义检索、历史 backfill 补算
- 发现与归档
  - 按章节/板块聚合展示
  - 支持“通用”入口（无真实章节绑定资源）

## 系统架构与目录

### 架构（文字图）

```text
frontend (React + Nginx)
   -> backend (FastAPI)
      -> db-primary (PostgreSQL 写)
      -> db-replica (PostgreSQL 读)
      -> minio (对象存储)
      -> onlyoffice (文档在线预览)
```

### 目录说明

```text
.
├── backend/               # FastAPI 服务、路由、模型、核心逻辑与脚本
├── frontend/              # React 前端页面与组件
├── docker-compose.yml     # 本地一键启动编排
├── onlyoffice/            # OnlyOffice 配置
├── test_assets/           # 测试素材
├── .env.example           # 环境变量模板
└── README.md
```

## 快速启动（Docker）

### 前置条件

- 已安装 Docker（支持 Compose）
- 本机端口未被占用：`8080`、`8000`、`5432`、`5433`、`9000`、`9001`

### 1) 准备环境变量

```bash
cp .env.example .env
```

### 2) 启动服务

优先使用 Docker Compose V2：

```bash
docker compose up -d --build
```

若你的环境是旧版命令：

```bash
docker-compose up -d --build
```

### 3) 启动校验

```bash
docker ps
curl http://localhost:8000/api/health
```

访问地址：

- 前端：`http://localhost:8080`
- 后端 OpenAPI：`http://localhost:8000/docs`
- MinIO Console：`http://localhost:9001`

默认管理员账号（可在 `.env` 修改）：

- 账号：`admin`
- 密码：`admin123`

### 4) 首次使用建议流程

1. 管理员登录后台，确认章节/板块/标签已加载
2. 教师在上传页提交资源（文件或链接）
3. 管理员在“待审核/资源管理”完成审核
4. 在发现页做关键词 + 语义检索验证

## 环境变量说明（按分组）

以 `.env.example` 为准。建议先保留默认值，按实际环境逐步调整。

| 分组 | 关键变量 | 最小必填 | 常见错误 |
| --- | --- | --- | --- |
| 数据库 | `DATABASE_URL` `DATABASE_WRITE_URL` `DATABASE_READ_URL` | 是 | 写读库地址写反、`db-primary`/`db-replica` 主机名错误 |
| 认证 | `JWT_SECRET_KEY` `ADMIN_EMAIL` `ADMIN_PASSWORD` | 是 | 生产环境未改默认密钥与默认管理员口令 |
| 对象存储 | `MINIO_ENDPOINT` `MINIO_ACCESS_KEY` `MINIO_SECRET_KEY` `MINIO_BUCKET` | 是 | MinIO 密钥不一致、桶未初始化导致上传失败 |
| OnlyOffice | `ONLYOFFICE_ENABLED` `ONLYOFFICE_INTERNAL_BASE_URL` `ONLYOFFICE_PUBLIC_PATH` | 否（预览功能必需） | 反向代理路径不通，出现 `/office` 502 |
| MinerU | `MINERU_API_BASE_URL` `MINERU_API_TOKEN` | 否（MinerU 功能必需） | Token 未配置导致任务创建失败 |
| AI | `OPENAI_API_KEY` `OPENAI_BASE_URL` `AI_CHAT_MODEL` `AI_EMBEDDING_MODEL` | 否（AI 功能必需） | Key 为空时语义检索/自动富化能力降级 |

## 核心接口索引（开发联调）

> 完整接口以 `/docs` 为准。以下列常用入口。

### 认证

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

### 资源

- `GET /api/resources`
- `POST /api/resources`
- `GET /api/resources/chapter/{chapter_id}/groups`
- `GET /api/resources/chapter/general/groups`（通用资源聚合）
- `POST /api/resources/semantic-search`
- `POST /api/resources/auto-classify`

### 章节 / 板块 / 标签

- `GET/POST/PATCH /api/chapters`
- `GET/POST/PATCH /api/sections`
- `GET/POST/PATCH /api/tags`

### 知识点

- `GET/POST/PATCH /api/knowledge-points`
- `POST /api/knowledge-points/edges`

### 来源采集（ingest）

- `POST /api/ingest/url`
- `GET /api/ingest/jobs`
- `GET /api/ingest/documents`
- `POST /api/ingest/documents/semantic-search`（新增关键）
- `POST /api/ingest/documents/backfill`（新增关键）

### RAG

- `GET /api/rag/workspaces`
- `POST /api/rag/quick-bootstrap`
- `POST /api/rag/workspaces/{workspace_id}/semantic-search`
- `POST /api/rag/workspaces/{workspace_id}/qa`
- `POST /api/rag/ask`

### MinerU

- `POST /api/mineru/file-urls/batch`
- `GET /api/mineru/extract-results/batch/{batch_id}`
- `POST /api/mineru/jobs`

### 存储与回收站

- `GET /api/storage/list`
- `POST /api/storage/upload`
- `POST /api/storage/reconcile`
- `GET /api/trash/items`
- `POST /api/trash/items/{item_id}/restore`

### `chapter_mode=general` 说明（关键）

- `POST /api/resources`：传 `chapter_mode=general` 时允许 `chapter_id` 为空
- `GET /api/resources`：支持 `chapter_mode=general` 过滤通用资源
- `GET /api/knowledge-points`：`chapter_mode=general` 返回空集（知识点需绑定真实章节）

## 典型开发任务

### 1) 前端本地热更新开发

保持后端容器运行后，单独启动前端 dev server：

```bash
cd frontend
npm install
npm run dev
```

- 访问：`http://localhost:5173`
- 默认已通过 Vite 代理 `/api` 到 `http://localhost:8000`

### 2) API 调试

- 打开 `http://localhost:8000/docs`
- 先调用 `POST /api/auth/login` 获取 token
- 在 Swagger Authorize 中填入 Bearer Token

### 3) 常见变更入口

- 前端页面：`frontend/src/pages/`
- 前端组件：`frontend/src/components/`
- 后端路由：`backend/app/routers/`
- 后端模型与 schema：`backend/app/models.py`、`backend/app/schemas.py`

### 4) 数据库运行时 schema patch 机制

- 启动时会执行 `backend/app/main.py` 中 `RUNTIME_SCHEMA_PATCHES`
- 用于 Demo 环境下的增量 schema 补齐与索引补丁
- 生产建议改为显式迁移流程，避免启动时隐式变更

## 排障指南（高频问题）

### 1) 端口冲突

```bash
lsof -iTCP -sTCP:LISTEN -n -P | grep -E "8000|8080|5432|9000"
```

处理方式：停止占用进程，或修改 `docker-compose.yml` 左侧 Host 端口。

### 2) OnlyOffice 预览失败（/office 502）

- 检查 `onlyoffice` 容器是否运行
- 检查 `frontend/nginx.conf` 中 `/office/` 代理配置
- 检查 `ONLYOFFICE_ENABLED` 与相关地址配置

### 3) MinIO 上传/访问异常

- 检查 `MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY` 是否一致
- 检查桶 `MINIO_BUCKET` 是否创建成功（`minio-init`）

### 4) AI 功能不可用

- 检查 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、模型名
- 未配置时系统可运行，但语义检索/自动富化能力会降级

### 5) 语义检索无结果

- 先确认资源或来源文档已有 embedding
- 对来源文档可调用 backfill：`POST /api/ingest/documents/backfill`
- 检查查询范围（stage/subject/chapter_mode）是否过窄

### 6) 代码更新后页面“没有变化”

- 重新构建并重启前后端：

```bash
docker compose up -d --build backend frontend
```

- 浏览器强制刷新（`Ctrl+Shift+R`）

## 版本状态与后续计划

- 当前状态：`v1.1.0`，持续迭代中的教学资源库 Demo
- 规划文档：见 `docs/project-proposal.md`

