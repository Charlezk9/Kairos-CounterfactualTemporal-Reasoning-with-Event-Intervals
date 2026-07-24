"""Deterministic, manifest-bound training order and resume cursors."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping, Sequence

from .ids import canonical_json, make_stable_id, sha256_canonical
from .training_adapter import QwenCoreTrainingAdapter, TrainingBatch
from .training_execution import (
    TrainingArtifactBinding,
    TrainingExecutionConfig,
    TrainingProgress,
    TrainingStepResult,
    run_optimizer_steps,
)


MANIFEST_SCHEMA_VERSION = "training-plan-manifest-v1"
CORPUS_SCHEMA_VERSION = "training-corpus-binding-v1"
SAMPLER_SCHEMA_VERSION = "sha256-epoch-rank-v1"
CANDIDATE_SCHEMA_VERSION = "training-candidate-binding-v1"
ARTIFACT_ID = "TRAINING-PLAN-V1"
_STATUS = "COMPLETE"
_MAX_EPOCHS = 3
_EFFECTIVE_BATCH_SIZE = 32
_SEEDS = frozenset({13, 42, 2026})
_MICRO_BATCH_SIZES = frozenset({1, 2, 4, 8, 16, 32})
_ORIGINS = ("direct", "cot", "self-consistency", "gold")
_ORIGIN_ORDER = {value: index for index, value in enumerate(_ORIGINS)}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,511}$")


class TrainingPlanError(ValueError):
    """A corpus, candidate, sampling, batching, or cursor invariant failed."""


def _fail(message: str) -> None:
    raise TrainingPlanError(message) from None


def _mapping(value: Any, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC) or any(
        not isinstance(key, str) for key in value
    ):
        _fail(f"{name} must be a string-keyed mapping")
    missing = keys.difference(value)
    extra = set(value).difference(keys)
    if missing or extra:
        _fail(
            f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        _fail(f"{name} must be a sequence")
    return value


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        _fail(f"{name} is outside its allowed range")
    return value


def _identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        _fail(f"{name} is invalid")
    return value


def _hex(value: Any, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        _fail(f"{name} is invalid")
    return value


def _text_sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{name} must be a non-empty string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(f"{name} is not valid Unicode")
    if len(encoded) > 1_048_576:
        _fail(f"{name} exceeds its byte limit")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CandidateBinding:
    candidate_id: str
    content_sha256: str
    origins: tuple[str, ...]

    def __post_init__(self) -> None:
        _identity(self.candidate_id, "candidate ID")
        _hex(self.content_sha256, _HEX64, "candidate content SHA256")
        if not isinstance(self.origins, tuple) or not self.origins:
            _fail("candidate origins must be a non-empty tuple")
        if any(
            not isinstance(origin, str) or origin not in _ORIGIN_ORDER
            for origin in self.origins
        ):
            _fail("candidate origin is unsupported")
        expected = tuple(sorted(set(self.origins), key=_ORIGIN_ORDER.__getitem__))
        if self.origins != expected:
            _fail("candidate origins must be unique and canonically ordered")

    @classmethod
    def from_text(
        cls, example_id: str, text: str, origins: Sequence[str]
    ) -> "CandidateBinding":
        example_id = _identity(example_id, "example ID")
        content_sha256 = _text_sha256(text, "candidate text")
        origin_values = tuple(_sequence(origins, "candidate origins"))
        candidate_id = make_stable_id(
            "candidate",
            {
                "schema_version": CANDIDATE_SCHEMA_VERSION,
                "example_id": example_id,
                "content_sha256": content_sha256,
            },
        )
        return cls(candidate_id, content_sha256, origin_values)

    def validate_for_example(self, example_id: str) -> None:
        expected = make_stable_id(
            "candidate",
            {
                "schema_version": CANDIDATE_SCHEMA_VERSION,
                "example_id": example_id,
                "content_sha256": self.content_sha256,
            },
        )
        if self.candidate_id != expected:
            _fail("candidate ID differs from its example/content binding")

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "content_sha256": self.content_sha256,
            "origins": list(self.origins),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CandidateBinding":
        value = _mapping(
            value, {"candidate_id", "content_sha256", "origins"}, "candidate"
        )
        return cls(
            candidate_id=value["candidate_id"],
            content_sha256=value["content_sha256"],
            origins=tuple(_sequence(value["origins"], "candidate origins")),
        )


@dataclass(frozen=True)
class TrainingExampleBinding:
    source_order_index: int
    example_id: str
    source_id: str
    original_record_id: str
    counterfactual_record_id: str
    record_sha256: str
    gold_answer_sha256: str
    candidates: tuple[CandidateBinding, ...]
    answer_target_index: int
    gold_injected: bool

    def __post_init__(self) -> None:
        _integer(self.source_order_index, "source order index", 0, 10_000_000)
        for name in (
            "example_id",
            "source_id",
            "original_record_id",
            "counterfactual_record_id",
        ):
            _identity(getattr(self, name), name.replace("_", " "))
        if self.original_record_id == self.counterfactual_record_id:
            _fail("original and counterfactual record IDs must differ")
        _hex(self.record_sha256, _HEX64, "record SHA256")
        _hex(self.gold_answer_sha256, _HEX64, "gold answer SHA256")
        if (
            not isinstance(self.candidates, tuple)
            or not 1 <= len(self.candidates) <= 64
            or any(not isinstance(item, CandidateBinding) for item in self.candidates)
        ):
            _fail("candidate pool must contain 1..64 candidate bindings")
        target = _integer(
            self.answer_target_index,
            "answer target index",
            0,
            len(self.candidates) - 1,
        )
        if not isinstance(self.gold_injected, bool):
            _fail("gold_injected must be Boolean")
        candidate_ids: set[str] = set()
        content_hashes: set[str] = set()
        for candidate in self.candidates:
            candidate.validate_for_example(self.example_id)
            if candidate.candidate_id in candidate_ids:
                _fail("candidate ID is duplicated within an example")
            if candidate.content_sha256 in content_hashes:
                _fail("candidate content is not deduplicated")
            candidate_ids.add(candidate.candidate_id)
            content_hashes.add(candidate.content_sha256)
        selected = self.candidates[target]
        if selected.content_sha256 != self.gold_answer_sha256:
            _fail("answer target does not bind the gold answer")
        gold_candidates = [
            index
            for index, candidate in enumerate(self.candidates)
            if "gold" in candidate.origins
        ]
        if self.gold_injected:
            if target != len(self.candidates) - 1 or gold_candidates != [target]:
                _fail("injected gold must be the final and only gold-origin candidate")
            if selected.origins != ("gold",):
                _fail("injected gold candidate must have only gold provenance")
        elif gold_candidates:
            _fail("a non-injected pool must not claim gold provenance")

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "source_order_index": self.source_order_index,
            "example_id": self.example_id,
            "source_id": self.source_id,
            "original_record_id": self.original_record_id,
            "counterfactual_record_id": self.counterfactual_record_id,
            "record_sha256": self.record_sha256,
            "gold_answer_sha256": self.gold_answer_sha256,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "answer_target_index": self.answer_target_index,
            "gold_injected": self.gold_injected,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TrainingExampleBinding":
        value = _mapping(
            value,
            {
                "source_order_index",
                "example_id",
                "source_id",
                "original_record_id",
                "counterfactual_record_id",
                "record_sha256",
                "gold_answer_sha256",
                "candidates",
                "answer_target_index",
                "gold_injected",
            },
            "training example",
        )
        return cls(
            source_order_index=value["source_order_index"],
            example_id=value["example_id"],
            source_id=value["source_id"],
            original_record_id=value["original_record_id"],
            counterfactual_record_id=value["counterfactual_record_id"],
            record_sha256=value["record_sha256"],
            gold_answer_sha256=value["gold_answer_sha256"],
            candidates=tuple(
                CandidateBinding.from_dict(candidate)
                for candidate in _sequence(value["candidates"], "candidates")
            ),
            answer_target_index=value["answer_target_index"],
            gold_injected=value["gold_injected"],
        )


@dataclass(frozen=True)
class TrainingCorpusBinding:
    execution_commit: str
    dataset_id: str
    dataset_revision: str
    official_split: str
    source_artifact_id: str
    source_manifest_sha256: str
    examples: tuple[TrainingExampleBinding, ...]

    def __post_init__(self) -> None:
        _hex(self.execution_commit, _HEX40, "execution commit")
        if not isinstance(self.dataset_id, str) or not _DATASET_ID.fullmatch(
            self.dataset_id
        ):
            _fail("dataset ID is invalid")
        _hex(self.dataset_revision, _HEX40, "dataset revision")
        if self.official_split != "train":
            _fail("training corpus is restricted to the official train split")
        if not isinstance(self.source_artifact_id, str) or not _ARTIFACT_ID.fullmatch(
            self.source_artifact_id
        ):
            _fail("source artifact ID is invalid")
        _hex(self.source_manifest_sha256, _HEX64, "source manifest SHA256")
        if (
            not isinstance(self.examples, tuple)
            or not self.examples
            or any(not isinstance(item, TrainingExampleBinding) for item in self.examples)
        ):
            _fail("training corpus examples must be a non-empty tuple")
        identity_sets = {
            "example ID": set(),
            "source ID": set(),
            "original record ID": set(),
            "counterfactual record ID": set(),
            "record SHA256": set(),
        }
        for index, example in enumerate(self.examples):
            if example.source_order_index != index:
                _fail("source order indices must be consecutive and unchanged")
            values = {
                "example ID": example.example_id,
                "source ID": example.source_id,
                "original record ID": example.original_record_id,
                "counterfactual record ID": example.counterfactual_record_id,
                "record SHA256": example.record_sha256,
            }
            for name, value in values.items():
                if value in identity_sets[name]:
                    _fail(f"{name} is duplicated in the training corpus")
                identity_sets[name].add(value)

    @property
    def sha256(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "execution_commit": self.execution_commit,
            "dataset": {
                "dataset_id": self.dataset_id,
                "revision": self.dataset_revision,
                "official_split": self.official_split,
            },
            "source_artifact": {
                "artifact_id": self.source_artifact_id,
                "manifest_sha256": self.source_manifest_sha256,
            },
            "examples": [example.to_dict() for example in self.examples],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TrainingCorpusBinding":
        value = _mapping(
            value,
            {
                "schema_version",
                "execution_commit",
                "dataset",
                "source_artifact",
                "examples",
            },
            "training corpus",
        )
        if value["schema_version"] != CORPUS_SCHEMA_VERSION:
            _fail("training corpus schema version differs")
        dataset = _mapping(
            value["dataset"],
            {"dataset_id", "revision", "official_split"},
            "training corpus dataset",
        )
        source = _mapping(
            value["source_artifact"],
            {"artifact_id", "manifest_sha256"},
            "training corpus source artifact",
        )
        return cls(
            execution_commit=value["execution_commit"],
            dataset_id=dataset["dataset_id"],
            dataset_revision=dataset["revision"],
            official_split=dataset["official_split"],
            source_artifact_id=source["artifact_id"],
            source_manifest_sha256=source["manifest_sha256"],
            examples=tuple(
                TrainingExampleBinding.from_dict(example)
                for example in _sequence(value["examples"], "training examples")
            ),
        )


@dataclass(frozen=True)
class TrainingSlot:
    global_slot_index: int
    epoch_index: int | None
    epoch_position: int
    source_order_index: int
    example_id: str
    rank_sha256: str
    repeat_padding: bool

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "global_slot_index": self.global_slot_index,
            "epoch_index": self.epoch_index,
            "epoch_position": self.epoch_position,
            "source_order_index": self.source_order_index,
            "example_id": self.example_id,
            "rank_sha256": self.rank_sha256,
            "repeat_padding": self.repeat_padding,
        }


@dataclass(frozen=True)
class MicroBatchBinding:
    micro_batch_index: int
    optimizer_step_index: int
    accumulation_index: int
    slot_indices: tuple[int, ...]
    example_ids: tuple[str, ...]
    candidate_ids: tuple[tuple[str, ...], ...]
    repeat_padding: tuple[bool, ...]

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "micro_batch_index": self.micro_batch_index,
            "optimizer_step_index": self.optimizer_step_index,
            "accumulation_index": self.accumulation_index,
            "slot_indices": list(self.slot_indices),
            "example_ids": list(self.example_ids),
            "candidate_ids": [list(values) for values in self.candidate_ids],
            "repeat_padding": list(self.repeat_padding),
        }


def _rank(
    corpus_sha256: str,
    seed: int,
    epoch_index: int | None,
    example: TrainingExampleBinding,
) -> str:
    return sha256_canonical(
        {
            "schema_version": SAMPLER_SCHEMA_VERSION,
            "corpus_sha256": corpus_sha256,
            "seed": seed,
            "epoch_index": epoch_index,
            "source_order_index": example.source_order_index,
            "example_id": example.example_id,
        }
    )


def _expected_slots(
    corpus: TrainingCorpusBinding, seed: int
) -> tuple[TrainingSlot, ...]:
    slots: list[TrainingSlot] = []
    for epoch_index in range(_MAX_EPOCHS):
        ranked = sorted(
            (
                (_rank(corpus.sha256, seed, epoch_index, example), example)
                for example in corpus.examples
            ),
            key=lambda item: (
                item[0],
                item[1].source_order_index,
                item[1].example_id,
            ),
        )
        for epoch_position, (rank_sha256, example) in enumerate(ranked):
            slots.append(
                TrainingSlot(
                    global_slot_index=len(slots),
                    epoch_index=epoch_index,
                    epoch_position=epoch_position,
                    source_order_index=example.source_order_index,
                    example_id=example.example_id,
                    rank_sha256=rank_sha256,
                    repeat_padding=False,
                )
            )
    padding_count = (-len(slots)) % _EFFECTIVE_BATCH_SIZE
    ranked_padding = sorted(
        (
            (_rank(corpus.sha256, seed, None, example), example)
            for example in corpus.examples
        ),
        key=lambda item: (
            item[0],
            item[1].source_order_index,
            item[1].example_id,
        ),
    )
    for padding_position in range(padding_count):
        rank_sha256, example = ranked_padding[padding_position % len(ranked_padding)]
        slots.append(
            TrainingSlot(
                global_slot_index=len(slots),
                epoch_index=None,
                epoch_position=padding_position,
                source_order_index=example.source_order_index,
                example_id=example.example_id,
                rank_sha256=rank_sha256,
                repeat_padding=True,
            )
        )
    return tuple(slots)


def _expected_micro_batches(
    corpus: TrainingCorpusBinding,
    slots: tuple[TrainingSlot, ...],
    micro_batch_size: int,
) -> tuple[MicroBatchBinding, ...]:
    by_index = {example.source_order_index: example for example in corpus.examples}
    accumulation_steps = _EFFECTIVE_BATCH_SIZE // micro_batch_size
    batches: list[MicroBatchBinding] = []
    for start in range(0, len(slots), micro_batch_size):
        selected = slots[start : start + micro_batch_size]
        index = len(batches)
        batches.append(
            MicroBatchBinding(
                micro_batch_index=index,
                optimizer_step_index=index // accumulation_steps,
                accumulation_index=index % accumulation_steps,
                slot_indices=tuple(slot.global_slot_index for slot in selected),
                example_ids=tuple(slot.example_id for slot in selected),
                candidate_ids=tuple(
                    tuple(
                        candidate.candidate_id
                        for candidate in by_index[slot.source_order_index].candidates
                    )
                    for slot in selected
                ),
                repeat_padding=tuple(slot.repeat_padding for slot in selected),
            )
        )
    return tuple(batches)


@dataclass(frozen=True)
class TrainingCursor:
    manifest_sha256: str
    optimizer_steps_completed: int
    next_micro_batch_index: int
    consumed_slots: int
    consumed_real_slots: int
    consumed_repeat_padding_slots: int
    completed_epochs: int
    next_example_id: str | None
    next_source_order_index: int | None
    next_epoch_index: int | None
    next_is_repeat_padding: bool | None
    done: bool

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "manifest_sha256": self.manifest_sha256,
            "optimizer_steps_completed": self.optimizer_steps_completed,
            "next_micro_batch_index": self.next_micro_batch_index,
            "consumed_slots": self.consumed_slots,
            "consumed_real_slots": self.consumed_real_slots,
            "consumed_repeat_padding_slots": self.consumed_repeat_padding_slots,
            "completed_epochs": self.completed_epochs,
            "next_example_id": self.next_example_id,
            "next_source_order_index": self.next_source_order_index,
            "next_epoch_index": self.next_epoch_index,
            "next_is_repeat_padding": self.next_is_repeat_padding,
            "done": self.done,
        }


@dataclass(frozen=True)
class MaterializedTrainingBatch:
    example_ids: tuple[str, ...]
    candidate_ids: tuple[tuple[str, ...], ...]
    batch: TrainingBatch

    def __post_init__(self) -> None:
        if not isinstance(self.example_ids, tuple) or not self.example_ids:
            _fail("materialized example IDs must be a non-empty tuple")
        if any(not isinstance(value, str) for value in self.example_ids):
            _fail("materialized example IDs are invalid")
        if (
            not isinstance(self.candidate_ids, tuple)
            or len(self.candidate_ids) != len(self.example_ids)
            or any(
                not isinstance(values, tuple)
                or not values
                or any(not isinstance(value, str) for value in values)
                for values in self.candidate_ids
            )
        ):
            _fail("materialized candidate IDs are invalid")
        if not isinstance(self.batch, TrainingBatch):
            _fail("materialized training batch is invalid")
        if self.batch.input_ids.shape[0] != len(self.example_ids):
            _fail("materialized batch size differs from its identities")


@dataclass(frozen=True)
class TrainingPlan:
    corpus: TrainingCorpusBinding
    seed: int
    micro_batch_size: int
    slots: tuple[TrainingSlot, ...]
    micro_batches: tuple[MicroBatchBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.corpus, TrainingCorpusBinding):
            _fail("training plan corpus is invalid")
        if self.seed not in _SEEDS:
            _fail("training plan seed is not frozen")
        if self.micro_batch_size not in _MICRO_BATCH_SIZES:
            _fail("training micro batch size is not frozen")
        expected_slots = _expected_slots(self.corpus, self.seed)
        if self.slots != expected_slots:
            _fail("training slots differ from deterministic reconstruction")
        expected_batches = _expected_micro_batches(
            self.corpus, expected_slots, self.micro_batch_size
        )
        if self.micro_batches != expected_batches:
            _fail("micro batches differ from deterministic reconstruction")
        if len(self.slots) % _EFFECTIVE_BATCH_SIZE:
            _fail("training slots do not end at an optimizer boundary")

    @property
    def gradient_accumulation_steps(self) -> int:
        return _EFFECTIVE_BATCH_SIZE // self.micro_batch_size

    @property
    def total_optimizer_steps(self) -> int:
        return len(self.slots) // _EFFECTIVE_BATCH_SIZE

    @property
    def real_slot_count(self) -> int:
        return len(self.corpus.examples) * _MAX_EPOCHS

    @property
    def repeat_padding_count(self) -> int:
        return len(self.slots) - self.real_slot_count

    @property
    def manifest_sha256(self) -> str:
        return sha256_canonical(self.to_dict())

    @property
    def execution_config(self) -> TrainingExecutionConfig:
        return TrainingExecutionConfig(
            seed=self.seed,
            micro_batch_size=self.micro_batch_size,
            gradient_accumulation_steps=self.gradient_accumulation_steps,
            total_optimizer_steps=self.total_optimizer_steps,
        )

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "status": _STATUS,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "artifact_id": ARTIFACT_ID,
            "corpus": self.corpus.to_dict(),
            "sampler": {
                "schema_version": SAMPLER_SCHEMA_VERSION,
                "seed": self.seed,
                "max_epochs": _MAX_EPOCHS,
                "rank_order": ["rank_sha256", "source_order_index", "example_id"],
                "shuffle_rng": "none",
            },
            "batching": {
                "micro_batch_size": self.micro_batch_size,
                "gradient_accumulation_steps": self.gradient_accumulation_steps,
                "effective_batch_size": _EFFECTIVE_BATCH_SIZE,
                "tail_policy": "deterministic-explicit-repeat-padding-v1",
            },
            "execution_config": self.execution_config.to_dict(),
            "summary": {
                "source_example_count": len(self.corpus.examples),
                "real_slot_count": self.real_slot_count,
                "repeat_padding_count": self.repeat_padding_count,
                "total_slot_count": len(self.slots),
                "micro_batch_count": len(self.micro_batches),
                "optimizer_step_count": self.total_optimizer_steps,
            },
            "slots": [slot.to_dict() for slot in self.slots],
            "micro_batches": [batch.to_dict() for batch in self.micro_batches],
        }

    def cursor(self, optimizer_steps_completed: int) -> TrainingCursor:
        steps = _integer(
            optimizer_steps_completed,
            "optimizer steps completed",
            0,
            self.total_optimizer_steps,
        )
        consumed = steps * _EFFECTIVE_BATCH_SIZE
        real = min(consumed, self.real_slot_count)
        repeat = consumed - real
        completed_epochs = min(real // len(self.corpus.examples), _MAX_EPOCHS)
        done = consumed == len(self.slots)
        next_slot = None if done else self.slots[consumed]
        return TrainingCursor(
            manifest_sha256=self.manifest_sha256,
            optimizer_steps_completed=steps,
            next_micro_batch_index=steps * self.gradient_accumulation_steps,
            consumed_slots=consumed,
            consumed_real_slots=real,
            consumed_repeat_padding_slots=repeat,
            completed_epochs=completed_epochs,
            next_example_id=None if next_slot is None else next_slot.example_id,
            next_source_order_index=(
                None if next_slot is None else next_slot.source_order_index
            ),
            next_epoch_index=None if next_slot is None else next_slot.epoch_index,
            next_is_repeat_padding=(
                None if next_slot is None else next_slot.repeat_padding
            ),
            done=done,
        )

    def progress(self, optimizer_steps_completed: int) -> TrainingProgress:
        cursor = self.cursor(optimizer_steps_completed)
        progress = TrainingProgress(
            epoch=cursor.completed_epochs,
            next_micro_batch_index=cursor.next_micro_batch_index,
            optimizer_steps_completed=cursor.optimizer_steps_completed,
            samples_seen=cursor.consumed_slots,
        )
        progress.validate(self.execution_config)
        return progress

    def validate_cursor(self, cursor: TrainingCursor) -> None:
        if not isinstance(cursor, TrainingCursor):
            _fail("resume cursor is invalid")
        if cursor != self.cursor(cursor.optimizer_steps_completed):
            _fail("resume cursor differs from the deterministic training plan")

    def validate_progress(self, progress: TrainingProgress) -> TrainingCursor:
        if not isinstance(progress, TrainingProgress):
            _fail("training progress is invalid")
        try:
            progress.validate(self.execution_config)
        except ValueError:
            _fail("training progress violates the execution configuration")
        expected = self.progress(progress.optimizer_steps_completed)
        if progress != expected:
            _fail("training progress differs from the exact plan cursor")
        return self.cursor(progress.optimizer_steps_completed)

    def validate_artifact_binding(self, binding: TrainingArtifactBinding) -> None:
        if not isinstance(binding, TrainingArtifactBinding):
            _fail("checkpoint artifact binding is invalid")
        if (
            binding.dataset_id != self.corpus.dataset_id
            or binding.dataset_revision != self.corpus.dataset_revision
            or binding.split != self.corpus.official_split
            or binding.data_artifact_id != ARTIFACT_ID
            or binding.data_manifest_sha256 != self.manifest_sha256
        ):
            _fail("checkpoint data binding differs from the training plan")


def build_training_plan(
    corpus: TrainingCorpusBinding, seed: int, micro_batch_size: int
) -> TrainingPlan:
    if not isinstance(corpus, TrainingCorpusBinding):
        _fail("training corpus is invalid")
    if seed not in _SEEDS:
        _fail("training plan seed is not frozen")
    if micro_batch_size not in _MICRO_BATCH_SIZES:
        _fail("training micro batch size is not frozen")
    slots = _expected_slots(corpus, seed)
    batches = _expected_micro_batches(corpus, slots, micro_batch_size)
    return TrainingPlan(corpus, seed, micro_batch_size, slots, batches)


def training_plan_from_dict(value: Any) -> TrainingPlan:
    value = _mapping(
        value,
        {
            "status",
            "schema_version",
            "artifact_id",
            "corpus",
            "sampler",
            "batching",
            "execution_config",
            "summary",
            "slots",
            "micro_batches",
        },
        "training plan manifest",
    )
    if (
        value["status"] != _STATUS
        or value["schema_version"] != MANIFEST_SCHEMA_VERSION
        or value["artifact_id"] != ARTIFACT_ID
    ):
        _fail("training plan manifest identity differs")
    sampler = _mapping(
        value["sampler"],
        {"schema_version", "seed", "max_epochs", "rank_order", "shuffle_rng"},
        "training sampler",
    )
    batching = _mapping(
        value["batching"],
        {
            "micro_batch_size",
            "gradient_accumulation_steps",
            "effective_batch_size",
            "tail_policy",
        },
        "training batching",
    )
    corpus = TrainingCorpusBinding.from_dict(value["corpus"])
    plan = build_training_plan(
        corpus, sampler["seed"], batching["micro_batch_size"]
    )
    try:
        matches = canonical_json(plan.to_dict()) == canonical_json(value)
    except (TypeError, ValueError):
        _fail("training plan manifest is not canonical-JSON compatible")
    if not matches:
        _fail("training plan manifest differs from deterministic reconstruction")
    return plan


def _validate_materialized_batch(
    plan: TrainingPlan,
    expected: MicroBatchBinding,
    materialized: MaterializedTrainingBatch,
) -> TrainingBatch:
    if not isinstance(materialized, MaterializedTrainingBatch):
        _fail("materialized training batch entry is invalid")
    if (
        materialized.example_ids != expected.example_ids
        or materialized.candidate_ids != expected.candidate_ids
    ):
        _fail("materialized batch identities differ from the training manifest")
    by_id = {example.example_id: example for example in plan.corpus.examples}
    target_indices = tuple(
        by_id[example_id].answer_target_index for example_id in expected.example_ids
    )
    batch = materialized.batch
    if tuple(batch.answer_targets.detach().cpu().tolist()) != target_indices:
        _fail("materialized answer targets differ from the training manifest")
    candidate_mask = batch.candidate_mask.detach().cpu().tolist()
    for mask, candidate_ids in zip(candidate_mask, expected.candidate_ids):
        wanted = [True] * len(candidate_ids) + [False] * (
            len(mask) - len(candidate_ids)
        )
        if len(mask) < len(candidate_ids) or mask != wanted:
            _fail("materialized candidate mask differs from the training manifest")
    return batch


class _ValidatedBatchWindow(SequenceABC[TrainingBatch]):
    def __init__(
        self, total_count: int, validated: Mapping[int, TrainingBatch]
    ) -> None:
        self._total_count = total_count
        self._validated = dict(validated)

    def __len__(self) -> int:
        return self._total_count

    def __getitem__(self, index: int | slice) -> TrainingBatch | tuple[TrainingBatch, ...]:
        if isinstance(index, slice):
            return tuple(self[item] for item in range(*index.indices(len(self))))
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("training batch index must be an integer")
        normalized = index + len(self) if index < 0 else index
        if not 0 <= normalized < len(self):
            raise IndexError(index)
        if normalized not in self._validated:
            _fail("training executor accessed outside the validated batch window")
        return self._validated[normalized]


def execute_planned_training_steps(
    adapter: QwenCoreTrainingAdapter,
    batches: Sequence[MaterializedTrainingBatch],
    optimizer: Any,
    scheduler: Any,
    plan: TrainingPlan,
    progress: TrainingProgress,
    optimizer_steps: int,
) -> TrainingStepResult:
    """Execute only manifest-identity-matched batches and advance the exact cursor."""

    if not isinstance(plan, TrainingPlan):
        _fail("training plan is invalid")
    plan.validate_progress(progress)
    if isinstance(batches, (str, bytes, bytearray)) or not isinstance(
        batches, SequenceABC
    ):
        _fail("materialized training batches must be a sequence")
    if len(batches) != len(plan.micro_batches):
        _fail("materialized batch count differs from the training manifest")
    steps = _integer(
        optimizer_steps,
        "requested optimizer steps",
        1,
        plan.total_optimizer_steps,
    )
    start = progress.next_micro_batch_index
    end = start + steps * plan.gradient_accumulation_steps
    if end > len(plan.micro_batches):
        _fail("requested optimizer steps exceed the training plan")
    validated = {
        index: _validate_materialized_batch(
            plan, plan.micro_batches[index], batches[index]
        )
        for index in range(start, end)
    }
    tensor_batches = _ValidatedBatchWindow(len(plan.micro_batches), validated)
    result = run_optimizer_steps(
        adapter,
        tensor_batches,
        optimizer,
        scheduler,
        plan.execution_config,
        progress,
        steps,
    )
    exact = plan.progress(result.progress.optimizer_steps_completed)
    if (
        result.progress.next_micro_batch_index != exact.next_micro_batch_index
        or result.progress.optimizer_steps_completed
        != exact.optimizer_steps_completed
        or result.progress.samples_seen != exact.samples_seen
    ):
        _fail("training executor cursor differs from the manifest plan")
    return TrainingStepResult(exact, result.optimizer_losses, result.gradient_norms)


__all__ = [
    "ARTIFACT_ID",
    "CANDIDATE_SCHEMA_VERSION",
    "CORPUS_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "CandidateBinding",
    "MaterializedTrainingBatch",
    "MicroBatchBinding",
    "TrainingCorpusBinding",
    "TrainingCursor",
    "TrainingExampleBinding",
    "TrainingPlan",
    "TrainingPlanError",
    "TrainingSlot",
    "build_training_plan",
    "execute_planned_training_steps",
    "training_plan_from_dict",
]
