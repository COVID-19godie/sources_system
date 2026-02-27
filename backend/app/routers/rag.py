from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import math
from pathlib import Path
import re
import threading
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.core import ai_service, rag_cache, rag_sync, resource_variants, semantic_ranker
from app.core.config import settings
from app.core.db_read_write import WriteSessionLocal
from app.core.file_access_tokens import build_storage_access_urls
from app.core import storage as storage_service
from app.deps import get_current_user, get_db_read, get_db_write
from app.routers.resources import to_resource_out
from app.services.rag import bootstrap_service, extract_service


router = APIRouter(tags=["rag"])
logger = logging.getLogger(__name__)


ENTITY_TYPES = {
    "chapter",
    "knowledge_point",
    "formula",
    "experiment",
    "problem_type",
    "resource",
}

KEYWORD_STOP_WORDS = {
    "课件",
    "教程",
    "文档",
    "视频",
    "资料",
    "最终版",
    "定稿",
    "副本",
    "高中",
    "物理",
    "final",
    "new",
    "v1",
    "v2",
}

RAG_GRAPH_SCOPE_PUBLIC = "public"
RAG_GRAPH_SCOPE_MIXED = "mixed"

FORMAT_GROUP_LABELS = {
    "ppt": "课件",
    "exercise": "题目",
    "simulation": "仿真",
    "video": "视频",
    "document": "文档",
    "image": "图片",
    "audio": "音频",
    "other": "其他",
}


def _extract_filename_from_key(object_key: str | None) -> str:
    if not object_key:
        return ""
    return Path(object_key).name


def _split_keyword_tokens(raw: str) -> list[str]:
    if not raw:
        return []
    raw = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", raw.strip())
    return [token.strip() for token in re.split(r"[_\-\.\s\(\)（）\[\]【】]+", raw) if token.strip()]


def _is_valid_keyword_token(token: str) -> bool:
    if not token:
        return False
    lower = token.lower()
    if lower in KEYWORD_STOP_WORDS or token in KEYWORD_STOP_WORDS:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]+", token):
        return 1 <= len(token) <= 4
    if re.fullmatch(r"[A-Za-z0-9]+", token):
        return 2 <= len(token) <= 10
    return False


def build_resource_keyword_label(
    source: models.RagSource | None,
    resource: models.Resource | None,
) -> str:
    candidates = [
        _extract_filename_from_key(source.object_key if source else None),
        source.title if source else "",
        resource.title if resource else "",
    ]
    seen: set[str] = set()
    words: list[str] = []

    for candidate in candidates:
        for token in _split_keyword_tokens(candidate or ""):
            normalized = token.lower()
            if normalized in seen:
                continue
            if not _is_valid_keyword_token(token):
                continue
            seen.add(normalized)
            words.append(token)
            if len(words) >= 2:
                return "·".join(words)

    fallback = (source.title if source else "") or (resource.title if resource else "") or "资源"
    fallback = re.sub(r"\s+", "", fallback)
    return fallback[:6] if fallback else "资源"


def _can_manage_workspace(user: models.User) -> bool:
    return user.role in {models.UserRole.admin, models.UserRole.teacher}


def _resource_chapter_ids(resource: models.Resource) -> list[int]:
    ids: set[int] = set()
    if resource.chapter_id:
        ids.add(resource.chapter_id)
    for link in resource.chapter_links:
        if link.chapter_id:
            ids.add(link.chapter_id)
    return sorted(ids)


def _detect_file_format(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".mp4", ".webm", ".mov", ".m4v", ".avi"}:
        return "video"
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp3", ".wav", ".m4a", ".ogg", ".aac"}:
        return "audio"
    if suffix in {".doc", ".docx"}:
        return "word"
    if suffix in {".xls", ".xlsx", ".csv"}:
        return "excel"
    if suffix in {".ppt", ".pptx"}:
        return "ppt"
    return "other"


def _normalize_graph_scope(scope: str | None) -> str:
    return RAG_GRAPH_SCOPE_MIXED if (scope or "").strip().lower() == RAG_GRAPH_SCOPE_MIXED else RAG_GRAPH_SCOPE_PUBLIC


def _resource_is_public(resource: models.Resource | None) -> bool:
    return bool(
        resource
        and resource.status == models.ResourceStatus.approved
        and not resource.is_trashed
    )


def _resolve_source_variant_kind(source: models.RagSource) -> str:
    return resource_variants.normalize_variant_kind(
        source.variant_kind or resource_variants.guess_variant_kind_from_object_key(source.object_key, source.file_format),
        fallback=resource_variants.VARIANT_KIND_UPLOAD,
    )


def _resolve_source_canonical_key(source: models.RagSource) -> str:
    variant_kind = _resolve_source_variant_kind(source)
    if source.resource_id or source.object_key:
        return resource_variants.build_canonical_key(
            resource_id=source.resource_id,
            object_key=source.object_key,
            variant_kind=variant_kind,
        )
    if source.canonical_key:
        return source.canonical_key
    return resource_variants.build_canonical_key(
        object_key=f"source:{source.id}",
    )


def _source_is_graph_visible(source: models.RagSource) -> bool:
    if source.is_graph_visible is False:
        return False
    return _resolve_source_variant_kind(source) != resource_variants.VARIANT_KIND_PREVIEW_PDF


def _source_display_priority(source: models.RagSource) -> int:
    if source.display_priority is not None:
        return int(source.display_priority)
    return resource_variants.variant_priority(_resolve_source_variant_kind(source))


def _canonical_node_id(source: models.RagSource) -> str:
    return resource_variants.canonical_node_id(_resolve_source_canonical_key(source))


def _resolve_format_group(
    resource: models.Resource | None,
    source: models.RagSource,
) -> tuple[str, str]:
    file_format = (resource.file_format if resource else source.file_format) or "other"
    resource_kind = (resource.resource_kind if resource else "") or ""

    if file_format == "ppt":
        return "ppt", FORMAT_GROUP_LABELS["ppt"]
    if resource_kind in {"exercise", "exam"}:
        return "exercise", FORMAT_GROUP_LABELS["exercise"]
    if resource_kind in {"simulation"}:
        return "simulation", FORMAT_GROUP_LABELS["simulation"]
    if file_format == "video":
        return "video", FORMAT_GROUP_LABELS["video"]
    if file_format == "image":
        return "image", FORMAT_GROUP_LABELS["image"]
    if file_format == "audio":
        return "audio", FORMAT_GROUP_LABELS["audio"]
    if file_format in {"markdown", "html", "pdf", "word", "excel"}:
        return "document", FORMAT_GROUP_LABELS["document"]
    return "other", FORMAT_GROUP_LABELS["other"]


def _to_workspace_out(row: models.RagWorkspace) -> schemas.RagWorkspaceOut:
    return schemas.RagWorkspaceOut.model_validate(row)


def _to_source_out(row: models.RagSource) -> schemas.RagSourceOut:
    return schemas.RagSourceOut.model_validate(row)


def _ensure_workspace(db: Session, workspace_id: int) -> models.RagWorkspace:
    workspace = db.query(models.RagWorkspace).filter(models.RagWorkspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _split_chunks(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    content = (text or "").strip()
    if not content:
        return []

    chunks: list[str] = []
    idx = 0
    while idx < len(content):
        end = min(len(content), idx + size)
        part = content[idx:end].strip()
        if part:
            chunks.append(part)
        if end >= len(content):
            break
        idx = max(end - overlap, idx + 1)
    return chunks


def _safe_embedding(text: str) -> list[float] | None:
    if not ai_service.is_enabled():
        return None
    try:
        return ai_service.generate_embedding(text)
    except Exception:  # noqa: BLE001
        return None


def _safe_answer(question: str, contexts: list[dict]) -> str:
    if ai_service.is_enabled():
        try:
            answer = ai_service.generate_rag_answer(question, contexts)
            if answer.strip():
                return answer.strip()
        except Exception:  # noqa: BLE001
            pass

    lines = ["基于当前工作台证据，给出快速回答："]
    for idx, row in enumerate(contexts[:4], start=1):
        lines.append(f"{idx}. {row.get('title')}: {row.get('summary') or row.get('snippet') or ''}")
    return "\n".join(lines)[:2000]


def _hash_to_axis(node_id: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{node_id}".encode("utf-8")).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return value * 2.0 - 1.0


def _parse_created_at_ts(meta: dict | None) -> int:
    if not meta:
        return 0
    raw = meta.get("created_at") or meta.get("created_at_ts")
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return 0
    return 0


def _to_graph_embedding_out(workspace_id: int, graph: schemas.RagGraphOut) -> schemas.RagGraphEmbeddingOut:
    edge_weights: dict[str, list[float]] = {}
    for edge in graph.edges:
        weight = float(edge.weight or 0.0)
        edge_weights.setdefault(edge.source, []).append(weight)
        edge_weights.setdefault(edge.target, []).append(weight)

    nodes: list[schemas.RagGraphEmbeddingNodeOut] = []
    for node in graph.nodes:
        meta = node.meta or {}
        prerequisite = float(meta.get("prerequisite_level") or 0.0)
        relation_strength = (
            sum(edge_weights.get(node.id, [])) / max(1, len(edge_weights.get(node.id, [])))
            if edge_weights.get(node.id)
            else float(node.score or 0.0)
        )
        heat = float(meta.get("heat") or meta.get("hotness") or node.score or 0.0)
        base = {
            "chapter": 2.2,
            "section": 1.6,
            "format": 1.1,
            "resource": 0.7,
        }.get(node.node_type, 0.5)

        x = _hash_to_axis(node.id, "x") * (1.2 + base)
        y = _hash_to_axis(node.id, "y") * (0.9 + relation_strength)
        z = _hash_to_axis(node.id, "z") * (0.8 + prerequisite)
        if node.chapter_id:
            x += (node.chapter_id % 11) * 0.2
        if node.section_id:
            y += (node.section_id % 7) * 0.1
        z += math.tanh(heat) * 0.7

        nodes.append(
            schemas.RagGraphEmbeddingNodeOut(
                id=node.id,
                label=node.keyword_label or node.label,
                node_type=node.node_type,
                x=round(x, 6),
                y=round(y, 6),
                z=round(z, 6),
                prerequisite_level=round(prerequisite, 6),
                relation_strength=round(relation_strength, 6),
                heat=round(heat, 6),
                created_at_ts=_parse_created_at_ts(meta),
                meta=meta,
            )
        )
    return schemas.RagGraphEmbeddingOut(
        workspace_id=workspace_id,
        generated_at=datetime.now(timezone.utc),
        nodes=nodes,
        edges=graph.edges,
    )


def _upsert_entity(
    db: Session,
    workspace_id: int,
    entity_type: str,
    canonical_name: str,
    *,
    description: str | None = None,
    confidence: float = 0.8,
) -> tuple[models.RagEntity, bool]:
    normalized_name = canonical_name.strip()
    if not normalized_name:
        raise ValueError("entity name is required")
    if entity_type not in ENTITY_TYPES:
        entity_type = "knowledge_point"

    row = (
        db.query(models.RagEntity)
        .filter(
            models.RagEntity.workspace_id == workspace_id,
            models.RagEntity.entity_type == entity_type,
            models.RagEntity.canonical_name == normalized_name,
        )
        .first()
    )
    if row:
        if description and not row.description:
            row.description = description
            db.add(row)
        return row, False

    row = models.RagEntity(
        workspace_id=workspace_id,
        entity_type=entity_type,
        canonical_name=normalized_name,
        aliases=[],
        description=description,
        confidence=max(0.0, min(1.0, confidence)),
    )
    db.add(row)
    db.flush()
    return row, True


def _upsert_relation(
    db: Session,
    workspace_id: int,
    source_entity_id: int,
    target_entity_id: int,
    relation_type: str,
    *,
    source_id: int | None,
    confidence: float,
) -> tuple[models.RagRelation | None, bool]:
    if confidence < 0.58:
        return None, False

    existing = (
        db.query(models.RagRelation)
        .filter(
            models.RagRelation.workspace_id == workspace_id,
            models.RagRelation.source_entity_id == source_entity_id,
            models.RagRelation.target_entity_id == target_entity_id,
            models.RagRelation.relation_type == relation_type,
            models.RagRelation.source_id == source_id,
        )
        .first()
    )
    if existing:
        return existing, False

    row = models.RagRelation(
        workspace_id=workspace_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type=relation_type,
        confidence=max(0.0, min(1.0, confidence)),
        source_id=source_id,
    )
    db.add(row)
    db.flush()
    return row, True


def _create_evidence(
    db: Session,
    workspace_id: int,
    source_id: int,
    chunk_id: int | None,
    content: str,
    *,
    score: float,
    meta: dict,
) -> models.RagEvidence:
    row = models.RagEvidence(
        workspace_id=workspace_id,
        source_id=source_id,
        chunk_id=chunk_id,
        content=content[:2000],
        score=max(0.0, min(1.0, score)),
        meta=meta,
    )
    db.add(row)
    db.flush()
    return row


def _serialize_bootstrap_job(job: models.RagExtractionJob) -> schemas.RagBootstrapJobOut:
    stats = job.stats if isinstance(job.stats, dict) else {}
    failed_sources = [
        schemas.RagBootstrapErrorOut(**item)
        for item in bootstrap_service.normalize_failed_sources(stats.get("failed_sources"))
    ]
    return schemas.RagBootstrapJobOut(
        job_id=job.id,
        workspace_id=job.workspace_id,
        status=job.status,
        mode=job.mode,
        processed_sources=int(stats.get("processed_sources") or 0),
        succeeded_sources=int(stats.get("succeeded_sources") or 0),
        failed_sources_count=int(stats.get("failed_sources_count") or len(failed_sources)),
        failed_sources=failed_sources,
        entities_created=int(stats.get("entities_created") or 0),
        relations_created=int(stats.get("relations_created") or 0),
        evidences_created=int(stats.get("evidences_created") or 0),
        created_at=job.created_at,
        updated_at=job.updated_at,
        error_message=job.error_message,
    )


def _cleanup_extract_artifacts_for_source(db: Session, *, source_id: int) -> None:
    extract_service.cleanup_source_extract_artifacts(db, source_id=source_id)


def _extract_for_source(
    db: Session,
    workspace: models.RagWorkspace,
    source: models.RagSource,
    *,
    mode: str,
) -> dict[str, int]:
    resource = None
    if source.resource_id:
        resource = db.query(models.Resource).filter(models.Resource.id == source.resource_id).first()

    source_text_parts = [source.title]
    if source.summary_text:
        source_text_parts.append(source.summary_text)

    if mode == "full" and source.object_key:
        try:
            source_text_parts.append(storage_service.get_object_text(source.object_key, max_bytes=400_000))
        except Exception:  # noqa: BLE001
            pass

    if resource:
        source_text_parts.extend(
            [
                resource.description or "",
                resource.ai_summary or "",
                "、".join((resource.ai_tags or []) + (resource.tags or [])),
            ]
        )

    raw_text = "\n\n".join(part for part in source_text_parts if part and part.strip())
    if not raw_text.strip():
        raw_text = source.title

    # Rebuild extract artifacts in a FK-safe order.
    _cleanup_extract_artifacts_for_source(db, source_id=source.id)
    chunks = _split_chunks(raw_text, size=1200 if mode == "full" else 700, overlap=140)
    chunk_rows: list[models.RagChunk] = []
    for idx, chunk in enumerate(chunks):
        chunk_rows.append(
            models.RagChunk(
                workspace_id=workspace.id,
                source_id=source.id,
                chunk_index=idx,
                content=chunk,
                embedding_json=_safe_embedding(chunk[:2500]),
            )
        )
    if chunk_rows:
        db.add_all(chunk_rows)
        db.flush()

    if not source.embedding_json:
        source.embedding_json = _safe_embedding((source.summary_text or raw_text)[:5000])
    source.status = "indexed"
    db.add(source)

    created_entities = 0
    created_relations = 0
    created_evidences = 0

    resource_entity, created = _upsert_entity(
        db,
        workspace.id,
        "resource",
        source.title,
        description=source.summary_text,
        confidence=0.88,
    )
    created_entities += int(created)

    chapter_entity = None
    section_entity = None
    if resource and resource.chapter_id:
        chapter = db.query(models.Chapter).filter(models.Chapter.id == resource.chapter_id).first()
        if chapter:
            chapter_entity, created = _upsert_entity(
                db,
                workspace.id,
                "chapter",
                f"{chapter.chapter_code} {chapter.title}",
                description=chapter.grade,
                confidence=0.95,
            )
            created_entities += int(created)

    if resource and resource.section_id:
        section = db.query(models.ResourceSection).filter(models.ResourceSection.id == resource.section_id).first()
        if section:
            section_entity, created = _upsert_entity(
                db,
                workspace.id,
                "knowledge_point",
                section.name,
                description=section.code,
                confidence=0.82,
            )
            created_entities += int(created)

    kp_names = list(dict.fromkeys((source.tags or []) + ((resource.ai_tags if resource else []) or [])))
    for name in kp_names[:12]:
        kp_entity, created = _upsert_entity(
            db,
            workspace.id,
            "knowledge_point",
            name,
            description="标签提取",
            confidence=0.75,
        )
        created_entities += int(created)
        rel, rel_created = _upsert_relation(
            db,
            workspace.id,
            kp_entity.id,
            resource_entity.id,
            "related_to",
            source_id=source.id,
            confidence=0.76,
        )
        created_relations += int(rel_created)
        if rel:
            evidence = _create_evidence(
                db,
                workspace.id,
                source.id,
                chunk_rows[0].id if chunk_rows else None,
                (source.summary_text or raw_text)[:260],
                score=0.74,
                meta={"kind": "tag", "value": name},
            )
            created_evidences += 1
            db.add(models.RagRelationEvidence(relation_id=rel.id, evidence_id=evidence.id))

    if chapter_entity:
        rel, rel_created = _upsert_relation(
            db,
            workspace.id,
            chapter_entity.id,
            resource_entity.id,
            "contains",
            source_id=source.id,
            confidence=0.94,
        )
        created_relations += int(rel_created)
        if rel:
            evidence = _create_evidence(
                db,
                workspace.id,
                source.id,
                chunk_rows[0].id if chunk_rows else None,
                source.title,
                score=0.82,
                meta={"kind": "chapter"},
            )
            created_evidences += 1
            db.add(models.RagRelationEvidence(relation_id=rel.id, evidence_id=evidence.id))

    if section_entity:
        rel, rel_created = _upsert_relation(
            db,
            workspace.id,
            section_entity.id,
            resource_entity.id,
            "contains",
            source_id=source.id,
            confidence=0.86,
        )
        created_relations += int(rel_created)
        if rel:
            evidence = _create_evidence(
                db,
                workspace.id,
                source.id,
                chunk_rows[0].id if chunk_rows else None,
                (source.summary_text or source.title)[:220],
                score=0.78,
                meta={"kind": "section"},
            )
            created_evidences += 1
            db.add(models.RagRelationEvidence(relation_id=rel.id, evidence_id=evidence.id))

    formula_matches = re.findall(r"([A-Za-z][A-Za-z0-9_]{0,16}\s*=\s*[^\n]{1,40})", raw_text)
    for formula in list(dict.fromkeys(formula_matches))[:6]:
        formula_entity, created = _upsert_entity(
            db,
            workspace.id,
            "formula",
            formula,
            confidence=0.68,
        )
        created_entities += int(created)
        rel, rel_created = _upsert_relation(
            db,
            workspace.id,
            formula_entity.id,
            resource_entity.id,
            "appears_in",
            source_id=source.id,
            confidence=0.65,
        )
        created_relations += int(rel_created)
        if rel:
            evidence = _create_evidence(
                db,
                workspace.id,
                source.id,
                chunk_rows[0].id if chunk_rows else None,
                formula,
                score=0.66,
                meta={"kind": "formula"},
            )
            created_evidences += 1
            db.add(models.RagRelationEvidence(relation_id=rel.id, evidence_id=evidence.id))

    return {
        "entities": created_entities,
        "relations": created_relations,
        "evidences": created_evidences,
        "chunks": len(chunk_rows),
    }


def _build_workspace_graph(
    db: Session,
    workspace: models.RagWorkspace,
    *,
    q: str | None,
    limit: int,
    scope: str = RAG_GRAPH_SCOPE_PUBLIC,
    include_format_nodes: bool = True,
    dedupe: bool = True,
    include_variants: bool = True,
    access_user_id: int | None = None,
) -> schemas.RagGraphOut:
    normalized_scope = _normalize_graph_scope(scope)
    source_query = db.query(models.RagSource).filter(
        models.RagSource.workspace_id == workspace.id,
        models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
    )
    if q:
        like = f"%{q.strip()}%"
        source_query = source_query.filter(
            or_(models.RagSource.title.ilike(like), models.RagSource.summary_text.ilike(like))
        )
    source_rows = source_query.order_by(models.RagSource.updated_at.desc()).limit(limit).all()

    resource_ids = [row.resource_id for row in source_rows if row.resource_id]
    resource_map: dict[int, models.Resource] = {}
    if resource_ids:
        resources = (
            db.query(models.Resource)
            .filter(
                models.Resource.id.in_(resource_ids),
                models.Resource.is_trashed.is_(False),
                models.Resource.status == models.ResourceStatus.approved,
            )
            .all()
        )
        resource_map = {row.id: row for row in resources}

    chapter_map: dict[int, models.Chapter] = {}
    chapter_ids = [res.chapter_id for res in resource_map.values() if res.chapter_id]
    if chapter_ids:
        chapter_rows = db.query(models.Chapter).filter(models.Chapter.id.in_(chapter_ids)).all()
        chapter_map = {row.id: row for row in chapter_rows}

    section_map: dict[int, models.ResourceSection] = {}
    section_ids = [res.section_id for res in resource_map.values() if res.section_id]
    if section_ids:
        section_rows = db.query(models.ResourceSection).filter(models.ResourceSection.id.in_(section_ids)).all()
        section_map = {row.id: row for row in section_rows}

    nodes: list[schemas.RagGraphNodeOut] = []
    edges: list[schemas.RagGraphEdgeOut] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    included_source_ids: set[int] = set()
    public_source_count = 0
    private_source_count = 0

    def add_node(node: schemas.RagGraphNodeOut) -> None:
        if node.id in seen_nodes:
            return
        seen_nodes.add(node.id)
        nodes.append(node)

    def add_edge(source: str, target: str, edge_type: str, weight: float = 1.0) -> None:
        key = (source, target, edge_type)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            schemas.RagGraphEdgeOut(
                source=source,
                target=target,
                edge_type=edge_type,
                weight=round(weight, 4),
            )
        )

    add_node(
        schemas.RagGraphNodeOut(
            id="chapter:unknown",
            label="未归档章节",
            keyword_label="未归档",
            node_type="chapter",
            meta={"virtual": True},
        )
    )

    active_rows: list[models.RagSource] = []
    for source in source_rows:
        resource = resource_map.get(source.resource_id or -1)
        is_public_resource_source = bool(
            source.source_type == "resource"
            and source.resource_id
            and _resource_is_public(resource)
        )
        if source.source_type == "resource" and source.resource_id and not is_public_resource_source:
            continue
        if normalized_scope == RAG_GRAPH_SCOPE_PUBLIC and not is_public_resource_source:
            continue
        if not _source_is_graph_visible(source):
            continue
        active_rows.append(source)

    if dedupe and settings.RAG_CANONICAL_DEDUPE:
        grouped_sources: dict[str, list[models.RagSource]] = {}
        for source in active_rows:
            grouped_sources.setdefault(_resolve_source_canonical_key(source), []).append(source)
    else:
        grouped_sources = {
            f"source:{source.id}": [source]
            for source in active_rows
        }

    for canonical_key, group_sources in grouped_sources.items():
        sorted_sources = sorted(
            group_sources,
            key=lambda item: (
                _source_display_priority(item),
                item.updated_at or datetime.min.replace(tzinfo=timezone.utc),
                item.id,
            ),
            reverse=True,
        )
        primary_source = sorted_sources[0]
        primary_resource = resource_map.get(primary_source.resource_id or -1)

        group_has_public_resource = any(
            source.source_type == "resource"
            and source.resource_id
            and _resource_is_public(resource_map.get(source.resource_id or -1))
            for source in sorted_sources
        )
        visibility = "public" if group_has_public_resource else "private"
        if visibility == "public":
            public_source_count += 1
        else:
            private_source_count += 1

        for source in sorted_sources:
            included_source_ids.add(source.id)

        source_node_id = _canonical_node_id(primary_source)

        chapter_node_id = "chapter:unknown"
        if primary_resource and primary_resource.chapter_id and primary_resource.chapter_id in chapter_map:
            chapter = chapter_map[primary_resource.chapter_id]
            chapter_node_id = f"chapter:{chapter.id}"
            add_node(
                schemas.RagGraphNodeOut(
                    id=chapter_node_id,
                    label=f"{chapter.chapter_code} {chapter.title}",
                    keyword_label=chapter.title[:8],
                    node_type="chapter",
                    chapter_id=chapter.id,
                    meta={"grade": chapter.grade},
                )
            )

        section = section_map.get(primary_resource.section_id) if primary_resource and primary_resource.section_id else None
        if primary_resource:
            section_key = f"{primary_resource.chapter_id if primary_resource.chapter_id else 'unknown'}:{section.id if section else 'unassigned'}"
            section_label = section.name if section else "未分区"
        else:
            section_key = "private:workspace"
            section_label = "工作台直传"
        section_node_id = f"section:{section_key}"
        add_node(
            schemas.RagGraphNodeOut(
                id=section_node_id,
                label=section_label,
                keyword_label=section_label[:8],
                node_type="section",
                chapter_id=primary_resource.chapter_id if primary_resource else None,
                section_id=section.id if section else None,
                group_key=section_key,
                meta={
                    "code": section.code if section else None,
                    "visibility": visibility,
                },
            )
        )
        add_edge(chapter_node_id, section_node_id, "contains")

        format_key, format_label = _resolve_format_group(primary_resource, primary_source)
        parent_node_id = section_node_id
        if include_format_nodes:
            format_node_id = f"format:{section_key}:{format_key}"
            add_node(
                schemas.RagGraphNodeOut(
                    id=format_node_id,
                    label=format_label,
                    keyword_label=format_label[:8],
                    node_type="format",
                    chapter_id=primary_resource.chapter_id if primary_resource else None,
                    section_id=section.id if section else None,
                    group_key=f"{section_key}:{format_key}",
                    meta={
                        "format_group": format_key,
                        "file_format": (primary_resource.file_format if primary_resource else primary_source.file_format) or "other",
                        "visibility": visibility,
                    },
                )
            )
            add_edge(section_node_id, format_node_id, "contains")
            parent_node_id = format_node_id

        keyword_label = build_resource_keyword_label(primary_source, primary_resource)
        variants_payload: list[dict] = []
        for index, variant_source in enumerate(sorted_sources):
            variant_resource = resource_map.get(variant_source.resource_id or -1)
            open_url = None
            download_url = None
            if variant_source.object_key:
                open_url, download_url = build_storage_access_urls(
                    object_key=variant_source.object_key,
                    user_id=access_user_id,
                )
            variant_visibility = "public" if (
                variant_source.source_type == "resource"
                and variant_source.resource_id
                and _resource_is_public(variant_resource)
            ) else "private"
            variants_payload.append(
                {
                    "source_id": variant_source.id,
                    "resource_id": variant_source.resource_id,
                    "title": variant_source.title,
                    "object_key": variant_source.object_key,
                    "variant_kind": _resolve_source_variant_kind(variant_source),
                    "file_format": (variant_resource.file_format if variant_resource else variant_source.file_format) or "other",
                    "is_graph_visible": _source_is_graph_visible(variant_source),
                    "open_url": open_url,
                    "download_url": download_url,
                    "visibility": variant_visibility,
                    "display_priority": _source_display_priority(variant_source),
                    "is_primary": index == 0,
                }
            )
        variant_kinds = [item["variant_kind"] for item in variants_payload]
        auto_open_kind = resource_variants.auto_open_variant_kind(
            variant_kinds,
            primary_file_format=(primary_resource.file_format if primary_resource else primary_source.file_format),
        )

        add_node(
            schemas.RagGraphNodeOut(
                id=source_node_id,
                label=primary_source.title[:48],
                keyword_label=keyword_label,
                node_type="resource",
                source_id=primary_source.id,
                resource_id=primary_source.resource_id,
                is_resource_linkable=bool(primary_source.resource_id),
                chapter_id=primary_resource.chapter_id if primary_resource else None,
                section_id=primary_resource.section_id if primary_resource else None,
                canonical_key=canonical_key,
                primary_variant_kind=_resolve_source_variant_kind(primary_source),
                variants_count=len(variants_payload),
                meta={
                    "source_ids": [item.id for item in sorted_sources],
                    "file_format": (primary_resource.file_format if primary_resource else primary_source.file_format) or "other",
                    "resource_type": primary_resource.type if primary_resource else primary_source.source_type,
                    "difficulty": primary_resource.difficulty if primary_resource else None,
                    "visibility": visibility,
                    "format_group": format_key,
                    "summary": primary_source.summary_text or "",
                    "tags": primary_source.tags or [],
                    "has_embedding": bool(
                        (primary_resource and isinstance(primary_resource.embedding_json, list) and primary_resource.embedding_json)
                        or (isinstance(primary_source.embedding_json, list) and primary_source.embedding_json)
                    ),
                    "keyword_title": keyword_label,
                    "variants": variants_payload if include_variants and settings.RAG_GRAPH_VARIANTS else [],
                    "auto_open_variant": auto_open_kind,
                },
            )
        )
        add_edge(parent_node_id, source_node_id, "contains")

    relation_rows: list[models.RagRelation] = []
    if included_source_ids:
        relation_rows = (
            db.query(models.RagRelation)
            .filter(
                models.RagRelation.workspace_id == workspace.id,
                models.RagRelation.source_id.in_(list(included_source_ids)),
            )
            .order_by(models.RagRelation.id.desc())
            .limit(max(160, limit * 3))
            .all()
        )

    entity_ids: set[int] = set()
    for relation in relation_rows:
        entity_ids.add(relation.source_entity_id)
        entity_ids.add(relation.target_entity_id)

    entity_rows: list[models.RagEntity] = []
    if entity_ids:
        entity_rows = (
            db.query(models.RagEntity)
            .filter(
                models.RagEntity.workspace_id == workspace.id,
                models.RagEntity.id.in_(list(entity_ids)),
            )
            .order_by(models.RagEntity.updated_at.desc())
            .limit(max(100, limit * 2))
            .all()
        )
    for entity in entity_rows:
        add_node(
            schemas.RagGraphNodeOut(
                id=f"entity:{entity.id}",
                label=entity.canonical_name[:48],
                keyword_label=entity.canonical_name[:8],
                node_type=entity.entity_type,
                meta={
                    "entity_id": entity.id,
                    "confidence": entity.confidence,
                    "description": entity.description,
                },
            )
        )

    for relation in relation_rows:
        add_edge(
            f"entity:{relation.source_entity_id}",
            f"entity:{relation.target_entity_id}",
            relation.relation_type,
            relation.confidence,
        )

    resource_nodes = [node for node in nodes if node.node_type == "resource"]
    total_resources = len(resource_nodes)
    embedded_sources = sum(1 for node in resource_nodes if bool(node.meta.get("has_embedding")))
    chapter_node_count = sum(1 for node in nodes if node.node_type == "chapter")
    section_node_count = sum(1 for node in nodes if node.node_type == "section")
    format_node_count = sum(1 for node in nodes if node.node_type == "format")
    similarity_edges = sum(1 for edge in edges if edge.edge_type not in {"contains"})

    return schemas.RagGraphOut(
        nodes=nodes,
        edges=edges,
        stats=schemas.RagGraphStatsOut(
            total_resources=total_resources,
            embedded_resources=embedded_sources,
            chapter_nodes=chapter_node_count,
            section_nodes=section_node_count,
            format_nodes=format_node_count,
            public_sources=public_source_count,
            private_sources=private_source_count,
            similarity_edges=similarity_edges,
            generated_at=datetime.now(timezone.utc),
        ),
    )


def _build_highlight_for_source(
    db: Session,
    source: models.RagSource,
    resource: models.Resource | None,
) -> tuple[list[str], list[str]]:
    source_canonical_node = _canonical_node_id(source)
    nodes: list[str] = [source_canonical_node]
    edges: list[str] = []

    if resource and resource.chapter_id:
        nodes.append(f"chapter:{resource.chapter_id}")
    if resource:
        section_key = f"{resource.chapter_id if resource.chapter_id else 'unknown'}:{resource.section_id if resource.section_id else 'unassigned'}"
    else:
        section_key = "private:workspace"
    nodes.append(f"section:{section_key}")
    format_key, _ = _resolve_format_group(resource, source)
    nodes.append(f"format:{section_key}:{format_key}")

    relation_rows = (
        db.query(models.RagRelation)
        .filter(models.RagRelation.source_id == source.id)
        .order_by(models.RagRelation.confidence.desc())
        .limit(5)
        .all()
    )
    for relation in relation_rows:
        source_node = f"entity:{relation.source_entity_id}"
        target_node = f"entity:{relation.target_entity_id}"
        nodes.extend([source_node, target_node])
        edges.append(f"{source_node}->{target_node}:{relation.relation_type}")

    return list(dict.fromkeys(nodes)), list(dict.fromkeys(edges))


def _workspace_candidates(
    db: Session,
    workspace: models.RagWorkspace,
    *,
    dedupe: bool = True,
) -> tuple[list[semantic_ranker.SemanticCandidate], dict[int, models.Resource], dict[int, models.RagSource]]:
    all_source_rows = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
        )
        .order_by(models.RagSource.updated_at.desc())
        .all()
    )
    source_map = {row.id: row for row in all_source_rows}

    resource_ids = [row.resource_id for row in all_source_rows if row.resource_id]
    resource_map: dict[int, models.Resource] = {}
    if resource_ids:
        resources = (
            db.query(models.Resource)
            .filter(
                models.Resource.id.in_(resource_ids),
                models.Resource.is_trashed.is_(False),
                models.Resource.status == models.ResourceStatus.approved,
            )
            .all()
        )
        resource_map = {row.id: row for row in resources}

    valid_rows: list[models.RagSource] = []
    for source in all_source_rows:
        resource = resource_map.get(source.resource_id or -1)
        if source.source_type == "resource" and source.resource_id and not resource:
            continue
        if not _source_is_graph_visible(source):
            continue
        valid_rows.append(source)

    if dedupe:
        best_by_canonical: dict[str, models.RagSource] = {}
        for source in valid_rows:
            canonical_key = _resolve_source_canonical_key(source)
            current = best_by_canonical.get(canonical_key)
            if current is None:
                best_by_canonical[canonical_key] = source
                continue
            current_score = (_source_display_priority(current), current.updated_at or datetime.min.replace(tzinfo=timezone.utc))
            next_score = (_source_display_priority(source), source.updated_at or datetime.min.replace(tzinfo=timezone.utc))
            if next_score > current_score:
                best_by_canonical[canonical_key] = source
        source_rows = list(best_by_canonical.values())
    else:
        source_rows = valid_rows

    candidates: list[semantic_ranker.SemanticCandidate] = []
    for source in source_rows:
        resource = resource_map.get(source.resource_id or -1)
        title = resource.title if resource else source.title
        description = (resource.description if resource else "") or ""
        summary = (resource.ai_summary if resource else source.summary_text) or ""
        tags = list(
            dict.fromkeys(
                (source.tags or [])
                + ((resource.ai_tags if resource else []) or [])
                + ((resource.tags if resource else []) or [])
            )
        )
        embedding = None
        if resource and isinstance(resource.embedding_json, list):
            embedding = resource.embedding_json
        elif isinstance(source.embedding_json, list):
            embedding = source.embedding_json

        highlight_nodes, highlight_edges = _build_highlight_for_source(db, source, resource)
        candidates.append(
            semantic_ranker.SemanticCandidate(
                candidate_id=f"source:{source.id}",
                title=title,
                description=description,
                summary=summary,
                tags=tags,
                embedding=embedding,
                chapter_id=resource.chapter_id if resource else None,
                section_id=resource.section_id if resource else None,
                payload={"resource": resource, "source": source},
                target={
                    "resource_id": resource.id if resource else None,
                    "source_id": source.id,
                    "canonical_key": _resolve_source_canonical_key(source),
                    "title": title,
                    "file_format": (resource.file_format if resource else source.file_format),
                    "chapter_id": resource.chapter_id if resource else None,
                    "section_id": resource.section_id if resource else None,
                    "summary": summary,
                    "tags": tags,
                },
                highlight_nodes=highlight_nodes,
                highlight_edges=highlight_edges,
            )
        )

    return candidates, resource_map, source_map


def _get_or_create_default_workspace(
    db: Session,
    *,
    stage: str,
    subject: str,
    creator_id: int,
) -> models.RagWorkspace:
    workspace = (
        db.query(models.RagWorkspace)
        .filter(
            models.RagWorkspace.stage == stage,
            models.RagWorkspace.subject == subject,
            models.RagWorkspace.name == "默认工作台",
        )
        .order_by(models.RagWorkspace.updated_at.desc())
        .first()
    )
    if workspace:
        return workspace

    workspace = models.RagWorkspace(
        name="默认工作台",
        description="GraphRAG 极简默认工作台",
        stage=stage,
        subject=subject,
        created_by=creator_id,
    )
    db.add(workspace)
    db.flush()
    return workspace


def _bind_resources_to_workspace_internal(
    db: Session,
    workspace: models.RagWorkspace,
    *,
    actor_id: int,
) -> tuple[int, int]:
    resources = (
        db.query(models.Resource)
        .filter(
            models.Resource.status == models.ResourceStatus.approved,
            models.Resource.is_trashed.is_(False),
            models.Resource.subject == workspace.subject,
        )
        .order_by(models.Resource.updated_at.desc())
        .limit(260)
        .all()
    )
    if not resources:
        return 0, 0

    exists_rows = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.resource_id.isnot(None),
            models.RagSource.source_type == "resource",
        )
        .order_by(models.RagSource.updated_at.desc(), models.RagSource.id.desc())
        .all()
    )
    existing_by_resource: dict[int, models.RagSource] = {}
    for row in exists_rows:
        if not row.resource_id or row.resource_id in existing_by_resource:
            continue
        existing_by_resource[row.resource_id] = row

    created = 0
    skipped = 0
    for resource in resources:
        existing = existing_by_resource.get(resource.id)
        if existing:
            changed = False
            if not rag_sync.is_rag_source_active(existing.status):
                existing.status = "ready"
                changed = True
            tags = list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or [])))
            summary = resource.ai_summary or resource.description
            embedding = resource.embedding_json if isinstance(resource.embedding_json, list) else None
            variant_kind = resource_variants.guess_variant_kind_from_object_key(
                resource.object_key,
                resource.file_format,
            )
            if existing.title != resource.title:
                existing.title = resource.title
                changed = True
            if existing.object_key != resource.object_key:
                existing.object_key = resource.object_key
                changed = True
            if existing.file_format != resource.file_format:
                existing.file_format = resource.file_format
                changed = True
            if existing.summary_text != summary:
                existing.summary_text = summary
                changed = True
            if (existing.tags or []) != tags:
                existing.tags = tags
                changed = True
            if existing.embedding_json != embedding:
                existing.embedding_json = embedding
                changed = True
            canonical_key = resource_variants.build_canonical_key(
                resource_id=resource.id,
                object_key=resource.object_key,
            )
            if existing.canonical_key != canonical_key:
                existing.canonical_key = canonical_key
                changed = True
            if existing.variant_kind != variant_kind:
                existing.variant_kind = variant_kind
                changed = True
            if existing.is_graph_visible is not True:
                existing.is_graph_visible = True
                changed = True
            priority = resource_variants.variant_priority(variant_kind)
            if existing.display_priority != priority:
                existing.display_priority = priority
                changed = True
            if changed:
                existing.updated_at = datetime.now(timezone.utc)
                db.add(existing)
                created += 1
            else:
                skipped += 1
            continue

        db.add(
            models.RagSource(
                workspace_id=workspace.id,
                source_type="resource",
                resource_id=resource.id,
                title=resource.title,
                object_key=resource.object_key,
                file_format=resource.file_format,
                summary_text=resource.ai_summary or resource.description,
                tags=list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or []))),
                embedding_json=resource.embedding_json if isinstance(resource.embedding_json, list) else None,
                status="ready",
                canonical_key=resource_variants.build_canonical_key(
                    resource_id=resource.id,
                    object_key=resource.object_key,
                ),
                variant_kind=resource_variants.guess_variant_kind_from_object_key(
                    resource.object_key,
                    resource.file_format,
                ),
                is_graph_visible=True,
                display_priority=resource_variants.variant_priority(resource_variants.VARIANT_KIND_ORIGIN),
                created_by=actor_id,
            )
        )
        created += 1

    return created, skipped


def _run_extract_job(
    db: Session,
    workspace: models.RagWorkspace,
    source_rows: list[models.RagSource],
    *,
    mode: str,
    actor_id: int,
    existing_job: models.RagExtractionJob | None = None,
) -> tuple[models.RagExtractionJob, dict[str, int]]:
    job = existing_job
    if job is None:
        job = models.RagExtractionJob(
            workspace_id=workspace.id,
            source_id=source_rows[0].id if len(source_rows) == 1 else None,
            mode=mode,
            status=bootstrap_service.BOOTSTRAP_STATUS_PROCESSING,
            stats={},
            created_by=actor_id,
        )
        db.add(job)
        db.flush()
    else:
        job.mode = mode
        job.status = bootstrap_service.BOOTSTRAP_STATUS_PROCESSING
        job.error_message = None
        db.add(job)
        db.flush()

    entities = 0
    relations = 0
    evidences = 0
    succeeded_sources = 0
    failed_sources: list[dict[str, str | int | None]] = []
    for source in source_rows:
        try:
            with db.begin_nested():
                stat = _extract_for_source(db, workspace, source, mode=mode)
            entities += stat["entities"]
            relations += stat["relations"]
            evidences += stat["evidences"]
            succeeded_sources += 1
        except Exception as error:  # noqa: BLE001
            logger.exception("RAG extract failed for source_id=%s mode=%s", source.id, mode)
            failed_sources.append(
                {
                    "source_id": source.id,
                    "stage": "extract",
                    "message": str(error),
                }
            )
            source.status = "error"
            db.add(source)

    if failed_sources and succeeded_sources > 0:
        final_status = bootstrap_service.BOOTSTRAP_STATUS_PARTIAL_FAILED
    elif failed_sources:
        final_status = bootstrap_service.BOOTSTRAP_STATUS_FAILED
    else:
        final_status = bootstrap_service.BOOTSTRAP_STATUS_DONE

    job.status = final_status
    job.stats = {
        "processed_sources": len(source_rows),
        "succeeded_sources": succeeded_sources,
        "failed_sources_count": len(failed_sources),
        "failed_sources": failed_sources,
        "entities_created": entities,
        "relations_created": relations,
        "evidences_created": evidences,
        "mode": mode,
    }
    if failed_sources:
        job.error_message = f"{len(failed_sources)} source(s) failed during extract"
    workspace.updated_at = datetime.now(timezone.utc)
    db.add_all([job, workspace])

    return job, {
        "processed_sources": len(source_rows),
        "succeeded_sources": succeeded_sources,
        "failed_sources_count": len(failed_sources),
        "failed_sources": failed_sources,
        "entities_created": entities,
        "relations_created": relations,
        "evidences_created": evidences,
    }


def _should_run_quick_extract(
    db: Session,
    workspace: models.RagWorkspace,
    *,
    force_extract: bool,
) -> tuple[bool, str]:
    if force_extract:
        return True, "forced"

    source_count = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
        )
        .count()
    )
    if source_count == 0:
        return False, "no_sources"

    latest_done_job = (
        db.query(models.RagExtractionJob)
        .filter(
            models.RagExtractionJob.workspace_id == workspace.id,
            models.RagExtractionJob.status == "done",
        )
        .order_by(models.RagExtractionJob.updated_at.desc())
        .first()
    )
    if latest_done_job is None:
        return True, "no_extract_job"

    latest_resource_update = (
        db.query(models.Resource.updated_at)
        .join(models.RagSource, models.RagSource.resource_id == models.Resource.id)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
            models.Resource.status == models.ResourceStatus.approved,
            models.Resource.is_trashed.is_(False),
        )
        .order_by(models.Resource.updated_at.desc())
        .limit(1)
        .scalar()
    )
    if latest_resource_update and latest_resource_update > latest_done_job.updated_at:
        return True, "resources_updated"

    if latest_done_job.updated_at < datetime.now(timezone.utc) - timedelta(hours=12):
        return True, "stale_over_12h"

    return False, "fresh"


def _is_bootstrap_terminal(status_value: str | None) -> bool:
    return status_value in {
        bootstrap_service.BOOTSTRAP_STATUS_DONE,
        bootstrap_service.BOOTSTRAP_STATUS_PARTIAL_FAILED,
        bootstrap_service.BOOTSTRAP_STATUS_FAILED,
        bootstrap_service.BOOTSTRAP_STATUS_SKIPPED,
    }


def _run_bootstrap_job_in_background(
    workspace_id: int,
    job_id: int,
    actor_id: int,
) -> None:
    db = WriteSessionLocal()
    try:
        workspace = (
            db.query(models.RagWorkspace)
            .filter(models.RagWorkspace.id == workspace_id)
            .first()
        )
        job = (
            db.query(models.RagExtractionJob)
            .filter(
                models.RagExtractionJob.id == job_id,
                models.RagExtractionJob.workspace_id == workspace_id,
            )
            .first()
        )
        if workspace is None or job is None:
            return

        job.status = bootstrap_service.BOOTSTRAP_STATUS_PROCESSING
        job.error_message = None
        db.add(job)
        db.commit()
        db.refresh(job)

        source_rows = (
            db.query(models.RagSource)
            .filter(
                models.RagSource.workspace_id == workspace_id,
                models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
            )
            .order_by(models.RagSource.updated_at.desc())
            .all()
        )
        if not source_rows:
            job.status = bootstrap_service.BOOTSTRAP_STATUS_SKIPPED
            job.stats = {
                "processed_sources": 0,
                "succeeded_sources": 0,
                "failed_sources_count": 0,
                "failed_sources": [],
                "entities_created": 0,
                "relations_created": 0,
                "evidences_created": 0,
                "mode": "quick",
            }
            job.error_message = None
            db.add(job)
            db.commit()
            return

        _run_extract_job(
            db,
            workspace,
            source_rows,
            mode="quick",
            actor_id=actor_id,
            existing_job=job,
        )
        db.commit()
        rag_cache.invalidate_graph_cache(f"workspace:{workspace_id}:")
    except Exception as error:  # noqa: BLE001
        db.rollback()
        logger.exception("RAG bootstrap job failed: workspace_id=%s job_id=%s", workspace_id, job_id)
        try:
            job = (
                db.query(models.RagExtractionJob)
                .filter(
                    models.RagExtractionJob.id == job_id,
                    models.RagExtractionJob.workspace_id == workspace_id,
                )
                .first()
            )
            if job:
                stats = job.stats if isinstance(job.stats, dict) else {}
                failed_sources = bootstrap_service.normalize_failed_sources(stats.get("failed_sources"))
                failed_sources.append(
                    {
                        "source_id": None,
                        "stage": "bootstrap",
                        "message": str(error)[:800],
                    }
                )
                stats.update(
                    {
                        "failed_sources": failed_sources,
                        "failed_sources_count": len(failed_sources),
                    }
                )
                job.stats = stats
                job.status = bootstrap_service.BOOTSTRAP_STATUS_FAILED
                job.error_message = str(error)[:800]
                db.add(job)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()


def _resource_open_path(resource_id: int | None) -> str | None:
    if not resource_id:
        return None
    return f"/viewer/resource/{resource_id}"


def _linked_resources_for_node(
    db: Session,
    workspace: models.RagWorkspace,
    *,
    node_id: str,
    limit: int,
) -> list[schemas.RagLinkedResourceOut]:
    normalized_node_id = (node_id or "").strip()
    if not normalized_node_id:
        return []

    max_limit = max(1, min(20, limit))
    items: list[schemas.RagLinkedResourceOut] = []
    seen_sources: set[int] = set()

    def push_item(source: models.RagSource, resource: models.Resource | None, score: float) -> None:
        if source.id in seen_sources:
            return
        seen_sources.add(source.id)
        keyword_title = build_resource_keyword_label(source, resource)
        resource_id = resource.id if resource else source.resource_id
        is_openable = bool(resource and resource.id)
        items.append(
            schemas.RagLinkedResourceOut(
                source_id=source.id,
                resource_id=resource_id,
                keyword_title=keyword_title,
                open_path=_resource_open_path(resource.id if resource else None),
                score=round(float(score), 4),
                is_openable=is_openable,
                message=None if is_openable else "该源尚未发布到资源库",
            )
        )

    if normalized_node_id.startswith("canonical:"):
        source_rows = (
            db.query(models.RagSource)
            .filter(
                models.RagSource.workspace_id == workspace.id,
                models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
            )
            .order_by(models.RagSource.updated_at.desc())
            .all()
        )
        matched = [row for row in source_rows if _canonical_node_id(row) == normalized_node_id]
        if not matched:
            return []
        matched = sorted(
            matched,
            key=lambda row: (
                _source_display_priority(row),
                row.updated_at or datetime.min.replace(tzinfo=timezone.utc),
                row.id,
            ),
            reverse=True,
        )
        for index, source in enumerate(matched, start=1):
            resource = None
            if source.resource_id:
                resource = (
                    db.query(models.Resource)
                    .filter(
                        models.Resource.id == source.resource_id,
                        models.Resource.is_trashed.is_(False),
                        models.Resource.status == models.ResourceStatus.approved,
                    )
                    .first()
                )
            push_item(source, resource, max(0.2, 1 - index * 0.05))
            if len(items) >= max_limit:
                break
        return items

    if normalized_node_id.startswith("source:"):
        try:
            source_id = int(normalized_node_id.split(":", 1)[1])
        except ValueError:
            return []
        source = (
            db.query(models.RagSource)
            .filter(
                models.RagSource.workspace_id == workspace.id,
                models.RagSource.id == source_id,
                models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
            )
            .first()
        )
        if not source:
            return []
        resource = None
        if source.resource_id:
            resource = (
                db.query(models.Resource)
                .filter(
                    models.Resource.id == source.resource_id,
                    models.Resource.is_trashed.is_(False),
                    models.Resource.status == models.ResourceStatus.approved,
                )
                .first()
            )
        push_item(source, resource, 1.0)
        return items

    if normalized_node_id.startswith("chapter:"):
        chapter_raw = normalized_node_id.split(":", 1)[1]
        if chapter_raw.isdigit():
            chapter_id = int(chapter_raw)
            source_rows = (
                db.query(models.RagSource, models.Resource)
                .join(models.Resource, models.Resource.id == models.RagSource.resource_id)
                .filter(
                    models.RagSource.workspace_id == workspace.id,
                    models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
                    models.Resource.is_trashed.is_(False),
                    models.Resource.status == models.ResourceStatus.approved,
                    models.Resource.chapter_id == chapter_id,
                )
                .order_by(models.Resource.updated_at.desc())
                .limit(max_limit * 3)
                .all()
            )
            for index, (source, resource) in enumerate(source_rows, start=1):
                push_item(source, resource, max(0.2, 1 - index * 0.03))
                if len(items) >= max_limit:
                    break
        return items

    if normalized_node_id.startswith("section:"):
        section_part = normalized_node_id.split(":", 1)[1]
        if section_part == "private:workspace":
            rows = (
                db.query(models.RagSource)
                .filter(
                    models.RagSource.workspace_id == workspace.id,
                    models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
                    models.RagSource.source_type != "resource",
                )
                .order_by(models.RagSource.updated_at.desc())
                .limit(max_limit * 3)
                .all()
            )
            for index, source in enumerate(rows, start=1):
                push_item(source, None, max(0.2, 1 - index * 0.03))
                if len(items) >= max_limit:
                    break
            return items

        parts = section_part.split(":")
        section_id = int(parts[-1]) if parts and parts[-1].isdigit() else None
        source_query = (
            db.query(models.RagSource, models.Resource)
            .join(models.Resource, models.Resource.id == models.RagSource.resource_id)
            .filter(
                models.RagSource.workspace_id == workspace.id,
                models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
                models.Resource.is_trashed.is_(False),
                models.Resource.status == models.ResourceStatus.approved,
            )
        )
        if section_id is None:
            source_query = source_query.filter(models.Resource.section_id.is_(None))
        else:
            source_query = source_query.filter(models.Resource.section_id == section_id)
        rows = source_query.order_by(models.Resource.updated_at.desc()).limit(max_limit * 3).all()
        for index, (source, resource) in enumerate(rows, start=1):
            push_item(source, resource, max(0.2, 1 - index * 0.03))
            if len(items) >= max_limit:
                break
        return items

    if normalized_node_id.startswith("format:"):
        format_part = normalized_node_id.split(":", 1)[1]
        if ":" not in format_part:
            return []
        section_part, format_key = format_part.rsplit(":", 1)
        if not format_key:
            return []

        if section_part == "private:workspace":
            rows = (
                db.query(models.RagSource)
                .filter(
                    models.RagSource.workspace_id == workspace.id,
                    models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
                    models.RagSource.source_type != "resource",
                )
                .order_by(models.RagSource.updated_at.desc())
                .limit(max_limit * 4)
                .all()
            )
            for index, source in enumerate(rows, start=1):
                current_format_key, _ = _resolve_format_group(None, source)
                if current_format_key != format_key:
                    continue
                push_item(source, None, max(0.2, 1 - index * 0.03))
                if len(items) >= max_limit:
                    break
            return items

        parts = section_part.split(":")
        section_id = int(parts[-1]) if parts and parts[-1].isdigit() else None
        query = (
            db.query(models.RagSource, models.Resource)
            .join(models.Resource, models.Resource.id == models.RagSource.resource_id)
            .filter(
                models.RagSource.workspace_id == workspace.id,
                models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
                models.Resource.is_trashed.is_(False),
                models.Resource.status == models.ResourceStatus.approved,
            )
        )
        if section_id is None:
            query = query.filter(models.Resource.section_id.is_(None))
        else:
            query = query.filter(models.Resource.section_id == section_id)
        rows = query.order_by(models.Resource.updated_at.desc()).limit(max_limit * 4).all()
        for index, (source, resource) in enumerate(rows, start=1):
            current_format_key, _ = _resolve_format_group(resource, source)
            if current_format_key != format_key:
                continue
            push_item(source, resource, max(0.2, 1 - index * 0.03))
            if len(items) >= max_limit:
                break
        return items

    if normalized_node_id.startswith("entity:"):
        entity_raw = normalized_node_id.split(":", 1)[1]
        if not entity_raw.isdigit():
            return []
        entity_id = int(entity_raw)
        relation_rows = (
            db.query(models.RagRelation)
            .filter(
                models.RagRelation.workspace_id == workspace.id,
                or_(
                    models.RagRelation.source_entity_id == entity_id,
                    models.RagRelation.target_entity_id == entity_id,
                ),
                models.RagRelation.source_id.isnot(None),
            )
            .order_by(models.RagRelation.confidence.desc(), models.RagRelation.id.desc())
            .limit(120)
            .all()
        )
        best_score_by_source: dict[int, float] = {}
        for relation in relation_rows:
            if relation.source_id is None:
                continue
            current = best_score_by_source.get(relation.source_id)
            score = float(relation.confidence or 0.0)
            if current is None or score > current:
                best_score_by_source[relation.source_id] = score

        if not best_score_by_source:
            return []

        source_rows = (
            db.query(models.RagSource)
            .filter(
                models.RagSource.workspace_id == workspace.id,
                models.RagSource.id.in_(list(best_score_by_source.keys())),
                models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
            )
            .all()
        )
        source_map = {row.id: row for row in source_rows}
        resource_ids = [row.resource_id for row in source_rows if row.resource_id]
        resources = (
            db.query(models.Resource)
            .filter(
                models.Resource.id.in_(resource_ids) if resource_ids else models.Resource.id == -1,
                models.Resource.is_trashed.is_(False),
                models.Resource.status == models.ResourceStatus.approved,
            )
            .all()
        )
        resource_map = {row.id: row for row in resources}

        ranked_source_ids = sorted(best_score_by_source, key=lambda sid: best_score_by_source[sid], reverse=True)
        for source_id in ranked_source_ids:
            source = source_map.get(source_id)
            if not source:
                continue
            resource = resource_map.get(source.resource_id or -1)
            push_item(source, resource, best_score_by_source[source_id])
            if len(items) >= max_limit:
                break
        return items

    return []


def _variants_for_node(
    db: Session,
    workspace: models.RagWorkspace,
    *,
    node_id: str,
    user_id: int | None,
) -> schemas.RagNodeVariantsOut:
    normalized_node_id = (node_id or "").strip()
    if not normalized_node_id:
        return schemas.RagNodeVariantsOut(node_id=node_id, variants=[])

    source_rows = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
        )
        .order_by(models.RagSource.updated_at.desc(), models.RagSource.id.desc())
        .all()
    )
    if not source_rows:
        return schemas.RagNodeVariantsOut(node_id=node_id, variants=[])

    if normalized_node_id.startswith("source:"):
        try:
            source_id = int(normalized_node_id.split(":", 1)[1])
        except ValueError:
            return schemas.RagNodeVariantsOut(node_id=node_id, variants=[])
        matched = [row for row in source_rows if row.id == source_id]
    elif normalized_node_id.startswith("canonical:"):
        matched = [row for row in source_rows if _canonical_node_id(row) == normalized_node_id]
    else:
        return schemas.RagNodeVariantsOut(node_id=node_id, variants=[])

    if not matched:
        return schemas.RagNodeVariantsOut(node_id=node_id, variants=[])

    resource_ids = [row.resource_id for row in matched if row.resource_id]
    resource_map: dict[int, models.Resource] = {}
    if resource_ids:
        resources = (
            db.query(models.Resource)
            .filter(models.Resource.id.in_(resource_ids))
            .all()
        )
        resource_map = {row.id: row for row in resources}

    sorted_sources = sorted(
        matched,
        key=lambda row: (
            _source_display_priority(row),
            row.updated_at or datetime.min.replace(tzinfo=timezone.utc),
            row.id,
        ),
        reverse=True,
    )
    canonical_key = _resolve_source_canonical_key(sorted_sources[0])
    variants: list[schemas.RagNodeVariantOut] = []
    for index, source in enumerate(sorted_sources):
        resource = resource_map.get(source.resource_id or -1)
        visibility = "public" if (
            source.source_type == "resource"
            and source.resource_id
            and _resource_is_public(resource)
        ) else "private"
        open_url = None
        download_url = None
        if source.object_key:
            open_url, download_url = build_storage_access_urls(
                object_key=source.object_key,
                user_id=user_id,
            )
        variants.append(
            schemas.RagNodeVariantOut(
                source_id=source.id,
                resource_id=source.resource_id,
                title=source.title,
                object_key=source.object_key,
                variant_kind=_resolve_source_variant_kind(source),
                file_format=(resource.file_format if resource else source.file_format) or None,
                is_graph_visible=_source_is_graph_visible(source),
                open_url=open_url,
                download_url=download_url,
                visibility=visibility,
                display_priority=_source_display_priority(source),
                is_primary=index == 0,
            )
        )

    auto_open_kind = resource_variants.auto_open_variant_kind(
        [item.variant_kind or resource_variants.VARIANT_KIND_UPLOAD for item in variants],
        primary_file_format=variants[0].file_format if variants else None,
    )
    return schemas.RagNodeVariantsOut(
        node_id=node_id,
        canonical_key=canonical_key,
        primary_source_id=variants[0].source_id if variants else None,
        auto_open_variant_kind=auto_open_kind,
        variants=variants,
    )


@router.get("/workspaces", response_model=list[schemas.RagWorkspaceOut])
def list_workspaces(
    stage: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.RagWorkspace)
    if stage:
        query = query.filter(models.RagWorkspace.stage == stage)
    if subject:
        query = query.filter(models.RagWorkspace.subject == subject)
    rows = query.order_by(models.RagWorkspace.updated_at.desc()).all()
    return [_to_workspace_out(row) for row in rows]


@router.post("/quick-bootstrap", response_model=schemas.RagQuickBootstrapOut)
def quick_bootstrap(
    payload: schemas.RagQuickBootstrapRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    stage = (payload.stage or "senior").strip() or "senior"
    subject = (payload.subject or "物理").strip() or "物理"

    workspace = _get_or_create_default_workspace(
        db,
        stage=stage,
        subject=subject,
        creator_id=current_user.id,
    )

    pruned_count = rag_sync.prune_invalid_sources(db, workspace.id)

    bound_count, skipped_count = _bind_resources_to_workspace_internal(
        db,
        workspace,
        actor_id=current_user.id,
    )
    db.flush()

    source_rows = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
        )
        .order_by(models.RagSource.updated_at.desc())
        .all()
    )
    source_count = len(source_rows)

    should_extract, reason = _should_run_quick_extract(
        db,
        workspace,
        force_extract=payload.force_extract,
    )

    extracted = False
    extract_stats: dict[str, int] = {}
    bootstrap_job: models.RagExtractionJob | None = None
    bootstrap_status = bootstrap_service.BOOTSTRAP_STATUS_SKIPPED
    if should_extract and source_count > 0:
        if _can_manage_workspace(current_user):
            active_job = (
                db.query(models.RagExtractionJob)
                .filter(
                    models.RagExtractionJob.workspace_id == workspace.id,
                    models.RagExtractionJob.status.in_(
                        list(bootstrap_service.ACTIVE_BOOTSTRAP_STATUSES)
                    ),
                )
                .order_by(models.RagExtractionJob.created_at.desc())
                .first()
            )
            if active_job:
                extracted = True
                reason = "already_running"
                bootstrap_job = active_job
                bootstrap_status = active_job.status
            else:
                extracted = True
                bootstrap_status = bootstrap_service.BOOTSTRAP_STATUS_QUEUED
                bootstrap_job = models.RagExtractionJob(
                    workspace_id=workspace.id,
                    source_id=None,
                    mode="quick",
                    status=bootstrap_service.BOOTSTRAP_STATUS_QUEUED,
                    stats={
                        "processed_sources": source_count,
                        "succeeded_sources": 0,
                        "failed_sources_count": 0,
                        "failed_sources": [],
                        "entities_created": 0,
                        "relations_created": 0,
                        "evidences_created": 0,
                        "mode": "quick",
                    },
                    created_by=current_user.id,
                )
                db.add(bootstrap_job)
                db.flush()
        else:
            reason = "permission_skip"

    if bound_count > 0 and not extracted:
        workspace.updated_at = datetime.now(timezone.utc)
        db.add(workspace)

    db.commit()
    rag_cache.invalidate_graph_cache(f"workspace:{workspace.id}:")
    db.refresh(workspace)
    if bootstrap_job and bootstrap_status == bootstrap_service.BOOTSTRAP_STATUS_QUEUED:
        thread = threading.Thread(
            target=_run_bootstrap_job_in_background,
            args=(workspace.id, bootstrap_job.id, current_user.id),
            daemon=True,
        )
        thread.start()

    return schemas.RagQuickBootstrapOut(
        workspace=_to_workspace_out(workspace),
        source_count=source_count,
        bound_count=bound_count,
        skipped_count=skipped_count,
        pruned_count=pruned_count,
        extracted=extracted,
        extract_reason=reason,
        extract_stats=extract_stats,
        bootstrap_job_id=bootstrap_job.id if bootstrap_job else None,
        bootstrap_status=bootstrap_status,
        failed_sources_count=0,
    )


@router.post("/workspaces", response_model=schemas.RagWorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: schemas.RagWorkspaceCreateRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage_workspace(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")

    row = models.RagWorkspace(
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        stage=(payload.stage or "senior").strip() or "senior",
        subject=(payload.subject or "物理").strip() or "物理",
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_workspace_out(row)


@router.get("/workspaces/{workspace_id}/sources", response_model=list[schemas.RagSourceOut])
def list_workspace_sources(
    workspace_id: int,
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    _ensure_workspace(db, workspace_id)
    rows = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace_id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
        )
        .order_by(models.RagSource.updated_at.desc())
        .all()
    )
    return [_to_source_out(row) for row in rows]


@router.post("/workspaces/{workspace_id}/sources/bind-resources", response_model=schemas.RagSourcesBindOut)
def bind_resources_to_workspace(
    workspace_id: int,
    payload: schemas.RagBindResourcesRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage_workspace(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")

    workspace = _ensure_workspace(db, workspace_id)
    resource_ids = list(dict.fromkeys([item for item in payload.resource_ids if item > 0]))
    if not resource_ids:
        return schemas.RagSourcesBindOut(created=0, skipped=0, items=[])

    resources = (
        db.query(models.Resource)
        .filter(
            models.Resource.id.in_(resource_ids),
            models.Resource.is_trashed.is_(False),
            models.Resource.status == models.ResourceStatus.approved,
        )
        .all()
    )
    resource_map = {row.id: row for row in resources}

    created = 0
    skipped = 0
    created_items: list[schemas.RagSourceOut] = []

    for resource_id in resource_ids:
        resource = resource_map.get(resource_id)
        if not resource:
            skipped += 1
            continue

        exists = (
            db.query(models.RagSource)
            .filter(
                models.RagSource.workspace_id == workspace.id,
                models.RagSource.resource_id == resource.id,
                models.RagSource.source_type == "resource",
            )
            .order_by(models.RagSource.updated_at.desc(), models.RagSource.id.desc())
            .first()
        )
        if exists:
            if rag_sync.is_rag_source_active(exists.status):
                skipped += 1
            else:
                variant_kind = resource_variants.guess_variant_kind_from_object_key(
                    resource.object_key,
                    resource.file_format,
                )
                exists.status = "ready"
                exists.title = resource.title
                exists.object_key = resource.object_key
                exists.file_format = resource.file_format
                exists.summary_text = resource.ai_summary or resource.description
                exists.tags = list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or [])))
                exists.embedding_json = resource.embedding_json if isinstance(resource.embedding_json, list) else None
                exists.canonical_key = resource_variants.build_canonical_key(
                    resource_id=resource.id,
                    object_key=resource.object_key,
                )
                exists.variant_kind = variant_kind
                exists.is_graph_visible = True
                exists.display_priority = resource_variants.variant_priority(variant_kind)
                exists.updated_at = datetime.now(timezone.utc)
                db.add(exists)
                created += 1
                created_items.append(_to_source_out(exists))
            continue

        row = models.RagSource(
            workspace_id=workspace.id,
            source_type="resource",
            resource_id=resource.id,
            title=resource.title,
            object_key=resource.object_key,
            file_format=resource.file_format,
            summary_text=resource.ai_summary or resource.description,
            tags=list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or []))),
            embedding_json=resource.embedding_json if isinstance(resource.embedding_json, list) else None,
            status="ready",
            canonical_key=resource_variants.build_canonical_key(
                resource_id=resource.id,
                object_key=resource.object_key,
            ),
            variant_kind=resource_variants.guess_variant_kind_from_object_key(
                resource.object_key,
                resource.file_format,
            ),
            is_graph_visible=True,
            display_priority=resource_variants.variant_priority(resource_variants.VARIANT_KIND_ORIGIN),
            created_by=current_user.id,
        )
        db.add(row)
        db.flush()
        created += 1
        created_items.append(_to_source_out(row))

    workspace.updated_at = datetime.now(timezone.utc)
    db.add(workspace)
    db.commit()
    if created > 0:
        rag_cache.invalidate_graph_cache(f"workspace:{workspace.id}:")

    return schemas.RagSourcesBindOut(created=created, skipped=skipped, items=created_items)


@router.post("/workspaces/{workspace_id}/sources/upload", response_model=schemas.RagSourceUploadOut, status_code=status.HTTP_201_CREATED)
def upload_workspace_source(
    workspace_id: int,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    summary_text: str = Form(default=""),
    tags: str = Form(default=""),
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage_workspace(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")
    workspace = _ensure_workspace(db, workspace_id)

    if not file.filename:
        raise HTTPException(status_code=400, detail="File is required")

    suffix = Path(file.filename).suffix.lower()
    planned_key = f"rag/workspaces/{workspace.id}/{uuid4().hex}{suffix}"
    try:
        object_key, _ = storage_service.upload_file(file, object_key=planned_key)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Upload failed: {error}") from error

    parsed_tags = [item.strip() for item in tags.split(",") if item.strip()]
    uploaded_format = _detect_file_format(file.filename)
    upload_variant_kind = resource_variants.normalize_variant_kind(
        resource_variants.VARIANT_KIND_UPLOAD,
        fallback=resource_variants.VARIANT_KIND_UPLOAD,
    )
    row = models.RagSource(
        workspace_id=workspace.id,
        source_type="upload",
        resource_id=None,
        title=(title or Path(file.filename).stem).strip() or Path(file.filename).stem,
        object_key=object_key,
        file_format=uploaded_format,
        summary_text=summary_text.strip() or None,
        tags=list(dict.fromkeys(parsed_tags)),
        status="ready",
        canonical_key=resource_variants.build_canonical_key(object_key=object_key),
        variant_kind=upload_variant_kind,
        is_graph_visible=True,
        display_priority=resource_variants.variant_priority(upload_variant_kind),
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    rag_cache.invalidate_graph_cache(f"workspace:{workspace.id}:")
    db.refresh(row)

    return schemas.RagSourceUploadOut(source=_to_source_out(row), object_key=object_key)


@router.post("/workspaces/{workspace_id}/extract", response_model=schemas.RagExtractOut)
def extract_workspace_graph(
    workspace_id: int,
    payload: schemas.RagExtractRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage_workspace(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")
    workspace = _ensure_workspace(db, workspace_id)

    source_query = db.query(models.RagSource).filter(models.RagSource.workspace_id == workspace.id)
    if payload.source_ids:
        source_query = source_query.filter(models.RagSource.id.in_(payload.source_ids))
    source_rows = source_query.order_by(models.RagSource.updated_at.desc()).all()
    if not source_rows:
        raise HTTPException(status_code=404, detail="No source found")

    job, stats = _run_extract_job(
        db,
        workspace,
        source_rows,
        mode=payload.mode,
        actor_id=current_user.id,
    )
    db.commit()
    rag_cache.invalidate_graph_cache(f"workspace:{workspace.id}:")

    return schemas.RagExtractOut(
        job_id=job.id,
        mode=payload.mode,
        status=job.status,
        processed_sources=stats["processed_sources"],
        entities_created=stats["entities_created"],
        relations_created=stats["relations_created"],
        evidences_created=stats["evidences_created"],
    )


@router.get("/workspaces/{workspace_id}/graph", response_model=schemas.RagGraphOut)
def workspace_graph(
    workspace_id: int,
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=40, le=800),
    scope: str = Query(default=RAG_GRAPH_SCOPE_PUBLIC, pattern="^(public|mixed)$"),
    include_format_nodes: bool = Query(default=True),
    dedupe: bool = Query(default=True),
    include_variants: bool = Query(default=True),
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    workspace = _ensure_workspace(db, workspace_id)
    cache_key = (
        f"workspace:{workspace.id}:graph:"
        f"scope={scope}|q={(q or '').strip()}|limit={limit}|"
        f"format={int(include_format_nodes)}|dedupe={int(dedupe)}|variants={int(include_variants)}"
    )
    cached = rag_cache.get_cached_graph(cache_key)
    if cached is not None:
        return cached
    graph_out = _build_workspace_graph(
        db,
        workspace,
        q=q,
        limit=limit,
        scope=scope,
        include_format_nodes=include_format_nodes,
        dedupe=dedupe,
        include_variants=include_variants,
        access_user_id=current_user.id,
    )
    rag_cache.set_cached_graph(cache_key, graph_out)
    return graph_out


@router.get(
    "/workspaces/{workspace_id}/nodes/{node_id}/linked-resources",
    response_model=schemas.RagNodeLinkedResourcesOut,
)
def workspace_node_linked_resources(
    workspace_id: int,
    node_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    workspace = _ensure_workspace(db, workspace_id)
    items = _linked_resources_for_node(
        db,
        workspace,
        node_id=node_id,
        limit=limit,
    )
    return schemas.RagNodeLinkedResourcesOut(node_id=node_id, items=items)


@router.get(
    "/workspaces/{workspace_id}/nodes/{node_id}/variants",
    response_model=schemas.RagNodeVariantsOut,
)
def workspace_node_variants(
    workspace_id: int,
    node_id: str,
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    workspace = _ensure_workspace(db, workspace_id)
    return _variants_for_node(
        db,
        workspace,
        node_id=node_id,
        user_id=current_user.id,
    )


@router.post("/workspaces/{workspace_id}/semantic-search", response_model=schemas.SemanticSearchResponse)
def workspace_semantic_search(
    workspace_id: int,
    payload: schemas.SemanticSearchRequest,
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    workspace = _ensure_workspace(db, workspace_id)
    candidates, resource_map, source_map = _workspace_candidates(
        db,
        workspace,
        dedupe=payload.dedupe,
    )
    candidate_cap = max(20, min(2000, payload.candidate_limit))
    if len(candidates) > candidate_cap:
        candidates = candidates[:candidate_cap]

    query_embedding = _safe_embedding(payload.query)
    ranked = semantic_ranker.rank_candidates(
        payload.query,
        candidates,
        query_embedding=query_embedding,
        top_k=max(1, min(20, payload.top_k, payload.rerank_top_k)),
    )

    items: list[schemas.SemanticSearchItem] = []
    for row in ranked.items:
        source_id = int(row.candidate.candidate_id.split(":", 1)[1])
        source = source_map.get(source_id)
        if not source:
            continue
        resource = resource_map.get(source.resource_id or -1)
        resource_out = to_resource_out(resource) if resource else None

        items.append(
            schemas.SemanticSearchItem(
                score=round(row.probability, 6),
                probability=round(row.probability, 6),
                factors=schemas.SemanticScoreFactorsOut(
                    vector=round(row.vector, 6),
                    summary=round(row.summary, 6),
                    content=round(row.content, 6),
                    tags=round(row.tags, 6),
                    raw=round(row.raw, 6),
                ),
                resource=resource_out,
                target=schemas.SemanticSearchTargetOut(**(row.candidate.target or {})),
                highlight_nodes=row.candidate.highlight_nodes,
                highlight_edges=row.candidate.highlight_edges,
            )
        )

    return schemas.SemanticSearchResponse(
        query=payload.query,
        threshold=round(ranked.threshold, 6),
        returned_count=len(items),
        scoring_profile="balanced_v1",
        results=items,
    )


@router.post("/workspaces/{workspace_id}/qa", response_model=schemas.RagQaResponse)
def workspace_qa(
    workspace_id: int,
    payload: schemas.RagQaRequest,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    workspace = _ensure_workspace(db, workspace_id)
    candidates, resource_map, source_map = _workspace_candidates(
        db,
        workspace,
        dedupe=True,
    )
    ranked = semantic_ranker.rank_candidates(
        payload.question,
        candidates,
        query_embedding=_safe_embedding(payload.question),
        top_k=12,
    )

    contexts: list[dict] = []
    citations: list[schemas.RagCitationOut] = []
    highlight_nodes: list[str] = []
    highlight_edges: list[str] = []

    for row in ranked.items[:12]:
        source_id = int(row.candidate.candidate_id.split(":", 1)[1])
        source = source_map.get(source_id)
        if not source:
            continue
        resource = resource_map.get(source.resource_id or -1)

        summary = (resource.ai_summary if resource else source.summary_text) or (resource.description if resource else "") or ""
        contexts.append(
            {
                "id": resource.id if resource else source.id,
                "title": resource.title if resource else source.title,
                "summary": summary,
                "snippet": summary[:280],
                "tags": row.candidate.tags,
            }
        )
        citations.append(
            schemas.RagCitationOut(
                source_id=source.id,
                title=resource.title if resource else source.title,
                evidence=summary[:280],
                score=round(row.probability, 6),
            )
        )
        highlight_nodes.extend(row.candidate.highlight_nodes)
        highlight_edges.extend(row.candidate.highlight_edges)

    answer = _safe_answer(payload.question, contexts)

    qa_log = models.RagQaLog(
        workspace_id=workspace.id,
        user_id=current_user.id,
        question=payload.question,
        answer=answer,
        citations=[item.model_dump() for item in citations],
        highlight_nodes=list(dict.fromkeys(highlight_nodes)),
        highlight_edges=list(dict.fromkeys(highlight_edges)),
    )
    db.add(qa_log)
    db.commit()

    return schemas.RagQaResponse(
        answer=answer,
        citations=citations,
        highlight_nodes=list(dict.fromkeys(highlight_nodes)),
        highlight_edges=list(dict.fromkeys(highlight_edges)),
    )


@router.post("/ask", response_model=schemas.RagAskResponse)
def rag_ask_global(
    payload: schemas.RagAskRequest,
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    rows = (
        db.query(models.Resource)
        .filter(
            models.Resource.status == models.ResourceStatus.approved,
            models.Resource.is_trashed.is_(False),
        )
        .order_by(models.Resource.updated_at.desc())
        .limit(1200)
        .all()
    )
    query_embedding = _safe_embedding(payload.question)
    candidates: list[semantic_ranker.SemanticCandidate] = []
    for row in rows:
        candidates.append(
            semantic_ranker.SemanticCandidate(
                candidate_id=f"resource:{row.id}",
                title=row.title,
                description=row.description or "",
                summary=row.ai_summary or "",
                tags=list(dict.fromkeys((row.ai_tags or []) + (row.tags or []))),
                embedding=row.embedding_json if isinstance(row.embedding_json, list) else None,
                chapter_id=row.chapter_id,
                section_id=row.section_id,
            )
        )

    ranked = semantic_ranker.rank_candidates(
        payload.question,
        candidates,
        query_embedding=query_embedding,
        top_k=payload.top_k,
    )
    row_map = {row.id: row for row in rows}
    contexts: list[dict] = []
    citations: list[schemas.RagCitationOut] = []
    for item in ranked.items:
        resource_id = int(item.candidate.candidate_id.split(":", 1)[1])
        row = row_map.get(resource_id)
        if not row:
            continue
        summary = row.ai_summary or row.description or ""
        contexts.append(
            {
                "id": row.id,
                "title": row.title,
                "summary": summary,
                "snippet": summary[:280],
                "tags": row.ai_tags or row.tags or [],
            }
        )
        citations.append(
            schemas.RagCitationOut(
                source_id=row.id,
                title=row.title,
                evidence=summary[:280],
                score=round(item.probability, 6),
            )
        )
    answer = _safe_answer(payload.question, contexts)
    return schemas.RagAskResponse(
        answer=answer,
        citations=citations,
        used_count=len(citations),
    )


@router.get("/graph-embedding", response_model=schemas.RagGraphEmbeddingOut)
def rag_graph_embedding(
    workspace_id: int | None = Query(default=None),
    stage: str = Query(default="senior"),
    subject: str = Query(default="物理"),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=40, le=800),
    scope: str = Query(default=RAG_GRAPH_SCOPE_PUBLIC, pattern="^(public|mixed)$"),
    include_format_nodes: bool = Query(default=True),
    dedupe: bool = Query(default=True),
    include_variants: bool = Query(default=True),
    db: Session = Depends(get_db_read),
    current_user: models.User = Depends(get_current_user),
):
    workspace = None
    if workspace_id is not None:
        workspace = _ensure_workspace(db, workspace_id)
    else:
        workspace = (
            db.query(models.RagWorkspace)
            .filter(
                models.RagWorkspace.stage == stage,
                models.RagWorkspace.subject == subject,
            )
            .order_by(models.RagWorkspace.updated_at.desc())
            .first()
        )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    graph_out = _build_workspace_graph(
        db,
        workspace,
        q=q,
        limit=limit,
        scope=scope,
        include_format_nodes=include_format_nodes,
        dedupe=dedupe,
        include_variants=include_variants,
        access_user_id=current_user.id,
    )
    embedding_out = _to_graph_embedding_out(workspace.id, graph_out)

    chapter_rows = (
        db.query(models.Chapter)
        .filter(
            models.Chapter.stage == workspace.stage,
            models.Chapter.subject == workspace.subject,
            models.Chapter.is_enabled.is_(True),
        )
        .all()
    )
    chapter_ids = [item.id for item in chapter_rows]
    if chapter_ids:
        kp_query = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.chapter_id.in_(chapter_ids))
        if scope == RAG_GRAPH_SCOPE_PUBLIC:
            kp_query = kp_query.filter(models.KnowledgePoint.status == "published")
        if q and q.strip():
            keyword = f"%{q.strip()}%"
            kp_query = kp_query.filter(
                or_(
                    models.KnowledgePoint.name.ilike(keyword),
                    models.KnowledgePoint.kp_code.ilike(keyword),
                    models.KnowledgePoint.description.ilike(keyword),
                )
            )
        kp_rows = kp_query.order_by(models.KnowledgePoint.chapter_id.asc(), models.KnowledgePoint.kp_code.asc()).limit(2000).all()
        kp_node_ids: dict[int, str] = {}
        existing_node_ids = {item.id for item in embedding_out.nodes}
        for kp in kp_rows:
            node_id = f"knowledge:{kp.id}"
            kp_node_ids[kp.id] = node_id
            if node_id in existing_node_ids:
                continue
            x = _hash_to_axis(node_id, "kx") * 1.4 + (kp.chapter_id % 11) * 0.25
            y = _hash_to_axis(node_id, "ky") * 1.1
            z = _hash_to_axis(node_id, "kz") * 1.0 + math.tanh(float(kp.prerequisite_level or 0.0))
            embedding_out.nodes.append(
                schemas.RagGraphEmbeddingNodeOut(
                    id=node_id,
                    label=f"{kp.kp_code} {kp.name}".strip(),
                    node_type="knowledge_point",
                    x=round(x, 6),
                    y=round(y, 6),
                    z=round(z, 6),
                    prerequisite_level=float(kp.prerequisite_level or 0.0),
                    relation_strength=0.0,
                    heat=0.0,
                    created_at_ts=int(kp.created_at.timestamp()) if kp.created_at else 0,
                    meta={
                        "chapter_id": kp.chapter_id,
                        "difficulty": kp.difficulty,
                        "status": kp.status,
                        "aliases": kp.aliases or [],
                    },
                )
            )
            existing_node_ids.add(node_id)
            chapter_node_id = f"chapter:{kp.chapter_id}"
            if chapter_node_id in existing_node_ids:
                embedding_out.edges.append(
                    schemas.RagGraphEdgeOut(
                        source=chapter_node_id,
                        target=node_id,
                        edge_type="contains",
                        weight=1.0,
                    )
                )

        if kp_node_ids:
            edge_rows = (
                db.query(models.KnowledgeEdge)
                .filter(
                    models.KnowledgeEdge.src_kp_id.in_(list(kp_node_ids.keys())),
                    models.KnowledgeEdge.dst_kp_id.in_(list(kp_node_ids.keys())),
                )
                .limit(5000)
                .all()
            )
            for edge in edge_rows:
                src_id = kp_node_ids.get(edge.src_kp_id)
                dst_id = kp_node_ids.get(edge.dst_kp_id)
                if not src_id or not dst_id:
                    continue
                embedding_out.edges.append(
                    schemas.RagGraphEdgeOut(
                        source=src_id,
                        target=dst_id,
                        edge_type=edge.edge_type,
                        weight=float(edge.strength or 0.5),
                    )
                )

    return embedding_out


@router.get("/workspaces/{workspace_id}/jobs", response_model=list[schemas.RagJobOut])
def workspace_jobs(
    workspace_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    _ensure_workspace(db, workspace_id)
    rows = (
        db.query(models.RagExtractionJob)
        .filter(models.RagExtractionJob.workspace_id == workspace_id)
        .order_by(models.RagExtractionJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [schemas.RagJobOut.model_validate(row) for row in rows]


@router.get(
    "/workspaces/{workspace_id}/bootstrap-jobs/{job_id}",
    response_model=schemas.RagBootstrapJobOut,
)
def workspace_bootstrap_job(
    workspace_id: int,
    job_id: int,
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    _ensure_workspace(db, workspace_id)
    job = (
        db.query(models.RagExtractionJob)
        .filter(
            models.RagExtractionJob.id == job_id,
            models.RagExtractionJob.workspace_id == workspace_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Bootstrap job not found")
    return _serialize_bootstrap_job(job)


@router.get(
    "/workspaces/{workspace_id}/bootstrap-jobs/{job_id}/errors",
    response_model=schemas.RagBootstrapJobErrorsOut,
)
def workspace_bootstrap_job_errors(
    workspace_id: int,
    job_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    _ensure_workspace(db, workspace_id)
    job = (
        db.query(models.RagExtractionJob)
        .filter(
            models.RagExtractionJob.id == job_id,
            models.RagExtractionJob.workspace_id == workspace_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Bootstrap job not found")

    failed_sources = bootstrap_service.job_failed_sources(job)
    total = len(failed_sources)
    start = (page - 1) * page_size
    end = start + page_size
    items = [schemas.RagBootstrapErrorOut(**item) for item in failed_sources[start:end]]

    return schemas.RagBootstrapJobErrorsOut(
        job_id=job.id,
        status=job.status,
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/workspaces/{workspace_id}/qa/logs", response_model=list[schemas.RagQaLogOut])
def workspace_qa_logs(
    workspace_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_read),
    _: models.User = Depends(get_current_user),
):
    _ensure_workspace(db, workspace_id)
    rows = (
        db.query(models.RagQaLog)
        .filter(models.RagQaLog.workspace_id == workspace_id)
        .order_by(models.RagQaLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [schemas.RagQaLogOut.model_validate(row) for row in rows]


@router.post("/workspaces/{workspace_id}/sources/{source_id}/publish", response_model=schemas.RagPublishSourceOut)
def publish_workspace_source(
    workspace_id: int,
    source_id: int,
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    if not _can_manage_workspace(current_user):
        raise HTTPException(status_code=403, detail="Teacher/Admin only")

    workspace = _ensure_workspace(db, workspace_id)
    source = (
        db.query(models.RagSource)
        .filter(models.RagSource.id == source_id, models.RagSource.workspace_id == workspace.id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    resource = None
    if source.resource_id:
        resource = db.query(models.Resource).filter(models.Resource.id == source.resource_id).first()
    elif source.published_resource_id:
        resource = db.query(models.Resource).filter(models.Resource.id == source.published_resource_id).first()

    if resource is None:
        resource = models.Resource(
            title=source.title,
            description=source.summary_text,
            type="document",
            subject=workspace.subject,
            grade=None,
            tags=source.tags or [],
            status=models.ResourceStatus.pending,
            resource_kind="tutorial",
            file_format=source.file_format or "other",
            difficulty=None,
            section_id=None,
            storage_provider=models.StorageProvider.minio if source.object_key else models.StorageProvider.local,
            object_key=source.object_key,
            chapter_id=None,
            author_id=current_user.id,
            file_path=None,
        )
        db.add(resource)
        db.flush()

        source.published_resource_id = resource.id
        source.resource_id = resource.id
        source.status = "published"
        source.canonical_key = resource_variants.build_canonical_key(
            resource_id=resource.id,
            object_key=resource.object_key,
        )
        source.variant_kind = resource_variants.guess_variant_kind_from_object_key(
            resource.object_key,
            resource.file_format,
        )
        source.is_graph_visible = True
        source.display_priority = resource_variants.variant_priority(source.variant_kind)
        db.add(source)
        if resource.object_key:
            resource_variants.ensure_resource_origin_variant(db, resource)
        db.commit()
        rag_cache.invalidate_graph_cache(f"workspace:{workspace.id}:")
        db.refresh(resource)
        db.refresh(source)
    else:
        source.canonical_key = resource_variants.build_canonical_key(
            resource_id=resource.id,
            object_key=resource.object_key,
        )
        source.variant_kind = resource_variants.guess_variant_kind_from_object_key(
            resource.object_key,
            resource.file_format,
        )
        source.is_graph_visible = True
        source.display_priority = resource_variants.variant_priority(source.variant_kind)
        db.add(source)
        if resource.object_key:
            resource_variants.ensure_resource_origin_variant(db, resource)
        db.commit()
        rag_cache.invalidate_graph_cache(f"workspace:{workspace.id}:")
        db.refresh(source)

    return schemas.RagPublishSourceOut(source=_to_source_out(source), resource=to_resource_out(resource))


@router.get("/graph", response_model=schemas.RagGraphOut)
def rag_graph_compat(
    stage: str = Query(default="senior"),
    subject: str = Query(default="物理"),
    q: str | None = Query(default=None),
    limit: int = Query(default=240, ge=40, le=800),
    scope: str = Query(default=RAG_GRAPH_SCOPE_PUBLIC, pattern="^(public|mixed)$"),
    include_format_nodes: bool = Query(default=True),
    dedupe: bool = Query(default=True),
    include_variants: bool = Query(default=True),
    db: Session = Depends(get_db_write),
    current_user: models.User = Depends(get_current_user),
):
    # Compatibility endpoint: map to a default workspace for one version cycle.
    workspace = (
        db.query(models.RagWorkspace)
        .filter(
            models.RagWorkspace.stage == stage,
            models.RagWorkspace.subject == subject,
        )
        .order_by(models.RagWorkspace.updated_at.desc())
        .first()
    )

    if workspace is None:
        workspace = models.RagWorkspace(
            name="默认工作台",
            description="兼容 /api/rag/graph 自动创建",
            stage=stage,
            subject=subject,
            created_by=current_user.id,
        )
        db.add(workspace)
        db.flush()

    has_source = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id == workspace.id,
            models.RagSource.status != rag_sync.RAG_SOURCE_STATUS_INACTIVE,
        )
        .first()
        is not None
    )
    if not has_source:
        resources = (
            db.query(models.Resource)
            .filter(
                models.Resource.status == models.ResourceStatus.approved,
                models.Resource.is_trashed.is_(False),
                models.Resource.subject == subject,
            )
            .order_by(models.Resource.updated_at.desc())
            .limit(180)
            .all()
        )
        for resource in resources:
            db.add(
                models.RagSource(
                    workspace_id=workspace.id,
                    source_type="resource",
                    resource_id=resource.id,
                    title=resource.title,
                    object_key=resource.object_key,
                    file_format=resource.file_format,
                    summary_text=resource.ai_summary or resource.description,
                    tags=list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or []))),
                    embedding_json=resource.embedding_json if isinstance(resource.embedding_json, list) else None,
                    status="ready",
                    canonical_key=resource_variants.build_canonical_key(
                        resource_id=resource.id,
                        object_key=resource.object_key,
                    ),
                    variant_kind=resource_variants.guess_variant_kind_from_object_key(
                        resource.object_key,
                        resource.file_format,
                    ),
                    is_graph_visible=True,
                    display_priority=resource_variants.variant_priority(resource_variants.VARIANT_KIND_ORIGIN),
                    created_by=current_user.id,
                )
            )

    db.commit()
    db.refresh(workspace)
    return _build_workspace_graph(
        db,
        workspace,
        q=q,
        limit=limit,
        scope=scope,
        include_format_nodes=include_format_nodes,
        dedupe=dedupe,
        include_variants=include_variants,
        access_user_id=current_user.id,
    )
