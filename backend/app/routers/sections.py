from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.deps import get_current_admin, get_db_read, get_db_write


router = APIRouter(tags=["sections"])

PHYSICS_DEFAULT_SECTIONS = [
    ("tutorial", "课程讲解", "核心概念讲解、课堂例题拆解与章节导学", 10),
    ("thinking", "思维训练", "物理模型建构、方法迁移与解题策略训练", 20),
    ("interdisciplinary", "跨学科项目", "物理与数学/信息/工程融合任务与项目活动", 30),
    ("experiment", "实验探究", "实验原理、操作步骤、数据处理与误差分析", 40),
    ("exercise", "题型训练", "分层题组、典型题型与易错点专项训练", 50),
    ("exam", "高考真题", "历年真题、地区联考题与命题趋势解析", 60),
    ("simulation", "仿真可视化", "仿真动画、交互演示与过程可视化资源", 70),
    ("lab", "实验设计", "实验改进、器材方案与开放性实验设计案例", 80),
    ("reading", "拓展阅读", "学科史、前沿科普与课外拓展阅读材料", 90),
    ("project", "项目化学习", "情境任务、研究性学习与综合实践成果", 100),
]


def ensure_default_sections(db: Session) -> None:
    for code, name, description, sort_order in PHYSICS_DEFAULT_SECTIONS:
        exists = (
            db.query(models.ResourceSection)
            .filter(
                models.ResourceSection.stage == "senior",
                models.ResourceSection.subject == "物理",
                models.ResourceSection.code == code,
            )
            .first()
        )
        if exists:
            changed = False
            if exists.name != name:
                exists.name = name
                changed = True
            if (exists.description or "") != (description or ""):
                exists.description = description
                changed = True
            if exists.sort_order != sort_order:
                exists.sort_order = sort_order
                changed = True
            if not exists.is_enabled:
                exists.is_enabled = True
                changed = True
            if changed:
                db.add(exists)
            continue

        db.add(
            models.ResourceSection(
                stage="senior",
                subject="物理",
                code=code,
                name=name,
                description=description,
                sort_order=sort_order,
                is_enabled=True,
            )
        )
    db.commit()


@router.get("", response_model=list[schemas.ResourceSectionOut])
def list_sections(
    stage: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    db: Session = Depends(get_db_read),
):
    query = db.query(models.ResourceSection)
    if stage:
        query = query.filter(models.ResourceSection.stage == stage)
    if subject:
        query = query.filter(models.ResourceSection.subject == subject)
    if enabled_only:
        query = query.filter(models.ResourceSection.is_enabled.is_(True))

    return query.order_by(
        models.ResourceSection.sort_order.asc(),
        models.ResourceSection.id.asc(),
    ).all()


@router.post("", response_model=schemas.ResourceSectionOut, status_code=status.HTTP_201_CREATED)
def create_section(
    payload: schemas.SectionCreateRequest,
    db: Session = Depends(get_db_write),
    admin: models.User = Depends(get_current_admin),
):
    exists = (
        db.query(models.ResourceSection)
        .filter(
            models.ResourceSection.stage == payload.stage,
            models.ResourceSection.subject == payload.subject,
            models.ResourceSection.code == payload.code,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Section already exists")

    section = models.ResourceSection(
        stage=payload.stage,
        subject=payload.subject,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        sort_order=payload.sort_order,
        is_enabled=payload.is_enabled,
        created_by=admin.id,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.patch("/{section_id}", response_model=schemas.ResourceSectionOut)
def update_section(
    section_id: int,
    payload: schemas.SectionUpdateRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    section = db.query(models.ResourceSection).filter(models.ResourceSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    if payload.code and payload.code != section.code:
        duplicate = (
            db.query(models.ResourceSection)
            .filter(
                models.ResourceSection.id != section_id,
                models.ResourceSection.stage == section.stage,
                models.ResourceSection.subject == section.subject,
                models.ResourceSection.code == payload.code,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Section code already exists")
        section.code = payload.code

    if payload.name is not None:
        section.name = payload.name
    if payload.description is not None:
        section.description = payload.description
    if payload.sort_order is not None:
        section.sort_order = payload.sort_order
    if payload.is_enabled is not None:
        section.is_enabled = payload.is_enabled

    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.post("/reorder", response_model=list[schemas.ResourceSectionOut])
def reorder_sections(
    payload: schemas.SectionReorderRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    ids = [item.id for item in payload.items]
    rows = db.query(models.ResourceSection).filter(models.ResourceSection.id.in_(ids)).all()
    mapping = {row.id: row for row in rows}
    if len(mapping) != len(ids):
        raise HTTPException(status_code=400, detail="Some section ids are invalid")

    for item in payload.items:
        mapping[item.id].sort_order = item.sort_order
        db.add(mapping[item.id])

    db.commit()
    return (
        db.query(models.ResourceSection)
        .filter(models.ResourceSection.id.in_(ids))
        .order_by(models.ResourceSection.sort_order.asc(), models.ResourceSection.id.asc())
        .all()
    )
