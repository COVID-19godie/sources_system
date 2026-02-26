from datetime import timedelta
from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4

from fastapi import UploadFile
from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error

from app.core.config import settings


def _build_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _object_name(original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    return f"resources/{uuid4().hex}{suffix}"


def _normalize_path_component(raw: str | None, fallback: str = "unassigned") -> str:
    value = (raw or "").strip()
    if not value:
        return fallback
    value = value.replace("\\", "/").strip("/")
    value = value.replace("/", "-")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:120] or fallback


def _normalize_filename_component(raw: str | None, fallback: str = "resource") -> str:
    value = (raw or "").strip()
    if not value:
        return fallback
    value = value.replace("\\", "-").replace("/", "-")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-_")
    return value[:80] or fallback


def build_resource_object_prefix(
    chapter_code: str | None,
    section_code: str | None,
    volume_code: str | None = None,
    *,
    low_confidence: bool = False,
) -> str:
    volume = _normalize_path_component(volume_code, fallback="unassigned") if volume_code else None
    section = _normalize_path_component(section_code, fallback="general") if section_code else "general"
    chapter = _normalize_path_component(chapter_code) if chapter_code else None

    if volume:
        if chapter and not low_confidence:
            return f"resources/{volume}/{chapter}/{section}/"
        return f"resources/{volume}/unassigned/{section}/"

    if chapter and section_code and not low_confidence:
        return f"resources/{chapter}/{section}/"

    return "resources/unassigned/"


def build_resource_object_key(
    filename: str,
    chapter_code: str | None,
    section_code: str | None,
    volume_code: str | None = None,
    *,
    base_name: str | None = None,
    low_confidence: bool = False,
    short_id: str | None = None,
) -> str:
    suffix = Path(filename).suffix.lower()
    prefix = build_resource_object_prefix(
        chapter_code,
        section_code,
        volume_code,
        low_confidence=low_confidence,
    )
    if base_name:
        clean = _normalize_filename_component(base_name, fallback="resource")
        rid = (short_id or uuid4().hex[:4]).strip()[:8]
        return f"{prefix}{clean}-{rid}{suffix}"
    return f"{prefix}{uuid4().hex}{suffix}"


def normalize_prefix(prefix: str | None) -> str:
    value = (prefix or "").strip().lstrip("/")
    if value and not value.endswith("/"):
        value = f"{value}/"
    return value


def normalize_key(object_key: str) -> str:
    value = object_key.strip().lstrip("/")
    if not value:
        raise ValueError("Invalid object key")
    return value


def upload_file(file: UploadFile, object_key: str | None = None) -> tuple[str, str]:
    if not file.filename:
        raise ValueError("Invalid file")

    client = _build_client()
    key = normalize_key(object_key) if object_key else _object_name(file.filename)

    payload = file.file.read()
    file_size = len(payload)
    file.file.seek(0)

    content_type = file.content_type or "application/octet-stream"

    client.put_object(
        settings.MINIO_BUCKET,
        key,
        BytesIO(payload),
        length=file_size,
        content_type=content_type,
    )

    return key, content_type


def object_exists(object_key: str) -> bool:
    client = _build_client()
    key = normalize_key(object_key)
    try:
        client.stat_object(settings.MINIO_BUCKET, key)
        return True
    except S3Error as error:
        code = (error.code or "").lower()
        if code in {"nosuchkey", "nosuchobject", "notfound"}:
            return False
        raise


def list_objects(prefix: str = "", recursive: bool = False):
    client = _build_client()
    normalized = normalize_prefix(prefix)
    return list(
        client.list_objects(
            settings.MINIO_BUCKET,
            prefix=normalized,
            recursive=recursive,
        )
    )


def stat_object(object_key: str):
    client = _build_client()
    key = normalize_key(object_key)
    return client.stat_object(settings.MINIO_BUCKET, key)


def create_folder(prefix: str, folder_name: str) -> str:
    clean_name = folder_name.strip().strip("/")
    if not clean_name:
        raise ValueError("Folder name is required")

    object_key = f"{normalize_prefix(prefix)}{clean_name}/"
    upload_bytes(b"", object_key, content_type="application/x-directory")
    return object_key


def _build_unique_object_key(prefix: str, original_name: str) -> str:
    base_name = Path(original_name).name
    stem = Path(base_name).stem
    suffix = Path(base_name).suffix

    candidate = f"{normalize_prefix(prefix)}{base_name}"
    counter = 1
    while object_exists(candidate):
        candidate = f"{normalize_prefix(prefix)}{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def upload_file_to_prefix(file: UploadFile, prefix: str = "") -> tuple[str, int, str]:
    if not file.filename:
        raise ValueError("Invalid file")

    object_key = _build_unique_object_key(prefix, file.filename)
    payload = file.file.read()
    file_size = len(payload)
    content_type = file.content_type or "application/octet-stream"
    upload_bytes(payload, object_key, content_type=content_type)
    file.file.seek(0)
    return object_key, file_size, content_type


def upload_bytes(
    payload: bytes,
    object_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    client = _build_client()
    client.put_object(
        settings.MINIO_BUCKET,
        object_key,
        BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )
    return object_key


def upload_file_from_path(
    object_key: str,
    source_path: Path,
    content_type: str = "application/octet-stream",
) -> None:
    client = _build_client()
    client.fput_object(
        settings.MINIO_BUCKET,
        object_key,
        str(source_path),
        content_type=content_type,
    )


def build_download_url(object_key: str) -> str:
    client = _build_client()
    key = normalize_key(object_key)
    return client.presigned_get_object(
        settings.MINIO_BUCKET,
        key,
        expires=timedelta(seconds=settings.DOWNLOAD_URL_EXPIRE_SECONDS),
    )


def delete_object(object_key: str) -> None:
    client = _build_client()
    key = normalize_key(object_key)
    client.remove_object(settings.MINIO_BUCKET, key)


def delete_prefix(prefix: str) -> int:
    normalized = normalize_prefix(prefix)
    deleted = 0
    for item in list_objects(prefix=normalized, recursive=True):
        delete_object(item.object_name)
        deleted += 1

    if object_exists(normalized):
        delete_object(normalized)
        deleted += 1

    return deleted


def copy_object(source_key: str, target_key: str) -> None:
    client = _build_client()
    source = normalize_key(source_key)
    target = normalize_key(target_key)
    client.copy_object(
        settings.MINIO_BUCKET,
        target,
        CopySource(settings.MINIO_BUCKET, source),
    )


def get_object_bytes(object_key: str, max_bytes: int | None = None) -> bytes:
    client = _build_client()
    key = normalize_key(object_key)
    response = client.get_object(settings.MINIO_BUCKET, key)
    try:
        if max_bytes is None:
            data = response.read()
        else:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("Object too large for preview")
    finally:
        response.close()
        response.release_conn()

    return data


def get_object_stream(object_key: str):
    client = _build_client()
    key = normalize_key(object_key)
    return client.get_object(settings.MINIO_BUCKET, key)


def get_object_text(object_key: str, max_bytes: int = 1_000_000) -> str:
    try:
        data = get_object_bytes(object_key, max_bytes=max_bytes)
    except ValueError:
        data = get_object_bytes(object_key, max_bytes=None)[:max_bytes]
    return data.decode("utf-8", errors="ignore")


def healthcheck_minio() -> bool:
    client = _build_client()
    try:
        return client.bucket_exists(settings.MINIO_BUCKET)
    except S3Error:
        return False
