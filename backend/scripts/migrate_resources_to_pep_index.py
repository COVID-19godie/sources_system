from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app import models
from app.core import chapter_classifier, storage
from app.core.db_read_write import WriteSessionLocal


CATALOG_PATH = Path(__file__).resolve().parent / "data" / "pep_physics_2019_full.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate resources to strict PEP 2019 chapter catalog")
    parser.add_argument("--from-id", type=int, default=1, help="start resource id (inclusive)")
    parser.add_argument("--limit", type=int, default=0, help="max rows to process, 0 for all")
    parser.add_argument("--dry-run", action="store_true", help="show plan only")
    parser.add_argument(
        "--manual-review-file",
        default="manual_review.csv",
        help="CSV output for low-confidence/manual-review resources",
    )
    return parser.parse_args()


def load_catalog_keys() -> set[tuple[str, str, str, str]]:
    if not CATALOG_PATH.exists():
        raise RuntimeError(f"catalog file not found: {CATALOG_PATH}")
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = payload.get("chapters") or []
    keys: set[tuple[str, str, str, str]] = set()
    for row in rows:
        stage = str(row.get("stage") or "").strip()
        subject = str(row.get("subject") or "").strip()
        volume_code = str(row.get("volume_code") or "").strip()
        chapter_code = str(row.get("chapter_code") or "").strip()
        if stage and subject and volume_code and chapter_code:
            keys.add((stage, subject, volume_code, chapter_code))
    return keys


def infer_filename(resource: models.Resource) -> str:
    if resource.source_filename:
        return resource.source_filename
    if resource.object_key:
        return Path(resource.object_key).name
    if resource.file_path:
        return Path(resource.file_path).name
    return f"resource-{resource.id}"


def infer_section_code(resource: models.Resource) -> str | None:
    if resource.section and resource.section.code:
        return resource.section.code
    if resource.resource_kind:
        return resource.resource_kind
    return None


def chapter_in_catalog(chapter: models.Chapter | None, catalog_keys: set[tuple[str, str, str, str]]) -> bool:
    if not chapter:
        return False
    key = (chapter.stage, chapter.subject, chapter.volume_code, chapter.chapter_code)
    return key in catalog_keys


def classify_if_needed(
    db,
    resource: models.Resource,
    catalog_keys: set[tuple[str, str, str, str]],
) -> tuple[models.Chapter | None, str | None, bool, str, list[str]]:
    chapter = resource.chapter
    if chapter_in_catalog(chapter, catalog_keys):
        return chapter, chapter.volume_code, False, "already-in-catalog", []

    result = chapter_classifier.classify_chapter(
        db,
        stage="senior",
        subject=resource.subject or "物理",
        title=resource.title or "",
        description=resource.description or "",
        tags=list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or []))),
        filename=infer_filename(resource),
        volume_code=resource.volume_code or None,
        top_k=3,
    )
    candidate_text = [
        f"{item.chapter.volume_code}-{item.chapter.chapter_code}:{item.chapter.title}:{round(item.probability, 4)}"
        for item in result.candidates
    ]
    if result.chapter and not result.is_low_confidence and chapter_in_catalog(result.chapter, catalog_keys):
        return result.chapter, result.chapter.volume_code, False, result.reason, candidate_text
    return None, (result.volume_code or resource.volume_code), True, result.reason, candidate_text


def append_review_note(resource: models.Resource, reason: str) -> None:
    message = f"[strict-migration] {reason}"
    if resource.review_note:
        if message in resource.review_note:
            return
        resource.review_note = f"{resource.review_note}\n{message}"[:4000]
        return
    resource.review_note = message[:4000]


def write_manual_review_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "resource_id",
                "title",
                "filename",
                "volume_code",
                "reason",
                "candidates",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    catalog_keys = load_catalog_keys()
    db = WriteSessionLocal()
    review_rows: list[dict] = []
    try:
        query = (
            db.query(models.Resource)
            .filter(
                models.Resource.id >= args.from_id,
                models.Resource.is_trashed.is_(False),
            )
            .order_by(models.Resource.id.asc())
        )
        if args.limit > 0:
            query = query.limit(args.limit)
        rows = query.all()

        print(
            f"strict migrate start: count={len(rows)} from_id={args.from_id} "
            f"dry_run={args.dry_run} manual_review_file={args.manual_review_file}"
        )
        updated = 0
        hidden = 0
        skipped = 0
        failed = 0

        for resource in rows:
            try:
                chapter, volume_code, low_confidence, reason, candidates = classify_if_needed(db, resource, catalog_keys)
                section_code = infer_section_code(resource)
                filename = infer_filename(resource)

                if low_confidence:
                    print(
                        f"[MANUAL] id={resource.id} title={resource.title} "
                        f"volume={volume_code or '-'} reason={reason}"
                    )
                    review_rows.append(
                        {
                            "resource_id": resource.id,
                            "title": resource.title,
                            "filename": filename,
                            "volume_code": volume_code or "",
                            "reason": reason,
                            "candidates": " | ".join(candidates),
                        }
                    )
                    if args.dry_run:
                        skipped += 1
                        continue

                    resource.chapter_id = None
                    resource.volume_code = volume_code
                    resource.status = models.ResourceStatus.hidden
                    append_review_note(resource, reason)
                    db.add(resource)
                    db.commit()
                    hidden += 1
                    continue

                keyword = chapter_classifier.normalize_keyword(
                    " ".join((resource.ai_tags or []) + (resource.tags or [])) or resource.title or filename,
                    fallback=chapter_classifier.clean_filename_stem(filename, fallback="资源"),
                )
                title = chapter_classifier.build_resource_title(
                    volume_code=volume_code,
                    chapter_code=chapter.chapter_code if chapter else None,
                    section_code=section_code,
                    keyword=keyword,
                )

                new_key = None
                if resource.storage_provider == models.StorageProvider.minio and resource.object_key:
                    new_key = storage.build_resource_object_key(
                        filename,
                        chapter.chapter_code if chapter else None,
                        section_code,
                        volume_code=volume_code,
                        base_name=title,
                        low_confidence=False,
                    )

                print(
                    f"[PLAN] id={resource.id} old_key={resource.object_key or '-'} "
                    f"new_key={new_key or '-'} chapter={chapter.id if chapter else '-'} volume={volume_code or '-'}"
                )

                if args.dry_run:
                    skipped += 1
                    continue

                changed = False
                if new_key and resource.object_key and new_key != resource.object_key:
                    storage.copy_object(resource.object_key, new_key)
                    storage.delete_object(resource.object_key)
                    resource.object_key = new_key
                    changed = True

                if resource.title != title[:255]:
                    resource.title = title[:255]
                    changed = True
                if resource.chapter_id != (chapter.id if chapter else None):
                    resource.chapter_id = chapter.id if chapter else None
                    changed = True
                if resource.volume_code != volume_code:
                    resource.volume_code = volume_code
                    changed = True
                if resource.source_filename != filename:
                    resource.source_filename = filename
                    changed = True
                if not resource.title_auto_generated:
                    resource.title_auto_generated = True
                    changed = True
                if resource.rename_version != "v1":
                    resource.rename_version = "v1"
                    changed = True

                if changed:
                    db.add(resource)

                rag_rows = (
                    db.query(models.RagSource)
                    .filter(
                        models.RagSource.source_type == "resource",
                        models.RagSource.resource_id == resource.id,
                    )
                    .all()
                )
                for rag_source in rag_rows:
                    rag_changed = False
                    if rag_source.title != resource.title:
                        rag_source.title = resource.title
                        rag_changed = True
                    if resource.object_key and rag_source.object_key != resource.object_key:
                        rag_source.object_key = resource.object_key
                        rag_changed = True
                    if rag_changed:
                        db.add(rag_source)

                db.commit()
                updated += 1
            except Exception as error:  # noqa: BLE001
                db.rollback()
                failed += 1
                print(f"[FAIL] id={resource.id} error={error}")

        review_path = Path(args.manual_review_file)
        write_manual_review_csv(review_path, review_rows)
        print(
            f"strict migrate done: updated={updated} hidden={hidden} skipped={skipped} failed={failed} "
            f"manual_review={review_path if review_rows else '-'}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
