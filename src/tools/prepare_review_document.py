from __future__ import annotations

import logging
import time
from pathlib import PurePosixPath
from typing import Any, Protocol

from azure.connectors import ConnectorException
from azure_functions_agents import tool
from pydantic import BaseModel, ConfigDict, Field

from config import Settings, get_settings
from document_review.connectors import SharePointConnector, SharePointGateway
from document_review.documents import (
    DocumentExtractionError,
    DocumentExtractor,
    ExtractionResult,
    document_name_from_path,
    is_allowed_source_path,
    metadata_value,
    normalize_sharepoint_path,
    optional_size,
    optional_text,
    safe_document_url,
)
from document_review.state import (
    ClaimResult,
    ReviewRecord,
    ReviewStore,
    review_context_cache,
)


logger = logging.getLogger(__name__)

FAILURE_REASONS = {
    "unsupported_file_type": "Only PDF and DOCX documents are supported.",
    "file_too_large": "The document is larger than the 10 MB application limit.",
    "source_metadata_unavailable": "The document could not be retrieved from SharePoint.",
    "source_content_unavailable": "The document could not be retrieved from SharePoint.",
    "source_not_allowed": "The document is outside the configured SharePoint folder.",
    "document_encrypted": "The document is encrypted or password protected.",
    "extraction_failed": "Document content extraction failed.",
    "extraction_unavailable": "Document extraction is temporarily unavailable.",
    "page_limit_exceeded": "The document exceeds the 50-page application limit.",
    "no_extractable_content": "No reviewable text was found in the document.",
    "extracted_content_too_large": "The extracted document is too large for this sample.",
}


class PrepareReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=260)
    path: str = Field(min_length=1, max_length=2048)
    size: int | None = Field(default=None, ge=0)
    etag: str = Field(default="", max_length=512)
    last_modified: str = Field(default="", max_length=128)
    identifier: str = Field(default="", max_length=1024)
    web_url: str = Field(default="", max_length=2048)


class ExtractorGateway(Protocol):
    async def extract(self, document: bytes, file_extension: str) -> ExtractionResult: ...


class StoreGateway(Protocol):
    async def claim(self, **kwargs: Any) -> ClaimResult: ...

    async def mark_prepared(self, reference: str, **kwargs: Any) -> ReviewRecord: ...


@tool(
    name="prepare_review_document",
    description=(
        "Validate and claim one SharePoint file, privately retrieve its bytes, "
        "extract bounded Markdown, and return a controlled review or failure outcome."
    ),
    schema=PrepareReviewInput,
)
async def prepare_review_document(input: PrepareReviewInput) -> dict[str, object]:
    settings = get_settings()
    async with ReviewStore.from_settings(settings) as store:
        async with SharePointConnector(settings) as sharepoint:
            return await _prepare_review_document(
                input,
                settings=settings,
                store=store,
                sharepoint=sharepoint,
                extractor=DocumentExtractor(settings),
            )


async def _prepare_review_document(
    input: PrepareReviewInput,
    *,
    settings: Settings,
    store: StoreGateway,
    sharepoint: SharePointGateway,
    extractor: ExtractorGateway,
) -> dict[str, object]:
    path = normalize_sharepoint_path(input.path)
    if not is_allowed_source_path(path, settings.sharepoint_folder_path):
        return {
            "status": "ignored",
            "reason": "source_not_allowed",
        }

    file_name = document_name_from_path(path, input.name)
    web_url = safe_document_url(settings, input.web_url, path)
    claim = await store.claim(
        site_url=settings.sharepoint_site_url,
        library_name=settings.sharepoint_library_name,
        path=path,
        file_name=file_name,
        web_url=web_url,
        size=input.size,
        etag=input.etag,
        last_modified=input.last_modified,
        identifier=input.identifier,
    )
    if claim.status != "claimed":
        logger.info(
            "document_prepare_skipped source=%s status=%s",
            claim.record.source_hash[:16],
            claim.status,
        )
        return {"status": claim.status}

    reference = claim.record.reference
    extension = PurePosixPath(file_name).suffix.casefold()
    if extension not in {".pdf", ".docx"}:
        return await _failure(
            store,
            reference,
            claim.record,
            "unsupported_file_type",
        )
    if input.size is not None and input.size > settings.max_document_bytes:
        return await _failure(
            store,
            reference,
            claim.record,
            "file_too_large",
            file_size=input.size,
        )

    try:
        metadata = await sharepoint.get_metadata(path)
    except ConnectorException:
        return await _failure(
            store,
            reference,
            claim.record,
            "source_metadata_unavailable",
        )

    canonical_path = optional_text(
        metadata_value(metadata, "Path", "FullPath", "{FullPath}"),
        2048,
    )
    if canonical_path:
        canonical_path = normalize_sharepoint_path(canonical_path)
        if not is_allowed_source_path(
            canonical_path, settings.sharepoint_folder_path
        ):
            return await _failure(
                store,
                reference,
                claim.record,
                "source_not_allowed",
            )
        path = canonical_path

    metadata_name = optional_text(
        metadata_value(metadata, "Name", "DisplayName", "{FilenameWithExtension}"),
        260,
    )
    if metadata_name:
        file_name = document_name_from_path(path, metadata_name)
        extension = PurePosixPath(file_name).suffix.casefold()
    metadata_size = optional_size(metadata_value(metadata, "Size", "Length"))
    file_size = metadata_size if metadata_size is not None else input.size
    metadata_url = optional_text(
        metadata_value(metadata, "LinkingUri", "WebUrl", "webUrl", "{Link}"),
        2048,
    )
    web_url = safe_document_url(settings, metadata_url or input.web_url, path)

    if extension not in {".pdf", ".docx"}:
        return await _failure(
            store,
            reference,
            claim.record,
            "unsupported_file_type",
            file_name=file_name,
            web_url=web_url,
            file_size=file_size,
        )
    if file_size is not None and file_size > settings.max_document_bytes:
        return await _failure(
            store,
            reference,
            claim.record,
            "file_too_large",
            file_name=file_name,
            web_url=web_url,
            file_size=file_size,
        )

    try:
        document = await sharepoint.download(path)
    except ConnectorException:
        return await _failure(
            store,
            reference,
            claim.record,
            "source_content_unavailable",
            file_name=file_name,
            web_url=web_url,
            file_size=file_size,
        )
    if len(document) > settings.max_document_bytes:
        return await _failure(
            store,
            reference,
            claim.record,
            "file_too_large",
            file_name=file_name,
            web_url=web_url,
            file_size=len(document),
        )

    started = time.monotonic()
    try:
        extraction = await extractor.extract(document, extension)
    except DocumentExtractionError as error:
        duration_ms = int((time.monotonic() - started) * 1000)
        return await _failure(
            store,
            reference,
            claim.record,
            error.code,
            file_name=file_name,
            web_url=web_url,
            file_size=len(document),
            extraction_duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    prepared = await store.mark_prepared(
        reference,
        kind="review",
        page_count=extraction.page_count,
        extraction_duration_ms=duration_ms,
        file_name=file_name,
        web_url=web_url,
        file_size=len(document),
    )
    review_context_cache.put(
        prepared.reference,
        extraction.content_markdown,
        settings.context_ttl_seconds,
    )
    logger.info(
        "document_prepare_ready source=%s bytes=%d pages=%d duration_ms=%d",
        prepared.source_hash[:16],
        len(document),
        extraction.page_count,
        duration_ms,
    )
    return {
        "status": "ready",
        "claim_reference": prepared.reference,
        "document_name": prepared.file_name,
        "document_url": prepared.web_url,
        "page_count": extraction.page_count,
        "content_markdown": extraction.content_markdown,
    }


async def _failure(
    store: StoreGateway,
    reference: str,
    record: ReviewRecord,
    code: str,
    *,
    file_name: str = "",
    web_url: str = "",
    file_size: int | None = None,
    extraction_duration_ms: int = 0,
) -> dict[str, object]:
    prepared = await store.mark_prepared(
        reference,
        kind="failure",
        failure_code=code,
        extraction_duration_ms=extraction_duration_ms,
        file_name=file_name,
        web_url=web_url,
        file_size=file_size,
    )
    logger.warning(
        "document_prepare_failed source=%s category=%s",
        record.source_hash[:16],
        code,
    )
    return {
        "status": "failure",
        "claim_reference": prepared.reference,
        "failure_reason": FAILURE_REASONS[code],
    }
