from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.core import rag_cache, resource_variants


RAG_SOURCE_STATUS_READY = "ready"
RAG_SOURCE_STATUS_INACTIVE = "inactive"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_rag_source_active(status: str | None) -> bool:
    return (status or "").strip().lower() != RAG_SOURCE_STATUS_INACTIVE


def is_resource_rag_eligible(resource: models.Resource | None) -> bool:
    return bool(
        resource
        and not resource.is_trashed
        and resource.status == models.ResourceStatus.approved
    )


def _normalize_resource_ids(resource_ids: list[int]) -> list[int]:
    seen: set[int] = set()
    normalized: list[int] = []
    for raw_id in resource_ids:
        if raw_id <= 0 or raw_id in seen:
            continue
        seen.add(raw_id)
        normalized.append(raw_id)
    return normalized


def _resource_tags(resource: models.Resource) -> list[str]:
    return list(dict.fromkeys((resource.ai_tags or []) + (resource.tags or [])))


def _resource_subject(resource: models.Resource) -> str:
    return (resource.subject or "").strip()


def _mark_source_inactive(source: models.RagSource) -> bool:
    if not is_rag_source_active(source.status):
        return False
    source.status = RAG_SOURCE_STATUS_INACTIVE
    source.updated_at = utc_now()
    return True


def _sync_source_fields(
    source: models.RagSource,
    resource: models.Resource,
    *,
    actor_id: int | None = None,
) -> dict[str, bool]:
    changed = False
    reactivated = False

    if not is_rag_source_active(source.status):
        source.status = RAG_SOURCE_STATUS_READY
        reactivated = True
        changed = True

    title = resource.title
    object_key = resource.object_key
    file_format = resource.file_format
    summary_text = resource.ai_summary or resource.description
    tags = _resource_tags(resource)
    embedding = resource.embedding_json if isinstance(resource.embedding_json, list) else None
    canonical_key = resource_variants.build_canonical_key(
        resource_id=resource.id,
        object_key=resource.object_key,
    )
    variant_kind = resource_variants.guess_variant_kind_from_object_key(
        resource.object_key,
        resource.file_format,
    )
    display_priority = resource_variants.variant_priority(variant_kind)

    if source.title != title:
        source.title = title
        changed = True
    if source.object_key != object_key:
        source.object_key = object_key
        changed = True
    if source.file_format != file_format:
        source.file_format = file_format
        changed = True
    if source.summary_text != summary_text:
        source.summary_text = summary_text
        changed = True
    if (source.tags or []) != tags:
        source.tags = tags
        changed = True
    if source.embedding_json != embedding:
        source.embedding_json = embedding
        changed = True
    if source.canonical_key != canonical_key:
        source.canonical_key = canonical_key
        changed = True
    if source.variant_kind != variant_kind:
        source.variant_kind = variant_kind
        changed = True
    if source.is_graph_visible is not True:
        source.is_graph_visible = True
        changed = True
    if source.display_priority != display_priority:
        source.display_priority = display_priority
        changed = True

    if actor_id and source.created_by <= 0:
        source.created_by = actor_id
        changed = True

    if changed:
        source.updated_at = utc_now()

    return {"changed": changed, "reactivated": reactivated}


def prune_invalid_sources(db: Session, workspace_id: int) -> int:
    rows = (
        db.query(models.RagSource, models.Resource)
        .outerjoin(models.Resource, models.Resource.id == models.RagSource.resource_id)
        .filter(
            models.RagSource.workspace_id == workspace_id,
            models.RagSource.source_type == "resource",
            models.RagSource.resource_id.isnot(None),
        )
        .all()
    )

    pruned_count = 0
    for source, resource in rows:
        if is_resource_rag_eligible(resource):
            continue
        if _mark_source_inactive(source):
            db.add(source)
            pruned_count += 1
    if pruned_count:
        rag_cache.invalidate_graph_cache(f"workspace:{workspace_id}:")
    return pruned_count


def sync_resource_to_workspaces(
    db: Session,
    resource_ids: list[int],
    *,
    actor_id: int | None = None,
    reason: str = "resource_sync",
) -> dict[str, int]:
    normalized_ids = _normalize_resource_ids(resource_ids)
    if not normalized_ids:
        return {
            "requested": 0,
            "created": 0,
            "reactivated": 0,
            "updated": 0,
            "deactivated": 0,
            "skipped": 0,
            "reason": reason,
        }

    resources = (
        db.query(models.Resource)
        .filter(models.Resource.id.in_(normalized_ids))
        .all()
    )
    if not resources:
        return {
            "requested": len(normalized_ids),
            "created": 0,
            "reactivated": 0,
            "updated": 0,
            "deactivated": 0,
            "skipped": len(normalized_ids),
            "reason": reason,
        }

    resource_map = {row.id: row for row in resources}
    subjects = {
        _resource_subject(row)
        for row in resources
        if _resource_subject(row)
    }

    workspace_query = db.query(models.RagWorkspace)
    if subjects:
        workspace_query = workspace_query.filter(models.RagWorkspace.subject.in_(sorted(subjects)))
    workspaces = workspace_query.all()
    if not workspaces:
        return {
            "requested": len(normalized_ids),
            "created": 0,
            "reactivated": 0,
            "updated": 0,
            "deactivated": 0,
            "skipped": len(normalized_ids),
            "reason": reason,
        }

    workspace_ids = [row.id for row in workspaces]
    source_rows = (
        db.query(models.RagSource)
        .filter(
            models.RagSource.workspace_id.in_(workspace_ids),
            models.RagSource.resource_id.in_(normalized_ids),
            models.RagSource.source_type == "resource",
        )
        .order_by(models.RagSource.updated_at.desc(), models.RagSource.id.desc())
        .all()
    )

    source_map: dict[tuple[int, int], list[models.RagSource]] = {}
    for row in source_rows:
        key = (row.workspace_id, row.resource_id or 0)
        source_map.setdefault(key, []).append(row)

    created = 0
    reactivated = 0
    updated = 0
    deactivated = 0
    skipped = 0

    for workspace in workspaces:
        for resource_id in normalized_ids:
            resource = resource_map.get(resource_id)
            if resource is None:
                skipped += 1
                continue

            resource_subject = _resource_subject(resource)
            if resource_subject and resource_subject != workspace.subject:
                continue

            key = (workspace.id, resource.id)
            source_group = source_map.get(key, [])
            primary = source_group[0] if source_group else None
            duplicates = source_group[1:] if len(source_group) > 1 else []

            for duplicate in duplicates:
                if _mark_source_inactive(duplicate):
                    deactivated += 1
                    db.add(duplicate)

            if is_resource_rag_eligible(resource):
                if primary is None:
                    variant_kind = resource_variants.guess_variant_kind_from_object_key(
                        resource.object_key,
                        resource.file_format,
                    )
                    db.add(
                        models.RagSource(
                            workspace_id=workspace.id,
                            source_type="resource",
                            resource_id=resource.id,
                            title=resource.title,
                            object_key=resource.object_key,
                            file_format=resource.file_format,
                            summary_text=resource.ai_summary or resource.description,
                            tags=_resource_tags(resource),
                            embedding_json=resource.embedding_json if isinstance(resource.embedding_json, list) else None,
                            status=RAG_SOURCE_STATUS_READY,
                            canonical_key=resource_variants.build_canonical_key(
                                resource_id=resource.id,
                                object_key=resource.object_key,
                            ),
                            variant_kind=variant_kind,
                            is_graph_visible=True,
                            display_priority=resource_variants.variant_priority(variant_kind),
                            created_by=actor_id or workspace.created_by,
                        )
                    )
                    created += 1
                    continue

                sync_state = _sync_source_fields(primary, resource, actor_id=actor_id)
                if sync_state["reactivated"]:
                    reactivated += 1
                if sync_state["changed"]:
                    updated += 1
                    db.add(primary)
                else:
                    skipped += 1
            else:
                if primary and _mark_source_inactive(primary):
                    deactivated += 1
                    db.add(primary)
                else:
                    skipped += 1

    output = {
        "requested": len(normalized_ids),
        "created": created,
        "reactivated": reactivated,
        "updated": updated,
        "deactivated": deactivated,
        "skipped": skipped,
        "reason": reason,
    }
    if created or reactivated or updated or deactivated:
        rag_cache.invalidate_graph_cache()
    return output
