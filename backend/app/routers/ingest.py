from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app import models, schemas
from app.core import ai_service, chapter_classifier, semantic_ranker
from app.core.config import settings
from app.core.db_read_write import WriteSessionLocal
from app.core.link_content import fetch_link_content, normalize_public_http_url
from app.deps import get_current_admin, get_current_user, get_db_read, get_db_write


router = APIRouter(tags=["ingest"])


def _url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _content_excerpt(content_text: str | None, size: int = 320) -> str | None:
    text = (content_text or "").strip()
    if not text:
        return None
    return text[:size]


def _source_document_out(row: models.SourceDocument) -> schemas.SourceDocumentOut:
    payload = schemas.SourceDocumentOut.model_validate(row)
    return payload.model_copy(update={"content_excerpt": _content_excerpt(row.content_text)})


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(item):.12g}" for item in values) + "]"


def _update_document_embedding_vector_column(
    db: Session,
    *,
    source_document_id: int,
    embedding: list[float] | None,
) -> None:
    if not settings.SEMANTIC_PGVECTOR_ENABLED or not embedding:
        return
    try:
        db.execute(
            text(
                """
                UPDATE source_documents
                SET content_embedding_vec = CAST(:vec AS vector)
                WHERE id = :id
                """
            ),
            {"id": source_document_id, "vec": _vector_literal(embedding)},
        )
    except Exception:  # noqa: BLE001
        pass


def _sync_document_embedding(db: Session, source_doc: models.SourceDocument) -> bool:
    content = (source_doc.content_text or "").strip()
    if not content or not ai_service.is_enabled():
        return False

    try:
        embedding = ai_service.generate_embedding(content)
    except ai_service.AIServiceError:
        return False

    source_doc.content_embedding_json = embedding
    source_doc.content_embedding_model = settings.AI_EMBEDDING_MODEL
    source_doc.content_indexed_at = datetime.now(timezone.utc)
    db.add(source_doc)
    _update_document_embedding_vector_column(
        db,
        source_document_id=source_doc.id,
        embedding=embedding,
    )
    return True


def _enqueue_document_embedding(source_document_id: int) -> None:
    def run() -> None:
        db = WriteSessionLocal()
        try:
            row = (
                db.query(models.SourceDocument)
                .filter(models.SourceDocument.id == source_document_id)
                .first()
            )
            if not row:
                return
            if _sync_document_embedding(db, row):
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()


def _populate_source_document_from_url(
    db: Session,
    *,
    source_doc: models.SourceDocument,
    url: str,
    stage: str,
    subject: str,
) -> chapter_classifier.ChapterClassification:
    parsed = fetch_link_content(url)
    title = (parsed.title or url).strip()[:255]
    description = (parsed.description or "").strip()[:1000]
    content_text = (parsed.content_text or "").strip()
    summary = description or (content_text[:220] if content_text else "")

    ai_tags: list[str] = []
    if ai_service.is_enabled() and content_text:
        try:
            ai_summary, ai_tags = ai_service.generate_summary_and_tags(
                content_text,
                title=title,
                subject=subject,
            )
            if ai_summary.strip():
                summary = ai_summary.strip()
        except Exception:  # noqa: BLE001
            pass

    classify = chapter_classifier.classify_chapter(
        db,
        stage=stage,
        subject=subject,
        title=title,
        description=description,
        tags=ai_tags,
        external_url=url,
        content_text=content_text,
        top_k=3,
    )
    chapter_id = classify.recommended_chapter_id or (
        classify.chapter.id if classify.chapter else None
    )

    hash_changed = source_doc.content_hash != parsed.content_hash
    source_doc.url = url
    source_doc.title = title
    source_doc.summary = summary or None
    source_doc.tags = ai_tags
    source_doc.stage = stage
    source_doc.subject = subject
    source_doc.chapter_id = chapter_id
    source_doc.confidence = classify.confidence
    source_doc.status = "ready"
    source_doc.content_text = content_text or None
    source_doc.content_chars = parsed.content_chars if content_text else 0
    source_doc.content_truncated = parsed.content_truncated if content_text else False
    source_doc.content_hash = parsed.content_hash
    source_doc.parse_error = parsed.parse_error
    if hash_changed:
        source_doc.content_embedding_json = None
        source_doc.content_embedding_model = None
        source_doc.content_indexed_at = None
    db.add(source_doc)
    return classify


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

        url = normalize_public_http_url(job.url or "")
        source_doc = (
            db.query(models.SourceDocument)
            .filter(models.SourceDocument.id == job.source_document_id)
            .first()
        )
        if not source_doc:
            source_doc = models.SourceDocument(
                source_type="url",
                url=url,
                title=url[:255],
                summary=None,
                tags=[],
                fingerprint=_url_fingerprint(url),
                stage=job.stage,
                subject=job.subject,
                status="queued",
                created_by=job.created_by,
            )
            db.add(source_doc)
            db.flush()
            job.source_document_id = source_doc.id
            db.add(job)
            db.commit()

        classify = _populate_source_document_from_url(
            db,
            source_doc=source_doc,
            url=url,
            stage=job.stage,
            subject=job.subject,
        )
        job.progress = 1.0
        job.status = "done"
        base_detail = (
            f"分类结果：{classify.chapter.volume_name if classify.chapter else '未命中'} "
            f"{classify.chapter.chapter_code if classify.chapter else ''} "
            f"{classify.chapter.title if classify.chapter else ''}"
        ).strip()
        parse_note = source_doc.parse_error or "html parsed"
        job.detail = f"{base_detail} | parse: {parse_note}"[:2000]
        db.add(job)
        db.add(source_doc)
        db.commit()
        db.refresh(source_doc)

        if source_doc.content_text:
            _enqueue_document_embedding(source_doc.id)
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


def _run_backfill_job(job_id: int, *, limit: int, reparse: bool, reembed: bool) -> None:
    db = WriteSessionLocal()
    try:
        job = db.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
        if not job:
            return
        job.status = "processing"
        job.progress = 0.05
        db.add(job)
        db.commit()

        query = (
            db.query(models.SourceDocument)
            .filter(
                models.SourceDocument.source_type == "url",
                models.SourceDocument.url.is_not(None),
                models.SourceDocument.stage == job.stage,
                models.SourceDocument.subject == job.subject,
            )
            .order_by(models.SourceDocument.updated_at.desc())
        )
        if not reparse and not reembed:
            query = query.filter(
                or_(
                    and_(
                        models.SourceDocument.content_text.is_(None),
                        models.SourceDocument.parse_error.is_(None),
                    ),
                    and_(
                        models.SourceDocument.content_text.is_not(None),
                        models.SourceDocument.content_embedding_json.is_(None),
                    ),
                )
            )
        rows = query.limit(limit).all()
        total = len(rows)
        if total == 0:
            job.status = "done"
            job.progress = 1.0
            job.detail = "无需补算"
            db.add(job)
            db.commit()
            return

        parsed_count = 0
        embedded_count = 0
        failed_count = 0
        for idx, row in enumerate(rows, start=1):
            try:
                should_parse = reparse or not (row.content_text or "").strip()
                if should_parse and row.url:
                    _populate_source_document_from_url(
                        db,
                        source_doc=row,
                        url=normalize_public_http_url(row.url),
                        stage=row.stage,
                        subject=row.subject,
                    )
                    parsed_count += 1

                should_embed = reembed or row.content_embedding_json is None
                if should_embed and _sync_document_embedding(db, row):
                    embedded_count += 1
                db.add(row)
                db.commit()
            except Exception as row_error:  # noqa: BLE001
                db.rollback()
                failed_count += 1
                row.parse_error = str(row_error)[:1000]
                db.add(row)
                db.commit()

            job.progress = min(0.98, 0.1 + (idx / total) * 0.88)
            db.add(job)
            db.commit()

        job.status = "done"
        job.progress = 1.0
        job.detail = (
            f"backfill completed: parsed={parsed_count}, embedded={embedded_count}, failed={failed_count}"
        )[:2000]
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
    normalized_url = normalize_public_http_url(payload.url)
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
            content_text=None,
            content_chars=0,
            content_truncated=False,
            content_hash=None,
            parse_error=None,
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
        document=_source_document_out(source_doc) if source_doc else None,
    )


@router.post(
    "/documents/backfill",
    response_model=schemas.IngestBackfillOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_source_documents(
    payload: schemas.IngestBackfillRequest,
    db: Session = Depends(get_db_write),
    _: models.User = Depends(get_current_admin),
):
    stage = (payload.stage or "senior").strip() or "senior"
    subject = (payload.subject or "物理").strip() or "物理"
    job = models.IngestJob(
        source_type="backfill",
        url=None,
        source_document_id=None,
        stage=stage,
        subject=subject,
        status="queued",
        progress=0.0,
        detail="补算任务已创建",
        created_by=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(
        target=_run_backfill_job,
        kwargs={
            "job_id": job.id,
            "limit": payload.limit,
            "reparse": payload.reparse,
            "reembed": payload.reembed,
        },
        daemon=True,
    )
    thread.start()
    return schemas.IngestBackfillOut(job=schemas.IngestJobOut.model_validate(job))


@router.post("/documents/semantic-search", response_model=schemas.IngestSemanticSearchResponse)
def semantic_search_source_documents(
    payload: schemas.IngestSemanticSearchRequest,
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    query = (
        db.query(models.SourceDocument)
        .filter(
            models.SourceDocument.stage == payload.stage,
            models.SourceDocument.subject == payload.subject,
            models.SourceDocument.status.in_(["ready", "published", "pending_review"]),
        )
        .order_by(models.SourceDocument.updated_at.desc())
    )
    if current_user.role != models.UserRole.admin:
        query = query.filter(models.SourceDocument.created_by == current_user.id)

    rows = query.limit(payload.candidate_limit).all()
    if not rows:
        return schemas.IngestSemanticSearchResponse(
            query=payload.query,
            threshold=0.02,
            returned_count=0,
            results=[],
        )

    query_embedding: list[float] | None = None
    if ai_service.is_enabled():
        try:
            query_embedding = ai_service.generate_embedding(payload.query)
        except ai_service.AIServiceError:
            query_embedding = None

    candidates: list[semantic_ranker.SemanticCandidate] = []
    doc_map: dict[str, models.SourceDocument] = {}
    for row in rows:
        candidate_id = f"source_doc:{row.id}"
        doc_map[candidate_id] = row
        candidates.append(
            semantic_ranker.SemanticCandidate(
                candidate_id=candidate_id,
                title=row.title or "",
                description=(row.content_text or "")[:4000],
                summary=row.summary or "",
                tags=row.tags or [],
                embedding=row.content_embedding_json
                if isinstance(row.content_embedding_json, list)
                else None,
            )
        )

    ranked = semantic_ranker.rank_candidates(
        payload.query,
        candidates,
        query_embedding=query_embedding,
        top_k=payload.top_k,
    )
    results: list[schemas.IngestSemanticSearchItemOut] = []
    for item in ranked.items:
        row = doc_map.get(item.candidate.candidate_id)
        if not row:
            continue
        results.append(
            schemas.IngestSemanticSearchItemOut(
                score=round(item.probability, 6),
                probability=round(item.probability, 6),
                factors=schemas.IngestSemanticFactorsOut(
                    vector=round(item.vector, 6),
                    summary=round(item.summary, 6),
                    content=round(item.content, 6),
                    tags=round(item.tags, 6),
                    raw=round(item.raw, 6),
                ),
                document=_source_document_out(row),
            )
        )

    return schemas.IngestSemanticSearchResponse(
        query=payload.query,
        threshold=round(ranked.threshold, 6),
        returned_count=len(results),
        results=results,
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
    chapter_mode: str = Query(default="normal", pattern="^(normal|general)$"),
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
    if chapter_mode == "general":
        query = query.filter(models.SourceDocument.chapter_id.is_(None))
    elif chapter_id is not None:
        query = query.filter(models.SourceDocument.chapter_id == chapter_id)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.SourceDocument.title.ilike(keyword),
                models.SourceDocument.summary.ilike(keyword),
                models.SourceDocument.content_text.ilike(keyword),
                models.SourceDocument.url.ilike(keyword),
            )
        )
    rows = query.order_by(models.SourceDocument.updated_at.desc()).limit(limit).all()
    return [_source_document_out(item) for item in rows]


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
    return _source_document_out(row)
