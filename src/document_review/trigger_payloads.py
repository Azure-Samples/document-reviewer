from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from typing import Any


_FIELD_ALIASES = {
    "Name": ("name", "filenamewithextension"),
    "Path": ("fullpath", "path"),
    "Size": ("size",),
    "ETag": ("etag",),
    "LastModified": ("lastmodified", "modified"),
    "Id": ("identifier", "id"),
    "LinkingUri": ("linkinguri", "weburl", "link"),
}


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _decode_container(value: object) -> object:
    current = value
    for _ in range(5):
        if isinstance(current, (bytes, bytearray)):
            try:
                current = bytes(current).decode("utf-8")
            except UnicodeDecodeError:
                return current
            continue

        if not isinstance(current, str):
            return current

        text = current.strip()
        if not text:
            return current

        parsed: object | None = None
        for decoder in (json.loads, ast.literal_eval):
            try:
                parsed = decoder(text)
                break
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                continue

        if parsed is None or parsed == current:
            return current
        current = parsed

    return current


def _canonical_record(value: Mapping[object, object]) -> dict[str, object] | None:
    fields: dict[str, object] = {}
    for key, item in value.items():
        fields.setdefault(_normalized_key(key), item)

    record: dict[str, object] = {}
    for canonical_name, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in fields and fields[alias] not in (None, ""):
                record[canonical_name] = fields[alias]
                break

    if not isinstance(record.get("Name"), str) or not isinstance(record.get("Path"), str):
        return None
    return record


def _find_records(value: object, *, depth: int = 0) -> list[dict[str, object]]:
    if depth > 12:
        return []

    decoded = _decode_container(value)
    if isinstance(decoded, Mapping):
        record = _canonical_record(decoded)
        if record is not None:
            return [record]

        records: list[dict[str, object]] = []
        for item in decoded.values():
            records.extend(_find_records(item, depth=depth + 1))
        return records

    if isinstance(decoded, (list, tuple)):
        records = []
        for item in decoded:
            records.extend(_find_records(item, depth=depth + 1))
        return records

    return []


def normalize_connector_trigger_data(serialized: str) -> str:
    records = _find_records(serialized)
    if not records:
        return serialized
    return json.dumps({"body": {"value": records}}, ensure_ascii=False, separators=(",", ":"))


def install_connector_trigger_normalizer() -> None:
    from azure_functions_agents.registration import _handlers

    current_serializer = _handlers.serialize_trigger_data
    if getattr(current_serializer, "_document_review_normalizer", False):
        return

    def serialize_trigger_data(trigger_data: object) -> str:
        serialized = current_serializer(trigger_data)
        return normalize_connector_trigger_data(serialized)

    serialize_trigger_data._document_review_normalizer = True  # type: ignore[attr-defined]
    _handlers.serialize_trigger_data = serialize_trigger_data