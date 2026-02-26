import html
import re


_REAL_HTML_PATTERN = re.compile(r"<!doctype|<html\b|<head\b|<body\b", re.IGNORECASE)
_ESCAPED_HTML_PATTERN = re.compile(r"&lt;\s*!doctype|&lt;\s*html\b|&lt;\s*head\b|&lt;\s*body\b", re.IGNORECASE)
_PARAGRAPH_PATTERN = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_BREAK_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)


def is_real_html(text: str) -> bool:
    return bool(_REAL_HTML_PATTERN.search(text or ""))


def is_escaped_html(text: str) -> bool:
    return bool(_ESCAPED_HTML_PATTERN.search(text or ""))


def decode_escaped_html(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""

    paragraphs = _PARAGRAPH_PATTERN.findall(value)
    if paragraphs:
        chunks = paragraphs
    else:
        chunks = [value]

    decoded_parts: list[str] = []
    for chunk in chunks:
        normalized = _BREAK_PATTERN.sub("\n", chunk)
        decoded = html.unescape(normalized)
        decoded_parts.append(decoded.strip())

    return "\n".join(part for part in decoded_parts if part).strip()


def repair_html_preview(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if is_real_html(raw):
        return None
    if not is_escaped_html(raw):
        return None

    decoded = decode_escaped_html(raw)
    if not decoded or not is_real_html(decoded):
        return None
    return decoded
