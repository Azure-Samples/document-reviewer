from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from config import Settings
from document_review.documents import ExtractionResult
from document_review.state import ClaimResult, ReviewRecord, review_context_cache


@pytest.fixture(autouse=True)
def clear_review_context() -> None:
    review_context_cache.clear()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        sharepoint_site_url="https://contoso.sharepoint.com/sites/reviews",
        sharepoint_library_name="Documents",
        sharepoint_folder_path="/Shared Documents/Document Reviews",
        sharepoint_connection_runtime_url="https://connectors.example/sharepoint",
        teams_connection_runtime_url="https://connectors.example/teams",
        teams_group_id="11111111-1111-1111-1111-111111111111",
        teams_channel_id="19:review-channel@thread.tacv2",
        document_intelligence_endpoint="https://doc.example",
        table_endpoint="https://storage.table.core.windows.net",
        max_document_bytes=100,
        max_document_pages=50,
        max_extracted_characters=2_000,
        claim_stale_seconds=900,
        context_ttl_seconds=900,
    )


def make_record(stage: str = "preparing", failure_code: str = "") -> ReviewRecord:
    return ReviewRecord(
        partition_key="a" * 32,
        row_key="b" * 64,
        claim_token="c" * 32,
        status="processing",
        stage=stage,
        source_hash="d" * 64,
        file_name="Quarterly Review <draft>.pdf",
        web_url="https://contoso.sharepoint.com/sites/reviews/Shared%20Documents/review.pdf",
        failure_code=failure_code,
        page_count=0,
        etag='"etag"',
        entity={"Attempt": 1},
    )


class FakeStore:
    def __init__(
        self,
        *,
        claim_status: str = "claimed",
        stage: str = "preparing",
        failure_code: str = "",
    ) -> None:
        self.record = make_record(stage, failure_code)
        self.claim_status = claim_status
        self.marked_unknown = False
        self.completed = False

    async def claim(self, **kwargs: Any) -> ClaimResult:
        return ClaimResult(self.claim_status, self.record)

    async def get_active(self, reference: str) -> ReviewRecord:
        assert reference == self.record.reference
        return self.record

    async def mark_prepared(self, reference: str, **kwargs: Any) -> ReviewRecord:
        assert reference == self.record.reference
        self.record = replace(
            self.record,
            stage=f"prepared_{kwargs['kind']}",
            failure_code=kwargs.get("failure_code", ""),
            page_count=kwargs.get("page_count", 0),
            file_name=kwargs.get("file_name") or self.record.file_name,
            web_url=kwargs.get("web_url") or self.record.web_url,
        )
        return self.record

    async def begin_publish(self, reference: str, kind: str) -> ReviewRecord:
        assert reference == self.record.reference
        assert self.record.stage == f"prepared_{kind}"
        self.record = replace(
            self.record,
            status="indeterminate",
            stage="publishing",
        )
        return self.record

    async def mark_publish_unknown(self, record: ReviewRecord) -> ReviewRecord:
        assert record == self.record
        self.marked_unknown = True
        self.record = replace(
            self.record,
            status="indeterminate",
            stage="publication_unknown",
            failure_code="teams_publish_unknown",
        )
        return self.record

    async def complete(
        self, record: ReviewRecord, *, teams_message_id: str
    ) -> ReviewRecord:
        assert record == self.record
        assert teams_message_id == "message-123"
        self.completed = True
        self.record = replace(self.record, status="completed", stage="completed")
        return self.record


class FakeSharePoint:
    def __init__(
        self,
        *,
        document: bytes = b"document",
        metadata: dict[str, object] | None = None,
        metadata_error: Exception | None = None,
        download_error: Exception | None = None,
    ) -> None:
        self.document = document
        self.metadata = metadata or {
            "Name": "Quarterly Review.pdf",
            "Path": "/Shared Documents/Document Reviews/Quarterly Review.pdf",
            "Size": len(document),
            "LinkingUri": (
                "https://contoso.sharepoint.com/sites/reviews/"
                "Shared%20Documents/Document%20Reviews/Quarterly%20Review.pdf"
            ),
        }
        self.metadata_error = metadata_error
        self.download_error = download_error
        self.metadata_calls = 0
        self.download_calls = 0
        self.metadata_arguments = []
        self.download_arguments = []

    async def get_metadata(self, path: str) -> dict[str, object]:
        self.metadata_calls += 1
        self.metadata_arguments.append(path)
        if self.metadata_error:
            raise self.metadata_error
        return self.metadata

    async def download(self, path: str) -> bytes:
        self.download_calls += 1
        self.download_arguments.append(path)
        if self.download_error:
            raise self.download_error
        return self.document


class FakeExtractor:
    def __init__(
        self,
        result: ExtractionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or ExtractionResult(
            content_markdown="The board approved Project Atlas for launch.",
            page_count=2,
        )
        self.error = error
        self.calls = 0

    async def extract(self, document: bytes, file_extension: str) -> ExtractionResult:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeTeams:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[str] = []

    async def post_channel_message(self, message_html: str) -> str:
        self.messages.append(message_html)
        if self.error:
            raise self.error
        return "message-123"
