from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import ipaddress
import re
import socket
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from fastapi import HTTPException


MAX_TEXT_CHARS = 1_000_000
MAX_HTML_BYTES = 2_500_000
USER_AGENT = "Mozilla/5.0 (compatible; EduResourceBot/1.0)"
MAX_REDIRECTS = 5

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(slots=True)
class LinkContentResult:
    normalized_url: str
    final_url: str
    title: str
    description: str
    content_text: str
    content_chars: int
    content_truncated: bool
    content_hash: str | None
    parse_error: str | None = None


def _to_http_exception(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _normalize_http_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise _to_http_exception("url is required")
    try:
        parsed = urlparse(value)
    except ValueError as error:
        raise _to_http_exception("invalid url") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise _to_http_exception("url must be http/https")
    normalized, _ = urldefrag(value)
    return normalized


def _is_disallowed_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return True
    if addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return True
    return not addr.is_global


def _resolve_host_ips(host: str, port: int | None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise _to_http_exception("url host can not be resolved") from error

    output: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for row in rows:
        sockaddr = row[4]
        if not sockaddr:
            continue
        ip_raw = sockaddr[0]
        try:
            output.append(ipaddress.ip_address(ip_raw))
        except ValueError:
            continue
    return output


def _assert_public_target(normalized_url: str) -> None:
    parsed = urlparse(normalized_url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise _to_http_exception("invalid url host")
    if host in {"localhost"} or host.endswith(".localhost") or host.endswith(".local"):
        raise _to_http_exception("private/local address is not allowed")

    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        literal = ipaddress.ip_address(host)
        ips.append(literal)
    except ValueError:
        ips.extend(_resolve_host_ips(host, parsed.port))

    if not ips:
        raise _to_http_exception("url host can not be resolved")

    for addr in ips:
        if _is_disallowed_ip(addr):
            raise _to_http_exception("private/local address is not allowed")


def normalize_public_http_url(raw_url: str) -> str:
    normalized = _normalize_http_url(raw_url)
    _assert_public_target(normalized)
    return normalized


def _extract_html_text(html_text: str) -> tuple[str, str, str]:
    text = html_text or ""
    title_match = _TITLE_RE.search(text)
    title = html.unescape(title_match.group(1).strip()) if title_match else ""
    desc_match = _META_DESC_RE.search(text)
    description = html.unescape(desc_match.group(1).strip()) if desc_match else ""

    body = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
    body = re.sub(r"(?is)<[^>]+>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"\s+", " ", body).strip()
    return title[:255], description[:1000], body


def _truncate_content(text: str) -> tuple[str, int, bool]:
    content = text or ""
    chars = len(content)
    if chars <= MAX_TEXT_CHARS:
        return content, chars, False
    return content[:MAX_TEXT_CHARS], chars, True


def fetch_link_content(raw_url: str) -> LinkContentResult:
    normalized_url = normalize_public_http_url(raw_url)
    final_url = normalized_url
    title = normalized_url
    description = ""
    content_text = ""
    parse_error: str | None = None

    session = requests.Session()
    response = None
    request_url = normalized_url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            response = session.get(
                request_url,
                timeout=(5, 20),
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = (response.headers.get("Location") or "").strip()
                if not location:
                    raise _to_http_exception("redirect location is empty")
                next_url = normalize_public_http_url(urljoin(request_url, location))
                request_url = next_url
                continue
            response.raise_for_status()
            final_url = request_url
            break
        else:
            raise _to_http_exception("too many redirects")
    except HTTPException:
        raise
    except requests.RequestException as error:
        raise _to_http_exception(f"url fetch failed: {error}") from error
    finally:
        session.close()

    if response is None:
        raise _to_http_exception("url fetch failed")

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "html" not in content_type:
        parse_error = f"unsupported content type: {content_type or 'unknown'}"
    else:
        try:
            payload = response.content[:MAX_HTML_BYTES]
            response.encoding = response.encoding or "utf-8"
            raw_html = payload.decode(response.encoding, errors="ignore")
            title, description, content_text = _extract_html_text(raw_html)
        except Exception as error:  # noqa: BLE001
            parse_error = f"html parse failed: {error}"

    truncated_text, content_chars, content_truncated = _truncate_content(content_text)
    content_hash = hashlib.sha256(truncated_text.encode("utf-8")).hexdigest() if truncated_text else None
    resolved_title = (title or final_url)[:255]
    resolved_description = (description or "")[:1000]

    return LinkContentResult(
        normalized_url=normalized_url,
        final_url=final_url,
        title=resolved_title,
        description=resolved_description,
        content_text=truncated_text,
        content_chars=content_chars,
        content_truncated=content_truncated,
        content_hash=content_hash,
        parse_error=parse_error,
    )
