from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from minio.error import S3Error
import requests

from app import schemas
from app.core import storage
from app.core.config import settings
from app.core.office_tokens import OfficeTokenError, decode_callback_token, decode_file_token


router = APIRouter(tags=["office"])
OFFICE_SCRIPT_CHECK_URL = "http://onlyoffice/web-apps/apps/api/documents/api.js"


def _is_host_allowed(host: str | None) -> bool:
    value = (host or "").strip()
    if not value:
        return False
    for rule in settings.onlyoffice_callback_allowlist:
        if value == rule or value.startswith(rule):
            return True
    return False


def _build_version_key(source_key: str, editor_id: int) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base_name = Path(source_key).name
    prefix = settings.OFFICE_VERSION_PREFIX.strip().strip("/")
    return f"{prefix}/{source_key}/{ts}_{editor_id}_{base_name}"


@router.get("/health", response_model=schemas.OfficeHealthOut)
def office_health():
    if not settings.ONLYOFFICE_ENABLED:
        return schemas.OfficeHealthOut(available=False, reason="OnlyOffice is disabled", script_url=None)
    try:
        response = requests.get(OFFICE_SCRIPT_CHECK_URL, timeout=5)
        if response.status_code >= 400:
            return schemas.OfficeHealthOut(
                available=False,
                reason=f"office script upstream {response.status_code}",
                script_url=OFFICE_SCRIPT_CHECK_URL,
            )
        return schemas.OfficeHealthOut(available=True, script_url=OFFICE_SCRIPT_CHECK_URL)
    except requests.RequestException as error:
        return schemas.OfficeHealthOut(
            available=False,
            reason=f"office script check failed: {error}",
            script_url=OFFICE_SCRIPT_CHECK_URL,
        )


@router.api_route("/file/{token}", methods=["GET", "HEAD"])
def read_file(token: str):
    try:
        payload = decode_file_token(token)
        object_key = storage.normalize_key(str(payload["obj"]))
    except OfficeTokenError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        stat = storage.stat_object(object_key)
        data = storage.get_object_bytes(object_key, max_bytes=None)
    except S3Error as error:
        raise HTTPException(status_code=404, detail=f"File not found: {error.code}") from error

    content_type = getattr(stat, "content_type", None) or "application/octet-stream"
    filename = Path(object_key).name
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/callback/{token}", response_model=schemas.OfficeCallbackAckOut)
async def callback(token: str, request: Request):
    host = request.client.host if request.client else ""
    if not _is_host_allowed(host):
        raise HTTPException(status_code=403, detail="OnlyOffice callback source not allowed")

    try:
        payload = decode_callback_token(token)
        object_key = storage.normalize_key(str(payload["obj"]))
        editor_id = int(payload.get("eid") or 0)
    except OfficeTokenError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    body = await request.json()
    status_code = int(body.get("status") or 0)

    # 2 = MustSave, 6 = ForceSave
    if status_code not in {2, 6}:
        return schemas.OfficeCallbackAckOut(error=0, message="No save action")

    download_url = str(body.get("url") or "").strip()
    if not download_url:
        return schemas.OfficeCallbackAckOut(error=1, message="Missing callback download url")

    try:
        source_stat = storage.stat_object(object_key)
    except S3Error as error:
        raise HTTPException(status_code=404, detail=f"Source object not found: {error.code}") from error

    try:
        response = requests.get(
            download_url,
            timeout=max(10, settings.LIBREOFFICE_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        updated_payload = response.content
    except requests.RequestException as error:
        return schemas.OfficeCallbackAckOut(error=1, message=f"Download callback file failed: {error}")

    if not updated_payload:
        return schemas.OfficeCallbackAckOut(error=1, message="Callback file is empty")

    try:
        version_key = _build_version_key(object_key, editor_id)
        storage.copy_object(object_key, version_key)
        content_type = getattr(source_stat, "content_type", None) or "application/octet-stream"
        storage.upload_bytes(updated_payload, object_key, content_type=content_type)
    except S3Error as error:
        return schemas.OfficeCallbackAckOut(error=1, message=f"Storage write failed: {error.code}")

    return schemas.OfficeCallbackAckOut(error=0, message="Saved")
