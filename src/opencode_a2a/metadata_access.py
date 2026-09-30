from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message as ProtoMessage


def extract_namespaced_value(
    source: Mapping[str, Any] | None,
    *,
    namespace: str,
    path: tuple[str, ...],
) -> Any | None:
    normalized_source = _normalize_mapping(source)
    if normalized_source is None:
        return None

    current: Any = normalized_source.get(namespace)
    current_mapping = _normalize_mapping(current)
    if current_mapping is None:
        return None
    current = current_mapping

    for part in path:
        current_mapping = _normalize_mapping(current)
        if current_mapping is None:
            return None
        current = current_mapping.get(part)
    return current


def extract_first_namespaced_string(
    sources: Iterable[Mapping[str, Any] | None],
    *,
    namespace: str,
    path: tuple[str, ...],
) -> str | None:
    for source in sources:
        candidate = extract_namespaced_value(source, namespace=namespace, path=path)
        if isinstance(candidate, str):
            value = candidate.strip()
            if value:
                return value
    return None


def extract_first_namespaced_value(
    sources: Iterable[Mapping[str, Any] | None],
    *,
    namespace: str,
    path: tuple[str, ...],
    expected_type: type | tuple[type, ...] = Mapping,
) -> Any | None:
    """First namespaced value whose type matches ``expected_type``.

    Unlike the string variant this returns non-scalar values (mappings,
    lists) — used by the structured-output contract to pass a JSON Schema
    format object through to the upstream request payload.
    """
    for source in sources:
        candidate = extract_namespaced_value(source, namespace=namespace, path=path)
        if isinstance(candidate, expected_type):
            if candidate is Mapping or isinstance(candidate, type):
                continue
            return candidate
    return None


def _normalize_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, ProtoMessage):
        normalized = MessageToDict(value)
        return normalized if isinstance(normalized, Mapping) else None
    if isinstance(value, Mapping):
        try:
            return value if isinstance(value, dict) else dict(value)
        except Exception:
            return None
    return None
