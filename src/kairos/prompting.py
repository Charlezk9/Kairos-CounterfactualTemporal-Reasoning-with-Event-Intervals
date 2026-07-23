"""Deterministic transfer prompts, strict output parsing and candidate pools."""

from __future__ import annotations

from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Sequence

from .ids import canonical_json
from .transfer_eval import (
    TimeQaExample,
    TorqueExample,
    normalize_timeqa_answer,
    normalize_torque_span,
)


_FINAL_PREFIX = "FINAL_ANSWER: "
_PROMPT_BYTE_LIMIT = 4 * 1024 * 1024
_RESPONSE_BYTE_LIMIT = 65_536
_RESPONSE_LINE_LIMIT = 1024
_TIMEQA_ANSWER_BYTE_LIMIT = 4096
_TORQUE_SPAN_BYTE_LIMIT = 4096
_TORQUE_SPAN_COUNT_LIMIT = 64
_CANDIDATE_COUNT_LIMIT = 64


class PromptError(ValueError):
    """A deterministic prompt, response or candidate invariant failed."""


class PromptStyle(str, Enum):
    DIRECT = "direct"
    COT = "cot"


@dataclass(frozen=True)
class PromptBundle:
    record_id: str
    dataset: str
    style: PromptStyle
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise PromptError("prompt record_id must be non-empty")
        if self.dataset not in {"torque-dev", "timeqa-hard"}:
            raise PromptError("prompt dataset is invalid")
        if not isinstance(self.style, PromptStyle):
            raise PromptError("prompt style is invalid")
        if not isinstance(self.text, str) or not self.text:
            raise PromptError("prompt text must be non-empty")
        try:
            size = len(self.text.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as error:
            raise PromptError("prompt text is not valid Unicode") from error
        if size > _PROMPT_BYTE_LIMIT:
            raise PromptError("prompt text exceeds its byte limit")


def _style(value: Any) -> PromptStyle:
    if isinstance(value, PromptStyle):
        return value
    try:
        return PromptStyle(value)
    except (TypeError, ValueError) as error:
        raise PromptError("prompt style must be direct or cot") from error


def _reasoning_instruction(style: PromptStyle) -> str:
    if style is PromptStyle.DIRECT:
        return "Answer the question directly. Do not include an explanation."
    return (
        "Reason step by step about the temporal relations. Keep the reasoning "
        "concise, then provide the answer in the required final line."
    )


def build_torque_prompt(
    example: TorqueExample, style: PromptStyle | str
) -> PromptBundle:
    """Build a fixed TORQUE prompt without exposing gold annotations."""

    if not isinstance(example, TorqueExample):
        raise PromptError("TORQUE prompt requires a TorqueExample")
    style = _style(style)
    text = "\n".join(
        (
            "Task: temporal event extraction.",
            "Read the passage and answer the question with every matching event span.",
            "Return spans exactly as they appear in the passage, in passage order.",
            _reasoning_instruction(style),
            "The final non-empty line must be FINAL_ANSWER: followed by a JSON array of strings.",
            "Use [] when no event answers the question.",
            "",
            "<PASSAGE>",
            example.passage,
            "</PASSAGE>",
            "<QUESTION>",
            example.question,
            "</QUESTION>",
        )
    )
    return PromptBundle(example.record_id, "torque-dev", style, text)


def build_timeqa_prompt(
    example: TimeQaExample, style: PromptStyle | str
) -> PromptBundle:
    """Build a fixed TimeQA-Hard prompt containing all supplied documents."""

    if not isinstance(example, TimeQaExample):
        raise PromptError("TimeQA prompt requires a TimeQaExample")
    style = _style(style)
    documents: list[str] = []
    for number, paragraph in enumerate(example.paragraphs, start=1):
        documents.extend(
            (
                f"<DOCUMENT index=\"{number}\">",
                f"TITLE: {paragraph.title}",
                paragraph.text,
                "</DOCUMENT>",
            )
        )
    if not documents:
        documents.append("<NO_SUPPORTING_DOCUMENTS />")
    text = "\n".join(
        (
            "Task: time-sensitive question answering.",
            "Answer using the temporal context and supporting documents.",
            _reasoning_instruction(style),
            "The final non-empty line must be FINAL_ANSWER: followed by one JSON string.",
            "Use the empty JSON string \"\" only when the correct answer is empty.",
            "",
            "<TEMPORAL_CONTEXT>",
            example.context,
            "</TEMPORAL_CONTEXT>",
            "<SUPPORTING_DOCUMENTS>",
            *documents,
            "</SUPPORTING_DOCUMENTS>",
            "<QUESTION>",
            example.question,
            "</QUESTION>",
        )
    )
    return PromptBundle(example.record_id, "timeqa-hard", style, text)


def _final_json(response: str) -> Any:
    if not isinstance(response, str):
        raise PromptError("model response must be a string")
    try:
        encoded = response.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise PromptError("model response is not valid Unicode") from error
    if not encoded or len(encoded) > _RESPONSE_BYTE_LIMIT:
        raise PromptError("model response is empty or exceeds its byte limit")
    lines = response.splitlines()
    if len(lines) > _RESPONSE_LINE_LIMIT:
        raise PromptError("model response exceeds its line limit")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise PromptError("model response has no non-empty line")
    final_lines = [line for line in lines if line.startswith(_FINAL_PREFIX)]
    if len(final_lines) != 1 or final_lines[0] != lines[-1]:
        raise PromptError("model response must have exactly one final answer line at the end")
    payload = lines[-1][len(_FINAL_PREFIX) :]
    if not payload:
        raise PromptError("final answer JSON payload is empty")

    def reject_constant(unused: str) -> Any:
        raise PromptError("final answer JSON contains a non-finite number")

    try:
        return json.loads(payload, parse_constant=reject_constant)
    except json.JSONDecodeError as error:
        raise PromptError("final answer is not strict JSON") from error


def parse_torque_response(response: str) -> tuple[str, ...]:
    """Parse the sole terminal JSON array from a TORQUE generation."""

    value = _final_json(response)
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        raise PromptError("TORQUE final answer must be a JSON array")
    if len(value) > _TORQUE_SPAN_COUNT_LIMIT:
        raise PromptError("TORQUE final answer has too many spans")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PromptError("TORQUE answer spans must be non-empty strings")
        try:
            size = len(item.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as error:
            raise PromptError("TORQUE answer span is not valid Unicode") from error
        if size > _TORQUE_SPAN_BYTE_LIMIT:
            raise PromptError("TORQUE answer span exceeds its byte limit")
        result.append(item)
    return tuple(result)


def parse_timeqa_response(response: str) -> str:
    """Parse the sole terminal JSON string from a TimeQA generation."""

    value = _final_json(response)
    if not isinstance(value, str):
        raise PromptError("TimeQA final answer must be one JSON string")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as error:
        raise PromptError("TimeQA final answer is not valid Unicode") from error
    if size > _TIMEQA_ANSWER_BYTE_LIMIT:
        raise PromptError("TimeQA final answer exceeds its byte limit")
    return value


def deduplicate_timeqa_candidates(values: Sequence[str]) -> tuple[str, ...]:
    """Keep first occurrence under the fixed TimeQA evaluation normalizer."""

    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, SequenceABC
    ):
        raise PromptError("TimeQA candidates must be a non-string sequence")
    if not values or len(values) > _CANDIDATE_COUNT_LIMIT:
        raise PromptError("TimeQA candidate count is outside its limit")
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise PromptError("TimeQA candidates must be strings")
        key = normalize_timeqa_answer(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def deduplicate_torque_candidates(
    values: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    """Deduplicate span-set candidates and spans while keeping first surfaces."""

    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, SequenceABC
    ):
        raise PromptError("TORQUE candidates must be a non-string sequence")
    if not values or len(values) > _CANDIDATE_COUNT_LIMIT:
        raise PromptError("TORQUE candidate count is outside its limit")
    seen_candidates: set[tuple[str, ...]] = set()
    result: list[tuple[str, ...]] = []
    for candidate in values:
        if isinstance(candidate, (str, bytes, bytearray)) or not isinstance(
            candidate, SequenceABC
        ):
            raise PromptError("each TORQUE candidate must be a span sequence")
        surfaces: list[str] = []
        normalized_spans: set[str] = set()
        for span in candidate:
            if not isinstance(span, str) or not span.strip():
                raise PromptError("TORQUE candidate spans must be non-empty strings")
            normalized = normalize_torque_span(span)
            if normalized not in normalized_spans:
                normalized_spans.add(normalized)
                surfaces.append(span)
        key = tuple(sorted(normalized_spans))
        if key not in seen_candidates:
            seen_candidates.add(key)
            result.append(tuple(surfaces))
    return tuple(result)


def serialize_candidate(dataset: str, candidate: Any) -> str:
    """Produce the stable text passed to the backbone candidate encoder."""

    if dataset == "timeqa-hard":
        if not isinstance(candidate, str):
            raise PromptError("TimeQA candidate must be a string")
        return canonical_json(candidate)
    if dataset == "torque-dev":
        if isinstance(candidate, (str, bytes, bytearray)) or not isinstance(
            candidate, SequenceABC
        ):
            raise PromptError("TORQUE candidate must be a span sequence")
        spans = parse_torque_response(
            _FINAL_PREFIX + canonical_json(list(candidate))
        )
        return canonical_json(list(spans))
    raise PromptError("candidate dataset is invalid")
