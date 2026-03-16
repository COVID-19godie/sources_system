from pathlib import Path
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+psycopg://edu_user:edu_pass@db-primary:5432/edu_demo"
    DATABASE_WRITE_URL: str | None = None
    DATABASE_READ_URL: str | None = None
    LOCAL_PREVIEW_MODE: bool = False
    LOCAL_PREVIEW_DB_PATH: str = "preview.db"

    JWT_SECRET_KEY: str = "change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200

    ADMIN_EMAIL: str = "admin"
    ADMIN_PASSWORD: str = "admin123"
    CORS_ORIGINS: str = (
        "http://localhost:8080,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "http://localhost:3000"
    )

    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "edu-resources"
    MINIO_SECURE: bool = False
    DOWNLOAD_URL_EXPIRE_SECONDS: int = 3600
    FILE_ACCESS_TOKEN_EXPIRE_SECONDS: int = 600

    ONLYOFFICE_ENABLED: bool = True
    ONLYOFFICE_INTERNAL_BASE_URL: str = "http://backend:8000"
    ONLYOFFICE_PUBLIC_PATH: str = "/office"
    ONLYOFFICE_CONVERTER_URL: str = "http://onlyoffice/converter"
    ONLYOFFICE_CALLBACK_ALLOWLIST: str = "127.0.0.1,::1,172.,onlyoffice"
    OFFICE_FILE_TOKEN_EXPIRE_SECONDS: int = 600
    OFFICE_CALLBACK_TOKEN_EXPIRE_SECONDS: int = 3600
    OFFICE_VERSION_PREFIX: str = "versions"
    OFFICE_LEGACY_PREVIEW_PREFIX: str = "legacy-previews"
    LIBREOFFICE_TIMEOUT_SECONDS: int = 120
    MINERU_API_BASE_URL: str = "https://mineru.net/api/v4"
    MINERU_API_TOKEN: str | None = None
    MINERU_MODEL_VERSION: str = "MinerU-HTML"
    MINERU_POLL_INTERVAL_SECONDS: int = 2
    MINERU_POLL_TIMEOUT_SECONDS: int = 180
    MINERU_HTTP_TIMEOUT_SECONDS: int = 60

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    AI_CHAT_MODEL: str = "gpt-4o-mini"
    AI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    AI_HTTP_TIMEOUT_SECONDS: int = 60
    AI_AUTO_ENRICH: bool = True
    AI_MAX_SOURCE_CHARS: int = 12000
    AI_RAG_TOP_K: int = 5
    AI_SEMANTIC_ENABLE_ANSWER: bool = False
    SEMANTIC_PGVECTOR_ENABLED: bool = True
    SEMANTIC_DEFAULT_CANDIDATE_LIMIT: int = 320
    SEMANTIC_DEFAULT_RERANK_TOP_K: int = 20
    AUTO_CHAPTER_MIN_SCORE: float = 0.58
    AUTO_CHAPTER_MIN_MARGIN: float = 0.06
    STRICT_PEP_CATALOG: bool = True

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    RAG_CANONICAL_DEDUPE: bool = True
    RAG_GRAPH_VARIANTS: bool = True
    RAG_GRAPH_CACHE_TTL_SECONDS: int = 30

    TRASH_RETENTION_DAYS: int = 30
    TRASH_PREFIX: str = "trash/resources"
    STORAGE_RECONCILE_INTERVAL_SECONDS: int = 300
    TRASH_PURGE_INTERVAL_SECONDS: int = 86400

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def onlyoffice_callback_allowlist(self) -> list[str]:
        return [item.strip() for item in self.ONLYOFFICE_CALLBACK_ALLOWLIST.split(",") if item.strip()]

    @property
    def resolved_database_write_url(self) -> str:
        return self.DATABASE_WRITE_URL or self.DATABASE_URL

    @property
    def resolved_database_read_url(self) -> str:
        return self.DATABASE_READ_URL or self.resolved_database_write_url


settings = Settings()
if settings.LOCAL_PREVIEW_MODE:
    backend_root = Path(__file__).resolve().parents[2]
    default_preview_db = backend_root / settings.LOCAL_PREVIEW_DB_PATH
    preview_db_url = f"sqlite:///{default_preview_db.as_posix()}"
    if not os.getenv("DATABASE_URL"):
        settings.DATABASE_URL = preview_db_url
    if not os.getenv("DATABASE_WRITE_URL"):
        settings.DATABASE_WRITE_URL = settings.DATABASE_URL
    if not os.getenv("DATABASE_READ_URL"):
        settings.DATABASE_READ_URL = settings.DATABASE_URL
    settings.ONLYOFFICE_ENABLED = False
    settings.SEMANTIC_PGVECTOR_ENABLED = False
    settings.STORAGE_RECONCILE_INTERVAL_SECONDS = 0
    settings.TRASH_PURGE_INTERVAL_SECONDS = 0
settings.DATABASE_WRITE_URL = settings.resolved_database_write_url
settings.DATABASE_READ_URL = settings.resolved_database_read_url
