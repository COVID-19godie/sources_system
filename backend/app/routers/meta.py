from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.deps import get_current_user, get_db_read


router = APIRouter(tags=["meta"])

DEFAULT_DIFFICULTIES = ["基础", "进阶", "挑战"]
DEFAULT_QUICK_QUERIES = [
    "牛顿第二定律 例题讲解",
    "楞次定律 思维训练",
    "机械能守恒 实验探究",
    "圆周运动 高考真题",
    "电磁感应 易错点",
    "原子核 综合复习",
]


@router.get("/upload-options", response_model=schemas.UploadOptionsOut)
def upload_options(
    stage: str = Query(default="senior"),
    subject: str = Query(default="物理"),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    chapters = (
        db.query(models.Chapter)
        .filter(
            models.Chapter.stage == stage,
            models.Chapter.subject == subject,
            models.Chapter.is_enabled.is_(True),
        )
        .order_by(
            models.Chapter.volume_order.asc(),
            models.Chapter.chapter_order.asc(),
            models.Chapter.chapter_code.asc(),
        )
        .all()
    )
    sections = (
        db.query(models.ResourceSection)
        .filter(
            models.ResourceSection.stage == stage,
            models.ResourceSection.subject == subject,
            models.ResourceSection.is_enabled.is_(True),
        )
        .order_by(models.ResourceSection.sort_order.asc(), models.ResourceSection.id.asc())
        .all()
    )
    tags = (
        db.query(models.ResourceTag)
        .filter(
            models.ResourceTag.stage == stage,
            models.ResourceTag.subject == subject,
            models.ResourceTag.is_enabled.is_(True),
        )
        .order_by(
            models.ResourceTag.category.asc(),
            models.ResourceTag.sort_order.asc(),
            models.ResourceTag.id.asc(),
        )
        .all()
    )
    volume_rows = sorted(
        {(item.volume_code, item.volume_name, item.volume_order) for item in chapters},
        key=lambda pair: (pair[2], pair[0]),
    )
    return schemas.UploadOptionsOut(
        chapters=[schemas.ChapterOut.model_validate(item) for item in chapters],
        volumes=[
            schemas.VolumeOut(
                volume_code=code,
                volume_name=name,
                volume_order=order,
            )
            for code, name, order in volume_rows
        ],
        chapters_grouped=[
            schemas.VolumeChapterGroupOut(
                volume=schemas.VolumeOut(
                    volume_code=volume_code,
                    volume_name=volume_name,
                    volume_order=volume_order,
                ),
                chapters=[
                    schemas.ChapterOut.model_validate(chapter)
                    for chapter in chapters
                    if chapter.volume_code == volume_code
                ],
            )
            for volume_code, volume_name, volume_order in volume_rows
        ],
        sections=[schemas.ResourceSectionOut.model_validate(item) for item in sections],
        tags=[schemas.ResourceTagOut.model_validate(item) for item in tags],
        difficulties=DEFAULT_DIFFICULTIES,
        quick_queries=DEFAULT_QUICK_QUERIES,
    )
