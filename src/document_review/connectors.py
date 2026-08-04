from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from azure.connectors import (
    AzureIdentityTokenProvider,
    ConnectorException,
    ConnectorClientOptions,
    TeamsClient,
)
from azure.connectors.sharepointonline import SharePointHttpRequestBodyParameters
from azure.connectors.teams import DynamicPostMessageRequest

from config import Settings
from document_review._connector_compat import (
    BinarySafeConnectorHttpClient,
    encode_dataset_path,
)


def _is_local_development() -> bool:
    return os.getenv("AZURE_FUNCTIONS_ENVIRONMENT", "").casefold() == "development"


def create_async_credential(client_id: str) -> Any:
    if _is_local_development():
        from azure.identity.aio import DefaultAzureCredential

        return DefaultAzureCredential()

    if not client_id:
        raise RuntimeError("AZURE_CLIENT_ID is required outside local development.")

    from azure.identity.aio import ManagedIdentityCredential

    return ManagedIdentityCredential(client_id=client_id)


def create_sync_credential(client_id: str) -> Any:
    if _is_local_development():
        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()

    if not client_id:
        raise RuntimeError("AZURE_CLIENT_ID is required outside local development.")

    from azure.identity import ManagedIdentityCredential

    return ManagedIdentityCredential(client_id=client_id)


class SharePointGateway(Protocol):
    async def get_metadata(self, path: str) -> dict[str, object]: ...

    async def download(self, path: str) -> bytes: ...


class TeamsGateway(Protocol):
    async def post_channel_message(self, message_html: str) -> str: ...


class SharePointConnector:
    def __init__(self, settings: Settings) -> None:
        credential = create_async_credential(settings.managed_identity_client_id)
        provider = AzureIdentityTokenProvider(credential)
        self._http_client = BinarySafeConnectorHttpClient(
            provider,
            ConnectorClientOptions(
                max_retry_attempts=3,
                timeout_seconds=30,
                use_exponential_backoff=True,
            ),
        )
        self._runtime_url = settings.sharepoint_connection_runtime_url.rstrip("/")
        self._site_url = settings.sharepoint_site_url

    async def __aenter__(self) -> SharePointConnector:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self._http_client.close()

    async def get_metadata(self, path: str) -> dict[str, object]:
        raw_response = await self._request_file(path)
        response = json.loads(raw_response.text) if raw_response.text else None
        if not isinstance(response, dict):
            raise RuntimeError("SharePoint returned invalid file metadata.")
        server_relative_url = response.get("ServerRelativeUrl")
        if isinstance(server_relative_url, str):
            response["Path"] = self._trigger_relative_path(server_relative_url)
        if "Length" in response:
            response["Size"] = response["Length"]
        return response

    async def download(self, path: str) -> bytes:
        raw_response = await self._request_file(path, content=True)
        response = raw_response.content
        if not isinstance(response, (bytes, bytearray)):
            raise RuntimeError("SharePoint returned an invalid file body.")
        return bytes(response)

    async def _request_file(
        self,
        path: str,
        *,
        content: bool = False,
    ) -> Any:
        dataset = encode_dataset_path(self._site_url)
        request_url = f"{self._runtime_url}/datasets/{dataset}/httprequest"
        server_path = self._server_relative_path(path).replace("'", "''")
        if content:
            uri = f"_api/web/GetFileByServerRelativePath(decodedurl='{server_path}')/$value"
            accept = "application/octet-stream"
        else:
            uri = (
                f"_api/web/GetFileByServerRelativePath(decodedurl='{server_path}')"
                "?$select=Name,ServerRelativeUrl,Length"
            )
            accept = "application/json;odata=nometadata"
        request = SharePointHttpRequestBodyParameters(
            method="GET",
            uri=uri,
            headers={"Accept": accept},
        )
        response = await self._http_client.send_async(
            "POST",
            request_url,
            body=request,
        )
        if not 200 <= response.status < 300:
            raise ConnectorException(
                "POST",
                request_url,
                response.status,
                response.text,
            )
        return response

    def _server_relative_path(self, path: str) -> str:
        normalized_path = "/" + unquote(path).replace("\\", "/").lstrip("/")
        site_path = unquote(urlparse(self._site_url).path).rstrip("/")
        if site_path and not normalized_path.casefold().startswith(
            site_path.casefold() + "/"
        ):
            return site_path + normalized_path
        return normalized_path

    def _trigger_relative_path(self, server_relative_path: str) -> str:
        normalized_path = "/" + unquote(server_relative_path).replace(
            "\\", "/"
        ).lstrip("/")
        site_path = unquote(urlparse(self._site_url).path).rstrip("/")
        if site_path and normalized_path.casefold().startswith(
            site_path.casefold() + "/"
        ):
            return normalized_path[len(site_path) :]
        return normalized_path


class TeamsConnector:
    def __init__(self, settings: Settings) -> None:
        credential = create_async_credential(settings.managed_identity_client_id)
        provider = AzureIdentityTokenProvider(credential)
        self._client = TeamsClient(
            settings.teams_connection_runtime_url,
            token_provider=provider,
            options=ConnectorClientOptions(
                # A retry after an ambiguous send could create a duplicate message.
                max_retry_attempts=1,
                timeout_seconds=30,
                use_exponential_backoff=True,
            ),
        )
        self._group_id = settings.teams_group_id
        self._channel_id = settings.teams_channel_id

    async def __aenter__(self) -> TeamsConnector:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self._client.close()

    async def post_channel_message(self, message_html: str) -> str:
        body = DynamicPostMessageRequest(
            additional_properties={
                "recipient": {
                    "groupId": self._group_id,
                    "channelId": self._channel_id,
                },
                "messageBody": message_html,
            }
        )
        response = await self._client.post_message_to_conversation_async(
            input=body,
            poster="Flow bot",
            location="Channel",
        )
        return _response_identifier(response)


def _response_identifier(response: object) -> str:
    if not isinstance(response, Mapping):
        return ""
    for key in ("id", "messageId", "message_id"):
        value = response.get(key)
        if value:
            return str(value)[:256]
    for value in response.values():
        if isinstance(value, Mapping):
            nested = _response_identifier(value)
            if nested:
                return nested
    return ""
