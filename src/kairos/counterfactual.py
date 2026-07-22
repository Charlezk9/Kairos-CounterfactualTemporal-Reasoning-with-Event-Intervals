"""Whitelisted counterfactual rewrites and conservative answer updates."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .events import extract_explicit_relation
from .schema import (
    AnswerStatus,
    AnswerType,
    AnswerUpdate,
    CounterfactualRewrite,
    Extraction,
    ExtractionResult,
    Relation,
    Rejection,
    RejectionReason,
)


_REWRITE_TARGETS = {
    "before": "after",
    "after": "before",
    "earlier than": "later than",
    "later than": "earlier than",
}


def _case_like(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source.istitle():
        return replacement.title()
    return replacement


def rewrite_counterfactual(extraction: Extraction) -> CounterfactualRewrite | ExtractionResult:
    """Rewrite only the target marker and prove all other characters unchanged."""

    replacement = _REWRITE_TARGETS.get(extraction.marker.casefold())
    if replacement is None:
        return ExtractionResult(
            rejection=Rejection(
                reason=RejectionReason.UNSUPPORTED_REWRITE,
                message="marker is detectable but not in the v0 rewrite whitelist",
                details={"marker": extraction.marker},
            )
        )
    original_surface = extraction.marker_span.text_from(extraction.text)
    replacement_surface = _case_like(original_surface, replacement)
    start, end = extraction.marker_span.start, extraction.marker_span.end
    rewritten_text = extraction.text[:start] + replacement_surface + extraction.text[end:]

    result = extract_explicit_relation(rewritten_text)
    if not result.accepted:
        return ExtractionResult(
            rejection=Rejection(
                reason=RejectionReason.REWRITE_INVARIANT_FAILED,
                message="rewritten text did not yield one valid target relation",
                details={"downstream_reason": result.rejection.reason.value},
            )
        )
    rewritten = result.extraction
    assert rewritten is not None
    if extraction.text[:start] != rewritten_text[:start] or extraction.text[end:] != rewritten_text[start + len(replacement_surface) :]:
        return ExtractionResult(
            rejection=Rejection(
                reason=RejectionReason.REWRITE_INVARIANT_FAILED,
                message="non-target text changed during rewrite",
            )
        )
    if rewritten.relation.relation is not extraction.relation.relation.inverse():
        return ExtractionResult(
            rejection=Rejection(
                reason=RejectionReason.REWRITE_INVARIANT_FAILED,
                message="rewrite did not invert the target relation",
            )
        )
    return CounterfactualRewrite(
        original_text=extraction.text,
        rewritten_text=rewritten_text,
        original=extraction,
        rewritten=rewritten,
        template_id=f"marker:{extraction.marker.casefold()}->{replacement}",
    )


def _normalized(text: str) -> str:
    return " ".join(text.strip().casefold().split())


def _event_choice(question: str) -> Optional[str]:
    normalized = _normalized(question).rstrip("?").strip()
    earlier = {
        "which happened first",
        "which happened earlier",
        "what happened earlier",
        "which came first",
        "which event was first",
        "which event happened first",
        "what was done earlier",
    }
    later = {
        "which happened last",
        "which happened later",
        "what happened later",
        "which came last",
        "which event was last",
        "which event happened last",
        "what was done later",
    }
    if normalized in earlier:
        return "earlier"
    if normalized in later:
        return "later"
    return None


def _ordered_events(extraction: Extraction) -> Optional[Tuple[str, str]]:
    relation = extraction.relation.relation
    if relation is Relation.PRECEDES:
        return extraction.event_a.text, extraction.event_b.text
    if relation is Relation.FOLLOWS:
        return extraction.event_b.text, extraction.event_a.text
    return None


def _parse_relation_question(question: str, extraction: Extraction) -> Optional[Relation]:
    a = re.escape(_normalized(extraction.event_a.text))
    b = re.escape(_normalized(extraction.event_b.text))
    q = _normalized(question).rstrip("?").strip()
    patterns = (
        (rf"(?:did|does) {a} (?:happen|occur|come) before {b}", Relation.PRECEDES),
        (rf"is {a} (?:before|earlier than) {b}", Relation.PRECEDES),
        (rf"(?:did|does) {a} (?:happen|occur|come) after {b}", Relation.FOLLOWS),
        (rf"is {a} (?:after|later than) {b}", Relation.FOLLOWS),
        (rf"(?:do|did) {a} and {b} overlap", Relation.OVERLAPS),
        (rf"(?:does|did) {a} overlap {b}", Relation.OVERLAPS),
        (rf"is {a} (?:during|contained in) {b}", Relation.DURING),
        (rf"does {a} contain {b}", Relation.CONTAINS),
    )
    for pattern, relation in patterns:
        if re.fullmatch(pattern, q):
            return relation
    return None


def update_answer(
    *,
    original_answer: str,
    question: str,
    answer_type: AnswerType,
    rewrite: CounterfactualRewrite,
) -> AnswerUpdate:
    """Return a gold answer only when a deterministic proof is available."""

    if not original_answer.strip():
        raise ValueError("original_answer must be non-empty")
    if not isinstance(answer_type, AnswerType):
        raise TypeError("answer_type must be an AnswerType enum")

    if answer_type is AnswerType.EXTRACTIVE:
        choice = _event_choice(question)
        original_order = _ordered_events(rewrite.original)
        rewritten_order = _ordered_events(rewrite.rewritten)
        if choice is None or original_order is None or rewritten_order is None:
            return AnswerUpdate(AnswerStatus.UNKNOWN, reason="not an exact earlier/later event-choice question")
        original_expected = original_order[0] if choice == "earlier" else original_order[1]
        if _normalized(original_answer) != _normalized(original_expected):
            return AnswerUpdate(AnswerStatus.UNKNOWN, reason="original answer does not exactly match the implied target event")
        updated = rewritten_order[0] if choice == "earlier" else rewritten_order[1]
        return AnswerUpdate(AnswerStatus.KNOWN, value=updated)

    if answer_type is AnswerType.YES_NO:
        queried = _parse_relation_question(question, rewrite.original)
        normalized_answer = _normalized(original_answer)
        if queried is None:
            return AnswerUpdate(AnswerStatus.UNKNOWN, reason="question is not an exact supported relation query")
        target_relations = {
            rewrite.original.relation.relation,
            rewrite.rewritten.relation.relation,
        }
        if queried not in target_relations:
            return AnswerUpdate(AnswerStatus.UNKNOWN, reason="question does not query the changed target relation")
        if normalized_answer not in {"yes", "no"}:
            return AnswerUpdate(AnswerStatus.UNKNOWN, reason="original yes/no answer is not yes or no")
        expected_original = "yes" if queried is rewrite.original.relation.relation else "no"
        if normalized_answer != expected_original:
            return AnswerUpdate(AnswerStatus.UNKNOWN, reason="original answer conflicts with the relation truth table")
        updated = "yes" if queried is rewrite.rewritten.relation.relation else "no"
        return AnswerUpdate(AnswerStatus.KNOWN, value=updated)

    return AnswerUpdate(
        AnswerStatus.UNKNOWN,
        reason=f"{answer_type.value} answers require a task-specific deterministic updater",
    )
