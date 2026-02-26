import json
import math
import re
from typing import Any

import requests

from app.core.config import settings


class AIServiceError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY)


def _base_url(path: str) -> str:
    return f"{settings.OPENAI_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _headers() -> dict[str, str]:
    if not settings.OPENAI_API_KEY:
        raise AIServiceError("OPENAI_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _request_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            _base_url(path),
            headers=_headers(),
            json=payload,
            timeout=settings.AI_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise AIServiceError(f"AI request failed: {error}") from error
    if response.status_code >= 400:
        try:
            data = response.json()
            error = data.get("error", {})
            message = error.get("message") or response.text
        except Exception:  # noqa: BLE001
            message = response.text
        raise AIServiceError(f"AI request failed: {response.status_code} {message}")

    try:
        return response.json()
    except ValueError as error:
        raise AIServiceError("AI returned non-JSON response") from error


def _parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except ValueError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except ValueError:
        return {}


def generate_summary_and_tags(
    text: str,
    *,
    title: str | None = None,
    subject: str | None = None,
) -> tuple[str, list[str]]:
    clean_text = text.strip()
    if not clean_text:
        return "", []

    source = clean_text[: settings.AI_MAX_SOURCE_CHARS]
    prompt = (
        "你是教育资源助手。请对输入内容做两件事："
        "1) 生成60-120字中文总结；"
        "2) 生成3-8个中文标签（偏教学语义）。"
        "只返回 JSON：{\"summary\":\"...\",\"tags\":[\"...\"]}。"
    )

    user_text = (
        f"标题: {title or '未命名'}\n"
        f"学科: {subject or '未知'}\n"
        f"内容:\n{source}"
    )
    data = _request_json(
        "/chat/completions",
        {
            "model": settings.AI_CHAT_MODEL,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "response_format": {"type": "json_object"},
        },
    )
    choices = data.get("choices") or []
    content = ""
    if choices:
        content = choices[0].get("message", {}).get("content", "")

    parsed = _parse_json_text(content)
    summary = str(parsed.get("summary") or "").strip()
    tags_raw = parsed.get("tags") or []
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for item in tags_raw:
            value = str(item).strip()
            if value and value not in tags:
                tags.append(value)

    return summary[:500], tags[:12]


def generate_embedding(text: str) -> list[float]:
    clean_text = text.strip()
    if not clean_text:
        return []

    source = clean_text[: settings.AI_MAX_SOURCE_CHARS]
    data = _request_json(
        "/embeddings",
        {
            "model": settings.AI_EMBEDDING_MODEL,
            "input": source,
        },
    )
    rows = data.get("data") or []
    if not rows:
        raise AIServiceError("Embedding response is empty")
    embedding = rows[0].get("embedding") or []
    if not isinstance(embedding, list):
        raise AIServiceError("Embedding format is invalid")
    return [float(item) for item in embedding]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0

    size = min(len(a), len(b))
    if size == 0:
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(size):
        av = float(a[i])
        bv = float(b[i])
        dot += av * bv
        norm_a += av * av
        norm_b += bv * bv

    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def generate_rag_answer(query: str, contexts: list[dict[str, Any]]) -> str:
    if not contexts:
        return ""

    context_lines = []
    for idx, item in enumerate(contexts, start=1):
        context_lines.append(
            f"[{idx}] id={item.get('id')} 标题={item.get('title')}\n"
            f"标签={','.join(item.get('tags') or [])}\n"
            f"摘要={item.get('summary') or item.get('snippet') or ''}"
        )
    context_text = "\n\n".join(context_lines)

    data = _request_json(
        "/chat/completions",
        {
            "model": settings.AI_CHAT_MODEL,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "你是高中物理资源库问答助手。只基于给定上下文回答，简洁、准确，中文输出。",
                },
                {
                    "role": "user",
                    "content": f"问题：{query}\n\n参考上下文：\n{context_text}\n\n请给出回答，并在末尾列出引用资源id。",
                },
            ],
        },
    )
    choices = data.get("choices") or []
    if not choices:
        return ""
    return str(choices[0].get("message", {}).get("content") or "").strip()[:2000]
