import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import MineruJobStatus, ResourceStatus, StorageProvider, UserRole


RESOURCE_KIND_VALUES = {
    "tutorial",
    "thinking",
    "interdisciplinary",
    "experiment",
    "exercise",
    "exam",
    "simulation",
    "lab",
    "reading",
    "project",
}
FILE_FORMAT_VALUES = {"markdown", "html", "pdf", "video", "image", "audio", "word", "excel", "ppt", "other"}
SECTION_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
RESERVED_SECTION_CODES = {"unassigned", "general", "trash", "versions", "legacy-previews"}


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    email: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    created_at: datetime


class ChapterCreateRequest(BaseModel):
    stage: str
    subject: str
    grade: str
    textbook: str | None = None
    volume_code: str = Field(default="bx1", min_length=1, max_length=20)
    volume_name: str = Field(default="必修第一册", min_length=1, max_length=50)
    volume_order: int = 10
    chapter_order: int = 10
    chapter_code: str
    chapter_keywords: list[str] = Field(default_factory=list)
    title: str


class ChapterUpdateRequest(BaseModel):
    textbook: str | None = None
    grade: str | None = None
    volume_code: str | None = Field(default=None, min_length=1, max_length=20)
    volume_name: str | None = Field(default=None, min_length=1, max_length=50)
    volume_order: int | None = None
    chapter_order: int | None = None
    chapter_code: str | None = None
    chapter_keywords: list[str] | None = None
    title: str | None = None
    is_enabled: bool | None = None


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    subject: str
    grade: str
    textbook: str | None
    volume_code: str
    volume_name: str
    volume_order: int
    chapter_order: int
    chapter_code: str
    chapter_keywords: list[str] = Field(default_factory=list)
    title: str
    is_enabled: bool
    updated_at: datetime


class ChapterSyncOut(BaseModel):
    strict_enabled: bool
    catalog_version: str
    managed_scope_count: int
    created_count: int
    updated_count: int
    enabled_count: int
    disabled_count: int


class ChapterCatalogAuditOut(BaseModel):
    strict_enabled: bool
    catalog_version: str
    stage: str
    subject: str
    expected_count: int
    db_count: int
    missing_count: int
    disabled_catalog_count: int
    unexpected_enabled_count: int
    mismatched_field_count: int
    missing_samples: list[str] = Field(default_factory=list)
    unexpected_enabled_samples: list[str] = Field(default_factory=list)
    mismatched_field_samples: list[str] = Field(default_factory=list)


class VolumeOut(BaseModel):
    volume_code: str
    volume_name: str
    volume_order: int


class VolumeChapterGroupOut(BaseModel):
    volume: VolumeOut
    chapters: list[ChapterOut]


class SectionCreateRequest(BaseModel):
    stage: str
    subject: str
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    sort_order: int = 100
    is_enabled: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        if value is None:
            return value
        code = str(value).strip().lower().replace("_", "-").replace(" ", "-")
        code = re.sub(r"-{2,}", "-", code).strip("-")
        return code

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if value in RESERVED_SECTION_CODES:
            raise ValueError(f"Section code '{value}' is reserved")
        if not SECTION_CODE_PATTERN.match(value):
            raise ValueError("Section code must match ^[a-z][a-z0-9-]{0,49}$")
        return value


class SectionUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    sort_order: int | None = None
    is_enabled: bool | None = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = str(value).strip().lower().replace("_", "-").replace(" ", "-")
        code = re.sub(r"-{2,}", "-", code).strip("-")
        return code

    @field_validator("code")
    @classmethod
    def validate_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value in RESERVED_SECTION_CODES:
            raise ValueError(f"Section code '{value}' is reserved")
        if not SECTION_CODE_PATTERN.match(value):
            raise ValueError("Section code must match ^[a-z][a-z0-9-]{0,49}$")
        return value


class SectionReorderItem(BaseModel):
    id: int
    sort_order: int


class SectionReorderRequest(BaseModel):
    items: list[SectionReorderItem]


class TagCreateRequest(BaseModel):
    stage: str
    subject: str
    tag: str = Field(min_length=1, max_length=80)
    category: str = Field(default="other", min_length=1, max_length=50)
    sort_order: int = 100
    is_enabled: bool = True


class TagUpdateRequest(BaseModel):
    tag: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    sort_order: int | None = None
    is_enabled: bool | None = None


class TagReorderItem(BaseModel):
    id: int
    sort_order: int


class TagReorderRequest(BaseModel):
    items: list[TagReorderItem]


class ResourceSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    subject: str
    code: str
    name: str
    description: str | None
    sort_order: int
    is_enabled: bool
    created_by: int | None
    updated_at: datetime


class ResourceSectionLiteOut(BaseModel):
    id: int
    code: str
    name: str


class ResourceTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    subject: str
    tag: str
    category: str
    sort_order: int
    is_enabled: bool
    created_by: int | None
    updated_at: datetime


class StorageListItemOut(BaseModel):
    key: str
    name: str
    is_dir: bool
    size: int | None = None
    updated_at: datetime | None = None
    content_type: str | None = None


class StorageListOut(BaseModel):
    prefix: str
    parent_prefix: str | None = None
    items: list[StorageListItemOut]


class StorageCreateFolderRequest(BaseModel):
    prefix: str = ""
    name: str = Field(min_length=1, max_length=255)


class StorageRenameRequest(BaseModel):
    source_key: str = Field(min_length=1, max_length=1024)
    target_name: str = Field(min_length=1, max_length=255)


class StorageUploadOut(BaseModel):
    key: str
    name: str
    size: int
    content_type: str | None = None


class StorageFolderOut(BaseModel):
    key: str


class StorageRenameOut(BaseModel):
    key: str
    moved_count: int


class StorageDeleteOut(BaseModel):
    deleted_count: int
    trashed_count: int = 0
    trashed_resource_count: int = 0
    trashed_storage_count: int = 0


class StorageReconcileOut(BaseModel):
    scanned_count: int
    trashed_count: int
    missing_count: int
    dry_run: bool


class StorageDownloadOut(BaseModel):
    key: str
    url: str


class AccessUrlsOut(BaseModel):
    open_url: str
    download_url: str


class StoragePreviewOut(BaseModel):
    key: str
    mode: str
    content_type: str | None = None
    size: int | None = None
    url: str | None = None
    open_url: str | None = None
    download_url: str | None = None
    content: str | None = None


class StorageBootstrapItemOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    folder_key: str
    status: str


class StorageBootstrapOut(BaseModel):
    chapter_id: int
    chapter_code: str
    created_count: int
    skipped_count: int
    items: list[StorageBootstrapItemOut]


class StorageBootstrapBatchOut(BaseModel):
    total_chapters: int
    created_count: int
    skipped_count: int
    no_section_chapter_ids: list[int]
    chapters: list[StorageBootstrapOut]


class OfficeConfigOut(BaseModel):
    document_server_js_url: str
    config: dict[str, Any]


class OfficeCallbackAckOut(BaseModel):
    error: int
    message: str | None = None


class OfficeHealthOut(BaseModel):
    available: bool
    reason: str | None = None
    script_url: str | None = None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    type: str
    subject: str | None
    grade: str | None
    tags: list[str]
    status: ResourceStatus
    resource_kind: str
    file_format: str
    difficulty: str | None
    ai_summary: str | None = None
    ai_tags: list[str] = Field(default_factory=list)
    has_embedding: bool = False
    section_id: int | None
    section: ResourceSectionLiteOut | None = None
    volume_code: str | None = None
    source_filename: str | None = None
    external_url: str | None = None
    title_auto_generated: bool = True
    rename_version: str = "v1"
    storage_provider: StorageProvider
    object_key: str | None
    chapter_id: int | None
    chapter_ids: list[int]
    author_id: int
    reviewer_id: int | None
    review_note: str | None
    file_path: str | None
    is_trashed: bool = False
    trashed_at: datetime | None = None
    trashed_by: int | None = None
    trash_source: str | None = None
    trash_has_binary: bool = False
    download_url: str | None = None
    preview_mode: str | None = None
    created_at: datetime
    updated_at: datetime


class ResourceListOut(BaseModel):
    items: list[ResourceOut]
    total: int
    page: int
    page_size: int


class DynamicGroupOut(BaseModel):
    section: ResourceSectionLiteOut | None
    items: list[ResourceOut]


class ChapterGroupsOut(BaseModel):
    chapter: ChapterOut
    groups: list[DynamicGroupOut]


class UploadOptionsOut(BaseModel):
    chapters: list[ChapterOut]
    volumes: list[VolumeOut] = Field(default_factory=list)
    chapters_grouped: list[VolumeChapterGroupOut] = Field(default_factory=list)
    sections: list[ResourceSectionOut]
    tags: list[ResourceTagOut]
    difficulties: list[str]
    quick_queries: list[str]


class IngestUrlRequest(BaseModel):
    url: str = Field(min_length=5, max_length=1024)
    title: str | None = Field(default=None, max_length=255)
    stage: str = "senior"
    subject: str = "物理"


class SourceDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    url: str | None
    object_key: str | None
    title: str
    summary: str | None
    tags: list[str] = Field(default_factory=list)
    fingerprint: str
    stage: str
    subject: str
    chapter_id: int | None
    confidence: float | None
    status: str
    published_at: datetime | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class IngestJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    url: str | None
    source_document_id: int | None
    stage: str
    subject: str
    status: str
    progress: float
    detail: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class IngestSubmitOut(BaseModel):
    job: IngestJobOut
    document: SourceDocumentOut | None = None


class SourceDocumentStatusRequest(BaseModel):
    status: Literal["ready", "published", "hidden", "failed", "pending_review"]


class KnowledgePointCreateRequest(BaseModel):
    chapter_id: int
    kp_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    difficulty: str | None = Field(default=None, max_length=30)
    prerequisite_level: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = "draft"


class KnowledgePointUpdateRequest(BaseModel):
    kp_code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    aliases: list[str] | None = None
    description: str | None = None
    difficulty: str | None = Field(default=None, max_length=30)
    prerequisite_level: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = None


class KnowledgePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_id: int
    kp_code: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None
    difficulty: str | None
    prerequisite_level: float
    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeEdgeCreateRequest(BaseModel):
    src_kp_id: int
    dst_kp_id: int
    edge_type: Literal["prerequisite", "related", "contains", "applies_to"] = "related"
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_count: int = Field(default=0, ge=0)


class KnowledgeEdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_kp_id: int
    dst_kp_id: int
    edge_type: str
    strength: float
    evidence_count: int
    created_at: datetime


class ReviewRequest(BaseModel):
    status: ResourceStatus
    review_note: str | None = None


class ResourceVisibilityRequest(BaseModel):
    visibility: Literal["public", "hidden"]
    note: str | None = None


class ResourceBulkManageRequest(BaseModel):
    resource_ids: list[int] = Field(default_factory=list)
    action: Literal["publish", "hide", "trash"]
    note: str | None = None


class ResourceBulkManageErrorOut(BaseModel):
    resource_id: int
    reason: str


class ResourceBulkManageOut(BaseModel):
    action: str
    requested: int
    succeeded: int
    failed: int
    errors: list[ResourceBulkManageErrorOut] = Field(default_factory=list)


class ResourceTagsUpdateRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)
    mode: Literal["replace", "append"] = "replace"


class ResourceTagsAdoptAIRequest(BaseModel):
    strategy: Literal["merge", "replace"] = "merge"


class LinkChapterRequest(BaseModel):
    chapter_id: int


class ResourcePreviewOut(BaseModel):
    mode: str
    url: str | None = None
    open_url: str | None = None
    download_url: str | None = None
    content: str | None = None


class ResourceAiStatusOut(BaseModel):
    enabled: bool
    auto_enrich: bool


class UploadPathPreviewOut(BaseModel):
    object_key: str
    prefix: str
    is_unassigned: bool


class AutoClassifyCandidateOut(BaseModel):
    chapter_id: int
    volume_code: str
    title: str
    score: float
    probability: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    rule_score: float = 0.0
    lexical_score: float = 0.0
    vector_score: float = 0.0
    final_score: float = 0.0


class AutoClassifyResponse(BaseModel):
    picked_chapter_id: int | None = None
    picked_volume_code: str | None = None
    recommended_chapter_id: int | None = None
    confidence: float = 0.0
    confidence_level: Literal["high", "medium", "low"] = "low"
    is_low_confidence: bool = True
    candidates: list[AutoClassifyCandidateOut] = Field(default_factory=list)
    rule_hits: list[str] = Field(default_factory=list)
    catalog_version: str = "pep2019_v1"
    reason: str = ""


class TextToMarkdownRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    title: str | None = Field(default=None, max_length=200)


class TextToMarkdownResponse(BaseModel):
    markdown: str
    provider: str = "mineruapi"


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=20, ge=1, le=20)
    include_answer: bool = False
    candidate_limit: int = Field(default=320, ge=20, le=2000)
    rerank_top_k: int = Field(default=20, ge=1, le=200)
    dedupe: bool = True


class SemanticScoreFactorsOut(BaseModel):
    vector: float
    summary: float
    content: float
    tags: float
    raw: float


class SemanticSearchTargetOut(BaseModel):
    resource_id: int | None = None
    source_id: int | None = None
    canonical_key: str | None = None
    title: str
    file_format: str | None = None
    chapter_id: int | None = None
    section_id: int | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)


class SemanticSearchItem(BaseModel):
    score: float
    probability: float
    factors: SemanticScoreFactorsOut
    resource: ResourceOut | None = None
    target: SemanticSearchTargetOut | None = None
    highlight_nodes: list[str] = Field(default_factory=list)
    highlight_edges: list[str] = Field(default_factory=list)


class SemanticSearchResponse(BaseModel):
    query: str
    answer: str | None = None
    threshold: float = 0.02
    returned_count: int = 0
    scoring_profile: str = "balanced_v1"
    results: list[SemanticSearchItem]


class RagGraphNodeOut(BaseModel):
    id: str
    label: str
    keyword_label: str | None = None
    node_type: str
    source_id: int | None = None
    resource_id: int | None = None
    is_resource_linkable: bool = False
    chapter_id: int | None = None
    section_id: int | None = None
    group_key: str | None = None
    score: float | None = None
    canonical_key: str | None = None
    primary_variant_kind: str | None = None
    variants_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


class RagGraphEdgeOut(BaseModel):
    source: str
    target: str
    edge_type: str
    weight: float = 1.0


class RagGraphStatsOut(BaseModel):
    total_resources: int
    embedded_resources: int
    chapter_nodes: int
    section_nodes: int
    format_nodes: int = 0
    public_sources: int = 0
    private_sources: int = 0
    similarity_edges: int
    generated_at: datetime


class RagGraphOut(BaseModel):
    nodes: list[RagGraphNodeOut]
    edges: list[RagGraphEdgeOut]
    stats: RagGraphStatsOut


class RagWorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    stage: str = "senior"
    subject: str = "物理"


class RagWorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    stage: str
    subject: str
    created_by: int
    created_at: datetime
    updated_at: datetime


class RagSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    source_type: str
    resource_id: int | None
    title: str
    object_key: str | None
    file_format: str | None
    summary_text: str | None
    tags: list[str] = Field(default_factory=list)
    status: str
    published_resource_id: int | None
    canonical_key: str | None = None
    variant_kind: str | None = None
    is_graph_visible: bool = True
    display_priority: int = 100
    created_by: int
    created_at: datetime
    updated_at: datetime


class RagBindResourcesRequest(BaseModel):
    resource_ids: list[int] = Field(default_factory=list)


class RagSourcesBindOut(BaseModel):
    created: int
    skipped: int
    items: list[RagSourceOut]


class RagSourceUploadOut(BaseModel):
    source: RagSourceOut
    object_key: str


class RagExtractRequest(BaseModel):
    mode: str = Field(default="quick", pattern="^(quick|full)$")
    source_ids: list[int] = Field(default_factory=list)


class RagExtractOut(BaseModel):
    job_id: int
    mode: str
    status: str
    processed_sources: int
    entities_created: int
    relations_created: int
    evidences_created: int


class RagJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    source_id: int | None
    mode: str
    status: str
    stats: dict[str, Any]
    error_message: str | None
    created_by: int
    created_at: datetime
    updated_at: datetime


class RagQaRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class RagCitationOut(BaseModel):
    source_id: int
    title: str
    evidence: str
    score: float


class RagQaResponse(BaseModel):
    answer: str
    citations: list[RagCitationOut]
    highlight_nodes: list[str] = Field(default_factory=list)
    highlight_edges: list[str] = Field(default_factory=list)


class RagAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=12, ge=1, le=20)


class RagAskResponse(BaseModel):
    answer: str
    citations: list[RagCitationOut]
    used_count: int


class RagGraphEmbeddingNodeOut(BaseModel):
    id: str
    label: str
    node_type: str
    x: float
    y: float
    z: float
    prerequisite_level: float = 0.0
    relation_strength: float = 0.0
    heat: float = 0.0
    created_at_ts: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


class RagGraphEmbeddingOut(BaseModel):
    workspace_id: int
    generated_at: datetime
    nodes: list[RagGraphEmbeddingNodeOut]
    edges: list[RagGraphEdgeOut]


class RagQaLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    user_id: int
    question: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    highlight_nodes: list[str] = Field(default_factory=list)
    highlight_edges: list[str] = Field(default_factory=list)
    created_at: datetime


class RagPublishSourceOut(BaseModel):
    source: RagSourceOut
    resource: ResourceOut


class RagQuickBootstrapRequest(BaseModel):
    stage: str = "senior"
    subject: str = "物理"
    force_extract: bool = False


class RagQuickBootstrapOut(BaseModel):
    workspace: RagWorkspaceOut
    source_count: int
    bound_count: int
    skipped_count: int
    pruned_count: int = 0
    extracted: bool
    extract_reason: str
    extract_stats: dict[str, Any] = Field(default_factory=dict)
    bootstrap_job_id: int | None = None
    bootstrap_status: str = "skipped"
    failed_sources_count: int = 0


class RagBootstrapErrorOut(BaseModel):
    source_id: int | None = None
    stage: str
    message: str


class RagBootstrapJobOut(BaseModel):
    job_id: int
    workspace_id: int
    status: str
    mode: str
    processed_sources: int = 0
    succeeded_sources: int = 0
    failed_sources_count: int = 0
    failed_sources: list[RagBootstrapErrorOut] = Field(default_factory=list)
    entities_created: int = 0
    relations_created: int = 0
    evidences_created: int = 0
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class RagBootstrapJobErrorsOut(BaseModel):
    job_id: int
    status: str
    total: int
    page: int
    page_size: int
    items: list[RagBootstrapErrorOut] = Field(default_factory=list)


class RagLinkedResourceOut(BaseModel):
    source_id: int
    resource_id: int | None = None
    keyword_title: str
    open_path: str | None = None
    score: float = 0.0
    is_openable: bool = False
    message: str | None = None


class RagNodeLinkedResourcesOut(BaseModel):
    node_id: str
    items: list[RagLinkedResourceOut]


class RagNodeVariantOut(BaseModel):
    source_id: int
    resource_id: int | None = None
    title: str
    object_key: str | None = None
    variant_kind: str | None = None
    file_format: str | None = None
    is_graph_visible: bool = True
    open_url: str | None = None
    download_url: str | None = None
    visibility: Literal["public", "private"] = "private"
    display_priority: int = 100
    is_primary: bool = False


class RagNodeVariantsOut(BaseModel):
    node_id: str
    canonical_key: str | None = None
    primary_source_id: int | None = None
    auto_open_variant_kind: str | None = None
    variants: list[RagNodeVariantOut] = Field(default_factory=list)


class TrashItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int | None
    resource_title: str | None = None
    scope: str
    original_key: str
    trash_key: str | None
    has_binary: bool
    source: str
    deleted_by: int | None
    deleted_at: datetime
    expires_at: datetime
    meta: dict[str, Any] = Field(default_factory=dict)


class TrashListOut(BaseModel):
    items: list[TrashItemOut]
    total: int
    page: int
    page_size: int


class TrashActionOut(BaseModel):
    item: TrashItemOut
    restored_key: str | None = None
    message: str | None = None


class TrashPurgeOut(BaseModel):
    purged_count: int


class MineruJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creator_id: int
    source_filename: str
    source_object_key: str | None
    batch_id: str
    status: MineruJobStatus
    parse_options: dict[str, Any]
    official_result: dict[str, Any] | None
    markdown_object_key: str | None
    markdown_preview: str | None
    auto_create_resource: bool
    resource_id: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class MineruMaterializeRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    type: str = "document"
    description: str | None = None
    subject: str | None = None
    grade: str | None = None
    tags: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    chapter_id: int | None = None
    section_id: int | None = None
    resource_kind: str | None = None
