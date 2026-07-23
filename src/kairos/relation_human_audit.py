"""Deterministic blinded human-audit packets for relation-only train data."""

from __future__ import annotations

import argparse
from collections import defaultdict
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
from . import relation_supervision_artifacts as relation_artifacts
from .ids import canonical_json, make_stable_id
from .relation_supervision import RelationOnlyPair, RelationSupervisionError


AUDIT_ARTIFACT_ID = "AUDIT-P01-GSM8K-RELATION-ONLY-200-20260723"
AUDIT_ITEM_SCHEMA_VERSION = "gsm8k-relation-human-audit-item-v1"
REVIEW_SCHEMA_VERSION = "gsm8k-relation-human-review-v1"
MANIFEST_SCHEMA_VERSION = "gsm8k-relation-human-audit-manifest-v1"
SAMPLING_VERSION = "stratified-hamilton-sha256-rank-v1"
SAMPLING_SEED = 20_260_723
SAMPLE_SIZE = 200
_TARGET_PARENT_REL = (
    f"data/processed/gsm8k/{relation_artifacts.REVISION}/human-audit-v1/"
    "explicit-marker-relation-only-v1"
)
_ITEMS_NAME = "audit-items.jsonl"
_REVIEW_A_NAME = "reviewer-a-template.jsonl"
_REVIEW_B_NAME = "reviewer-b-template.jsonl"
_INSTRUCTIONS_NAME = "review-instructions.md"
_MANIFEST_NAME = "human-audit-manifest.json"
_JSONL_LIMIT = 67_108_864
_INSTRUCTIONS_LIMIT = 1_048_576
_MANIFEST_LIMIT = 1_048_576
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_NAMES = {
    _ITEMS_NAME,
    _REVIEW_A_NAME,
    _REVIEW_B_NAME,
    _INSTRUCTIONS_NAME,
    _MANIFEST_NAME,
}


class HumanAuditError(ValueError):
    """The source, sampling, publication, or replay contract failed."""


class ObserverState(str, Enum):
    ABSENT = "ABSENT"
    PARTIAL_NO_MANIFEST = "PARTIAL_NO_MANIFEST"
    STRUCTURALLY_VERIFIED = "STRUCTURALLY_VERIFIED"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True)
class _Layout:
    relation_layout: relation_artifacts._Layout
    target_parent_rel: str
    sample_size: int
    sampling_seed: int


@dataclass(frozen=True)
class _Selection:
    pairs: tuple[RelationOnlyPair, ...]
    strata: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _Packet:
    files: Mapping[str, bytes]
    selection: _Selection
    source_manifest_sha256: str
    source_jsonl_sha256: str
    source_record_count: int


_PRODUCTION_LAYOUT = _Layout(
    relation_layout=relation_artifacts._PRODUCTION_LAYOUT,
    target_parent_rel=_TARGET_PARENT_REL,
    sample_size=SAMPLE_SIZE,
    sampling_seed=SAMPLING_SEED,
)


def _fail(message: str) -> None:
    raise HumanAuditError(message) from None


def _validate_layout(layout: _Layout) -> None:
    if (
        not isinstance(layout.sample_size, int)
        or isinstance(layout.sample_size, bool)
        or layout.sample_size <= 0
        or not isinstance(layout.sampling_seed, int)
        or isinstance(layout.sampling_seed, bool)
        or layout.sampling_seed < 0
    ):
        _fail("human audit sampling configuration is invalid")
    if set(layout.relation_layout.source_layout.splits) != {"train"}:
        _fail("human audit source layout must be train-only")


def _validate_execution_commit(value: str) -> None:
    if not isinstance(value, str) or not _HEX40.fullmatch(value):
        _fail("execution commit must be lowercase 40-hex")


def _git_gate(layout: _Layout, execution_commit: str) -> None:
    _validate_execution_commit(execution_commit)
    try:
        relation_artifacts._git_gate(layout.relation_layout, execution_commit)
    except relation_artifacts.RelationSupervisionArtifactError:
        _fail("Git provenance gate failed")


def _stratum(pair: RelationOnlyPair) -> str:
    return f"{pair.template_id}|{pair.original_relation.relation.value}"


def _rank(seed: int, purpose: str, pair_id: str) -> str:
    payload = f"{SAMPLING_VERSION}\0{seed}\0{purpose}\0{pair_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _select_pairs(
    population: Sequence[RelationOnlyPair], sample_size: int, seed: int
) -> _Selection:
    if (
        not isinstance(sample_size, int)
        or isinstance(sample_size, bool)
        or sample_size <= 0
        or sample_size > len(population)
        or not isinstance(seed, int)
        or isinstance(seed, bool)
        or seed < 0
    ):
        _fail("human audit sample size or seed is invalid")
    groups: dict[str, list[RelationOnlyPair]] = defaultdict(list)
    pair_ids: set[str] = set()
    for pair in population:
        if not isinstance(pair, RelationOnlyPair):
            _fail("human audit population contains a non-pair")
        if pair.pair_id in pair_ids:
            _fail("human audit population contains duplicate pair IDs")
        pair_ids.add(pair.pair_id)
        groups[_stratum(pair)].append(pair)

    total = len(population)
    allocations = {
        key: len(values) * sample_size // total for key, values in groups.items()
    }
    remaining = sample_size - sum(allocations.values())
    remainder_order = sorted(
        groups,
        key=lambda key: (-(len(groups[key]) * sample_size % total), key),
    )
    for key in remainder_order[:remaining]:
        allocations[key] += 1

    selected: list[RelationOnlyPair] = []
    strata = []
    for key in sorted(groups):
        ordered = sorted(
            groups[key], key=lambda pair: (_rank(seed, "within-stratum", pair.pair_id), pair.pair_id)
        )
        allocation = allocations[key]
        if allocation > len(ordered):
            _fail("human audit stratum allocation exceeds population")
        selected.extend(ordered[:allocation])
        strata.append(
            {
                "stratum": key,
                "population_count": len(ordered),
                "sample_count": allocation,
            }
        )
    selected.sort(
        key=lambda pair: (_rank(seed, "presentation", pair.pair_id), pair.pair_id)
    )
    if len(selected) != sample_size or len({pair.pair_id for pair in selected}) != sample_size:
        _fail("human audit selection count or uniqueness differs")
    return _Selection(tuple(selected), tuple(strata))


def _parse_population(layout: _Layout) -> tuple[tuple[RelationOnlyPair, ...], Mapping[str, Any]]:
    _validate_layout(layout)
    try:
        verification = relation_artifacts._verify_layout(layout.relation_layout)
        pair_payload, _ = relation_artifacts._read_complete_target(
            layout.relation_layout
        )
        manifest = verification["manifest"]
        expected_count = manifest["output"]["record_count"]
        expected_sha256 = manifest["output"]["sha256"]
    except (
        relation_artifacts.RelationSupervisionArtifactError,
        KeyError,
        TypeError,
    ):
        _fail("verified relation-supervision source cannot be loaded")
    if hashlib.sha256(pair_payload).hexdigest() != expected_sha256:
        _fail("relation-supervision source SHA differs after verification")
    pairs = []
    for index, line in enumerate(pair_payload.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n") or len(line) > 1_048_576:
            _fail("relation-supervision source line framing is invalid")
        try:
            value = source_binding._strict_json_object(
                line[:-1], f"relation source line {index}"
            )
            if canonical_json(value).encode("utf-8") + b"\n" != line:
                _fail("relation-supervision source line is not canonical")
            pairs.append(RelationOnlyPair.from_dict(value))
        except (
            source_binding.ConstructionAuditPersistenceError,
            RelationSupervisionError,
            TypeError,
            ValueError,
        ):
            _fail("relation-supervision source line cannot be replayed")
    if len(pairs) != expected_count:
        _fail("relation-supervision source count differs")
    return tuple(pairs), verification


def _event_values(pair: RelationOnlyPair, counterfactual: bool) -> list[Mapping[str, Any]]:
    events = pair.counterfactual_events if counterfactual else pair.original_events
    return [
        {
            "event_id": event.event_id,
            "text": event.text,
            "char_span": {
                "start": event.char_span.start,
                "end": event.char_span.end,
            },
        }
        for event in events
    ]


def _audit_item(pair: RelationOnlyPair, seed: int) -> Mapping[str, Any]:
    audit_item_id = make_stable_id(
        "human-audit-item",
        {
            "version": AUDIT_ITEM_SCHEMA_VERSION,
            "sampling_version": SAMPLING_VERSION,
            "seed": seed,
            "pair_id": pair.pair_id,
        },
    )
    return {
        "schema_version": AUDIT_ITEM_SCHEMA_VERSION,
        "audit_item_id": audit_item_id,
        "pair_id": pair.pair_id,
        "stratum": _stratum(pair),
        "original_query": pair.original_query,
        "counterfactual_query": pair.counterfactual_query,
        "original_events": _event_values(pair, False),
        "counterfactual_events": _event_values(pair, True),
        "proposed_original_relation": pair.original_relation.relation.value,
        "proposed_counterfactual_relation": pair.counterfactual_relation.relation.value,
        "template_id": pair.template_id,
    }


def _review_template(audit_item_id: str, reviewer_slot: str) -> Mapping[str, Any]:
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "audit_item_id": audit_item_id,
        "reviewer_slot": reviewer_slot,
        "event_spans_valid": None,
        "original_relation_valid": None,
        "counterfactual_relation_valid": None,
        "rewrite_grammatical": None,
        "non_target_content_preserved": None,
        "overall_valid": None,
        "notes": None,
    }


def _instructions() -> bytes:
    text = """# GSM8K relation-only 双人盲审说明

本包只包含 official train 的 200 个确定性分层样本。Reviewer A 与 Reviewer B
必须独立工作，不查看或交换对方表单。程序没有预填任何人工判断。

对每项填写六个布尔字段：事件 span 是否准确、原关系是否准确、反事实关系是否准确、
改写是否通顺、非目标内容是否保持，以及 overall_valid。`overall_valid` 必须等于前五项
的逻辑与；`notes` 可为 null 或不超过 1000 个 Unicode 字符的解释。不要修改
`schema_version`、`audit_item_id` 或 `reviewer_slot`。

模板属于不可变审计包，请复制后填写，不要原地覆盖。两份完成表锁定哈希后才能互看。
主一致性为 200 个 `overall_valid` 的 Cohen's kappa，门槛为 0.80。分歧必须在独立
标注锁定后由作者共识裁决；裁决后有效率门槛为 95%。未达到任一门槛时不得开始
GSM8K LoRA 训练，必须修订构造规则并用新的、不可复用的样本重新审计。
"""
    return text.encode("utf-8")


def _build_packet(layout: _Layout) -> _Packet:
    population, verification = _parse_population(layout)
    selection = _select_pairs(
        population, layout.sample_size, layout.sampling_seed
    )
    item_values = [
        _audit_item(pair, layout.sampling_seed) for pair in selection.pairs
    ]
    items = b"".join(
        canonical_json(value).encode("utf-8") + b"\n" for value in item_values
    )
    reviewer_a = b"".join(
        canonical_json(_review_template(value["audit_item_id"], "A")).encode("utf-8")
        + b"\n"
        for value in item_values
    )
    reviewer_b = b"".join(
        canonical_json(_review_template(value["audit_item_id"], "B")).encode("utf-8")
        + b"\n"
        for value in item_values
    )
    for payload in (items, reviewer_a, reviewer_b):
        if len(payload) > _JSONL_LIMIT:
            _fail("human audit JSONL exceeds its total limit")
    instructions = _instructions()
    if len(instructions) > _INSTRUCTIONS_LIMIT:
        _fail("human audit instructions exceed their limit")
    manifest = verification["manifest"]
    return _Packet(
        files={
            _ITEMS_NAME: items,
            _REVIEW_A_NAME: reviewer_a,
            _REVIEW_B_NAME: reviewer_b,
            _INSTRUCTIONS_NAME: instructions,
        },
        selection=selection,
        source_manifest_sha256=verification["manifest_sha256"],
        source_jsonl_sha256=manifest["output"]["sha256"],
        source_record_count=manifest["output"]["record_count"],
    )


def _manifest_values(
    layout: _Layout, packet: _Packet, execution_commit: str
) -> Mapping[str, Any]:
    _validate_execution_commit(execution_commit)
    return {
        "status": "COMPLETE",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_id": AUDIT_ARTIFACT_ID,
        "dataset": "gsm8k",
        "revision": relation_artifacts.REVISION,
        "official_split": "train",
        "source": {
            "artifact_id": relation_artifacts.ARTIFACT_ID,
            "manifest_sha256": packet.source_manifest_sha256,
            "jsonl_sha256": packet.source_jsonl_sha256,
            "population_count": packet.source_record_count,
        },
        "sampler": {
            "version": SAMPLING_VERSION,
            "seed": layout.sampling_seed,
            "sample_size": layout.sample_size,
            "strata": list(packet.selection.strata),
            "execution_commit": execution_commit,
        },
        "review_contract": {
            "item_schema_version": AUDIT_ITEM_SCHEMA_VERSION,
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "reviewer_slots": ["A", "B"],
            "boolean_fields": [
                "event_spans_valid",
                "original_relation_valid",
                "counterfactual_relation_valid",
                "rewrite_grammatical",
                "non_target_content_preserved",
                "overall_valid",
            ],
            "templates_are_blank": True,
            "cohen_kappa_threshold": 0.8,
            "adjudicated_validity_threshold": 0.95,
            "training_blocked_until_complete": True,
        },
        "outputs": {
            name: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "byte_size": len(payload),
                "record_count": (
                    layout.sample_size if name != _INSTRUCTIONS_NAME else 1
                ),
            }
            for name, payload in packet.files.items()
        },
    }


def _publication_source_layout(layout: _Layout) -> source_binding._Layout:
    return replace(
        layout.relation_layout.source_layout,
        target_parent_rel=layout.target_parent_rel,
        splits={"train": layout.relation_layout.source_layout.splits["train"]},
    )


def _target_path(layout: _Layout) -> Path:
    return (
        layout.relation_layout.source_layout.data_root
        / layout.target_parent_rel
        / "train"
    )


def _create_target(layout: _Layout) -> Path:
    try:
        return source_binding._create_target(
            _publication_source_layout(layout), "train"
        )
    except source_binding.ConstructionAuditPersistenceError:
        if _target_path(layout).exists() or _target_path(layout).is_symlink():
            _fail("human audit target already exists")
        _fail("human audit publication blocked partial")


def _publish_bytes(target: Path, name: str, payload: bytes) -> None:
    try:
        source_binding._publish_bytes(target, name, payload)
    except source_binding.ConstructionAuditPersistenceError:
        _fail("human audit publication blocked partial")


def _read_target(layout: _Layout) -> Mapping[str, bytes]:
    target = _target_path(layout)
    try:
        checked = source_binding._checked_path(
            layout.relation_layout.source_layout,
            f"{layout.target_parent_rel}/train",
            regular=False,
        )
        path_info = checked.lstat()
        if stat.S_IMODE(path_info.st_mode) != 0o700:
            _fail("human audit target directory mode is invalid")
        directory_fd = os.open(
            checked, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
    except HumanAuditError:
        raise
    except (
        source_binding.ConstructionAuditPersistenceError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ):
        _fail("human audit target binding is invalid")
    try:
        before = os.fstat(directory_fd)
        if before.st_dev != path_info.st_dev or before.st_ino != path_info.st_ino:
            _fail("human audit target directory changed")
        if set(os.listdir(directory_fd)) != _EXPECTED_NAMES:
            _fail("human audit target namespace differs")
        limits = {
            _ITEMS_NAME: _JSONL_LIMIT,
            _REVIEW_A_NAME: _JSONL_LIMIT,
            _REVIEW_B_NAME: _JSONL_LIMIT,
            _INSTRUCTIONS_NAME: _INSTRUCTIONS_LIMIT,
            _MANIFEST_NAME: _MANIFEST_LIMIT,
        }
        values = {}
        for name in sorted(_EXPECTED_NAMES):
            try:
                values[name] = relation_artifacts._read_file_at(
                    directory_fd, name, limits[name]
                )
            except relation_artifacts.RelationSupervisionArtifactError:
                _fail("human audit target file binding is invalid")
        after = os.fstat(directory_fd)
        named = target.lstat()
        if (
            set(os.listdir(directory_fd)) != _EXPECTED_NAMES
            or relation_artifacts._stable_binding(before)
            != relation_artifacts._stable_binding(after)
            or before.st_dev != named.st_dev
            or before.st_ino != named.st_ino
        ):
            _fail("human audit target changed while reading")
        return values
    except HumanAuditError:
        raise
    except (FileNotFoundError, PermissionError, OSError):
        _fail("human audit target cannot be read")
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _parse_manifest(payload: bytes) -> Mapping[str, Any]:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        _fail("human audit manifest must be one LF-terminated object")
    try:
        value = source_binding._strict_json_object(
            payload[:-1], "human audit manifest"
        )
    except source_binding.ConstructionAuditPersistenceError:
        _fail("human audit manifest is not strict JSON")
    if canonical_json(value).encode("utf-8") + b"\n" != payload:
        _fail("human audit manifest is not canonical")
    return value


def _verify_layout(layout: _Layout) -> Mapping[str, Any]:
    packet = _build_packet(layout)
    files = _read_target(layout)
    manifest = _parse_manifest(files[_MANIFEST_NAME])
    try:
        execution_commit = manifest["sampler"]["execution_commit"]
    except (KeyError, TypeError):
        _fail("human audit manifest lacks execution provenance")
    expected_manifest = _manifest_values(layout, packet, execution_commit)
    if manifest != expected_manifest:
        _fail("human audit manifest differs from full replay")
    for name, payload in packet.files.items():
        if files[name] != payload:
            _fail("human audit output differs from full replay")
    return {
        "observer_state": ObserverState.STRUCTURALLY_VERIFIED.value,
        "target": str(_target_path(layout)),
        "manifest_sha256": hashlib.sha256(files[_MANIFEST_NAME]).hexdigest(),
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
    except HumanAuditError:
        return ObserverState.CORRUPT
    return ObserverState.STRUCTURALLY_VERIFIED


def _publish_layout(
    layout: _Layout,
    execution_commit: str,
    git_gate: Callable[[_Layout, str], None] = _git_gate,
) -> Mapping[str, Any]:
    _validate_layout(layout)
    _validate_execution_commit(execution_commit)
    git_gate(layout, execution_commit)
    packet = _build_packet(layout)
    git_gate(layout, execution_commit)
    target = _create_target(layout)
    for name in (
        _ITEMS_NAME,
        _REVIEW_A_NAME,
        _REVIEW_B_NAME,
        _INSTRUCTIONS_NAME,
    ):
        _publish_bytes(target, name, packet.files[name])
    git_gate(layout, execution_commit)
    manifest = _manifest_values(layout, packet, execution_commit)
    manifest_payload = canonical_json(manifest).encode("utf-8") + b"\n"
    if len(manifest_payload) > _MANIFEST_LIMIT:
        _fail("human audit manifest exceeds its limit")
    _publish_bytes(target, _MANIFEST_NAME, manifest_payload)
    verified = _verify_layout(layout)
    git_gate(layout, execution_commit)
    return verified


def publish(execution_commit: str) -> Mapping[str, Any]:
    return _publish_layout(_PRODUCTION_LAYOUT, execution_commit)


def verify() -> Mapping[str, Any]:
    return _verify_layout(_PRODUCTION_LAYOUT)


def observe() -> ObserverState:
    return _observe_layout(_PRODUCTION_LAYOUT)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish or verify the fixed train-only human-audit packet"
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
    except HumanAuditError as error:
        print(f"human audit packet failed: {error}", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "AUDIT_ARTIFACT_ID",
    "AUDIT_ITEM_SCHEMA_VERSION",
    "HumanAuditError",
    "MANIFEST_SCHEMA_VERSION",
    "ObserverState",
    "REVIEW_SCHEMA_VERSION",
    "SAMPLE_SIZE",
    "SAMPLING_SEED",
    "SAMPLING_VERSION",
    "observe",
    "publish",
    "verify",
)
