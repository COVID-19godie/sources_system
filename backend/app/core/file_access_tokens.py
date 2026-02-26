from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from jose import JWTError, jwt

from app.core.config import settings


class FileAccessTokenError(ValueError):
    pass


DISP_INLINE = "inline"
DISP_ATTACHMENT = "attachment"
_VALID_DISPOSITIONS = {DISP_INLINE, DISP_ATTACHMENT}


def _encode(payload: dict[str, Any], expires_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    data = {
        **payload,
        "iat": now,
        "exp": now + timedelta(seconds=max(30, int(expires_seconds))),
    }
    return jwt.encode(data, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _decode(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as error:
        raise FileAccessTokenError("Invalid or expired file access token") from error
    if not isinstance(payload, dict):
        raise FileAccessTokenError("Invalid file access token payload")
    return payload


def create_storage_file_token(
    *,
    object_key: str,
    disposition: str = DISP_INLINE,
    user_id: int | None = None,
) -> str:
    disp = (disposition or DISP_INLINE).strip().lower()
    if disp not in _VALID_DISPOSITIONS:
        raise FileAccessTokenError("Invalid file disposition")
    return _encode(
        {
            "typ": "storage_file",
            "obj": object_key,
            "disp": disp,
            "uid": user_id,
        },
        settings.FILE_ACCESS_TOKEN_EXPIRE_SECONDS,
    )


def decode_storage_file_token(token: str) -> dict[str, Any]:
    payload = _decode(token)
    if payload.get("typ") != "storage_file":
        raise FileAccessTokenError("Invalid storage file token type")
    if not payload.get("obj"):
        raise FileAccessTokenError("Invalid storage file token object")
    disp = str(payload.get("disp") or DISP_INLINE).strip().lower()
    if disp not in _VALID_DISPOSITIONS:
        raise FileAccessTokenError("Invalid storage file token disposition")
    payload["disp"] = disp
    return payload


def build_storage_file_path(token: str) -> str:
    return f"/api/storage/file/{quote(token, safe='')}"


def build_storage_access_urls(
    *,
    object_key: str,
    user_id: int | None = None,
) -> tuple[str, str]:
    open_token = create_storage_file_token(
        object_key=object_key,
        disposition=DISP_INLINE,
        user_id=user_id,
    )
    download_token = create_storage_file_token(
        object_key=object_key,
        disposition=DISP_ATTACHMENT,
        user_id=user_id,
    )
    return build_storage_file_path(open_token), build_storage_file_path(download_token)
