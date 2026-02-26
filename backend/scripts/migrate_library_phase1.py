from sqlalchemy import text

from app.core.db_read_write import write_engine


SQL = [
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS resource_kind VARCHAR(30) NOT NULL DEFAULT 'tutorial';",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS file_format VARCHAR(30) NOT NULL DEFAULT 'other';",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS difficulty VARCHAR(30);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS chapter_id INTEGER;",
    "CREATE TABLE IF NOT EXISTS chapters (id SERIAL PRIMARY KEY, stage VARCHAR(30) NOT NULL, subject VARCHAR(50) NOT NULL, grade VARCHAR(30) NOT NULL, textbook VARCHAR(120), chapter_code VARCHAR(50) NOT NULL, title VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chapters_subject_grade_code ON chapters(subject, grade, chapter_code);",
    "CREATE TABLE IF NOT EXISTS resource_chapter_links (id SERIAL PRIMARY KEY, resource_id INTEGER NOT NULL REFERENCES resources(id), chapter_id INTEGER NOT NULL REFERENCES chapters(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_resource_chapter_link ON resource_chapter_links(resource_id, chapter_id);",
]


def main() -> None:
    with write_engine.begin() as conn:
        for statement in SQL:
            conn.execute(text(statement))
    print("library phase1 migration done")


if __name__ == "__main__":
    main()
