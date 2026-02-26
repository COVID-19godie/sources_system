from app.core.db_read_write import WriteSessionLocal
from app.routers.chapters import ensure_demo_chapters


def main() -> None:
    db = WriteSessionLocal()
    try:
        ensure_demo_chapters(db)
    finally:
        db.close()
    print("pep 2019 senior physics catalog ensured")


if __name__ == "__main__":
    main()
