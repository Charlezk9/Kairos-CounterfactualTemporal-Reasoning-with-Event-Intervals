"""Strict, non-adjudicating statistics for completed human-audit submissions."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .ids import canonical_json
from .relation_human_audit import REVIEW_SCHEMA_VERSION, SAMPLE_SIZE


RESULT_SCHEMA_VERSION = "relation-audit-result-v1"
ADJUDICATION_SCHEMA_VERSION = "relation-audit-adjudication-v1"
KAPPA_THRESHOLD = 0.80
VALIDITY_THRESHOLD = 0.95
_SUBMISSION_LIMIT = 8 * 1024 * 1024
_LINE_LIMIT = 64 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BOOLEAN_FIELDS = (
    "event_spans_valid",
    "original_relation_valid",
    "counterfactual_relation_valid",
    "rewrite_grammatical",
    "non_target_content_preserved",
    "overall_valid",
)
_REVIEW_KEYS = {
    "schema_version",
    "audit_item_id",
    "reviewer_slot",
    *_BOOLEAN_FIELDS,
    "notes",
}
_ADJUDICATION_KEYS = {
    "schema_version",
    "audit_item_id",
    "overall_valid",
    "notes",
}


class RelationAuditResultError(ValueError):
    """A filled submission, adjudication, binding, or statistic is invalid."""


def _fail(message: str) -> None:
    raise RelationAuditResultError(message) from None


def _hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        _fail(f"{name} is invalid")
    return value


def _notes(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 1000:
        _fail(f"{name} must be null or at most 1000 characters")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(f"{name} is not valid Unicode")
    return value


def _strict_object(payload: bytes, name: str) -> Mapping[str, Any]:
    duplicates: list[str] = []

    def pairs(values: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        result = {}
        for key, value in values:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    def reject_constant(unused: str) -> Any:
        _fail(f"{name} contains a non-finite number")

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RelationAuditResultError(f"{name} is not strict UTF-8 JSON") from error
    if duplicates:
        _fail(f"{name} contains duplicate JSON keys")
    if not isinstance(value, MappingABC) or any(
        not isinstance(key, str) for key in value
    ):
        _fail(f"{name} must be a string-keyed object")
    if canonical_json(value).encode("utf-8") != payload:
        _fail(f"{name} is not canonical JSON")
    return value


def _jsonl(payload: bytes, name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _SUBMISSION_LIMIT:
        _fail(f"{name} bytes are empty or exceed the limit")
    if not payload.endswith(b"\n"):
        _fail(f"{name} must end with LF")
    lines = payload.splitlines(keepends=True)
    if len(lines) != SAMPLE_SIZE or any(
        not line.endswith(b"\n") or len(line) > _LINE_LIMIT for line in lines
    ):
        _fail(f"{name} line count or line framing differs")
    return tuple(
        _strict_object(line[:-1], f"{name} line {index}")
        for index, line in enumerate(lines, start=1)
    )


def _expected_ids(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        _fail("expected audit item IDs must be a sequence")
    result = tuple(value)
    if (
        len(result) != SAMPLE_SIZE
        or any(not isinstance(item, str) or not item for item in result)
        or len(set(result)) != SAMPLE_SIZE
    ):
        _fail("expected audit item IDs are invalid")
    return result


def _review_values(
    payload: bytes, slot: str, expected_ids: tuple[str, ...]
) -> tuple[Mapping[str, bool], ...]:
    if slot not in {"A", "B"}:
        _fail("reviewer slot is invalid")
    rows = _jsonl(payload, f"reviewer {slot} submission")
    result = []
    for index, (row, expected_id) in enumerate(zip(rows, expected_ids), start=1):
        if set(row) != _REVIEW_KEYS:
            _fail(f"reviewer {slot} line {index} keys differ")
        if (
            row["schema_version"] != REVIEW_SCHEMA_VERSION
            or row["audit_item_id"] != expected_id
            or row["reviewer_slot"] != slot
        ):
            _fail(f"reviewer {slot} line {index} identity differs")
        values = {}
        for field in _BOOLEAN_FIELDS:
            if type(row[field]) is not bool:
                _fail(f"reviewer {slot} line {index} field {field} is not Boolean")
            values[field] = row[field]
        _notes(row["notes"], f"reviewer {slot} line {index} notes")
        if values["overall_valid"] != all(
            values[field] for field in _BOOLEAN_FIELDS[:-1]
        ):
            _fail(f"reviewer {slot} line {index} overall validity differs")
        result.append(values)
    return tuple(result)


def _adjudication_values(
    payload: bytes,
    expected_ids: tuple[str, ...],
    reviewer_a: Sequence[Mapping[str, bool]],
    reviewer_b: Sequence[Mapping[str, bool]],
) -> tuple[bool, ...]:
    rows = _jsonl(payload, "authors adjudication")
    result = []
    for index, (row, expected_id, first, second) in enumerate(
        zip(rows, expected_ids, reviewer_a, reviewer_b), start=1
    ):
        if set(row) != _ADJUDICATION_KEYS:
            _fail(f"adjudication line {index} keys differ")
        if (
            row["schema_version"] != ADJUDICATION_SCHEMA_VERSION
            or row["audit_item_id"] != expected_id
            or type(row["overall_valid"]) is not bool
        ):
            _fail(f"adjudication line {index} identity or value differs")
        _notes(row["notes"], f"adjudication line {index} notes")
        a_value = first["overall_valid"]
        b_value = second["overall_valid"]
        if a_value == b_value and row["overall_valid"] != a_value:
            _fail(f"adjudication line {index} changes reviewer agreement")
        result.append(row["overall_valid"])
    return tuple(result)


@dataclass(frozen=True)
class AuditResult:
    packet_manifest_sha256: str
    audit_items_sha256: str
    reviewer_a_sha256: str
    reviewer_b_sha256: str
    adjudication_sha256: str
    sample_size: int
    confusion: Mapping[str, int]
    observed_agreement: float
    expected_agreement: float
    cohen_kappa: float | None
    field_agreement: Mapping[str, Mapping[str, float | int]]
    adjudicated_valid_count: int
    adjudicated_validity: float
    gate_failures: tuple[str, ...]
    training_gate_passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "confusion", MappingProxyType(dict(self.confusion)))
        object.__setattr__(
            self,
            "field_agreement",
            MappingProxyType(
                {
                    field: MappingProxyType(dict(values))
                    for field, values in self.field_agreement.items()
                }
            ),
        )
        object.__setattr__(self, "gate_failures", tuple(self.gate_failures))

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "PASSED" if self.training_gate_passed else "BLOCKED",
            "input_bindings": {
                "packet_manifest_sha256": self.packet_manifest_sha256,
                "audit_items_sha256": self.audit_items_sha256,
                "reviewer_a_sha256": self.reviewer_a_sha256,
                "reviewer_b_sha256": self.reviewer_b_sha256,
                "adjudication_sha256": self.adjudication_sha256,
            },
            "sample_size": self.sample_size,
            "overall_valid_agreement": {
                "confusion": dict(self.confusion),
                "observed": self.observed_agreement,
                "expected": self.expected_agreement,
                "cohen_kappa": self.cohen_kappa,
            },
            "field_agreement": {
                key: dict(value) for key, value in self.field_agreement.items()
            },
            "adjudicated": {
                "valid_count": self.adjudicated_valid_count,
                "validity": self.adjudicated_validity,
            },
            "thresholds": {
                "cohen_kappa_minimum": KAPPA_THRESHOLD,
                "adjudicated_validity_minimum": VALIDITY_THRESHOLD,
            },
            "gate_failures": list(self.gate_failures),
            "training_gate_passed": self.training_gate_passed,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


def evaluate_audit_submissions(
    expected_item_ids: Sequence[str],
    packet_manifest_sha256: str,
    audit_items_sha256: str,
    reviewer_a_payload: bytes,
    reviewer_b_payload: bytes,
    adjudication_payload: bytes,
) -> AuditResult:
    """Validate locked human inputs and compute the frozen non-adjudicating gate."""

    item_ids = _expected_ids(expected_item_ids)
    packet_hash = _hex64(packet_manifest_sha256, "packet manifest SHA256")
    items_hash = _hex64(audit_items_sha256, "audit items SHA256")
    reviewer_a = _review_values(reviewer_a_payload, "A", item_ids)
    reviewer_b = _review_values(reviewer_b_payload, "B", item_ids)
    adjudicated = _adjudication_values(
        adjudication_payload, item_ids, reviewer_a, reviewer_b
    )
    a_values = tuple(value["overall_valid"] for value in reviewer_a)
    b_values = tuple(value["overall_valid"] for value in reviewer_b)
    true_true = sum(first and second for first, second in zip(a_values, b_values))
    true_false = sum(first and not second for first, second in zip(a_values, b_values))
    false_true = sum(not first and second for first, second in zip(a_values, b_values))
    false_false = SAMPLE_SIZE - true_true - true_false - false_true
    observed = (true_true + false_false) / SAMPLE_SIZE
    a_true = true_true + true_false
    b_true = true_true + false_true
    expected = (
        a_true * b_true + (SAMPLE_SIZE - a_true) * (SAMPLE_SIZE - b_true)
    ) / (SAMPLE_SIZE * SAMPLE_SIZE)
    kappa = None if expected == 1.0 else (observed - expected) / (1.0 - expected)
    if kappa is not None and not math.isfinite(kappa):
        _fail("computed Cohen's kappa is non-finite")
    field_agreement = {}
    for field in _BOOLEAN_FIELDS:
        count = sum(
            first[field] == second[field]
            for first, second in zip(reviewer_a, reviewer_b)
        )
        field_agreement[field] = {
            "agreement_count": count,
            "agreement_rate": count / SAMPLE_SIZE,
        }
    valid_count = sum(adjudicated)
    validity = valid_count / SAMPLE_SIZE
    failures = []
    if kappa is None:
        failures.append("cohen-kappa-unavailable")
    elif kappa < KAPPA_THRESHOLD:
        failures.append("cohen-kappa-below-threshold")
    if validity < VALIDITY_THRESHOLD:
        failures.append("adjudicated-validity-below-threshold")
    result = AuditResult(
        packet_manifest_sha256=packet_hash,
        audit_items_sha256=items_hash,
        reviewer_a_sha256=hashlib.sha256(reviewer_a_payload).hexdigest(),
        reviewer_b_sha256=hashlib.sha256(reviewer_b_payload).hexdigest(),
        adjudication_sha256=hashlib.sha256(adjudication_payload).hexdigest(),
        sample_size=SAMPLE_SIZE,
        confusion={
            "both_valid": true_true,
            "a_valid_b_invalid": true_false,
            "a_invalid_b_valid": false_true,
            "both_invalid": false_false,
        },
        observed_agreement=observed,
        expected_agreement=expected,
        cohen_kappa=kappa,
        field_agreement=field_agreement,
        adjudicated_valid_count=valid_count,
        adjudicated_validity=validity,
        gate_failures=tuple(failures),
        training_gate_passed=not failures,
    )
    canonical_json(result.to_dict())
    return result


__all__ = [
    "ADJUDICATION_SCHEMA_VERSION",
    "KAPPA_THRESHOLD",
    "RESULT_SCHEMA_VERSION",
    "VALIDITY_THRESHOLD",
    "AuditResult",
    "RelationAuditResultError",
    "evaluate_audit_submissions",
]
