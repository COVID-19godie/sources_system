import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.core.mineru_api import (
    MinerUAPIError,
    create_batch_and_upload_bytes,
    download_binary,
    extract_first_result_item,
    extract_markdown_from_zip,
    request_batch_result,
    request_create_batch,
)
from app.core.storage import upload_bytes, upload_file
from app.deps import get_current_user, get_db_read, get_db_write


router = APIRouter(tags=["mineru"])


def _serialize_job(job: models.MineruJob) -> schemas.MineruJobOut:
    return schemas.MineruJobOut.model_validate(job)


def _ensure_job_access(job: models.MineruJob, current_user: models.User) -> None:
    if current_user.role == models.UserRole.admin:
        return
    if job.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")


def _infer_section_for_materialize(
    db: Session,
    section_id: int | None,
    resource_kind: str | None,
    stage: str | None,
    subject: str | None,
) -> tuple[int | None, str]:
    section = None
    if section_id is not None:
        section = db.query(models.ResourceSection).filter(models.ResourceSection.id == section_id).first()
        if not section:
            raise HTTPException(status_code=400, detail="Invalid section_id")
        if not section.is_enabled:
            raise HTTPException(status_code=400, detail="Section is disabled")

    if section is None and resource_kind:
        section = (
            db.query(models.ResourceSection)
            .filter(
                models.ResourceSection.stage == (stage or "senior"),
                models.ResourceSection.subject == (subject or ""),
                models.ResourceSection.code == resource_kind,
            )
            .first()
        )

    if section is not None:
        return section.id, section.code

    resolved_kind = resource_kind or "tutorial"
    if resolved_kind not in schemas.RESOURCE_KIND_VALUES:
        raise HTTPException(status_code=400, detail="Invalid resource_kind")
    return None, resolved_kind


def _materialize_resource(
    db: Session,
    job: models.MineruJob,
    current_user: models.User,
    payload: schemas.MineruMaterializeRequest,
) -> models.Resource:
    if not job.markdown_object_key:
        raise HTTPException(status_code=400, detail="Job markdown is not ready")

    chapter = None
    if payload.chapter_id is not None:
        chapter = db.query(models.Chapter).filter(models.Chapter.id == payload.chapter_id).first()
        if not chapter:
            raise HTTPException(status_code=400, detail="Invalid chapter_id")

    subject = payload.subject or (chapter.subject if chapter else "物理")
    grade = payload.grade or (chapter.grade if chapter else None)
    stage = chapter.stage if chapter else ("senior" if (grade or "").startswith("高") else None)
    section_id, resolved_kind = _infer_section_for_materialize(
        db=db,
        section_id=payload.section_id,
        resource_kind=payload.resource_kind,
        stage=stage,
        subject=subject,
    )

    title = payload.title or Path(job.source_filename).stem or f"MinerU 资源 {job.id}"
    resource = models.Resource(
        title=title,
        type=payload.type,
        description=payload.description,
        subject=subject,
        grade=grade,
        tags=payload.tags,
        status=models.ResourceStatus.pending,
        resource_kind=resolved_kind,
        file_format="markdown",
        difficulty=payload.difficulty,
        section_id=section_id,
        storage_provider=models.StorageProvider.minio,
        object_key=job.markdown_object_key,
        chapter_id=payload.chapter_id,
        author_id=current_user.id,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    if payload.chapter_id:
        link = models.ResourceChapterLink(resource_id=resource.id, chapter_id=payload.chapter_id)
        db.add(link)
        db.commit()

    return resource


@router.post("/file-urls/batch")
def mineru_create_batch_proxy(
    payload: dict,
    _: models.User = Depends(get_current_user),
):
    try:
        return request_create_batch(payload)
    except MinerUAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/extract-results/batch/{batch_id}")
def mineru_extract_result_proxy(
    batch_id: str,
    _: models.User = Depends(get_current_user),
):
    try:
        return request_batch_result(batch_id)
    except MinerUAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/jobs", response_model=schemas.MineruJobOut)
def create_mineru_job(
    file: UploadFile = File(...),
    parse_options: str = Form(default="{}"),
    auto_create_resource: bool = Form(default=False),
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        options = json.loads(parse_options) if parse_options.strip() else {}
        if not isinstance(options, dict):
            raise ValueError
    except ValueError as error:
        raise HTTPException(status_code=400, detail="parse_options must be JSON object") from error

    payload_bytes = file.file.read()
    if not payload_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    file.file.seek(0)

    source_object_key = None
    try:
        source_object_key, _ = upload_file(file)
    except Exception:  # noqa: BLE001
        source_object_key = None

    try:
        batch_id = create_batch_and_upload_bytes(
            payload=payload_bytes,
            filename=file.filename,
            parse_options=options,
        )
    except MinerUAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    job = models.MineruJob(
        creator_id=current_user.id,
        source_filename=file.filename,
        source_object_key=source_object_key,
        batch_id=batch_id,
        status=models.MineruJobStatus.submitted,
        parse_options=options,
        auto_create_resource=auto_create_resource,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _serialize_job(job)


@router.get("/jobs", response_model=list[schemas.MineruJobOut])
def list_mineru_jobs(
    all: bool = Query(default=False),
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.MineruJob)
    if not all or current_user.role != models.UserRole.admin:
        query = query.filter(models.MineruJob.creator_id == current_user.id)
    rows = query.order_by(models.MineruJob.created_at.desc()).all()
    return [_serialize_job(row) for row in rows]


@router.get("/jobs/{job_id}", response_model=schemas.MineruJobOut)
def get_mineru_job(
    job_id: int,
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    job = db.query(models.MineruJob).filter(models.MineruJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _ensure_job_access(job, current_user)
    return _serialize_job(job)


@router.post("/jobs/{job_id}/refresh", response_model=schemas.MineruJobOut)
def refresh_mineru_job(
    job_id: int,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    job = db.query(models.MineruJob).filter(models.MineruJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _ensure_job_access(job, current_user)

    try:
        official_result = request_batch_result(job.batch_id)
    except MinerUAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    job.official_result = official_result
    first = extract_first_result_item(official_result)
    if not first:
        job.status = models.MineruJobStatus.processing
        db.add(job)
        db.commit()
        db.refresh(job)
        return _serialize_job(job)

    state = str(first.get("state") or "").lower()
    if state == "failed":
        job.status = models.MineruJobStatus.failed
        job.error_message = str(first.get("err_msg") or "MinerU parse failed")
    elif state == "done":
        job.status = models.MineruJobStatus.done
        zip_url = first.get("full_zip_url")
        if zip_url and not job.markdown_object_key:
            zip_bytes = download_binary(str(zip_url))
            markdown = extract_markdown_from_zip(zip_bytes)
            object_key = f"mineru/markdown/{job.id}_{uuid4().hex}.md"
            upload_bytes(
                payload=markdown.encode("utf-8"),
                object_key=object_key,
                content_type="text/markdown; charset=utf-8",
            )
            job.markdown_object_key = object_key
            job.markdown_preview = markdown[:20000]
        if job.auto_create_resource and not job.resource_id and job.markdown_object_key:
            resource = _materialize_resource(
                db=db,
                job=job,
                current_user=current_user,
                payload=schemas.MineruMaterializeRequest(
                    title=Path(job.source_filename).stem,
                    type="document",
                    subject="物理",
                    tags=["MinerU", "自动解析"],
                ),
            )
            job.resource_id = resource.id
            job.status = models.MineruJobStatus.materialized
    else:
        job.status = models.MineruJobStatus.processing

    db.add(job)
    db.commit()
    db.refresh(job)
    return _serialize_job(job)


@router.post("/jobs/{job_id}/materialize", response_model=schemas.ResourceOut)
def materialize_job(
    job_id: int,
    payload: schemas.MineruMaterializeRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    job = db.query(models.MineruJob).filter(models.MineruJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _ensure_job_access(job, current_user)

    if not job.markdown_object_key:
        raise HTTPException(status_code=400, detail="请先 refresh，确保任务已完成并生成 Markdown")

    resource = _materialize_resource(db=db, job=job, current_user=current_user, payload=payload)
    job.resource_id = resource.id
    job.status = models.MineruJobStatus.materialized
    db.add(job)
    db.commit()

    section_lite = None
    if resource.section:
        section_lite = schemas.ResourceSectionLiteOut(
            id=resource.section.id,
            code=resource.section.code,
            name=resource.section.name,
        )
    return schemas.ResourceOut(
        id=resource.id,
        title=resource.title,
        description=resource.description,
        type=resource.type,
        subject=resource.subject,
        grade=resource.grade,
        tags=resource.tags,
        status=resource.status,
        resource_kind=resource.resource_kind,
        file_format=resource.file_format,
        difficulty=resource.difficulty,
        ai_summary=resource.ai_summary,
        ai_tags=resource.ai_tags or [],
        has_embedding=bool(resource.embedding_json),
        section_id=resource.section_id,
        section=section_lite,
        storage_provider=resource.storage_provider,
        object_key=resource.object_key,
        chapter_id=resource.chapter_id,
        chapter_ids=[resource.chapter_id] if resource.chapter_id else [],
        author_id=resource.author_id,
        reviewer_id=resource.reviewer_id,
        review_note=resource.review_note,
        file_path=resource.file_path,
        download_url=None,
        preview_mode=resource.file_format,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )
