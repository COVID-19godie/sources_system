from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app import models


VARIANT_KIND_ORIGIN = "origin"
VARIANT_KIND_PREVIEW_PDF = "preview_pdf"
VARIANT_KIND_DERIVED = "derived"
VARIANT_KIND_UPLOAD = "upload"

_ALLOWED_VARIANT_KINDS = {
    VARIANT_KIND_ORIGIN,
    VARIANT_KIND_PREVIEW_PDF,
    VARIANT_KIND_DERIVED,
    VARIANT_KIND_UPLOAD,
}


def normalize_variant_kind(value: str | None, *, fallback: str = VARIANT_KIND_UPLOAD) -> str:
    key = (value or "").strip().lower()
    if key in _ALLOWED_VARIANT_KINDS:
        return key
    return fallback


def object_hash_key(object_key: str | None) -> str:
    normalized = (object_key or "").strip().lstrip("/").lower()
    if not normalized:
        return "unknown"
    digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:24]


def preview_pdf_origin_key(object_key: str | None) -> str | None:
    normalized = (object_key or "").strip().lstrip("/")
    lower = normalized.lower()
    if not lower.startswith("legacy-previews/"):
        return None
    raw = normalized[len("legacy-previews/") :]
    if raw.lower().endswith(".pdf"):
        raw = raw[:-4]
    origin = raw.strip().lstrip("/")
    return origin or None


def build_canonical_key(
    *,
    resource_id: int | None = None,
    object_key: str | None = None,
    variant_kind: str | None = None,
) -> str:
    if resource_id:
        return f"resource:{resource_id}"
    normalized_key = (object_key or "").strip().lstrip("/")
    normalized_kind = normalize_variant_kind(variant_kind, fallback=VARIANT_KIND_ORIGIN)
    if normalized_kind == VARIANT_KIND_PREVIEW_PDF:
        normalized_key = preview_pdf_origin_key(normalized_key) or normalized_key
    return f"object:{object_hash_key(normalized_key)}"


def canonical_node_id(canonical_key: str) -> str:
    return f"canonical:{canonical_key.replace(':', '_')}"


def guess_variant_kind_from_object_key(object_key: str | None, file_format: str | None = None) -> str:
    normalized = (object_key or "").strip().lower()
    if normalized.startswith("legacy-previews/"):
        return VARIANT_KIND_PREVIEW_PDF
    if normalized.startswith("versions/"):
        return VARIANT_KIND_DERIVED
    if (file_format or "").lower() == "pdf" and "/preview" in normalized:
        return VARIANT_KIND_PREVIEW_PDF
    return VARIANT_KIND_ORIGIN


def variant_priority(variant_kind: str | None) -> int:
    key = normalize_variant_kind(variant_kind)
    if key == VARIANT_KIND_ORIGIN:
        return 100
    if key == VARIANT_KIND_DERIVED:
        return 90
    if key == VARIANT_KIND_UPLOAD:
        return 80
    if key == VARIANT_KIND_PREVIEW_PDF:
        return 10
    return 60


def auto_open_variant_kind(variant_kinds: Iterable[str], *, primary_file_format: str | None = None) -> str:
    kinds = {normalize_variant_kind(item, fallback=VARIANT_KIND_UPLOAD) for item in variant_kinds}
    format_key = (primary_file_format or "").strip().lower()
    if format_key in {"ppt", "word", "excel"} and VARIANT_KIND_PREVIEW_PDF in kinds:
        return VARIANT_KIND_PREVIEW_PDF
    if VARIANT_KIND_ORIGIN in kinds:
        return VARIANT_KIND_ORIGIN
    if VARIANT_KIND_DERIVED in kinds:
        return VARIANT_KIND_DERIVED
    if VARIANT_KIND_UPLOAD in kinds:
        return VARIANT_KIND_UPLOAD
    if VARIANT_KIND_PREVIEW_PDF in kinds:
        return VARIANT_KIND_PREVIEW_PDF
    return VARIANT_KIND_UPLOAD


def upsert_resource_file_variant(
    db: Session,
    *,
    resource_id: int,
    object_key: str,
    variant_kind: str,
    file_format: str | None,
    mime_type: str | None = None,
    is_primary: bool = False,
    is_graph_visible: bool = True,
    derived_from_variant_id: int | None = None,
) -> models.ResourceFileVariant:
    normalized_key = object_key.strip().lstrip("/")
    row = (
        db.query(models.ResourceFileVariant)
        .filter(models.ResourceFileVariant.object_key == normalized_key)
        .first()
    )
    if row is None:
        row = models.ResourceFileVariant(
            resource_id=resource_id,
            object_key=normalized_key,
            variant_kind=normalize_variant_kind(variant_kind),
            file_format=(file_format or None),
            mime_type=(mime_type or None),
            is_primary=is_primary,
            is_graph_visible=is_graph_visible,
            derived_from_variant_id=derived_from_variant_id,
        )
        db.add(row)
        db.flush()
    else:
        row.resource_id = resource_id
        row.variant_kind = normalize_variant_kind(variant_kind)
        row.file_format = file_format or row.file_format
        row.mime_type = mime_type or row.mime_type
        row.is_primary = bool(is_primary)
        row.is_graph_visible = bool(is_graph_visible)
        row.derived_from_variant_id = derived_from_variant_id
        db.add(row)

    if is_primary:
        (
            db.query(models.ResourceFileVariant)
            .filter(
                models.ResourceFileVariant.resource_id == resource_id,
                models.ResourceFileVariant.id != row.id,
                models.ResourceFileVariant.is_primary.is_(True),
            )
            .update({"is_primary": False}, synchronize_session=False)
        )
    return row


def ensure_resource_origin_variant(db: Session, resource: models.Resource) -> models.ResourceFileVariant | None:
    if not resource.object_key:
        return None
    file_format = resource.file_format
    return upsert_resource_file_variant(
        db,
        resource_id=resource.id,
        object_key=resource.object_key,
        variant_kind=VARIANT_KIND_ORIGIN,
        file_format=file_format,
        is_primary=True,
        is_graph_visible=True,
    )


def ensure_resource_preview_pdf_variant(
    db: Session,
    *,
    resource: models.Resource,
    preview_key: str,
) -> models.ResourceFileVariant | None:
    if not preview_key:
        return None
    origin_variant = (
        db.query(models.ResourceFileVariant)
        .filter(
            models.ResourceFileVariant.resource_id == resource.id,
            models.ResourceFileVariant.is_primary.is_(True),
        )
        .first()
    )
    return upsert_resource_file_variant(
        db,
        resource_id=resource.id,
        object_key=preview_key,
        variant_kind=VARIANT_KIND_PREVIEW_PDF,
        file_format="pdf",
        mime_type="application/pdf",
        is_primary=False,
        is_graph_visible=False,
        derived_from_variant_id=origin_variant.id if origin_variant else None,
    )


def clean_variant_title(title: str | None, object_key: str | None) -> str:
    text = (title or "").strip()
    if text:
        return text
    name = Path(object_key or "").name
    return name or "资源"
