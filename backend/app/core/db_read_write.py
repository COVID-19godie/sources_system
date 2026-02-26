from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _engine_options() -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": max(1, settings.DB_POOL_SIZE),
        "max_overflow": max(0, settings.DB_MAX_OVERFLOW),
        "pool_timeout": max(1, settings.DB_POOL_TIMEOUT),
        "pool_recycle": max(30, settings.DB_POOL_RECYCLE),
    }


write_engine = create_engine(settings.DATABASE_WRITE_URL, **_engine_options())
read_engine = create_engine(settings.DATABASE_READ_URL, **_engine_options())

WriteSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=write_engine)
ReadSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=read_engine)
