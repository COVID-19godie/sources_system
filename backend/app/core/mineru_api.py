import html
import re
import time
import uuid
import zipfile
from io import BytesIO
from typing import Any

import requests

from app.core.config import settings


class MinerUAPIError(RuntimeError):
    pass


def _slug_name(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip())
    return value.strip("-") or "text"


def _text_to_html_document(text: str, title: str) -> str:
    escaped = html.escape(text).replace("\n", "<br/>\n")
    return (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        f"<title>{html.escape(title)}</title></head><body><article>{escaped}"
        "</article></body></html>"
    )


def _token_header() -> dict[str, str]:
    if not settings.MINERU_API_TOKEN:
        raise MinerUAPIError("MINERU_API_TOKEN is not configured")
    return {"Authorization": f"Bearer {settings.MINERU_API_TOKEN}"}


def _request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    timeout = kwargs.pop("timeout", settings.MINERU_HTTP_TIMEOUT_SECONDS)
    response = requests.request(method, url, timeout=timeout, **kwargs)
    if response.status_code >= 400:
        raise MinerUAPIError(f"MinerU request failed: {response.status_code}")

    try:
        data = response.json()
    except ValueError as error:
        raise MinerUAPIError("MinerU returned non-JSON response") from error

    if not isinstance(data, dict):
        raise MinerUAPIError("MinerU returned unexpected response")

    if data.get("code") not in (None, 0):
        message = data.get("msg") or "MinerU API error"
        raise MinerUAPIError(str(message))

    return data


def request_create_batch(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.MINERU_API_BASE_URL}/file-urls/batch"
    return _request_json("POST", url, headers=_token_header(), json=payload)


def request_batch_result(batch_id: str) -> dict[str, Any]:
    url = f"{settings.MINERU_API_BASE_URL}/extract-results/batch/{batch_id}"
    return _request_json("GET", url, headers=_token_header())


def upload_to_presigned_url(upload_url: str, payload: bytes) -> None:
    response = requests.put(
        upload_url,
        data=payload,
        headers={"Content-Type": "application/octet-stream"},
        timeout=settings.MINERU_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise MinerUAPIError(f"MinerU file upload failed: {response.status_code}")


def download_binary(url: str) -> bytes:
    response = requests.get(url, timeout=settings.MINERU_HTTP_TIMEOUT_SECONDS)
    if response.status_code >= 400:
        raise MinerUAPIError(f"MinerU file download failed: {response.status_code}")
    return response.content


def extract_markdown_from_zip(zip_bytes: bytes) -> str:
    try:
        archive = zipfile.ZipFile(BytesIO(zip_bytes))
    except zipfile.BadZipFile as error:
        raise MinerUAPIError("MinerU zip file is invalid") from error

    with archive:
        markdown_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".md") and not name.endswith("/") and "__MACOSX" not in name
        ]
        if not markdown_files:
            raise MinerUAPIError("MinerU output does not contain markdown file")

        markdown_files.sort(
            key=lambda item: archive.getinfo(item).file_size,
            reverse=True,
        )
        content = archive.read(markdown_files[0])

    return content.decode("utf-8", errors="ignore")


def extract_first_result_item(official_result: dict[str, Any]) -> dict[str, Any] | None:
    result_list = official_result.get("data", {}).get("extract_result") or []
    if not result_list:
        return None
    return result_list[0]


def create_batch_and_upload_bytes(
    payload: bytes,
    filename: str,
    parse_options: dict[str, Any] | None = None,
) -> str:
    options = dict(parse_options or {})
    options["files"] = [{"name": filename, "data_id": str(uuid.uuid4())}]
    if not options.get("backend"):
        options["backend"] = "pipeline"
    if not options.get("parse_mode"):
        options["parse_mode"] = "auto"
    if not options.get("model_version"):
        options["model_version"] = settings.MINERU_MODEL_VERSION

    data = request_create_batch(options)
    batch_id = data.get("data", {}).get("batch_id")
    file_urls = data.get("data", {}).get("file_urls") or []
    upload_url = file_urls[0] if file_urls else None

    if not batch_id or not upload_url:
        raise MinerUAPIError("MinerU upload URL response is invalid")

    upload_to_presigned_url(upload_url, payload)
    return str(batch_id)


def text_to_markdown_with_mineru(text: str, title: str | None = None) -> str:
    clean_text = text.strip()
    if not clean_text:
        return ""

    doc_title = title or "text-to-md"
    file_name = f"{_slug_name(doc_title)}.html"
    html_doc = _text_to_html_document(clean_text, doc_title)
    batch_id = create_batch_and_upload_bytes(
        payload=html_doc.encode("utf-8"),
        filename=file_name,
        parse_options={
            "enable_formula": True,
            "language": "ch",
            "layout_model": "doclayout_yolo",
        },
    )

    deadline = time.monotonic() + settings.MINERU_POLL_TIMEOUT_SECONDS
    zip_url = None
    while time.monotonic() < deadline:
        result = request_batch_result(batch_id)
        first = extract_first_result_item(result)
        if not first:
            time.sleep(settings.MINERU_POLL_INTERVAL_SECONDS)
            continue

        state = str(first.get("state") or "").lower()
        if state == "failed":
            raise MinerUAPIError("MinerU parse failed")
        if state != "done":
            time.sleep(settings.MINERU_POLL_INTERVAL_SECONDS)
            continue

        zip_url = first.get("full_zip_url")
        if zip_url:
            break
        raise MinerUAPIError("MinerU result missing full_zip_url")

    if not zip_url:
        raise MinerUAPIError("MinerU parse timeout")

    return extract_markdown_from_zip(download_binary(zip_url))
