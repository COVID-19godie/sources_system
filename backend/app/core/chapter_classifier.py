from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import math
import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models
from app.core import ai_service
from app.core.config import settings


NOISE_WORDS = {
    "最终版",
    "定稿",
    "副本",
    "课件",
    "教程",
    "资料",
    "高中",
    "物理",
    "final",
    "new",
    "v1",
    "v2",
}

VOLUME_PATTERNS = {
    "bx1": ["必修第一册", "必修一", "必修1", "bx1"],
    "bx2": ["必修第二册", "必修二", "必修2", "bx2"],
    "xbx1": ["选择性必修第一册", "选必一", "选必1", "xbx1"],
    "xbx2": ["选择性必修第二册", "选必二", "选必2", "xbx2"],
    "xbx3": ["选择性必修第三册", "选必三", "选必3", "xbx3"],
}


@dataclass(slots=True)
class ChapterCandidate:
    chapter: models.Chapter
    reasons: list[str] = field(default_factory=list)
    rule_score: float = 0.0
    lexical_score: float = 0.0
    vector_score: float = 0.0
    final_score: float = 0.0
    probability: float = 0.0


@dataclass(slots=True)
class ChapterClassification:
    chapter: models.Chapter | None
    volume_code: str | None
    confidence: float
    confidence_level: str
    is_low_confidence: bool
    candidates: list[ChapterCandidate]
    reason: str
    rule_hits: list[str]
    recommended_chapter_id: int | None


def _softmax_probabilities(values: list[float], temperature: float = 0.28) -> list[float]:
    if not values:
        return []
    temp = max(0.01, temperature)
    max_value = max(values)
    exp_values = [math.exp((value - max_value) / temp) for value in values]
    total = sum(exp_values)
    if total <= 0:
        size = len(values)
        return [1.0 / size for _ in values]
    return [value / total for value in exp_values]


def _tokenize(text: str) -> list[str]:
    value = (text or "").lower()
    if not value:
        return []
    raw_tokens = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", value)
    tokens: list[str] = []
    for token in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            segment = token if len(token) <= 12 else f"{token[:6]}{token[-6:]}"
            tokens.append(segment)
            if len(segment) >= 4:
                for gram_size in (2, 3, 4):
                    if len(segment) < gram_size:
                        continue
                    for idx in range(0, len(segment) - gram_size + 1):
                        tokens.append(segment[idx : idx + gram_size])
        else:
            tokens.append(token)
    return tokens


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def lexical_score(query: str, corpus: str) -> float:
    q = (query or "").strip().lower()
    body = (corpus or "").strip().lower()
    if not q or not body:
        return 0.0
    if q in body:
        return 1.0
    query_tokens = _dedupe(_tokenize(q))
    corpus_tokens = _dedupe(_tokenize(body))
    if not query_tokens or not corpus_tokens:
        return 0.0
    corpus_set = set(corpus_tokens)
    hits = sum(1 for token in query_tokens if token in corpus_set)
    overlap = hits / max(1, min(len(query_tokens), len(corpus_tokens)))
    coverage = hits / max(1, len(corpus_tokens))
    precision = hits / max(1, len(query_tokens))
    bonus = 0.0
    for token in corpus_tokens:
        if len(token) >= 2 and token in q:
            bonus += 1.0
    bonus = min(1.0, bonus / 4.0)
    score = 0.45 * overlap + 0.25 * coverage + 0.2 * precision + 0.1 * bonus
    return max(0.0, min(1.0, score))


def _chapter_index_text(chapter: models.Chapter) -> str:
    keywords = " ".join(chapter.chapter_keywords or [])
    return (
        f"{chapter.volume_name} {chapter.volume_code} {chapter.chapter_code} {chapter.title} "
        f"{chapter.grade} {keywords}"
    ).strip()


def _maybe_generate_chapter_embedding(db: Session, chapter: models.Chapter) -> tuple[list[float] | None, bool]:
    if isinstance(chapter.index_embedding_json, list) and chapter.index_embedding_json:
        return chapter.index_embedding_json, False
    if not ai_service.is_enabled():
        return None, False
    try:
        vector = ai_service.generate_embedding(_chapter_index_text(chapter))
    except ai_service.AIServiceError:
        return None, False
    chapter.index_embedding_json = vector
    chapter.index_embedding_model = settings.AI_EMBEDDING_MODEL
    chapter.index_updated_at = datetime.now(timezone.utc)
    db.add(chapter)
    return vector, True


def build_classification_query(
    *,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    filename: str = "",
    external_url: str = "",
    content_text: str = "",
) -> str:
    parts = [
        title or "",
        description or "",
        " ".join(tags or []),
        filename or "",
        external_url or "",
        content_text or "",
    ]
    text = "\n".join(item.strip() for item in parts if item and item.strip())
    return text[: settings.AI_MAX_SOURCE_CHARS]


def _build_lexical_query(
    *,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    filename: str = "",
    external_url: str = "",
    content_text: str = "",
) -> str:
    host = extract_host(external_url) or ""
    stem = clean_filename_stem(filename, fallback="")
    tag_text = " ".join(tags or [])
    content_excerpt = (content_text or "").strip()[:1200]
    parts = [
        title.strip(),
        title.strip(),
        tag_text,
        tag_text,
        stem,
        host,
        description.strip()[:400],
        content_excerpt,
    ]
    text = " ".join(item for item in parts if item)
    return text[:1600]


def _build_filename_query(*, filename: str = "", title: str = "") -> str:
    stem = Path(filename or "").stem.strip()
    if not stem:
        return (title or "").strip()[:300]
    normalized = stem.replace("_", " ").replace("-", " ").replace("+", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:300]


def _normalize_search_text(text: str) -> str:
    lowered = (text or "").lower().replace("（", "(").replace("）", ")")
    lowered = lowered.replace("+", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def _extract_explicit_chapter_codes(query_text: str) -> list[str]:
    text = (query_text or "").replace("（", "(").replace("）", ")")
    found = re.findall(r"(?<!\d)(\d\.\d{1,2})(?!\d)", text)
    normalized: list[str] = []
    for item in found:
        parts = item.split(".", 1)
        if len(parts) != 2:
            continue
        left = parts[0].lstrip("0") or "0"
        right = parts[1].lstrip("0") or "0"
        normalized.append(f"{left}.{right}")
    return _dedupe(normalized)


def _detect_volume_code(query_text: str) -> tuple[str | None, list[str]]:
    text = _normalize_search_text(query_text)
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for code, patterns in VOLUME_PATTERNS.items():
        for pattern in patterns:
            normalized = _normalize_search_text(pattern)
            if normalized and normalized in text:
                scores[code] = scores.get(code, 0.0) + 0.5
                reasons[code] = f"命中册关键词：{pattern}"
    if not scores:
        return None, []
    picked = max(scores.items(), key=lambda item: item[1])[0]
    return picked, [reasons[picked]]


def classify_chapter(
    db: Session,
    *,
    stage: str,
    subject: str,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    filename: str = "",
    external_url: str = "",
    content_text: str = "",
    volume_code: str | None = None,
    top_k: int = 3,
) -> ChapterClassification:
    chapters = (
        db.query(models.Chapter)
        .filter(
            models.Chapter.stage == stage,
            models.Chapter.subject == subject,
            models.Chapter.is_enabled.is_(True),
        )
        .order_by(
            models.Chapter.volume_order.asc(),
            models.Chapter.chapter_order.asc(),
            models.Chapter.chapter_code.asc(),
        )
        .all()
    )
    if not chapters:
        return ChapterClassification(
            chapter=None,
            volume_code=None,
            confidence=0.0,
            confidence_level="low",
            is_low_confidence=True,
            candidates=[],
            reason="暂无可用章节",
            rule_hits=[],
            recommended_chapter_id=None,
        )

    query_text = build_classification_query(
        title=title,
        description=description,
        tags=tags,
        filename=filename,
        external_url=external_url,
        content_text=content_text,
    )
    if not query_text:
        return ChapterClassification(
            chapter=None,
            volume_code=chapters[0].volume_code,
            confidence=0.0,
            confidence_level="low",
            is_low_confidence=True,
            candidates=[],
            reason="内容为空，无法自动判章",
            rule_hits=[],
            recommended_chapter_id=None,
        )
    lexical_query = _build_lexical_query(
        title=title,
        description=description,
        tags=tags,
        filename=filename,
        external_url=external_url,
        content_text=content_text,
    )
    filename_query = _build_filename_query(filename=filename, title=title)
    normalized_query = _normalize_search_text(lexical_query)
    normalized_filename_query = _normalize_search_text(filename_query)
    explicit_codes_from_filename = _extract_explicit_chapter_codes(filename_query)
    explicit_codes = _dedupe(explicit_codes_from_filename + _extract_explicit_chapter_codes(lexical_query))

    selected_volume = (volume_code or "").strip() or None
    selected_volume_reasons: list[str] = []
    if selected_volume and not any(ch.volume_code == selected_volume for ch in chapters):
        selected_volume = None
    if selected_volume:
        selected_volume_reasons.append(f"已按你选择的册限定：{selected_volume}")
    else:
        detected_volume, volume_hits = _detect_volume_code(filename_query or lexical_query)
        if detected_volume and not explicit_codes:
            selected_volume = detected_volume
            selected_volume_reasons.extend(volume_hits)

    chapter_pool = [item for item in chapters if item.volume_code == selected_volume] if selected_volume else chapters
    if not chapter_pool:
        chapter_pool = chapters

    query_embedding: list[float] | None = None
    if ai_service.is_enabled():
        try:
            query_embedding = ai_service.generate_embedding(query_text)
        except ai_service.AIServiceError:
            query_embedding = None

    scored: list[ChapterCandidate] = []
    changed_embedding = False
    for chapter in chapter_pool:
        reasons: list[str] = []
        rule_score = 0.0
        filename_score = 0.0

        chapter_code = (chapter.chapter_code or "").strip()
        if chapter_code and chapter_code in explicit_codes_from_filename:
            explicit_score = 1.0
            if explicit_score > rule_score:
                rule_score = explicit_score
            if explicit_score > filename_score:
                filename_score = explicit_score
            reasons.append(f"命中文件名章节号：{chapter_code}")
        elif chapter_code and chapter_code in explicit_codes:
            explicit_score = 0.99
            if explicit_score > rule_score:
                rule_score = explicit_score
            if explicit_score > filename_score:
                filename_score = explicit_score
            reasons.append(f"命中章节号：{chapter_code}")
        if chapter_code and chapter_code.lower() in normalized_query:
            code_score = 0.68
            if code_score > rule_score:
                rule_score = code_score
            reasons.append(f"命中章节编号：{chapter_code}")

        chapter_title = _normalize_search_text(chapter.title or "")
        if chapter_title and chapter_title in normalized_query:
            # Exact chapter-title hit should dominate ambiguous keyword matches.
            title_score = 0.995
            if title_score > rule_score:
                rule_score = title_score
            reasons.append(f"命中章节标题：{chapter.title}")
        if chapter_title and chapter_title in normalized_filename_query:
            filename_title_score = 0.995
            if filename_title_score > rule_score:
                rule_score = filename_title_score
            if filename_title_score > filename_score:
                filename_score = filename_title_score
            reasons.append(f"命中文件名章节标题：{chapter.title}")

        keyword_hits: list[str] = []
        for keyword in chapter.chapter_keywords or []:
            normalized_keyword = _normalize_search_text(keyword)
            if normalized_keyword and normalized_keyword in normalized_query:
                keyword_hits.append(keyword.strip())
            if normalized_keyword and normalized_keyword in normalized_filename_query:
                keyword_hits.append(keyword.strip())
        keyword_hits = _dedupe(keyword_hits)
        if keyword_hits:
            keyword_score = min(0.82, 0.45 + 0.12 * len(keyword_hits))
            if keyword_score > rule_score:
                rule_score = keyword_score
            if keyword_score > filename_score:
                filename_score = keyword_score
            reasons.append(f"命中章节关键词：{'、'.join(keyword_hits[:4])}")

        lex_score = lexical_score(lexical_query, _chapter_index_text(chapter))
        if filename_query:
            filename_lex_score = lexical_score(
                filename_query,
                f"{chapter.chapter_code} {chapter.title} {' '.join(chapter.chapter_keywords or [])}",
            )
            if filename_lex_score > filename_score:
                filename_score = filename_lex_score
            if filename_lex_score >= 0.6:
                reasons.append("文件名语义匹配较强")
        else:
            filename_score = lex_score

        vec_score = 0.0
        if query_embedding:
            vector, generated = _maybe_generate_chapter_embedding(db, chapter)
            if vector:
                vec_score = max(
                    0.0,
                    min(1.0, (ai_service.cosine_similarity(query_embedding, vector) + 1.0) / 2.0),
                )
            if generated:
                changed_embedding = True

        if filename_query:
            # 文件名优先：概率主要由文件名驱动，正文与向量作为补充。
            final_score = 0.45 * rule_score + 0.40 * filename_score + 0.13 * lex_score + 0.02 * vec_score
        else:
            final_score = 0.65 * rule_score + 0.25 * lex_score + 0.10 * vec_score
        if rule_score >= 0.85:
            final_score = max(final_score, rule_score)
        if filename_score >= 0.9:
            final_score = max(final_score, 0.92)
        scored.append(
            ChapterCandidate(
                chapter=chapter,
                reasons=_dedupe(reasons),
                rule_score=max(0.0, min(1.0, rule_score)),
                lexical_score=max(0.0, min(1.0, lex_score)),
                vector_score=max(0.0, min(1.0, vec_score)),
                final_score=max(0.0, min(1.0, final_score)),
            )
        )

    if changed_embedding:
        db.commit()

    scored.sort(key=lambda item: item.final_score, reverse=True)
    top_rows = scored[: max(1, min(5, top_k))]
    picked = top_rows[0] if top_rows else None
    raw_confidence = picked.final_score if picked else 0.0
    second_score = top_rows[1].final_score if len(top_rows) > 1 else 0.0
    margin = max(0.0, raw_confidence - second_score)
    probabilities = _softmax_probabilities([row.final_score for row in top_rows])
    for row, probability in zip(top_rows, probabilities):
        row.probability = max(0.0, min(1.0, probability))
    calibrated_confidence = 0.0
    if picked:
        calibrated_confidence = 0.75 * raw_confidence + 0.25 * min(1.0, margin * 3.0)
        if selected_volume and picked.chapter.volume_code == selected_volume and picked.rule_score >= 0.8:
            calibrated_confidence = min(1.0, calibrated_confidence + 0.08)
    confidence = max(top_rows[0].probability if top_rows else 0.0, calibrated_confidence)

    if picked and picked.rule_score >= 0.9 and raw_confidence >= 0.9:
        confidence_level = "high"
        reason = "规则命中很强，建议采用推荐章节"
    elif raw_confidence >= 0.75 and margin >= 0.15:
        confidence_level = "high"
        reason = "规则与模型一致，建议采用推荐章节"
    elif raw_confidence >= 0.45 and margin >= 0.08:
        confidence_level = "medium"
        reason = "有较明确候选，建议人工快速确认"
    else:
        confidence_level = "low"
        reason = "模型置信度较低，建议人工确认章节"

    combined_rule_hits = selected_volume_reasons.copy()
    if picked:
        for item in picked.reasons:
            if item not in combined_rule_hits:
                combined_rule_hits.append(item)

    return ChapterClassification(
        chapter=picked.chapter if picked else None,
        volume_code=(picked.chapter.volume_code if picked else selected_volume),
        confidence=confidence,
        confidence_level=confidence_level,
        is_low_confidence=confidence_level == "low",
        candidates=top_rows[: max(1, min(3, top_k))],
        reason=reason,
        rule_hits=combined_rule_hits,
        recommended_chapter_id=(picked.chapter.id if picked else None),
    )


def normalize_keyword(text: str, fallback: str = "资源") -> str:
    parts = _dedupe(_tokenize(text))
    picked: list[str] = []
    for token in parts:
        if token in NOISE_WORDS:
            continue
        if len(token) <= 1 and not re.fullmatch(r"[a-z0-9]+", token):
            continue
        picked.append(token)
        if len(picked) >= 2:
            break
    if not picked:
        return fallback
    return "·".join(picked)


def clean_filename_stem(filename: str | None, fallback: str = "资源") -> str:
    stem = Path(filename or "").stem.strip()
    if not stem:
        return fallback
    stem = stem.replace("_", " ").replace("-", " ")
    return normalize_keyword(stem, fallback=fallback)


def build_resource_title(
    *,
    volume_code: str | None,
    chapter_code: str | None,
    section_code: str | None,
    keyword: str,
) -> str:
    date_part = datetime.now().strftime("%Y%m%d")
    volume = (volume_code or "unassigned").strip() or "unassigned"
    chapter = (chapter_code or "unassigned").strip() or "unassigned"
    section = (section_code or "general").strip() or "general"
    return f"{volume}-{chapter}-{section}-{keyword}-{date_part}"[:255]


def extract_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    return parsed.netloc.lower() or None
