"""Frozen eight-sample CoT Self-Consistency baseline for TORQUE."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from . import generation
from .ids import canonical_json
from .prediction_artifacts import (
    GenerationEvidence,
    PredictionArtifactError,
    VerifiedPredictionArtifact,
    _strict_json,
    verify_predictions,
)
from .prompting import PromptStyle, parse_torque_response
from .transfer_eval import TorqueExample, normalize_torque_span


SAMPLE_COUNT = 8
TEMPERATURE = 0.7
TOP_P = 0.9
TOP_K = 0
MAX_NEW_TOKENS = 512
CONFIG_SCHEMA_VERSION = "self-consistency-generation-config-v1"
EVIDENCE_SCHEMA_VERSION = "self-consistency-evidence-envelope-v1"
AGGREGATION_VERSION = "normalized-set-plurality-earliest-sample-v1"
METHOD_NAME = "self-consistency"


class SelfConsistencyError(ValueError):
    """The frozen sampling, aggregation, or replay contract failed."""


@dataclass(frozen=True)
class SelfConsistencyConfig:
    dataset: str = "torque-dev"
    sample_count: int = SAMPLE_COUNT
    temperature: float = TEMPERATURE
    top_p: float = TOP_P
    top_k: int = TOP_K
    max_new_tokens: int = MAX_NEW_TOKENS
    batch_size: int = 8

    def __post_init__(self) -> None:
        if (
            self.dataset != "torque-dev"
            or not isinstance(self.sample_count, int)
            or isinstance(self.sample_count, bool)
            or not isinstance(self.temperature, float)
            or not isinstance(self.top_p, float)
            or not isinstance(self.top_k, int)
            or isinstance(self.top_k, bool)
            or not isinstance(self.max_new_tokens, int)
            or isinstance(self.max_new_tokens, bool)
            or not isinstance(self.batch_size, int)
            or isinstance(self.batch_size, bool)
            or self.sample_count != SAMPLE_COUNT
            or self.temperature != TEMPERATURE
            or self.top_p != TOP_P
            or self.top_k != TOP_K
            or self.max_new_tokens != MAX_NEW_TOKENS
            or self.batch_size != 8
        ):
            raise SelfConsistencyError("Self-Consistency config differs from freeze")

    @property
    def max_input_tokens(self) -> int:
        return generation.MODEL_CONTEXT_TOKENS - self.max_new_tokens

    def to_dict(self, sampling_seed: int) -> Mapping[str, Any]:
        _seed(sampling_seed)
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "dataset": self.dataset,
            "method_name": METHOD_NAME,
            "style": PromptStyle.COT.value,
            "model_id": generation.MODEL_ID,
            "model_revision": generation.MODEL_REVISION,
            "model_context_tokens": generation.MODEL_CONTEXT_TOKENS,
            "max_input_tokens": self.max_input_tokens,
            "max_new_tokens": self.max_new_tokens,
            "batch_size": self.batch_size,
            "sample_count": self.sample_count,
            "do_sample": True,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "sampling_seed": sampling_seed,
            "prompt_schema_version": generation.PROMPT_SCHEMA_VERSION,
            "parser_schema_version": generation.PARSER_SCHEMA_VERSION,
            "parse_error_sentinel": generation.PARSE_ERROR_SENTINEL,
            "parse_error_policy": "exclude-invalid-samples-all-invalid-sentinel-v1",
            "aggregation_version": AGGREGATION_VERSION,
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class SelfConsistencyResult:
    predictions: Mapping[str, list[str]]
    evidence: Mapping[str, GenerationEvidence]
    sample_parse_error_count: int
    all_invalid_record_count: int
    input_token_min: int
    input_token_max: int
    generated_token_total: int

    def __post_init__(self) -> None:
        if not isinstance(self.predictions, MappingABC) or not self.predictions:
            raise SelfConsistencyError("Self-Consistency predictions must be non-empty")
        if not isinstance(self.evidence, MappingABC) or set(self.evidence) != set(
            self.predictions
        ):
            raise SelfConsistencyError("Self-Consistency evidence keys differ")
        for value, name in (
            (self.sample_parse_error_count, "sample_parse_error_count"),
            (self.all_invalid_record_count, "all_invalid_record_count"),
            (self.input_token_min, "input_token_min"),
            (self.input_token_max, "input_token_max"),
            (self.generated_token_total, "generated_token_total"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SelfConsistencyError(f"{name} must be non-negative")
        if self.sample_parse_error_count > len(self.predictions) * SAMPLE_COUNT:
            raise SelfConsistencyError("sample parse errors exceed generated samples")
        if self.all_invalid_record_count > len(self.predictions):
            raise SelfConsistencyError("all-invalid count exceeds records")
        if self.input_token_min > self.input_token_max:
            raise SelfConsistencyError("input token range is reversed")


@dataclass(frozen=True)
class VerifiedSelfConsistency:
    artifact: VerifiedPredictionArtifact
    sample_parse_error_count: int
    all_invalid_record_count: int
    generated_token_total: int


def _seed(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 2_147_483_647
    ):
        raise SelfConsistencyError("sampling seed is invalid")
    return value


def _candidate(response: str) -> tuple[tuple[str, ...], list[str]]:
    parsed = parse_torque_response(response)
    normalized: set[str] = set()
    surfaces: list[str] = []
    for span in parsed:
        key = normalize_torque_span(span)
        if key not in normalized:
            normalized.add(key)
            surfaces.append(span)
    return tuple(sorted(normalized)), surfaces


def aggregate_responses(
    responses: Sequence[str],
) -> tuple[list[str], int, int]:
    """Return plurality prediction, parse-error count and valid count."""

    if isinstance(responses, (str, bytes, bytearray)) or not isinstance(
        responses, SequenceABC
    ) or len(responses) != SAMPLE_COUNT:
        raise SelfConsistencyError("responses must contain exactly eight strings")
    votes: Counter[tuple[str, ...]] = Counter()
    earliest: dict[tuple[str, ...], int] = {}
    surfaces: dict[tuple[str, ...], list[str]] = {}
    parse_errors = 0
    for index, response in enumerate(responses):
        if not isinstance(response, str):
            raise SelfConsistencyError("sample response must be a string")
        try:
            key, value = _candidate(response)
        except ValueError:
            parse_errors += 1
            continue
        votes[key] += 1
        if key not in earliest:
            earliest[key] = index
            surfaces[key] = value
    if not votes:
        return [generation.PARSE_ERROR_SENTINEL], parse_errors, 0
    winner = min(
        votes,
        key=lambda key: (-votes[key], earliest[key], canonical_json(list(key))),
    )
    return list(surfaces[winner]), parse_errors, sum(votes.values())


def _envelope(
    responses: Sequence[str], input_token_count: int, token_counts: Sequence[int]
) -> str:
    if len(responses) != SAMPLE_COUNT or len(token_counts) != SAMPLE_COUNT:
        raise SelfConsistencyError("evidence envelope sample count differs")
    samples = []
    for index, (response, generated_count) in enumerate(zip(responses, token_counts)):
        if (
            not isinstance(generated_count, int)
            or isinstance(generated_count, bool)
            or not 0 <= generated_count <= MAX_NEW_TOKENS
        ):
            raise SelfConsistencyError("sample generated-token count is invalid")
        samples.append(
            {
                "sample_index": index,
                "raw_response": response,
                "input_token_count": input_token_count,
                "generated_token_count": generated_count,
            }
        )
    return canonical_json(
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "sample_count": SAMPLE_COUNT,
            "samples": samples,
        }
    )


def _parse_envelope(value: str) -> tuple[tuple[str, ...], int, tuple[int, ...]]:
    if not isinstance(value, str):
        raise SelfConsistencyError("evidence envelope must be a string")
    try:
        envelope = _strict_json(value.encode("utf-8"), "Self-Consistency envelope")
    except (PredictionArtifactError, UnicodeEncodeError) as error:
        raise SelfConsistencyError("evidence envelope is not strict JSON") from error
    if not isinstance(envelope, MappingABC) or set(envelope) != {
        "schema_version", "sample_count", "samples"
    }:
        raise SelfConsistencyError("evidence envelope keys differ")
    if (
        envelope["schema_version"] != EVIDENCE_SCHEMA_VERSION
        or envelope["sample_count"] != SAMPLE_COUNT
        or canonical_json(envelope) != value
    ):
        raise SelfConsistencyError("evidence envelope fixed literals differ")
    samples = envelope["samples"]
    if isinstance(samples, (str, bytes, bytearray)) or not isinstance(
        samples, SequenceABC
    ) or len(samples) != SAMPLE_COUNT:
        raise SelfConsistencyError("evidence envelope samples differ")
    responses = []
    token_counts = []
    input_count: int | None = None
    for index, sample in enumerate(samples):
        if not isinstance(sample, MappingABC) or set(sample) != {
            "sample_index", "raw_response", "input_token_count",
            "generated_token_count",
        }:
            raise SelfConsistencyError("evidence sample keys differ")
        if sample["sample_index"] != index or not isinstance(
            sample["raw_response"], str
        ):
            raise SelfConsistencyError("evidence sample identity differs")
        current_input = sample["input_token_count"]
        generated_count = sample["generated_token_count"]
        if (
            isinstance(current_input, bool)
            or not isinstance(current_input, int)
            or not 1 <= current_input <= generation.MODEL_CONTEXT_TOKENS
            or isinstance(generated_count, bool)
            or not isinstance(generated_count, int)
            or not 0 <= generated_count <= MAX_NEW_TOKENS
        ):
            raise SelfConsistencyError("evidence sample token count is invalid")
        if input_count is None:
            input_count = current_input
        elif input_count != current_input:
            raise SelfConsistencyError("evidence samples use different prompts")
        responses.append(sample["raw_response"])
        token_counts.append(generated_count)
    if input_count is None:
        raise SelfConsistencyError("evidence envelope has no input count")
    return tuple(responses), input_count, tuple(token_counts)


def run_self_consistency(
    model: Any,
    tokenizer: Any,
    examples: Sequence[TorqueExample],
    config: SelfConsistencyConfig,
    device: str | torch.device,
    sampling_seed: int,
) -> SelfConsistencyResult:
    """Sample, aggregate and retain replayable raw evidence without writing."""

    if not isinstance(config, SelfConsistencyConfig):
        raise SelfConsistencyError("config must be SelfConsistencyConfig")
    seed = _seed(sampling_seed)
    validation_config = generation.GreedyGenerationConfig(
        dataset="torque-dev",
        style=PromptStyle.COT,
        max_new_tokens=config.max_new_tokens,
        batch_size=config.batch_size,
    )
    try:
        values = generation._examples(examples, validation_config)
    except generation.GenerationError as error:
        raise SelfConsistencyError("Self-Consistency examples failed validation") from error
    if not callable(getattr(model, "generate", None)) or not callable(tokenizer):
        raise SelfConsistencyError("model/tokenizer generation interface is invalid")
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(pad_token_id, bool) or not isinstance(pad_token_id, int):
        raise SelfConsistencyError("tokenizer pad token is invalid")
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
            raise SelfConsistencyError("tokenizer EOS sequence is invalid")
    else:
        raise SelfConsistencyError("tokenizer EOS token is invalid")
    if not eos_ids:
        raise SelfConsistencyError("tokenizer EOS set is empty")
    try:
        tokenizer.padding_side = "left"
    except Exception as error:
        raise SelfConsistencyError("cannot set tokenizer left padding") from error

    torch.manual_seed(seed)
    device_value = torch.device(device)
    if device_value.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    predictions: dict[str, list[str]] = {}
    evidence: dict[str, GenerationEvidence] = {}
    input_counts = []
    total_generated = 0
    total_parse_errors = 0
    all_invalid = 0
    for offset in range(0, len(values), config.batch_size):
        examples_batch = values[offset : offset + config.batch_size]
        prompts = [
            generation._prompt(example, validation_config)
            for example in examples_batch
        ]
        encoded = generation._token_batch(tokenizer, prompts)
        counts = encoded["attention_mask"].sum(dim=1)
        input_width = encoded["input_ids"].shape[1]
        if torch.any(counts <= 0) or torch.any(counts > config.max_input_tokens):
            raise SelfConsistencyError("prompt exceeds Self-Consistency context budget")
        if input_width + config.max_new_tokens > generation.MODEL_CONTEXT_TOKENS:
            raise SelfConsistencyError("padded prompt exceeds model context")
        try:
            device_inputs = {
                key: tensor.to(device=device_value, non_blocking=False)
                for key, tensor in encoded.items()
            }
            with torch.inference_mode():
                generated = model.generate(
                    **device_inputs,
                    max_new_tokens=config.max_new_tokens,
                    do_sample=True,
                    temperature=config.temperature,
                    top_p=config.top_p,
                    top_k=config.top_k,
                    num_return_sequences=config.sample_count,
                    use_cache=True,
                    pad_token_id=pad_token_id,
                    eos_token_id=sorted(eos_ids),
                )
        except Exception as error:
            raise SelfConsistencyError("Self-Consistency model generation failed") from error
        if (
            not isinstance(generated, Tensor)
            or generated.ndim != 2
            or generated.shape[0] != len(examples_batch) * SAMPLE_COUNT
            or generated.shape[1] < input_width
            or generated.shape[1] > input_width + config.max_new_tokens
        ):
            raise SelfConsistencyError("Self-Consistency generation shape differs")
        new_tokens = generated[:, input_width:].detach().cpu()
        for batch_index, example in enumerate(examples_batch):
            input_count = int(counts[batch_index].item())
            start = batch_index * SAMPLE_COUNT
            rows = new_tokens[start : start + SAMPLE_COUNT]
            responses = []
            token_counts = []
            for token_row in rows:
                try:
                    response = tokenizer.decode(
                        token_row,
                        skip_special_tokens=True,
                        clean_up_tokenization_spaces=False,
                    )
                except Exception as error:
                    raise SelfConsistencyError(
                        "Self-Consistency decode failed"
                    ) from error
                responses.append(response)
                count = generation._generated_token_count(
                    token_row, eos_ids, pad_token_id
                )
                token_counts.append(count)
            prediction, parse_errors, valid_count = aggregate_responses(responses)
            envelope = _envelope(responses, input_count, token_counts)
            parse_status = "PARSED" if valid_count else "PARSE_ERROR"
            predictions[example.record_id] = prediction
            evidence[example.record_id] = GenerationEvidence(
                raw_response=envelope,
                parse_status=parse_status,
                input_token_count=input_count,
                generated_token_count=sum(token_counts),
            )
            input_counts.append(input_count)
            total_generated += sum(token_counts)
            total_parse_errors += parse_errors
            all_invalid += int(valid_count == 0)
    return SelfConsistencyResult(
        predictions=predictions,
        evidence=evidence,
        sample_parse_error_count=total_parse_errors,
        all_invalid_record_count=all_invalid,
        input_token_min=min(input_counts),
        input_token_max=max(input_counts),
        generated_token_total=total_generated,
    )


def verify_self_consistency_predictions(run_id: str) -> VerifiedSelfConsistency:
    """Verify the prediction artifact and recompute every vote from raw samples."""

    try:
        artifact = verify_predictions(run_id)
    except PredictionArtifactError as error:
        raise SelfConsistencyError("prediction artifact verification failed") from error
    spec = artifact.spec
    expected_config = SelfConsistencyConfig().to_dict(spec.seed)
    if (
        spec.dataset != "torque-dev"
        or spec.method_name != METHOD_NAME
        or spec.model_id != generation.MODEL_ID
        or spec.model_revision != generation.MODEL_REVISION
        or spec.config != expected_config
    ):
        raise SelfConsistencyError("Self-Consistency run spec differs from freeze")
    if len(artifact.records) != len(artifact.evidence):
        raise SelfConsistencyError("Self-Consistency artifact evidence count differs")
    parse_errors = 0
    all_invalid = 0
    generated_total = 0
    for record, item in zip(artifact.records, artifact.evidence):
        responses, input_count, token_counts = _parse_envelope(item.raw_response)
        prediction, sample_errors, valid_count = aggregate_responses(responses)
        expected_status = "PARSED" if valid_count else "PARSE_ERROR"
        if (
            record.prediction != prediction
            or item.parse_status != expected_status
            or item.input_token_count != input_count
            or item.generated_token_count != sum(token_counts)
        ):
            raise SelfConsistencyError("Self-Consistency vote differs from evidence")
        parse_errors += sample_errors
        all_invalid += int(valid_count == 0)
        generated_total += sum(token_counts)
    return VerifiedSelfConsistency(
        artifact=artifact,
        sample_parse_error_count=parse_errors,
        all_invalid_record_count=all_invalid,
        generated_token_total=generated_total,
    )


__all__ = (
    "AGGREGATION_VERSION",
    "CONFIG_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "METHOD_NAME",
    "SAMPLE_COUNT",
    "SelfConsistencyConfig",
    "SelfConsistencyError",
    "SelfConsistencyResult",
    "VerifiedSelfConsistency",
    "aggregate_responses",
    "run_self_consistency",
    "verify_self_consistency_predictions",
)
