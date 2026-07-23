"""Typed, in-memory audit records for D-011 construction results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Any

from .construction import ConstructionResult, ConstructionTerminal
from .ids import canonical_json, make_stable_id, sha256_canonical
from .io import ConstructionOutcome
from .schema import (
    AnswerStatus,
    AnswerType,
    AnswerUpdate,
    CharSpan,
    CounterfactualRewrite,
    EventMention,
    Extraction,
    ExtractionResult,
    InternalSplit,
    Relation,
    RelationAnnotation,
    Rejection,
    RejectionReason,
    SplitAssignment,
    TemporalExample,
)

__all__ = (
    "ConstructionAuditRecord",
    "make_construction_audit_record",
)

_SCHEMA_VERSION = "construction-audit-v1"
_CONSTRUCTION_VERSION = "explicit-marker-construction-v0"
_MAX_INPUT_ORDER = (1 << 63) - 1
_MAX_DETAILS_DEPTH = 16
_MAX_DETAILS_NODES = 4096
_MAX_DETAILS_BYTES = 65536
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_FIELD_TYPE_ERROR = "invalid construction audit field type"
_INVARIANT_ERROR = "invalid construction audit invariant"
_NOT_MAPPING_ERROR = "construction audit value must be a mapping"
_MAPPING_ERROR = "invalid construction audit mapping"
_ID_ERROR = "construction audit ID mismatch"
_FINGERPRINT_ERROR = "construction audit fingerprint mismatch"
_MAKER_ERROR = "invalid construction audit maker input"


def _exact_mapping(value: Any, keys: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError
    if set(value) != set(keys) or any(not isinstance(key, str) for key in value):
        raise ValueError
    return value


def _non_string_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError
    return value


def _validate_input_order(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    if value < 0 or value > _MAX_INPUT_ORDER:
        raise ValueError
    return value


def _required_string(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    return _required_string(value)


def _enum_string(value: Any) -> str:
    return _required_string(value)


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError
    return value


def _freeze_details(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError
    node_count = 0

    def freeze(node: Any, depth: int) -> Any:
        nonlocal node_count
        if depth > _MAX_DETAILS_DEPTH:
            raise ValueError
        node_count += 1
        if node_count > _MAX_DETAILS_NODES:
            raise ValueError
        if node is None:
            return None
        if isinstance(node, bool):
            return node
        if isinstance(node, int):
            return node
        if isinstance(node, float):
            if not math.isfinite(node):
                raise ValueError
            return node
        if isinstance(node, str):
            return node
        if isinstance(node, Mapping):
            copied: dict[str, Any] = {}
            for key, item in node.items():
                if not isinstance(key, str):
                    raise TypeError
                copied[key] = freeze(item, depth + 1)
            return MappingProxyType(copied)
        if isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            return tuple(freeze(item, depth + 1) for item in node)
        raise TypeError

    frozen = freeze(value, 0)
    primitive = _thaw_details(frozen)
    try:
        encoded = canonical_json(primitive).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError from None
    if len(encoded) > _MAX_DETAILS_BYTES:
        raise ValueError
    return frozen


def _thaw_details(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_details(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_details(item) for item in value]
    return value


def _serialize_span(value: CharSpan) -> dict[str, Any]:
    return {"start": value.start, "end": value.end}


def _parse_span(value: Any) -> CharSpan:
    value = _exact_mapping(value, ("start", "end"))
    return CharSpan(start=_integer(value["start"]), end=_integer(value["end"]))


def _serialize_event(value: EventMention) -> dict[str, Any]:
    return {
        "event_id": value.event_id,
        "text": value.text,
        "char_span": _serialize_span(value.char_span),
    }


def _parse_event(value: Any) -> EventMention:
    value = _exact_mapping(value, ("event_id", "text", "char_span"))
    return EventMention(
        event_id=_required_string(value["event_id"]),
        text=_required_string(value["text"]),
        char_span=_parse_span(value["char_span"]),
    )


def _serialize_relation(value: RelationAnnotation) -> dict[str, Any]:
    return {
        "source_event_id": value.source_event_id,
        "target_event_id": value.target_event_id,
        "relation": value.relation.value,
        "marker": value.marker,
        "provenance": value.provenance,
    }


def _parse_relation(value: Any) -> RelationAnnotation:
    value = _exact_mapping(
        value,
        ("source_event_id", "target_event_id", "relation", "marker", "provenance"),
    )
    return RelationAnnotation(
        source_event_id=_required_string(value["source_event_id"]),
        target_event_id=_required_string(value["target_event_id"]),
        relation=Relation(_enum_string(value["relation"])),
        marker=_required_string(value["marker"]),
        provenance=_required_string(value["provenance"]),
    )


def _serialize_split(value: SplitAssignment) -> dict[str, Any]:
    return {
        "official": value.official,
        "internal": value.internal.value if value.internal is not None else None,
    }


def _parse_split(value: Any) -> SplitAssignment:
    value = _exact_mapping(value, ("official", "internal"))
    internal = _nullable_string(value["internal"])
    return SplitAssignment(
        official=_required_string(value["official"]),
        internal=InternalSplit(_enum_string(internal)) if internal is not None else None,
    )


def _serialize_temporal_example(value: TemporalExample) -> dict[str, Any]:
    return {
        "record_id": value.record_id,
        "source_id": value.source_id,
        "dataset": value.dataset,
        "split": _serialize_split(value.split),
        "revision": value.revision,
        "source_sha256": value.source_sha256,
        "text": value.text,
        "question": value.question,
        "answers": list(value.answers),
        "answer_type": value.answer_type.value,
        "events": [_serialize_event(event) for event in value.events],
        "relations": [_serialize_relation(relation) for relation in value.relations],
        "counterfactual_pair_id": value.counterfactual_pair_id,
    }


def _parse_temporal_example(value: Any) -> TemporalExample:
    value = _exact_mapping(
        value,
        (
            "record_id",
            "source_id",
            "dataset",
            "split",
            "revision",
            "source_sha256",
            "text",
            "question",
            "answers",
            "answer_type",
            "events",
            "relations",
            "counterfactual_pair_id",
        ),
    )
    answers = _non_string_sequence(value["answers"])
    events = _non_string_sequence(value["events"])
    relations = _non_string_sequence(value["relations"])
    return TemporalExample(
        record_id=_required_string(value["record_id"]),
        source_id=_required_string(value["source_id"]),
        dataset=_required_string(value["dataset"]),
        split=_parse_split(value["split"]),
        revision=_required_string(value["revision"]),
        source_sha256=_required_string(value["source_sha256"]),
        text=_required_string(value["text"]),
        question=_required_string(value["question"]),
        answers=tuple(_required_string(answer) for answer in answers),
        answer_type=AnswerType(_enum_string(value["answer_type"])),
        events=tuple(_parse_event(event) for event in events),
        relations=tuple(_parse_relation(relation) for relation in relations),
        counterfactual_pair_id=_nullable_string(value["counterfactual_pair_id"]),
    )


def _serialize_outcome(value: ConstructionOutcome) -> dict[str, Any]:
    return {
        "temporal_filtered": value.temporal_filtered,
        "event_extraction_success": value.event_extraction_success,
        "reliable_relation_label": value.reliable_relation_label,
        "valid_counterfactual": value.valid_counterfactual,
        "final_retained": value.final_retained,
    }


def _parse_outcome(value: Any) -> ConstructionOutcome:
    value = _exact_mapping(
        value,
        (
            "temporal_filtered",
            "event_extraction_success",
            "reliable_relation_label",
            "valid_counterfactual",
            "final_retained",
        ),
    )
    return ConstructionOutcome(
        temporal_filtered=_boolean(value["temporal_filtered"]),
        event_extraction_success=_boolean(value["event_extraction_success"]),
        reliable_relation_label=_boolean(value["reliable_relation_label"]),
        valid_counterfactual=_boolean(value["valid_counterfactual"]),
        final_retained=_boolean(value["final_retained"]),
    )


def _serialize_extraction(value: Extraction) -> dict[str, Any]:
    return {
        "text": value.text,
        "marker": value.marker,
        "marker_span": _serialize_span(value.marker_span),
        "event_a": _serialize_event(value.event_a),
        "event_b": _serialize_event(value.event_b),
        "relation": _serialize_relation(value.relation),
    }


def _parse_extraction(value: Any) -> Extraction:
    value = _exact_mapping(
        value, ("text", "marker", "marker_span", "event_a", "event_b", "relation")
    )
    return Extraction(
        text=_required_string(value["text"]),
        marker=_required_string(value["marker"]),
        marker_span=_parse_span(value["marker_span"]),
        event_a=_parse_event(value["event_a"]),
        event_b=_parse_event(value["event_b"]),
        relation=_parse_relation(value["relation"]),
    )


def _serialize_rejection(value: Rejection) -> dict[str, Any]:
    return {
        "reason": value.reason.value,
        "message": value.message,
        "details": _thaw_details(value.details),
    }


def _parse_rejection(value: Any) -> Rejection:
    value = _exact_mapping(value, ("reason", "message", "details"))
    details = _freeze_details(value["details"])
    return Rejection(
        reason=RejectionReason(_enum_string(value["reason"])),
        message=_required_string(value["message"]),
        details=details,
    )


def _serialize_extraction_result(value: ExtractionResult) -> dict[str, Any]:
    if value.extraction is not None:
        return {"kind": "extraction", "value": _serialize_extraction(value.extraction)}
    if value.rejection is not None:
        return {"kind": "rejection", "value": _serialize_rejection(value.rejection)}
    raise ValueError


def _parse_extraction_result(value: Any) -> ExtractionResult:
    value = _exact_mapping(value, ("kind", "value"))
    kind = _enum_string(value["kind"])
    if kind == "extraction":
        return ExtractionResult(extraction=_parse_extraction(value["value"]))
    if kind == "rejection":
        return ExtractionResult(rejection=_parse_rejection(value["value"]))
    raise ValueError


def _serialize_rewrite(value: CounterfactualRewrite) -> dict[str, Any]:
    return {
        "original_text": value.original_text,
        "rewritten_text": value.rewritten_text,
        "original": _serialize_extraction(value.original),
        "rewritten": _serialize_extraction(value.rewritten),
        "template_id": value.template_id,
    }


def _parse_rewrite(value: Any) -> CounterfactualRewrite:
    value = _exact_mapping(
        value,
        ("original_text", "rewritten_text", "original", "rewritten", "template_id"),
    )
    return CounterfactualRewrite(
        original_text=_required_string(value["original_text"]),
        rewritten_text=_required_string(value["rewritten_text"]),
        original=_parse_extraction(value["original"]),
        rewritten=_parse_extraction(value["rewritten"]),
        template_id=_required_string(value["template_id"]),
    )


def _serialize_rewrite_result(
    value: CounterfactualRewrite | ExtractionResult | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, CounterfactualRewrite):
        return {"kind": "counterfactual_rewrite", "value": _serialize_rewrite(value)}
    if isinstance(value, ExtractionResult) and not value.accepted:
        assert value.rejection is not None
        return {"kind": "rejection", "value": _serialize_rejection(value.rejection)}
    raise ValueError


def _parse_rewrite_result(value: Any) -> CounterfactualRewrite | ExtractionResult | None:
    if value is None:
        return None
    value = _exact_mapping(value, ("kind", "value"))
    kind = _enum_string(value["kind"])
    if kind == "counterfactual_rewrite":
        return _parse_rewrite(value["value"])
    if kind == "rejection":
        return ExtractionResult(rejection=_parse_rejection(value["value"]))
    raise ValueError


def _serialize_answer_update(value: AnswerUpdate | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "status": value.status.value,
        "value": value.value,
        "reason": value.reason,
    }


def _parse_answer_update(value: Any) -> AnswerUpdate | None:
    if value is None:
        return None
    value = _exact_mapping(value, ("status", "value", "reason"))
    return AnswerUpdate(
        status=AnswerStatus(_enum_string(value["status"])),
        value=_nullable_string(value["value"]),
        reason=_nullable_string(value["reason"]),
    )


def _normalize_rejection(value: Rejection) -> Rejection:
    if not isinstance(value, Rejection):
        raise TypeError
    details = _freeze_details(value.details)
    if not isinstance(value.reason, RejectionReason):
        raise TypeError
    return Rejection(
        reason=value.reason,
        message=_required_string(value.message),
        details=details,
    )


def _normalize_extraction_result(value: ExtractionResult) -> ExtractionResult:
    if not isinstance(value, ExtractionResult):
        raise TypeError
    if value.extraction is not None:
        if not isinstance(value.extraction, Extraction):
            raise TypeError
        return ExtractionResult(extraction=value.extraction)
    if value.rejection is not None:
        return ExtractionResult(rejection=_normalize_rejection(value.rejection))
    raise ValueError


def _normalize_rewrite_result(
    value: CounterfactualRewrite | ExtractionResult | None,
) -> CounterfactualRewrite | ExtractionResult | None:
    if value is None or isinstance(value, CounterfactualRewrite):
        return value
    if isinstance(value, ExtractionResult) and not value.accepted:
        return _normalize_extraction_result(value)
    raise TypeError


def _make_audit_record_id(value: TemporalExample) -> str:
    return make_stable_id(
        "construction-audit",
        {
            "schema_version": _SCHEMA_VERSION,
            "construction_version": _CONSTRUCTION_VERSION,
            "dataset": value.dataset,
            "revision": value.revision,
            "source_id": value.source_id,
            "input_record_id": value.record_id,
            "source_sha256": value.source_sha256,
        },
    )


def _primitive_payload(
    *,
    audit_record_id: str,
    schema_version: str,
    construction_version: str,
    input_order: int,
    input: TemporalExample,
    terminal: ConstructionTerminal,
    outcome: ConstructionOutcome,
    extraction_result: ExtractionResult,
    rewrite_result: CounterfactualRewrite | ExtractionResult | None,
    answer_update: AnswerUpdate | None,
    template_id: str | None,
    prospective_pair_id: str | None,
    prospective_counterfactual_record_id: str | None,
    original: TemporalExample | None,
    counterfactual: TemporalExample | None,
) -> dict[str, Any]:
    return {
        "audit_record_id": audit_record_id,
        "schema_version": schema_version,
        "construction_version": construction_version,
        "input_order": input_order,
        "input": _serialize_temporal_example(input),
        "terminal": terminal.value,
        "outcome": _serialize_outcome(outcome),
        "extraction_result": _serialize_extraction_result(extraction_result),
        "rewrite_result": _serialize_rewrite_result(rewrite_result),
        "answer_update": _serialize_answer_update(answer_update),
        "template_id": template_id,
        "prospective_pair_id": prospective_pair_id,
        "prospective_counterfactual_record_id": prospective_counterfactual_record_id,
        "original": _serialize_temporal_example(original) if original is not None else None,
        "counterfactual": (
            _serialize_temporal_example(counterfactual)
            if counterfactual is not None
            else None
        ),
    }


def _record_fingerprint(**fields: Any) -> str:
    return sha256_canonical(_primitive_payload(**fields))


def _payload_fields(
    *,
    audit_record_id: str,
    schema_version: str,
    construction_version: str,
    input_order: int,
    input: TemporalExample,
    terminal: ConstructionTerminal,
    outcome: ConstructionOutcome,
    extraction_result: ExtractionResult,
    rewrite_result: CounterfactualRewrite | ExtractionResult | None,
    answer_update: AnswerUpdate | None,
    template_id: str | None,
    prospective_pair_id: str | None,
    prospective_counterfactual_record_id: str | None,
    original: TemporalExample | None,
    counterfactual: TemporalExample | None,
) -> dict[str, Any]:
    return {
        "audit_record_id": audit_record_id,
        "schema_version": schema_version,
        "construction_version": construction_version,
        "input_order": input_order,
        "input": input,
        "terminal": terminal,
        "outcome": outcome,
        "extraction_result": extraction_result,
        "rewrite_result": rewrite_result,
        "answer_update": answer_update,
        "template_id": template_id,
        "prospective_pair_id": prospective_pair_id,
        "prospective_counterfactual_record_id": prospective_counterfactual_record_id,
        "original": original,
        "counterfactual": counterfactual,
    }


def _validate_crosslinks(
    *,
    input: TemporalExample,
    terminal: ConstructionTerminal,
    outcome: ConstructionOutcome,
    extraction_result: ExtractionResult,
    rewrite_result: CounterfactualRewrite | ExtractionResult | None,
    answer_update: AnswerUpdate | None,
    template_id: str | None,
    prospective_pair_id: str | None,
    prospective_counterfactual_record_id: str | None,
    original: TemporalExample | None,
    counterfactual: TemporalExample | None,
) -> None:
    if input.events != () or input.relations != () or input.counterfactual_pair_id is not None:
        raise ValueError
    if _parse_temporal_example(_serialize_temporal_example(input)) != input:
        raise ValueError
    if _parse_outcome(_serialize_outcome(outcome)) != outcome:
        raise ValueError
    if _parse_extraction_result(_serialize_extraction_result(extraction_result)) != extraction_result:
        raise ValueError
    if _parse_rewrite_result(_serialize_rewrite_result(rewrite_result)) != rewrite_result:
        raise ValueError
    if _parse_answer_update(_serialize_answer_update(answer_update)) != answer_update:
        raise ValueError
    for final in (original, counterfactual):
        if final is not None and _parse_temporal_example(
            _serialize_temporal_example(final)
        ) != final:
            raise ValueError
    result = ConstructionResult(
        input_record_id=input.record_id,
        outcome=outcome,
        terminal=terminal,
        extraction_result=extraction_result,
        rewrite_result=rewrite_result,
        answer_update=answer_update,
        template_id=template_id,
        prospective_pair_id=prospective_pair_id,
        prospective_counterfactual_record_id=prospective_counterfactual_record_id,
        original=original,
        counterfactual=counterfactual,
    )
    if result.input_record_id != input.record_id:
        raise ValueError
    if prospective_pair_id is not None:
        if prospective_counterfactual_record_id is None:
            raise ValueError
        if prospective_pair_id in {input.record_id, prospective_counterfactual_record_id}:
            raise ValueError
        if prospective_counterfactual_record_id == input.record_id:
            raise ValueError
    if original is None or counterfactual is None:
        if original is not None or counterfactual is not None:
            raise ValueError
        return
    if original.record_id != input.record_id:
        raise ValueError
    if counterfactual.record_id != prospective_counterfactual_record_id:
        raise ValueError
    if original.record_id == counterfactual.record_id:
        raise ValueError
    if prospective_pair_id in {original.record_id, counterfactual.record_id}:
        raise ValueError
    preserved = (
        "source_id",
        "dataset",
        "split",
        "revision",
        "source_sha256",
        "text",
        "question",
        "answers",
        "answer_type",
    )
    if any(getattr(original, name) != getattr(input, name) for name in preserved):
        raise ValueError
    inherited = (
        "source_id",
        "dataset",
        "split",
        "revision",
        "source_sha256",
        "question",
        "answer_type",
    )
    if any(getattr(counterfactual, name) != getattr(input, name) for name in inherited):
        raise ValueError
    if (
        original.counterfactual_pair_id != prospective_pair_id
        or counterfactual.counterfactual_pair_id != prospective_pair_id
    ):
        raise ValueError


@dataclass(frozen=True, repr=False)
class ConstructionAuditRecord:
    audit_record_id: str
    record_fingerprint_sha256: str
    schema_version: str
    construction_version: str
    input_order: int
    input: TemporalExample
    terminal: ConstructionTerminal
    outcome: ConstructionOutcome
    extraction_result: ExtractionResult
    rewrite_result: CounterfactualRewrite | ExtractionResult | None
    answer_update: AnswerUpdate | None
    template_id: str | None
    prospective_pair_id: str | None
    prospective_counterfactual_record_id: str | None
    original: TemporalExample | None
    counterfactual: TemporalExample | None

    def __post_init__(self) -> None:
        try:
            normalized_extraction = _normalize_extraction_result(self.extraction_result)
            normalized_rewrite = _normalize_rewrite_result(self.rewrite_result)
        except (AttributeError, TypeError):
            raise TypeError(_FIELD_TYPE_ERROR) from None
        except (ValueError, UnicodeError):
            raise ValueError(_INVARIANT_ERROR) from None
        object.__setattr__(self, "extraction_result", normalized_extraction)
        object.__setattr__(self, "rewrite_result", normalized_rewrite)

        try:
            if not isinstance(self.audit_record_id, str):
                raise TypeError
            if not isinstance(self.record_fingerprint_sha256, str):
                raise TypeError
            if not isinstance(self.schema_version, str):
                raise TypeError
            if not isinstance(self.construction_version, str):
                raise TypeError
            _validate_input_order(self.input_order)
            if not isinstance(self.input, TemporalExample):
                raise TypeError
            if not isinstance(self.terminal, ConstructionTerminal):
                raise TypeError
            if not isinstance(self.outcome, ConstructionOutcome):
                raise TypeError
            if self.schema_version != _SCHEMA_VERSION:
                raise ValueError
            if self.construction_version != _CONSTRUCTION_VERSION:
                raise ValueError
            if not _SHA256_RE.fullmatch(self.record_fingerprint_sha256):
                raise ValueError
            _validate_crosslinks(
                input=self.input,
                terminal=self.terminal,
                outcome=self.outcome,
                extraction_result=self.extraction_result,
                rewrite_result=self.rewrite_result,
                answer_update=self.answer_update,
                template_id=self.template_id,
                prospective_pair_id=self.prospective_pair_id,
                prospective_counterfactual_record_id=(
                    self.prospective_counterfactual_record_id
                ),
                original=self.original,
                counterfactual=self.counterfactual,
            )
        except (AttributeError, TypeError):
            raise TypeError(_FIELD_TYPE_ERROR) from None
        except (ValueError, AssertionError):
            raise ValueError(_INVARIANT_ERROR) from None

        expected_id = _make_audit_record_id(self.input)
        if self.audit_record_id != expected_id:
            raise ValueError(_ID_ERROR) from None
        fields = _payload_fields(
            audit_record_id=self.audit_record_id,
            schema_version=self.schema_version,
            construction_version=self.construction_version,
            input_order=self.input_order,
            input=self.input,
            terminal=self.terminal,
            outcome=self.outcome,
            extraction_result=self.extraction_result,
            rewrite_result=self.rewrite_result,
            answer_update=self.answer_update,
            template_id=self.template_id,
            prospective_pair_id=self.prospective_pair_id,
            prospective_counterfactual_record_id=self.prospective_counterfactual_record_id,
            original=self.original,
            counterfactual=self.counterfactual,
        )
        try:
            expected_fingerprint = _record_fingerprint(**fields)
        except (AttributeError, TypeError, ValueError, UnicodeError):
            raise ValueError(_INVARIANT_ERROR) from None
        if self.record_fingerprint_sha256 != expected_fingerprint:
            raise ValueError(_FINGERPRINT_ERROR) from None

    def __repr__(self) -> str:
        return "ConstructionAuditRecord(<redacted>)"

    def __str__(self) -> str:
        return "ConstructionAuditRecord(<redacted>)"

    def to_dict(self) -> dict[str, Any]:
        try:
            payload = _primitive_payload(
                **_payload_fields(
                    audit_record_id=self.audit_record_id,
                    schema_version=self.schema_version,
                    construction_version=self.construction_version,
                    input_order=self.input_order,
                    input=self.input,
                    terminal=self.terminal,
                    outcome=self.outcome,
                    extraction_result=self.extraction_result,
                    rewrite_result=self.rewrite_result,
                    answer_update=self.answer_update,
                    template_id=self.template_id,
                    prospective_pair_id=self.prospective_pair_id,
                    prospective_counterfactual_record_id=(
                        self.prospective_counterfactual_record_id
                    ),
                    original=self.original,
                    counterfactual=self.counterfactual,
                )
            )
            return {
                "audit_record_id": payload["audit_record_id"],
                "record_fingerprint_sha256": self.record_fingerprint_sha256,
                "schema_version": payload["schema_version"],
                "construction_version": payload["construction_version"],
                "input_order": payload["input_order"],
                "input": payload["input"],
                "terminal": payload["terminal"],
                "outcome": payload["outcome"],
                "extraction_result": payload["extraction_result"],
                "rewrite_result": payload["rewrite_result"],
                "answer_update": payload["answer_update"],
                "template_id": payload["template_id"],
                "prospective_pair_id": payload["prospective_pair_id"],
                "prospective_counterfactual_record_id": payload[
                    "prospective_counterfactual_record_id"
                ],
                "original": payload["original"],
                "counterfactual": payload["counterfactual"],
            }
        except (AttributeError, TypeError, ValueError, UnicodeError, KeyError):
            raise ValueError(_INVARIANT_ERROR) from None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConstructionAuditRecord":
        if not isinstance(value, Mapping):
            raise TypeError(_NOT_MAPPING_ERROR) from None
        try:
            raw = _exact_mapping(
                value,
                (
                    "audit_record_id",
                    "record_fingerprint_sha256",
                    "schema_version",
                    "construction_version",
                    "input_order",
                    "input",
                    "terminal",
                    "outcome",
                    "extraction_result",
                    "rewrite_result",
                    "answer_update",
                    "template_id",
                    "prospective_pair_id",
                    "prospective_counterfactual_record_id",
                    "original",
                    "counterfactual",
                ),
            )
            record = cls(
                audit_record_id=_required_string(raw["audit_record_id"]),
                record_fingerprint_sha256=_required_string(
                    raw["record_fingerprint_sha256"]
                ),
                schema_version=_required_string(raw["schema_version"]),
                construction_version=_required_string(raw["construction_version"]),
                input_order=_validate_input_order(raw["input_order"]),
                input=_parse_temporal_example(raw["input"]),
                terminal=ConstructionTerminal(_enum_string(raw["terminal"])),
                outcome=_parse_outcome(raw["outcome"]),
                extraction_result=_parse_extraction_result(raw["extraction_result"]),
                rewrite_result=_parse_rewrite_result(raw["rewrite_result"]),
                answer_update=_parse_answer_update(raw["answer_update"]),
                template_id=_nullable_string(raw["template_id"]),
                prospective_pair_id=_nullable_string(raw["prospective_pair_id"]),
                prospective_counterfactual_record_id=_nullable_string(
                    raw["prospective_counterfactual_record_id"]
                ),
                original=(
                    _parse_temporal_example(raw["original"])
                    if raw["original"] is not None
                    else None
                ),
                counterfactual=(
                    _parse_temporal_example(raw["counterfactual"])
                    if raw["counterfactual"] is not None
                    else None
                ),
            )
            return record
        except ValueError as error:
            if str(error) == _ID_ERROR:
                raise ValueError(_ID_ERROR) from None
            if str(error) == _FINGERPRINT_ERROR:
                raise ValueError(_FINGERPRINT_ERROR) from None
            raise ValueError(_MAPPING_ERROR) from None
        except (AttributeError, TypeError, KeyError, AssertionError, UnicodeError):
            raise ValueError(_MAPPING_ERROR) from None


def make_construction_audit_record(
    *,
    input_order: int,
    input: TemporalExample,
    result: ConstructionResult,
) -> ConstructionAuditRecord:
    try:
        normalized_extraction = _normalize_extraction_result(result.extraction_result)
        normalized_rewrite = _normalize_rewrite_result(result.rewrite_result)
    except (AttributeError, TypeError):
        raise TypeError(_MAKER_ERROR) from None
    except (ValueError, UnicodeError):
        raise ValueError(_MAKER_ERROR) from None
    try:
        _validate_input_order(input_order)
        if not isinstance(input, TemporalExample) or not isinstance(result, ConstructionResult):
            raise TypeError
        if result.input_record_id != input.record_id:
            raise ValueError
        _validate_crosslinks(
            input=input,
            terminal=result.terminal,
            outcome=result.outcome,
            extraction_result=normalized_extraction,
            rewrite_result=normalized_rewrite,
            answer_update=result.answer_update,
            template_id=result.template_id,
            prospective_pair_id=result.prospective_pair_id,
            prospective_counterfactual_record_id=result.prospective_counterfactual_record_id,
            original=result.original,
            counterfactual=result.counterfactual,
        )
        audit_record_id = _make_audit_record_id(input)
        fields = _payload_fields(
            audit_record_id=audit_record_id,
            schema_version=_SCHEMA_VERSION,
            construction_version=_CONSTRUCTION_VERSION,
            input_order=input_order,
            input=input,
            terminal=result.terminal,
            outcome=result.outcome,
            extraction_result=normalized_extraction,
            rewrite_result=normalized_rewrite,
            answer_update=result.answer_update,
            template_id=result.template_id,
            prospective_pair_id=result.prospective_pair_id,
            prospective_counterfactual_record_id=(
                result.prospective_counterfactual_record_id
            ),
            original=result.original,
            counterfactual=result.counterfactual,
        )
        fingerprint = _record_fingerprint(**fields)
        return ConstructionAuditRecord(
            record_fingerprint_sha256=fingerprint,
            **fields,
        )
    except (AttributeError, TypeError):
        raise TypeError(_MAKER_ERROR) from None
    except (ValueError, AssertionError, UnicodeError):
        raise ValueError(_MAKER_ERROR) from None
