from sqlalchemy import text

from app.core.db_read_write import write_engine


SQL = [
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
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS volume_code VARCHAR(20);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS source_filename VARCHAR(255);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS title_auto_generated BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS rename_version VARCHAR(20) NOT NULL DEFAULT 'v1';",
]


def main() -> None:
    with write_engine.begin() as conn:
        for statement in SQL:
            conn.execute(text(statement))
    print("pep index schema migration done")


if __name__ == "__main__":
    main()
