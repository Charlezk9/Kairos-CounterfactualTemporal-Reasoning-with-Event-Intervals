"""Conservative explicit-marker event and relation extraction."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .schema import (
    CharSpan,
    EventMention,
    Extraction,
    ExtractionResult,
    Relation,
    RelationAnnotation,
    Rejection,
    RejectionReason,
)


SUPPORTED_MARKERS: Dict[str, Relation] = {
    "before": Relation.PRECEDES,
    "after": Relation.FOLLOWS,
    "earlier than": Relation.PRECEDES,
    "later than": Relation.FOLLOWS,
    "prior to": Relation.PRECEDES,
}

UNSUPPORTED_V0_MARKERS = ("while", "when", "until", "then")
_ALL_MARKERS = tuple(SUPPORTED_MARKERS) + UNSUPPORTED_V0_MARKERS
_BOUNDARIES = frozenset(".?!;")


def _marker_matches(text: str) -> List[Tuple[str, re.Match[str]]]:
    matches: List[Tuple[str, re.Match[str]]] = []
    for marker in _ALL_MARKERS:
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in marker.split()) + r"(?!\w)"
        matches.extend((marker, match) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    matches.sort(key=lambda item: (item[1].start(), -(item[1].end() - item[1].start())))
    return matches


def _reject(reason: RejectionReason, message: str, **details: object) -> ExtractionResult:
    return ExtractionResult(rejection=Rejection(reason=reason, message=message, details=details))


def _trimmed_span(text: str, start: int, end: int) -> CharSpan | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        return None
    return CharSpan(start, end)


def extract_explicit_relation(text: str) -> ExtractionResult:
    """Extract two clause-local event spans around the sole known marker.

    This is intentionally a high-precision v0 detector, not a general event parser.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    matches = _marker_matches(text)
    if not matches:
        return _reject(RejectionReason.NO_MARKER, "no recognized temporal marker was found")
    if len(matches) != 1:
        return _reject(
            RejectionReason.MULTIPLE_MARKERS,
            "v0 requires exactly one recognized temporal marker",
            markers=[marker for marker, _ in matches],
            spans=[[match.start(), match.end()] for _, match in matches],
        )

    marker, match = matches[0]
    if marker not in SUPPORTED_MARKERS:
        return _reject(
            RejectionReason.UNSUPPORTED_MARKER,
            "the sole marker is recognized but unsupported in v0",
            marker=marker,
        )

    clause_start = match.start()
    while clause_start > 0 and text[clause_start - 1] not in _BOUNDARIES:
        clause_start -= 1
    clause_end = match.end()
    while clause_end < len(text) and text[clause_end] not in _BOUNDARIES:
        clause_end += 1

    left_span = _trimmed_span(text, clause_start, match.start())
    if left_span is None:
        return _reject(RejectionReason.EMPTY_LEFT_EVENT, "marker has no non-whitespace left event")
    right_span = _trimmed_span(text, match.end(), clause_end)
    if right_span is None:
        return _reject(RejectionReason.EMPTY_RIGHT_EVENT, "marker has no non-whitespace right event")

    marker_span = CharSpan(match.start(), match.end())
    if left_span.end > marker_span.start or marker_span.end > right_span.start:
        return _reject(RejectionReason.OVERLAPPING_SPANS, "event and marker spans overlap")

    event_a = EventMention("e1", left_span.text_from(text), left_span)
    event_b = EventMention("e2", right_span.text_from(text), right_span)
    annotation = RelationAnnotation(
        source_event_id=event_a.event_id,
        target_event_id=event_b.event_id,
        relation=SUPPORTED_MARKERS[marker],
        marker=marker,
    )
    extraction = Extraction(
        text=text,
        marker=marker,
        marker_span=marker_span,
        event_a=event_a,
        event_b=event_b,
        relation=annotation,
    )
    return ExtractionResult(extraction=extraction)
