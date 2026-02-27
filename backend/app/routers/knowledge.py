from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.deps import get_current_user, get_db_read, get_db_write


router = APIRouter(tags=["knowledge"])


def _can_manage(user: models.User) -> bool:
    return user.role in {models.UserRole.admin, models.UserRole.teacher}


@router.get("", response_model=list[schemas.KnowledgePointOut])
def list_knowledge_points(
    chapter_id: int | None = Query(default=None),
    volume_code: str | None = Query(default=None),
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.KnowledgePoint)
    if chapter_id is not None:
        query = query.filter(models.KnowledgePoint.chapter_id == chapter_id)
    if volume_code:
        query = query.join(models.Chapter, models.Chapter.id == models.KnowledgePoint.chapter_id).filter(
            models.Chapter.volume_code == volume_code
        )
    if status_filter:
        query = query.filter(models.KnowledgePoint.status == status_filter.strip())
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.KnowledgePoint.name.ilike(keyword),
                models.KnowledgePoint.kp_code.ilike(keyword),
                models.KnowledgePoint.description.ilike(keyword),
            )
        )
    rows = (
        query.order_by(models.KnowledgePoint.chapter_id.asc(), models.KnowledgePoint.kp_code.asc())
        .limit(limit)
        .all()
    )
    return [schemas.KnowledgePointOut.model_validate(item) for item in rows]


@router.post("", response_model=schemas.KnowledgePointOut, status_code=status.HTTP_201_CREATED)
def create_knowledge_point(
    payload: schemas.KnowledgePointCreateRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")
    chapter = db.query(models.Chapter).filter(models.Chapter.id == payload.chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=400, detail="Invalid chapter_id")

    row = models.KnowledgePoint(
        chapter_id=payload.chapter_id,
        kp_code=payload.kp_code.strip(),
        name=payload.name.strip(),
        aliases=[item.strip() for item in payload.aliases if item.strip()],
        description=(payload.description or "").strip() or None,
        difficulty=(payload.difficulty or "").strip() or None,
        prerequisite_level=float(payload.prerequisite_level),
        status=(payload.status or "draft").strip() or "draft",
    )
    db.add(row)
    try:
        db.commit()
    except Exception as error:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Create knowledge point failed: {error}") from error
    db.refresh(row)
    return schemas.KnowledgePointOut.model_validate(row)


@router.patch("/{knowledge_point_id}", response_model=schemas.KnowledgePointOut)
def update_knowledge_point(
    knowledge_point_id: int,
    payload: schemas.KnowledgePointUpdateRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")
    row = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == knowledge_point_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge point not found")

    if payload.kp_code is not None:
        row.kp_code = payload.kp_code.strip()
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.aliases is not None:
        row.aliases = [item.strip() for item in payload.aliases if item.strip()]
    if payload.description is not None:
        row.description = payload.description.strip() or None
    if payload.difficulty is not None:
        row.difficulty = payload.difficulty.strip() or None
    if payload.prerequisite_level is not None:
        row.prerequisite_level = float(payload.prerequisite_level)
    if payload.status is not None:
        row.status = payload.status.strip() or row.status

    db.add(row)
    try:
        db.commit()
    except Exception as error:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Update knowledge point failed: {error}") from error
    db.refresh(row)
    return schemas.KnowledgePointOut.model_validate(row)


@router.post("/edges", response_model=schemas.KnowledgeEdgeOut, status_code=status.HTTP_201_CREATED)
def create_knowledge_edge(
    payload: schemas.KnowledgeEdgeCreateRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")
    src = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == payload.src_kp_id).first()
    dst = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == payload.dst_kp_id).first()
    if not src or not dst:
        raise HTTPException(status_code=400, detail="Invalid knowledge point id")
    if src.id == dst.id:
        raise HTTPException(status_code=400, detail="Self edge is not allowed")

    edge = models.KnowledgeEdge(
        src_kp_id=src.id,
        dst_kp_id=dst.id,
        edge_type=payload.edge_type,
        strength=float(payload.strength),
        evidence_count=int(payload.evidence_count),
    )
    db.add(edge)
    try:
        db.commit()
    except Exception as error:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Create knowledge edge failed: {error}") from error
    db.refresh(edge)
    return schemas.KnowledgeEdgeOut.model_validate(edge)
