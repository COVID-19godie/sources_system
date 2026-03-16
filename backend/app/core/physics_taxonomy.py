from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[4]

CHAPTER_RE = re.compile(r"^#\s*第[0-9一二三四五六七八九十百零两]+章\s*(.+?)\s*$")
KNOWLEDGE_RE = re.compile(r"^知识组\s*\d+\s*(.+?)(?:\s+\d+)?\s*$")
FOCUS_RE = re.compile(r"^重难点\s*\d+\s*(.+?)(?:\s+\d+)?\s*$")
EXAM_RE = re.compile(r"^考\s*点\s*\d+\s*(.+?)(?:\s+\d+)?\s*$")
PROBLEM_RE = re.compile(r"^题组\s*\d+\s*(.+?)(?:\s+\d+)?\s*$")
EXPERIMENT_RE = re.compile(r"^实验[一二三四五六七八九十百零两0-9]+\s+(.+?)(?:\s+\d+)?\s*$")
NUMBERED_ITEM_RE = re.compile(r"^[一二三四五六七八九十百零两0-9]+\s+(.+?)(?:\s+\d+)?\s*$")
TRAILING_PAGE_RE = re.compile(r"(.*?)\s+\d+\s*$")
CHAPTER_PREFIX_RE = re.compile(r"^第[0-9一二三四五六七八九十百零两]+章")
STRIP_NOISE_RE = re.compile(r"[A-Da-d$·•…\-\.\s\(\)（）:：]+")


@dataclass(slots=True)
class ChapterTaxonomy:
    title: str
    source_files: list[str] = field(default_factory=list)
    knowledge_tags: list[str] = field(default_factory=list)
    focus_tags: list[str] = field(default_factory=list)
    exam_tags: list[str] = field(default_factory=list)
    problem_tags: list[str] = field(default_factory=list)
    experiment_tags: list[str] = field(default_factory=list)

    @property
    def tags(self) -> list[str]:
        merged: list[str] = []
        for group in (
            self.knowledge_tags,
            self.focus_tags,
            self.exam_tags,
            self.problem_tags,
            self.experiment_tags,
        ):
            for item in group:
                if item and item not in merged:
                    merged.append(item)
        return merged[:24]


def _clean_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("考 点", "考点")
    text = re.sub(r"[·•…]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    match = TRAILING_PAGE_RE.match(text)
    if match:
        text = match.group(1).strip()
    return text.strip(" -:：")


def _normalize_for_match(value: str) -> str:
    text = _clean_label(value)
    text = CHAPTER_PREFIX_RE.sub("", text)
    text = STRIP_NOISE_RE.sub("", text)
    return text.lower()


def _append_unique(items: list[str], value: str) -> None:
    cleaned = _clean_label(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _iter_markdown_files() -> list[Path]:
    return sorted(path for path in REPO_ROOT.glob("*.md") if path.name.lower() != "readme.md")


def _parse_markdown_taxonomy(path: Path) -> list[ChapterTaxonomy]:
    chapters: list[ChapterTaxonomy] = []
    current: ChapterTaxonomy | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = _clean_label(raw_line)
        if not line:
            continue

        chapter_match = CHAPTER_RE.match(line)
        if chapter_match:
            current = ChapterTaxonomy(title=_clean_label(chapter_match.group(1)), source_files=[path.name])
            chapters.append(current)
            continue

        if current is None:
            continue

        for pattern, attr in (
            (KNOWLEDGE_RE, "knowledge_tags"),
            (FOCUS_RE, "focus_tags"),
            (EXAM_RE, "exam_tags"),
            (PROBLEM_RE, "problem_tags"),
            (EXPERIMENT_RE, "experiment_tags"),
        ):
            match = pattern.match(line)
            if match:
                _append_unique(getattr(current, attr), match.group(1))
                break
        else:
            if "实验" in current.title:
                numbered_match = NUMBERED_ITEM_RE.match(line)
                if numbered_match:
                    _append_unique(current.experiment_tags, numbered_match.group(1))

    return chapters


@lru_cache(maxsize=1)
def load_physics_taxonomy() -> dict[str, ChapterTaxonomy]:
    merged: dict[str, ChapterTaxonomy] = {}
    for path in _iter_markdown_files():
        for item in _parse_markdown_taxonomy(path):
            key = _normalize_for_match(item.title)
            if not key:
                continue
            current = merged.get(key)
            if current is None:
                merged[key] = item
                continue
            for source_file in item.source_files:
                if source_file not in current.source_files:
                    current.source_files.append(source_file)
            for attr in ("knowledge_tags", "focus_tags", "exam_tags", "problem_tags", "experiment_tags"):
                for value in getattr(item, attr):
                    _append_unique(getattr(current, attr), value)
    return merged


def find_chapter_taxonomy(
    title: str,
    *,
    chapter_code: str | None = None,
    chapter_keywords: list[str] | None = None,
) -> ChapterTaxonomy | None:
    taxonomy = load_physics_taxonomy()
    candidates = [
        _normalize_for_match(title),
        _normalize_for_match(chapter_code or ""),
        *[_normalize_for_match(item) for item in (chapter_keywords or [])],
    ]
    candidates = [item for item in candidates if item]
    if not candidates:
        return None

    for candidate in candidates:
        exact = taxonomy.get(candidate)
        if exact:
            return exact

    best: ChapterTaxonomy | None = None
    best_score = -1
    for normalized_title, chapter in taxonomy.items():
        for candidate in candidates:
            if candidate in normalized_title or normalized_title in candidate:
                score = min(len(candidate), len(normalized_title)) * 10
            else:
                overlap = {char for char in candidate if char in normalized_title}
                score = len(overlap)
            if score > best_score:
                best_score = score
                best = chapter
    return best


def match_kp_taxonomy_labels(
    kp_name: str,
    chapter_taxonomy: ChapterTaxonomy | None,
    *,
    aliases: list[str] | None = None,
    description: str | None = None,
) -> dict[str, list[str]]:
    if chapter_taxonomy is None:
        return {
            "knowledge_tags": [],
            "focus_tags": [],
            "exam_tags": [],
            "problem_tags": [],
            "experiment_tags": [],
        }

    search_blob = " ".join(
        part for part in [kp_name, *(aliases or []), description or ""] if part
    )
    normalized_blob = _normalize_for_match(search_blob)

    def pick(items: list[str]) -> list[str]:
        if not normalized_blob:
            return items[:6]
        matched = [
            item
            for item in items
            if _normalize_for_match(item) and _normalize_for_match(item) in normalized_blob
        ]
        return (matched or items)[:6]

    return {
        "knowledge_tags": pick(chapter_taxonomy.knowledge_tags),
        "focus_tags": pick(chapter_taxonomy.focus_tags),
        "exam_tags": pick(chapter_taxonomy.exam_tags),
        "problem_tags": pick(chapter_taxonomy.problem_tags),
        "experiment_tags": pick(chapter_taxonomy.experiment_tags),
    }
