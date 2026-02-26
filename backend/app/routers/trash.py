from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query

from app import models, schemas
from app.core import rag_sync, trash_service
from app.deps import get_current_admin, get_db_write


router = APIRouter(tags=["trash"])


def _to_trash_item_out(item: models.TrashItem) -> schemas.TrashItemOut:
    return schemas.TrashItemOut(
        id=item.id,
        resource_id=item.resource_id,
        resource_title=item.resource.title if item.resource else None,
        scope=item.scope,
        original_key=item.original_key,
        trash_key=item.trash_key,
        has_binary=item.has_binary,
        source=item.source,
        deleted_by=item.deleted_by,
        deleted_at=item.deleted_at,
        expires_at=item.expires_at,
        meta=item.meta or {},
    )


@router.get("/items", response_model=schemas.TrashListOut)
def list_trash_items(
    scope: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    query = db.query(models.TrashItem).order_by(models.TrashItem.deleted_at.desc(), models.TrashItem.id.desc())

    if scope:
        query = query.filter(models.TrashItem.scope == scope.strip())
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.TrashItem.original_key.ilike(pattern),
                models.TrashItem.source.ilike(pattern),
            )
        )

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return schemas.TrashListOut(
        items=[_to_trash_item_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/items/{item_id}/restore", response_model=schemas.TrashActionOut)
def restore_trash_item(
    item_id: int,
    db: Session = Depends(get_db_write),
    current_admin: models.User = Depends(get_current_admin),
):
    item = db.query(models.TrashItem).filter(models.TrashItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Trash item not found")

    snapshot = _to_trash_item_out(item)
    try:
        _, restored_key = trash_service.restore_trash_item(db, item)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if item.resource_id is not None:
        rag_sync.sync_resource_to_workspaces(
            db,
            [item.resource_id],
            actor_id=current_admin.id,
            reason="trash_restore",
        )
    db.commit()

    return schemas.TrashActionOut(
        item=snapshot,
        restored_key=restored_key,
        message="恢复成功",
    )


@router.delete("/items/{item_id}", response_model=schemas.TrashActionOut)
def purge_trash_item(
    item_id: int,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    item = db.query(models.TrashItem).filter(models.TrashItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Trash item not found")

    snapshot = _to_trash_item_out(item)
    trash_service.purge_trash_item(db, item)
    db.commit()
    return schemas.TrashActionOut(item=snapshot, message="已彻底删除")


@router.post("/purge-expired", response_model=schemas.TrashPurgeOut)
def purge_expired_trash(
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    purged = trash_service.purge_expired_items(db, limit=limit)
    db.commit()
    return schemas.TrashPurgeOut(purged_count=purged)
