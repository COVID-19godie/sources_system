from sqlalchemy import text

from app.core.db_read_write import write_engine


SQL = [
    "ALTER TYPE resource_status ADD VALUE IF NOT EXISTS 'hidden';",
]


def main() -> None:
    with write_engine.begin() as conn:
        for statement in SQL:
            conn.execute(text(statement))
    print("resource status migration done: hidden")


if __name__ == "__main__":
    main()
