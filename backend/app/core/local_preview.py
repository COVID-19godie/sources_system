from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app import models
from app.core.physics_taxonomy import find_chapter_taxonomy


PREVIEW_STAGE = "senior"
PREVIEW_SUBJECT = "物理"
PREVIEW_WORKSPACE_NAME = "高中物理本地预览"

PREVIEW_RESOURCE_BLUEPRINTS = [
    ("tutorial", "pdf", "核心讲解", "tutorial"),
    ("exercise", "pdf", "考点训练", "exercise"),
    ("simulation", "html", "图谱联动演示", "simulation"),
]


def _unique(values: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _ensure_preview_teacher(db: Session) -> models.User | None:
    user = db.query(models.User).filter(models.User.email == "preview@local").first()
    if user:
        return user

    admin = db.query(models.User).filter(models.User.role == models.UserRole.admin).first()
    if admin is None:
        return None

    user = models.User(
        email="preview@local",
        hashed_password=admin.hashed_password,
        role=models.UserRole.teacher,
    )
    db.add(user)
    db.flush()
    return user


def _ensure_preview_workspace(db: Session, *, creator_id: int) -> tuple[models.RagWorkspace, bool]:
    workspace = (
        db.query(models.RagWorkspace)
        .filter(
            models.RagWorkspace.stage == PREVIEW_STAGE,
            models.RagWorkspace.subject == PREVIEW_SUBJECT,
            models.RagWorkspace.name == PREVIEW_WORKSPACE_NAME,
        )
        .first()
    )
    if workspace:
        return workspace, False

    workspace = models.RagWorkspace(
        name=PREVIEW_WORKSPACE_NAME,
        description="本地临时预览模式自动生成，用于浏览教材目录、知识点与地图式 GraphRAG。",
        stage=PREVIEW_STAGE,
        subject=PREVIEW_SUBJECT,
        created_by=creator_id,
    )
    db.add(workspace)
    db.flush()
    return workspace, True


def seed_local_preview_data(db: Session) -> dict[str, int]:
    admin = db.query(models.User).filter(models.User.role == models.UserRole.admin).first()
    if admin is None:
        return {
            "preview_chapters": 0,
            "preview_knowledge_points": 0,
            "preview_resources": 0,
            "preview_sources": 0,
            "preview_workspace_created": 0,
        }

    _ensure_preview_teacher(db)
    workspace, workspace_created = _ensure_preview_workspace(db, creator_id=admin.id)

    sections = (
        db.query(models.ResourceSection)
        .filter(
            models.ResourceSection.stage == PREVIEW_STAGE,
            models.ResourceSection.subject == PREVIEW_SUBJECT,
            models.ResourceSection.is_enabled.is_(True),
        )
        .all()
    )
    section_by_code = {item.code: item for item in sections}

    chapters = (
        db.query(models.Chapter)
        .filter(
            models.Chapter.stage == PREVIEW_STAGE,
            models.Chapter.subject == PREVIEW_SUBJECT,
            models.Chapter.is_enabled.is_(True),
        )
        .order_by(
            models.Chapter.volume_order.asc(),
            models.Chapter.chapter_order.asc(),
            models.Chapter.id.asc(),
        )
        .all()
    )

    chapter_count = 0
    kp_count = 0
    resource_count = 0
    source_count = 0

    for chapter in chapters:
        taxonomy = find_chapter_taxonomy(
            chapter.title,
            chapter_code=chapter.chapter_code,
            chapter_keywords=chapter.chapter_keywords or [],
        )
        if taxonomy is None:
            continue

        chapter_count += 1
        knowledge_labels = _unique(
            list(taxonomy.knowledge_tags[:4])
            + list(taxonomy.focus_tags[:2])
            + list(taxonomy.exam_tags[:2])
        )[:6]
        resource_tags = _unique(
            list(taxonomy.tags[:8])
            + [chapter.volume_name, chapter.title]
        )[:10]

        created_kps: list[models.KnowledgePoint] = []
        for index, label in enumerate(knowledge_labels, start=1):
            kp_code = f"{chapter.chapter_code}-KP{index:02d}"
            kp = (
                db.query(models.KnowledgePoint)
                .filter(
                    models.KnowledgePoint.chapter_id == chapter.id,
                    models.KnowledgePoint.kp_code == kp_code,
                )
                .first()
            )
            if kp is None:
                kp = models.KnowledgePoint(
                    chapter_id=chapter.id,
                    kp_code=kp_code,
                    name=label,
                    aliases=[],
                    description="；".join(_unique(
                        [label] + list(taxonomy.focus_tags[:2]) + list(taxonomy.exam_tags[:2])
                    ))[:400],
                    difficulty="基础" if index <= 2 else "进阶",
                    prerequisite_level=round(max(0.0, (index - 1) * 0.14), 2),
                    status="published",
                )
                db.add(kp)
                db.flush()
                kp_count += 1
            created_kps.append(kp)

        for left, right in zip(created_kps, created_kps[1:]):
            edge = (
                db.query(models.KnowledgeEdge)
                .filter(
                    models.KnowledgeEdge.src_kp_id == left.id,
                    models.KnowledgeEdge.dst_kp_id == right.id,
                    models.KnowledgeEdge.edge_type == "prerequisite",
                )
                .first()
            )
            if edge is None:
                db.add(
                    models.KnowledgeEdge(
                        src_kp_id=left.id,
                        dst_kp_id=right.id,
                        edge_type="prerequisite",
                        strength=0.82,
                        evidence_count=max(1, len(taxonomy.exam_tags)),
                    )
                )

        for resource_kind, file_format, suffix, section_code in PREVIEW_RESOURCE_BLUEPRINTS:
            title = f"{chapter.title}·{suffix}"
            resource = (
                db.query(models.Resource)
                .filter(
                    models.Resource.chapter_id == chapter.id,
                    models.Resource.title == title,
                )
                .first()
            )
            section = section_by_code.get(section_code)
            summary_parts = {
                "tutorial": taxonomy.knowledge_tags[:3],
                "exercise": taxonomy.exam_tags[:3] or taxonomy.focus_tags[:3],
                "simulation": taxonomy.experiment_tags[:2] or taxonomy.problem_tags[:2] or taxonomy.focus_tags[:2],
            }
            summary_text = "；".join(_unique(summary_parts.get(resource_kind, []))) or "本地预览模式示例资源"
            if resource is None:
                resource = models.Resource(
                    title=title,
                    description=f"{chapter.volume_name}《{chapter.title}》{suffix}，用于本地预览模式展示。",
                    type="document",
                    subject=PREVIEW_SUBJECT,
                    grade=chapter.grade,
                    tags=resource_tags[:6],
                    status=models.ResourceStatus.approved,
                    resource_kind=resource_kind,
                    file_format=file_format,
                    difficulty="基础" if resource_kind == "tutorial" else "进阶",
                    ai_summary=summary_text,
                    ai_tags=resource_tags[:8],
                    section_id=section.id if section else None,
                    volume_code=chapter.volume_code,
                    source_filename=f"{chapter.chapter_code}-{resource_kind}.{file_format}",
                    external_url=f"https://example.com/preview/{chapter.volume_code}/{chapter.chapter_code}/{resource_kind}",
                    title_auto_generated=False,
                    storage_provider=models.StorageProvider.local,
                    chapter_id=chapter.id,
                    author_id=admin.id,
                )
                db.add(resource)
                db.flush()
                resource_count += 1

            source = (
                db.query(models.RagSource)
                .filter(
                    models.RagSource.workspace_id == workspace.id,
                    models.RagSource.resource_id == resource.id,
                )
                .first()
            )
            if source is None:
                source = models.RagSource(
                    workspace_id=workspace.id,
                    source_type="resource",
                    resource_id=resource.id,
                    title=resource.title,
                    object_key=None,
                    file_format=resource.file_format,
                    summary_text=resource.ai_summary or resource.description,
                    tags=_unique((resource.ai_tags or []) + (resource.tags or []))[:10],
                    embedding_json=None,
                    status="ready",
                    canonical_key=f"preview-resource:{resource.id}",
                    variant_kind="origin",
                    is_graph_visible=True,
                    display_priority=100,
                    created_by=admin.id,
                )
                db.add(source)
                source_count += 1

    db.commit()
    return {
        "preview_chapters": chapter_count,
        "preview_knowledge_points": kp_count,
        "preview_resources": resource_count,
        "preview_sources": source_count,
        "preview_workspace_created": int(workspace_created),
    }
