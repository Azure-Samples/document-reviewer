"""Compatibility helpers for the pinned azure-connectors preview SDK.

azure-connectors 0.4.0b1 decodes every response body as UTF-8, including
SharePoint file content, and its dataset route requires double URL encoding.
Keep those preview-specific details here so the application connector remains
focused on the document-review workflow.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiohttp import ClientError
from azure.connectors import ConnectorException
from azure.connectors.sdk.http_client import ConnectorHttpClient, _ResponseSnapshot


def encode_dataset_path(dataset: str) -> str:
    return quote(quote(dataset, safe=""), safe="")


class BinarySafeConnectorHttpClient(ConnectorHttpClient):
    async def _send_with_retry(
        self,
        session: Any,
        method: str,
        url: str,
        headers: dict[str, str],
        body: object,
    ) -> _ResponseSnapshot:
        last_exception: ClientError | None = None
        for attempt in range(self._options.max_retry_attempts):
            try:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    data=body,
                ) as response:
                    if (
                        response.status >= 500 or response.status == 429
                    ) and attempt < self._options.max_retry_attempts - 1:
                        await self._delay_retry(attempt)
                        continue

                    content = await response.read()
                    content_type = response.headers.get("Content-Type", "").casefold()
                    is_text = content_type.startswith("text/") or "json" in content_type
                    text = (
                        content.decode(response.charset or "utf-8", errors="replace")
                        if is_text
                        else ""
                    )
                    return _ResponseSnapshot(
                        status=response.status,
                        headers=dict(response.headers),
                        text=text,
                        content=content,
                    )
            except ClientError as error:
                last_exception = error
                if attempt < self._options.max_retry_attempts - 1:
                    await self._delay_retry(attempt)
                    continue
                raise

        if last_exception:
            raise last_exception
        raise ConnectorException(
            "RETRY",
            "Request failed after all retry attempts.",
            0,
            "",
        )