"""Load and validate application settings supplied by the deployment."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_PAGES = 50
MAX_EXTRACTED_CHARACTERS = 200_000
CLAIM_STALE_SECONDS = 15 * 60
CONTEXT_TTL_SECONDS = 15 * 60


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Required setting {name} is missing.")
    return value


def _https_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ConfigurationError(f"{name} must be an HTTPS URL without a query or fragment.")
    return value.rstrip("/")


def _validate_team(group_id: str, channel_id: str) -> None:
    try:
        uuid.UUID(group_id)
    except ValueError as error:
        raise ConfigurationError("TEAMS_GROUP_ID must be a GUID.") from error
    if not channel_id.startswith("19:") or "@thread.tacv2" not in channel_id:
        raise ConfigurationError(
            "TEAMS_CHANNEL_ID must identify a standard Microsoft Teams channel."
        )


@dataclass(frozen=True)
class Settings:
    sharepoint_site_url: str
    sharepoint_library_name: str
    sharepoint_folder_path: str
    sharepoint_connection_runtime_url: str
    teams_connection_runtime_url: str
    teams_group_id: str
    teams_channel_id: str
    document_intelligence_endpoint: str
    table_endpoint: str
    table_name: str = "DocumentReviews"
    managed_identity_client_id: str = ""
    max_document_bytes: int = MAX_DOCUMENT_BYTES
    max_document_pages: int = MAX_DOCUMENT_PAGES
    max_extracted_characters: int = MAX_EXTRACTED_CHARACTERS
    claim_stale_seconds: int = CLAIM_STALE_SECONDS
    context_ttl_seconds: int = CONTEXT_TTL_SECONDS

    @classmethod
    def from_environment(cls) -> Settings:
        group_id = _required("TEAMS_GROUP_ID")
        channel_id = _required("TEAMS_CHANNEL_ID")
        _validate_team(group_id, channel_id)

        folder_path = _required("SHAREPOINT_FOLDER_PATH")
        if not folder_path.startswith("/"):
            raise ConfigurationError("SHAREPOINT_FOLDER_PATH must start with '/'.")

        return cls(
            sharepoint_site_url=_https_url(
                "SHAREPOINT_SITE_URL", _required("SHAREPOINT_SITE_URL")
            ),
            sharepoint_library_name=_required("SHAREPOINT_LIBRARY_NAME"),
            sharepoint_folder_path=folder_path,
            sharepoint_connection_runtime_url=_https_url(
                "SHAREPOINTONLINE_CONNECTION_RUNTIME_URL",
                _required("SHAREPOINTONLINE_CONNECTION_RUNTIME_URL"),
            ),
            teams_connection_runtime_url=_https_url(
                "TEAMS_CONNECTION_RUNTIME_URL",
                _required("TEAMS_CONNECTION_RUNTIME_URL"),
            ),
            teams_group_id=group_id,
            teams_channel_id=channel_id,
            document_intelligence_endpoint=_https_url(
                "DOCUMENT_INTELLIGENCE_ENDPOINT",
                _required("DOCUMENT_INTELLIGENCE_ENDPOINT"),
            ),
            table_endpoint=_https_url(
                "DOCUMENT_REVIEW_TABLE_ENDPOINT",
                _required("DOCUMENT_REVIEW_TABLE_ENDPOINT"),
            ),
            table_name=os.getenv(
                "DOCUMENT_REVIEW_TABLE_NAME", "DocumentReviews"
            ).strip()
            or "DocumentReviews",
            managed_identity_client_id=os.getenv("AZURE_CLIENT_ID", "").strip(),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
