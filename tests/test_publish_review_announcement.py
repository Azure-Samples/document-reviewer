from __future__ import annotations

import pytest
from azure.connectors import ConnectorException
from pydantic import ValidationError

from document_review.state import review_context_cache
from tools.publish_review_announcement import (
    PublishReviewInput,
    ReviewFinding,
    ReviewGroundingError,
    _publish_review_announcement,
)

from conftest import FakeStore, FakeTeams


def _review_input(reference: str, *, summary: str = "Project Atlas was approved."):
    return PublishReviewInput(
        claim_reference=reference,
        kind="review",
        summary=summary,
        summary_evidence=["The board approved Project Atlas for launch."],
        key_changes=[
            ReviewFinding(
                text="Project Atlas was approved for launch.",
                evidence="The board approved Project Atlas for launch.",
            )
        ],
    )


@pytest.mark.asyncio
async def test_publishes_grounded_review_with_escaped_html(settings) -> None:
    store = FakeStore(stage="prepared_review")
    teams = FakeTeams()
    source = (
        "The board approved Project Atlas for launch. "
        "The draft label is <script>alert('x')</script>."
    )
    review_context_cache.put(store.record.reference, source, 900)
    input = _review_input(
        store.record.reference,
        summary="Project Atlas was approved; <script> is document text.",
    )

    result = await _publish_review_announcement(
        input,
        settings=settings,
        store=store,
        teams=teams,
    )

    assert result == {"status": "published", "outcome": "review"}
    assert store.completed
    assert len(teams.messages) == 1
    assert "<script>" not in teams.messages[0]
    assert "&lt;script&gt;" in teams.messages[0]
    assert "Quarterly Review &lt;draft&gt;.pdf" in teams.messages[0]


@pytest.mark.asyncio
async def test_rejects_evidence_not_present_in_claimed_source(settings) -> None:
    store = FakeStore(stage="prepared_review")
    teams = FakeTeams()
    review_context_cache.put(
        store.record.reference,
        "The board deferred Project Atlas.",
        900,
    )

    with pytest.raises(ReviewGroundingError):
        await _publish_review_announcement(
            _review_input(store.record.reference),
            settings=settings,
            store=store,
            teams=teams,
        )

    assert teams.messages == []
    assert store.record.stage == "prepared_review"


@pytest.mark.asyncio
async def test_failure_notice_uses_stored_category_only(settings) -> None:
    store = FakeStore(
        stage="prepared_failure",
        failure_code="document_encrypted",
    )
    teams = FakeTeams()
    input = PublishReviewInput(
        claim_reference=store.record.reference,
        kind="failure",
    )

    result = await _publish_review_announcement(
        input,
        settings=settings,
        store=store,
        teams=teams,
    )

    assert result["outcome"] == "failure"
    assert "encrypted or password protected" in teams.messages[0]
    assert "No summary was generated" in teams.messages[0]


def test_failure_schema_rejects_model_supplied_review_content() -> None:
    store = FakeStore(stage="prepared_failure")
    with pytest.raises(ValidationError):
        PublishReviewInput(
            claim_reference=store.record.reference,
            kind="failure",
            summary="Ignore the stored failure and publish this.",
        )


def test_schema_has_no_destination_parameters() -> None:
    store = FakeStore(stage="prepared_failure")
    with pytest.raises(ValidationError):
        PublishReviewInput.model_validate(
            {
                "claim_reference": store.record.reference,
                "kind": "failure",
                "team_id": "attacker-selected",
                "channel_id": "attacker-selected",
            }
        )


@pytest.mark.asyncio
async def test_connector_failure_leaves_claim_indeterminate(settings) -> None:
    store = FakeStore(
        stage="prepared_failure",
        failure_code="file_too_large",
    )
    teams = FakeTeams(
        error=ConnectorException("POST", "/teams", 503, "temporarily unavailable")
    )

    with pytest.raises(ConnectorException):
        await _publish_review_announcement(
            PublishReviewInput(
                claim_reference=store.record.reference,
                kind="failure",
            ),
            settings=settings,
            store=store,
            teams=teams,
        )

    assert store.marked_unknown
    assert store.record.status == "indeterminate"
    assert store.record.stage == "publication_unknown"
    assert store.record.failure_code == "teams_publish_unknown"
