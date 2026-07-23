"""Frozen gold-free structured temporal graph baseline for TORQUE."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from . import generation
from .prediction_artifacts import (
    GenerationEvidence,
    PredictionArtifactError,
    VerifiedPredictionArtifact,
    verify_predictions,
)
from .prompting import parse_torque_response
from .transfer_eval import TorqueExample, load_torque_dev, normalize_torque_span


METHOD_NAME = "llm-graph"
MAX_NEW_TOKENS = 768
BATCH_SIZE = 8
PROMPT_SCHEMA_VERSION = "torque-llm-graph-prompt-v1"
PARSER_SCHEMA_VERSION = "torque-llm-graph-parser-v1"
CONFIG_SCHEMA_VERSION = "llm-graph-generation-config-v1"
GRAPH_SCHEMA_VERSION = "temporal-graph-json-v1"
GRAPH_PREFIX = "TEMPORAL_GRAPH: "
RELATIONS = ("precedes", "follows", "overlaps", "contains", "during")
_EVENT_ID = re.compile(r"E[1-9][0-9]{0,2}")
_EVENT_LIMIT = 64
_RELATION_LIMIT = 256
_SPAN_BYTE_LIMIT = 4096


class LlmGraphError(ValueError):
    """The frozen structured prompt, graph, generation, or replay failed."""


@dataclass(frozen=True)
class GraphEvent:
    event_id: str
    span: str


@dataclass(frozen=True)
class GraphRelation:
    source: str
    relation: str
    target: str


@dataclass(frozen=True)
class ParsedLlmGraph:
    events: tuple[GraphEvent, ...]
    relations: tuple[GraphRelation, ...]
    answer: tuple[str, ...]


@dataclass(frozen=True)
class LlmGraphConfig:
    dataset: str = "torque-dev"
    max_new_tokens: int = MAX_NEW_TOKENS
    batch_size: int = BATCH_SIZE

    def __post_init__(self) -> None:
        if (
            self.dataset != "torque-dev"
            or isinstance(self.max_new_tokens, bool)
            or not isinstance(self.max_new_tokens, int)
            or self.max_new_tokens != MAX_NEW_TOKENS
            or isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size != BATCH_SIZE
        ):
            raise LlmGraphError("LLM-Graph config differs from freeze")

    @property
    def max_input_tokens(self) -> int:
        return generation.MODEL_CONTEXT_TOKENS - self.max_new_tokens

    def to_dict(self, seed: int) -> Mapping[str, Any]:
        _seed(seed)
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "dataset": self.dataset,
            "method_name": METHOD_NAME,
            "model_id": generation.MODEL_ID,
            "model_revision": generation.MODEL_REVISION,
            "model_context_tokens": generation.MODEL_CONTEXT_TOKENS,
            "max_input_tokens": self.max_input_tokens,
            "max_new_tokens": self.max_new_tokens,
            "batch_size": self.batch_size,
            "do_sample": False,
            "seed": seed,
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "parser_schema_version": PARSER_SCHEMA_VERSION,
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "relation_order": list(RELATIONS),
            "answer_graph_binding": "normalized-answer-must-reference-event-v1",
            "parse_error_sentinel": generation.PARSE_ERROR_SENTINEL,
        }


@dataclass(frozen=True)
class VerifiedLlmGraph:
    artifact: VerifiedPredictionArtifact
    parse_error_count: int
    generated_token_total: int


def _seed(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 2_147_483_647
    ):
        raise LlmGraphError("seed is invalid")
    return value


def build_llm_graph_prompt(example: TorqueExample) -> str:
    """Build the fixed structured prompt without serializing gold or candidates."""

    if not isinstance(example, TorqueExample):
        raise LlmGraphError("LLM-Graph prompt requires a TorqueExample")
    return "\n".join(
        (
            "Task: structured temporal event reasoning.",
            "Read the passage and question without assuming facts outside the passage.",
            "First construct a directed temporal graph of relevant event mentions.",
            "Each event span must be copied exactly from the passage and assigned E1, E2, ... .",
            "Allowed relation labels are: precedes, follows, overlaps, contains, during.",
            "Each relation source and target must name an event in the graph.",
            "Then answer with every matching event span in passage order; [] is allowed.",
            "Every non-empty final answer span must reference an event span in the graph.",
            "You may reason concisely before the required output.",
            "The last two non-empty lines must have exactly these prefixes and JSON shapes:",
            'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"<first exact passage span>"},{"id":"E2","span":"<second exact passage span>"}],"relations":[{"source":"E1","relation":"precedes","target":"E2"}]}',
            'FINAL_ANSWER: ["<exact passage span>"]',
            "",
            "<PASSAGE>",
            example.passage,
            "</PASSAGE>",
            "<QUESTION>",
            example.question,
            "</QUESTION>",
        )
    )


def _strict_json(payload: str) -> Any:
    duplicates: list[str] = []

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                duplicates.append(key)
            value[key] = item
        return value

    def reject_constant(unused: str) -> Any:
        raise LlmGraphError("temporal graph contains a non-finite number")

    try:
        value = json.loads(
            payload,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise LlmGraphError("temporal graph is not strict JSON") from error
    if duplicates:
        raise LlmGraphError("temporal graph contains duplicate keys")
    return value


def _mapping(value: Any, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC) or set(value) != keys:
        raise LlmGraphError(f"{name} keys differ")
    if any(not isinstance(key, str) for key in value):
        raise LlmGraphError(f"{name} keys must be strings")
    return value


def _sequence(value: Any, name: str, limit: int) -> Sequence[Any]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, SequenceABC)
        or len(value) > limit
    ):
        raise LlmGraphError(f"{name} is not a bounded sequence")
    return value


def parse_llm_graph_response(response: str, passage: str) -> ParsedLlmGraph:
    """Parse the strict graph and final span set, binding answers to graph events."""

    if not isinstance(response, str) or not isinstance(passage, str):
        raise LlmGraphError("response and passage must be strings")
    try:
        answer = parse_torque_response(response)
    except ValueError as error:
        raise LlmGraphError("LLM-Graph final answer is invalid") from error
    nonempty = [line for line in response.splitlines() if line.strip()]
    graph_lines = [line for line in nonempty if line.startswith(GRAPH_PREFIX)]
    if len(nonempty) < 2 or len(graph_lines) != 1 or graph_lines[0] != nonempty[-2]:
        raise LlmGraphError("temporal graph must be the penultimate non-empty line")
    payload = graph_lines[0][len(GRAPH_PREFIX) :]
    if not payload:
        raise LlmGraphError("temporal graph payload is empty")
    graph = _mapping(_strict_json(payload), {"events", "relations"}, "graph")

    events: list[GraphEvent] = []
    event_ids: set[str] = set()
    event_spans: set[str] = set()
    for raw_event in _sequence(graph["events"], "events", _EVENT_LIMIT):
        item = _mapping(raw_event, {"id", "span"}, "event")
        event_id = item["id"]
        span = item["span"]
        if (
            not isinstance(event_id, str)
            or _EVENT_ID.fullmatch(event_id) is None
            or event_id in event_ids
        ):
            raise LlmGraphError("event ID is invalid or duplicated")
        if not isinstance(span, str) or not span.strip() or span not in passage:
            raise LlmGraphError("event span is not an exact passage substring")
        try:
            span_size = len(span.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as error:
            raise LlmGraphError("event span is not valid Unicode") from error
        if span_size > _SPAN_BYTE_LIMIT:
            raise LlmGraphError("event span exceeds its byte limit")
        event_ids.add(event_id)
        event_spans.add(normalize_torque_span(span))
        events.append(GraphEvent(event_id, span))

    relations: list[GraphRelation] = []
    relation_keys: set[tuple[str, str, str]] = set()
    for raw_relation in _sequence(
        graph["relations"], "relations", _RELATION_LIMIT
    ):
        item = _mapping(
            raw_relation, {"source", "relation", "target"}, "relation"
        )
        source = item["source"]
        relation = item["relation"]
        target = item["target"]
        key = (source, relation, target)
        if (
            not isinstance(source, str)
            or not isinstance(relation, str)
            or not isinstance(target, str)
            or source not in event_ids
            or target not in event_ids
            or source == target
            or relation not in RELATIONS
            or key in relation_keys
        ):
            raise LlmGraphError("relation is invalid, duplicated, or unbound")
        relation_keys.add(key)
        relations.append(GraphRelation(source, relation, target))

    if any(normalize_torque_span(span) not in event_spans for span in answer):
        raise LlmGraphError("final answer does not reference a graph event")
    return ParsedLlmGraph(tuple(events), tuple(relations), tuple(answer))


def _tokenizer_ids(tokenizer: Any) -> tuple[int, set[int]]:
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(pad_token_id, bool) or not isinstance(pad_token_id, int):
        raise LlmGraphError("tokenizer pad token is invalid")
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
            raise LlmGraphError("tokenizer EOS sequence is invalid")
    else:
        raise LlmGraphError("tokenizer EOS token is invalid")
    if not eos_ids:
        raise LlmGraphError("tokenizer EOS set is empty")
    return pad_token_id, eos_ids


def run_llm_graph(
    model: Any,
    tokenizer: Any,
    examples: Sequence[TorqueExample],
    config: LlmGraphConfig,
    device: str | torch.device,
    seed: int,
) -> generation.GenerationResult:
    """Run fixed greedy structured generation without writing an artifact."""

    if not isinstance(config, LlmGraphConfig):
        raise LlmGraphError("config must be LlmGraphConfig")
    _seed(seed)
    validation_config = generation.GreedyGenerationConfig(
        dataset="torque-dev",
        style=generation.PromptStyle.COT,
        max_new_tokens=config.max_new_tokens,
        batch_size=config.batch_size,
    )
    try:
        values = generation._examples(examples, validation_config)
    except generation.GenerationError as error:
        raise LlmGraphError("LLM-Graph examples failed validation") from error
    if not callable(getattr(model, "generate", None)) or not callable(tokenizer):
        raise LlmGraphError("model/tokenizer generation interface is invalid")
    pad_token_id, eos_ids = _tokenizer_ids(tokenizer)
    try:
        tokenizer.padding_side = "left"
    except Exception as error:
        raise LlmGraphError("cannot set tokenizer left padding") from error

    predictions: dict[str, list[str]] = {}
    evidence: dict[str, GenerationEvidence] = {}
    input_counts: list[int] = []
    generated_total = 0
    parse_errors = 0
    for offset in range(0, len(values), config.batch_size):
        examples_batch = values[offset : offset + config.batch_size]
        prompts = [build_llm_graph_prompt(example) for example in examples_batch]
        try:
            encoded = generation._token_batch(tokenizer, prompts)
        except generation.GenerationError as error:
            raise LlmGraphError("LLM-Graph tokenization failed") from error
        counts = encoded["attention_mask"].sum(dim=1)
        input_width = encoded["input_ids"].shape[1]
        if torch.any(counts <= 0) or torch.any(counts > config.max_input_tokens):
            raise LlmGraphError("prompt exceeds LLM-Graph context budget")
        if input_width + config.max_new_tokens > generation.MODEL_CONTEXT_TOKENS:
            raise LlmGraphError("padded prompt exceeds model context")
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
            raise LlmGraphError("LLM-Graph model generation failed") from error
        if (
            not isinstance(generated, Tensor)
            or generated.ndim != 2
            or generated.shape[0] != len(examples_batch)
            or generated.shape[1] < input_width
            or generated.shape[1] > input_width + config.max_new_tokens
        ):
            raise LlmGraphError("LLM-Graph generation shape differs")
        new_tokens = generated[:, input_width:].detach().cpu()
        for example, token_row, input_count in zip(
            examples_batch, new_tokens, counts.tolist()
        ):
            try:
                response = tokenizer.decode(
                    token_row,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
            except Exception as error:
                raise LlmGraphError("LLM-Graph decode failed") from error
            generated_count = generation._generated_token_count(
                token_row, eos_ids, pad_token_id
            )
            try:
                prediction = list(
                    parse_llm_graph_response(response, example.passage).answer
                )
                parse_status = "PARSED"
            except ValueError:
                prediction = [generation.PARSE_ERROR_SENTINEL]
                parse_status = "PARSE_ERROR"
                parse_errors += 1
            predictions[example.record_id] = prediction
            evidence[example.record_id] = GenerationEvidence(
                raw_response=response,
                parse_status=parse_status,
                input_token_count=int(input_count),
                generated_token_count=generated_count,
            )
            input_counts.append(int(input_count))
            generated_total += generated_count
    return generation.GenerationResult(
        predictions=predictions,
        evidence=evidence,
        parse_error_count=parse_errors,
        input_token_min=min(input_counts),
        input_token_max=max(input_counts),
        generated_token_total=generated_total,
    )


def verify_llm_graph_predictions(run_id: str) -> VerifiedLlmGraph:
    """Replay source-bound graph parsing and prediction selection offline."""

    try:
        artifact = verify_predictions(run_id)
    except PredictionArtifactError as error:
        raise LlmGraphError("prediction artifact verification failed") from error
    spec = artifact.spec
    expected_config = LlmGraphConfig().to_dict(spec.seed)
    if (
        spec.dataset != "torque-dev"
        or spec.method_name != METHOD_NAME
        or spec.model_id != generation.MODEL_ID
        or spec.model_revision != generation.MODEL_REVISION
        or spec.config != expected_config
    ):
        raise LlmGraphError("LLM-Graph run spec differs from freeze")
    examples = load_torque_dev()
    if not (
        len(artifact.records) == len(artifact.evidence) == len(examples)
    ):
        raise LlmGraphError("LLM-Graph artifact coverage differs")
    parse_errors = 0
    generated_total = 0
    for record, evidence, example in zip(
        artifact.records, artifact.evidence, examples
    ):
        if record.record_id != example.record_id:
            raise LlmGraphError("LLM-Graph source order differs")
        try:
            prediction = list(
                parse_llm_graph_response(evidence.raw_response, example.passage).answer
            )
            status = "PARSED"
        except ValueError:
            prediction = [generation.PARSE_ERROR_SENTINEL]
            status = "PARSE_ERROR"
            parse_errors += 1
        if record.prediction != prediction or evidence.parse_status != status:
            raise LlmGraphError("LLM-Graph prediction differs from evidence")
        generated_total += evidence.generated_token_count
    return VerifiedLlmGraph(artifact, parse_errors, generated_total)


__all__ = (
    "BATCH_SIZE",
    "CONFIG_SCHEMA_VERSION",
    "GRAPH_SCHEMA_VERSION",
    "LlmGraphConfig",
    "LlmGraphError",
    "MAX_NEW_TOKENS",
    "METHOD_NAME",
    "PROMPT_SCHEMA_VERSION",
    "PARSER_SCHEMA_VERSION",
    "ParsedLlmGraph",
    "RELATIONS",
    "VerifiedLlmGraph",
    "build_llm_graph_prompt",
    "parse_llm_graph_response",
    "run_llm_graph",
    "verify_llm_graph_predictions",
)
