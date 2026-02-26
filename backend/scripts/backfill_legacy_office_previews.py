from datetime import datetime
from pathlib import Path

from app.core import storage
from app.core.config import settings
from app.core.office_converter import ensure_legacy_pdf_preview, is_legacy_office_suffix


LOG_FILE = Path("backfill_legacy_office_previews.log")


def write_log(line: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat()} {line}\n")


def should_skip(key: str) -> bool:
    prefix_legacy = settings.OFFICE_LEGACY_PREVIEW_PREFIX.strip().strip("/")
    prefix_version = settings.OFFICE_VERSION_PREFIX.strip().strip("/")
    return key.startswith(f"{prefix_legacy}/") or key.startswith(f"{prefix_version}/")


def main() -> None:
    converted = 0
    skipped = 0
    failed = 0

    rows = storage.list_objects(prefix="", recursive=True)
    for row in rows:
        key = row.object_name
        if key.endswith("/") or should_skip(key):
            skipped += 1
            continue

        suffix = Path(key).suffix.lower()
        if not is_legacy_office_suffix(suffix):
            skipped += 1
            continue

        try:
            preview_key = ensure_legacy_pdf_preview(key, force=False)
            converted += 1
            write_log(f"status=success source={key} preview={preview_key}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            write_log(f"status=failed source={key} reason={error}")

    print(f"backfill done. converted={converted} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
