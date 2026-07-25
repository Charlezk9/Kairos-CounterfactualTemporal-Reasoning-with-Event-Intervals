"""In-memory relation-only candidate and token materialization."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from .backbone import (
    AlignedEventBatch,
    BackboneContractError,
    align_char_spans,
    build_candidate_encoding_text,
    format_chat_prompt,
    shift_user_spans,
)
from .ids import canonical_json, sha256_canonical
from .modeling import IGNORE_RELATION_INDEX, RELATION_TO_INDEX
from .relation_supervision import RelationOnlyPair
from .training_adapter import TrainingBatch
from .training_plan import (
    CandidateBinding,
    MaterializedTrainingBatch,
    TrainingCorpusBinding,
    TrainingExampleBinding,
    TrainingPlan,
)


SCHEMA_VERSION = "relation-training-materialization-v1"
DATASET_ID = "gsm8k-relation-only-v1"
MAX_TOKENS = 32_768
EMPTY_POOL_POLICY = "train-empty-generated-pool-gold-only-injection-v1"
_GENERATED_ORIGINS = frozenset({"direct", "cot", "self-consistency"})
_ORIGIN_ORDER = {value: index for index, value in enumerate(
    ("direct", "cot", "self-consistency", "gold")
)}


class TrainingMaterializationError(ValueError):
    """A candidate, source, tokenizer, alignment, or target invariant failed."""


def _fail(message: str) -> None:
    raise TrainingMaterializationError(message) from None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{name} must be a non-empty string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(f"{name} is not valid Unicode")
    if len(encoded) > 1_048_576:
        _fail(f"{name} exceeds its byte limit")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        _fail(f"{name} must be a non-string sequence")
    return value


def _content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


@dataclass(frozen=True)
class CandidateProposal:
    text: str
    origin: str

    def __post_init__(self) -> None:
        _text(self.text, "candidate proposal text")
        if self.origin not in _GENERATED_ORIGINS:
            _fail("candidate proposal origin is unsupported")


@dataclass(frozen=True)
class BoundTrainingRecord:
    pair: RelationOnlyPair
    binding: TrainingExampleBinding
    candidate_texts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pair, RelationOnlyPair):
            _fail("materialization pair is invalid")
        if not isinstance(self.binding, TrainingExampleBinding):
            _fail("materialization binding is invalid")
        if (
            not isinstance(self.candidate_texts, tuple)
            or len(self.candidate_texts) != len(self.binding.candidates)
        ):
            _fail("candidate text count differs from its binding")
        if any(not isinstance(value, str) for value in self.candidate_texts):
            _fail("candidate texts are invalid")
        pair = self.pair
        binding = self.binding
        expected = (
            binding.example_id == pair.pair_id
            and binding.source_id == pair.source_id
            and binding.original_record_id == pair.original_record_id
            and binding.counterfactual_record_id == pair.counterfactual_record_id
            and binding.record_sha256 == sha256_canonical(pair.to_dict())
            and binding.gold_answer_sha256 == _content_sha256(pair.original_answer)
        )
        if not expected:
            _fail("materialization record differs from its relation pair")
        for text, candidate in zip(self.candidate_texts, binding.candidates):
            _text(text, "candidate text")
            if _content_sha256(text) != candidate.content_sha256:
                _fail("candidate text differs from its content binding")


def bind_relation_pair(
    pair: RelationOnlyPair,
    proposals: Sequence[CandidateProposal],
    source_order_index: int,
) -> BoundTrainingRecord:
    """Deduplicate generated proposals and bind or append the original gold."""

    if not isinstance(pair, RelationOnlyPair):
        _fail("relation-only pair is invalid")
    if (
        isinstance(source_order_index, bool)
        or not isinstance(source_order_index, int)
        or not 0 <= source_order_index <= 10_000_000
    ):
        _fail("source order index is invalid")
    values = tuple(_sequence(proposals, "candidate proposals"))
    if not values:
        _fail("candidate proposals must be non-empty")
    by_hash: OrderedDict[str, tuple[str, list[str]]] = OrderedDict()
    for proposal in values:
        if not isinstance(proposal, CandidateProposal):
            _fail("candidate proposal is invalid")
        digest = _content_sha256(proposal.text)
        existing = by_hash.get(digest)
        if existing is None:
            by_hash[digest] = (proposal.text, [proposal.origin])
        else:
            text, origins = existing
            if text != proposal.text:
                _fail("candidate content SHA256 collision detected")
            if proposal.origin not in origins:
                origins.append(proposal.origin)
    gold_hash = _content_sha256(pair.original_answer)
    gold_injected = gold_hash not in by_hash
    if gold_injected:
        by_hash[gold_hash] = (pair.original_answer, ["gold"])
    if len(by_hash) > 64:
        _fail("deduplicated candidate count exceeds 64")
    texts = tuple(value[0] for value in by_hash.values())
    try:
        candidates = tuple(
            CandidateBinding.from_text(
                pair.pair_id,
                text,
                tuple(sorted(origins, key=_ORIGIN_ORDER.__getitem__)),
            )
            for text, origins in by_hash.values()
        )
    except ValueError as error:
        raise TrainingMaterializationError(
            "candidate binding rejected materialized proposals"
        ) from error
    target = tuple(by_hash).index(gold_hash)
    try:
        binding = TrainingExampleBinding(
            source_order_index=source_order_index,
            example_id=pair.pair_id,
            source_id=pair.source_id,
            original_record_id=pair.original_record_id,
            counterfactual_record_id=pair.counterfactual_record_id,
            record_sha256=sha256_canonical(pair.to_dict()),
            gold_answer_sha256=gold_hash,
            candidates=candidates,
            answer_target_index=target,
            gold_injected=gold_injected,
        )
    except ValueError as error:
        raise TrainingMaterializationError(
            "training example binding rejected materialized proposals"
        ) from error
    return BoundTrainingRecord(pair, binding, texts)


def _bind_authorized_empty_train_pair(
    pair: RelationOnlyPair,
    proposals: Sequence[CandidateProposal],
    source_order_index: int,
    *,
    partition: str,
    policy: str,
    authorized_pair_ids: frozenset[str],
) -> BoundTrainingRecord:
    """Apply the private D-043 capability without weakening D-034."""

    values = tuple(_sequence(proposals, "candidate proposals"))
    if partition != "train" or policy != EMPTY_POOL_POLICY:
        _fail("empty generated pool is not authorized for this materialization")
    if values:
        _fail("D-043 capability accepts only an empty generated train pool")
    if not isinstance(pair, RelationOnlyPair):
        _fail("relation-only pair is invalid")
    if (
        not isinstance(authorized_pair_ids, frozenset)
        or not authorized_pair_ids
        or any(not isinstance(value, str) for value in authorized_pair_ids)
        or pair.pair_id not in authorized_pair_ids
    ):
        _fail("empty train pair is outside the verified D-043 capability")
    if (
        isinstance(source_order_index, bool)
        or not isinstance(source_order_index, int)
        or not 0 <= source_order_index <= 10_000_000
    ):
        _fail("source order index is invalid")
    gold = _text(pair.original_answer, "gold answer")
    gold_hash = _content_sha256(gold)
    try:
        candidate = CandidateBinding.from_text(pair.pair_id, gold, ("gold",))
        binding = TrainingExampleBinding(
            source_order_index=source_order_index,
            example_id=pair.pair_id,
            source_id=pair.source_id,
            original_record_id=pair.original_record_id,
            counterfactual_record_id=pair.counterfactual_record_id,
            record_sha256=sha256_canonical(pair.to_dict()),
            gold_answer_sha256=gold_hash,
            candidates=(candidate,),
            answer_target_index=0,
            gold_injected=True,
        )
    except ValueError as error:
        raise TrainingMaterializationError(
            "D-043 singleton binding rejected materialized gold"
        ) from error
    return BoundTrainingRecord(pair, binding, (gold,))


def build_relation_training_corpus(
    records: Sequence[BoundTrainingRecord],
    execution_commit: str,
    source_artifact_id: str,
    source_manifest_sha256: str,
) -> TrainingCorpusBinding:
    """Build a D-031 corpus from an already verified source-order record stream."""

    values = tuple(_sequence(records, "bound training records"))
    if not values or any(not isinstance(item, BoundTrainingRecord) for item in values):
        _fail("bound training records are invalid")
    revisions = {item.pair.revision for item in values}
    if len(revisions) != 1:
        _fail("relation pairs use different source revisions")
    for index, item in enumerate(values):
        if item.binding.source_order_index != index:
            _fail("bound records are not in consecutive source order")
        if item.pair.split.official != "train":
            _fail("relation training materialization requires official train")
    try:
        return TrainingCorpusBinding(
            execution_commit=execution_commit,
            dataset_id=DATASET_ID,
            dataset_revision=next(iter(revisions)),
            official_split="train",
            source_artifact_id=source_artifact_id,
            source_manifest_sha256=source_manifest_sha256,
            examples=tuple(item.binding for item in values),
        )
    except ValueError as error:
        raise TrainingMaterializationError(
            "training corpus binding rejected materialized records"
        ) from error


def _tokenize(tokenizer: Any, texts: Sequence[str], name: str) -> tuple[Tensor, Tensor, Tensor]:
    if not callable(tokenizer) or getattr(tokenizer, "is_fast", None) is not True:
        _fail("materialization requires a callable fast tokenizer")
    if getattr(tokenizer, "padding_side", None) != "right":
        _fail("materialization tokenizer must use right padding")
    try:
        value = tokenizer(
            list(texts),
            padding=True,
            truncation=False,
            add_special_tokens=False,
            return_offsets_mapping=True,
            return_tensors="pt",
        )
    except Exception as error:
        raise TrainingMaterializationError(f"{name} tokenization failed") from error
    if not isinstance(value, MappingABC):
        _fail(f"{name} tokenizer output must be a mapping")
    required = {"input_ids", "attention_mask", "offset_mapping"}
    if not required.issubset(value):
        _fail(f"{name} tokenizer output is incomplete")
    input_ids = value["input_ids"]
    attention = value["attention_mask"]
    offsets = value["offset_mapping"]
    if (
        not isinstance(input_ids, Tensor)
        or input_ids.dtype != torch.long
        or input_ids.ndim != 2
        or not isinstance(attention, Tensor)
        or attention.dtype not in {torch.bool, torch.int32, torch.int64}
        or attention.shape != input_ids.shape
        or not isinstance(offsets, Tensor)
        or offsets.dtype not in {torch.int32, torch.int64}
        or offsets.shape != (*input_ids.shape, 2)
        or input_ids.device.type != "cpu"
        or attention.device.type != "cpu"
        or offsets.device.type != "cpu"
    ):
        _fail(f"{name} tokenizer tensors are invalid")
    if torch.any(input_ids < 0):
        _fail(f"{name} tokenizer IDs are negative")
    if input_ids.shape[0] != len(texts) or not 1 <= input_ids.shape[1] <= MAX_TOKENS:
        _fail(f"{name} tokenized shape is outside its limit")
    normalized_attention = attention.bool()
    if torch.any((attention != 0) & (attention != 1)):
        _fail(f"{name} attention mask is not binary")
    if torch.any(normalized_attention.sum(dim=1) == 0):
        _fail(f"{name} contains an empty token sequence")
    for index, text in enumerate(texts):
        real_offsets = offsets[index][normalized_attention[index]]
        if (
            torch.any(real_offsets < 0)
            or torch.any(real_offsets[:, 1] < real_offsets[:, 0])
            or torch.any(real_offsets > len(text))
            or int(real_offsets[:, 1].max()) != len(text)
        ):
            _fail(f"{name} offsets indicate truncation or invalid coverage")
    return input_ids, attention.long(), offsets.long()


def _source_tensors(
    tokenizer: Any,
    records: Sequence[BoundTrainingRecord],
    counterfactual: bool,
) -> tuple[Tensor, Tensor, AlignedEventBatch]:
    formatted_texts: list[str] = []
    shifted_spans = []
    for record in records:
        pair = record.pair
        query = pair.counterfactual_query if counterfactual else pair.original_query
        events = pair.counterfactual_events if counterfactual else pair.original_events
        try:
            formatted = format_chat_prompt(tokenizer, query)
            spans = shift_user_spans(
                formatted, query, tuple(event.char_span for event in events)
            )
        except BackboneContractError as error:
            raise TrainingMaterializationError(
                "source chat formatting or span shift failed"
            ) from error
        formatted_texts.append(formatted.text)
        shifted_spans.append(spans)
    ids, attention, offsets = _tokenize(
        tokenizer,
        formatted_texts,
        "counterfactual source" if counterfactual else "original source",
    )
    try:
        aligned = align_char_spans(offsets, attention, shifted_spans)
    except BackboneContractError as error:
        raise TrainingMaterializationError("source event alignment failed") from error
    return ids, attention, aligned


def _relation_targets(pair: RelationOnlyPair, counterfactual: bool) -> Tensor:
    events = pair.counterfactual_events if counterfactual else pair.original_events
    annotation = (
        pair.counterfactual_relation if counterfactual else pair.original_relation
    )
    indices = {event.event_id: index for index, event in enumerate(events)}
    if set(indices) != {annotation.source_event_id, annotation.target_event_id}:
        _fail("relation annotation does not bind both materialized events")
    relation = annotation.relation
    inverse = relation.inverse()
    if relation.value not in RELATION_TO_INDEX or inverse.value not in RELATION_TO_INDEX:
        _fail("relation target is not one of the five modeled relations")
    result = torch.full((2, 2), IGNORE_RELATION_INDEX, dtype=torch.long)
    source = indices[annotation.source_event_id]
    target = indices[annotation.target_event_id]
    result[source, target] = RELATION_TO_INDEX[relation.value]
    result[target, source] = RELATION_TO_INDEX[inverse.value]
    return result


def _candidate_tensors(
    tokenizer: Any, records: Sequence[BoundTrainingRecord]
) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    encodings = []
    owner_indices: list[tuple[int, int]] = []
    for batch_index, record in enumerate(records):
        for candidate_index, text in enumerate(record.candidate_texts):
            try:
                encoding = build_candidate_encoding_text(
                    record.pair.original_query, canonical_json(text)
                )
            except (BackboneContractError, TypeError, ValueError) as error:
                raise TrainingMaterializationError(
                    "candidate encoding text construction failed"
                ) from error
            encodings.append(encoding)
            owner_indices.append((batch_index, candidate_index))
    ids, attention, offsets = _tokenize(
        tokenizer, [value.text for value in encodings], "candidate"
    )
    try:
        aligned = align_char_spans(
            offsets,
            attention,
            tuple((value.candidate_span,) for value in encodings),
        )
    except BackboneContractError as error:
        raise TrainingMaterializationError("candidate answer alignment failed") from error
    batch_size = len(records)
    candidate_count = max(len(record.candidate_texts) for record in records)
    token_count = ids.shape[1]
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if isinstance(pad_token_id, bool) or not isinstance(pad_token_id, int) or pad_token_id < 0:
        _fail("tokenizer pad token ID is invalid")
    batch_ids = torch.full(
        (batch_size, candidate_count, token_count), pad_token_id, dtype=torch.long
    )
    batch_attention = torch.zeros_like(batch_ids)
    batch_tokens = torch.zeros_like(batch_ids, dtype=torch.bool)
    batch_mask = torch.zeros((batch_size, candidate_count), dtype=torch.bool)
    for flat_index, (batch_index, candidate_index) in enumerate(owner_indices):
        batch_ids[batch_index, candidate_index] = ids[flat_index]
        batch_attention[batch_index, candidate_index] = attention[flat_index]
        batch_tokens[batch_index, candidate_index] = aligned.event_token_mask[
            flat_index, 0
        ]
        batch_mask[batch_index, candidate_index] = True
    return batch_ids, batch_attention, batch_tokens, batch_mask


def materialize_micro_batch(
    plan: TrainingPlan,
    micro_batch_index: int,
    records_by_example_id: Mapping[str, BoundTrainingRecord],
    tokenizer: Any,
) -> MaterializedTrainingBatch:
    """Materialize exactly one D-031 micro-batch, including explicit repeats."""

    if not isinstance(plan, TrainingPlan):
        _fail("training plan is invalid")
    if (
        isinstance(micro_batch_index, bool)
        or not isinstance(micro_batch_index, int)
        or not 0 <= micro_batch_index < len(plan.micro_batches)
    ):
        _fail("micro-batch index is invalid")
    if not isinstance(records_by_example_id, MappingABC) or any(
        not isinstance(key, str) for key in records_by_example_id
    ):
        _fail("materialization record map is invalid")
    expected_examples = {item.example_id: item for item in plan.corpus.examples}
    if set(records_by_example_id) != set(expected_examples):
        _fail("materialization record coverage differs from the training corpus")
    for example_id, expected in expected_examples.items():
        record = records_by_example_id[example_id]
        if not isinstance(record, BoundTrainingRecord) or record.binding != expected:
            _fail("materialization record binding differs from the training corpus")
    expected_batch = plan.micro_batches[micro_batch_index]
    records = tuple(records_by_example_id[value] for value in expected_batch.example_ids)
    original_ids, original_attention, original_events = _source_tensors(
        tokenizer, records, False
    )
    cf_ids, cf_attention, cf_events = _source_tensors(tokenizer, records, True)
    candidate_ids, candidate_attention, candidate_tokens, candidate_mask = (
        _candidate_tensors(tokenizer, records)
    )
    batch = TrainingBatch(
        input_ids=original_ids,
        attention_mask=original_attention,
        event_token_mask=original_events.event_token_mask,
        event_mask=original_events.event_mask,
        candidate_input_ids=candidate_ids,
        candidate_attention_mask=candidate_attention,
        candidate_token_mask=candidate_tokens,
        candidate_mask=candidate_mask,
        answer_targets=torch.tensor(
            [record.binding.answer_target_index for record in records],
            dtype=torch.long,
        ),
        relation_targets=torch.stack(
            [_relation_targets(record.pair, False) for record in records]
        ),
        counterfactual_input_ids=cf_ids,
        counterfactual_attention_mask=cf_attention,
        counterfactual_event_token_mask=cf_events.event_token_mask,
        counterfactual_event_mask=cf_events.event_mask,
        counterfactual_relation_targets=torch.stack(
            [_relation_targets(record.pair, True) for record in records]
        ),
    )
    return MaterializedTrainingBatch(
        example_ids=expected_batch.example_ids,
        candidate_ids=expected_batch.candidate_ids,
        batch=batch,
    )


__all__ = [
    "DATASET_ID",
    "EMPTY_POOL_POLICY",
    "MAX_TOKENS",
    "SCHEMA_VERSION",
    "BoundTrainingRecord",
    "CandidateProposal",
    "TrainingMaterializationError",
    "bind_relation_pair",
    "build_relation_training_corpus",
    "materialize_micro_batch",
]
