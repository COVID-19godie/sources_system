from sqlalchemy import text

from app.core.db_read_write import write_engine


SQL = [
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_summary TEXT;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_json JSONB;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS ai_updated_at TIMESTAMPTZ;",
]


def main() -> None:
    with write_engine.begin() as conn:
        for statement in SQL:
            conn.execute(text(statement))
    print("ai fields migration done")


if __name__ == "__main__":
    main()
