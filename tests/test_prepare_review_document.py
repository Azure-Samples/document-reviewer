from __future__ import annotations

import pytest
from azure.connectors import ConnectorException

from document_review.documents import DocumentExtractionError
from document_review.state import review_context_cache
from tools.prepare_review_document import (
    PrepareReviewInput,
    _prepare_review_document,
)

from conftest import FakeExtractor, FakeSharePoint, FakeStore


@pytest.mark.asyncio
async def test_ignores_file_outside_allowlisted_folder(settings) -> None:
    store = FakeStore()
    sharepoint = FakeSharePoint()

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="outside.pdf",
            path="/Shared Documents/Outside/outside.pdf",
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result == {"status": "ignored", "reason": "source_not_allowed"}
    assert sharepoint.metadata_calls == 0


@pytest.mark.asyncio
async def test_rejects_oversized_file_before_download(settings) -> None:
    store = FakeStore()
    sharepoint = FakeSharePoint()

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="large.pdf",
            path="/Shared Documents/Document Reviews/large.pdf",
            size=101,
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result["status"] == "failure"
    assert store.record.failure_code == "file_too_large"
    assert sharepoint.metadata_calls == 0
    assert sharepoint.download_calls == 0


@pytest.mark.asyncio
async def test_rejects_unsupported_extension(settings) -> None:
    store = FakeStore()
    sharepoint = FakeSharePoint()

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="notes.txt",
            path="/Shared Documents/Document Reviews/notes.txt",
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result["status"] == "failure"
    assert store.record.failure_code == "unsupported_file_type"
    assert sharepoint.metadata_calls == 0


@pytest.mark.asyncio
async def test_suppresses_completed_duplicate(settings) -> None:
    store = FakeStore(claim_status="duplicate")
    sharepoint = FakeSharePoint()

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="review.pdf",
            path="/Shared Documents/Document Reviews/review.pdf",
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result == {"status": "duplicate"}
    assert sharepoint.metadata_calls == 0


@pytest.mark.asyncio
async def test_suppresses_unknown_publication_without_retry(settings) -> None:
    store = FakeStore(claim_status="publication_unknown")
    sharepoint = FakeSharePoint()

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="review.pdf",
            path="/Shared Documents/Document Reviews/review.pdf",
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result == {"status": "publication_unknown"}
    assert sharepoint.metadata_calls == 0


@pytest.mark.asyncio
async def test_prepares_bounded_content_and_claim_context(settings) -> None:
    store = FakeStore()
    sharepoint = FakeSharePoint(document=b"valid")
    extractor = FakeExtractor()

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="Quarterly Review.pdf",
            path="/Shared Documents/Document Reviews/Quarterly Review.pdf",
            size=5,
            etag='"version-1"',
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=extractor,
    )

    assert result["status"] == "ready"
    assert result["page_count"] == 2
    assert result["content_markdown"] == (
        "The board approved Project Atlas for launch."
    )
    assert store.record.stage == "prepared_review"
    assert review_context_cache.get(store.record.reference) is not None


@pytest.mark.asyncio
async def test_uses_validated_path_for_sharepoint_retrieval(settings) -> None:
    path = "/Shared Documents/Document Reviews/review.pdf"
    sharepoint = FakeSharePoint(
        document=b"valid",
        metadata={
            "Name": "review.pdf",
            "Path": path,
            "Size": 5,
        },
    )

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="review.pdf",
            path=path,
            size=5,
            identifier="trigger-file-id",
        ),
        settings=settings,
        store=FakeStore(),
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result["status"] == "ready"
    assert sharepoint.metadata_arguments == [path]
    assert sharepoint.download_arguments == [path]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    [
        "document_encrypted",
        "extraction_failed",
        "extraction_unavailable",
        "page_limit_exceeded",
        "no_extractable_content",
        "extracted_content_too_large",
    ],
)
async def test_maps_extraction_error_to_factual_failure(
    settings,
    error_code: str,
) -> None:
    store = FakeStore()
    extractor = FakeExtractor(error=DocumentExtractionError(error_code))

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="protected.pdf",
            path="/Shared Documents/Document Reviews/protected.pdf",
            size=8,
        ),
        settings=settings,
        store=store,
        sharepoint=FakeSharePoint(document=b"protected"),
        extractor=extractor,
    )

    assert result["status"] == "failure"
    assert store.record.failure_code == error_code
    assert "summary" not in result


@pytest.mark.asyncio
async def test_maps_sharepoint_failure_without_downloading(settings) -> None:
    store = FakeStore()
    unavailable = ConnectorException(
        "GET",
        "/sharepoint",
        503,
        "temporarily unavailable",
    )
    sharepoint = FakeSharePoint(metadata_error=unavailable)

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="review.pdf",
            path="/Shared Documents/Document Reviews/review.pdf",
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result["status"] == "failure"
    assert store.record.failure_code == "source_metadata_unavailable"
    assert sharepoint.download_calls == 0


@pytest.mark.asyncio
async def test_maps_sharepoint_content_failure(settings) -> None:
    store = FakeStore()
    unavailable = ConnectorException(
        "GET",
        "/sharepoint",
        503,
        "temporarily unavailable",
    )

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="review.pdf",
            path="/Shared Documents/Document Reviews/review.pdf",
        ),
        settings=settings,
        store=store,
        sharepoint=FakeSharePoint(download_error=unavailable),
        extractor=FakeExtractor(),
    )

    assert result["status"] == "failure"
    assert store.record.failure_code == "source_content_unavailable"


@pytest.mark.asyncio
async def test_rejects_canonical_path_outside_allowlist(settings) -> None:
    store = FakeStore()
    sharepoint = FakeSharePoint(
        metadata={
            "Name": "review.pdf",
            "Path": "/Shared Documents/Outside/review.pdf",
            "Size": 8,
        }
    )

    result = await _prepare_review_document(
        PrepareReviewInput(
            name="review.pdf",
            path="/Shared Documents/Document Reviews/review.pdf",
        ),
        settings=settings,
        store=store,
        sharepoint=sharepoint,
        extractor=FakeExtractor(),
    )

    assert result["status"] == "failure"
    assert store.record.failure_code == "source_not_allowed"
    assert sharepoint.download_calls == 0
