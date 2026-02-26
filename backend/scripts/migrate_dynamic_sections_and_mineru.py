from sqlalchemy import text

from app.core.db_read_write import write_engine


SQL = [
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
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
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS section_id INTEGER REFERENCES resource_sections(id);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_summary TEXT;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_json JSONB;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_updated_at TIMESTAMPTZ;",
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
]


def main() -> None:
    with write_engine.begin() as conn:
        for statement in SQL:
            conn.execute(text(statement))
    print("dynamic sections + mineru migration done")


if __name__ == "__main__":
    main()
