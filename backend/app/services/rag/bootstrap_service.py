from __future__ import annotations

from typing import Any

from app import models


BOOTSTRAP_STATUS_QUEUED = "queued"
BOOTSTRAP_STATUS_PROCESSING = "processing"
BOOTSTRAP_STATUS_DONE = "done"
BOOTSTRAP_STATUS_PARTIAL_FAILED = "partial_failed"
BOOTSTRAP_STATUS_FAILED = "failed"
BOOTSTRAP_STATUS_SKIPPED = "skipped"

ACTIVE_BOOTSTRAP_STATUSES = {
    BOOTSTRAP_STATUS_QUEUED,
    BOOTSTRAP_STATUS_PROCESSING,
}


def normalize_failed_sources(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        source_id_raw = item.get("source_id")
        try:
            source_id = int(source_id_raw)
        except Exception:  # noqa: BLE001
            source_id = 0
        stage = str(item.get("stage") or "extract").strip() or "extract"
        message = str(item.get("message") or "").strip()
        rows.append(
            {
                "source_id": source_id if source_id > 0 else None,
                "stage": stage[:50],
                "message": message[:800],
            }
        )
    return rows


def job_failed_sources(job: models.RagExtractionJob) -> list[dict[str, Any]]:
    stats = job.stats if isinstance(job.stats, dict) else {}
    return normalize_failed_sources(stats.get("failed_sources"))


def job_failed_sources_count(job: models.RagExtractionJob) -> int:
    stats = job.stats if isinstance(job.stats, dict) else {}
    explicit = stats.get("failed_sources_count")
    if isinstance(explicit, int) and explicit >= 0:
        return explicit
    return len(job_failed_sources(job))

