from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


def cleanup_source_extract_artifacts(db: Session, *, source_id: int) -> None:
    evidence_ids_subquery = (
        select(models.RagEvidence.id)
        .where(models.RagEvidence.source_id == source_id)
    )
    relation_ids_subquery = (
        select(models.RagRelation.id)
        .where(models.RagRelation.source_id == source_id)
    )

    db.query(models.RagRelationEvidence).filter(
        models.RagRelationEvidence.evidence_id.in_(evidence_ids_subquery)
    ).delete(synchronize_session=False)
    db.query(models.RagRelationEvidence).filter(
        models.RagRelationEvidence.relation_id.in_(relation_ids_subquery)
    ).delete(synchronize_session=False)

    db.query(models.RagEvidence).filter(
        models.RagEvidence.source_id == source_id
    ).delete(synchronize_session=False)
    db.query(models.RagRelation).filter(
        models.RagRelation.source_id == source_id
    ).delete(synchronize_session=False)
    db.query(models.RagChunk).filter(
        models.RagChunk.source_id == source_id
    ).delete(synchronize_session=False)

