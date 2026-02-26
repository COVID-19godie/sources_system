from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings


class OfficeTokenError(ValueError):
    pass


def _encode(payload: dict[str, Any], expires_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **payload,
        "iat": now,
        "exp": now + timedelta(seconds=max(30, int(expires_seconds))),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _decode(token: str) -> dict[str, Any]:
    try:
        data = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as error:
        raise OfficeTokenError("Invalid or expired office token") from error
    if not isinstance(data, dict):
        raise OfficeTokenError("Invalid office token payload")
    return data


def create_file_token(
    *,
    object_key: str,
    user_id: int,
    role: str,
    editable: bool,
) -> str:
    return _encode(
        {
            "typ": "office_file",
            "obj": object_key,
            "uid": user_id,
            "role": role,
            "editable": bool(editable),
        },
        settings.OFFICE_FILE_TOKEN_EXPIRE_SECONDS,
    )


def decode_file_token(token: str) -> dict[str, Any]:
    data = _decode(token)
    if data.get("typ") != "office_file":
        raise OfficeTokenError("Invalid office file token type")
    if not data.get("obj"):
        raise OfficeTokenError("Invalid office file token object")
    return data


def create_callback_token(
    *,
    object_key: str,
    editor_id: int,
) -> str:
    return _encode(
        {
            "typ": "office_callback",
            "obj": object_key,
            "eid": editor_id,
        },
        settings.OFFICE_CALLBACK_TOKEN_EXPIRE_SECONDS,
    )


def decode_callback_token(token: str) -> dict[str, Any]:
    data = _decode(token)
    if data.get("typ") != "office_callback":
        raise OfficeTokenError("Invalid office callback token type")
    if not data.get("obj"):
        raise OfficeTokenError("Invalid office callback token object")
    return data
