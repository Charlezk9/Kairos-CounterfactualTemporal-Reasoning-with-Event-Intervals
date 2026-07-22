"""Canonical serialization, stable identifiers, and deterministic splits."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Optional

from .schema import InternalSplit, SplitAssignment


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON mappings require string keys")
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not canonical-JSON serializable")


def canonical_json(value: Any) -> str:
    """Serialize a value to deterministic UTF-8 JSON text."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_stable_id(namespace: str, payload: Any) -> str:
    if not namespace.strip():
        raise ValueError("namespace must be non-empty")
    return f"{namespace}:{sha256_canonical(payload)}"


def assign_split(source_id: str, official_split: str) -> SplitAssignment:
    """Preserve official splits and deterministically carve dev from train."""

    if not source_id:
        raise ValueError("source_id must be non-empty")
    if not official_split.strip():
        raise ValueError("official_split must be non-empty")
    if official_split.casefold() != "train":
        return SplitAssignment(official=official_split, internal=None)

    digest = hashlib.sha256(source_id.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], byteorder="big", signed=False) % 10
    internal = InternalSplit.DEV if bucket == 0 else InternalSplit.TRAIN
    return SplitAssignment(official=official_split, internal=internal)
