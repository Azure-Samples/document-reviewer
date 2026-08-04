import html
import logging
from typing import Any, Literal, Protocol

from azure.connectors import ConnectorException
from azure_functions_agents import tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import Settings, get_settings
from document_review.connectors import TeamsConnector, TeamsGateway
from document_review.documents import evidence_is_grounded
from document_review.state import (
    ClaimError,
    ReviewRecord,
    ReviewStore,
    review_context_cache,
)
from tools.prepare_review_document import FAILURE_REASONS


logger = logging.getLogger(__name__)
MAX_TEAMS_HTML_CHARACTERS = 24_000


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=400)
    evidence: str = Field(min_length=12, max_length=400)


class PublishReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_reference: str = Field(
        min_length=130,
        max_length=130,
        pattern=r"^[0-9a-f]{32}\.[0-9a-f]{64}\.[0-9a-f]{32}$",
    )
    kind: Literal["review", "failure"]
    summary: str = Field(default="", max_length=800)
    summary_evidence: list[str] = Field(default_factory=list, max_length=3)
    key_changes: list[ReviewFinding] = Field(default_factory=list, max_length=4)
    risks: list[ReviewFinding] = Field(default_factory=list, max_length=4)
    open_questions: list[ReviewFinding] = Field(default_factory=list, max_length=4)
    review_focus: list[ReviewFinding] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_outcome(self):
        review_fields_present = bool(
            self.summary
            or self.summary_evidence
            or self.key_changes
            or self.risks
            or self.open_questions
            or self.review_focus
        )
        if self.kind == "review":
            if not self.summary.strip():
                raise ValueError("A review publication requires a summary.")
            if not self.summary_evidence:
                raise ValueError("A review publication requires source evidence.")
        elif review_fields_present:
            raise ValueError("A failure publication cannot contain review content.")
        return self


class StoreGateway(Protocol):
    async def get_active(self, reference: str) -> ReviewRecord: ...

    async def begin_publish(self, reference: str, kind: str) -> ReviewRecord: ...

    async def mark_publish_unknown(self, record: ReviewRecord) -> ReviewRecord: ...

    async def complete(
        self, record: ReviewRecord, *, teams_message_id: str
    ) -> ReviewRecord: ...


class ReviewGroundingError(RuntimeError):
    """Raised when proposed review content is not grounded in the extracted source."""


@tool(
    name="publish_review_announcement",
    description=(
        "Publish a claim-bound, evidence-checked document review or factual failure "
        "notice to the single configured Microsoft Teams channel."
    ),
    schema=PublishReviewInput,
)
async def publish_review_announcement(input: PublishReviewInput) -> dict[str, object]:
    settings = get_settings()
    async with ReviewStore.from_settings(settings) as store:
        async with TeamsConnector(settings) as teams:
            return await _publish_review_announcement(
                input,
                settings=settings,
                store=store,
                teams=teams,
            )


async def _publish_review_announcement(
    input: PublishReviewInput,
    *,
    settings: Settings,
    store: StoreGateway,
    teams: TeamsGateway,
) -> dict[str, object]:
    record = await store.get_active(input.claim_reference)
    if record.stage != f"prepared_{input.kind}":
        raise ClaimError("The claim is not ready for this publication outcome.")

    if input.kind == "review":
        context = review_context_cache.get(input.claim_reference)
        if context is None:
            raise ReviewGroundingError(
                "The claim-bound source context expired; the document must be retried."
            )
        _validate_grounding(input, context.content)
        message_html = _build_review_html(record, input)
    else:
        message_html = _build_failure_html(record)

    if len(message_html) > MAX_TEAMS_HTML_CHARACTERS:
        raise ValueError("The Teams announcement exceeds the application limit.")

    publishing = await store.begin_publish(input.claim_reference, input.kind)
    try:
        teams_message_id = await teams.post_channel_message(message_html)
    except ConnectorException:
        await store.mark_publish_unknown(publishing)
        logger.error(
            "document_publish_unknown source=%s category=teams_publish_unknown",
            publishing.source_hash[:16],
        )
        raise

    await store.complete(publishing, teams_message_id=teams_message_id)
    review_context_cache.remove(input.claim_reference)
    logger.info(
        "document_publish_completed source=%s outcome=%s",
        publishing.source_hash[:16],
        input.kind,
    )
    return {
        "status": "published",
        "outcome": input.kind,
    }


def _validate_grounding(input: PublishReviewInput, source: str) -> None:
    unsupported: list[str] = []
    for evidence in input.summary_evidence:
        if not evidence_is_grounded(evidence, source):
            unsupported.append("summary")

    sections = {
        "key_changes": input.key_changes,
        "risks": input.risks,
        "open_questions": input.open_questions,
        "review_focus": input.review_focus,
    }
    for section, findings in sections.items():
        for finding in findings:
            if not evidence_is_grounded(finding.evidence, source):
                unsupported.append(section)

    if unsupported:
        names = ", ".join(sorted(set(unsupported)))
        raise ReviewGroundingError(
            f"One or more evidence excerpts are not present in the source: {names}."
        )


def _build_review_html(record: ReviewRecord, input: PublishReviewInput) -> str:
    title = _document_heading(record)
    sections = [
        title,
        "<h3>Summary</h3>",
        f"<p>{html.escape(input.summary.strip())}</p>",
        _evidence_html(input.summary_evidence),
        _findings_html("Key changes or decisions", input.key_changes),
        _findings_html("Risks", input.risks),
        _findings_html("Open questions", input.open_questions),
        _findings_html("Suggested review focus", input.review_focus),
    ]
    return "".join(sections)


def _build_failure_html(record: ReviewRecord) -> str:
    reason = FAILURE_REASONS.get(record.failure_code)
    if reason is None:
        raise ClaimError("The claim has an invalid failure category.")
    return "".join(
        (
            _document_heading(record, heading="Document review unavailable"),
            f"<p>{html.escape(reason)}</p>",
            "<p>No summary was generated.</p>",
        )
    )


def _document_heading(
    record: ReviewRecord,
    *,
    heading: str = "Document ready for review",
) -> str:
    safe_name = html.escape(record.file_name or "SharePoint document")
    safe_url = html.escape(record.web_url, quote=True)
    return f"<h2>{html.escape(heading)}</h2><p><a href=\"{safe_url}\">{safe_name}</a></p>"


def _evidence_html(evidence: list[str]) -> str:
    excerpts = "".join(
        f"<li><i>{html.escape(item.strip())}</i></li>" for item in evidence
    )
    return f"<p><b>Source evidence</b></p><ul>{excerpts}</ul>"


def _findings_html(title: str, findings: list[ReviewFinding]) -> str:
    safe_title = html.escape(title)
    if not findings:
        return (
            f"<h3>{safe_title}</h3>"
            "<p>None found in the supplied document.</p>"
        )
    items = "".join(
        (
            f"<li>{html.escape(finding.text.strip())}"
            f"<br><i>Evidence: {html.escape(finding.evidence.strip())}</i></li>"
        )
        for finding in findings
    )
    return f"<h3>{safe_title}</h3><ul>{items}</ul>"
