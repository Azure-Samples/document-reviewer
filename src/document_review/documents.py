from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlparse

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    DocumentContentFormat,
)
from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)

from config import Settings
from document_review.connectors import create_sync_credential


_MARKDOWN_PUNCTUATION = str.maketrans({character: " " for character in "#*_`>[]"})


@dataclass(frozen=True)
class ExtractionResult:
    content_markdown: str
    page_count: int


class DocumentExtractionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DocumentExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def extract(self, document: bytes, file_extension: str) -> ExtractionResult:
        return await asyncio.to_thread(self._extract_sync, document, file_extension)

    def _extract_sync(self, document: bytes, file_extension: str) -> ExtractionResult:
        credential = create_sync_credential(self._settings.managed_identity_client_id)
        client = DocumentIntelligenceClient(
            endpoint=self._settings.document_intelligence_endpoint,
            credential=credential,
            api_version="2024-11-30",
            retry_total=3,
            connection_timeout=10,
            read_timeout=120,
        )
        try:
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=AnalyzeDocumentRequest(bytes_source=document),
                output_content_format=DocumentContentFormat.MARKDOWN,
            )
            result = poller.result(timeout=300)
        except HttpResponseError as error:
            message = str(error).casefold()
            if "password" in message or "encrypt" in message:
                raise DocumentExtractionError("document_encrypted") from error
            raise DocumentExtractionError("extraction_failed") from error
        except (ServiceRequestError, ServiceResponseError) as error:
            raise DocumentExtractionError("extraction_unavailable") from error
        finally:
            client.close()
            credential.close()

        page_count = len(result.pages or [])
        if page_count > self._settings.max_document_pages:
            raise DocumentExtractionError("page_limit_exceeded")

        content = (result.content or "").strip()
        if not content:
            raise DocumentExtractionError("no_extractable_content")
        if len(content) > self._settings.max_extracted_characters:
            raise DocumentExtractionError("extracted_content_too_large")

        return ExtractionResult(content_markdown=content, page_count=page_count)


def normalize_sharepoint_path(value: str) -> str:
    decoded = unquote(value.strip()).replace("\\", "/")
    decoded = re.sub(r"/+", "/", decoded)
    if not decoded.startswith("/"):
        decoded = "/" + decoded
    if decoded != "/":
        decoded = decoded.rstrip("/")
    return decoded


def is_allowed_source_path(path: str, allowed_folder: str) -> bool:
    normalized_path = normalize_sharepoint_path(path).casefold()
    normalized_folder = normalize_sharepoint_path(allowed_folder).casefold()
    if any(part in {".", ".."} for part in PurePosixPath(normalized_path).parts):
        return False
    return normalized_path.startswith(normalized_folder.rstrip("/") + "/")


def document_name_from_path(path: str, fallback: str) -> str:
    candidate = PurePosixPath(normalize_sharepoint_path(path)).name.strip()
    return candidate or fallback.strip()


def safe_document_url(settings: Settings, candidate: str | None, path: str) -> str:
    site = urlparse(settings.sharepoint_site_url)
    if candidate:
        parsed = urlparse(candidate.strip())
        site_path = site.path.rstrip("/")
        candidate_path = parsed.path.rstrip("/")
        is_site_path = (
            not site_path
            or candidate_path == site_path
            or candidate_path.startswith(site_path + "/")
        )
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.hostname.casefold() == (site.hostname or "").casefold()
            and not parsed.username
            and not parsed.password
            and is_site_path
        ):
            return candidate.strip()

    relative_path = quote(normalize_sharepoint_path(path), safe="/%:@")
    return f"{settings.sharepoint_site_url}{relative_path}"


def metadata_value(metadata: dict[str, object], *names: str) -> object | None:
    exact = {str(key): value for key, value in metadata.items()}
    folded = {key.casefold(): value for key, value in exact.items()}
    for name in names:
        if name in exact:
            return exact[name]
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None


def optional_text(value: object | None, maximum: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:maximum]


def optional_size(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        size = int(str(value))
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


def normalize_evidence(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_MARKDOWN_PUNCTUATION)
    return " ".join(normalized.casefold().split())


def evidence_is_grounded(evidence: str, source: str) -> bool:
    normalized_evidence = normalize_evidence(evidence)
    if len(normalized_evidence) < 12:
        return False
    return normalized_evidence in normalize_evidence(source)
