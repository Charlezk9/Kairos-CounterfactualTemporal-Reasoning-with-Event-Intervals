"""Strict schemas for the deterministic stage-1 data core."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Mapping, Optional, Tuple
import unicodedata


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _source_relative_path(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("source relative_path must be a string")
    if not value:
        raise ValueError("source relative_path must be non-empty")
    if value.startswith("/") or "\\" in value:
        raise ValueError("source relative_path must be a POSIX relative path")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("source relative_path must be NFC-normalized")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        raise ValueError("source relative_path contains a forbidden code point")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("source relative_path must be valid UTF-8") from error
    if len(encoded) > 4096:
        raise ValueError("source relative_path exceeds 4096 UTF-8 bytes")
    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError("source relative_path contains an invalid component")
    if any(len(component.encode("utf-8")) > 255 for component in components):
        raise ValueError("source relative_path component exceeds 255 UTF-8 bytes")
    return value


def _exact_mapping(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC):
        raise TypeError(f"{name} must be a mapping")
    keys = set(value)
    missing = expected.difference(keys)
    extra = keys.difference(expected)
    if missing or extra:
        raise ValueError(f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}")
    return value


def _sequence(value: Any, name: str) -> SequenceABC[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, SequenceABC):
        raise TypeError(f"{name} must be a non-string sequence")
    return value


class Relation(str, Enum):
    """The relation in ``relation(a, b)`` describes event a relative to b."""

    PRECEDES = "precedes"
    FOLLOWS = "follows"
    OVERLAPS = "overlaps"
    CONTAINS = "contains"
    DURING = "during"
    UNKNOWN = "unknown"

    def inverse(self) -> "Relation":
        return {
            Relation.PRECEDES: Relation.FOLLOWS,
            Relation.FOLLOWS: Relation.PRECEDES,
            Relation.OVERLAPS: Relation.OVERLAPS,
            Relation.CONTAINS: Relation.DURING,
            Relation.DURING: Relation.CONTAINS,
            Relation.UNKNOWN: Relation.UNKNOWN,
        }[self]

    @property
    def symmetric(self) -> bool:
        return self in {Relation.OVERLAPS, Relation.UNKNOWN}


class AnswerStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class AnswerType(str, Enum):
    EXTRACTIVE = "extractive"
    YES_NO = "yes_no"
    NUMERIC = "numeric"
    FREE_GENERATION = "free_generation"


class InternalSplit(str, Enum):
    TRAIN = "train"
    DEV = "dev"


class RejectionReason(str, Enum):
    NO_MARKER = "no_marker"
    UNSUPPORTED_MARKER = "unsupported_marker"
    MULTIPLE_MARKERS = "multiple_markers"
    EMPTY_LEFT_EVENT = "empty_left_event"
    EMPTY_RIGHT_EVENT = "empty_right_event"
    OVERLAPPING_SPANS = "overlapping_spans"
    NESTED_SPANS = "nested_spans"
    AMBIGUOUS_ALIGNMENT = "ambiguous_alignment"
    UNSUPPORTED_REWRITE = "unsupported_rewrite"
    REWRITE_INVARIANT_FAILED = "rewrite_invariant_failed"


@dataclass(frozen=True)
class CharSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if isinstance(self.start, bool) or not isinstance(self.start, int):
            raise TypeError("span start must be an integer")
        if isinstance(self.end, bool) or not isinstance(self.end, int):
            raise TypeError("span end must be an integer")
        if self.start < 0:
            raise ValueError("span start must be non-negative")
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")

    def text_from(self, source: str) -> str:
        if self.end > len(source):
            raise ValueError("span exceeds source text")
        return source[self.start : self.end]


@dataclass(frozen=True)
class EventMention:
    event_id: str
    text: str
    char_span: CharSpan

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must be non-empty")
        if not self.text or self.text != self.text.strip():
            raise ValueError("event text must be non-empty and trimmed")

    def validate_against(self, source: str) -> None:
        if self.char_span.text_from(source) != self.text:
            raise ValueError(f"event {self.event_id!r} does not match its source span")


@dataclass(frozen=True)
class RelationAnnotation:
    source_event_id: str
    target_event_id: str
    relation: Relation
    marker: str
    provenance: str = "explicit-marker-v0"

    def __post_init__(self) -> None:
        if not self.source_event_id.strip() or not self.target_event_id.strip():
            raise ValueError("relation endpoints must be non-empty")
        if self.source_event_id == self.target_event_id:
            raise ValueError("relation endpoints must be distinct")
        if not isinstance(self.relation, Relation):
            raise TypeError("relation must be a Relation enum")
        if not self.marker.strip():
            raise ValueError("marker must be non-empty")
        if not self.provenance.strip():
            raise ValueError("provenance must be non-empty")

    def inverse(self) -> "RelationAnnotation":
        return RelationAnnotation(
            source_event_id=self.target_event_id,
            target_event_id=self.source_event_id,
            relation=self.relation.inverse(),
            marker=self.marker,
            provenance=self.provenance,
        )


@dataclass(frozen=True)
class Rejection:
    reason: RejectionReason
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, RejectionReason):
            raise TypeError("reason must be a RejectionReason enum")
        if not self.message.strip():
            raise ValueError("rejection message must be non-empty")


@dataclass(frozen=True)
class Extraction:
    text: str
    marker: str
    marker_span: CharSpan
    event_a: EventMention
    event_b: EventMention
    relation: RelationAnnotation

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("extraction text must be non-empty")
        if self.marker_span.text_from(self.text).casefold() != self.marker.casefold():
            raise ValueError("marker does not match marker_span")
        self.event_a.validate_against(self.text)
        self.event_b.validate_against(self.text)
        if self.event_a.event_id != self.relation.source_event_id:
            raise ValueError("event_a must be the relation source")
        if self.event_b.event_id != self.relation.target_event_id:
            raise ValueError("event_b must be the relation target")
        spans = (self.event_a.char_span, self.marker_span, self.event_b.char_span)
        if not (spans[0].end <= spans[1].start and spans[1].end <= spans[2].start):
            raise ValueError("event and marker spans must be ordered and non-overlapping")


@dataclass(frozen=True)
class ExtractionResult:
    extraction: Optional[Extraction] = None
    rejection: Optional[Rejection] = None

    def __post_init__(self) -> None:
        if (self.extraction is None) == (self.rejection is None):
            raise ValueError("exactly one of extraction or rejection is required")

    @property
    def accepted(self) -> bool:
        return self.extraction is not None


@dataclass(frozen=True)
class CounterfactualRewrite:
    original_text: str
    rewritten_text: str
    original: Extraction
    rewritten: Extraction
    template_id: str

    def __post_init__(self) -> None:
        if self.original_text != self.original.text:
            raise ValueError("original extraction text mismatch")
        if self.rewritten_text != self.rewritten.text:
            raise ValueError("rewritten extraction text mismatch")
        if self.original.relation.relation.inverse() != self.rewritten.relation.relation:
            raise ValueError("rewritten relation must invert the original relation")
        if not self.template_id.strip():
            raise ValueError("template_id must be non-empty")


@dataclass(frozen=True)
class AnswerUpdate:
    status: AnswerStatus
    value: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AnswerStatus):
            raise TypeError("status must be an AnswerStatus enum")
        if self.status is AnswerStatus.KNOWN:
            if self.value is None or not self.value.strip():
                raise ValueError("known answer update requires a non-empty value")
            if self.reason is not None:
                raise ValueError("known answer update must not carry an unknown reason")
        else:
            if self.value is not None:
                raise ValueError("unknown answer update must not carry an answer value")
            if self.reason is None or not self.reason.strip():
                raise ValueError("unknown answer update requires a reason")


@dataclass(frozen=True)
class SplitAssignment:
    official: str
    internal: Optional[InternalSplit]

    def __post_init__(self) -> None:
        if not self.official.strip():
            raise ValueError("official split must be non-empty")
        if self.official.casefold() != "train" and self.internal is not None:
            raise ValueError("only the official train split may receive an internal split")


@dataclass(frozen=True)
class SourceProvenance:
    relative_path: str
    line_number: int
    source_file_sha256: str

    def __post_init__(self) -> None:
        _source_relative_path(self.relative_path)
        if isinstance(self.line_number, bool) or not isinstance(self.line_number, int):
            raise TypeError("source line_number must be an integer")
        if self.line_number < 1:
            raise ValueError("source line_number must be at least one")
        if not isinstance(self.source_file_sha256, str):
            raise TypeError("source_file_sha256 must be a string")
        if not _SHA256_RE.fullmatch(self.source_file_sha256):
            raise ValueError(
                "source_file_sha256 must be 64 lowercase hexadecimal characters"
            )

    def to_dict(self) -> Mapping[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceProvenance":
        value = _exact_mapping(
            value,
            {"relative_path", "line_number", "source_file_sha256"},
            "SourceProvenance",
        )
        return cls(
            relative_path=value["relative_path"],
            line_number=value["line_number"],
            source_file_sha256=value["source_file_sha256"],
        )


@dataclass(frozen=True)
class TemporalExample:
    record_id: str
    source_id: str
    dataset: str
    split: SplitAssignment
    revision: str
    source_sha256: str
    text: str
    question: str
    answers: Tuple[str, ...]
    answer_type: AnswerType
    events: Tuple[EventMention, ...] = ()
    relations: Tuple[RelationAnnotation, ...] = ()
    counterfactual_pair_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("record_id", "source_id", "dataset", "revision"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if not _SHA256_RE.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be 64 lowercase hexadecimal characters")
        if not self.text:
            raise ValueError("text must be non-empty")
        if not self.question.strip():
            raise ValueError("question must be non-empty")
        if not isinstance(self.answer_type, AnswerType):
            raise TypeError("answer_type must be an AnswerType enum")
        if not self.answers or any(not answer.strip() for answer in self.answers):
            raise ValueError("answers must contain only non-empty strings")
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event IDs must be unique")
        for event in self.events:
            event.validate_against(self.text)
        known_ids = set(event_ids)
        for relation in self.relations:
            if relation.source_event_id not in known_ids or relation.target_event_id not in known_ids:
                raise ValueError("relation endpoint does not name a stored event")
        if self.counterfactual_pair_id is not None and not self.counterfactual_pair_id.strip():
            raise ValueError("counterfactual_pair_id must be non-empty when provided")

    def to_dict(self) -> Mapping[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TemporalExample":
        example_keys = {
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
        }
        value = _exact_mapping(value, example_keys, "TemporalExample")
        split_value = _exact_mapping(value["split"], {"official", "internal"}, "split")
        split = SplitAssignment(
            official=split_value["official"],
            internal=(
                InternalSplit(split_value["internal"])
                if split_value.get("internal") is not None
                else None
            ),
        )
        answers_value = _sequence(value["answers"], "answers")
        if any(not isinstance(answer, str) for answer in answers_value):
            raise TypeError("answers must contain only strings")

        event_values = _sequence(value["events"], "events")
        events_list = []
        for index, raw_event in enumerate(event_values):
            event = _exact_mapping(
                raw_event, {"event_id", "text", "char_span"}, f"events[{index}]"
            )
            char_span = _exact_mapping(
                event["char_span"], {"start", "end"}, f"events[{index}].char_span"
            )
            events_list.append(
                EventMention(
                    event_id=event["event_id"],
                    text=event["text"],
                    char_span=CharSpan(start=char_span["start"], end=char_span["end"]),
                )
            )
        events = tuple(events_list)

        relation_values = _sequence(value["relations"], "relations")
        relations_list = []
        relation_keys = {
            "source_event_id",
            "target_event_id",
            "relation",
            "marker",
            "provenance",
        }
        for index, raw_relation in enumerate(relation_values):
            relation = _exact_mapping(raw_relation, relation_keys, f"relations[{index}]")
            relations_list.append(
                RelationAnnotation(
                    source_event_id=relation["source_event_id"],
                    target_event_id=relation["target_event_id"],
                    relation=Relation(relation["relation"]),
                    marker=relation["marker"],
                    provenance=relation["provenance"],
                )
            )
        relations = tuple(relations_list)
        return cls(
            record_id=value["record_id"],
            source_id=value["source_id"],
            dataset=value["dataset"],
            split=split,
            revision=value["revision"],
            source_sha256=value["source_sha256"],
            text=value["text"],
            question=value["question"],
            answers=tuple(answers_value),
            answer_type=AnswerType(value["answer_type"]),
            events=events,
            relations=relations,
            counterfactual_pair_id=value["counterfactual_pair_id"],
        )
