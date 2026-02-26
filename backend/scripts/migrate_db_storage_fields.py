from sqlalchemy import text

from app.core.db_read_write import write_engine


SQL = [
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'storage_provider') THEN CREATE TYPE storage_provider AS ENUM ('local','minio'); END IF; END $$;",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS storage_provider storage_provider NOT NULL DEFAULT 'local';",
    "ALTER TABLE resources ADD COLUMN IF NOT EXISTS object_key VARCHAR(255);",
]


def main() -> None:
    with write_engine.begin() as conn:
        for statement in SQL:
            conn.execute(text(statement))
    print("storage fields migration done")


if __name__ == "__main__":
    main()
