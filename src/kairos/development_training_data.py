"""Audit-bound immutable GSM8K relation-only development partition."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence

from .ids import canonical_json
from . import prediction_artifacts as artifact_io
from .prediction_artifacts import PredictionArtifactError
from . import development_audit_artifacts as audit_artifacts
from .relation_audit_results import AGREEMENT_PROJECTION_SCHEMA_VERSION
from .relation_supervision import RelationOnlyPair, RelationSupervisionError
from . import relation_supervision_artifacts
from .schema import InternalSplit


ALLOWED_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
REVISION = "3101c7d5072418e28b9008a6636bde82a006892c"
SOURCE_DIR = (
    ALLOWED_DATA_ROOT
    / f"data/processed/gsm8k/{REVISION}"
    / "relation-supervision-v1/explicit-marker-relation-only-v1/train"
)
SOURCE_DATA_NAME = "relation-supervision.jsonl"
SOURCE_MANIFEST_NAME = "relation-supervision-manifest.json"
SOURCE_DATA_SHA256 = (
    "525e3b09c6a6d03942a6bc3e03ebcd1722c3a68f4f224753dbc641f98465c12a"
)
SOURCE_MANIFEST_SHA256 = (
    "4e22ff135d97c89ded50a54fc1007f25d9646db67ce112e4637d4e8c8b63674a"
)
AUDIT_MANIFEST_SHA256 = (
    "c501f37697e5254a274075e0a5d017472b960240b436e5a5acdd65c4d1c4afe7"
)
AUDIT_RESULT_SHA256 = (
    "df7310e8a5c9f85f9e4f7f1e635d24d92db173217ee25d97fba28c9de149f318"
)
AUDIT_PROJECTION_SHA256 = (
    "ae8bc796147e7b7b9f87dcb1924501625ff6d2acdbd5e8175727bb64081ef230"
)
AUDIT_EXECUTION_COMMIT = "06eff003309cb67e0b71167043e4a41b04351856"
ARTIFACT_ROOT = ALLOWED_DATA_ROOT / f"data/processed/gsm8k/{REVISION}/training-data-v2"
ARTIFACT_ID = "audit-bound-user-attested-relation-only-v1-train"
DATA_NAME = "training-data.jsonl"
TRAIN_NAME = "train.jsonl"
DEV_NAME = "internal-dev.jsonl"
PARTITION_NAME = "partition.json"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = "gsm8k-audit-bound-training-data-manifest-v2"
PARTITION_SCHEMA_VERSION = "gsm8k-relation-partition-v1"
STATUS = "COMPLETE_DEVELOPMENT_ONLY"
_OUTPUT_NAMES = {DATA_NAME, TRAIN_NAME, DEV_NAME, PARTITION_NAME, MANIFEST_NAME}
_SOURCE_NAMES = {SOURCE_DATA_NAME, SOURCE_MANIFEST_NAME}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_FILE_LIMIT = 32 * 1024 * 1024
_MANIFEST_LIMIT = 4 * 1024 * 1024
_LINE_LIMIT = 1024 * 1024


class DevelopmentTrainingDataError(ValueError):
    """An audit chain, partition, publication, or replay invariant failed."""


def _fail(message: str) -> None:
    raise DevelopmentTrainingDataError(message) from None


@dataclass(frozen=True)
class _Record:
    raw: bytes
    pair_id: str
    source_id: str
    internal_split: str


@dataclass(frozen=True)
class _Derived:
    data_payload: bytes
    train_payload: bytes
    dev_payload: bytes
    partition_payload: bytes
    invalid_pairs: tuple[tuple[str, str], ...]
    all_records: tuple[_Record, ...]
    train_records: tuple[_Record, ...]
    dev_records: tuple[_Record, ...]


@dataclass(frozen=True)
class VerifiedDevelopmentTrainingData:
    artifact_id: str
    record_count: int
    train_count: int
    internal_dev_count: int
    data_sha256: str
    train_sha256: str
    internal_dev_sha256: str
    partition_sha256: str
    manifest_sha256: str
    artifact_path: Path


def _read(path: Path, limit: int, name: str) -> bytes:
    try:
        return artifact_io._read_artifact_file(path, limit, name)
    except PredictionArtifactError as error:
        raise DevelopmentTrainingDataError(f"{name} file is invalid") from error


def _hash(payload: bytes, expected: str, name: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected:
        _fail(f"{name} SHA256 differs")


def _canonical_object(payload: bytes, name: str) -> Mapping[str, Any]:
    try:
        return artifact_io._canonical_object(payload, name)
    except PredictionArtifactError as error:
        raise DevelopmentTrainingDataError(f"{name} is invalid") from error


def _jsonl_values(payload: bytes, name: str) -> tuple[tuple[bytes, Mapping[str, Any]], ...]:
    if not payload or not payload.endswith(b"\n"):
        _fail(f"{name} is not LF-delimited JSONL")
    result = []
    for index, raw in enumerate(payload.splitlines(keepends=True), start=1):
        if not raw.endswith(b"\n") or len(raw) > _LINE_LIMIT:
            _fail(f"{name} line framing differs")
        try:
            value = artifact_io._strict_json(raw[:-1], f"{name} line {index}")
        except PredictionArtifactError as error:
            raise DevelopmentTrainingDataError(f"{name} JSON is invalid") from error
        if not isinstance(value, Mapping):
            _fail(f"{name} row is not an object")
        if canonical_json(value).encode("utf-8") + b"\n" != raw:
            _fail(f"{name} row is not canonical JSON")
        result.append((raw, value))
    return tuple(result)


def _source_records(payload: bytes) -> tuple[_Record, ...]:
    records = []
    for raw, value in _jsonl_values(payload, "relation supervision"):
        try:
            pair = RelationOnlyPair.from_dict(value)
        except RelationSupervisionError as error:
            raise DevelopmentTrainingDataError(
                "relation supervision deterministic replay failed"
            ) from error
        if pair.revision != REVISION or pair.split.official != "train":
            _fail("relation supervision dataset binding differs")
        if pair.split.internal not in {InternalSplit.TRAIN, InternalSplit.DEV}:
            _fail("relation supervision internal split is absent")
        records.append(
            _Record(raw, pair.pair_id, pair.source_id, pair.split.internal.value)
        )
    if len(records) != 370:
        _fail("relation supervision source count differs")
    return tuple(records)


def _invalid_pairs(items_payload: bytes, projection_payload: bytes) -> tuple[tuple[str, str], ...]:
    items = _jsonl_values(items_payload, "audit items")
    projection = _jsonl_values(projection_payload, "agreement projection")
    if len(items) != 200 or len(projection) != 200:
        _fail("audit coverage differs")
    item_pairs: dict[str, str] = {}
    for _, item in items:
        item_id = item.get("audit_item_id")
        pair_id = item.get("pair_id")
        if (
            not isinstance(item_id, str)
            or not item_id
            or not isinstance(pair_id, str)
            or not pair_id
            or item_id in item_pairs
        ):
            _fail("audit item identity differs")
        item_pairs[item_id] = pair_id
    invalid = []
    seen = set()
    for _, row in projection:
        if set(row) != {"schema_version", "audit_item_id", "overall_valid"}:
            _fail("agreement projection keys differ")
        item_id = row["audit_item_id"]
        valid = row["overall_valid"]
        if (
            row["schema_version"] != AGREEMENT_PROJECTION_SCHEMA_VERSION
            or item_id not in item_pairs
            or item_id in seen
            or type(valid) is not bool
        ):
            _fail("agreement projection identity differs")
        seen.add(item_id)
        if not valid:
            invalid.append((item_id, item_pairs[item_id]))
    if seen != set(item_pairs) or len(invalid) != 4:
        _fail("agreement projection invalid-pair set differs")
    return tuple(invalid)


def _ordered_id_hash(records: Sequence[_Record]) -> str:
    return hashlib.sha256(
        canonical_json([record.pair_id for record in records]).encode("utf-8")
    ).hexdigest()


def _derive(records: Sequence[_Record], invalid_pairs: Sequence[tuple[str, str]]) -> _Derived:
    records = tuple(records)
    invalid_pairs = tuple(invalid_pairs)
    pair_ids = [record.pair_id for record in records]
    source_ids = [record.source_id for record in records]
    if len(set(pair_ids)) != len(pair_ids) or len(set(source_ids)) != len(source_ids):
        _fail("source pair/source identities are not unique")
    invalid_ids = {pair_id for _, pair_id in invalid_pairs}
    if len(invalid_ids) != len(invalid_pairs) or not invalid_ids.issubset(pair_ids):
        _fail("audit exclusions do not bind unique source pairs")
    retained = tuple(record for record in records if record.pair_id not in invalid_ids)
    train = tuple(record for record in retained if record.internal_split == "train")
    dev = tuple(record for record in retained if record.internal_split == "dev")
    if len(retained) != 366 or len(train) != 330 or len(dev) != 36:
        _fail("frozen development partition counts differ")
    if set(record.pair_id for record in train).intersection(
        record.pair_id for record in dev
    ):
        _fail("a pair crosses development partitions")
    train_sources = {record.source_id for record in train}
    dev_sources = {record.source_id for record in dev}
    if train_sources.intersection(dev_sources):
        _fail("a source group crosses development partitions")
    partition_value = {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "status": STATUS,
        "assignment_rule": "replay-frozen-split.internal-v1",
        "gold_access": {
            "train": "train-only recorded injection permitted during later materialization",
            "internal-dev": "gold-blind; no optimizer and no ordinary gold injection",
        },
        "source_record_count": len(records),
        "retained_record_count": len(retained),
        "exclusions": [
            {"audit_item_id": item_id, "pair_id": pair_id}
            for item_id, pair_id in invalid_pairs
        ],
        "partitions": {
            "train": {
                "count": len(train),
                "ordered_pair_ids": [record.pair_id for record in train],
                "ordered_pair_ids_sha256": _ordered_id_hash(train),
            },
            "internal-dev": {
                "count": len(dev),
                "ordered_pair_ids": [record.pair_id for record in dev],
                "ordered_pair_ids_sha256": _ordered_id_hash(dev),
            },
        },
        "counterfactual_answer_available": False,
        "paper_metric_eligible": False,
    }
    return _Derived(
        data_payload=b"".join(record.raw for record in retained),
        train_payload=b"".join(record.raw for record in train),
        dev_payload=b"".join(record.raw for record in dev),
        partition_payload=canonical_json(partition_value).encode("utf-8") + b"\n",
        invalid_pairs=invalid_pairs,
        all_records=retained,
        train_records=train,
        dev_records=dev,
    )


def _production_derivation() -> _Derived:
    source_verification = relation_supervision_artifacts.verify()
    if source_verification.get("manifest_sha256") != SOURCE_MANIFEST_SHA256:
        _fail("relation supervision artifact verification differs")
    audit_verification = audit_artifacts.verify(AUDIT_EXECUTION_COMMIT)
    if audit_verification.manifest_sha256 != AUDIT_MANIFEST_SHA256:
        _fail("development audit artifact verification differs")
    source_payload = _read(SOURCE_DIR / SOURCE_DATA_NAME, _FILE_LIMIT, SOURCE_DATA_NAME)
    source_manifest = _read(
        SOURCE_DIR / SOURCE_MANIFEST_NAME, _MANIFEST_LIMIT, SOURCE_MANIFEST_NAME
    )
    items_payload = _read(
        audit_artifacts.PACKET_DIR / "audit-items.jsonl",
        _FILE_LIMIT,
        "audit-items.jsonl",
    )
    projection_payload = _read(
        audit_verification.artifact_path / audit_artifacts.PROJECTION_NAME,
        _FILE_LIMIT,
        audit_artifacts.PROJECTION_NAME,
    )
    result_payload = _read(
        audit_verification.artifact_path / audit_artifacts.RESULT_NAME,
        _MANIFEST_LIMIT,
        audit_artifacts.RESULT_NAME,
    )
    for payload, expected, name in (
        (source_payload, SOURCE_DATA_SHA256, "relation supervision data"),
        (source_manifest, SOURCE_MANIFEST_SHA256, "relation supervision manifest"),
        (items_payload, audit_artifacts.AUDIT_ITEMS_SHA256, "audit items"),
        (projection_payload, AUDIT_PROJECTION_SHA256, "agreement projection"),
        (result_payload, AUDIT_RESULT_SHA256, "development audit result"),
    ):
        _hash(payload, expected, name)
    return _derive(
        _source_records(source_payload),
        _invalid_pairs(items_payload, projection_payload),
    )


def _output_binding(payload: bytes, count: int | None = None) -> Mapping[str, Any]:
    value: dict[str, Any] = {
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if count is not None:
        value["record_count"] = count
    return value


def _manifest_value(execution_commit: str, derived: _Derived) -> Mapping[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": STATUS,
        "artifact_id": ARTIFACT_ID,
        "execution_commit": execution_commit,
        "dataset": "gsm8k",
        "revision": REVISION,
        "official_split": "train",
        "source": {
            "artifact_id": relation_supervision_artifacts.ARTIFACT_ID,
            "path": str(SOURCE_DIR),
            "data_sha256": SOURCE_DATA_SHA256,
            "manifest_sha256": SOURCE_MANIFEST_SHA256,
            "record_count": 370,
        },
        "audit": {
            "artifact_id": audit_artifacts.ARTIFACT_ID,
            "execution_commit": AUDIT_EXECUTION_COMMIT,
            "manifest_sha256": AUDIT_MANIFEST_SHA256,
            "result_sha256": AUDIT_RESULT_SHA256,
            "projection_sha256": AUDIT_PROJECTION_SHA256,
            "provenance_status": "USER_ATTESTED / INDEPENDENCE_UNVERIFIED",
            "paper_metric_eligible": False,
        },
        "partition_policy": {
            "version": "audit-invalid-filter-plus-frozen-internal-split-v1",
            "excluded_count": len(derived.invalid_pairs),
            "train_count": len(derived.train_records),
            "internal_dev_count": len(derived.dev_records),
            "optimizer_eligible_partition": "train",
        },
        "outputs": {
            DATA_NAME: _output_binding(derived.data_payload, len(derived.all_records)),
            TRAIN_NAME: _output_binding(derived.train_payload, len(derived.train_records)),
            DEV_NAME: _output_binding(derived.dev_payload, len(derived.dev_records)),
            PARTITION_NAME: _output_binding(derived.partition_payload),
        },
        "counterfactual_answer_available": False,
        "formal_experiment_eligible": False,
        "paper_metric_eligible": False,
    }


def _payload(value: Mapping[str, Any], name: str) -> bytes:
    try:
        payload = canonical_json(value).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise DevelopmentTrainingDataError(f"{name} cannot be serialized") from error
    if len(payload) > _MANIFEST_LIMIT:
        _fail(f"{name} exceeds its byte limit")
    return payload


def _prepare_root() -> None:
    if not ARTIFACT_ROOT.is_relative_to(ALLOWED_DATA_ROOT):
        _fail("training data root is outside the allowed data path")
    audit_artifacts._private_directory(ARTIFACT_ROOT.parent, "training data root parent")
    try:
        artifact_io._prepare_root(ARTIFACT_ROOT)
    except (PredictionArtifactError, OSError) as error:
        raise DevelopmentTrainingDataError("training data root cannot be prepared") from error


def _verify(expected_commit: str | None = None) -> VerifiedDevelopmentTrainingData:
    audit_artifacts._private_directory(ARTIFACT_ROOT, "training data root")
    target = ARTIFACT_ROOT / ARTIFACT_ID
    audit_artifacts._namespace(target, _OUTPUT_NAMES, "training data artifact")
    binding = audit_artifacts._directory_binding(target, "training data artifact")
    files = {
        DATA_NAME: _read(target / DATA_NAME, _FILE_LIMIT, DATA_NAME),
        TRAIN_NAME: _read(target / TRAIN_NAME, _FILE_LIMIT, TRAIN_NAME),
        DEV_NAME: _read(target / DEV_NAME, _FILE_LIMIT, DEV_NAME),
        PARTITION_NAME: _read(target / PARTITION_NAME, _MANIFEST_LIMIT, PARTITION_NAME),
        MANIFEST_NAME: _read(target / MANIFEST_NAME, _MANIFEST_LIMIT, MANIFEST_NAME),
    }
    manifest = _canonical_object(files[MANIFEST_NAME], "training data manifest")
    execution_commit = manifest.get("execution_commit")
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("training data execution commit is invalid")
    if expected_commit is not None and execution_commit != expected_commit:
        _fail("training data execution commit differs")
    derived = _production_derivation()
    expected_files = {
        DATA_NAME: derived.data_payload,
        TRAIN_NAME: derived.train_payload,
        DEV_NAME: derived.dev_payload,
        PARTITION_NAME: derived.partition_payload,
    }
    if any(files[name] != payload for name, payload in expected_files.items()):
        _fail("training data output differs from full replay")
    expected_manifest = _manifest_value(execution_commit, derived)
    if manifest != expected_manifest:
        _fail("training data manifest differs from full replay")
    audit_artifacts._namespace(target, _OUTPUT_NAMES, "training data artifact")
    if binding != audit_artifacts._directory_binding(target, "training data artifact"):
        _fail("training data artifact changed while reading")
    return VerifiedDevelopmentTrainingData(
        artifact_id=ARTIFACT_ID,
        record_count=len(derived.all_records),
        train_count=len(derived.train_records),
        internal_dev_count=len(derived.dev_records),
        data_sha256=hashlib.sha256(files[DATA_NAME]).hexdigest(),
        train_sha256=hashlib.sha256(files[TRAIN_NAME]).hexdigest(),
        internal_dev_sha256=hashlib.sha256(files[DEV_NAME]).hexdigest(),
        partition_sha256=hashlib.sha256(files[PARTITION_NAME]).hexdigest(),
        manifest_sha256=hashlib.sha256(files[MANIFEST_NAME]).hexdigest(),
        artifact_path=target,
    )


def publish(execution_commit: str) -> VerifiedDevelopmentTrainingData:
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("execution commit is invalid")
    artifact_io._git_gate(execution_commit)
    derived = _production_derivation()
    manifest_payload = _payload(
        _manifest_value(execution_commit, derived), "training data manifest"
    )
    _prepare_root()
    target = ARTIFACT_ROOT / ARTIFACT_ID
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("training data artifact already exists")
    except OSError as error:
        raise DevelopmentTrainingDataError("training data target cannot be created") from error
    try:
        for name, payload in (
            (DATA_NAME, derived.data_payload),
            (TRAIN_NAME, derived.train_payload),
            (DEV_NAME, derived.dev_payload),
            (PARTITION_NAME, derived.partition_payload),
        ):
            artifact_io._write_exclusive(target / name, payload)
        artifact_io._fsync_directory(target)
        artifact_io._git_gate(execution_commit)
        artifact_io._write_exclusive(target / MANIFEST_NAME, manifest_payload)
        artifact_io._fsync_directory(target)
        artifact_io._fsync_directory(ARTIFACT_ROOT)
    except (PredictionArtifactError, OSError) as error:
        raise DevelopmentTrainingDataError(
            "training data publication failed; partial state is retained"
        ) from error
    return _verify(execution_commit)


def verify(expected_commit: str | None = None) -> VerifiedDevelopmentTrainingData:
    return _verify(expected_commit)


def _summary(value: VerifiedDevelopmentTrainingData) -> Mapping[str, Any]:
    return {
        "artifact_id": value.artifact_id,
        "artifact_path": str(value.artifact_path),
        "record_count": value.record_count,
        "train_count": value.train_count,
        "internal_dev_count": value.internal_dev_count,
        "data_sha256": value.data_sha256,
        "train_sha256": value.train_sha256,
        "internal_dev_sha256": value.internal_dev_sha256,
        "partition_sha256": value.partition_sha256,
        "manifest_sha256": value.manifest_sha256,
        "status": STATUS,
        "paper_metric_eligible": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publisher = commands.add_parser("publish")
    publisher.add_argument("--execution-commit", required=True)
    verifier = commands.add_parser("verify")
    verifier.add_argument("--expected-commit")
    commands.add_parser("derive")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "publish":
            result: Any = _summary(publish(arguments.execution_commit))
        elif arguments.command == "verify":
            result = _summary(verify(arguments.expected_commit))
        else:
            derived = _production_derivation()
            result = {
                "record_count": len(derived.all_records),
                "train_count": len(derived.train_records),
                "internal_dev_count": len(derived.dev_records),
                "excluded_count": len(derived.invalid_pairs),
                "data_sha256": hashlib.sha256(derived.data_payload).hexdigest(),
                "partition_sha256": hashlib.sha256(
                    derived.partition_payload
                ).hexdigest(),
            }
    except DevelopmentTrainingDataError as error:
        print(f"development training data failed: {error}", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_ID",
    "ARTIFACT_ROOT",
    "DevelopmentTrainingDataError",
    "VerifiedDevelopmentTrainingData",
    "publish",
    "verify",
]
