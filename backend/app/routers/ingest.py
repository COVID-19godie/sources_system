from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import re
import threading
from urllib.parse import urldefrag, urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.core import ai_service, chapter_classifier
from app.core.db_read_write import WriteSessionLocal
from app.deps import get_current_user, get_db_read, get_db_write


router = APIRouter(tags=["ingest"])


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)


def _normalize_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="url is required")
    try:
        parsed = urlparse(value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="invalid url") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="url must be http/https")
    normalized, _ = urldefrag(value)
    return normalized


def _url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _extract_page_text(html_text: str) -> tuple[str, str, str]:
    text = html_text or ""
    title_match = _TITLE_RE.search(text)
    title = html.unescape(title_match.group(1).strip()) if title_match else ""
    desc_match = _META_DESC_RE.search(text)
    description = html.unescape(desc_match.group(1).strip()) if desc_match else ""

    body = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
    body = re.sub(r"(?is)<[^>]+>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"\s+", " ", body).strip()
    return title[:255], description[:1000], body[:8000]


def _run_ingest_job(job_id: int) -> None:
    db = WriteSessionLocal()
    try:
        job = db.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
        if not job:
            return
        job.status = "processing"
        job.progress = 0.1
        db.add(job)
        db.commit()

        url = (job.url or "").strip()
        response = requests.get(
            url,
            timeout=(5, 20),
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; EduResourceBot/1.0)"
            },
        )
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        raw_html = response.text[:2_000_000]
        title, description, content_text = _extract_page_text(raw_html)
        if not title:
            title = url

        summary = description or content_text[:220]
        ai_tags: list[str] = []
        if ai_service.is_enabled() and content_text:
            try:
                ai_summary, ai_tags = ai_service.generate_summary_and_tags(
                    content_text,
                    title=title,
                    subject=job.subject,
                )
                if ai_summary.strip():
                    summary = ai_summary.strip()
            except Exception:  # noqa: BLE001
                pass

        classify = chapter_classifier.classify_chapter(
            db,
            stage=job.stage,
            subject=job.subject,
            title=title,
            description=description,
            tags=ai_tags,
            external_url=url,
            content_text=content_text,
            top_k=3,
        )
        chapter_id = classify.recommended_chapter_id or (classify.chapter.id if classify.chapter else None)

        source_doc = (
            db.query(models.SourceDocument)
            .filter(models.SourceDocument.id == job.source_document_id)
            .first()
        )
        if not source_doc:
            source_doc = models.SourceDocument(
                source_type="url",
                url=url,
                title=title,
                summary=summary,
                tags=ai_tags,
                fingerprint=_url_fingerprint(url),
                stage=job.stage,
                subject=job.subject,
                chapter_id=chapter_id,
                confidence=classify.confidence,
                status="ready",
                created_by=job.created_by,
            )
            db.add(source_doc)
            db.flush()
            job.source_document_id = source_doc.id
        else:
            source_doc.title = title
            source_doc.summary = summary
            source_doc.tags = ai_tags
            source_doc.chapter_id = chapter_id
            source_doc.confidence = classify.confidence
            source_doc.status = "ready"
            db.add(source_doc)

        job.progress = 1.0
        job.status = "done"
        job.detail = (
            f"分类结果：{classify.chapter.volume_name if classify.chapter else '未命中'} "
            f"{classify.chapter.chapter_code if classify.chapter else ''} "
            f"{classify.chapter.title if classify.chapter else ''}"
        ).strip()
        db.add(job)
        db.commit()
    except Exception as error:  # noqa: BLE001
        db.rollback()
        job = db.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.progress = 1.0
            job.detail = str(error)[:2000]
            db.add(job)
            db.commit()
    finally:
        db.close()


@router.post("/url", response_model=schemas.IngestSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def submit_url_ingest(
    payload: schemas.IngestUrlRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    normalized_url = _normalize_url(payload.url)
    fingerprint = _url_fingerprint(normalized_url)
    existing = (
        db.query(models.SourceDocument)
        .filter(models.SourceDocument.fingerprint == fingerprint)
        .first()
    )

    source_doc: models.SourceDocument | None = existing
    if not source_doc:
        source_doc = models.SourceDocument(
            source_type="url",
            url=normalized_url,
            title=(payload.title or normalized_url)[:255],
            summary=None,
            tags=[],
            fingerprint=fingerprint,
            stage=(payload.stage or "senior").strip() or "senior",
            subject=(payload.subject or "物理").strip() or "物理",
            status="queued",
            created_by=current_user.id,
        )
        db.add(source_doc)
        db.flush()

    job = models.IngestJob(
        source_type="url",
        url=normalized_url,
        source_document_id=source_doc.id if source_doc else None,
        stage=(payload.stage or "senior").strip() or "senior",
        subject=(payload.subject or "物理").strip() or "物理",
        status="queued",
        progress=0.0,
        detail="任务已创建",
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if source_doc:
        db.refresh(source_doc)

    thread = threading.Thread(target=_run_ingest_job, args=(job.id,), daemon=True)
    thread.start()

    return schemas.IngestSubmitOut(
        job=schemas.IngestJobOut.model_validate(job),
        document=schemas.SourceDocumentOut.model_validate(source_doc) if source_doc else None,
    )


@router.get("/jobs", response_model=list[schemas.IngestJobOut])
def list_ingest_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.IngestJob)
    if current_user.role != models.UserRole.admin:
        query = query.filter(models.IngestJob.created_by == current_user.id)
    if status_filter:
        query = query.filter(models.IngestJob.status == status_filter.strip())
    rows = query.order_by(models.IngestJob.created_at.desc()).limit(limit).all()
    return [schemas.IngestJobOut.model_validate(item) for item in rows]


@router.get("/documents", response_model=list[schemas.SourceDocumentOut])
def list_source_documents(
    status_filter: str | None = Query(default=None, alias="status"),
    chapter_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.SourceDocument)
    if current_user.role != models.UserRole.admin:
        query = query.filter(models.SourceDocument.created_by == current_user.id)
    if status_filter:
        query = query.filter(models.SourceDocument.status == status_filter.strip())
    if chapter_id is not None:
        query = query.filter(models.SourceDocument.chapter_id == chapter_id)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.SourceDocument.title.ilike(keyword),
                models.SourceDocument.summary.ilike(keyword),
                models.SourceDocument.url.ilike(keyword),
            )
        )
    rows = query.order_by(models.SourceDocument.updated_at.desc()).limit(limit).all()
    return [schemas.SourceDocumentOut.model_validate(item) for item in rows]


@router.patch("/documents/{document_id}", response_model=schemas.SourceDocumentOut)
def set_source_document_status(
    document_id: int,
    payload: schemas.SourceDocumentStatusRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    row = db.query(models.SourceDocument).filter(models.SourceDocument.id == document_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row.status = payload.status
    row.published_at = datetime.now(timezone.utc) if payload.status == "published" else None
    db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.SourceDocumentOut.model_validate(row)
