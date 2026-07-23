"""Backbone-independent chat formatting and character-to-token alignment."""

from __future__ import annotations

from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Sequence

import torch
from torch import Tensor

from .schema import CharSpan


_TEXT_BYTE_LIMIT = 4 * 1024 * 1024
_EVENT_LIMIT = 256


class BackboneContractError(ValueError):
    """A chat-formatting or span-alignment invariant failed."""


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise BackboneContractError(f"{name} must be a string")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as error:
        raise BackboneContractError(f"{name} is not valid Unicode") from error
    if not allow_empty and not value:
        raise BackboneContractError(f"{name} must be non-empty")
    if size > _TEXT_BYTE_LIMIT:
        raise BackboneContractError(f"{name} exceeds its byte limit")
    return value


@dataclass(frozen=True)
class FormattedPrompt:
    text: str
    user_content_span: CharSpan

    def __post_init__(self) -> None:
        _text(self.text, "formatted prompt")
        if not isinstance(self.user_content_span, CharSpan):
            raise BackboneContractError("user_content_span must be a CharSpan")
        if self.user_content_span.end > len(self.text):
            raise BackboneContractError("user content span exceeds formatted prompt")


@dataclass(frozen=True)
class CandidateEncodingText:
    text: str
    candidate_span: CharSpan

    def __post_init__(self) -> None:
        _text(self.text, "candidate encoding text")
        if not isinstance(self.candidate_span, CharSpan):
            raise BackboneContractError("candidate_span must be a CharSpan")
        if self.candidate_span.end > len(self.text):
            raise BackboneContractError("candidate span exceeds encoding text")


@dataclass(frozen=True)
class AlignedEventBatch:
    event_token_mask: Tensor
    event_mask: Tensor

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_token_mask, Tensor)
            or self.event_token_mask.dtype != torch.bool
            or self.event_token_mask.ndim != 3
        ):
            raise BackboneContractError("event_token_mask is invalid")
        if (
            not isinstance(self.event_mask, Tensor)
            or self.event_mask.dtype != torch.bool
            or self.event_mask.shape != self.event_token_mask.shape[:2]
        ):
            raise BackboneContractError("event_mask is invalid")


def format_chat_prompt(tokenizer: Any, user_prompt: str) -> FormattedPrompt:
    """Apply one user-only chat template and bind the literal content location."""

    user_prompt = _text(user_prompt, "user prompt")
    formatter = getattr(tokenizer, "apply_chat_template", None)
    if not callable(formatter):
        raise BackboneContractError("tokenizer has no callable chat template")
    try:
        formatted = formatter(
            [{"role": "user", "content": user_prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception as error:
        raise BackboneContractError("tokenizer chat template failed") from error
    formatted = _text(formatted, "formatted prompt")
    first = formatted.find(user_prompt)
    if first < 0 or formatted.find(user_prompt, first + 1) >= 0:
        raise BackboneContractError(
            "formatted prompt must contain the literal user prompt exactly once"
        )
    return FormattedPrompt(formatted, CharSpan(first, first + len(user_prompt)))


def shift_user_spans(
    formatted: FormattedPrompt, user_prompt: str, spans: Sequence[CharSpan]
) -> tuple[CharSpan, ...]:
    """Move user-content character spans into the formatted chat string."""

    if not isinstance(formatted, FormattedPrompt):
        raise BackboneContractError("formatted must be a FormattedPrompt")
    user_prompt = _text(user_prompt, "user prompt")
    if formatted.user_content_span.text_from(formatted.text) != user_prompt:
        raise BackboneContractError("formatted prompt is not bound to user prompt")
    if isinstance(spans, (str, bytes, bytearray)) or not isinstance(
        spans, SequenceABC
    ):
        raise BackboneContractError("user spans must be a sequence")
    result: list[CharSpan] = []
    for span in spans:
        if not isinstance(span, CharSpan) or span.end > len(user_prompt):
            raise BackboneContractError("user span is invalid")
        result.append(
            CharSpan(
                formatted.user_content_span.start + span.start,
                formatted.user_content_span.start + span.end,
            )
        )
    return tuple(result)


def build_candidate_encoding_text(
    query: str, serialized_candidate: str
) -> CandidateEncodingText:
    """Create the fixed `[q;a]` text and exact answer-character span."""

    query = _text(query, "query")
    serialized_candidate = _text(
        serialized_candidate, "serialized candidate", allow_empty=True
    )
    prefix = "<QUERY>\n" + query + "\n</QUERY>\n<CANDIDATE>\n"
    suffix = "\n</CANDIDATE>"
    text = prefix + serialized_candidate + suffix
    if not serialized_candidate:
        raise BackboneContractError(
            "serialized candidate must use an explicit representation for empty answer"
        )
    return CandidateEncodingText(
        text=text,
        candidate_span=CharSpan(len(prefix), len(prefix) + len(serialized_candidate)),
    )


def _offset_tensors(offset_mapping: Tensor, attention_mask: Tensor) -> None:
    if (
        not isinstance(offset_mapping, Tensor)
        or offset_mapping.ndim != 3
        or offset_mapping.shape[-1] != 2
        or offset_mapping.dtype not in {torch.int32, torch.int64}
    ):
        raise BackboneContractError(
            "offset_mapping must be an integer [batch, tokens, 2] tensor"
        )
    if not isinstance(attention_mask, Tensor) or attention_mask.shape != offset_mapping.shape[:2]:
        raise BackboneContractError("attention_mask shape is invalid")
    if attention_mask.dtype == torch.bool:
        normalized_attention = attention_mask
    elif attention_mask.dtype in {torch.int32, torch.int64}:
        if torch.any((attention_mask != 0) & (attention_mask != 1)):
            raise BackboneContractError("integer attention_mask must contain only 0/1")
        normalized_attention = attention_mask.bool()
    else:
        raise BackboneContractError("attention_mask must be Boolean or integer")
    starts = offset_mapping[..., 0]
    ends = offset_mapping[..., 1]
    if torch.any(starts < 0) or torch.any(ends < starts):
        raise BackboneContractError("token offsets are negative or reversed")
    if torch.any((~normalized_attention) & ((starts != 0) | (ends != 0))):
        raise BackboneContractError("padded token offsets must be (0,0)")


def align_char_spans(
    offset_mapping: Tensor,
    attention_mask: Tensor,
    spans: Sequence[Sequence[CharSpan]],
) -> AlignedEventBatch:
    """Align non-overlapping character spans to all intersecting real tokens."""

    _offset_tensors(offset_mapping, attention_mask)
    if isinstance(spans, (str, bytes, bytearray)) or not isinstance(
        spans, SequenceABC
    ):
        raise BackboneContractError("batch spans must be a sequence")
    batch, token_count, unused = offset_mapping.shape
    if len(spans) != batch:
        raise BackboneContractError("span batch size differs from token offsets")
    normalized_attention = attention_mask.bool()
    normalized: list[tuple[CharSpan, ...]] = []
    for batch_index, example_spans in enumerate(spans):
        if isinstance(example_spans, (str, bytes, bytearray)) or not isinstance(
            example_spans, SequenceABC
        ):
            raise BackboneContractError("example spans must be a sequence")
        if not example_spans or len(example_spans) > _EVENT_LIMIT:
            raise BackboneContractError("event count is outside its limit")
        values: list[CharSpan] = []
        previous_end = -1
        for span in example_spans:
            if not isinstance(span, CharSpan):
                raise BackboneContractError("event span must be a CharSpan")
            if span.start < previous_end:
                raise BackboneContractError("event spans overlap or are out of order")
            previous_end = span.end
            values.append(span)
        normalized.append(tuple(values))
    max_events = max(len(value) for value in normalized)
    event_token_mask = torch.zeros(
        (batch, max_events, token_count),
        dtype=torch.bool,
        device=offset_mapping.device,
    )
    event_mask = torch.zeros(
        (batch, max_events), dtype=torch.bool, device=offset_mapping.device
    )
    token_starts = offset_mapping[..., 0]
    token_ends = offset_mapping[..., 1]
    real_token = normalized_attention & (token_ends > token_starts)
    for batch_index, example_spans in enumerate(normalized):
        for event_index, span in enumerate(example_spans):
            selected = (
                real_token[batch_index]
                & (token_starts[batch_index] < span.end)
                & (token_ends[batch_index] > span.start)
            )
            if not torch.any(selected):
                raise BackboneContractError(
                    "event span has no aligned token, possibly due to truncation"
                )
            event_token_mask[batch_index, event_index] = selected
            event_mask[batch_index, event_index] = True
    return AlignedEventBatch(event_token_mask, event_mask)
