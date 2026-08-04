import json

from azure_functions_agents.registration import _handlers

from document_review.trigger_payloads import (
    install_connector_trigger_normalizer,
    normalize_connector_trigger_data,
)


EXPECTED_RECORD = {
    "Name": "project-atlas-review-v2.pdf",
    "Path": "/Shared Documents/Document Reviews/project-atlas-review-v2.pdf",
    "Size": 4812,
    "ETag": '"version-2"',
    "LastModified": "2026-08-03T21:00:00Z",
    "Id": "synthetic-project-atlas-review-v2",
    "LinkingUri": "https://contoso.sharepoint.com/sites/reviews/project-atlas-review-v2.pdf",
}


def _records(serialized: str) -> list[dict[str, object]]:
    return json.loads(serialized)["body"]["value"]


def test_normalizes_nested_json_encoded_sharepoint_record() -> None:
    trigger_data = json.dumps(
        {
            "data": {
                "body": json.dumps(
                    {
                        "value": [
                            {
                                "{FilenameWithExtension}": EXPECTED_RECORD["Name"],
                                "Path": "/Shared Documents/Document Reviews/",
                                "{FullPath}": EXPECTED_RECORD["Path"],
                                "{Size}": EXPECTED_RECORD["Size"],
                                "{ETag}": EXPECTED_RECORD["ETag"],
                                "Modified": EXPECTED_RECORD["LastModified"],
                                "ID": 42,
                                "{Identifier}": EXPECTED_RECORD["Id"],
                                "{Link}": EXPECTED_RECORD["LinkingUri"],
                            }
                        ]
                    }
                )
            }
        }
    )

    assert _records(normalize_connector_trigger_data(trigger_data)) == [EXPECTED_RECORD]


def test_normalizes_double_encoded_python_literal_payload() -> None:
    trigger_data = json.dumps(repr({"payload": [EXPECTED_RECORD]}))

    assert _records(normalize_connector_trigger_data(trigger_data)) == [EXPECTED_RECORD]


def test_preserves_unrecognized_payload_for_agent_failure_reporting() -> None:
    trigger_data = '{"body":{"status":"unexpected"}}'

    assert normalize_connector_trigger_data(trigger_data) == trigger_data


def test_installs_normalizer_in_agent_handler(monkeypatch) -> None:
    monkeypatch.setattr(_handlers, "serialize_trigger_data", lambda value: str(value))

    install_connector_trigger_normalizer()

    assert _records(_handlers.serialize_trigger_data(repr({"value": [EXPECTED_RECORD]}))) == [
        EXPECTED_RECORD
    ]


def test_normalizer_install_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(_handlers, "serialize_trigger_data", lambda value: str(value))

    install_connector_trigger_normalizer()
    installed_serializer = _handlers.serialize_trigger_data
    install_connector_trigger_normalizer()

    assert _handlers.serialize_trigger_data is installed_serializer