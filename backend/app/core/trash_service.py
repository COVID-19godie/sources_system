from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app import models
from app.core import storage as storage_service
from app.core.config import settings


RESOURCE_PREFIX = "resources/"
TRASH_SCOPE_RESOURCE = "resource"
TRASH_SCOPE_STORAGE = "storage"

TRASH_SOURCE_RESOURCE_API = "resource_api"
TRASH_SOURCE_STORAGE_API = "storage_api"
TRASH_SOURCE_RECONCILE = "reconcile"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_resource_key(key: str) -> bool:
    normalized = storage_service.normalize_key(key)
    return normalized.startswith(RESOURCE_PREFIX)


def _expires_at(base_time: datetime | None = None) -> datetime:
    anchor = base_time or utc_now()
    return anchor + timedelta(days=settings.TRASH_RETENTION_DAYS)


def build_trash_key(original_key: str, now: datetime | None = None) -> str:
    normalized = storage_service.normalize_key(original_key)
    basename = Path(normalized).name or "file"
    timestamp = (now or utc_now())
    return (
        f"{settings.TRASH_PREFIX.rstrip('/')}/"
        f"{timestamp:%Y/%m/%d}/"
        f"{uuid4().hex}_{basename}"
    )


def _build_restore_target(preferred_key: str) -> str:
    normalized = storage_service.normalize_key(preferred_key)
    if not storage_service.object_exists(normalized):
        return normalized

    parsed = Path(normalized)
    stem = parsed.stem
    suffix = parsed.suffix
    parent = parsed.parent.as_posix()
    restored_name = f"{stem} (restored-{utc_now():%Y%m%d%H%M%S}){suffix}"
    candidate = f"{parent}/{restored_name}" if parent != "." else restored_name
    while storage_service.object_exists(candidate):
        restored_name = f"{stem} (restored-{utc_now():%Y%m%d%H%M%S}-{uuid4().hex[:4]}){suffix}"
        candidate = f"{parent}/{restored_name}" if parent != "." else restored_name
    return candidate


def _move_object_to_trash(original_key: str) -> tuple[str | None, bool]:
    normalized = storage_service.normalize_key(original_key)
    if not is_resource_key(normalized):
        return None, False
    if not storage_service.object_exists(normalized):
        return None, False

    trash_key = build_trash_key(normalized)
    storage_service.copy_object(normalized, trash_key)
    storage_service.delete_object(normalized)
    return trash_key, True


def _restore_object_from_trash(trash_key: str, preferred_key: str) -> str:
    normalized_trash = storage_service.normalize_key(trash_key)
    if not storage_service.object_exists(normalized_trash):
        raise ValueError("Trash object not found")

    target_key = _build_restore_target(preferred_key)
    storage_service.copy_object(normalized_trash, target_key)
    storage_service.delete_object(normalized_trash)
    return target_key


def _build_default_original_key(resource: models.Resource) -> str:
    if resource.object_key:
        return resource.object_key
    if resource.file_path:
        return resource.file_path
    return f"resource:{resource.id}"


def _hard_delete_local_file(resource: models.Resource) -> None:
    if not resource.file_path:
        return
    filename = resource.file_path.split("/")[-1]
    local_path = Path("uploads") / filename
    if local_path.exists():
        local_path.unlink()


def _find_latest_resource_trash_item(db: Session, resource_id: int) -> models.TrashItem | None:
    return (
        db.query(models.TrashItem)
        .filter(models.TrashItem.resource_id == resource_id)
        .order_by(models.TrashItem.id.desc())
        .first()
    )


def trash_resource(
    db: Session,
    resource: models.Resource,
    *,
    source: str,
    deleted_by: int | None,
    scope: str = TRASH_SCOPE_RESOURCE,
    meta: dict | None = None,
) -> models.TrashItem:
    if resource.is_trashed:
        existing = _find_latest_resource_trash_item(db, resource.id)
        if existing:
            return existing

    now = utc_now()
    original_key = resource.object_key or resource.file_path or _build_default_original_key(resource)
    trash_key: str | None = None
    has_binary = False

    if resource.storage_provider == models.StorageProvider.minio and resource.object_key:
        trash_key, has_binary = _move_object_to_trash(resource.object_key)
        resource.object_key = None
    elif resource.storage_provider == models.StorageProvider.local:
        has_binary = bool(resource.file_path)

    resource.is_trashed = True
    resource.trashed_at = now
    resource.trashed_by = deleted_by
    resource.trash_source = source
    resource.original_object_key = original_key
    resource.trash_object_key = trash_key or resource.file_path
    resource.trash_has_binary = has_binary

    item = models.TrashItem(
        resource_id=resource.id,
        scope=scope,
        original_key=original_key,
        trash_key=trash_key or resource.file_path,
        has_binary=has_binary,
        source=source,
        deleted_by=deleted_by,
        deleted_at=now,
        expires_at=_expires_at(now),
        meta=meta or {},
    )
    db.add(resource)
    db.add(item)
    return item


def trash_storage_object(
    db: Session,
    object_key: str,
    *,
    source: str,
    deleted_by: int | None,
    meta: dict | None = None,
) -> models.TrashItem | None:
    normalized = storage_service.normalize_key(object_key)
    if normalized.endswith("/"):
        return None
    if not normalized.startswith(RESOURCE_PREFIX):
        return None

    resource = (
        db.query(models.Resource)
        .filter(
            models.Resource.object_key == normalized,
            models.Resource.is_trashed.is_(False),
        )
        .first()
    )
    if resource:
        return trash_resource(
            db,
            resource,
            source=source,
            deleted_by=deleted_by,
            scope=TRASH_SCOPE_RESOURCE,
            meta=meta,
        )

    now = utc_now()
    trash_key, has_binary = _move_object_to_trash(normalized)
    item = models.TrashItem(
        resource_id=None,
        scope=TRASH_SCOPE_STORAGE,
        original_key=normalized,
        trash_key=trash_key,
        has_binary=has_binary,
        source=source,
        deleted_by=deleted_by,
        deleted_at=now,
        expires_at=_expires_at(now),
        meta=meta or {},
    )
    db.add(item)
    return item


def trash_storage_prefix(
    db: Session,
    prefix: str,
    *,
    source: str,
    deleted_by: int | None,
) -> list[models.TrashItem]:
    normalized = storage_service.normalize_prefix(prefix)
    if not normalized.startswith(RESOURCE_PREFIX):
        return []

    items: list[models.TrashItem] = []
    processed_keys: set[str] = set()
    for row in storage_service.list_objects(prefix=normalized, recursive=True):
        key = row.object_name
        if key.endswith("/"):
            continue
        processed_keys.add(key)
        item = trash_storage_object(
            db,
            key,
            source=source,
            deleted_by=deleted_by,
            meta={"from_prefix": normalized},
        )
        if item:
            items.append(item)

    resource_rows = (
        db.query(models.Resource)
        .filter(
            models.Resource.object_key.like(f"{normalized}%"),
            models.Resource.is_trashed.is_(False),
        )
        .all()
    )
    for resource in resource_rows:
        if not resource.object_key or resource.object_key in processed_keys:
            continue
        item = trash_resource(
            db,
            resource,
            source=source,
            deleted_by=deleted_by,
            scope=TRASH_SCOPE_RESOURCE,
            meta={"from_prefix": normalized, "object_missing": True},
        )
        items.append(item)

    # directory placeholder object does not need to be restorable
    if storage_service.object_exists(normalized):
        storage_service.delete_object(normalized)
    return items


def restore_trash_item(db: Session, item: models.TrashItem) -> tuple[models.TrashItem, str | None]:
    if not item.has_binary:
        raise ValueError("该条目无二进制文件，无法恢复文件")

    restored_key: str | None = None

    if item.scope == TRASH_SCOPE_RESOURCE:
        if item.resource_id is None:
            raise ValueError("资源回收条目缺少 resource_id")
        resource = db.query(models.Resource).filter(models.Resource.id == item.resource_id).first()
        if not resource:
            raise ValueError("对应资源记录不存在")

        if resource.storage_provider == models.StorageProvider.minio:
            if not item.trash_key:
                raise ValueError("回收站对象不存在")
            preferred_key = resource.original_object_key or item.original_key
            restored_key = _restore_object_from_trash(item.trash_key, preferred_key)
            resource.object_key = restored_key
        else:
            # Local fallback path remains unchanged for soft-delete cases.
            restored_key = resource.file_path

        resource.is_trashed = False
        resource.trashed_at = None
        resource.trashed_by = None
        resource.trash_source = None
        resource.original_object_key = None
        resource.trash_object_key = None
        resource.trash_has_binary = False
        db.add(resource)
    else:
        if not item.trash_key:
            raise ValueError("回收站对象不存在")
        restored_key = _restore_object_from_trash(item.trash_key, item.original_key)

    db.delete(item)
    return item, restored_key


def purge_trash_item(db: Session, item: models.TrashItem) -> None:
    if item.has_binary and item.trash_key:
        try:
            if storage_service.object_exists(item.trash_key):
                storage_service.delete_object(item.trash_key)
        except Exception:  # noqa: BLE001
            pass

    if item.resource_id is not None:
        resource = db.query(models.Resource).filter(models.Resource.id == item.resource_id).first()
        if resource and resource.is_trashed:
            if resource.storage_provider == models.StorageProvider.local:
                _hard_delete_local_file(resource)
            (
                db.query(models.ResourceChapterLink)
                .filter(models.ResourceChapterLink.resource_id == resource.id)
                .delete(synchronize_session=False)
            )
            db.delete(resource)

    db.delete(item)


def purge_expired_items(db: Session, *, limit: int = 500) -> int:
    rows = (
        db.query(models.TrashItem)
        .filter(models.TrashItem.expires_at <= utc_now())
        .order_by(models.TrashItem.expires_at.asc())
        .limit(limit)
        .all()
    )
    for item in rows:
        purge_trash_item(db, item)
    return len(rows)


def reconcile_missing_resources(db: Session, *, dry_run: bool = False) -> dict[str, int | list[int]]:
    rows = (
        db.query(models.Resource)
        .filter(
            models.Resource.storage_provider == models.StorageProvider.minio,
            models.Resource.object_key.is_not(None),
            models.Resource.is_trashed.is_(False),
        )
        .all()
    )

    scanned_count = 0
    missing_count = 0
    trashed_count = 0
    trashed_resource_ids: list[int] = []

    for resource in rows:
        if not resource.object_key:
            continue
        if not resource.object_key.startswith(RESOURCE_PREFIX):
            continue
        scanned_count += 1

        if storage_service.object_exists(resource.object_key):
            continue

        missing_count += 1
        if dry_run:
            continue

        trash_resource(
            db,
            resource,
            source=TRASH_SOURCE_RECONCILE,
            deleted_by=None,
            scope=TRASH_SCOPE_RESOURCE,
            meta={"reason": "object_missing", "external_deleted": True},
        )
        trashed_count += 1
        trashed_resource_ids.append(resource.id)

    return {
        "scanned_count": scanned_count,
        "missing_count": missing_count,
        "trashed_count": trashed_count,
        "resource_ids": trashed_resource_ids,
    }
