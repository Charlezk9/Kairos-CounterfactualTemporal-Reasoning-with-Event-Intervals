"""Immutable development-only publication for user-attested audit agreement."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Mapping, Sequence

from .ids import canonical_json
from . import prediction_artifacts as artifact_io
from .prediction_artifacts import PredictionArtifactError
from . import relation_human_audit
from .relation_audit_results import (
    DevelopmentAuditEvaluation,
    RelationAuditResultError,
    evaluate_development_agreement,
)


ALLOWED_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
ARTIFACT_ROOT = ALLOWED_DATA_ROOT / "artifacts/audit-results"
ARTIFACT_ID = "gsm8k-relation-user-attested-development-20260725"
PACKET_DIR = (
    ALLOWED_DATA_ROOT
    / "data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c"
    / "human-audit-v1/explicit-marker-relation-only-v1/train"
)
INTAKE_DIR = (
    ALLOWED_DATA_ROOT
    / "artifacts/audit-intake/gsm8k-relation-v1/user-attested-20260725"
)
PACKET_MANIFEST_SHA256 = (
    "da5d7fb0659e1bb13aa1d6b03e59e83c5ddb42c05535932313552af7dcc19ecb"
)
AUDIT_ITEMS_SHA256 = (
    "0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113"
)
REVIEWER_A_SHA256 = (
    "99b95522c1f57156bd8f904c6d66e13b1ee9c6f6154988392b32ffdd8d5941ba"
)
REVIEWER_B_SHA256 = (
    "96c9c53561730d776834b5e7cc705a3274af82b2b2afd08faf1f1dc63cc67e67"
)
INTAKE_METADATA_SHA256 = (
    "a518d5076248ab3c137744308eea0c332e2103c98dccfd47bf024f618e786c13"
)
MANIFEST_SCHEMA_VERSION = "relation-development-audit-artifact-manifest-v1"
STATUS = "PASSED_DEVELOPMENT"
PROJECTION_NAME = "agreement-projection.jsonl"
RESULT_NAME = "audit-result.json"
MANIFEST_NAME = "manifest.json"
_PACKET_MANIFEST_NAME = "human-audit-manifest.json"
_ITEMS_NAME = "audit-items.jsonl"
_REVIEW_A_NAME = "20260725T012706_user-checked_formal-A.jsonl"
_REVIEW_A_SIDECAR = _REVIEW_A_NAME + ".sha256"
_REVIEW_B_NAME = "20260725T012706_user-checked_formal-B.jsonl"
_REVIEW_B_SIDECAR = _REVIEW_B_NAME + ".sha256"
_INTAKE_METADATA_NAME = "intake-metadata.json"
_PACKET_NAMES = {
    _ITEMS_NAME,
    _PACKET_MANIFEST_NAME,
    "review-instructions.md",
    "reviewer-a-template.jsonl",
    "reviewer-b-template.jsonl",
}
_INTAKE_NAMES = {
    _REVIEW_A_NAME,
    _REVIEW_A_SIDECAR,
    _REVIEW_B_NAME,
    _REVIEW_B_SIDECAR,
    _INTAKE_METADATA_NAME,
}
_OUTPUT_NAMES = {PROJECTION_NAME, RESULT_NAME, MANIFEST_NAME}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FILE_LIMIT = 8 * 1024 * 1024
_MANIFEST_LIMIT = 1 * 1024 * 1024


class DevelopmentAuditArtifactError(ValueError):
    """A private source, publication, or replay invariant failed."""


def _fail(message: str) -> None:
    raise DevelopmentAuditArtifactError(message) from None


@dataclass(frozen=True)
class AuditSources:
    packet_dir: Path
    intake_dir: Path
    packet_manifest_sha256: str
    audit_items_sha256: str
    reviewer_a_sha256: str
    reviewer_b_sha256: str
    intake_metadata_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.packet_dir, Path) or not isinstance(
            self.intake_dir, Path
        ):
            _fail("audit source paths are invalid")
        if any(
            not isinstance(value, str) or not _HEX64.fullmatch(value)
            for value in (
                self.packet_manifest_sha256,
                self.audit_items_sha256,
                self.reviewer_a_sha256,
                self.reviewer_b_sha256,
                self.intake_metadata_sha256,
            )
        ):
            _fail("audit source hash is invalid")


PRODUCTION_SOURCES = AuditSources(
    packet_dir=PACKET_DIR,
    intake_dir=INTAKE_DIR,
    packet_manifest_sha256=PACKET_MANIFEST_SHA256,
    audit_items_sha256=AUDIT_ITEMS_SHA256,
    reviewer_a_sha256=REVIEWER_A_SHA256,
    reviewer_b_sha256=REVIEWER_B_SHA256,
    intake_metadata_sha256=INTAKE_METADATA_SHA256,
)


@dataclass(frozen=True)
class VerifiedDevelopmentAuditArtifact:
    artifact_id: str
    result: Mapping[str, Any]
    projection_sha256: str
    result_file_sha256: str
    result_semantic_sha256: str
    manifest_sha256: str
    artifact_path: Path


@dataclass(frozen=True)
class _SourceSnapshot:
    item_ids: tuple[str, ...]
    reviewer_a: bytes
    reviewer_b: bytes
    manifest_binding: Mapping[str, Any]


def _private_directory(path: Path, name: str) -> None:
    try:
        info = path.lstat()
    except OSError:
        _fail(f"{name} is unavailable")
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        _fail(f"{name} metadata is invalid")


def _namespace(path: Path, expected: set[str], name: str) -> None:
    _private_directory(path, name)
    try:
        names = {entry.name for entry in os.scandir(path)}
    except OSError:
        _fail(f"{name} cannot be scanned")
    if names != expected:
        _fail(f"{name} namespace differs")


def _directory_binding(path: Path, name: str) -> tuple[int, ...]:
    _private_directory(path, name)
    try:
        info = path.lstat()
    except OSError:
        _fail(f"{name} metadata is unavailable")
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read(path: Path, limit: int, name: str) -> bytes:
    try:
        return artifact_io._read_artifact_file(path, limit, name)
    except PredictionArtifactError as error:
        raise DevelopmentAuditArtifactError(f"{name} file is invalid") from error


def _canonical_object(payload: bytes, name: str) -> Mapping[str, Any]:
    try:
        return artifact_io._canonical_object(payload, name)
    except PredictionArtifactError as error:
        raise DevelopmentAuditArtifactError(f"{name} is invalid") from error


def _hash(payload: bytes, expected: str, name: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected:
        _fail(f"{name} SHA256 differs")


def _item_ids(payload: bytes) -> tuple[str, ...]:
    if not payload or not payload.endswith(b"\n"):
        _fail("audit items are not LF-delimited JSONL")
    result: list[str] = []
    for index, raw in enumerate(payload.splitlines(keepends=True), start=1):
        if not raw.endswith(b"\n") or len(raw) > 64 * 1024:
            _fail("audit item line framing differs")
        try:
            value = artifact_io._strict_json(raw[:-1], f"audit item {index}")
        except PredictionArtifactError as error:
            raise DevelopmentAuditArtifactError("audit item JSON is invalid") from error
        if not isinstance(value, Mapping):
            _fail("audit item is not an object")
        if canonical_json(value).encode("utf-8") + b"\n" != raw:
            _fail("audit item is not canonical JSON")
        item_id = value.get("audit_item_id")
        if not isinstance(item_id, str) or not item_id:
            _fail("audit item ID is invalid")
        result.append(item_id)
    if len(result) != relation_human_audit.SAMPLE_SIZE or len(set(result)) != len(
        result
    ):
        _fail("audit item coverage differs")
    return tuple(result)


def _source_snapshot(sources: AuditSources) -> _SourceSnapshot:
    _namespace(sources.packet_dir, _PACKET_NAMES, "human audit packet")
    _namespace(sources.intake_dir, _INTAKE_NAMES, "private audit intake")
    packet_binding = _directory_binding(sources.packet_dir, "human audit packet")
    intake_binding = _directory_binding(sources.intake_dir, "private audit intake")
    packet_manifest = _read(
        sources.packet_dir / _PACKET_MANIFEST_NAME,
        _MANIFEST_LIMIT,
        _PACKET_MANIFEST_NAME,
    )
    items = _read(sources.packet_dir / _ITEMS_NAME, _FILE_LIMIT, _ITEMS_NAME)
    reviewer_a = _read(sources.intake_dir / _REVIEW_A_NAME, _FILE_LIMIT, _REVIEW_A_NAME)
    reviewer_b = _read(sources.intake_dir / _REVIEW_B_NAME, _FILE_LIMIT, _REVIEW_B_NAME)
    sidecar_a = _read(
        sources.intake_dir / _REVIEW_A_SIDECAR, 128, _REVIEW_A_SIDECAR
    )
    sidecar_b = _read(
        sources.intake_dir / _REVIEW_B_SIDECAR, 128, _REVIEW_B_SIDECAR
    )
    metadata = _read(
        sources.intake_dir / _INTAKE_METADATA_NAME,
        _MANIFEST_LIMIT,
        _INTAKE_METADATA_NAME,
    )
    for payload, expected, name in (
        (packet_manifest, sources.packet_manifest_sha256, "packet manifest"),
        (items, sources.audit_items_sha256, "audit items"),
        (reviewer_a, sources.reviewer_a_sha256, "reviewer A"),
        (reviewer_b, sources.reviewer_b_sha256, "reviewer B"),
        (metadata, sources.intake_metadata_sha256, "intake metadata"),
    ):
        _hash(payload, expected, name)
    if sidecar_a != (sources.reviewer_a_sha256 + "\n").encode("ascii"):
        _fail("reviewer A sidecar differs")
    if sidecar_b != (sources.reviewer_b_sha256 + "\n").encode("ascii"):
        _fail("reviewer B sidecar differs")
    metadata_value = _canonical_object(metadata, "intake metadata")
    if (
        metadata_value.get("provenance_status")
        != "USER_ATTESTED / INDEPENDENCE_UNVERIFIED"
        or metadata_value.get("human_independence_verified") is not False
        or metadata_value.get("packet_manifest_sha256")
        != sources.packet_manifest_sha256
        or metadata_value.get("audit_items_sha256") != sources.audit_items_sha256
    ):
        _fail("intake metadata provenance differs")
    _namespace(sources.packet_dir, _PACKET_NAMES, "human audit packet")
    _namespace(sources.intake_dir, _INTAKE_NAMES, "private audit intake")
    if packet_binding != _directory_binding(
        sources.packet_dir, "human audit packet"
    ) or intake_binding != _directory_binding(
        sources.intake_dir, "private audit intake"
    ):
        _fail("audit source directory changed while reading")
    ids = _item_ids(items)
    return _SourceSnapshot(
        item_ids=ids,
        reviewer_a=reviewer_a,
        reviewer_b=reviewer_b,
        manifest_binding={
            "packet": {
                "path": str(sources.packet_dir),
                "manifest_sha256": sources.packet_manifest_sha256,
                "audit_items_sha256": sources.audit_items_sha256,
                "sample_size": len(ids),
            },
            "intake": {
                "path": str(sources.intake_dir),
                "metadata_sha256": sources.intake_metadata_sha256,
                "provenance_status": "USER_ATTESTED / INDEPENDENCE_UNVERIFIED",
                "human_independence_verified": False,
                "reviewer_a": {
                    "filename": _REVIEW_A_NAME,
                    "byte_size": len(reviewer_a),
                    "sha256": sources.reviewer_a_sha256,
                },
                "reviewer_b": {
                    "filename": _REVIEW_B_NAME,
                    "byte_size": len(reviewer_b),
                    "sha256": sources.reviewer_b_sha256,
                },
            },
        },
    )


def _payload(value: Mapping[str, Any], name: str, limit: int) -> bytes:
    try:
        payload = canonical_json(value).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise DevelopmentAuditArtifactError(f"{name} cannot be serialized") from error
    if len(payload) > limit:
        _fail(f"{name} exceeds its byte limit")
    return payload


def _evaluate(snapshot: _SourceSnapshot, sources: AuditSources) -> DevelopmentAuditEvaluation:
    try:
        return evaluate_development_agreement(
            expected_item_ids=snapshot.item_ids,
            packet_manifest_sha256=sources.packet_manifest_sha256,
            audit_items_sha256=sources.audit_items_sha256,
            reviewer_a_payload=snapshot.reviewer_a,
            reviewer_b_payload=snapshot.reviewer_b,
        )
    except RelationAuditResultError as error:
        raise DevelopmentAuditArtifactError("development audit evaluation failed") from error


def _manifest_value(
    execution_commit: str,
    snapshot: _SourceSnapshot,
    evaluation: DevelopmentAuditEvaluation,
    projection_payload: bytes,
    result_payload: bytes,
) -> Mapping[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": STATUS,
        "artifact_id": ARTIFACT_ID,
        "execution_commit": execution_commit,
        "paper_metric_eligible": False,
        "human_independence_verified": False,
        "sources": snapshot.manifest_binding,
        "outputs": {
            PROJECTION_NAME: {
                "byte_size": len(projection_payload),
                "record_count": relation_human_audit.SAMPLE_SIZE,
                "sha256": hashlib.sha256(projection_payload).hexdigest(),
            },
            RESULT_NAME: {
                "byte_size": len(result_payload),
                "semantic_sha256": evaluation.result.sha256,
                "sha256": hashlib.sha256(result_payload).hexdigest(),
            },
        },
    }


def _prepare_root(root: Path) -> None:
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or not root.is_relative_to(ALLOWED_DATA_ROOT)
    ):
        _fail("development audit root is outside the allowed data path")
    _private_directory(root.parent, "development audit root parent")
    try:
        artifact_io._prepare_root(root)
    except (PredictionArtifactError, OSError) as error:
        raise DevelopmentAuditArtifactError("artifact root cannot be prepared") from error


def _verify(
    root: Path,
    sources: AuditSources,
    expected_commit: str | None = None,
) -> VerifiedDevelopmentAuditArtifact:
    _private_directory(root, "development audit root")
    target = root / ARTIFACT_ID
    _namespace(target, _OUTPUT_NAMES, "development audit artifact")
    target_binding = _directory_binding(target, "development audit artifact")
    projection = _read(target / PROJECTION_NAME, _FILE_LIMIT, PROJECTION_NAME)
    result_payload = _read(target / RESULT_NAME, _MANIFEST_LIMIT, RESULT_NAME)
    manifest_payload = _read(target / MANIFEST_NAME, _MANIFEST_LIMIT, MANIFEST_NAME)
    result_value = _canonical_object(result_payload, "development audit result")
    manifest_value = _canonical_object(manifest_payload, "development audit manifest")
    execution_commit = manifest_value.get("execution_commit")
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("development audit execution commit is invalid")
    if expected_commit is not None and execution_commit != expected_commit:
        _fail("development audit execution commit differs")
    snapshot = _source_snapshot(sources)
    evaluation = _evaluate(snapshot, sources)
    expected_result = _payload(
        evaluation.result.to_dict(), "development audit result", _MANIFEST_LIMIT
    )
    if projection != evaluation.projection_payload:
        _fail("agreement projection differs from source replay")
    if result_payload != expected_result or result_value != evaluation.result.to_dict():
        _fail("development audit result differs from source replay")
    expected_manifest = _manifest_value(
        execution_commit,
        snapshot,
        evaluation,
        evaluation.projection_payload,
        expected_result,
    )
    if manifest_value != expected_manifest:
        _fail("development audit manifest differs from source replay")
    if not evaluation.result.development_gate_passed:
        _fail("development audit gate is not passed")
    _namespace(target, _OUTPUT_NAMES, "development audit artifact")
    if target_binding != _directory_binding(target, "development audit artifact"):
        _fail("development audit artifact changed while reading")
    return VerifiedDevelopmentAuditArtifact(
        artifact_id=ARTIFACT_ID,
        result=result_value,
        projection_sha256=hashlib.sha256(projection).hexdigest(),
        result_file_sha256=hashlib.sha256(result_payload).hexdigest(),
        result_semantic_sha256=evaluation.result.sha256,
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_path=target,
    )


def _publish(
    root: Path,
    sources: AuditSources,
    execution_commit: str,
    git_gate: Callable[[str], None],
) -> VerifiedDevelopmentAuditArtifact:
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("execution commit is invalid")
    git_gate(execution_commit)
    snapshot = _source_snapshot(sources)
    evaluation = _evaluate(snapshot, sources)
    if not evaluation.result.development_gate_passed:
        _fail("development audit gate is blocked")
    result_payload = _payload(
        evaluation.result.to_dict(), "development audit result", _MANIFEST_LIMIT
    )
    manifest_payload = _payload(
        _manifest_value(
            execution_commit,
            snapshot,
            evaluation,
            evaluation.projection_payload,
            result_payload,
        ),
        "development audit manifest",
        _MANIFEST_LIMIT,
    )
    _prepare_root(root)
    target = root / ARTIFACT_ID
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("development audit artifact already exists")
    except OSError as error:
        raise DevelopmentAuditArtifactError("artifact directory cannot be created") from error
    try:
        artifact_io._write_exclusive(target / PROJECTION_NAME, evaluation.projection_payload)
        artifact_io._write_exclusive(target / RESULT_NAME, result_payload)
        artifact_io._fsync_directory(target)
        git_gate(execution_commit)
        artifact_io._write_exclusive(target / MANIFEST_NAME, manifest_payload)
        artifact_io._fsync_directory(target)
        artifact_io._fsync_directory(root)
    except (PredictionArtifactError, OSError) as error:
        raise DevelopmentAuditArtifactError(
            "development audit publication failed; partial state is retained"
        ) from error
    return _verify(root, sources, execution_commit)


def publish(execution_commit: str) -> VerifiedDevelopmentAuditArtifact:
    packet = relation_human_audit.verify()
    if packet.get("manifest_sha256") != PACKET_MANIFEST_SHA256:
        _fail("production human-audit packet verification differs")
    return _publish(ARTIFACT_ROOT, PRODUCTION_SOURCES, execution_commit, artifact_io._git_gate)


def verify(expected_commit: str | None = None) -> VerifiedDevelopmentAuditArtifact:
    packet = relation_human_audit.verify()
    if packet.get("manifest_sha256") != PACKET_MANIFEST_SHA256:
        _fail("production human-audit packet verification differs")
    return _verify(ARTIFACT_ROOT, PRODUCTION_SOURCES, expected_commit)


def _summary(value: VerifiedDevelopmentAuditArtifact) -> Mapping[str, Any]:
    return {
        "artifact_id": value.artifact_id,
        "artifact_path": str(value.artifact_path),
        "manifest_sha256": value.manifest_sha256,
        "projection_sha256": value.projection_sha256,
        "result_file_sha256": value.result_file_sha256,
        "result_semantic_sha256": value.result_semantic_sha256,
        "status": value.result["status"],
        "provenance_status": value.result["provenance_status"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--execution-commit", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--expected-commit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "publish":
            value = publish(arguments.execution_commit)
        else:
            value = verify(arguments.expected_commit)
    except DevelopmentAuditArtifactError as error:
        print(f"development audit artifact failed: {error}", file=sys.stderr)
        return 1
    print(canonical_json(_summary(value)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_ID",
    "ARTIFACT_ROOT",
    "AuditSources",
    "DevelopmentAuditArtifactError",
    "VerifiedDevelopmentAuditArtifact",
    "publish",
    "verify",
]
