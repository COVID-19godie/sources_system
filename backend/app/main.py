from pathlib import Path
import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app import models
from app.core.config import settings
from app.core import rag_sync, trash_service
from app.core.security import get_password_hash
from app.core.db_read_write import WriteSessionLocal, write_engine
from app.db import Base
from app.routers import auth, chapters, meta, mineru, office, rag, resources, sections, storage, tags, trash


app = FastAPI(title="Education Resource Demo", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

uploads_dir = Path("uploads")
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

app.include_router(auth.router, prefix="/api/auth")
app.include_router(chapters.router, prefix="/api/chapters")
app.include_router(sections.router, prefix="/api/sections")
app.include_router(tags.router, prefix="/api/tags")
app.include_router(meta.router, prefix="/api/meta")
app.include_router(storage.router, prefix="/api/storage")
app.include_router(office.router, prefix="/api/office")
app.include_router(resources.router, prefix="/api/resources")
app.include_router(rag.router, prefix="/api/rag")
app.include_router(mineru.router, prefix="/api/mineru")
app.include_router(trash.router, prefix="/api/trash")


logger = logging.getLogger(__name__)
_scheduler_stop = threading.Event()
_scheduler_threads: list[threading.Thread] = []


RUNTIME_SCHEMA_PATCHES = [
    """
    DO $$
    BEGIN
      CREATE EXTENSION IF NOT EXISTS vector;
    EXCEPTION WHEN OTHERS THEN
      NULL;
    END $$;
    """,
    "ALTER TYPE resource_status ADD VALUE IF NOT EXISTS 'hidden';",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS volume_code VARCHAR(20) NOT NULL DEFAULT 'bx1';",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS volume_name VARCHAR(50) NOT NULL DEFAULT '必修第一册';",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS volume_order INT NOT NULL DEFAULT 10;",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS chapter_order INT NOT NULL DEFAULT 10;",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS chapter_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS index_embedding_json JSONB;",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS index_embedding_model VARCHAR(100);",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS index_updated_at TIMESTAMPTZ;",
    "ALTER TABLE chapters DROP CONSTRAINT IF EXISTS uq_chapters_subject_code;",
    "ALTER TABLE chapters DROP CONSTRAINT IF EXISTS chapters_subject_chapter_code_key;",
    "ALTER TABLE chapters DROP CONSTRAINT IF EXISTS uq_chapters_subject_grade_code;",
    "DROP INDEX IF EXISTS uq_chapters_subject_code;",
    "DROP INDEX IF EXISTS chapters_subject_chapter_code_key;",
    "DROP INDEX IF EXISTS uq_chapters_subject_grade_code;",
    "CREATE INDEX IF NOT EXISTS idx_chapters_scope_order ON chapters(stage, subject, volume_order, chapter_order);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chapters_subject_volume_code ON chapters(subject, volume_code, chapter_code);",
    """
    CREATE TABLE IF NOT EXISTS chapter_aliases (
      id SERIAL PRIMARY KEY,
      stage VARCHAR(30) NOT NULL,
      subject VARCHAR(50) NOT NULL,
      source_pattern VARCHAR(200) NOT NULL,
      pattern_type VARCHAR(20) NOT NULL DEFAULT 'keyword',
      target_chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
      priority INT NOT NULL DEFAULT 100,
      is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapter_aliases_scope ON chapter_aliases(stage, subject, is_enabled, priority);",
    "CREATE INDEX IF NOT EXISTS idx_chapter_aliases_target ON chapter_aliases(target_chapter_id);",
    "CREATE INDEX IF NOT EXISTS idx_chapter_aliases_pattern ON chapter_aliases(source_pattern);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chapter_aliases_rule ON chapter_aliases(stage, subject, source_pattern, pattern_type, target_chapter_id);",
    """
    CREATE TABLE IF NOT EXISTS resource_sections (
      id SERIAL PRIMARY KEY,
      stage VARCHAR(30) NOT NULL,
      subject VARCHAR(50) NOT NULL,
      code VARCHAR(50) NOT NULL,
      name VARCHAR(100) NOT NULL,
      description TEXT,
      sort_order INT NOT NULL DEFAULT 100,
      is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
      created_by INTEGER REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_resource_sections_scope_code ON resource_sections(stage, subject, code);",
    """
    CREATE TABLE IF NOT EXISTS resource_tags (
      id SERIAL PRIMARY KEY,
      stage VARCHAR(30) NOT NULL,
      subject VARCHAR(50) NOT NULL,
      tag VARCHAR(80) NOT NULL,
      category VARCHAR(50) NOT NULL DEFAULT 'other',
      sort_order INT NOT NULL DEFAULT 100,
      is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
      created_by INTEGER REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_resource_tags_scope_tag ON resource_tags(stage, subject, tag);",
    """
    INSERT INTO resource_sections(stage, subject, code, name, description, sort_order, is_enabled)
    VALUES
      ('senior','物理','tutorial','课程讲解','核心概念讲解、课堂例题拆解与章节导学',10,TRUE),
      ('senior','物理','thinking','思维训练','物理模型建构、方法迁移与解题策略训练',20,TRUE),
      ('senior','物理','interdisciplinary','跨学科项目','物理与数学/信息/工程融合任务与项目活动',30,TRUE),
      ('senior','物理','experiment','实验探究','实验原理、操作步骤、数据处理与误差分析',40,TRUE),
      ('senior','物理','exercise','题型训练','分层题组、典型题型与易错点专项训练',50,TRUE),
      ('senior','物理','exam','高考真题','历年真题、地区联考题与命题趋势解析',60,TRUE),
      ('senior','物理','simulation','仿真可视化','仿真动画、交互演示与过程可视化资源',70,TRUE),
      ('senior','物理','lab','实验设计','实验改进、器材方案与开放性实验设计案例',80,TRUE),
      ('senior','物理','reading','拓展阅读','学科史、前沿科普与课外拓展阅读材料',90,TRUE),
      ('senior','物理','project','项目化学习','情境任务、研究性学习与综合实践成果',100,TRUE)
    ON CONFLICT (stage, subject, code) DO UPDATE
      SET name = EXCLUDED.name,
          description = EXCLUDED.description,
          sort_order = EXCLUDED.sort_order,
          is_enabled = TRUE,
          updated_at = NOW();
    """,
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS section_id INTEGER REFERENCES resource_sections(id);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_summary TEXT;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_json JSONB;",
    """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_vec vector(768);
      END IF;
    END $$;
    """,
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_updated_at TIMESTAMPTZ;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS volume_code VARCHAR(20);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS source_filename VARCHAR(255);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS title_auto_generated BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS rename_version VARCHAR(20) NOT NULL DEFAULT 'v1';",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS is_trashed BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS trashed_at TIMESTAMPTZ;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS trashed_by INTEGER REFERENCES users(id);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS trash_source VARCHAR(30);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS original_object_key VARCHAR(255);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS trash_object_key VARCHAR(255);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS trash_has_binary BOOLEAN NOT NULL DEFAULT FALSE;",
    "CREATE INDEX IF NOT EXISTS idx_resources_is_trashed ON resources(is_trashed);",
    "CREATE INDEX IF NOT EXISTS idx_resources_object_key ON resources(object_key);",
    "CREATE INDEX IF NOT EXISTS idx_resources_status_trashed_chapter_section_format_updated ON resources(status, is_trashed, chapter_id, section_id, file_format, updated_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_resources_tags_gin ON resources USING GIN(tags);",
    "CREATE INDEX IF NOT EXISTS idx_resources_ai_tags_gin ON resources USING GIN(ai_tags);",
    "CREATE INDEX IF NOT EXISTS idx_resources_search_tsv_gin ON resources USING GIN(to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(ai_summary,'')));",
    """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        CREATE INDEX IF NOT EXISTS idx_resources_embedding_vec_hnsw
        ON resources USING hnsw (embedding_vec vector_cosine_ops);
      END IF;
    END $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_file_variants (
      id SERIAL PRIMARY KEY,
      resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
      object_key VARCHAR(255) NOT NULL UNIQUE,
      variant_kind VARCHAR(30) NOT NULL DEFAULT 'origin',
      file_format VARCHAR(30),
      mime_type VARCHAR(120),
      is_primary BOOLEAN NOT NULL DEFAULT FALSE,
      is_graph_visible BOOLEAN NOT NULL DEFAULT TRUE,
      derived_from_variant_id INTEGER REFERENCES resource_file_variants(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_resource_file_variants_resource_primary ON resource_file_variants(resource_id, is_primary);",
    "CREATE INDEX IF NOT EXISTS idx_resource_file_variants_resource_kind ON resource_file_variants(resource_id, variant_kind);",
    """
    INSERT INTO resource_file_variants(resource_id, object_key, variant_kind, file_format, mime_type, is_primary, is_graph_visible)
    SELECT r.id,
           r.object_key,
           'origin',
           r.file_format,
           NULL,
           TRUE,
           TRUE
    FROM resources r
    WHERE r.object_key IS NOT NULL
      AND r.object_key <> ''
    ON CONFLICT (object_key) DO UPDATE
      SET resource_id = EXCLUDED.resource_id,
          file_format = EXCLUDED.file_format,
          is_primary = TRUE,
          is_graph_visible = TRUE,
          updated_at = NOW();
    """,
    """
    UPDATE resources r
    SET section_id = rs.id
    FROM resource_sections rs
    WHERE r.section_id IS NULL
      AND rs.stage = 'senior'
      AND rs.subject = COALESCE(NULLIF(r.subject, ''), '物理')
      AND rs.code = r.resource_kind;
    """,
    """
    UPDATE resources r
    SET section_id = rs.id
    FROM resource_sections rs
    WHERE r.section_id IS NULL
      AND rs.stage = 'senior'
      AND rs.subject = '物理'
      AND rs.code = r.resource_kind;
    """,
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'mineru_job_status') THEN CREATE TYPE mineru_job_status AS ENUM ('submitted','processing','done','failed','materialized'); END IF; END $$;",
    """
    CREATE TABLE IF NOT EXISTS mineru_jobs (
      id SERIAL PRIMARY KEY,
      creator_id INTEGER NOT NULL REFERENCES users(id),
      source_filename VARCHAR(255) NOT NULL,
      source_object_key VARCHAR(255),
      batch_id VARCHAR(128) NOT NULL UNIQUE,
      status mineru_job_status NOT NULL DEFAULT 'submitted',
      parse_options JSONB NOT NULL DEFAULT '{}'::jsonb,
      official_result JSONB,
      markdown_object_key VARCHAR(255),
      markdown_preview TEXT,
      auto_create_resource BOOLEAN NOT NULL DEFAULT FALSE,
      resource_id INTEGER REFERENCES resources(id),
      error_message TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS trash_items (
      id SERIAL PRIMARY KEY,
      resource_id INTEGER REFERENCES resources(id),
      scope VARCHAR(20) NOT NULL,
      original_key VARCHAR(255) NOT NULL,
      trash_key VARCHAR(255),
      has_binary BOOLEAN NOT NULL DEFAULT FALSE,
      source VARCHAR(30) NOT NULL,
      deleted_by INTEGER REFERENCES users(id),
      deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      expires_at TIMESTAMPTZ NOT NULL,
      meta JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_trash_items_expires_at ON trash_items(expires_at);",
    "CREATE INDEX IF NOT EXISTS idx_trash_items_resource_id ON trash_items(resource_id);",
    "CREATE INDEX IF NOT EXISTS idx_trash_items_original_key ON trash_items(original_key);",
    """
    CREATE TABLE IF NOT EXISTS rag_workspaces (
      id SERIAL PRIMARY KEY,
      name VARCHAR(120) NOT NULL,
      description TEXT,
      stage VARCHAR(30) NOT NULL DEFAULT 'senior',
      subject VARCHAR(50) NOT NULL DEFAULT '物理',
      created_by INTEGER NOT NULL REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_sources (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      source_type VARCHAR(20) NOT NULL,
      resource_id INTEGER REFERENCES resources(id),
      title VARCHAR(255) NOT NULL,
      object_key VARCHAR(255),
      file_format VARCHAR(30),
      summary_text TEXT,
      tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
      embedding_json JSONB,
      status VARCHAR(30) NOT NULL DEFAULT 'ready',
      published_resource_id INTEGER REFERENCES resources(id),
      canonical_key VARCHAR(190),
      variant_kind VARCHAR(30),
      is_graph_visible BOOLEAN NOT NULL DEFAULT TRUE,
      display_priority INT NOT NULL DEFAULT 100,
      created_by INTEGER NOT NULL REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "ALTER TABLE rag_sources ADD COLUMN IF NOT EXISTS canonical_key VARCHAR(190);",
    "ALTER TABLE rag_sources ADD COLUMN IF NOT EXISTS variant_kind VARCHAR(30);",
    "ALTER TABLE rag_sources ADD COLUMN IF NOT EXISTS is_graph_visible BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE rag_sources ADD COLUMN IF NOT EXISTS display_priority INT NOT NULL DEFAULT 100;",
    """
    UPDATE rag_sources
    SET canonical_key = CASE
      WHEN resource_id IS NOT NULL THEN 'resource:' || resource_id::text
      WHEN object_key IS NOT NULL AND object_key <> '' THEN 'object:' || substring(md5(lower(object_key)) for 24)
      ELSE 'object:unknown'
    END
    WHERE canonical_key IS NULL OR canonical_key = '';
    """,
    """
    UPDATE rag_sources
    SET variant_kind = CASE
      WHEN object_key ILIKE 'legacy-previews/%' THEN 'preview_pdf'
      WHEN object_key ILIKE 'versions/%' THEN 'derived'
      WHEN source_type = 'upload' THEN 'upload'
      ELSE 'origin'
    END
    WHERE variant_kind IS NULL OR variant_kind = '';
    """,
    "UPDATE rag_sources SET display_priority = CASE WHEN variant_kind = 'origin' THEN 100 WHEN variant_kind = 'derived' THEN 90 WHEN variant_kind = 'upload' THEN 80 WHEN variant_kind = 'preview_pdf' THEN 10 ELSE 60 END WHERE display_priority IS NULL;",
    "CREATE INDEX IF NOT EXISTS idx_rag_sources_workspace_id ON rag_sources(workspace_id);",
    "CREATE INDEX IF NOT EXISTS idx_rag_sources_resource_id ON rag_sources(resource_id);",
    "CREATE INDEX IF NOT EXISTS idx_rag_sources_canonical_key ON rag_sources(canonical_key);",
    """
    CREATE TABLE IF NOT EXISTS rag_chunks (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      source_id INTEGER NOT NULL REFERENCES rag_sources(id) ON DELETE CASCADE,
      chunk_index INTEGER NOT NULL,
      content TEXT NOT NULL,
      embedding_json JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_chunks_source_index ON rag_chunks(source_id, chunk_index);",
    """
    CREATE TABLE IF NOT EXISTS rag_entities (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      entity_type VARCHAR(40) NOT NULL,
      canonical_name VARCHAR(200) NOT NULL,
      aliases TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
      description TEXT,
      confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_entities_scope_name ON rag_entities(workspace_id, entity_type, canonical_name);",
    """
    CREATE TABLE IF NOT EXISTS rag_relations (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      source_entity_id INTEGER NOT NULL REFERENCES rag_entities(id) ON DELETE CASCADE,
      target_entity_id INTEGER NOT NULL REFERENCES rag_entities(id) ON DELETE CASCADE,
      relation_type VARCHAR(60) NOT NULL,
      confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
      source_id INTEGER REFERENCES rag_sources(id) ON DELETE SET NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_rag_relations_workspace_id ON rag_relations(workspace_id);",
    "CREATE INDEX IF NOT EXISTS idx_rag_relations_source_id ON rag_relations(source_id);",
    """
    CREATE TABLE IF NOT EXISTS rag_evidences (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      source_id INTEGER NOT NULL REFERENCES rag_sources(id) ON DELETE CASCADE,
      chunk_id INTEGER REFERENCES rag_chunks(id) ON DELETE SET NULL,
      content TEXT NOT NULL,
      score DOUBLE PRECISION NOT NULL DEFAULT 0.8,
      meta JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_rag_evidences_workspace_id ON rag_evidences(workspace_id);",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = 'rag_evidences'
          AND constraint_name = 'rag_evidences_chunk_id_fkey'
      ) THEN
        ALTER TABLE rag_evidences DROP CONSTRAINT rag_evidences_chunk_id_fkey;
      END IF;

      ALTER TABLE rag_evidences
      ADD CONSTRAINT rag_evidences_chunk_id_fkey
      FOREIGN KEY (chunk_id)
      REFERENCES rag_chunks(id)
      ON DELETE SET NULL;
    EXCEPTION
      WHEN duplicate_object THEN NULL;
      WHEN undefined_table THEN NULL;
    END $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_relation_evidences (
      id SERIAL PRIMARY KEY,
      relation_id INTEGER NOT NULL REFERENCES rag_relations(id) ON DELETE CASCADE,
      evidence_id INTEGER NOT NULL REFERENCES rag_evidences(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_relation_evidences_link ON rag_relation_evidences(relation_id, evidence_id);",
    """
    CREATE TABLE IF NOT EXISTS rag_extraction_jobs (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      source_id INTEGER REFERENCES rag_sources(id) ON DELETE SET NULL,
      mode VARCHAR(20) NOT NULL DEFAULT 'quick',
      status VARCHAR(30) NOT NULL DEFAULT 'submitted',
      stats JSONB NOT NULL DEFAULT '{}'::jsonb,
      error_message TEXT,
      created_by INTEGER NOT NULL REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_rag_jobs_workspace_id ON rag_extraction_jobs(workspace_id);",
    """
    CREATE TABLE IF NOT EXISTS rag_qa_logs (
      id SERIAL PRIMARY KEY,
      workspace_id INTEGER NOT NULL REFERENCES rag_workspaces(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id),
      question TEXT NOT NULL,
      answer TEXT NOT NULL,
      citations JSONB NOT NULL DEFAULT '[]'::jsonb,
      highlight_nodes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
      highlight_edges TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_rag_qa_logs_workspace_id ON rag_qa_logs(workspace_id);",
]


def _run_reconcile_once() -> None:
    db = WriteSessionLocal()
    try:
        result = trash_service.reconcile_missing_resources(db, dry_run=False)
        resource_ids = [int(item) for item in (result.get("resource_ids") or [])]
        if resource_ids:
            rag_sync.sync_resource_to_workspaces(
                db,
                resource_ids,
                actor_id=None,
                reason="storage_reconcile_scheduler",
            )
        db.commit()
        if result["trashed_count"] > 0:
            logger.info(
                "storage reconcile done: scanned=%s missing=%s trashed=%s",
                result["scanned_count"],
                result["missing_count"],
                result["trashed_count"],
            )
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("storage reconcile failed")
    finally:
        db.close()


def _run_purge_once() -> None:
    db = WriteSessionLocal()
    try:
        purged = trash_service.purge_expired_items(db, limit=5000)
        db.commit()
        if purged > 0:
            logger.info("trash purge done: purged=%s", purged)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("trash purge failed")
    finally:
        db.close()


def _start_scheduler_thread(name: str, interval_seconds: int, task) -> None:
    if interval_seconds <= 0:
        return

    def loop() -> None:
        while not _scheduler_stop.wait(interval_seconds):
            task()

    thread = threading.Thread(target=loop, name=name, daemon=True)
    thread.start()
    _scheduler_threads.append(thread)


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=write_engine)

    with write_engine.begin() as conn:
        for statement in RUNTIME_SCHEMA_PATCHES:
            conn.execute(text(statement))

    db = WriteSessionLocal()
    try:
        admin = db.query(models.User).filter(models.User.email == settings.ADMIN_EMAIL).first()
        if admin is None:
            db.add(
                models.User(
                    email=settings.ADMIN_EMAIL,
                    hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
                    role=models.UserRole.admin,
                )
            )
            db.commit()

        sync_stats = chapters.ensure_demo_chapters(db)
        logger.info("chapter sync on startup: strict=%s stats=%s", settings.STRICT_PEP_CATALOG, sync_stats)
        sections.ensure_default_sections(db)
        tags.ensure_default_tags(db)
    finally:
        db.close()

    _scheduler_stop.clear()
    _start_scheduler_thread(
        "storage-reconcile",
        settings.STORAGE_RECONCILE_INTERVAL_SECONDS,
        _run_reconcile_once,
    )
    _start_scheduler_thread(
        "trash-purge",
        settings.TRASH_PURGE_INTERVAL_SECONDS,
        _run_purge_once,
    )


@app.on_event("shutdown")
def shutdown_event():
    _scheduler_stop.set()
    for thread in _scheduler_threads:
        thread.join(timeout=1.0)
    _scheduler_threads.clear()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "db_write": settings.DATABASE_WRITE_URL,
        "db_read": settings.DATABASE_READ_URL,
    }
