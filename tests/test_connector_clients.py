from types import SimpleNamespace

import pytest
from azure.connectors import ConnectorClientOptions

from document_review import connectors
from document_review._connector_compat import BinarySafeConnectorHttpClient
from document_review.connectors import (
    SharePointConnector,
    TeamsConnector,
)


@pytest.mark.asyncio
async def test_sharepoint_connector_uses_rest_path_for_metadata_and_content() -> None:
    requests = []

    class FakeHttpClient:
        async def send_async(self, method, url, body=None):
            requests.append((method, url, body))
            if body.uri.endswith("/$value"):
                return SimpleNamespace(status=200, text="", content=b"pdf")
            return SimpleNamespace(
                status=200,
                text=(
                    '{"Name":"review.pdf","Length":"3",'
                    '"ServerRelativeUrl":"/sites/reviews/Shared Documents/review%27s.pdf"}'
                ),
                content=b"",
            )

    connector = object.__new__(SharePointConnector)
    connector._http_client = FakeHttpClient()
    connector._runtime_url = "https://runtime.example"
    connector._site_url = "https://contoso.sharepoint.com/sites/reviews"
    path = "/Shared Documents/review's.pdf"

    assert await connector.get_metadata(path) == {
        "Name": "review.pdf",
        "Length": "3",
        "ServerRelativeUrl": "/sites/reviews/Shared Documents/review%27s.pdf",
        "Path": "/Shared Documents/review's.pdf",
        "Size": "3",
    }
    assert await connector.download(path) == b"pdf"

    expected_url = (
        "https://runtime.example/datasets/"
        "https%253A%252F%252Fcontoso.sharepoint.com%252Fsites%252Freviews/"
        "httprequest"
    )
    assert [request[0] for request in requests] == ["POST", "POST"]
    assert [request[1] for request in requests] == [expected_url, expected_url]
    assert "decodedurl='/sites/reviews/Shared Documents/review''s.pdf'" in requests[0][2].uri
    assert requests[0][2].headers == {
        "Accept": "application/json;odata=nometadata"
    }
    assert requests[0][2].uri.endswith("?$select=Name,ServerRelativeUrl,Length")
    assert requests[1][2].uri.endswith("/$value")
    assert requests[1][2].headers == {"Accept": "application/octet-stream"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "content", "expected_text"),
    [
        ("application/pdf", b"%PDF-\xff", ""),
        ("application/json; charset=utf-8", b'{"ok":true}', '{"ok":true}'),
    ],
)
async def test_connector_transport_decodes_only_text_responses(
    content_type: str,
    content: bytes,
    expected_text: str,
) -> None:
    class FakeResponse:
        status = 200
        headers = {"Content-Type": content_type}
        charset = None

        async def read(self):
            return content

    class FakeContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    class FakeSession:
        def request(self, method, url, headers=None, data=None):
            return FakeContext()

    client = object.__new__(BinarySafeConnectorHttpClient)
    client._options = ConnectorClientOptions(max_retry_attempts=1)

    response = await client._send_with_retry(
        FakeSession(),
        "POST",
        "https://runtime.example",
        {},
        None,
    )

    assert response.status == 200
    assert response.text == expected_text
    assert response.content == content


def test_teams_connector_disables_ambiguous_send_retries(
    settings,
    monkeypatch,
) -> None:
    captured_options = []

    class FakeTeamsClient:
        def __init__(
            self,
            runtime_url,
            *,
            token_provider,
            options,
        ) -> None:
            captured_options.append(options)

    monkeypatch.setattr(
        connectors,
        "create_async_credential",
        lambda client_id: object(),
    )
    monkeypatch.setattr(connectors, "TeamsClient", FakeTeamsClient)

    TeamsConnector(settings)

    assert captured_options[0].max_retry_attempts == 1
