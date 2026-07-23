"""Gold-free CoT+Verifier selection over frozen TORQUE baseline candidates."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from .generation import (
    MODEL_CONTEXT_TOKENS,
    MODEL_ID,
    MODEL_REVISION,
    GenerationResult,
    _generated_token_count,
    _token_batch,
)
from .ids import canonical_json
from .prediction_artifacts import GenerationEvidence
from .prompting import deduplicate_torque_candidates
from .transfer_eval import TorqueExample


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RESPONSE_BYTE_LIMIT = 65_536
_RESPONSE_LINE_LIMIT = 1_024


class VerifierGenerationError(ValueError):
    """A verifier configuration, prompt or runtime invariant failed."""


@dataclass(frozen=True)
class VerifierGenerationConfig:
    reference_run_id: str
    reference_manifest_sha256: str
    candidate_run_id: str
    candidate_manifest_sha256: str
    max_new_tokens: int = 32
    batch_size: int = 8

    def __post_init__(self) -> None:
        for name in ("reference_run_id", "candidate_run_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise VerifierGenerationError(f"{name} must be non-empty")
        if self.reference_run_id == self.candidate_run_id:
            raise VerifierGenerationError("verifier input runs must differ")
        for name in ("reference_manifest_sha256", "candidate_manifest_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX64.fullmatch(value):
                raise VerifierGenerationError(f"{name} must be lowercase SHA256")
        if (
            isinstance(self.max_new_tokens, bool)
            or not isinstance(self.max_new_tokens, int)
            or not 1 <= self.max_new_tokens <= 128
        ):
            raise VerifierGenerationError("max_new_tokens is outside its limit")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or not 1 <= self.batch_size <= 8
        ):
            raise VerifierGenerationError("batch_size is outside its limit")

    @property
    def method_name(self) -> str:
        return "cot-verifier"

    @property
    def max_input_tokens(self) -> int:
        return MODEL_CONTEXT_TOKENS - self.max_new_tokens

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": "torque-cot-verifier-config-v1",
            "dataset": "torque-dev",
            "method": self.method_name,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "model_context_tokens": MODEL_CONTEXT_TOKENS,
            "max_input_tokens": self.max_input_tokens,
            "max_new_tokens": self.max_new_tokens,
            "batch_size": self.batch_size,
            "do_sample": False,
            "fallback": "reference-candidate-on-parse-error",
            "equivalent_candidate_policy": "reference-without-generation",
            "candidate_order": ["reference-direct", "candidate-cot"],
            "reference_run_id": self.reference_run_id,
            "reference_manifest_sha256": self.reference_manifest_sha256,
            "candidate_run_id": self.candidate_run_id,
            "candidate_manifest_sha256": self.candidate_manifest_sha256,
            "prompt_schema_version": "torque-cot-verifier-prompt-v1",
            "parser_schema_version": "terminal-json-index-parser-v1",
        }


def _torque_candidate(value: Any, name: str) -> list[str]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        raise VerifierGenerationError(f"{name} must be a span sequence")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise VerifierGenerationError(f"{name} spans must be non-empty strings")
        result.append(item)
    return result


def _candidate_pairs(
    examples: Sequence[Any],
    reference_predictions: Mapping[str, Any],
    candidate_predictions: Mapping[str, Any],
) -> tuple[tuple[TorqueExample, list[str], list[str], bool], ...]:
    if isinstance(examples, (str, bytes, bytearray)) or not isinstance(
        examples, SequenceABC
    ):
        raise VerifierGenerationError("examples must be a non-string sequence")
    values = tuple(examples)
    if not values or any(not isinstance(item, TorqueExample) for item in values):
        raise VerifierGenerationError("examples must be non-empty TORQUE examples")
    if not isinstance(reference_predictions, MappingABC) or not isinstance(
        candidate_predictions, MappingABC
    ):
        raise VerifierGenerationError("verifier predictions must be mappings")
    expected = tuple(example.record_id for example in values)
    if len(set(expected)) != len(expected):
        raise VerifierGenerationError("example record IDs are duplicated")
    for predictions in (reference_predictions, candidate_predictions):
        if set(predictions) != set(expected):
            raise VerifierGenerationError("verifier prediction coverage differs")
    result = []
    for example in values:
        reference = _torque_candidate(
            reference_predictions[example.record_id], "reference candidate"
        )
        candidate = _torque_candidate(
            candidate_predictions[example.record_id], "CoT candidate"
        )
        unique = deduplicate_torque_candidates((reference, candidate))
        equivalent = len(unique) == 1
        result.append((example, reference, candidate, equivalent))
    return tuple(result)


def build_torque_verifier_prompt(
    example: TorqueExample,
    reference_candidate: Sequence[str],
    cot_candidate: Sequence[str],
) -> str:
    """Build the frozen gold-free candidate-selection prompt."""

    if not isinstance(example, TorqueExample):
        raise VerifierGenerationError("verifier prompt requires a TORQUE example")
    reference = _torque_candidate(reference_candidate, "reference candidate")
    candidate = _torque_candidate(cot_candidate, "CoT candidate")
    return "\n".join(
        (
            "Task: verify two candidate answers for temporal event extraction.",
            "Use only the passage and question. The candidates may be wrong.",
            "Select the candidate containing every matching event span and no other spans.",
            "Spans should match the passage and be interpreted as an unordered answer set.",
            "Reason concisely, then return exactly one candidate index.",
            "The final non-empty line must be FINAL_ANSWER: followed by JSON integer 0 or 1.",
            "",
            "<PASSAGE>",
            example.passage,
            "</PASSAGE>",
            "<QUESTION>",
            example.question,
            "</QUESTION>",
            "<CANDIDATE_0>",
            canonical_json(reference),
            "</CANDIDATE_0>",
            "<CANDIDATE_1>",
            canonical_json(candidate),
            "</CANDIDATE_1>",
        )
    )


def parse_verifier_response(response: str) -> int:
    """Parse one unique terminal JSON index without recovering malformed output."""

    if not isinstance(response, str):
        raise VerifierGenerationError("verifier response must be a string")
    try:
        encoded = response.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise VerifierGenerationError("verifier response is not valid Unicode") from error
    if not encoded or len(encoded) > _RESPONSE_BYTE_LIMIT:
        raise VerifierGenerationError("verifier response is empty or oversized")
    lines = response.splitlines()
    if len(lines) > _RESPONSE_LINE_LIMIT:
        raise VerifierGenerationError("verifier response has too many lines")
    while lines and not lines[-1].strip():
        lines.pop()
    final = [line for line in lines if line.startswith("FINAL_ANSWER: ")]
    if not lines or len(final) != 1 or final[0] != lines[-1]:
        raise VerifierGenerationError("verifier response has no unique terminal answer")
    payload = lines[-1][len("FINAL_ANSWER: ") :]
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise VerifierGenerationError("verifier answer is not strict JSON") from error
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1}:
        raise VerifierGenerationError("verifier answer must be integer 0 or 1")
    return value


def run_torque_verifier_generation(
    model: Any,
    tokenizer: Any,
    examples: Sequence[Any],
    reference_predictions: Mapping[str, Any],
    candidate_predictions: Mapping[str, Any],
    config: VerifierGenerationConfig,
    device: str | torch.device,
) -> GenerationResult:
    """Select between Direct and CoT candidates without reading gold annotations."""

    if not isinstance(config, VerifierGenerationConfig):
        raise VerifierGenerationError("config must be a VerifierGenerationConfig")
    pairs = _candidate_pairs(examples, reference_predictions, candidate_predictions)
    if not callable(getattr(model, "generate", None)):
        raise VerifierGenerationError("model has no callable generate method")
    if not callable(tokenizer):
        raise VerifierGenerationError("tokenizer is not callable")
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(pad_token_id, bool) or not isinstance(pad_token_id, int):
        raise VerifierGenerationError("tokenizer pad_token_id is invalid")
    if isinstance(eos_token_id, int) and not isinstance(eos_token_id, bool):
        eos_ids = {eos_token_id}
    elif isinstance(eos_token_id, SequenceABC) and not isinstance(
        eos_token_id, (str, bytes, bytearray)
    ):
        eos_ids = {
            int(item)
            for item in eos_token_id
            if isinstance(item, int) and not isinstance(item, bool)
        }
        if len(eos_ids) != len(eos_token_id):
            raise VerifierGenerationError("tokenizer eos_token_id is invalid")
    else:
        raise VerifierGenerationError("tokenizer eos_token_id is invalid")
    if not eos_ids:
        raise VerifierGenerationError("tokenizer eos_token_id must be non-empty")
    try:
        tokenizer.padding_side = "left"
    except Exception as error:
        raise VerifierGenerationError("cannot set tokenizer left padding") from error

    predictions: dict[str, list[str]] = {}
    evidence: dict[str, GenerationEvidence] = {}
    pending = []
    for example, reference, candidate, equivalent in pairs:
        if equivalent:
            predictions[example.record_id] = reference
            evidence[example.record_id] = GenerationEvidence(
                raw_response="",
                parse_status="NOT_APPLICABLE",
                input_token_count=0,
                generated_token_count=0,
            )
        else:
            pending.append((example, reference, candidate))

    input_counts: list[int] = []
    generated_total = 0
    parse_errors = 0
    for offset in range(0, len(pending), config.batch_size):
        batch = pending[offset : offset + config.batch_size]
        prompts = [
            build_torque_verifier_prompt(example, reference, candidate)
            for example, reference, candidate in batch
        ]
        encoded = _token_batch(tokenizer, prompts)
        counts = encoded["attention_mask"].sum(dim=1)
        if torch.any(counts <= 0):
            raise VerifierGenerationError("a tokenized verifier prompt is empty")
        if torch.any(counts > config.max_input_tokens):
            raise VerifierGenerationError("a verifier prompt exceeds the context budget")
        input_width = encoded["input_ids"].shape[1]
        if input_width + config.max_new_tokens > MODEL_CONTEXT_TOKENS:
            raise VerifierGenerationError("padded verifier batch exceeds the context budget")
        input_counts.extend(int(value) for value in counts.tolist())
        try:
            device_inputs = {
                key: tensor.to(device=device, non_blocking=False)
                for key, tensor in encoded.items()
            }
            with torch.inference_mode():
                generated = model.generate(
                    **device_inputs,
                    max_new_tokens=config.max_new_tokens,
                    do_sample=False,
                    temperature=None,
                    top_p=None,
                    top_k=None,
                    use_cache=True,
                    pad_token_id=pad_token_id,
                    eos_token_id=sorted(eos_ids),
                )
        except Exception as error:
            raise VerifierGenerationError("verifier model generation failed") from error
        if (
            not isinstance(generated, Tensor)
            or generated.ndim != 2
            or generated.shape[0] != len(batch)
            or generated.shape[1] < input_width
            or generated.shape[1] > input_width + config.max_new_tokens
        ):
            raise VerifierGenerationError("verifier generation tensor shape is invalid")
        new_tokens = generated[:, input_width:].detach().cpu()
        for item, token_row, input_count in zip(batch, new_tokens, counts.tolist()):
            example, reference, candidate = item
            try:
                raw_response = tokenizer.decode(
                    token_row,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
            except Exception as error:
                raise VerifierGenerationError("tokenizer verifier decode failed") from error
            token_count = _generated_token_count(token_row, eos_ids, pad_token_id)
            generated_total += token_count
            try:
                selected = parse_verifier_response(raw_response)
                parse_status = "PARSED"
            except VerifierGenerationError:
                selected = 0
                parse_status = "PARSE_ERROR"
                parse_errors += 1
            predictions[example.record_id] = reference if selected == 0 else candidate
            evidence[example.record_id] = GenerationEvidence(
                raw_response=raw_response,
                parse_status=parse_status,
                input_token_count=int(input_count),
                generated_token_count=token_count,
            )
    ordered_predictions = {example.record_id: predictions[example.record_id] for example, *_ in pairs}
    ordered_evidence = {example.record_id: evidence[example.record_id] for example, *_ in pairs}
    return GenerationResult(
        predictions=ordered_predictions,
        evidence=ordered_evidence,
        parse_error_count=parse_errors,
        input_token_min=min(input_counts) if input_counts else 0,
        input_token_max=max(input_counts) if input_counts else 0,
        generated_token_total=generated_total,
    )
