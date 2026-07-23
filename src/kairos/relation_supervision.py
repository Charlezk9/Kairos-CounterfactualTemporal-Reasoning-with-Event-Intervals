"""GSM8K relation-only supervision with explicitly unavailable CF answers."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

from .counterfactual import rewrite_counterfactual
from .events import extract_explicit_relation
from .ids import make_stable_id
from .schema import (
    AnswerType,
    CharSpan,
    CounterfactualRewrite,
    EventMention,
    ExtractionResult,
    InternalSplit,
    Relation,
    RelationAnnotation,
    RejectionReason,
    SplitAssignment,
    TemporalExample,
)


SCHEMA_VERSION = "gsm8k-relation-only-pair-v1"
CONSTRUCTION_VERSION = "explicit-marker-relation-only-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CounterfactualAnswerStatus(str, Enum):
    UNAVAILABLE = "unavailable-relation-only"


class RelationOnlyTerminal(str, Enum):
    NO_MARKER = "no_marker"
    EXTRACTION_REJECTED = "extraction_rejected"
    REWRITE_REJECTED = "rewrite_rejected"
    RETAINED = "retained"


class RelationSupervisionError(ValueError):
    """The relation-only schema or constructor rejected an input."""


def _exact_mapping(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC):
        raise RelationSupervisionError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RelationSupervisionError(f"{name} keys must be strings")
    missing = expected.difference(value)
    extra = set(value).difference(expected)
    if missing or extra:
        raise RelationSupervisionError(
            f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RelationSupervisionError(f"{name} must be a non-empty string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise RelationSupervisionError(f"{name} is not valid Unicode") from error
    return value


def _event_value(event: EventMention) -> Mapping[str, Any]:
    return {
        "event_id": event.event_id,
        "text": event.text,
        "char_span": {
            "start": event.char_span.start,
            "end": event.char_span.end,
        },
    }


def _event_from_value(value: Any, name: str) -> EventMention:
    value = _exact_mapping(value, {"event_id", "text", "char_span"}, name)
    span = _exact_mapping(value["char_span"], {"start", "end"}, f"{name} span")
    try:
        return EventMention(
            event_id=value["event_id"],
            text=value["text"],
            char_span=CharSpan(start=span["start"], end=span["end"]),
        )
    except (TypeError, ValueError) as error:
        raise RelationSupervisionError(f"{name} is invalid") from error


def _relation_value(relation: RelationAnnotation) -> Mapping[str, Any]:
    return {
        "source_event_id": relation.source_event_id,
        "target_event_id": relation.target_event_id,
        "relation": relation.relation.value,
        "marker": relation.marker,
        "provenance": relation.provenance,
    }


def _relation_from_value(value: Any, name: str) -> RelationAnnotation:
    value = _exact_mapping(
        value,
        {"source_event_id", "target_event_id", "relation", "marker", "provenance"},
        name,
    )
    try:
        return RelationAnnotation(
            source_event_id=value["source_event_id"],
            target_event_id=value["target_event_id"],
            relation=Relation(value["relation"]),
            marker=value["marker"],
            provenance=value["provenance"],
        )
    except (TypeError, ValueError) as error:
        raise RelationSupervisionError(f"{name} is invalid") from error


def _split_value(split: SplitAssignment) -> Mapping[str, Any]:
    return {
        "official": split.official,
        "internal": split.internal.value if split.internal is not None else None,
    }


def _split_from_value(value: Any) -> SplitAssignment:
    value = _exact_mapping(value, {"official", "internal"}, "split")
    try:
        internal = None if value["internal"] is None else InternalSplit(value["internal"])
        return SplitAssignment(official=value["official"], internal=internal)
    except (TypeError, ValueError) as error:
        raise RelationSupervisionError("split is invalid") from error


def _identities(
    source_id: str, original_record_id: str, template_id: str
) -> tuple[str, str]:
    pair_id = make_stable_id(
        "relation-supervision-pair",
        {
            "version": CONSTRUCTION_VERSION,
            "source_id": source_id,
            "original_record_id": original_record_id,
            "template_id": template_id,
        },
    )
    counterfactual_record_id = make_stable_id(
        "record",
        {
            "version": CONSTRUCTION_VERSION,
            "source_id": source_id,
            "original_record_id": original_record_id,
            "pair_id": pair_id,
            "template_id": template_id,
            "variant": "counterfactual-relation-only",
        },
    )
    return pair_id, counterfactual_record_id


@dataclass(frozen=True)
class RelationOnlyPair:
    pair_id: str
    original_record_id: str
    counterfactual_record_id: str
    source_id: str
    dataset: str
    split: SplitAssignment
    revision: str
    source_sha256: str
    original_query: str
    counterfactual_query: str
    original_answer: str
    answer_type: AnswerType
    template_id: str
    original_events: tuple[EventMention, EventMention]
    counterfactual_events: tuple[EventMention, EventMention]
    original_relation: RelationAnnotation
    counterfactual_relation: RelationAnnotation
    counterfactual_answer_status: CounterfactualAnswerStatus

    def __post_init__(self) -> None:
        for name in (
            "pair_id", "original_record_id", "counterfactual_record_id", "source_id",
            "dataset", "revision", "source_sha256", "original_query",
            "counterfactual_query", "original_answer", "template_id",
        ):
            _text(getattr(self, name), name)
        if self.dataset != "gsm8k":
            raise RelationSupervisionError("relation-only v1 is fixed to GSM8K")
        if not _HEX64.fullmatch(self.source_sha256):
            raise RelationSupervisionError("source_sha256 must be lowercase SHA256")
        if not isinstance(self.split, SplitAssignment):
            raise RelationSupervisionError("split must be a SplitAssignment")
        if self.answer_type is not AnswerType.NUMERIC:
            raise RelationSupervisionError("relation-only v1 requires a numeric answer")
        if self.counterfactual_answer_status is not CounterfactualAnswerStatus.UNAVAILABLE:
            raise RelationSupervisionError("counterfactual answer must remain unavailable")
        if self.original_query == self.counterfactual_query:
            raise RelationSupervisionError("counterfactual query must differ")
        if self.original_record_id == self.counterfactual_record_id:
            raise RelationSupervisionError("original and counterfactual IDs must differ")
        for events, query, name in (
            (self.original_events, self.original_query, "original events"),
            (self.counterfactual_events, self.counterfactual_query, "counterfactual events"),
        ):
            if not isinstance(events, tuple) or len(events) != 2 or any(
                not isinstance(event, EventMention) for event in events
            ):
                raise RelationSupervisionError(f"{name} must contain exactly two events")
            for event in events:
                try:
                    event.validate_against(query)
                except ValueError as error:
                    raise RelationSupervisionError(f"{name} do not match their query") from error
        if not isinstance(self.original_relation, RelationAnnotation) or not isinstance(
            self.counterfactual_relation, RelationAnnotation
        ):
            raise RelationSupervisionError("relation labels must be annotations")
        if self.original_relation.relation is Relation.UNKNOWN:
            raise RelationSupervisionError("original relation must be known")
        if (
            self.counterfactual_relation.relation
            is not self.original_relation.relation.inverse()
        ):
            raise RelationSupervisionError("counterfactual relation must invert original")

        original_result = extract_explicit_relation(self.original_query)
        if not original_result.accepted:
            raise RelationSupervisionError("original query does not replay extraction")
        original = original_result.extraction
        assert original is not None
        rewritten = rewrite_counterfactual(original)
        if not isinstance(rewritten, CounterfactualRewrite):
            raise RelationSupervisionError("original query does not replay rewrite")
        expected_pair_id, expected_counterfactual_id = _identities(
            self.source_id, self.original_record_id, rewritten.template_id
        )
        if (
            self.pair_id != expected_pair_id
            or self.counterfactual_record_id != expected_counterfactual_id
            or self.template_id != rewritten.template_id
            or self.counterfactual_query != rewritten.rewritten_text
            or self.original_events != (original.event_a, original.event_b)
            or self.counterfactual_events
            != (rewritten.rewritten.event_a, rewritten.rewritten.event_b)
            or self.original_relation != original.relation
            or self.counterfactual_relation != rewritten.rewritten.relation
        ):
            raise RelationSupervisionError("pair differs from deterministic replay")

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "pair_id": self.pair_id,
            "original_record_id": self.original_record_id,
            "counterfactual_record_id": self.counterfactual_record_id,
            "source_id": self.source_id,
            "dataset": self.dataset,
            "split": _split_value(self.split),
            "revision": self.revision,
            "source_sha256": self.source_sha256,
            "original_query": self.original_query,
            "counterfactual_query": self.counterfactual_query,
            "original_answer": self.original_answer,
            "answer_type": self.answer_type.value,
            "template_id": self.template_id,
            "original_events": [_event_value(event) for event in self.original_events],
            "counterfactual_events": [
                _event_value(event) for event in self.counterfactual_events
            ],
            "original_relation": _relation_value(self.original_relation),
            "counterfactual_relation": _relation_value(self.counterfactual_relation),
            "counterfactual_answer_status": self.counterfactual_answer_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RelationOnlyPair":
        value = _exact_mapping(
            value,
            {
                "schema_version", "pair_id", "original_record_id",
                "counterfactual_record_id", "source_id", "dataset", "split",
                "revision", "source_sha256", "original_query",
                "counterfactual_query", "original_answer", "answer_type",
                "template_id", "original_events", "counterfactual_events",
                "original_relation", "counterfactual_relation",
                "counterfactual_answer_status",
            },
            "relation-only pair",
        )
        if value["schema_version"] != SCHEMA_VERSION:
            raise RelationSupervisionError("relation-only schema version differs")
        parsed_events = []
        for field in ("original_events", "counterfactual_events"):
            raw = value[field]
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(
                raw, SequenceABC
            ) or len(raw) != 2:
                raise RelationSupervisionError(f"{field} must contain two events")
            parsed_events.append(
                tuple(
                    _event_from_value(item, f"{field}[{index}]")
                    for index, item in enumerate(raw)
                )
            )
        try:
            return cls(
                pair_id=value["pair_id"],
                original_record_id=value["original_record_id"],
                counterfactual_record_id=value["counterfactual_record_id"],
                source_id=value["source_id"],
                dataset=value["dataset"],
                split=_split_from_value(value["split"]),
                revision=value["revision"],
                source_sha256=value["source_sha256"],
                original_query=value["original_query"],
                counterfactual_query=value["counterfactual_query"],
                original_answer=value["original_answer"],
                answer_type=AnswerType(value["answer_type"]),
                template_id=value["template_id"],
                original_events=parsed_events[0],
                counterfactual_events=parsed_events[1],
                original_relation=_relation_from_value(
                    value["original_relation"], "original relation"
                ),
                counterfactual_relation=_relation_from_value(
                    value["counterfactual_relation"], "counterfactual relation"
                ),
                counterfactual_answer_status=CounterfactualAnswerStatus(
                    value["counterfactual_answer_status"]
                ),
            )
        except RelationSupervisionError:
            raise
        except (TypeError, ValueError) as error:
            raise RelationSupervisionError("relation-only pair is invalid") from error


@dataclass(frozen=True)
class RelationOnlyConstructionResult:
    input_record_id: str
    terminal: RelationOnlyTerminal
    rejection_reason: RejectionReason | None
    pair: RelationOnlyPair | None

    def __post_init__(self) -> None:
        _text(self.input_record_id, "input_record_id")
        if not isinstance(self.terminal, RelationOnlyTerminal):
            raise RelationSupervisionError("terminal must be a RelationOnlyTerminal")
        if self.rejection_reason is not None and not isinstance(
            self.rejection_reason, RejectionReason
        ):
            raise RelationSupervisionError("rejection_reason is invalid")
        if self.pair is not None and not isinstance(self.pair, RelationOnlyPair):
            raise RelationSupervisionError("pair is invalid")
        retained = self.terminal is RelationOnlyTerminal.RETAINED
        if retained != (self.pair is not None) or retained == (
            self.rejection_reason is not None
        ):
            raise RelationSupervisionError("terminal payload is inconsistent")


def construct_gsm8k_relation_only(
    original: TemporalExample,
) -> RelationOnlyConstructionResult:
    """Construct relation supervision while withholding an unknown CF answer."""

    if not isinstance(original, TemporalExample):
        raise TypeError("original must be a TemporalExample")
    if (
        original.dataset != "gsm8k"
        or original.answer_type is not AnswerType.NUMERIC
        or original.text != original.question
        or len(original.answers) != 1
        or original.events != ()
        or original.relations != ()
        or original.counterfactual_pair_id is not None
    ):
        raise RelationSupervisionError("input is not a raw GSM8K numeric example")
    extraction_result = extract_explicit_relation(original.text)
    if not extraction_result.accepted:
        reason = extraction_result.rejection.reason
        assert reason is not None
        terminal = (
            RelationOnlyTerminal.NO_MARKER
            if reason is RejectionReason.NO_MARKER
            else RelationOnlyTerminal.EXTRACTION_REJECTED
        )
        return RelationOnlyConstructionResult(
            original.record_id, terminal, reason, None
        )
    extraction = extraction_result.extraction
    assert extraction is not None
    if extraction.relation.relation is Relation.UNKNOWN:
        return RelationOnlyConstructionResult(
            original.record_id,
            RelationOnlyTerminal.EXTRACTION_REJECTED,
            RejectionReason.AMBIGUOUS_ALIGNMENT,
            None,
        )
    rewrite = rewrite_counterfactual(extraction)
    if isinstance(rewrite, ExtractionResult):
        assert rewrite.rejection is not None
        return RelationOnlyConstructionResult(
            original.record_id,
            RelationOnlyTerminal.REWRITE_REJECTED,
            rewrite.rejection.reason,
            None,
        )
    pair_id, counterfactual_record_id = _identities(
        original.source_id, original.record_id, rewrite.template_id
    )
    pair = RelationOnlyPair(
        pair_id=pair_id,
        original_record_id=original.record_id,
        counterfactual_record_id=counterfactual_record_id,
        source_id=original.source_id,
        dataset=original.dataset,
        split=original.split,
        revision=original.revision,
        source_sha256=original.source_sha256,
        original_query=original.text,
        counterfactual_query=rewrite.rewritten_text,
        original_answer=original.answers[0],
        answer_type=original.answer_type,
        template_id=rewrite.template_id,
        original_events=(extraction.event_a, extraction.event_b),
        counterfactual_events=(rewrite.rewritten.event_a, rewrite.rewritten.event_b),
        original_relation=extraction.relation,
        counterfactual_relation=rewrite.rewritten.relation,
        counterfactual_answer_status=CounterfactualAnswerStatus.UNAVAILABLE,
    )
    return RelationOnlyConstructionResult(
        original.record_id, RelationOnlyTerminal.RETAINED, None, pair
    )


__all__ = (
    "CONSTRUCTION_VERSION",
    "SCHEMA_VERSION",
    "CounterfactualAnswerStatus",
    "RelationOnlyConstructionResult",
    "RelationOnlyPair",
    "RelationOnlyTerminal",
    "RelationSupervisionError",
    "construct_gsm8k_relation_only",
)
