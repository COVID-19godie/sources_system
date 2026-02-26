from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import models
from app.core.security import decode_access_token
from app.core.db_read_write import ReadSessionLocal, WriteSessionLocal


bearer_scheme = HTTPBearer(auto_error=False)


def get_db_write():
    db = WriteSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_read():
    db = ReadSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_auth_payload_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict | None:
    if credentials is None:
        return None
    return decode_access_token(credentials.credentials)


def get_current_user_optional(
    payload: dict | None = Depends(get_auth_payload_optional),
    db: Session = Depends(get_db_write),
) -> models.User | None:
    if payload is None:
        return None

    email = payload.get("sub")
    if not email:
        return None

    return db.query(models.User).filter(models.User.email == email).first()


def get_current_user(
    current_user: models.User | None = Depends(get_current_user_optional),
) -> models.User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    return current_user


def get_current_admin(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if current_user.role != models.UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only",
        )
    return current_user
