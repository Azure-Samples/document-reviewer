from unittest.mock import AsyncMock

import pytest
from azure.core.exceptions import ResourceExistsError

from document_review.state import ReviewRecord, ReviewStore


def _record(*, status: str, stage: str) -> ReviewRecord:
    return ReviewRecord(
        partition_key="a" * 32,
        row_key="b" * 64,
        claim_token="c" * 32,
        status=status,
        stage=stage,
        source_hash="d" * 64,
        file_name="review.pdf",
        web_url="https://contoso.sharepoint.com/review.pdf",
        failure_code="",
        page_count=1,
        etag='"etag"',
        entity={"Attempt": 1},
    )


@pytest.mark.asyncio
async def test_existing_indeterminate_publish_is_never_reclaimed() -> None:
    table = AsyncMock()
    table.create_entity.side_effect = ResourceExistsError("exists")
    store = ReviewStore(table, AsyncMock(), stale_seconds=0)
    store._get = AsyncMock(
        return_value=_record(status="indeterminate", stage="publishing")
    )
    store._reclaim = AsyncMock()

    result = await store.claim(
        site_url="https://contoso.sharepoint.com/sites/reviews",
        library_name="Documents",
        path="/Shared Documents/Document Reviews/review.pdf",
        file_name="review.pdf",
        web_url="https://contoso.sharepoint.com/review.pdf",
        size=100,
        etag='"v1"',
        last_modified="",
        identifier="item-1",
    )

    assert result.status == "publication_unknown"
    store._reclaim.assert_not_awaited()


@pytest.mark.asyncio
async def test_begin_publish_enters_at_most_once_state() -> None:
    store = ReviewStore(AsyncMock(), AsyncMock(), stale_seconds=900)
    prepared = _record(status="processing", stage="prepared_review")
    publishing = _record(status="indeterminate", stage="publishing")
    store.get_active = AsyncMock(return_value=prepared)
    store._replace = AsyncMock(return_value=publishing)

    result = await store.begin_publish(prepared.reference, "review")

    assert result == publishing
    store._replace.assert_awaited_once_with(
        prepared,
        Status="indeterminate",
        Stage="publishing",
        Outcome="review",
    )
