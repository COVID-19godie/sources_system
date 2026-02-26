import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserRole(str, enum.Enum):
    teacher = "teacher"
    admin = "admin"


class ResourceStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    hidden = "hidden"


class StorageProvider(str, enum.Enum):
    local = "local"
    minio = "minio"


class MineruJobStatus(str, enum.Enum):
    submitted = "submitted"
    processing = "processing"
    done = "done"
    failed = "failed"
    materialized = "materialized"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_constraint=True),
        default=UserRole.teacher,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    resources: Mapped[list["Resource"]] = relationship(
        back_populates="author",
        foreign_keys="Resource.author_id",
    )
    reviewed_resources: Mapped[list["Resource"]] = relationship(
        back_populates="reviewer",
        foreign_keys="Resource.reviewer_id",
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint(
            "subject", "volume_code", "chapter_code", name="uq_chapters_subject_volume_code"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    grade: Mapped[str] = mapped_column(String(30), nullable=False)
    textbook: Mapped[str | None] = mapped_column(String(120), nullable=True)
    volume_code: Mapped[str] = mapped_column(String(20), default="bx1", nullable=False)
    volume_name: Mapped[str] = mapped_column(String(50), default="必修第一册", nullable=False)
    volume_order: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    chapter_order: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    chapter_code: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    index_embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    index_embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    index_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    resources: Mapped[list["Resource"]] = relationship(back_populates="chapter")
    resource_links: Mapped[list["ResourceChapterLink"]] = relationship(
        back_populates="chapter"
    )
    aliases: Mapped[list["ChapterAlias"]] = relationship(back_populates="chapter")


class ChapterAlias(Base):
    __tablename__ = "chapter_aliases"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_pattern: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    pattern_type: Mapped[str] = mapped_column(String(20), nullable=False, default="keyword")
    target_chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chapter: Mapped["Chapter"] = relationship(back_populates="aliases")


class ResourceSection(Base):
    __tablename__ = "resource_sections"
    __table_args__ = (
        UniqueConstraint("stage", "subject", "code", name="uq_resource_sections_scope_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    resources: Mapped[list["Resource"]] = relationship(back_populates="section")


class ResourceTag(Base):
    __tablename__ = "resource_tags"
    __table_args__ = (
        UniqueConstraint("stage", "subject", "tag", name="uq_resource_tags_scope_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    tag: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    status: Mapped[ResourceStatus] = mapped_column(
        Enum(ResourceStatus, name="resource_status", create_constraint=True),
        default=ResourceStatus.pending,
        nullable=False,
    )
    resource_kind: Mapped[str] = mapped_column(String(30), default="tutorial", nullable=False)
    file_format: Mapped[str] = mapped_column(String(30), default="other", nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_sections.id"),
        nullable=True,
    )
    volume_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_auto_generated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rename_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    storage_provider: Mapped[StorageProvider] = mapped_column(
        Enum(StorageProvider, name="storage_provider", create_constraint=True),
        default=StorageProvider.local,
        nullable=False,
    )
    object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_trashed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trashed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    trash_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    original_object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trash_object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trash_has_binary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chapter: Mapped["Chapter | None"] = relationship(back_populates="resources")
    section: Mapped["ResourceSection | None"] = relationship(back_populates="resources")
    author: Mapped["User"] = relationship(
        back_populates="resources",
        foreign_keys=[author_id],
    )
    reviewer: Mapped["User"] = relationship(
        back_populates="reviewed_resources",
        foreign_keys=[reviewer_id],
    )
    chapter_links: Mapped[list["ResourceChapterLink"]] = relationship(
        back_populates="resource"
    )
    file_variants: Mapped[list["ResourceFileVariant"]] = relationship(
        back_populates="resource"
    )
    trash_items: Mapped[list["TrashItem"]] = relationship(back_populates="resource")


class ResourceFileVariant(Base):
    __tablename__ = "resource_file_variants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    variant_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="origin")
    file_format: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_graph_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    derived_from_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_file_variants.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    resource: Mapped["Resource"] = relationship(back_populates="file_variants")
    derived_from: Mapped["ResourceFileVariant | None"] = relationship(
        remote_side="ResourceFileVariant.id",
        foreign_keys=[derived_from_variant_id],
    )


class ResourceChapterLink(Base):
    __tablename__ = "resource_chapter_links"
    __table_args__ = (
        UniqueConstraint("resource_id", "chapter_id", name="uq_resource_chapter_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    resource: Mapped["Resource"] = relationship(back_populates="chapter_links")
    chapter: Mapped["Chapter"] = relationship(back_populates="resource_links")


class TrashItem(Base):
    __tablename__ = "trash_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    original_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    trash_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    has_binary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    resource: Mapped["Resource | None"] = relationship(back_populates="trash_items")


class MineruJob(Base):
    __tablename__ = "mineru_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    batch_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    status: Mapped[MineruJobStatus] = mapped_column(
        Enum(MineruJobStatus, name="mineru_job_status", create_constraint=True),
        default=MineruJobStatus.submitted,
        nullable=False,
    )
    parse_options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    official_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    markdown_object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    markdown_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_create_resource: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    resource: Mapped["Resource | None"] = relationship(foreign_keys=[resource_id])


class RagWorkspace(Base):
    __tablename__ = "rag_workspaces"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(String(30), default="senior", nullable=False)
    subject: Mapped[str] = mapped_column(String(50), default="物理", nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sources: Mapped[list["RagSource"]] = relationship(back_populates="workspace")
    chunks: Mapped[list["RagChunk"]] = relationship(back_populates="workspace")
    entities: Mapped[list["RagEntity"]] = relationship(back_populates="workspace")
    relations: Mapped[list["RagRelation"]] = relationship(back_populates="workspace")
    jobs: Mapped[list["RagExtractionJob"]] = relationship(back_populates="workspace")
    qa_logs: Mapped[list["RagQaLog"]] = relationship(back_populates="workspace")


class RagSource(Base):
    __tablename__ = "rag_sources"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_format: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ready", nullable=False)
    published_resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    canonical_key: Mapped[str | None] = mapped_column(String(190), nullable=True, index=True)
    variant_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_graph_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["RagWorkspace"] = relationship(back_populates="sources")
    resource: Mapped["Resource | None"] = relationship(foreign_keys=[resource_id])
    published_resource: Mapped["Resource | None"] = relationship(foreign_keys=[published_resource_id])
    chunks: Mapped[list["RagChunk"]] = relationship(back_populates="source")
    evidences: Mapped[list["RagEvidence"]] = relationship(back_populates="source")


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "chunk_index", name="uq_rag_chunks_source_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("rag_sources.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    workspace: Mapped["RagWorkspace"] = relationship(back_populates="chunks")
    source: Mapped["RagSource"] = relationship(back_populates="chunks")
    evidences: Mapped[list["RagEvidence"]] = relationship(back_populates="chunk")


class RagEntity(Base):
    __tablename__ = "rag_entities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "entity_type", "canonical_name", name="uq_rag_entities_scope_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["RagWorkspace"] = relationship(back_populates="entities")
    source_relations: Mapped[list["RagRelation"]] = relationship(
        back_populates="source_entity",
        foreign_keys="RagRelation.source_entity_id",
    )
    target_relations: Mapped[list["RagRelation"]] = relationship(
        back_populates="target_entity",
        foreign_keys="RagRelation.target_entity_id",
    )


class RagRelation(Base):
    __tablename__ = "rag_relations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    source_entity_id: Mapped[int] = mapped_column(ForeignKey("rag_entities.id"), nullable=False, index=True)
    target_entity_id: Mapped[int] = mapped_column(ForeignKey("rag_entities.id"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("rag_sources.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    workspace: Mapped["RagWorkspace"] = relationship(back_populates="relations")
    source_entity: Mapped["RagEntity"] = relationship(
        back_populates="source_relations",
        foreign_keys=[source_entity_id],
    )
    target_entity: Mapped["RagEntity"] = relationship(
        back_populates="target_relations",
        foreign_keys=[target_entity_id],
    )
    evidences: Mapped[list["RagRelationEvidence"]] = relationship(back_populates="relation")


class RagEvidence(Base):
    __tablename__ = "rag_evidences"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("rag_sources.id"), nullable=False, index=True)
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("rag_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source: Mapped["RagSource"] = relationship(back_populates="evidences")
    chunk: Mapped["RagChunk | None"] = relationship(back_populates="evidences")
    links: Mapped[list["RagRelationEvidence"]] = relationship(back_populates="evidence")


class RagRelationEvidence(Base):
    __tablename__ = "rag_relation_evidences"
    __table_args__ = (
        UniqueConstraint("relation_id", "evidence_id", name="uq_rag_relation_evidences_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    relation_id: Mapped[int] = mapped_column(ForeignKey("rag_relations.id"), nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("rag_evidences.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    relation: Mapped["RagRelation"] = relationship(back_populates="evidences")
    evidence: Mapped["RagEvidence"] = relationship(back_populates="links")


class RagExtractionJob(Base):
    __tablename__ = "rag_extraction_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("rag_sources.id"), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="quick")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")
    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["RagWorkspace"] = relationship(back_populates="jobs")


class RagQaLog(Base):
    __tablename__ = "rag_qa_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("rag_workspaces.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    highlight_nodes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    highlight_edges: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    workspace: Mapped["RagWorkspace"] = relationship(back_populates="qa_logs")
