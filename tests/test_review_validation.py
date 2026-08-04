from document_review.documents import (
    evidence_is_grounded,
    is_allowed_source_path,
    safe_document_url,
)


def test_sharepoint_folder_boundary_is_segment_aware() -> None:
    folder = "/Shared Documents/Document Reviews"
    assert is_allowed_source_path(
        "/Shared Documents/Document Reviews/report.pdf",
        folder,
    )
    assert not is_allowed_source_path(
        "/Shared Documents/Document Reviews-Other/report.pdf",
        folder,
    )
    assert not is_allowed_source_path(
        "/Shared Documents/Document Reviews/../Outside/report.pdf",
        folder,
    )


def test_document_url_cannot_escape_configured_site(settings) -> None:
    result = safe_document_url(
        settings,
        "https://contoso.sharepoint.com/sites/other/report.pdf",
        "/Shared Documents/Document Reviews/report.pdf",
    )

    assert result.startswith("https://contoso.sharepoint.com/sites/reviews/")
    assert "/sites/other/" not in result


def test_markdown_formatting_does_not_break_evidence_match() -> None:
    source = "## Decision\nThe **board approved** Project Atlas for launch."
    assert evidence_is_grounded(
        "The board approved Project Atlas for launch.",
        source,
    )
    assert not evidence_is_grounded(
        "The board rejected Project Atlas for launch.",
        source,
    )
