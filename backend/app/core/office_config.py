import hashlib
from pathlib import Path
from urllib.parse import quote

from app import models, schemas
from app.core.config import settings
from app.core.office_tokens import create_callback_token, create_file_token
from app.core import storage


def _document_type(file_suffix: str) -> str:
    suffix = file_suffix.lower()
    if suffix in {".xls", ".xlsx", ".csv"}:
        return "cell"
    if suffix in {".ppt", ".pptx"}:
        return "slide"
    return "word"


def _docs_key(object_key: str, etag: str | None, size: int | None) -> str:
    seed = f"{object_key}|{etag or ''}|{size or 0}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:40]


def _public_docs_js_url() -> str:
    prefix = settings.ONLYOFFICE_PUBLIC_PATH.strip()
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return f"{prefix.rstrip('/')}/web-apps/apps/api/documents/api.js"


def build_office_config(
    *,
    object_key: str,
    filename: str,
    current_user: models.User,
    editable: bool,
) -> schemas.OfficeConfigOut:
    key = storage.normalize_key(object_key)
    stat = storage.stat_object(key)
    suffix = Path(filename).suffix.lower() or Path(key).suffix.lower()
    file_type = suffix.lstrip(".") or "docx"
    file_token = create_file_token(
        object_key=key,
        user_id=current_user.id,
        role=current_user.role.value,
        editable=editable,
    )
    file_url = f"{settings.ONLYOFFICE_INTERNAL_BASE_URL.rstrip('/')}/api/office/file/{quote(file_token, safe='')}"

    config: dict = {
        "documentType": _document_type(suffix),
        "type": "desktop",
        "document": {
            "title": filename,
            "url": file_url,
            "fileType": file_type,
            "key": _docs_key(key, getattr(stat, "etag", None), getattr(stat, "size", None)),
            "permissions": {
                "edit": bool(editable),
                "download": True,
                "print": True,
                "review": False,
                "comment": False,
                "chat": False,
                "copy": True,
            },
        },
        "editorConfig": {
            "mode": "edit" if editable else "view",
            "lang": "zh-CN",
            "user": {
                "id": str(current_user.id),
                "name": current_user.email,
            },
        },
    }

    if editable:
        callback_token = create_callback_token(object_key=key, editor_id=current_user.id)
        callback_url = (
            f"{settings.ONLYOFFICE_INTERNAL_BASE_URL.rstrip('/')}/api/office/callback/"
            f"{quote(callback_token, safe='')}"
        )
        config["editorConfig"]["callbackUrl"] = callback_url

    return schemas.OfficeConfigOut(
        document_server_js_url=_public_docs_js_url(),
        config=config,
    )
