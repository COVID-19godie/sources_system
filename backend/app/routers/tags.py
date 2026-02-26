from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.deps import get_current_admin, get_db_read, get_db_write


router = APIRouter(tags=["tags"])

PHYSICS_DEFAULT_TAGS = [
    ("mechanics", "直线运动", 10),
    ("mechanics", "牛顿定律", 20),
    ("mechanics", "圆周运动", 30),
    ("mechanics", "机械能守恒", 40),
    ("electromagnetism", "电场", 50),
    ("electromagnetism", "恒定电流", 60),
    ("electromagnetism", "磁场", 70),
    ("electromagnetism", "电磁感应", 80),
    ("thermodynamics", "分子动理论", 90),
    ("thermodynamics", "热力学定律", 100),
    ("optics", "几何光学", 110),
    ("optics", "波动光学", 120),
    ("modern_physics", "原子结构", 130),
    ("modern_physics", "原子核", 140),
    ("experiment", "实验探究", 150),
    ("problem_solving", "模型建构", 160),
    ("problem_solving", "高考真题", 170),
    ("problem_solving", "易错点", 180),
]


def ensure_default_tags(db: Session) -> None:
    for category, tag, sort_order in PHYSICS_DEFAULT_TAGS:
        exists = (
            db.query(models.ResourceTag)
            .filter(
                models.ResourceTag.stage == "senior",
                models.ResourceTag.subject == "物理",
                models.ResourceTag.tag == tag,
            )
            .first()
        )
        if exists:
            exists.category = category
            exists.sort_order = sort_order
            if not exists.is_enabled:
                exists.is_enabled = True
            db.add(exists)
            continue

        db.add(
            models.ResourceTag(
                stage="senior",
                subject="物理",
                tag=tag,
                category=category,
                sort_order=sort_order,
                is_enabled=True,
            )
        )
    db.commit()


@router.get("", response_model=list[schemas.ResourceTagOut])
def list_tags(
    stage: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    category: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db_read),
):
    query = db.query(models.ResourceTag)
    if stage:
        query = query.filter(models.ResourceTag.stage == stage)
    if subject:
        query = query.filter(models.ResourceTag.subject == subject)
    if category:
        query = query.filter(models.ResourceTag.category == category)
    if enabled_only:
        query = query.filter(models.ResourceTag.is_enabled.is_(True))
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.ResourceTag.tag.ilike(pattern),
                models.ResourceTag.category.ilike(pattern),
            )
        )

    return query.order_by(
        models.ResourceTag.category.asc(),
        models.ResourceTag.sort_order.asc(),
        models.ResourceTag.id.asc(),
    ).all()


@router.post("", response_model=schemas.ResourceTagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: schemas.TagCreateRequest,
    db: Session = Depends(get_db_write),
    admin: models.User = Depends(get_current_admin),
):
    duplicate = (
        db.query(models.ResourceTag)
        .filter(
            models.ResourceTag.stage == payload.stage,
            models.ResourceTag.subject == payload.subject,
            models.ResourceTag.tag == payload.tag,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Tag already exists")

    tag = models.ResourceTag(
        stage=payload.stage,
        subject=payload.subject,
        tag=payload.tag.strip(),
        category=payload.category.strip(),
        sort_order=payload.sort_order,
        is_enabled=payload.is_enabled,
        created_by=admin.id,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.patch("/{tag_id}", response_model=schemas.ResourceTagOut)
def update_tag(
    tag_id: int,
    payload: schemas.TagUpdateRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    row = db.query(models.ResourceTag).filter(models.ResourceTag.id == tag_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")

    if payload.tag and payload.tag.strip() != row.tag:
        duplicate = (
            db.query(models.ResourceTag)
            .filter(
                models.ResourceTag.id != tag_id,
                models.ResourceTag.stage == row.stage,
                models.ResourceTag.subject == row.subject,
                models.ResourceTag.tag == payload.tag.strip(),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Tag already exists")
        row.tag = payload.tag.strip()

    if payload.category is not None:
        row.category = payload.category.strip()
    if payload.sort_order is not None:
        row.sort_order = payload.sort_order
    if payload.is_enabled is not None:
        row.is_enabled = payload.is_enabled

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/reorder", response_model=list[schemas.ResourceTagOut])
def reorder_tags(
    payload: schemas.TagReorderRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    ids = [item.id for item in payload.items]
    rows = db.query(models.ResourceTag).filter(models.ResourceTag.id.in_(ids)).all()
    mapping = {row.id: row for row in rows}
    if len(mapping) != len(ids):
        raise HTTPException(status_code=400, detail="Some tag ids are invalid")

    for item in payload.items:
        mapping[item.id].sort_order = item.sort_order
        db.add(mapping[item.id])

    db.commit()
    return (
        db.query(models.ResourceTag)
        .filter(models.ResourceTag.id.in_(ids))
        .order_by(models.ResourceTag.sort_order.asc(), models.ResourceTag.id.asc())
        .all()
    )
