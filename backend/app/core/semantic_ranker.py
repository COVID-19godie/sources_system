import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.core import ai_service


WEIGHTS = {
    "vector": 0.55,
    "summary": 0.20,
    "content": 0.15,
    "tags": 0.10,
}


@dataclass(slots=True)
class SemanticCandidate:
    candidate_id: str
    title: str
    description: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    chapter_id: int | None = None
    section_id: int | None = None
    payload: Any = None
    target: dict[str, Any] | None = None
    highlight_nodes: list[str] = field(default_factory=list)
    highlight_edges: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RankedCandidate:
    candidate: SemanticCandidate
    vector: float
    summary: float
    content: float
    tags: float
    raw: float
    probability: float


@dataclass(slots=True)
class RankResult:
    items: list[RankedCandidate]
    threshold: float


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    text = text.lower()
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _lexical_score(query: str, text: str) -> float:
    query_text = (query or "").strip().lower()
    body = (text or "").strip().lower()
    if not query_text or not body:
        return 0.0

    # Exact phrase gets a stronger boost in education title/summary matching.
    if query_text in body:
        return 1.0

    query_tokens = _unique(_tokenize(query_text))
    if not query_tokens:
        return 0.0

    hit = 0
    for token in query_tokens:
        if token in body:
            hit += 1
    return max(0.0, min(1.0, hit / len(query_tokens)))


def _tags_score(query: str, tags: list[str]) -> float:
    if not tags:
        return 0.0
    corpus = " ".join(tag for tag in tags if tag)
    return _lexical_score(query, corpus)


def _vector_score(query_embedding: list[float] | None, embedding: list[float] | None) -> float:
    if not query_embedding or not embedding:
        return 0.0
    similarity = ai_service.cosine_similarity(query_embedding, embedding)
    return max(0.0, min(1.0, (similarity + 1.0) / 2.0))


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    max_v = max(values)
    exps = [math.exp(max(-60.0, min(60.0, value - max_v))) for value in values]
    total = sum(exps)
    if total <= 0:
        return [1.0 / len(values)] * len(values)
    return [value / total for value in exps]


def _adaptive_threshold(probabilities: list[float]) -> float:
    if not probabilities:
        return 0.02
    n = len(probabilities)
    if n <= 1:
        return 0.08

    p_sum = sum(probabilities)
    if p_sum <= 0:
        return 0.02
    normalized = [p / p_sum for p in probabilities if p > 0]
    if not normalized:
        return 0.02

    entropy = -sum(p * math.log(p) for p in normalized)
    entropy_norm = entropy / math.log(n)
    threshold = 0.02 + (1 - entropy_norm) * 0.06
    return max(0.02, min(0.08, threshold))


def rank_candidates(
    query: str,
    candidates: list[SemanticCandidate],
    *,
    query_embedding: list[float] | None = None,
    top_k: int = 20,
) -> RankResult:
    if not candidates:
        return RankResult(items=[], threshold=0.02)

    scored: list[RankedCandidate] = []
    for candidate in candidates:
        vector = _vector_score(query_embedding, candidate.embedding)
        summary = _lexical_score(query, candidate.summary)
        content = _lexical_score(query, f"{candidate.title}\n{candidate.description}")
        tags = _tags_score(query, candidate.tags)
        raw = (
            WEIGHTS["vector"] * vector
            + WEIGHTS["summary"] * summary
            + WEIGHTS["content"] * content
            + WEIGHTS["tags"] * tags
        )
        scored.append(
            RankedCandidate(
                candidate=candidate,
                vector=vector,
                summary=summary,
                content=content,
                tags=tags,
                raw=raw,
                probability=0.0,
            )
        )

    probabilities = _softmax([item.raw for item in scored])
    for item, probability in zip(scored, probabilities):
        item.probability = probability

    scored.sort(key=lambda item: item.probability, reverse=True)
    upper = max(1, min(20, top_k))
    top_items = scored[:upper]

    threshold = _adaptive_threshold([item.probability for item in top_items])
    filtered = [item for item in top_items if item.probability >= threshold]

    return RankResult(items=filtered, threshold=threshold)
