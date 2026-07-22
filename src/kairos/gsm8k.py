"""Immutable GSM8K source-ledger preparation fixed by D-005/D-005-A."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, BinaryIO, Callable, Mapping, Optional, Sequence

from . import acquisition
from .archive_safety import ArchiveSafetyError
from .ids import assign_split, canonical_json, make_stable_id
from .schema import (
    AnswerType,
    InternalSplit,
    SourceProvenance,
    SplitAssignment,
    TemporalExample,
)


REVISION = "3101c7d5072418e28b9008a6636bde82a006892c"
_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
_RAW_REVISION_REL = f"data/raw/gsm8k/{REVISION}"
_TARGET_PARENT_REL = f"data/processed/gsm8k/{REVISION}"
_TARGET_LEAF = "source-record-v1"
_COMPLETION_REL = f"{_RAW_REVISION_REL}/completion-manifest.json"
_RAW_LINE_LIMIT = 1_048_576
_OUTPUT_LINE_LIMIT = 2 * _RAW_LINE_LIMIT + 65_536
_SMALL_FILE_LIMIT = 1_048_576
_ASCII_WS = " \t\n\r\v\f"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_NAMES = {
    "source_train": "source-train.jsonl",
    "source_test": "source-test.jsonl",
    "example_train": "examples-train.jsonl",
    "example_test": "examples-test.jsonl",
}
_MANIFEST = "processed-manifest.json"
_FINAL_NAMES = frozenset((*_OUTPUT_NAMES.values(), _MANIFEST))
_FAULT_HOOK: Optional[Callable[[str, str], None]] = None


class Gsm8kError(ValueError):
    """A frozen GSM8K adapter invariant failed."""


@dataclass(frozen=True)
class Gsm8kAnswerParts:
    prefix: str
    separator: str
    suffix: str
    target: str

    def reconstruct(self) -> str:
        return self.prefix + self.separator + self.suffix


@dataclass(frozen=True)
class Gsm8kSourceRecord:
    source_id: str
    dataset: str
    revision: str
    split: SplitAssignment
    source_sha256: str
    provenance: SourceProvenance
    question: str
    answer: str

    def __post_init__(self) -> None:
        for name in ("source_id", "revision", "question", "answer"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise Gsm8kError(f"source record {name} must be a non-empty string")
        if self.dataset != "gsm8k":
            raise Gsm8kError("source record dataset must be gsm8k")
        if self.revision != REVISION:
            raise Gsm8kError("source record revision differs from the frozen revision")
        if not isinstance(self.split, SplitAssignment):
            raise Gsm8kError("source record split must be a SplitAssignment")
        if self.split.official not in {"train", "test"}:
            raise Gsm8kError("source record official split is invalid")
        if self.split != assign_split(self.source_id, self.split.official):
            raise Gsm8kError("source record internal split is invalid")
        if not isinstance(self.source_sha256, str) or not _HEX64.fullmatch(
            self.source_sha256
        ):
            raise Gsm8kError("source record SHA256 is invalid")
        if not isinstance(self.provenance, SourceProvenance):
            raise Gsm8kError("source record provenance is invalid")
        expected_source_id = make_stable_id(
            "source",
            {
                "dataset": "gsm8k",
                "revision": REVISION,
                "official_split": self.split.official,
                "relative_path": self.provenance.relative_path,
                "line_number": self.provenance.line_number,
                "source_sha256": self.source_sha256,
            },
        )
        if self.source_id != expected_source_id:
            raise Gsm8kError("source record ID differs from its literal inputs")

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "source_id": self.source_id,
            "dataset": self.dataset,
            "revision": self.revision,
            "split": {
                "official": self.split.official,
                "internal": (
                    self.split.internal.value
                    if self.split.internal is not None
                    else None
                ),
            },
            "source_sha256": self.source_sha256,
            "provenance": self.provenance.to_dict(),
            "question": self.question,
            "answer": self.answer,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Gsm8kSourceRecord":
        value = _exact_mapping(
            value,
            {
                "source_id",
                "dataset",
                "revision",
                "split",
                "source_sha256",
                "provenance",
                "question",
                "answer",
            },
            "Gsm8kSourceRecord",
        )
        split_value = _exact_mapping(
            value["split"], {"official", "internal"}, "source split"
        )
        official = split_value["official"]
        internal_value = split_value["internal"]
        if not isinstance(official, str):
            raise Gsm8kError("source official split must be a string")
        try:
            internal = (
                InternalSplit(internal_value) if internal_value is not None else None
            )
        except (TypeError, ValueError) as error:
            raise Gsm8kError("source internal split is invalid") from error
        try:
            provenance = SourceProvenance.from_dict(value["provenance"])
        except (TypeError, ValueError) as error:
            raise Gsm8kError("source provenance is invalid") from error
        return cls(
            source_id=value["source_id"],
            dataset=value["dataset"],
            revision=value["revision"],
            split=SplitAssignment(official=official, internal=internal),
            source_sha256=value["source_sha256"],
            provenance=provenance,
            question=value["question"],
            answer=value["answer"],
        )


@dataclass(frozen=True)
class _Fingerprint:
    device: int
    inode: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _OwnedResource:
    resource: Any
    artifact: Optional[str] = None


@dataclass(frozen=True)
class _SourceBinding:
    official_split: str
    relative_path: str
    sha256: str
    byte_size: int
    record_count: int


@dataclass(frozen=True)
class _AcquisitionBinding:
    provenance_commit: str
    completion_manifest_path: str
    completion_manifest_sha256: str
    sha256sums_sha256: str
    formal_tree_fingerprint_sha256: str


@dataclass(frozen=True)
class _Layout:
    data_root: Path
    raw_revision_rel: str
    target_parent_rel: str
    target_leaf: str
    acquisition: _AcquisitionBinding
    sources: Mapping[str, _SourceBinding]


@dataclass(frozen=True)
class _FileFacts:
    path: str
    byte_size: int
    record_count: int
    sha256: str
    fingerprint: _Fingerprint


@dataclass(frozen=True)
class _SplitVerification:
    source: _FileFacts
    example: _FileFacts
    duplicate_values: Mapping[str, int]


@dataclass(frozen=True)
class _OutputVerification:
    outputs: Mapping[str, _FileFacts]
    duplicates: Mapping[str, int]


_PRODUCTION_LAYOUT = _Layout(
    data_root=_DATA_ROOT,
    raw_revision_rel=_RAW_REVISION_REL,
    target_parent_rel=_TARGET_PARENT_REL,
    target_leaf=_TARGET_LEAF,
    acquisition=_AcquisitionBinding(
        provenance_commit="482af857249b03d89c986dce96c9d38fc11cfd70",
        completion_manifest_path=_COMPLETION_REL,
        completion_manifest_sha256=(
            "d8861250e197bf04e1f24fee4dbb7bfe07194f485095f77cdcc8669412e35047"
        ),
        sha256sums_sha256=(
            "fb6bb5349ea5a620062f34cda78eb4faed2aa8a6ec9cf43ad54010904b813107"
        ),
        formal_tree_fingerprint_sha256=(
            "6b52e122a14c0f78baf3fc0b046b312b780518771828702acf074ab8ac95583f"
        ),
    ),
    sources={
        "train": _SourceBinding(
            "train",
            (
                f"extracted/grade-school-math-{REVISION}/"
                "grade_school_math/data/train.jsonl"
            ),
            "17f347dc51477c50d4efb83959dbb7c56297aba886e5544ee2aaed3024813465",
            4_166_206,
            7_473,
        ),
        "test": _SourceBinding(
            "test",
            (
                f"extracted/grade-school-math-{REVISION}/"
                "grade_school_math/data/test.jsonl"
            ),
            "3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14",
            749_738,
            1_319,
        ),
    },
)


def parse_gsm8k_answer(answer: str) -> Gsm8kAnswerParts:
    if not isinstance(answer, str):
        raise Gsm8kError("GSM8K answer must be a string")
    if answer.count("####") != 1:
        raise Gsm8kError("GSM8K answer must contain exactly one delimiter")
    prefix, separator, suffix = answer.partition("####")
    if prefix + separator + suffix != answer:
        raise Gsm8kError("GSM8K answer split is not reversible")
    if not prefix.strip(_ASCII_WS):
        raise Gsm8kError("GSM8K answer prefix is empty")
    target = suffix.strip(_ASCII_WS)
    if not target or not target.strip():
        raise Gsm8kError("GSM8K answer target is empty")
    return Gsm8kAnswerParts(prefix, separator, suffix, target)


def _exact_mapping(
    value: Any, expected: set[str], name: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Gsm8kError(f"{name} must be a mapping")
    keys = set(value)
    missing = expected.difference(keys)
    extra = keys.difference(expected)
    if missing or extra:
        raise Gsm8kError(f"invalid {name} keys")
    return value


def _strict_object(data: bytes, name: str) -> Mapping[str, Any]:
    duplicates: list[str] = []

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    def reject_constant(unused: str) -> Any:
        raise Gsm8kError(f"{name} contains a non-finite number")

    try:
        decoded = data.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Gsm8kError(f"{name} is not strict UTF-8 JSON") from error
    if duplicates:
        raise Gsm8kError(f"{name} contains duplicate keys")
    if not isinstance(value, Mapping):
        raise Gsm8kError(f"{name} must be a JSON object")
    return value


def _fingerprint_fd(fd: int) -> _Fingerprint:
    value = os.fstat(fd)
    return _Fingerprint(
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _dir_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _fault(point: str, artifact: str) -> None:
    if _FAULT_HOOK is not None:
        _FAULT_HOOK(point, artifact)


def _close_resources_best_effort(
    resources: Sequence[Any], active_exception: Optional[BaseException] = None
) -> None:
    first: Optional[BaseException] = None
    for owned in tuple(resources):
        if isinstance(owned, _OwnedResource):
            resource = owned.resource
            artifact = owned.artifact
        else:
            resource = owned
            artifact = None
        if resource is None or (
            isinstance(resource, int) and not isinstance(resource, bool) and resource < 0
        ):
            continue
        if artifact is not None:
            try:
                _fault("close", artifact)
            except BaseException as error:
                if first is None:
                    first = error
        try:
            if isinstance(resource, int):
                os.close(resource)
            else:
                resource.close()
        except BaseException as error:
            if first is None:
                first = error
    if first is not None and active_exception is None:
        raise first


def _close_fds_best_effort(
    fds: Sequence[int], active_exception: Optional[BaseException] = None
) -> None:
    _close_resources_best_effort(fds, active_exception)


def _owned_fdopen(fd: int) -> BinaryIO:
    try:
        handle = os.fdopen(fd, "rb")
    except BaseException:
        active = sys.exc_info()[1]
        _close_resources_best_effort((fd,), active)
        raise
    return handle


def _components(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise Gsm8kError("internal relative path is invalid")
    values = tuple(path.split("/"))
    if any(value in {"", ".", ".."} for value in values):
        raise Gsm8kError("internal relative path component is invalid")
    return values


def _open_absolute_dir(path: Path) -> int:
    if not path.is_absolute():
        raise Gsm8kError("data root must be absolute")
    current = os.open("/", _dir_flags())
    try:
        for component in path.parts[1:]:
            following = os.open(component, _dir_flags(), dir_fd=current)
            previous = current
            current = following
            following = -1
            _close_resources_best_effort((previous,))
        result = current
        current = -1
        return result
    finally:
        active = sys.exc_info()[1]
        owned = current
        current = -1
        _close_resources_best_effort((owned,), active)


def _open_relative_chain(root_fd: int, path: str) -> list[int]:
    held: list[int] = []
    current = os.dup(root_fd)
    try:
        for component in _components(path):
            following = os.open(component, _dir_flags(), dir_fd=current)
            held.append(following)
            following = -1
            traversal = os.dup(held[-1])
            previous = current
            current = traversal
            traversal = -1
            _close_resources_best_effort((previous,))
        traversal = current
        current = -1
        _close_resources_best_effort((traversal,))
        result = held
        held = []
        return result
    finally:
        active = sys.exc_info()[1]
        owned_current = current
        current = -1
        owned = tuple(reversed(held))
        held.clear()
        _close_resources_best_effort((owned_current, *owned), active)


def _require_private_directory(fd: int, name: str) -> None:
    value = os.fstat(fd)
    if not stat.S_ISDIR(value.st_mode):
        raise Gsm8kError(f"{name} must be a directory")
    if value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o700:
        raise Gsm8kError(f"{name} must be owned by this user with mode 0700")


def _open_or_create_chain(root_fd: int, path: str) -> list[int]:
    held: list[int] = []
    current = os.dup(root_fd)
    following = -1
    try:
        for component in _components(path):
            following = -1
            try:
                following = os.open(component, _dir_flags(), dir_fd=current)
            except FileNotFoundError:
                _fault("mkdir-enoent", component)
                try:
                    os.mkdir(component, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                else:
                    os.fsync(current)
                following = os.open(component, _dir_flags(), dir_fd=current)
            _require_private_directory(following, f"processed parent {component}")
            held.append(following)
            following = -1
            traversal = os.dup(held[-1])
            previous = current
            current = traversal
            traversal = -1
            _close_resources_best_effort((previous,))
        traversal = current
        current = -1
        _close_resources_best_effort((traversal,))
        result = held
        held = []
        return result
    finally:
        active = sys.exc_info()[1]
        owned_current = current
        owned_following = following
        current = following = -1
        owned = tuple(reversed(held))
        held.clear()
        _close_resources_best_effort(
            (owned_following, owned_current, *owned), active
        )


def _open_relative_regular(root_fd: int, path: str) -> int:
    components = _components(path)
    current = os.dup(root_fd)
    result = -1
    try:
        for component in components[:-1]:
            following = os.open(component, _dir_flags(), dir_fd=current)
            previous = current
            current = following
            following = -1
            _close_resources_best_effort((previous,))
        result = os.open(components[-1], _file_flags(), dir_fd=current)
        parent = current
        current = -1
        _close_resources_best_effort((parent,))
        value = os.fstat(result)
        if not stat.S_ISREG(value.st_mode):
            raise Gsm8kError("fixed file must be regular")
        returned = result
        result = -1
        return returned
    finally:
        active = sys.exc_info()[1]
        owned_result = result
        owned_current = current
        result = current = -1
        _close_resources_best_effort(
            (owned_result, owned_current), active
        )


def _hash_fd(fd: int, limit: Optional[int] = None) -> tuple[str, int]:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(fd, 1_048_576)
        if not chunk:
            break
        size += len(chunk)
        if limit is not None and size > limit:
            raise Gsm8kError("fixed file exceeds its byte limit")
        digest.update(chunk)
    return digest.hexdigest(), size


def _stable_hash_fd(fd: int, limit: Optional[int] = None) -> tuple[str, int, _Fingerprint]:
    before = _fingerprint_fd(fd)
    digest, size = _hash_fd(fd, limit)
    after = _fingerprint_fd(fd)
    if before != after:
        raise Gsm8kError("held file changed while hashing")
    return digest, size, after


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written < 1:
            raise OSError("output write made no progress")
        view = view[written:]


def _raw_record(raw_line: bytes, split: str, line_number: int) -> tuple[str, str]:
    if len(raw_line) > _RAW_LINE_LIMIT:
        raise Gsm8kError(f"{split} line {line_number}: raw line exceeds limit")
    if not raw_line.endswith(b"\n"):
        raise Gsm8kError(f"{split} line {line_number}: raw line lacks LF")
    value = _strict_object(raw_line[:-1], f"{split} line {line_number}: raw record")
    value = _exact_mapping(value, {"question", "answer"}, "raw record")
    question = value["question"]
    answer = value["answer"]
    if not isinstance(question, str) or not question.strip():
        raise Gsm8kError(f"{split} line {line_number}: question is invalid")
    if not isinstance(answer, str) or not answer.strip():
        raise Gsm8kError(f"{split} line {line_number}: answer is invalid")
    return question, answer


def _expected_records(
    raw_line: bytes,
    binding: _SourceBinding,
    line_number: int,
) -> tuple[Gsm8kSourceRecord, TemporalExample]:
    split = binding.official_split
    question, answer = _raw_record(raw_line, split, line_number)
    source_sha256 = hashlib.sha256(raw_line).hexdigest()
    source_id = make_stable_id(
        "source",
        {
            "dataset": "gsm8k",
            "revision": REVISION,
            "official_split": split,
            "relative_path": binding.relative_path,
            "line_number": line_number,
            "source_sha256": source_sha256,
        },
    )
    split_assignment = assign_split(source_id, split)
    source = Gsm8kSourceRecord(
        source_id=source_id,
        dataset="gsm8k",
        revision=REVISION,
        split=split_assignment,
        source_sha256=source_sha256,
        provenance=SourceProvenance(
            relative_path=binding.relative_path,
            line_number=line_number,
            source_file_sha256=binding.sha256,
        ),
        question=question,
        answer=answer,
    )
    answer_parts = parse_gsm8k_answer(answer)
    example = TemporalExample(
        record_id=make_stable_id(
            "record", {"source_id": source_id, "variant": "original"}
        ),
        source_id=source_id,
        dataset="gsm8k",
        split=split_assignment,
        revision=REVISION,
        source_sha256=source_sha256,
        text=question,
        question=question,
        answers=(answer_parts.target,),
        answer_type=AnswerType.NUMERIC,
        events=(),
        relations=(),
        counterfactual_pair_id=None,
    )
    return source, example


def _duplicate_values(
    split: str,
    questions: Counter[str],
    raw_records: Counter[tuple[str, str]],
) -> Mapping[str, int]:
    return {
        f"{split}_question_group_count": sum(
            count > 1 for count in questions.values()
        ),
        f"{split}_question_record_count": sum(
            count for count in questions.values() if count > 1
        ),
        f"{split}_raw_record_group_count": sum(
            count > 1 for count in raw_records.values()
        ),
        f"{split}_raw_record_record_count": sum(
            count for count in raw_records.values() if count > 1
        ),
    }


def _line(handle: Any, limit: int, label: str, line_number: int) -> bytes:
    value = handle.readline(limit + 1)
    if len(value) > limit:
        raise Gsm8kError(f"{label} line {line_number}: line exceeds limit")
    return value


def _verify_split_fds(
    raw_fd: int,
    source_fd: int,
    example_fd: int,
    binding: _SourceBinding,
    source_path: str,
    example_path: str,
) -> _SplitVerification:
    descriptors = (raw_fd, source_fd, example_fd)
    before = tuple(_fingerprint_fd(fd) for fd in descriptors)
    for index, fingerprint in enumerate(before):
        if not stat.S_ISREG(fingerprint.mode) or fingerprint.nlink != 1:
            raise Gsm8kError("lockstep input must be a single-link regular file")
        if index and stat.S_IMODE(fingerprint.mode) != 0o600:
            raise Gsm8kError("processed output must have mode 0600")
    for fd in descriptors:
        os.lseek(fd, 0, os.SEEK_SET)
    raw_digest = hashlib.sha256()
    source_digest = hashlib.sha256()
    example_digest = hashlib.sha256()
    raw_size = source_size = example_size = 0
    questions: Counter[str] = Counter()
    raw_records: Counter[tuple[str, str]] = Counter()
    count = 0
    raw_handle: Optional[BinaryIO] = None
    source_handle: Optional[BinaryIO] = None
    example_handle: Optional[BinaryIO] = None
    try:
        raw_handle = _owned_fdopen(os.dup(raw_fd))
        source_handle = _owned_fdopen(os.dup(source_fd))
        example_handle = _owned_fdopen(os.dup(example_fd))
        while True:
            line_number = count + 1
            raw_line = _line(raw_handle, _RAW_LINE_LIMIT, binding.official_split, line_number)
            source_line = _line(source_handle, _OUTPUT_LINE_LIMIT, "source ledger", line_number)
            example_line = _line(example_handle, _OUTPUT_LINE_LIMIT, "example", line_number)
            if not raw_line and not source_line and not example_line:
                break
            if not raw_line or not source_line or not example_line:
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: lockstep EOF differs"
                )
            if not source_line.endswith(b"\n") or not example_line.endswith(b"\n"):
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: output lacks LF"
                )
            expected_source, expected_example = _expected_records(
                raw_line, binding, line_number
            )
            source_value = _strict_object(
                source_line[:-1], f"source ledger line {line_number}"
            )
            example_value = _strict_object(
                example_line[:-1], f"example line {line_number}"
            )
            try:
                observed_source = Gsm8kSourceRecord.from_dict(source_value)
                observed_example = TemporalExample.from_dict(example_value)
            except (TypeError, ValueError) as error:
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: output schema is invalid"
                ) from error
            if source_line != canonical_json(source_value).encode("utf-8") + b"\n":
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: source is not canonical"
                )
            if example_line != canonical_json(example_value).encode("utf-8") + b"\n":
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: example is not canonical"
                )
            if observed_source != expected_source or observed_example != expected_example:
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: raw replay differs"
                )
            if observed_source.source_id != observed_example.source_id:
                raise Gsm8kError(
                    f"{binding.official_split} line {line_number}: source linkage differs"
                )
            raw_digest.update(raw_line)
            source_digest.update(source_line)
            example_digest.update(example_line)
            raw_size += len(raw_line)
            source_size += len(source_line)
            example_size += len(example_line)
            questions[expected_source.question] += 1
            raw_records[(expected_source.question, expected_source.answer)] += 1
            count += 1
    finally:
        active = sys.exc_info()[1]
        owned = (example_handle, source_handle, raw_handle)
        example_handle = source_handle = raw_handle = None
        _close_resources_best_effort(owned, active)
    after = tuple(_fingerprint_fd(fd) for fd in descriptors)
    if before != after:
        raise Gsm8kError("lockstep input changed while reading")
    if (
        count != binding.record_count
        or raw_size != binding.byte_size
        or raw_digest.hexdigest() != binding.sha256
    ):
        raise Gsm8kError(f"{binding.official_split} fixed source binding differs")
    return _SplitVerification(
        source=_FileFacts(
            source_path,
            source_size,
            count,
            source_digest.hexdigest(),
            after[1],
        ),
        example=_FileFacts(
            example_path,
            example_size,
            count,
            example_digest.hexdigest(),
            after[2],
        ),
        duplicate_values=_duplicate_values(
            binding.official_split, questions, raw_records
        ),
    )


def _inspect_raw_fd(fd: int, binding: _SourceBinding) -> None:
    value = os.fstat(fd)
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise Gsm8kError("fixed raw source must be a single-link regular file")
    before = _fingerprint_fd(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = count = 0
    handle: Optional[BinaryIO] = None
    try:
        handle = _owned_fdopen(os.dup(fd))
        while True:
            raw_line = _line(
                handle, _RAW_LINE_LIMIT, binding.official_split, count + 1
            )
            if not raw_line:
                break
            _, answer = _raw_record(raw_line, binding.official_split, count + 1)
            parse_gsm8k_answer(answer)
            digest.update(raw_line)
            size += len(raw_line)
            count += 1
    finally:
        active = sys.exc_info()[1]
        owned = handle
        handle = None
        _close_resources_best_effort((owned,), active)
    if before != _fingerprint_fd(fd):
        raise Gsm8kError("fixed raw source changed while reading")
    if (
        count != binding.record_count
        or size != binding.byte_size
        or digest.hexdigest() != binding.sha256
    ):
        raise Gsm8kError(f"{binding.official_split} fixed source binding differs")


def _open_source_fds(raw_revision_fd: int, layout: _Layout) -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for split in ("train", "test"):
            result[split] = _open_relative_regular(
                raw_revision_fd, layout.sources[split].relative_path
            )
        return result
    except BaseException:
        active = sys.exc_info()[1]
        owned = tuple(reversed(tuple(result.values())))
        result.clear()
        _close_fds_best_effort(owned, active)
        raise


def _assert_source_bindings(
    raw_revision_fd: int,
    layout: _Layout,
    held_fds: Mapping[str, int],
    baselines: Mapping[str, _Fingerprint],
) -> None:
    if set(held_fds) != {"train", "test"} or set(baselines) != {
        "train",
        "test",
    }:
        raise Gsm8kError("held raw source binding is incomplete")
    for split in ("train", "test"):
        _fault("source-binding", split)
    reopened = _open_source_fds(raw_revision_fd, layout)
    try:
        for split in ("train", "test"):
            if _fingerprint_fd(held_fds[split]) != baselines[split]:
                raise Gsm8kError("held raw source changed")
            if _fingerprint_fd(reopened[split]) != baselines[split]:
                raise Gsm8kError("canonical raw source changed")
    finally:
        active = sys.exc_info()[1]
        owned = tuple(reversed(tuple(reopened.values())))
        reopened.clear()
        _close_fds_best_effort(owned, active)


def _acquisition_values(result: Any) -> Mapping[str, Any]:
    values = result if isinstance(result, Mapping) else getattr(result, "values", result)
    if not isinstance(values, Mapping):
        raise Gsm8kError("acquisition verifier returned an invalid result")
    return values


def _acquisition_gate(
    layout: _Layout,
    data_root_fd: int,
    verifier: Callable[[], Any],
) -> Mapping[str, Any]:
    values = _acquisition_values(verifier())
    required = {
        "status": "COMPLETE",
        "dataset": "gsm8k",
        "revision": REVISION,
        "kairos_git_commit": layout.acquisition.provenance_commit,
        "sha256sums_sha256": layout.acquisition.sha256sums_sha256,
        "formal_tree_fingerprint_sha256": (
            layout.acquisition.formal_tree_fingerprint_sha256
        ),
        "train_path": layout.sources["train"].relative_path,
        "train_count": layout.sources["train"].record_count,
        "test_path": layout.sources["test"].relative_path,
        "test_count": layout.sources["test"].record_count,
    }
    if any(values.get(key) != expected for key, expected in required.items()):
        raise Gsm8kError("acquisition verification differs from D-005")
    completion_fd = _open_relative_regular(
        data_root_fd, layout.acquisition.completion_manifest_path
    )
    canonical_fd = -1
    try:
        digest, _, baseline = _stable_hash_fd(completion_fd, _SMALL_FILE_LIMIT)
        _fault(
            "completion-binding", layout.acquisition.completion_manifest_path
        )
        canonical_fd = _open_relative_regular(
            data_root_fd, layout.acquisition.completion_manifest_path
        )
        if _fingerprint_fd(canonical_fd) != baseline:
            raise Gsm8kError("canonical acquisition completion binding changed")
    finally:
        active = sys.exc_info()[1]
        owned = (canonical_fd, completion_fd)
        canonical_fd = completion_fd = -1
        _close_resources_best_effort(owned, active)
    if digest != layout.acquisition.completion_manifest_sha256:
        raise Gsm8kError("acquisition completion manifest hash differs")
    return values


def _create_temp(
    target_fd: int, label: str, artifact: Optional[str] = None
) -> tuple[str, int]:
    _fault("create", artifact or label)
    name = f".kairos-{label}.{secrets.token_hex(16)}.tmp"
    fd = os.open(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=target_fd,
    )
    return name, fd


def _generate_split_temps(
    target_fd: int,
    raw_fd: int,
    binding: _SourceBinding,
) -> tuple[str, str]:
    source_artifact = _OUTPUT_NAMES[f"source_{binding.official_split}"]
    example_artifact = _OUTPUT_NAMES[f"example_{binding.official_split}"]
    source_temp, source_fd = _create_temp(
        target_fd, f"source-{binding.official_split}", source_artifact
    )
    example_temp = ""
    example_fd = -1
    handle: Optional[BinaryIO] = None
    try:
        example_temp, example_fd = _create_temp(
            target_fd, f"example-{binding.official_split}", example_artifact
        )
        os.lseek(raw_fd, 0, os.SEEK_SET)
        handle = _owned_fdopen(os.dup(raw_fd))
        count = 0
        while True:
            raw_line = _line(
                handle, _RAW_LINE_LIMIT, binding.official_split, count + 1
            )
            if not raw_line:
                break
            source, example = _expected_records(raw_line, binding, count + 1)
            _fault("write", source_artifact)
            _write_all(
                source_fd,
                canonical_json(source.to_dict()).encode("utf-8") + b"\n",
            )
            _fault("write", example_artifact)
            _write_all(
                example_fd,
                canonical_json(example).encode("utf-8") + b"\n",
            )
            count += 1
        _fault("file-fsync", source_artifact)
        os.fsync(source_fd)
        _fault("file-fsync", example_artifact)
        os.fsync(example_fd)
        if stat.S_IMODE(os.fstat(source_fd).st_mode) != 0o600 or stat.S_IMODE(
            os.fstat(example_fd).st_mode
        ) != 0o600:
            raise Gsm8kError("processed temp mode differs")
    finally:
        active = sys.exc_info()[1]
        owned = (
            handle,
            _OwnedResource(example_fd, example_artifact),
            _OwnedResource(source_fd, source_artifact),
        )
        handle = None
        source_fd = example_fd = -1
        _close_resources_best_effort(owned, active)
    return source_temp, example_temp


def _open_named_pair(target_fd: int, source_name: str, example_name: str) -> tuple[int, int]:
    source_fd = example_fd = -1
    try:
        source_fd = _open_relative_regular(target_fd, source_name)
        example_fd = _open_relative_regular(target_fd, example_name)
        result = (source_fd, example_fd)
        source_fd = example_fd = -1
        return result
    except BaseException:
        active = sys.exc_info()[1]
        owned = (example_fd, source_fd)
        source_fd = example_fd = -1
        _close_fds_best_effort(owned, active)
        raise


def _verify_named_split(
    target_fd: int,
    raw_fd: int,
    binding: _SourceBinding,
    source_name: str,
    example_name: str,
    source_artifact: Optional[str] = None,
    example_artifact: Optional[str] = None,
) -> _SplitVerification:
    source_fd, example_fd = _open_named_pair(
        target_fd, source_name, example_name
    )
    try:
        if source_artifact is not None:
            _fault("content", source_artifact)
        if example_artifact is not None:
            _fault("content", example_artifact)
        return _verify_split_fds(
            raw_fd,
            source_fd,
            example_fd,
            binding,
            source_name,
            example_name,
        )
    finally:
        active = sys.exc_info()[1]
        owned = (example_fd, source_fd)
        source_fd = example_fd = -1
        _close_fds_best_effort(owned, active)


def _publish_temp(
    target_fd: int,
    temp: str,
    final: str,
    artifact: Optional[str] = None,
    expected_fingerprint: Optional[_Fingerprint] = None,
) -> _Fingerprint:
    artifact = artifact or final
    _fault("reopen", artifact)
    temp_fd = _open_relative_regular(target_fd, temp)
    final_fd = -1
    try:
        stable = _fingerprint_fd(temp_fd)
        if expected_fingerprint is not None and stable != expected_fingerprint:
            raise Gsm8kError("processed temp changed after content validation")
        if stable.nlink != 1 or stat.S_IMODE(stable.mode) != 0o600:
            raise Gsm8kError("processed temp binding is invalid")
        if _fingerprint_fd(temp_fd) != stable:
            raise Gsm8kError("processed temp changed before publication")
        _fault("publish-before-link", artifact)
        _fault("link", artifact)
        os.link(
            temp,
            final,
            src_dir_fd=target_fd,
            dst_dir_fd=target_fd,
            follow_symlinks=False,
        )
        _fault("publish-after-link", artifact)
        temp_stat = os.stat(temp, dir_fd=target_fd, follow_symlinks=False)
        final_stat = os.stat(final, dir_fd=target_fd, follow_symlinks=False)
        linked = _fingerprint_fd(temp_fd)
        stable_binding = (
            stable.device,
            stable.inode,
            stable.mode,
            stable.size,
            stable.mtime_ns,
        )
        if any(
            (
                value.st_dev,
                value.st_ino,
                stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
                value.st_size,
                value.st_mtime_ns,
            )
            != stable_binding
            for value in (temp_stat, final_stat)
        ) or (
            linked.device,
            linked.inode,
            linked.mode,
            linked.size,
            linked.mtime_ns,
        ) != stable_binding:
            raise Gsm8kError("processed hardlink publication lost its stable binding")
        if temp_stat.st_nlink != 2 or final_stat.st_nlink != 2 or linked.nlink != 2:
            raise Gsm8kError("processed hardlink publication has an invalid link count")
        _fault("publish-before-unlink", artifact)
        _fault("unlink", artifact)
        os.unlink(temp, dir_fd=target_fd)
        _fault("root-fsync", artifact)
        os.fsync(target_fd)
        held_final = _fingerprint_fd(temp_fd)
        if (
            held_final.device,
            held_final.inode,
            held_final.mode,
            held_final.size,
            held_final.mtime_ns,
        ) != stable_binding or held_final.nlink != 1:
            raise Gsm8kError("processed held final binding is invalid")
        final_fd = _open_relative_regular(target_fd, final)
        baseline = _fingerprint_fd(final_fd)
        if baseline != held_final:
            raise Gsm8kError("processed canonical final binding differs")
        if baseline.nlink != 1 or stat.S_IMODE(baseline.mode) != 0o600:
            raise Gsm8kError("processed final binding is invalid")
        return baseline
    finally:
        active = sys.exc_info()[1]
        owned = (final_fd, temp_fd)
        final_fd = temp_fd = -1
        _close_fds_best_effort(owned, active)


def _write_manifest_temp(
    target_fd: int, values: Mapping[str, Any], layout: _Layout
) -> tuple[str, _Fingerprint]:
    content = canonical_json(values).encode("utf-8") + b"\n"
    if len(content) > _SMALL_FILE_LIMIT:
        raise Gsm8kError("processed manifest exceeds its byte limit")
    artifact = _MANIFEST
    name, fd = _create_temp(target_fd, "processed-manifest", artifact)
    try:
        _fault("write", artifact)
        _write_all(fd, content)
        _fault("file-fsync", artifact)
        os.fsync(fd)
    finally:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_resources_best_effort(
            (_OwnedResource(owned, artifact),), active
        )
    _fault("reopen", artifact)
    reopened = _open_relative_regular(target_fd, name)
    try:
        _fault("content", artifact)
        observed = _read_manifest_fd(reopened, layout)
        if observed != values:
            raise Gsm8kError("processed manifest temp differs")
        fingerprint = _fingerprint_fd(reopened)
    finally:
        active = sys.exc_info()[1]
        owned = reopened
        reopened = -1
        _close_resources_best_effort((owned,), active)
    return name, fingerprint


def _read_bounded_fd(fd: int, limit: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    result = bytearray()
    while True:
        chunk = os.read(fd, min(65_536, limit + 1 - len(result)))
        if not chunk:
            break
        result.extend(chunk)
        if len(result) > limit:
            raise Gsm8kError("processed manifest exceeds its byte limit")
    return bytes(result)


def _strict_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Gsm8kError(f"{name} must be a non-negative integer")
    return value


def _strict_hex(value: Any, length: int, name: str) -> str:
    pattern = _HEX40 if length == 40 else _HEX64
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Gsm8kError(f"{name} must be lowercase hexadecimal")
    return value


def _validate_manifest(value: Mapping[str, Any], layout: _Layout) -> Mapping[str, Any]:
    value = _exact_mapping(
        value,
        {
            "status",
            "schema_version",
            "dataset",
            "revision",
            "acquisition",
            "adapter",
            "sources",
            "outputs",
            "duplicates",
        },
        "processed manifest",
    )
    literals = {
        "status": "COMPLETE",
        "schema_version": "kairos-gsm8k-processed-v1",
        "dataset": "gsm8k",
        "revision": REVISION,
    }
    if any(value[key] != expected for key, expected in literals.items()):
        raise Gsm8kError("processed manifest literal differs")
    acquisition_value = _exact_mapping(
        value["acquisition"],
        {
            "provenance_commit",
            "completion_manifest_path",
            "completion_manifest_sha256",
            "sha256sums_sha256",
            "formal_tree_fingerprint_sha256",
        },
        "manifest acquisition",
    )
    expected_acquisition = {
        "provenance_commit": layout.acquisition.provenance_commit,
        "completion_manifest_path": layout.acquisition.completion_manifest_path,
        "completion_manifest_sha256": layout.acquisition.completion_manifest_sha256,
        "sha256sums_sha256": layout.acquisition.sha256sums_sha256,
        "formal_tree_fingerprint_sha256": (
            layout.acquisition.formal_tree_fingerprint_sha256
        ),
    }
    if acquisition_value != expected_acquisition:
        raise Gsm8kError("processed manifest acquisition binding differs")
    adapter = _exact_mapping(
        value["adapter"],
        {
            "git_commit",
            "source_record_schema_version",
            "temporal_example_schema_version",
            "id_version",
            "split_version",
            "answer_parser_version",
        },
        "manifest adapter",
    )
    _strict_hex(adapter["git_commit"], 40, "adapter commit")
    adapter_literals = {
        "source_record_schema_version": "kairos-gsm8k-source-record-v1",
        "temporal_example_schema_version": "kairos-temporal-example-v1",
        "id_version": "kairos-stable-id-v1",
        "split_version": "sha256-first8-mod10-v1",
        "answer_parser_version": "gsm8k-single-delimiter-ascii-trim-v1",
    }
    if any(adapter[key] != expected for key, expected in adapter_literals.items()):
        raise Gsm8kError("processed manifest adapter version differs")
    sources = _exact_mapping(value["sources"], {"train", "test"}, "manifest sources")
    for split in ("train", "test"):
        source = _exact_mapping(
            sources[split],
            {"official_split", "relative_path", "sha256", "byte_size", "record_count"},
            f"manifest source {split}",
        )
        binding = layout.sources[split]
        if (
            source.get("official_split") != binding.official_split
            or source.get("relative_path") != binding.relative_path
            or source.get("sha256") != binding.sha256
            or _strict_nonnegative_int(source.get("byte_size"), "source byte_size")
            != binding.byte_size
            or _strict_nonnegative_int(source.get("record_count"), "source count")
            != binding.record_count
        ):
            raise Gsm8kError(f"processed manifest {split} source differs")
    outputs = _exact_mapping(
        value["outputs"], set(_OUTPUT_NAMES), "manifest outputs"
    )
    expected_counts = {
        "source_train": layout.sources["train"].record_count,
        "example_train": layout.sources["train"].record_count,
        "source_test": layout.sources["test"].record_count,
        "example_test": layout.sources["test"].record_count,
    }
    for key, expected_path in _OUTPUT_NAMES.items():
        output = _exact_mapping(
            outputs[key], {"path", "byte_size", "record_count", "sha256"}, f"manifest output {key}"
        )
        if output.get("path") != expected_path:
            raise Gsm8kError(f"processed manifest {key} path differs")
        _strict_nonnegative_int(output.get("byte_size"), "output byte_size")
        if (
            _strict_nonnegative_int(output.get("record_count"), "output count")
            != expected_counts[key]
        ):
            raise Gsm8kError(f"processed manifest {key} count differs")
        _strict_hex(output.get("sha256"), 64, "output SHA256")
    duplicate_keys = {
        f"{split}_{kind}_{measure}"
        for split in ("train", "test")
        for kind in ("question", "raw_record")
        for measure in ("group_count", "record_count")
    }
    duplicates = _exact_mapping(
        value["duplicates"], duplicate_keys, "manifest duplicates"
    )
    for key in duplicate_keys:
        _strict_nonnegative_int(duplicates[key], f"duplicate {key}")
    return value


def _read_manifest_fd(fd: int, layout: Optional[_Layout]) -> Mapping[str, Any]:
    before = _fingerprint_fd(fd)
    if not stat.S_ISREG(before.mode) or before.nlink != 1 or stat.S_IMODE(before.mode) != 0o600:
        raise Gsm8kError("processed manifest must be a 0600 single-link regular file")
    content = _read_bounded_fd(fd, _SMALL_FILE_LIMIT)
    if before != _fingerprint_fd(fd):
        raise Gsm8kError("processed manifest changed while reading")
    if not content.endswith(b"\n") or content.count(b"\n") != 1:
        raise Gsm8kError("processed manifest must be one LF-terminated object")
    value = _strict_object(content[:-1], "processed manifest")
    if content != canonical_json(value).encode("utf-8") + b"\n":
        raise Gsm8kError("processed manifest is not canonical")
    return _validate_manifest(value, layout or _PRODUCTION_LAYOUT)


def _manifest_values(
    layout: _Layout,
    adapter_commit: str,
    verification: _OutputVerification,
) -> Mapping[str, Any]:
    return {
        "status": "COMPLETE",
        "schema_version": "kairos-gsm8k-processed-v1",
        "dataset": "gsm8k",
        "revision": REVISION,
        "acquisition": {
            "provenance_commit": layout.acquisition.provenance_commit,
            "completion_manifest_path": layout.acquisition.completion_manifest_path,
            "completion_manifest_sha256": layout.acquisition.completion_manifest_sha256,
            "sha256sums_sha256": layout.acquisition.sha256sums_sha256,
            "formal_tree_fingerprint_sha256": layout.acquisition.formal_tree_fingerprint_sha256,
        },
        "adapter": {
            "git_commit": adapter_commit,
            "source_record_schema_version": "kairos-gsm8k-source-record-v1",
            "temporal_example_schema_version": "kairos-temporal-example-v1",
            "id_version": "kairos-stable-id-v1",
            "split_version": "sha256-first8-mod10-v1",
            "answer_parser_version": "gsm8k-single-delimiter-ascii-trim-v1",
        },
        "sources": {
            split: {
                "official_split": binding.official_split,
                "relative_path": binding.relative_path,
                "sha256": binding.sha256,
                "byte_size": binding.byte_size,
                "record_count": binding.record_count,
            }
            for split, binding in layout.sources.items()
        },
        "outputs": {
            key: {
                "path": facts.path,
                "byte_size": facts.byte_size,
                "record_count": facts.record_count,
                "sha256": facts.sha256,
            }
            for key, facts in verification.outputs.items()
        },
        "duplicates": dict(verification.duplicates),
    }


def _scan_target(target_fd: int, require_manifest: bool) -> Mapping[str, _Fingerprint]:
    expected = _FINAL_NAMES if require_manifest else frozenset(_OUTPUT_NAMES.values())
    result: dict[str, _Fingerprint] = {}
    entries = os.scandir(target_fd)
    try:
        for entry in entries:
            if entry.name not in expected or entry.name in result:
                raise Gsm8kError("processed target contains an unexpected entry")
            value = entry.stat(follow_symlinks=False)
            fingerprint = _Fingerprint(
                value.st_dev,
                value.st_ino,
                stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            if (
                not stat.S_ISREG(fingerprint.mode)
                or stat.S_IMODE(fingerprint.mode) != 0o600
                or fingerprint.nlink != 1
            ):
                raise Gsm8kError("processed target entry binding is invalid")
            result[entry.name] = fingerprint
    finally:
        active = sys.exc_info()[1]
        owned = entries
        entries = None
        _close_resources_best_effort((owned,), active)
    if set(result) != set(expected):
        raise Gsm8kError("processed target file set is incomplete")
    inodes = {(value.device, value.inode) for value in result.values()}
    if len(inodes) != len(result):
        raise Gsm8kError("processed target contains an unknown hardlink")
    return result


def _verify_outputs(
    layout: _Layout,
    target_fd: int,
    source_fds: Mapping[str, int],
) -> _OutputVerification:
    outputs: dict[str, _FileFacts] = {}
    duplicates: dict[str, int] = {}
    for split in ("train", "test"):
        result = _verify_named_split(
            target_fd,
            source_fds[split],
            layout.sources[split],
            _OUTPUT_NAMES[f"source_{split}"],
            _OUTPUT_NAMES[f"example_{split}"],
        )
        outputs[f"source_{split}"] = result.source
        outputs[f"example_{split}"] = result.example
        duplicates.update(result.duplicate_values)
    return _OutputVerification(outputs, duplicates)


def _binding_baselines(fds: Sequence[int]) -> tuple[_Fingerprint, ...]:
    return tuple(_fingerprint_fd(fd) for fd in fds)


def _assert_root_binding(
    layout: _Layout, root_fd: int, baseline: _Fingerprint
) -> None:
    if _fingerprint_fd(root_fd) != baseline:
        raise Gsm8kError("held data root changed")
    canonical = _open_absolute_dir(layout.data_root)
    try:
        if _fingerprint_fd(canonical) != baseline:
            raise Gsm8kError("canonical data root changed")
    finally:
        active = sys.exc_info()[1]
        owned = canonical
        canonical = -1
        _close_resources_best_effort((owned,), active)


def _assert_chain_binding(
    root_fd: int,
    relative_path: str,
    held_fds: Sequence[int],
    baselines: Sequence[_Fingerprint],
) -> None:
    if len(held_fds) != len(baselines):
        raise Gsm8kError("held directory binding is incomplete")
    if _binding_baselines(held_fds) != tuple(baselines):
        raise Gsm8kError("held directory chain changed")
    reopened = _open_relative_chain(root_fd, relative_path)
    try:
        if _binding_baselines(reopened) != tuple(baselines):
            raise Gsm8kError("canonical directory chain changed")
    finally:
        active = sys.exc_info()[1]
        owned = tuple(reversed(reopened))
        reopened.clear()
        _close_fds_best_effort(owned, active)


def _terminal_target_binding(
    layout: _Layout,
    data_root_fd: int,
    target_parent_fd: int,
    target_parent_chain: Sequence[int],
    parent_baselines: Sequence[_Fingerprint],
    target_fd: int,
    target_baseline: _Fingerprint,
    tree_baseline: Mapping[str, _Fingerprint],
) -> None:
    _fault("terminal-held", layout.target_leaf)
    if _fingerprint_fd(target_fd) != target_baseline or _scan_target(
        target_fd, True
    ) != tree_baseline:
        raise Gsm8kError("held processed target changed")
    _fault("terminal-parent", layout.target_leaf)
    _assert_chain_binding(
        data_root_fd,
        layout.target_parent_rel,
        target_parent_chain,
        parent_baselines,
    )
    canonical_target = -1
    try:
        _fault("terminal-canonical-open", layout.target_leaf)
        canonical_target = os.open(
            layout.target_leaf, _dir_flags(), dir_fd=target_parent_fd
        )
        _fault("terminal-canonical-tree", layout.target_leaf)
        if _fingerprint_fd(canonical_target) != target_baseline or _scan_target(
            canonical_target, True
        ) != tree_baseline:
            raise Gsm8kError("canonical processed target changed")
        _fault("terminal-final-parent", layout.target_leaf)
        _assert_chain_binding(
            data_root_fd,
            layout.target_parent_rel,
            target_parent_chain,
            parent_baselines,
        )
    finally:
        active = sys.exc_info()[1]
        owned = canonical_target
        canonical_target = -1
        _close_resources_best_effort((owned,), active)


def _verify_layout(
    layout: _Layout,
    verifier: Callable[[], Any],
) -> Mapping[str, Any]:
    data_root_fd = -1
    raw_chain: list[int] = []
    target_parent_chain: list[int] = []
    source_fds: dict[str, int] = {}
    target_fd = manifest_fd = -1
    try:
        data_root_fd = _open_absolute_dir(layout.data_root)
        raw_chain = _open_relative_chain(data_root_fd, layout.raw_revision_rel)
        raw_revision_fd = raw_chain[-1]
        _require_private_directory(raw_revision_fd, "raw revision")
        data_root_baseline = _fingerprint_fd(data_root_fd)
        raw_baselines = _binding_baselines(raw_chain)
        _acquisition_gate(layout, data_root_fd, verifier)
        source_fds = _open_source_fds(raw_revision_fd, layout)
        source_baselines = {
            split: _fingerprint_fd(fd) for split, fd in source_fds.items()
        }
        target_parent_chain = _open_relative_chain(
            data_root_fd, layout.target_parent_rel
        )
        target_parent_fd = target_parent_chain[-1]
        target_fd = os.open(layout.target_leaf, _dir_flags(), dir_fd=target_parent_fd)
        _require_private_directory(target_fd, "processed target")
        parent_baselines = _binding_baselines(target_parent_chain)
        target_baseline = _fingerprint_fd(target_fd)
        tree_baseline = _scan_target(target_fd, True)
        manifest_fd = _open_relative_regular(target_fd, _MANIFEST)
        manifest = _read_manifest_fd(manifest_fd, layout)
        verification = _verify_outputs(layout, target_fd, source_fds)
        expected_manifest = _manifest_values(
            layout, manifest["adapter"]["git_commit"], verification
        )
        if manifest != expected_manifest:
            raise Gsm8kError("processed manifest differs from replayed outputs")
        _acquisition_gate(layout, data_root_fd, verifier)
        _assert_source_bindings(
            raw_revision_fd, layout, source_fds, source_baselines
        )
        _assert_chain_binding(
            data_root_fd,
            layout.raw_revision_rel,
            raw_chain,
            raw_baselines,
        )
        _assert_root_binding(layout, data_root_fd, data_root_baseline)
        _terminal_target_binding(
            layout,
            data_root_fd,
            target_parent_fd,
            target_parent_chain,
            parent_baselines,
            target_fd,
            target_baseline,
            tree_baseline,
        )
        return manifest
    finally:
        active = sys.exc_info()[1]
        owned = [manifest_fd, target_fd]
        owned.extend(reversed(tuple(source_fds.values())))
        owned.extend(reversed(target_parent_chain))
        owned.extend(reversed(raw_chain))
        owned.append(data_root_fd)
        manifest_fd = target_fd = data_root_fd = -1
        target_parent_chain.clear()
        raw_chain.clear()
        source_fds.clear()
        _close_fds_best_effort(tuple(owned), active)


def _prepare_layout(
    layout: _Layout,
    adapter_commit: str,
    verifier: Callable[[], Any],
) -> Mapping[str, Any]:
    if not isinstance(adapter_commit, str) or not _HEX40.fullmatch(adapter_commit):
        raise Gsm8kError("adapter commit must be 40 lowercase hexadecimal characters")
    data_root_fd = target_fd = -1
    raw_chain: list[int] = []
    target_parent_chain: list[int] = []
    raw_source_fds: dict[str, int] = {}
    try:
        data_root_fd = _open_absolute_dir(layout.data_root)
        raw_chain = _open_relative_chain(data_root_fd, layout.raw_revision_rel)
        raw_revision_fd = raw_chain[-1]
        _require_private_directory(raw_revision_fd, "raw revision")
        _acquisition_gate(layout, data_root_fd, verifier)
        raw_source_fds = _open_source_fds(raw_revision_fd, layout)
        for split in ("train", "test"):
            _inspect_raw_fd(raw_source_fds[split], layout.sources[split])
        target_parent_chain = _open_or_create_chain(
            data_root_fd, layout.target_parent_rel
        )
        target_parent_fd = target_parent_chain[-1]
        os.mkdir(layout.target_leaf, 0o700, dir_fd=target_parent_fd)
        os.fsync(target_parent_fd)
        target_fd = os.open(layout.target_leaf, _dir_flags(), dir_fd=target_parent_fd)
        _require_private_directory(target_fd, "processed target")
        data_root_baseline = _fingerprint_fd(data_root_fd)
        raw_baselines = _binding_baselines(raw_chain)
        source_baselines = {
            split: _fingerprint_fd(fd) for split, fd in raw_source_fds.items()
        }
        parent_baselines = _binding_baselines(target_parent_chain)
        published_baselines: dict[str, _Fingerprint] = {}
        for split in ("train", "test"):
            source_temp, example_temp = _generate_split_temps(
                target_fd, raw_source_fds[split], layout.sources[split]
            )
            temp_verification = _verify_named_split(
                target_fd,
                raw_source_fds[split],
                layout.sources[split],
                source_temp,
                example_temp,
                _OUTPUT_NAMES[f"source_{split}"],
                _OUTPUT_NAMES[f"example_{split}"],
            )
            published_baselines[_OUTPUT_NAMES[f"source_{split}"]] = _publish_temp(
                target_fd,
                source_temp,
                _OUTPUT_NAMES[f"source_{split}"],
                expected_fingerprint=temp_verification.source.fingerprint,
            )
            published_baselines[_OUTPUT_NAMES[f"example_{split}"]] = _publish_temp(
                target_fd,
                example_temp,
                _OUTPUT_NAMES[f"example_{split}"],
                expected_fingerprint=temp_verification.example.fingerprint,
            )
        verification = _verify_outputs(layout, target_fd, raw_source_fds)
        _acquisition_gate(layout, data_root_fd, verifier)
        _assert_source_bindings(
            raw_revision_fd, layout, raw_source_fds, source_baselines
        )
        manifest_values = _manifest_values(layout, adapter_commit, verification)
        _validate_manifest(manifest_values, layout)
        manifest_temp, manifest_fingerprint = _write_manifest_temp(
            target_fd, manifest_values, layout
        )
        published_baselines[_MANIFEST] = _publish_temp(
            target_fd,
            manifest_temp,
            _MANIFEST,
            expected_fingerprint=manifest_fingerprint,
        )
        target_baseline = _fingerprint_fd(target_fd)
        tree_baseline = _scan_target(target_fd, True)
        if tree_baseline != published_baselines:
            raise Gsm8kError("processed final baseline differs after publication")
        result = _verify_layout(layout, verifier)
        _assert_root_binding(layout, data_root_fd, data_root_baseline)
        _assert_chain_binding(
            data_root_fd,
            layout.raw_revision_rel,
            raw_chain,
            raw_baselines,
        )
        _terminal_target_binding(
            layout,
            data_root_fd,
            target_parent_fd,
            target_parent_chain,
            parent_baselines,
            target_fd,
            target_baseline,
            tree_baseline,
        )
        return result
    finally:
        active = sys.exc_info()[1]
        owned = [target_fd]
        owned.extend(reversed(tuple(raw_source_fds.values())))
        owned.extend(reversed(target_parent_chain))
        owned.extend(reversed(raw_chain))
        owned.append(data_root_fd)
        target_fd = data_root_fd = -1
        target_parent_chain.clear()
        raw_chain.clear()
        raw_source_fds.clear()
        _close_fds_best_effort(tuple(owned), active)


def _production_verifier() -> Any:
    return acquisition.verify_complete()


def prepare(adapter_commit: str) -> Mapping[str, Any]:
    return _prepare_layout(_PRODUCTION_LAYOUT, adapter_commit, _production_verifier)


def verify() -> Mapping[str, Any]:
    return _verify_layout(_PRODUCTION_LAYOUT, _production_verifier)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kairos.gsm8k")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--adapter-commit", required=True)
    commands.add_parser("verify")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            result = prepare(arguments.adapter_commit)
        else:
            result = verify()
    except (
        Gsm8kError,
        acquisition.AcquisitionError,
        ArchiveSafetyError,
        FileExistsError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ) as error:
        print(f"GSM8K adapter failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "Gsm8kAnswerParts",
    "Gsm8kError",
    "Gsm8kSourceRecord",
    "main",
    "parse_gsm8k_answer",
    "prepare",
    "verify",
]
