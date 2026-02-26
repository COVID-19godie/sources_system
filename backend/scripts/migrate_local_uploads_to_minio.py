from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app import models
from app.core.storage import upload_file_from_path
from app.core.db_read_write import WriteSessionLocal


LOCAL_UPLOAD_DIR = Path("uploads")
LOG_FILE = Path("migration_minio.log")


def write_log(line: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat()} {line}\n")


def main() -> None:
    migrated = 0
    failed = 0

    db = WriteSessionLocal()
    try:
        rows = db.execute(select(models.Resource).where(models.Resource.file_path.is_not(None))).scalars().all()

        for row in rows:
            if row.object_key and row.storage_provider == models.StorageProvider.minio:
                continue

            filename = (row.file_path or "").split("/")[-1]
            if not filename:
                failed += 1
                write_log(f"resource={row.id} status=failed reason=invalid_file_path")
                continue

            source = LOCAL_UPLOAD_DIR / filename
            if not source.exists():
                failed += 1
                write_log(f"resource={row.id} status=failed reason=file_not_found path={source}")
                continue

            object_key = f"resources/{filename}"
            try:
                upload_file_from_path(object_key=object_key, source_path=source)
                row.storage_provider = models.StorageProvider.minio
                row.object_key = object_key
                row.file_path = None
                db.add(row)
                db.commit()
                migrated += 1
                write_log(
                    f"resource={row.id} status=success object_key={object_key} bytes={source.stat().st_size}"
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed += 1
                write_log(f"resource={row.id} status=failed reason={exc}")
    finally:
        db.close()

    print(f"migration done. migrated={migrated} failed={failed}")


if __name__ == "__main__":
    main()
