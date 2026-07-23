"""Resource-bounded local greedy generation for Direct and CoT baselines."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from .backbone import format_chat_prompt
from .prediction_artifacts import GenerationEvidence
from .prompting import (
    PromptStyle,
    build_timeqa_prompt,
    build_torque_prompt,
    parse_timeqa_response,
    parse_torque_response,
)
from .transfer_eval import (
    TimeQaExample,
    TorqueExample,
    normalize_timeqa_answer,
    normalize_torque_span,
)


MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
MODEL_PATH = (
    "/data0/hk_data/kairos-zx/models/Qwen2.5-7B-Instruct/"
    "a09a35458c702b33eeacc393d103063234e8bc28"
)
MODEL_CONTEXT_TOKENS = 32_768
PARSE_ERROR_SENTINEL = "KAIROS_PARSE_ERROR_V1_8F3C2A"
PROMPT_SCHEMA_VERSION = "transfer-prompt-v1"
PARSER_SCHEMA_VERSION = "terminal-json-parser-v1"


class GenerationError(ValueError):
    """A generation configuration or runtime invariant failed."""


@dataclass(frozen=True)
class GreedyGenerationConfig:
    dataset: str
    style: PromptStyle
    max_new_tokens: int
    batch_size: int = 1

    def __post_init__(self) -> None:
        if self.dataset not in {"torque-dev", "timeqa-hard"}:
            raise GenerationError("dataset is not a frozen transfer binding")
        if not isinstance(self.style, PromptStyle):
            raise GenerationError("style must be a PromptStyle")
        if (
            isinstance(self.max_new_tokens, bool)
            or not isinstance(self.max_new_tokens, int)
            or not 1 <= self.max_new_tokens <= 4096
        ):
            raise GenerationError("max_new_tokens is outside its limit")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or not 1 <= self.batch_size <= 8
        ):
            raise GenerationError("batch_size is outside its limit")
        if self.max_new_tokens >= MODEL_CONTEXT_TOKENS:
            raise GenerationError("max_new_tokens leaves no input context")

    @property
    def method_name(self) -> str:
        return self.style.value

    @property
    def max_input_tokens(self) -> int:
        return MODEL_CONTEXT_TOKENS - self.max_new_tokens

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": "greedy-generation-config-v1",
            "dataset": self.dataset,
            "style": self.style.value,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "model_context_tokens": MODEL_CONTEXT_TOKENS,
            "max_input_tokens": self.max_input_tokens,
            "max_new_tokens": self.max_new_tokens,
            "batch_size": self.batch_size,
            "do_sample": False,
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "parser_schema_version": PARSER_SCHEMA_VERSION,
            "parse_error_sentinel": PARSE_ERROR_SENTINEL,
        }


@dataclass(frozen=True)
class GenerationResult:
    predictions: Mapping[str, Any]
    evidence: Mapping[str, GenerationEvidence]
    parse_error_count: int
    input_token_min: int
    input_token_max: int
    generated_token_total: int

    def __post_init__(self) -> None:
        if not isinstance(self.predictions, MappingABC) or not self.predictions:
            raise GenerationError("generation predictions must be a non-empty mapping")
        if not isinstance(self.evidence, MappingABC):
            raise GenerationError("generation evidence must be a mapping")
        if set(self.predictions) != set(self.evidence):
            raise GenerationError("generation prediction/evidence keys differ")
        for value, name in (
            (self.parse_error_count, "parse_error_count"),
            (self.input_token_min, "input_token_min"),
            (self.input_token_max, "input_token_max"),
            (self.generated_token_total, "generated_token_total"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise GenerationError(f"{name} must be a non-negative integer")
        if self.parse_error_count > len(self.predictions):
            raise GenerationError("parse_error_count exceeds prediction count")
        if self.input_token_min > self.input_token_max:
            raise GenerationError("input token range is reversed")


def default_generation_config(
    dataset: str, style: PromptStyle | str, batch_size: int = 1
) -> GreedyGenerationConfig:
    try:
        normalized_style = PromptStyle(style)
    except (TypeError, ValueError) as error:
        raise GenerationError("style must be direct or cot") from error
    max_new_tokens = 128 if normalized_style is PromptStyle.DIRECT else 512
    return GreedyGenerationConfig(
        dataset=dataset,
        style=normalized_style,
        max_new_tokens=max_new_tokens,
        batch_size=batch_size,
    )


def _examples(examples: Sequence[Any], config: GreedyGenerationConfig) -> tuple[Any, ...]:
    if isinstance(examples, (str, bytes, bytearray)) or not isinstance(
        examples, SequenceABC
    ):
        raise GenerationError("examples must be a non-string sequence")
    values = tuple(examples)
    if not values:
        raise GenerationError("examples must be non-empty")
    expected_type = TorqueExample if config.dataset == "torque-dev" else TimeQaExample
    if any(not isinstance(example, expected_type) for example in values):
        raise GenerationError("example type differs from generation dataset")
    record_ids = tuple(example.record_id for example in values)
    if len(set(record_ids)) != len(record_ids):
        raise GenerationError("example record IDs are duplicated")
    sentinel = (
        normalize_torque_span(PARSE_ERROR_SENTINEL)
        if config.dataset == "torque-dev"
        else normalize_timeqa_answer(PARSE_ERROR_SENTINEL)
    )
    for example in values:
        gold = example.gold_spans if config.dataset == "torque-dev" else example.targets
        normalizer = (
            normalize_torque_span
            if config.dataset == "torque-dev"
            else normalize_timeqa_answer
        )
        if any(normalizer(value) == sentinel for value in gold):
            raise GenerationError("parse-error sentinel collides with a gold answer")
    return values


def _prompt(example: Any, config: GreedyGenerationConfig) -> str:
    bundle = (
        build_torque_prompt(example, config.style)
        if config.dataset == "torque-dev"
        else build_timeqa_prompt(example, config.style)
    )
    return bundle.text


def _token_batch(tokenizer: Any, prompts: Sequence[str]) -> Mapping[str, Tensor]:
    formatted = [format_chat_prompt(tokenizer, prompt).text for prompt in prompts]
    try:
        values = tokenizer(
            formatted,
            return_tensors="pt",
            padding=True,
            truncation=False,
            add_special_tokens=False,
        )
    except Exception as error:
        raise GenerationError("tokenizer batch encoding failed") from error
    if not isinstance(values, MappingABC):
        raise GenerationError("tokenizer output must be a mapping")
    input_ids = values.get("input_ids")
    attention_mask = values.get("attention_mask")
    if (
        not isinstance(input_ids, Tensor)
        or input_ids.ndim != 2
        or input_ids.dtype not in {torch.int32, torch.int64}
    ):
        raise GenerationError("tokenizer input_ids tensor is invalid")
    if (
        not isinstance(attention_mask, Tensor)
        or attention_mask.shape != input_ids.shape
        or attention_mask.dtype not in {torch.bool, torch.int32, torch.int64}
    ):
        raise GenerationError("tokenizer attention_mask tensor is invalid")
    if torch.any((attention_mask != 0) & (attention_mask != 1)):
        raise GenerationError("tokenizer attention_mask must contain only 0/1")
    return {"input_ids": input_ids.long(), "attention_mask": attention_mask.long()}


def _generated_token_count(
    generated: Tensor, eos_token_ids: set[int], pad_token_id: int
) -> int:
    count = 0
    for value in generated.tolist():
        token = int(value)
        count += 1
        if token in eos_token_ids or token == pad_token_id:
            break
    return count


def run_greedy_generation(
    model: Any,
    tokenizer: Any,
    examples: Sequence[Any],
    config: GreedyGenerationConfig,
    device: str | torch.device,
) -> GenerationResult:
    """Generate and parse a fixed example sequence without writing artifacts."""

    if not isinstance(config, GreedyGenerationConfig):
        raise GenerationError("config must be a GreedyGenerationConfig")
    values = _examples(examples, config)
    if not callable(getattr(model, "generate", None)):
        raise GenerationError("model has no callable generate method")
    if not callable(tokenizer):
        raise GenerationError("tokenizer is not callable")
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(pad_token_id, bool) or not isinstance(pad_token_id, int):
        raise GenerationError("tokenizer pad_token_id is invalid")
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
            raise GenerationError("tokenizer eos_token_id sequence is invalid")
    else:
        raise GenerationError("tokenizer eos_token_id is invalid")
    if not eos_ids:
        raise GenerationError("tokenizer eos_token_id must be non-empty")
    try:
        tokenizer.padding_side = "left"
    except Exception as error:
        raise GenerationError("cannot set tokenizer left padding") from error

    predictions: dict[str, Any] = {}
    evidence: dict[str, GenerationEvidence] = {}
    input_counts: list[int] = []
    generated_total = 0
    parse_errors = 0
    for offset in range(0, len(values), config.batch_size):
        examples_batch = values[offset : offset + config.batch_size]
        prompts = [_prompt(example, config) for example in examples_batch]
        encoded = _token_batch(tokenizer, prompts)
        counts = encoded["attention_mask"].sum(dim=1)
        if torch.any(counts <= 0):
            raise GenerationError("a tokenized prompt is empty")
        if torch.any(counts > config.max_input_tokens):
            raise GenerationError("a prompt exceeds the frozen context budget")
        input_width = encoded["input_ids"].shape[1]
        if input_width + config.max_new_tokens > MODEL_CONTEXT_TOKENS:
            raise GenerationError("padded batch exceeds the frozen context budget")
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
            raise GenerationError("model generation failed") from error
        if (
            not isinstance(generated, Tensor)
            or generated.ndim != 2
            or generated.shape[0] != len(examples_batch)
            or generated.shape[1] < input_width
            or generated.shape[1] > input_width + config.max_new_tokens
        ):
            raise GenerationError("model generation tensor shape is invalid")
        new_tokens = generated[:, input_width:].detach().cpu()
        for example, token_row, input_count in zip(
            examples_batch, new_tokens, counts.tolist()
        ):
            try:
                raw_response = tokenizer.decode(
                    token_row,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
            except Exception as error:
                raise GenerationError("tokenizer decode failed") from error
            token_count = _generated_token_count(token_row, eos_ids, pad_token_id)
            generated_total += token_count
            try:
                prediction = (
                    list(parse_torque_response(raw_response))
                    if config.dataset == "torque-dev"
                    else parse_timeqa_response(raw_response)
                )
                parse_status = "PARSED"
            except ValueError:
                parse_errors += 1
                parse_status = "PARSE_ERROR"
                prediction = (
                    [PARSE_ERROR_SENTINEL]
                    if config.dataset == "torque-dev"
                    else PARSE_ERROR_SENTINEL
                )
            predictions[example.record_id] = prediction
            evidence[example.record_id] = GenerationEvidence(
                raw_response=raw_response,
                parse_status=parse_status,
                input_token_count=int(input_count),
                generated_token_count=token_count,
            )
    return GenerationResult(
        predictions=predictions,
        evidence=evidence,
        parse_error_count=parse_errors,
        input_token_min=min(input_counts),
        input_token_max=max(input_counts),
        generated_token_total=generated_total,
    )


def load_local_backbone(device: str | torch.device) -> tuple[Any, Any]:
    """Load the fixed local Qwen snapshot; callers must run resource gates first."""

    try:
        from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        raise GenerationError("Transformers is unavailable") from error
    try:
        source_config = AutoConfig.from_pretrained(
            MODEL_PATH, local_files_only=True, trust_remote_code=False
        )
        if (
            source_config.model_type != "qwen2"
            or source_config.hidden_size != 3584
            or source_config.num_hidden_layers != 28
            or source_config.max_position_embeddings != MODEL_CONTEXT_TOKENS
        ):
            raise GenerationError("local model configuration differs from its binding")
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_PATH,
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
        if not getattr(tokenizer, "is_fast", False):
            raise GenerationError("fixed tokenizer must be fast")
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "left"
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map={"": str(device)},
            attn_implementation="sdpa",
        )
        model.eval()
    except GenerationError:
        raise
    except Exception as error:
        raise GenerationError("fixed local backbone load failed") from error
    return model, tokenizer
