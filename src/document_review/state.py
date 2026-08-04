from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient

from config import Settings
from document_review.connectors import create_async_credential


@dataclass(frozen=True)
class ReviewContext:
    content: str
    expires_at: float


class ReviewContextCache:
    def __init__(self) -> None:
        self._entries: dict[str, ReviewContext] = {}
        self._lock = Lock()

    def put(self, claim_reference: str, content: str, ttl_seconds: int) -> None:
        with self._lock:
            self._discard_expired_locked()
            self._entries[claim_reference] = ReviewContext(
                content=content,
                expires_at=time.monotonic() + ttl_seconds,
            )

    def get(self, claim_reference: str) -> ReviewContext | None:
        with self._lock:
            self._discard_expired_locked()
            return self._entries.get(claim_reference)

    def remove(self, claim_reference: str) -> None:
        with self._lock:
            self._entries.pop(claim_reference, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _discard_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            reference
            for reference, context in self._entries.items()
            if context.expires_at <= now
        ]
        for reference in expired:
            self._entries.pop(reference, None)


review_context_cache = ReviewContextCache()


_REFERENCE_PATTERN = re.compile(
    r"^(?P<partition>[0-9a-f]{32})\.(?P<row>[0-9a-f]{64})\.(?P<token>[0-9a-f]{32})$"
)


class ClaimError(RuntimeError):
    """Raised when a claim reference is invalid or no longer active."""


@dataclass(frozen=True)
class ReviewRecord:
    partition_key: str
    row_key: str
    claim_token: str
    status: str
    stage: str
    source_hash: str
    file_name: str
    web_url: str
    failure_code: str
    page_count: int
    etag: str
    entity: dict[str, Any]

    @property
    def reference(self) -> str:
        return f"{self.partition_key}.{self.row_key}.{self.claim_token}"


@dataclass(frozen=True)
class ClaimResult:
    status: str
    record: ReviewRecord


class ReviewStore:
    def __init__(
        self,
        table_client: TableClient,
        credential: Any,
        stale_seconds: int,
    ) -> None:
        self._table = table_client
        self._credential = credential
        self._stale_seconds = stale_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> ReviewStore:
        credential = create_async_credential(settings.managed_identity_client_id)
        table = TableClient(
            endpoint=settings.table_endpoint,
            table_name=settings.table_name,
            credential=credential,
            retry_total=3,
        )
        return cls(table, credential, settings.claim_stale_seconds)

    async def __aenter__(self) -> ReviewStore:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self._table.close()
        await self._credential.close()

    async def claim(
        self,
        *,
        site_url: str,
        library_name: str,
        path: str,
        file_name: str,
        web_url: str,
        size: int | None,
        etag: str,
        last_modified: str,
        identifier: str,
    ) -> ClaimResult:
        source_hash = hashlib.sha256(
            f"{site_url}|{library_name}|{path}".encode()
        ).hexdigest()
        version_material = "|".join(
            (
                etag,
                last_modified,
                identifier,
                str(size) if size is not None else "",
                path,
            )
        )
        row_key = hashlib.sha256(
            f"{source_hash}|{version_material}".encode()
        ).hexdigest()
        partition_key = source_hash[:32]
        now = _utc_now()
        entity = {
            "PartitionKey": partition_key,
            "RowKey": row_key,
            "Status": "processing",
            "Stage": "preparing",
            "ClaimToken": secrets.token_hex(16),
            "SourceHash": source_hash,
            "VersionHash": row_key,
            "FileName": file_name[:260],
            "WebUrl": web_url[:2048],
            "FileSize": size if size is not None else -1,
            "FailureCode": "",
            "PageCount": 0,
            "ExtractionDurationMs": 0,
            "TeamsMessageId": "",
            "Attempt": 1,
            "CreatedAt": now,
            "UpdatedAt": now,
        }

        try:
            await self._table.create_entity(entity=entity)
        except ResourceExistsError:
            existing = await self._get(partition_key, row_key)
            if existing.status == "completed":
                return ClaimResult("duplicate", existing)
            if existing.status == "indeterminate" or existing.stage == "publishing":
                return ClaimResult("publication_unknown", existing)
            if existing.status == "processing":
                if not self._is_stale(existing):
                    return ClaimResult("in_progress", existing)
            return await self._reclaim(existing)

        return ClaimResult("claimed", await self._get(partition_key, row_key))

    async def get_active(self, reference: str) -> ReviewRecord:
        partition_key, row_key, token = _parse_reference(reference)
        record = await self._get(partition_key, row_key)
        if record.claim_token != token or record.status != "processing":
            raise ClaimError("The claim is not active.")
        return record

    async def mark_prepared(
        self,
        reference: str,
        *,
        kind: str,
        failure_code: str = "",
        page_count: int = 0,
        extraction_duration_ms: int = 0,
        file_name: str = "",
        web_url: str = "",
        file_size: int | None = None,
    ) -> ReviewRecord:
        record = await self.get_active(reference)
        if record.stage != "preparing":
            raise ClaimError("The claim is not in the preparation stage.")
        if kind not in {"review", "failure"}:
            raise ValueError("Prepared kind must be 'review' or 'failure'.")
        changes: dict[str, Any] = {
            "Stage": f"prepared_{kind}",
            "FailureCode": failure_code[:64],
            "PageCount": page_count,
            "ExtractionDurationMs": extraction_duration_ms,
        }
        if file_name:
            changes["FileName"] = file_name[:260]
        if web_url:
            changes["WebUrl"] = web_url[:2048]
        if file_size is not None:
            changes["FileSize"] = file_size
        return await self._replace(record, **changes)

    async def begin_publish(self, reference: str, kind: str) -> ReviewRecord:
        record = await self.get_active(reference)
        if record.stage != f"prepared_{kind}":
            raise ClaimError("The claim outcome does not match the publication request.")
        return await self._replace(
            record,
            Status="indeterminate",
            Stage="publishing",
            Outcome=kind,
        )

    async def mark_publish_unknown(self, record: ReviewRecord) -> ReviewRecord:
        return await self._replace(
            record,
            Status="indeterminate",
            Stage="publication_unknown",
            FailureCode="teams_publish_unknown",
        )

    async def complete(
        self,
        record: ReviewRecord,
        *,
        teams_message_id: str,
    ) -> ReviewRecord:
        return await self._replace(
            record,
            Status="completed",
            Stage="completed",
            TeamsMessageId=teams_message_id[:256],
        )

    async def _reclaim(self, record: ReviewRecord) -> ClaimResult:
        replacement = await self._replace(
            record,
            Status="processing",
            Stage="preparing",
            ClaimToken=secrets.token_hex(16),
            FailureCode="",
            PageCount=0,
            ExtractionDurationMs=0,
            TeamsMessageId="",
            Attempt=int(record.entity.get("Attempt", 1)) + 1,
        )
        return ClaimResult("claimed", replacement)

    async def _get(self, partition_key: str, row_key: str) -> ReviewRecord:
        try:
            entity = await self._table.get_entity(
                partition_key=partition_key,
                row_key=row_key,
            )
        except ResourceNotFoundError as error:
            raise ClaimError("The claim does not exist.") from error
        return _record_from_entity(entity)

    async def _replace(self, record: ReviewRecord, **changes: Any) -> ReviewRecord:
        entity = dict(record.entity)
        entity.update(changes)
        entity["UpdatedAt"] = _utc_now()
        try:
            await self._table.update_entity(
                entity=entity,
                mode=UpdateMode.REPLACE,
                etag=record.etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except ResourceModifiedError as error:
            raise ClaimError("The claim changed concurrently.") from error
        return await self._get(record.partition_key, record.row_key)

    def _is_stale(self, record: ReviewRecord) -> bool:
        updated_at = _parse_datetime(str(record.entity.get("UpdatedAt", "")))
        return (datetime.now(UTC) - updated_at).total_seconds() >= self._stale_seconds


def _record_from_entity(entity: Any) -> ReviewRecord:
    values = dict(entity)
    metadata = getattr(entity, "metadata", {})
    etag = str(metadata.get("etag") or metadata.get("ETag") or "*")
    return ReviewRecord(
        partition_key=str(values["PartitionKey"]),
        row_key=str(values["RowKey"]),
        claim_token=str(values.get("ClaimToken") or ""),
        status=str(values.get("Status") or ""),
        stage=str(values.get("Stage") or ""),
        source_hash=str(values.get("SourceHash") or ""),
        file_name=str(values.get("FileName") or ""),
        web_url=str(values.get("WebUrl") or ""),
        failure_code=str(values.get("FailureCode") or ""),
        page_count=int(values.get("PageCount") or 0),
        etag=etag,
        entity=values,
    )


def _parse_reference(reference: str) -> tuple[str, str, str]:
    match = _REFERENCE_PATTERN.fullmatch(reference)
    if not match:
        raise ClaimError("The claim reference is invalid.")
    return match.group("partition"), match.group("row"), match.group("token")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
