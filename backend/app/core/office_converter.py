import subprocess
import time
from pathlib import Path
import tempfile
from uuid import uuid4

import requests

from app.core.config import settings
from app.core.file_access_tokens import DISP_INLINE, build_storage_file_path, create_storage_file_token
from app.core import storage


LEGACY_OFFICE_SUFFIXES = {".doc", ".xls", ".ppt"}
PRESENTATION_SUFFIXES = {".ppt", ".pptx"}
PDF_PREVIEW_SUFFIXES = {".doc", ".xls", ".ppt", ".pptx"}


class OfficeConvertError(RuntimeError):
    pass


def is_legacy_office_suffix(suffix: str) -> bool:
    return suffix.lower() in LEGACY_OFFICE_SUFFIXES


def is_legacy_office_key(object_key: str) -> bool:
    return is_legacy_office_suffix(Path(object_key).suffix.lower())


def office_preview_key(object_key: str) -> str:
    prefix = settings.OFFICE_LEGACY_PREVIEW_PREFIX.strip().strip("/")
    normalized = storage.normalize_key(object_key)
    return f"{prefix}/{normalized}.pdf"


def legacy_preview_key(object_key: str) -> str:
    # Backward-compatible alias
    return office_preview_key(object_key)


def convert_office_to_pdf(payload: bytes, suffix: str) -> bytes:
    file_suffix = suffix.lower()
    if file_suffix not in PDF_PREVIEW_SUFFIXES:
        raise OfficeConvertError(f"Unsupported office suffix for PDF preview: {suffix}")
    if not payload:
        raise OfficeConvertError("Input payload is empty")

    with tempfile.TemporaryDirectory(prefix="office_convert_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / f"source{file_suffix}"
        input_path.write_bytes(payload)

        command = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(input_path),
        ]
        try:
            result = subprocess.run(  # noqa: S603
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=settings.LIBREOFFICE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise OfficeConvertError("LibreOffice convert timeout") from error
        except FileNotFoundError as error:
            raise OfficeConvertError("LibreOffice is not installed in runtime") from error

        output_path = tmp_path / "source.pdf"
        if result.returncode != 0 or not output_path.exists():
            stdout = (result.stdout or b"").decode("utf-8", errors="ignore")
            stderr = (result.stderr or b"").decode("utf-8", errors="ignore")
            message = (stderr or stdout).strip() or "Unknown LibreOffice error"
            raise OfficeConvertError(f"LibreOffice convert failed: {message[:400]}")

        pdf_bytes = output_path.read_bytes()
        if not pdf_bytes:
            raise OfficeConvertError("Converted PDF is empty")
        return pdf_bytes


def _download_via_onlyoffice_converter(object_key: str, suffix: str) -> bytes:
    file_suffix = suffix.lower()
    if file_suffix not in PDF_PREVIEW_SUFFIXES:
        raise OfficeConvertError(f"Unsupported office suffix for PDF preview: {suffix}")

    token = create_storage_file_token(
        object_key=object_key,
        disposition=DISP_INLINE,
        user_id=None,
    )
    source_url = f"{settings.ONLYOFFICE_INTERNAL_BASE_URL.rstrip('/')}{build_storage_file_path(token)}"
    converter_url = settings.ONLYOFFICE_CONVERTER_URL.strip() or "http://onlyoffice/converter"

    payload: dict = {
        "async": False,
        "filetype": file_suffix.lstrip("."),
        "key": f"conv_{uuid4().hex}",
        "outputtype": "pdf",
        "title": f"{Path(object_key).stem}.pdf",
        "url": source_url,
    }

    timeout = max(20, settings.LIBREOFFICE_TIMEOUT_SECONDS)
    file_url = ""
    for _ in range(20):
        try:
            response = requests.post(converter_url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as error:
            raise OfficeConvertError(f"OnlyOffice converter request failed: {error}") from error
        except ValueError as error:
            raise OfficeConvertError("OnlyOffice converter returned non-JSON response") from error

        err = int(data.get("error") or 0)
        if err != 0:
            raise OfficeConvertError(f"OnlyOffice converter failed: error={err}")

        file_url = str(data.get("fileUrl") or "").strip()
        if file_url and bool(data.get("endConvert", False)):
            break

        time.sleep(1)
        payload.pop("url", None)
    else:
        raise OfficeConvertError("OnlyOffice converter timeout")

    if not file_url:
        raise OfficeConvertError("OnlyOffice converter returned empty fileUrl")

    try:
        file_response = requests.get(file_url, timeout=timeout)
        file_response.raise_for_status()
    except requests.RequestException as error:
        raise OfficeConvertError(f"OnlyOffice converter download failed: {error}") from error

    if not file_response.content:
        raise OfficeConvertError("OnlyOffice converter returned empty PDF")
    return file_response.content


def convert_legacy_to_pdf(payload: bytes, suffix: str) -> bytes:
    file_suffix = suffix.lower()
    if not is_legacy_office_suffix(file_suffix):
        raise OfficeConvertError(f"Unsupported legacy office suffix: {suffix}")
    return convert_office_to_pdf(payload, suffix)


def ensure_office_pdf_preview(
    object_key: str,
    *,
    force: bool = False,
    allowed_suffixes: set[str] | None = None,
) -> str | None:
    key = storage.normalize_key(object_key)
    suffix = Path(key).suffix.lower()
    if allowed_suffixes is not None:
        if suffix not in allowed_suffixes:
            return None
    elif suffix not in PDF_PREVIEW_SUFFIXES:
        return None

    preview_key = office_preview_key(key)
    if not force and storage.object_exists(preview_key):
        return preview_key

    source = storage.get_object_bytes(key, max_bytes=None)
    try:
        pdf_payload = convert_office_to_pdf(source, suffix)
    except OfficeConvertError:
        pdf_payload = _download_via_onlyoffice_converter(key, suffix)
    storage.upload_bytes(pdf_payload, preview_key, content_type="application/pdf")
    return preview_key


def ensure_legacy_pdf_preview(object_key: str, *, force: bool = False) -> str | None:
    return ensure_office_pdf_preview(
        object_key,
        force=force,
        allowed_suffixes=LEGACY_OFFICE_SUFFIXES,
    )


def ensure_presentation_pdf_preview(object_key: str, *, force: bool = False) -> str | None:
    return ensure_office_pdf_preview(
        object_key,
        force=force,
        allowed_suffixes=PRESENTATION_SUFFIXES,
    )
