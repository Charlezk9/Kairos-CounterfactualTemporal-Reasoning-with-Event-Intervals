"""Frozen read-only adapters and metrics for TORQUE and TimeQA-Hard."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import string
from typing import Any, Mapping, Sequence
import unicodedata

from .ids import make_stable_id


TORQUE_REVISION = "ab27019cc6a317fde3c879900499f02acce8b16d"
TIMEQA_REVISION = "38b05989070c1168b2bef3d5a2656afeeba763dc"
TORQUE_DEV_SHA256 = (
    "7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434"
)
TIMEQA_HARD_SHA256 = (
    "0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188"
)

_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
_TORQUE_DEV = _DATA_ROOT / (
    "data/raw/torque/ab27019cc6a317fde3c879900499f02acce8b16d/"
    "extracted/TORQUE-dataset-ab27019cc6a317fde3c879900499f02acce8b16d/"
    "data/dev.json"
)
_TIMEQA_HARD = _DATA_ROOT / (
    "data/raw/timeqa/38b05989070c1168b2bef3d5a2656afeeba763dc/"
    "extracted/Time-Sensitive-QA-38b05989070c1168b2bef3d5a2656afeeba763dc/"
    "dataset/human_test.hard.json"
)
_TORQUE_BYTE_LIMIT = 4 * 1024 * 1024
_TIMEQA_BYTE_LIMIT = 32 * 1024 * 1024
_TIMEQA_LINE_LIMIT = 4 * 1024 * 1024
_TORQUE_SCHEMA = "torque-dev-adapter-v1"
_TIMEQA_SCHEMA = "timeqa-hard-adapter-v1"
_TORQUE_METRIC_SCHEMA = "torque-set-metrics-v1"
_TIMEQA_METRIC_SCHEMA = "timeqa-official-string-metrics-v1"
_ARTICLES = re.compile(r"\b(a|an|the)\b", re.UNICODE)
_PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation)


class TransferEvalError(ValueError):
    """A frozen transfer adapter or metric invariant failed."""


def _text(value: Any, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise TransferEvalError(f"{name} must be a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise TransferEvalError(f"{name} is not valid Unicode") from error
    if any(unicodedata.category(character) == "Cs" for character in value):
        raise TransferEvalError(f"{name} contains a surrogate code point")
    if nonempty and not value.strip():
        raise TransferEvalError(f"{name} must be non-empty")
    return value


def _exact_mapping(
    value: Any, expected: set[str], name: str
) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC):
        raise TransferEvalError(f"{name} must be a mapping")
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        raise TransferEvalError(f"{name} keys must be strings")
    missing = expected.difference(keys)
    extra = keys.difference(expected)
    if missing or extra:
        raise TransferEvalError(
            f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        raise TransferEvalError(f"{name} must be a non-string sequence")
    return value


def _string_sequence(
    value: Any,
    name: str,
    *,
    allow_empty: bool = True,
    item_nonempty: bool = True,
) -> tuple[str, ...]:
    result = tuple(
        _text(item, f"{name} item", nonempty=item_nonempty)
        for item in _sequence(value, name)
    )
    if not allow_empty and not result:
        raise TransferEvalError(f"{name} must be non-empty")
    return result


def _strict_json(payload: bytes, name: str) -> Any:
    duplicates: list[str] = []

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    def reject_constant(unused: str) -> Any:
        raise TransferEvalError(f"{name} contains a non-finite number")

    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TransferEvalError(f"{name} is not strict UTF-8 JSON") from error
    if duplicates:
        raise TransferEvalError(f"{name} contains duplicate JSON keys")
    return value


def _fingerprint(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_fixed_file(
    path: Path, expected_sha256: str, byte_limit: int, name: str
) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise TransferEvalError(f"{name} expected SHA256 is invalid")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise TransferEvalError(f"cannot open fixed {name} file") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise TransferEvalError(f"fixed {name} path is not a regular file")
        if before.st_size > byte_limit:
            raise TransferEvalError(f"fixed {name} file exceeds its byte limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1_048_576, byte_limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > byte_limit:
                raise TransferEvalError(f"fixed {name} file exceeds its byte limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _fingerprint(before) != _fingerprint(after) or total != after.st_size:
            raise TransferEvalError(f"fixed {name} file changed while reading")
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise TransferEvalError(f"fixed {name} SHA256 mismatch")
    return payload


@dataclass(frozen=True)
class TorqueExample:
    record_id: str
    passage_id: str
    cluster_id: str
    question: str
    passage: str
    gold_spans: tuple[str, ...]
    gold_indices: tuple[str, ...]
    is_default_question: bool
    derived_from_question: str

    def __post_init__(self) -> None:
        for field in ("record_id", "passage_id", "cluster_id", "question", "passage"):
            _text(getattr(self, field), f"TORQUE {field}")
        if not isinstance(self.is_default_question, bool):
            raise TransferEvalError("TORQUE is_default_question must be Boolean")
        _text(
            self.derived_from_question,
            "TORQUE derived_from_question",
            nonempty=False,
        )
        spans = _string_sequence(self.gold_spans, "TORQUE gold spans")
        indices = _string_sequence(self.gold_indices, "TORQUE gold indices")
        if spans != self.gold_spans or indices != self.gold_indices:
            raise TransferEvalError("TORQUE answer collections must be tuples")
        if len(spans) != len(indices):
            raise TransferEvalError("TORQUE span/index lengths differ")
        if len(set(indices)) != len(indices):
            raise TransferEvalError("TORQUE answer indices are duplicated")


@dataclass(frozen=True)
class TimeQaParagraph:
    title: str
    text: str

    def __post_init__(self) -> None:
        _text(self.title, "TimeQA paragraph title", nonempty=False)
        _text(self.text, "TimeQA paragraph text", nonempty=False)


@dataclass(frozen=True)
class TimeQaExample:
    record_id: str
    idx: str
    question: str
    context: str
    paragraphs: tuple[TimeQaParagraph, ...]
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("record_id", "idx", "question", "context"):
            _text(getattr(self, field), f"TimeQA {field}")
        if not isinstance(self.paragraphs, tuple) or any(
            not isinstance(item, TimeQaParagraph) for item in self.paragraphs
        ):
            raise TransferEvalError("TimeQA paragraphs must be a paragraph tuple")
        targets = _string_sequence(
            self.targets, "TimeQA targets", allow_empty=False
        )
        if targets != self.targets:
            raise TransferEvalError("TimeQA targets must be a tuple")


def _validate_torque_answer(
    value: Any, name: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    answer = _exact_mapping(value, {"agreed_by", "indices", "spans"}, name)
    agreed_by = _sequence(answer["agreed_by"], f"{name} agreed_by")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in agreed_by):
        raise TransferEvalError(f"{name} agreed_by items must be integers")
    indices = _string_sequence(answer["indices"], f"{name} indices")
    spans = _string_sequence(answer["spans"], f"{name} spans")
    if not (len(agreed_by) == len(indices) == len(spans)):
        raise TransferEvalError(f"{name} collection lengths differ")
    if len(set(indices)) != len(indices):
        raise TransferEvalError(f"{name} indices are duplicated")
    return spans, indices


def _validate_torque_events(value: Any, passage_id: str) -> None:
    events = _exact_mapping(value, {"answer", "passageID"}, "TORQUE events")
    if _text(events["passageID"], "TORQUE events passageID") != passage_id:
        raise TransferEvalError("TORQUE events passageID differs from its record")
    nested = _exact_mapping(
        events["answer"], {"indices", "spans"}, "TORQUE events answer"
    )
    indices = _string_sequence(nested["indices"], "TORQUE events indices")
    spans = _string_sequence(nested["spans"], "TORQUE events spans")
    if len(indices) != len(spans) or len(set(indices)) != len(indices):
        raise TransferEvalError("TORQUE event span/index invariants failed")


def _validate_individual_answers(value: Any) -> None:
    for number, raw in enumerate(
        _sequence(value, "TORQUE individual_answers"), start=1
    ):
        item = _exact_mapping(
            raw,
            {"indices", "spans", "workerId"},
            f"TORQUE individual answer {number}",
        )
        indices = _string_sequence(
            item["indices"], f"TORQUE individual answer {number} indices"
        )
        spans = _string_sequence(
            item["spans"], f"TORQUE individual answer {number} spans"
        )
        _text(item["workerId"], f"TORQUE individual answer {number} workerId")
        if len(indices) != len(spans) or len(set(indices)) != len(indices):
            raise TransferEvalError("TORQUE individual answer invariants failed")


def _parse_torque(payload: bytes) -> tuple[TorqueExample, ...]:
    root = _strict_json(payload, "TORQUE dev")
    if not isinstance(root, MappingABC) or not root:
        raise TransferEvalError("TORQUE dev must be a non-empty object")
    examples: list[TorqueExample] = []
    record_ids: set[str] = set()
    for passage_id, raw_passage in root.items():
        passage_id = _text(passage_id, "TORQUE passage ID")
        passage_record = _exact_mapping(
            raw_passage,
            {"events", "passage", "question_answer_pairs"},
            "TORQUE passage record",
        )
        passage = _text(passage_record["passage"], "TORQUE passage")
        _validate_torque_events(passage_record["events"], passage_id)
        pairs = passage_record["question_answer_pairs"]
        if not isinstance(pairs, MappingABC) or not pairs:
            raise TransferEvalError(
                "TORQUE question_answer_pairs must be a non-empty object"
            )
        for question, raw_answer in pairs.items():
            question = _text(question, "TORQUE question")
            qa = _exact_mapping(
                raw_answer,
                {
                    "answer",
                    "cluster_id",
                    "derived_from_question",
                    "individual_answers",
                    "is_default_question",
                    "passageID",
                    "validated_by",
                },
                "TORQUE question record",
            )
            if _text(qa["passageID"], "TORQUE question passageID") != passage_id:
                raise TransferEvalError(
                    "TORQUE question passageID differs from its record"
                )
            cluster_id = _text(qa["cluster_id"], "TORQUE cluster ID")
            derived = _text(
                qa["derived_from_question"],
                "TORQUE derived_from_question",
                nonempty=False,
            )
            is_default = qa["is_default_question"]
            if not isinstance(is_default, bool):
                raise TransferEvalError(
                    "TORQUE is_default_question must be Boolean"
                )
            validated_by = qa["validated_by"]
            if (
                isinstance(validated_by, bool)
                or not isinstance(validated_by, int)
                or validated_by < 0
            ):
                raise TransferEvalError(
                    "TORQUE validated_by must be a non-negative integer"
                )
            _validate_individual_answers(qa["individual_answers"])
            spans, indices = _validate_torque_answer(
                qa["answer"], "TORQUE agreed answer"
            )
            record_id = make_stable_id(
                "torque-example",
                {
                    "revision": TORQUE_REVISION,
                    "passage_id": passage_id,
                    "question": question,
                },
            )
            if record_id in record_ids:
                raise TransferEvalError("TORQUE record ID is duplicated")
            record_ids.add(record_id)
            examples.append(
                TorqueExample(
                    record_id=record_id,
                    passage_id=passage_id,
                    cluster_id=cluster_id,
                    question=question,
                    passage=passage,
                    gold_spans=spans,
                    gold_indices=indices,
                    is_default_question=is_default,
                    derived_from_question=derived,
                )
            )
    return tuple(examples)


def _load_torque_dev_file(
    path: Path, expected_sha256: str
) -> tuple[TorqueExample, ...]:
    return _parse_torque(
        _read_fixed_file(path, expected_sha256, _TORQUE_BYTE_LIMIT, "TORQUE dev")
    )


def load_torque_dev() -> tuple[TorqueExample, ...]:
    """Load the fixed, public TORQUE development split without writing files."""

    return _load_torque_dev_file(_TORQUE_DEV, TORQUE_DEV_SHA256)


def _parse_timeqa(payload: bytes) -> tuple[TimeQaExample, ...]:
    if not payload or not payload.endswith(b"\n"):
        raise TransferEvalError("TimeQA-Hard must be non-empty LF-delimited JSON")
    examples: list[TimeQaExample] = []
    record_ids: set[str] = set()
    indices: set[str] = set()
    for line_number, raw_line in enumerate(payload.splitlines(keepends=True), start=1):
        if not raw_line.endswith(b"\n") or raw_line.endswith(b"\r\n"):
            raise TransferEvalError(
                f"TimeQA-Hard line {line_number} is not LF-delimited"
            )
        content = raw_line[:-1]
        if not content:
            raise TransferEvalError(f"TimeQA-Hard line {line_number} is blank")
        if len(content) > _TIMEQA_LINE_LIMIT:
            raise TransferEvalError(
                f"TimeQA-Hard line {line_number} exceeds its byte limit"
            )
        raw = _exact_mapping(
            _strict_json(content, f"TimeQA-Hard line {line_number}"),
            {"context", "idx", "paragraphs", "question", "targets"},
            f"TimeQA-Hard line {line_number}",
        )
        idx = _text(raw["idx"], "TimeQA idx")
        if idx in indices:
            raise TransferEvalError("TimeQA idx is duplicated")
        indices.add(idx)
        paragraphs: list[TimeQaParagraph] = []
        for number, value in enumerate(
            _sequence(raw["paragraphs"], "TimeQA paragraphs"), start=1
        ):
            paragraph = _exact_mapping(
                value, {"text", "title"}, f"TimeQA paragraph {number}"
            )
            paragraphs.append(
                TimeQaParagraph(
                    title=_text(
                        paragraph["title"],
                        f"TimeQA paragraph {number} title",
                        nonempty=False,
                    ),
                    text=_text(
                        paragraph["text"],
                        f"TimeQA paragraph {number} text",
                        nonempty=False,
                    ),
                )
            )
        targets = _string_sequence(
            raw["targets"], "TimeQA targets", allow_empty=False
        )
        record_id = make_stable_id(
            "timeqa-example", {"revision": TIMEQA_REVISION, "idx": idx}
        )
        if record_id in record_ids:
            raise TransferEvalError("TimeQA record ID is duplicated")
        record_ids.add(record_id)
        examples.append(
            TimeQaExample(
                record_id=record_id,
                idx=idx,
                question=_text(raw["question"], "TimeQA question"),
                context=_text(raw["context"], "TimeQA context"),
                paragraphs=tuple(paragraphs),
                targets=targets,
            )
        )
    return tuple(examples)


def _load_timeqa_hard_file(
    path: Path, expected_sha256: str
) -> tuple[TimeQaExample, ...]:
    return _parse_timeqa(
        _read_fixed_file(
            path, expected_sha256, _TIMEQA_BYTE_LIMIT, "TimeQA-Hard"
        )
    )


def load_timeqa_hard() -> tuple[TimeQaExample, ...]:
    """Load the fixed TimeQA human hard split without writing files."""

    return _load_timeqa_hard_file(_TIMEQA_HARD, TIMEQA_HARD_SHA256)


def normalize_torque_span(value: str) -> str:
    """Normalize TORQUE spans without deleting semantically relevant punctuation."""

    value = _text(value, "TORQUE span", nonempty=False)
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _prediction_mapping(
    examples: Sequence[Any], predictions: Mapping[str, Any], name: str
) -> tuple[str, ...]:
    if not examples:
        raise TransferEvalError(f"{name} examples must be non-empty")
    if not isinstance(predictions, MappingABC):
        raise TransferEvalError(f"{name} predictions must be a mapping")
    expected = tuple(example.record_id for example in examples)
    if len(set(expected)) != len(expected):
        raise TransferEvalError(f"{name} example record IDs are duplicated")
    keys = set(predictions)
    if any(not isinstance(key, str) for key in keys):
        raise TransferEvalError(f"{name} prediction keys must be strings")
    missing = set(expected).difference(keys)
    extra = keys.difference(expected)
    if missing or extra:
        raise TransferEvalError(
            f"{name} prediction key mismatch; missing={len(missing)}, extra={len(extra)}"
        )
    return expected


def evaluate_torque(
    examples: Sequence[TorqueExample],
    predictions: Mapping[str, Sequence[str]],
) -> Mapping[str, Any]:
    """Score set-valued TORQUE predictions and both frozen cluster definitions."""

    record_ids = _prediction_mapping(examples, predictions, "TORQUE")
    exact_values: list[float] = []
    f1_values: list[float] = []
    groups: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for example, record_id in zip(examples, record_ids):
        if not isinstance(example, TorqueExample):
            raise TransferEvalError("TORQUE examples contain an invalid item")
        raw_prediction = predictions[record_id]
        predicted = {
            normalize_torque_span(item)
            for item in _string_sequence(
                raw_prediction, "TORQUE prediction", item_nonempty=False
            )
        }
        if "" in predicted:
            raise TransferEvalError(
                "TORQUE empty answer must be represented by an empty sequence"
            )
        gold = {normalize_torque_span(item) for item in example.gold_spans}
        exact = float(predicted == gold)
        if not predicted and not gold:
            f1 = 1.0
        elif not predicted or not gold:
            f1 = 0.0
        else:
            f1 = 2.0 * len(predicted.intersection(gold)) / (
                len(predicted) + len(gold)
            )
        exact_values.append(exact)
        f1_values.append(f1)
        groups[(example.passage_id, example.cluster_id)].append((exact, f1))
    exact_groups = sum(all(exact == 1.0 for exact, unused in values) for values in groups.values())
    f1_groups = sum(all(f1 >= 0.8 for unused, f1 in values) for values in groups.values())
    return {
        "schema_version": _TORQUE_METRIC_SCHEMA,
        "adapter_schema_version": _TORQUE_SCHEMA,
        "question_count": len(examples),
        "cluster_count": len(groups),
        "question_exact_match": 100.0 * sum(exact_values) / len(exact_values),
        "question_set_f1": 100.0 * sum(f1_values) / len(f1_values),
        "cluster_exact_consistency": 100.0 * exact_groups / len(groups),
        "cluster_f1_80_consistency": 100.0 * f1_groups / len(groups),
    }


def normalize_timeqa_answer(value: str) -> str:
    """Semantically reproduce the fixed TimeQA repository normalizer."""

    value = _text(value, "TimeQA answer", nonempty=False)
    lowered = value.lower()
    without_punctuation = lowered.translate(_PUNCTUATION_TABLE)
    without_articles = _ARTICLES.sub(" ", without_punctuation)
    return " ".join(without_articles.split())


def timeqa_exact(gold: str, prediction: str) -> float:
    return float(normalize_timeqa_answer(gold) == normalize_timeqa_answer(prediction))


def timeqa_f1(gold: str, prediction: str) -> float:
    gold_tokens = normalize_timeqa_answer(gold).split() if gold else []
    prediction_tokens = (
        normalize_timeqa_answer(prediction).split() if prediction else []
    )
    common = Counter(gold_tokens) & Counter(prediction_tokens)
    same = sum(common.values())
    if not gold_tokens or not prediction_tokens:
        return float(gold_tokens == prediction_tokens)
    if same == 0:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(gold_tokens)
    return 2.0 * precision * recall / (precision + recall)


def evaluate_timeqa(
    examples: Sequence[TimeQaExample], predictions: Mapping[str, str]
) -> Mapping[str, Any]:
    """Apply fixed TimeQA exact/F1 metrics, maximizing over gold targets."""

    record_ids = _prediction_mapping(examples, predictions, "TimeQA")
    exact_values: list[float] = []
    f1_values: list[float] = []
    for example, record_id in zip(examples, record_ids):
        if not isinstance(example, TimeQaExample):
            raise TransferEvalError("TimeQA examples contain an invalid item")
        prediction = predictions[record_id]
        if not isinstance(prediction, str):
            raise TransferEvalError("TimeQA predictions must be strings")
        _text(prediction, "TimeQA prediction", nonempty=False)
        exact_values.append(
            max(timeqa_exact(target, prediction) for target in example.targets)
        )
        f1_values.append(
            max(timeqa_f1(target, prediction) for target in example.targets)
        )
    return {
        "schema_version": _TIMEQA_METRIC_SCHEMA,
        "adapter_schema_version": _TIMEQA_SCHEMA,
        "total": len(examples),
        "exact_match": 100.0 * sum(exact_values) / len(exact_values),
        "token_f1": 100.0 * sum(f1_values) / len(f1_values),
    }
