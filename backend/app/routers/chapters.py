import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.core.config import settings
from app.deps import get_current_admin, get_db_read, get_db_write


router = APIRouter(tags=["chapters"])
logger = logging.getLogger(__name__)

STRICT_STAGE = "senior"
STRICT_SUBJECT = "物理"
CATALOG_PATH = Path(__file__).resolve().parents[2] / "scripts" / "data" / "pep_physics_2019_full.json"


def _is_strict_scope(stage: str, subject: str) -> bool:
    return bool(settings.STRICT_PEP_CATALOG and stage == STRICT_STAGE and subject == STRICT_SUBJECT)


def _load_catalog_payload() -> dict:
    if not CATALOG_PATH.exists():
        raise RuntimeError(f"PEP catalog file not found: {CATALOG_PATH}")

    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f"PEP catalog file is invalid JSON: {CATALOG_PATH}") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("chapters"), list):
        raise RuntimeError("PEP catalog payload must include a `chapters` array")
    return payload


def _normalize_keywords(values: list[str] | None) -> list[str]:
    raw = values or []
    return list(dict.fromkeys(item.strip() for item in raw if isinstance(item, str) and item.strip()))


def _catalog_chapter_keys(payload: dict | None = None) -> set[tuple[str, str, str, str]]:
    data = payload or _load_catalog_payload()
    rows = data.get("chapters") or []
    keys: set[tuple[str, str, str, str]] = set()
    for row in rows:
        stage = str(row.get("stage") or "").strip()
        subject = str(row.get("subject") or "").strip()
        volume_code = str(row.get("volume_code") or "").strip()
        chapter_code = str(row.get("chapter_code") or "").strip()
        if stage and subject and volume_code and chapter_code:
            keys.add((stage, subject, volume_code, chapter_code))
    return keys


def _enforce_pep_catalog_scope(
    *,
    stage: str,
    subject: str,
    volume_code: str,
    chapter_code: str,
) -> None:
    if not _is_strict_scope(stage, subject):
        return
    allowed = _catalog_chapter_keys()
    if (stage, subject, volume_code, chapter_code) not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="章节不在人教版2019目录内，请使用标准目录章节",
        )


def ensure_demo_chapters(db: Session) -> dict:
    payload = _load_catalog_payload()
    chapter_rows = payload.get("chapters") or []
    catalog_version = str(payload.get("catalog_version") or "unknown")

    chapter_map: dict[tuple[str, str, str, str], models.Chapter] = {}
    managed_scope: set[tuple[str, str]] = set()
    created_count = 0
    updated_count = 0
    enabled_count = 0
    disabled_count = 0

    for row in chapter_rows:
        stage = str(row.get("stage") or STRICT_STAGE).strip() or STRICT_STAGE
        subject = str(row.get("subject") or STRICT_SUBJECT).strip() or STRICT_SUBJECT
        managed_scope.add((stage, subject))
        grade = str(row.get("grade") or "高一").strip() or "高一"
        textbook = str(row.get("textbook") or "人教版2019").strip() or "人教版2019"
        volume_code = str(row.get("volume_code") or "").strip()
        volume_name = str(row.get("volume_name") or "").strip()
        chapter_code = str(row.get("chapter_code") or "").strip()
        title = str(row.get("title") or "").strip()
        if not volume_code or not volume_name or not chapter_code or not title:
            continue

        volume_order = int(row.get("volume_order") or 10)
        chapter_order = int(row.get("chapter_order") or 10)
        keywords = _normalize_keywords(row.get("chapter_keywords") or [])

        exists = (
            db.query(models.Chapter)
            .filter(
                models.Chapter.stage == stage,
                models.Chapter.subject == subject,
                models.Chapter.volume_code == volume_code,
                models.Chapter.chapter_code == chapter_code,
            )
            .first()
        )
        if not exists:
            exists = (
                db.query(models.Chapter)
                .filter(
                    models.Chapter.stage == stage,
                    models.Chapter.subject == subject,
                    models.Chapter.chapter_code == chapter_code,
                    models.Chapter.title == title,
                )
                .first()
            )

        if exists:
            changed = False
            updates = {
                "grade": grade,
                "textbook": textbook,
                "volume_code": volume_code,
                "volume_name": volume_name,
                "volume_order": volume_order,
                "chapter_order": chapter_order,
                "chapter_keywords": keywords,
                "title": title,
            }
            for attr, new_value in updates.items():
                if getattr(exists, attr) != new_value:
                    setattr(exists, attr, new_value)
                    changed = True

            if not exists.is_enabled:
                exists.is_enabled = True
                enabled_count += 1
                changed = True

            if changed:
                updated_count += 1
                db.add(exists)
            db.flush()
            chapter_map[(stage, subject, volume_code, chapter_code)] = exists
            continue

        created = models.Chapter(
            stage=stage,
            subject=subject,
            grade=grade,
            textbook=textbook,
            volume_code=volume_code,
            volume_name=volume_name,
            volume_order=volume_order,
            chapter_order=chapter_order,
            chapter_code=chapter_code,
            chapter_keywords=keywords,
            title=title,
            is_enabled=True,
        )
        db.add(created)
        db.flush()
        chapter_map[(stage, subject, volume_code, chapter_code)] = created
        created_count += 1

    for stage, subject in managed_scope:
        rows = (
            db.query(models.Chapter)
            .filter(
                models.Chapter.stage == stage,
                models.Chapter.subject == subject,
            )
            .all()
        )
        for chapter in rows:
            key = (stage, subject, chapter.volume_code, chapter.chapter_code)
            if key in chapter_map:
                continue
            if chapter.is_enabled:
                chapter.is_enabled = False
                db.add(chapter)
                disabled_count += 1

    if settings.STRICT_PEP_CATALOG:
        db.query(models.ChapterAlias).filter(
            models.ChapterAlias.stage == STRICT_STAGE,
            models.ChapterAlias.subject == STRICT_SUBJECT,
        ).delete(synchronize_session=False)

    db.commit()
    result = {
        "catalog_version": catalog_version,
        "managed_scope_count": len(managed_scope),
        "created_count": created_count,
        "updated_count": updated_count,
        "enabled_count": enabled_count,
        "disabled_count": disabled_count,
    }
    logger.info("pep catalog sync done: %s", result)
    return result


def _build_catalog_audit(db: Session, *, stage: str, subject: str) -> schemas.ChapterCatalogAuditOut:
    payload = _load_catalog_payload()
    catalog_version = str(payload.get("catalog_version") or "unknown")
    catalog_rows = [
        row
        for row in (payload.get("chapters") or [])
        if str(row.get("stage") or "").strip() == stage and str(row.get("subject") or "").strip() == subject
    ]
    expected_map: dict[tuple[str, str], dict] = {}
    for row in catalog_rows:
        volume_code = str(row.get("volume_code") or "").strip()
        chapter_code = str(row.get("chapter_code") or "").strip()
        if volume_code and chapter_code:
            expected_map[(volume_code, chapter_code)] = row

    db_rows = (
        db.query(models.Chapter)
        .filter(
            models.Chapter.stage == stage,
            models.Chapter.subject == subject,
        )
        .all()
    )

    matched_keys: set[tuple[str, str]] = set()
    unexpected_enabled: list[str] = []
    mismatched_fields: list[str] = []
    disabled_catalog_count = 0

    for row in db_rows:
        key = (row.volume_code, row.chapter_code)
        catalog_row = expected_map.get(key)
        if not catalog_row:
            if row.is_enabled:
                unexpected_enabled.append(f"{row.volume_code}-{row.chapter_code}:{row.title}")
            continue

        matched_keys.add(key)
        if not row.is_enabled:
            disabled_catalog_count += 1

        checks = (
            ("title", row.title, str(catalog_row.get("title") or "").strip()),
            ("volume_name", row.volume_name, str(catalog_row.get("volume_name") or "").strip()),
            ("volume_order", row.volume_order, int(catalog_row.get("volume_order") or 10)),
            ("chapter_order", row.chapter_order, int(catalog_row.get("chapter_order") or 10)),
        )
        for field, actual, expected in checks:
            if actual != expected:
                mismatched_fields.append(f"{row.volume_code}-{row.chapter_code}:{field}")

    missing_keys = [key for key in expected_map if key not in matched_keys]
    return schemas.ChapterCatalogAuditOut(
        strict_enabled=settings.STRICT_PEP_CATALOG,
        catalog_version=catalog_version,
        stage=stage,
        subject=subject,
        expected_count=len(expected_map),
        db_count=len(db_rows),
        missing_count=len(missing_keys),
        disabled_catalog_count=disabled_catalog_count,
        unexpected_enabled_count=len(unexpected_enabled),
        mismatched_field_count=len(mismatched_fields),
        missing_samples=[f"{volume}-{chapter}" for volume, chapter in missing_keys[:20]],
        unexpected_enabled_samples=unexpected_enabled[:20],
        mismatched_field_samples=mismatched_fields[:20],
    )


@router.get("", response_model=list[schemas.ChapterOut])
def list_chapters(
    stage: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    grade: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    db: Session = Depends(get_db_read),
):
    query = db.query(models.Chapter)
    if stage:
        query = query.filter(models.Chapter.stage == stage)
    if subject:
        query = query.filter(models.Chapter.subject == subject)
    if grade:
        query = query.filter(models.Chapter.grade == grade)
    if enabled_only:
        query = query.filter(models.Chapter.is_enabled.is_(True))

    return query.order_by(
        models.Chapter.stage.asc(),
        models.Chapter.subject.asc(),
        models.Chapter.volume_order.asc(),
        models.Chapter.chapter_order.asc(),
        models.Chapter.chapter_code.asc(),
    ).all()


@router.post("", response_model=schemas.ChapterOut, status_code=status.HTTP_201_CREATED)
def create_chapter(
    payload: schemas.ChapterCreateRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    if _is_strict_scope(payload.stage, payload.subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="严格目录模式下禁止新增章节，请通过目录文件同步",
        )

    _enforce_pep_catalog_scope(
        stage=payload.stage,
        subject=payload.subject,
        volume_code=payload.volume_code,
        chapter_code=payload.chapter_code,
    )
    exists = (
        db.query(models.Chapter)
        .filter(
            models.Chapter.subject == payload.subject,
            models.Chapter.volume_code == payload.volume_code,
            models.Chapter.chapter_code == payload.chapter_code,
        )
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chapter already exists",
        )

    chapter = models.Chapter(
        stage=payload.stage,
        subject=payload.subject,
        grade=payload.grade,
        textbook=payload.textbook,
        volume_code=payload.volume_code,
        volume_name=payload.volume_name,
        volume_order=payload.volume_order,
        chapter_order=payload.chapter_order,
        chapter_code=payload.chapter_code,
        chapter_keywords=payload.chapter_keywords,
        title=payload.title,
        is_enabled=True,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@router.patch("/{chapter_id}", response_model=schemas.ChapterOut)
def update_chapter(
    chapter_id: int,
    payload: schemas.ChapterUpdateRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    if _is_strict_scope(chapter.stage, chapter.subject):
        locked_fields = {
            "volume_code": payload.volume_code,
            "volume_name": payload.volume_name,
            "volume_order": payload.volume_order,
            "chapter_code": payload.chapter_code,
            "title": payload.title,
        }
        blocked = [name for name, value in locked_fields.items() if value is not None]
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"严格目录模式下禁止修改字段: {', '.join(blocked)}",
            )

    stage = chapter.stage
    subject = chapter.subject
    next_volume_code = payload.volume_code or chapter.volume_code
    next_chapter_code = payload.chapter_code or chapter.chapter_code
    _enforce_pep_catalog_scope(
        stage=stage,
        subject=subject,
        volume_code=next_volume_code,
        chapter_code=next_chapter_code,
    )

    if payload.grade is not None:
        chapter.grade = payload.grade
    if payload.volume_code and payload.volume_code != chapter.volume_code:
        duplicate = (
            db.query(models.Chapter)
            .filter(
                models.Chapter.id != chapter_id,
                models.Chapter.subject == chapter.subject,
                models.Chapter.volume_code == payload.volume_code,
                models.Chapter.chapter_code == chapter.chapter_code,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Volume code already has same chapter code")
    if payload.chapter_code and payload.chapter_code != chapter.chapter_code:
        duplicate = (
            db.query(models.Chapter)
            .filter(
                models.Chapter.id != chapter_id,
                models.Chapter.subject == chapter.subject,
                models.Chapter.volume_code == (payload.volume_code or chapter.volume_code),
                models.Chapter.chapter_code == payload.chapter_code,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Chapter code already exists")
        chapter.chapter_code = payload.chapter_code

    if payload.textbook is not None:
        chapter.textbook = payload.textbook
    if payload.volume_code is not None:
        chapter.volume_code = payload.volume_code
    if payload.volume_name is not None:
        chapter.volume_name = payload.volume_name
    if payload.volume_order is not None:
        chapter.volume_order = payload.volume_order
    if payload.chapter_order is not None:
        chapter.chapter_order = payload.chapter_order
    if payload.chapter_keywords is not None:
        chapter.chapter_keywords = list(
            dict.fromkeys(item.strip() for item in payload.chapter_keywords if item and item.strip())
        )
    if payload.title is not None:
        chapter.title = payload.title
    if payload.is_enabled is not None:
        chapter.is_enabled = payload.is_enabled

    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@router.post("/sync-strict", response_model=schemas.ChapterSyncOut)
def sync_strict_chapters(
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    stats = ensure_demo_chapters(db)
    return schemas.ChapterSyncOut(strict_enabled=settings.STRICT_PEP_CATALOG, **stats)


@router.get("/catalog-audit", response_model=schemas.ChapterCatalogAuditOut)
def catalog_audit(
    stage: str = Query(default=STRICT_STAGE),
    subject: str = Query(default=STRICT_SUBJECT),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_admin),
):
    return _build_catalog_audit(db, stage=stage, subject=subject)


@router.post("/seed", status_code=status.HTTP_201_CREATED)
def seed_chapters(
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    stats = ensure_demo_chapters(db)
    return {"status": "ok", "stats": stats}
