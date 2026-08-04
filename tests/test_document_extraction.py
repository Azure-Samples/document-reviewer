from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.exceptions import HttpResponseError, ServiceRequestError

import document_review.documents as extraction_module
from document_review.documents import (
    DocumentExtractionError,
    DocumentExtractor,
)


def _install_client(
    monkeypatch,
    *,
    result: object | None = None,
    error: Exception | None = None,
):
    credential = Mock()
    client = Mock()
    poller = Mock()
    if error:
        poller.result.side_effect = error
    else:
        poller.result.return_value = result
    client.begin_analyze_document.return_value = poller
    monkeypatch.setattr(
        extraction_module,
        "create_sync_credential",
        lambda _: credential,
    )
    monkeypatch.setattr(
        extraction_module,
        "DocumentIntelligenceClient",
        lambda **_: client,
    )
    return credential, client


def test_extracts_markdown_with_prebuilt_layout(settings, monkeypatch) -> None:
    credential, client = _install_client(
        monkeypatch,
        result=SimpleNamespace(
            pages=[object(), object()],
            content="# Review\nGrounded content.",
        ),
    )

    result = DocumentExtractor(settings)._extract_sync(b"document", ".pdf")

    assert result.page_count == 2
    assert result.content_markdown == "# Review\nGrounded content."
    _, kwargs = client.begin_analyze_document.call_args
    assert kwargs["output_content_format"] == DocumentContentFormat.MARKDOWN
    client.close.assert_called_once()
    credential.close.assert_called_once()


@pytest.mark.parametrize(
    ("pages", "content", "expected_code"),
    [
        (51, "content", "page_limit_exceeded"),
        (1, "   ", "no_extractable_content"),
        (1, "x" * 2_001, "extracted_content_too_large"),
    ],
)
def test_enforces_extraction_bounds(
    settings,
    monkeypatch,
    pages: int,
    content: str,
    expected_code: str,
) -> None:
    _install_client(
        monkeypatch,
        result=SimpleNamespace(
            pages=[object()] * pages,
            content=content,
        ),
    )

    with pytest.raises(DocumentExtractionError, match=expected_code):
        DocumentExtractor(settings)._extract_sync(b"document", ".pdf")


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            HttpResponseError(message="The document is password protected."),
            "document_encrypted",
        ),
        (
            HttpResponseError(message="The service rejected the document."),
            "extraction_failed",
        ),
        (
            ServiceRequestError("The service is unavailable."),
            "extraction_unavailable",
        ),
    ],
)
def test_maps_document_intelligence_errors(
    settings,
    monkeypatch,
    error: Exception,
    expected_code: str,
) -> None:
    credential, client = _install_client(monkeypatch, error=error)

    with pytest.raises(DocumentExtractionError, match=expected_code):
        DocumentExtractor(settings)._extract_sync(b"document", ".docx")

    client.close.assert_called_once()
    credential.close.assert_called_once()
