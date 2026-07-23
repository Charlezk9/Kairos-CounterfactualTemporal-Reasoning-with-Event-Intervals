"""Immutable train-only artifacts for GSM8K relation supervision.

The official test split is intentionally absent from this module's public and
private interfaces.  Verification reconstructs the complete train stream from
the fixed processed source and compares canonical bytes; it never trusts the
stored aggregate counts alone.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Mapping, Sequence

from . import construction_audit_persistence as source_binding
from .ids import canonical_json
from .relation_supervision import (
    CONSTRUCTION_VERSION,
    SCHEMA_VERSION,
    CounterfactualAnswerStatus,
    RelationOnlyPair,
    RelationOnlyTerminal,
    RelationSupervisionError,
    construct_gsm8k_relation_only,
)


REVISION = source_binding.REVISION
ARTIFACT_ID = "PROC-P01-GSM8K-RELATION-ONLY-V1-20260723"
MANIFEST_SCHEMA_VERSION = "gsm8k-relation-supervision-manifest-v1"
PUBLISHER_VERSION = "gsm8k-relation-supervision-artifacts-v1"
_TARGET_PARENT_REL = (
    f"data/processed/gsm8k/{REVISION}/relation-supervision-v1/"
    f"{CONSTRUCTION_VERSION}"
)
_PAIR_NAME = "relation-supervision.jsonl"
_MANIFEST_NAME = "relation-supervision-manifest.json"
_PAIR_LINE_LIMIT = 1_048_576
_PAIR_TOTAL_LIMIT = 67_108_864
_MANIFEST_LIMIT = 1_048_576
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


class RelationSupervisionArtifactError(ValueError):
    """A source, publication, or offline-replay invariant failed."""


class ObserverState(str, Enum):
    ABSENT = "ABSENT"
    PARTIAL_NO_MANIFEST = "PARTIAL_NO_MANIFEST"
    STRUCTURALLY_VERIFIED = "STRUCTURALLY_VERIFIED"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True)
class _Layout:
    source_layout: source_binding._Layout
    target_parent_rel: str


@dataclass(frozen=True)
class _Derived:
    payload: bytes
    terminal_counts: Mapping[str, int]
    identities: Mapping[str, int]
    maximum_line_bytes: int
    source_facts: source_binding._SourceFacts
    license_sha256: str


_PRODUCTION_SOURCE_LAYOUT = replace(
    source_binding._PRODUCTION_LAYOUT,
    splits={"train": source_binding._PRODUCTION_LAYOUT.splits["train"]},
)
_PRODUCTION_LAYOUT = _Layout(
    source_layout=_PRODUCTION_SOURCE_LAYOUT,
    target_parent_rel=_TARGET_PARENT_REL,
)


def _fail(message: str) -> None:
    raise RelationSupervisionArtifactError(message) from None


def _validate_execution_commit(value: str) -> None:
    if not isinstance(value, str) or not _HEX40.fullmatch(value):
        _fail("execution commit must be lowercase 40-hex")


def _git_gate(layout: _Layout, execution_commit: str) -> None:
    _validate_execution_commit(execution_commit)
    try:
        source_binding._git_gate(layout.source_layout, execution_commit)
    except source_binding.ConstructionAuditPersistenceError:
        _fail("Git provenance gate failed")


def _publication_source_layout(layout: _Layout) -> source_binding._Layout:
    return replace(
        layout.source_layout,
        target_parent_rel=layout.target_parent_rel,
        splits={"train": layout.source_layout.splits["train"]},
    )


def _target_path(layout: _Layout) -> Path:
    return layout.source_layout.data_root / layout.target_parent_rel / "train"


def _create_target(layout: _Layout) -> Path:
    publication_layout = _publication_source_layout(layout)
    try:
        return source_binding._create_target(publication_layout, "train")
    except source_binding.ConstructionAuditPersistenceError:
        if _target_path(layout).exists() or _target_path(layout).is_symlink():
            _fail("relation supervision publication target already exists")
        _fail("relation supervision publication blocked partial")


def _publish_bytes(target: Path, final_name: str, payload: bytes) -> None:
    try:
        source_binding._publish_bytes(target, final_name, payload)
    except source_binding.ConstructionAuditPersistenceError:
        _fail("relation supervision publication blocked partial")


def _stable_binding(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_file_at(directory_fd: int, name: str, limit: int) -> bytes:
    fd = -1
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > limit
        ):
            _fail("relation supervision target file binding is invalid")
        payload = bytearray()
        while True:
            block = os.read(fd, min(1 << 20, limit - len(payload) + 1))
            if not block:
                break
            payload.extend(block)
            if len(payload) > limit:
                _fail("relation supervision target file exceeds its limit")
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            _stable_binding(before) != _stable_binding(after)
            or before.st_dev != named.st_dev
            or before.st_ino != named.st_ino
            or _stable_binding(after) != _stable_binding(named)
            or len(payload) != after.st_size
        ):
            _fail("relation supervision target changed while reading")
        return bytes(payload)
    except RelationSupervisionArtifactError:
        raise
    except (FileNotFoundError, PermissionError, OSError):
        _fail("relation supervision target cannot be read")
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


def _read_complete_target(layout: _Layout) -> tuple[bytes, bytes]:
    target = _target_path(layout)
    try:
        checked = source_binding._checked_path(
            layout.source_layout,
            f"{layout.target_parent_rel}/train",
            regular=False,
        )
    except source_binding.ConstructionAuditPersistenceError:
        _fail("relation supervision target binding is invalid")
    try:
        path_info = checked.lstat()
        if stat.S_IMODE(path_info.st_mode) != 0o700:
            _fail("relation supervision target directory mode is invalid")
        directory_fd = os.open(
            checked, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
    except RelationSupervisionArtifactError:
        raise
    except (FileNotFoundError, PermissionError, OSError):
        _fail("relation supervision target cannot be opened")
    try:
        before = os.fstat(directory_fd)
        if before.st_dev != path_info.st_dev or before.st_ino != path_info.st_ino:
            _fail("relation supervision target directory changed")
        expected_names = {_PAIR_NAME, _MANIFEST_NAME}
        if set(os.listdir(directory_fd)) != expected_names:
            _fail("relation supervision target namespace differs")
        pairs = _read_file_at(directory_fd, _PAIR_NAME, _PAIR_TOTAL_LIMIT)
        manifest = _read_file_at(directory_fd, _MANIFEST_NAME, _MANIFEST_LIMIT)
        after = os.fstat(directory_fd)
        named = target.lstat()
        if (
            set(os.listdir(directory_fd)) != expected_names
            or _stable_binding(before) != _stable_binding(after)
            or before.st_dev != named.st_dev
            or before.st_ino != named.st_ino
        ):
            _fail("relation supervision target changed while reading")
        return pairs, manifest
    except RelationSupervisionArtifactError:
        raise
    except (FileNotFoundError, PermissionError, OSError):
        _fail("relation supervision target cannot be read")
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _derive_expected(layout: _Layout) -> _Derived:
    try:
        facts, license_sha256 = source_binding._source_gate(
            layout.source_layout, "train"
        )
        source_path = source_binding._checked_path(
            layout.source_layout, facts.path, regular=True
        )
        terminals: Counter[str] = Counter()
        pair_ids: set[str] = set()
        original_ids: set[str] = set()
        counterfactual_ids: set[str] = set()
        source_ids: set[str] = set()
        payload = bytearray()
        maximum = 0
        with source_path.open("rb") as source:
            for index in range(facts.record_count):
                line = source_binding._read_source_line(
                    source, source_binding._LINE_PHYSICAL_LIMIT, index + 1
                )
                if not line:
                    _fail("processed train source ended before its bound count")
                example = source_binding._source_example(line, index + 1)
                if example.split.official != "train":
                    _fail("processed train source contains another official split")
                result = construct_gsm8k_relation_only(example)
                terminals[result.terminal.value] += 1
                if result.terminal is not RelationOnlyTerminal.RETAINED:
                    continue
                pair = result.pair
                if pair is None:
                    _fail("retained relation supervision result lacks a pair")
                if (
                    pair.pair_id in pair_ids
                    or pair.original_record_id in original_ids
                    or pair.counterfactual_record_id in counterfactual_ids
                    or pair.source_id in source_ids
                ):
                    _fail("relation supervision identity is duplicated")
                pair_ids.add(pair.pair_id)
                original_ids.add(pair.original_record_id)
                counterfactual_ids.add(pair.counterfactual_record_id)
                source_ids.add(pair.source_id)
                encoded = canonical_json(pair.to_dict()).encode("utf-8") + b"\n"
                if len(encoded) > _PAIR_LINE_LIMIT:
                    _fail("relation supervision line exceeds its limit")
                if len(payload) + len(encoded) > _PAIR_TOTAL_LIMIT:
                    _fail("relation supervision JSONL exceeds its total limit")
                payload.extend(encoded)
                maximum = max(maximum, len(encoded))
            if source_binding._read_source_line(
                source,
                source_binding._LINE_PHYSICAL_LIMIT,
                facts.record_count + 1,
            ):
                _fail("processed train source exceeds its bound count")
    except RelationSupervisionArtifactError:
        raise
    except (
        source_binding.ConstructionAuditPersistenceError,
        RelationSupervisionError,
        TypeError,
        UnicodeError,
        ValueError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ):
        _fail("bound processed train source failed relation replay")

    terminal_counts = {
        terminal.value: terminals[terminal.value] for terminal in RelationOnlyTerminal
    }
    if sum(terminal_counts.values()) != facts.record_count:
        _fail("relation supervision terminal counts do not cover train source")
    if terminal_counts[RelationOnlyTerminal.RETAINED.value] != len(pair_ids):
        _fail("relation supervision retained count differs from identities")
    return _Derived(
        payload=bytes(payload),
        terminal_counts=terminal_counts,
        identities={
            "pair_id_unique_count": len(pair_ids),
            "original_record_id_unique_count": len(original_ids),
            "counterfactual_record_id_unique_count": len(counterfactual_ids),
            "source_id_unique_count": len(source_ids),
        },
        maximum_line_bytes=maximum,
        source_facts=facts,
        license_sha256=license_sha256,
    )


def _manifest_values(
    layout: _Layout, derived: _Derived, execution_commit: str
) -> Mapping[str, Any]:
    _validate_execution_commit(execution_commit)
    facts = derived.source_facts
    return {
        "status": "COMPLETE",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_id": ARTIFACT_ID,
        "dataset": "gsm8k",
        "revision": REVISION,
        "official_split": "train",
        "source": {
            "processed_artifact_id": source_binding._ARTIFACT_ID,
            "processed_manifest_path": layout.source_layout.source_manifest_rel,
            "processed_manifest_sha256": layout.source_layout.source_manifest_sha256,
            "example_path": facts.path,
            "example_sha256": facts.sha256,
            "example_byte_size": facts.byte_size,
            "example_record_count": facts.record_count,
            "license_path": layout.source_layout.license_rel,
            "license_sha256": derived.license_sha256,
            "license_spdx_id": "MIT",
        },
        "publisher": {
            "version": PUBLISHER_VERSION,
            "execution_commit": execution_commit,
            "pair_schema_version": SCHEMA_VERSION,
            "construction_version": CONSTRUCTION_VERSION,
            "canonical_json_version": "kairos-canonical-json-v1",
            "ordering": "processed-train-source-order-retained-only-v1",
        },
        "supervision": {
            "original_answer_available": True,
            "counterfactual_answer_available": False,
            "counterfactual_answer_status": CounterfactualAnswerStatus.UNAVAILABLE.value,
            "original_relation_available": True,
            "counterfactual_relation_available": True,
            "counterfactual_answer_loss_masked": True,
        },
        "terminal_counts": dict(derived.terminal_counts),
        "identity": dict(derived.identities),
        "output": {
            "path": _PAIR_NAME,
            "sha256": hashlib.sha256(derived.payload).hexdigest(),
            "byte_size": len(derived.payload),
            "record_count": derived.identities["pair_id_unique_count"],
            "maximum_line_byte_size": derived.maximum_line_bytes,
        },
    }


def _parse_manifest(payload: bytes) -> Mapping[str, Any]:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        _fail("relation supervision manifest must be one LF-terminated object")
    try:
        value = source_binding._strict_json_object(
            payload[:-1], "relation supervision manifest"
        )
    except source_binding.ConstructionAuditPersistenceError:
        _fail("relation supervision manifest is not strict JSON")
    if canonical_json(value).encode("utf-8") + b"\n" != payload:
        _fail("relation supervision manifest is not canonical")
    return value


def _verify_layout(layout: _Layout) -> Mapping[str, Any]:
    derived = _derive_expected(layout)
    pair_payload, manifest_payload = _read_complete_target(layout)
    manifest = _parse_manifest(manifest_payload)
    try:
        execution_commit = manifest["publisher"]["execution_commit"]
    except (KeyError, TypeError):
        _fail("relation supervision manifest lacks execution provenance")
    expected_manifest = _manifest_values(layout, derived, execution_commit)
    if manifest != expected_manifest:
        _fail("relation supervision manifest differs from full replay")
    if pair_payload != derived.payload:
        _fail("relation supervision JSONL differs from full replay")
    return {
        "observer_state": ObserverState.STRUCTURALLY_VERIFIED.value,
        "target": str(_target_path(layout)),
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "manifest": manifest,
    }


def _observe_layout(layout: _Layout) -> ObserverState:
    target = _target_path(layout)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return ObserverState.ABSENT
    except (PermissionError, OSError):
        return ObserverState.CORRUPT
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return ObserverState.CORRUPT
    try:
        names = {entry.name for entry in os.scandir(target)}
    except (PermissionError, OSError):
        return ObserverState.CORRUPT
    if _MANIFEST_NAME not in names:
        return ObserverState.PARTIAL_NO_MANIFEST
    try:
        _verify_layout(layout)
    except RelationSupervisionArtifactError:
        return ObserverState.CORRUPT
    return ObserverState.STRUCTURALLY_VERIFIED


def _publish_layout(
    layout: _Layout,
    execution_commit: str,
    git_gate: Callable[[_Layout, str], None] = _git_gate,
) -> Mapping[str, Any]:
    _validate_execution_commit(execution_commit)
    git_gate(layout, execution_commit)
    derived = _derive_expected(layout)
    git_gate(layout, execution_commit)
    target = _create_target(layout)
    _publish_bytes(target, _PAIR_NAME, derived.payload)
    git_gate(layout, execution_commit)
    manifest = _manifest_values(layout, derived, execution_commit)
    manifest_payload = canonical_json(manifest).encode("utf-8") + b"\n"
    if len(manifest_payload) > _MANIFEST_LIMIT:
        _fail("relation supervision manifest exceeds its limit")
    _publish_bytes(target, _MANIFEST_NAME, manifest_payload)
    verified = _verify_layout(layout)
    git_gate(layout, execution_commit)
    return verified


def publish(execution_commit: str) -> Mapping[str, Any]:
    """Publish the one fixed official-train relation-supervision artifact."""

    return _publish_layout(_PRODUCTION_LAYOUT, execution_commit)


def verify() -> Mapping[str, Any]:
    """Replay the fixed official-train source and verify canonical output."""

    return _verify_layout(_PRODUCTION_LAYOUT)


def observe() -> ObserverState:
    """Classify the fixed publication without mutating or repairing it."""

    return _observe_layout(_PRODUCTION_LAYOUT)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish or verify fixed GSM8K train relation supervision"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--execution-commit", required=True)
    commands.add_parser("verify")
    commands.add_parser("observe")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "publish":
            result: Any = publish(arguments.execution_commit)
        elif arguments.command == "verify":
            result = verify()
        else:
            result = {"observer_state": observe().value}
    except RelationSupervisionArtifactError as error:
        print(f"relation supervision artifact failed: {error}", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "ARTIFACT_ID",
    "MANIFEST_SCHEMA_VERSION",
    "ObserverState",
    "PUBLISHER_VERSION",
    "RelationSupervisionArtifactError",
    "observe",
    "publish",
    "verify",
)
