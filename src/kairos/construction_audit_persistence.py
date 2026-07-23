"""Immutable JSONL publication for GSM8K construction-audit records.

This module persists records that were already produced by D-011/D-012.  It
does not select a temporal subset or run construction itself.  Publication is
manifest-last and never replaces an existing target.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence

from .construction import ConstructionTerminal
from .construction_audit import ConstructionAuditRecord
from .ids import canonical_json
from .io import compute_funnel
from .schema import TemporalExample


REVISION = "3101c7d5072418e28b9008a6636bde82a006892c"
_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
_REPO_ROOT = Path("/home/yangbin/zx-tmp/kairos")
_SOURCE_DIR_REL = f"data/processed/gsm8k/{REVISION}/source-record-v1"
_SOURCE_MANIFEST_REL = f"{_SOURCE_DIR_REL}/processed-manifest.json"
_SOURCE_MANIFEST_SHA256 = (
    "48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe"
)
_RAW_DIR_REL = f"data/raw/gsm8k/{REVISION}"
_COMPLETION_REL = f"{_RAW_DIR_REL}/completion-manifest.json"
_COMPLETION_SHA256 = (
    "d8861250e197bf04e1f24fee4dbb7fe07194f485095f77cdcc8669412e35047"
)
_SHA256SUMS_REL = f"{_RAW_DIR_REL}/SHA256SUMS"
_SHA256SUMS_SHA256 = (
    "fb6bb5349ea5a620062f34cda78eb4faed2aa8a6ec9cf43ad54010904b813107"
)
_FORMAL_TREE_SHA256 = (
    "6b52e122a14c0f78baf3fc0b046b312b780518771828702acf074ab8ac95583f"
)
_LICENSE_REL = (
    f"{_RAW_DIR_REL}/extracted/grade-school-math-{REVISION}/LICENSE"
)
_TARGET_PARENT_REL = (
    f"data/processed/gsm8k/{REVISION}/construction-audit-v1/"
    "explicit-marker-construction-v0"
)
_AUDIT_NAME = "construction-audit.jsonl"
_MANIFEST_NAME = "construction-audit-manifest.json"
_MANIFEST_SCHEMA = "construction-audit-publication-manifest-v1"
_MODULE_VERSION = "construction-audit-persistence-v1"
_CANONICAL_JSON_VERSION = "kairos-canonical-json-v1"
_ORDERING_VERSION = "input-order-contiguous-zero-based-v1"
_ARTIFACT_ID = "PROC-P01-GSM8K-20260722"
_LINE_PAYLOAD_LIMIT = 16_777_216
_LINE_PHYSICAL_LIMIT = _LINE_PAYLOAD_LIMIT + 1
_TOTAL_BYTE_LIMIT = 2_147_483_648
_MANIFEST_BYTE_LIMIT = 1_048_576
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_SPLITS = {
    "train": {
        "path": f"{_SOURCE_DIR_REL}/examples-train.jsonl",
        "sha256": "485ef8996a700958a327ed5888467f630274ecff105249f88b008e8cf88d5be2",
        "byte_size": 7_236_805,
        "record_count": 7_473,
    },
    "test": {
        "path": f"{_SOURCE_DIR_REL}/examples-test.jsonl",
        "sha256": "b0b14552e13e6390a8e40187e76d5f65e2d29e49146e4757a10759ba98cd1a97",
        "byte_size": 1_286_440,
        "record_count": 1_319,
    },
}


class ConstructionAuditPersistenceError(ValueError):
    """A persistence, publication, or verification invariant failed."""


class ObserverState(str, Enum):
    ABSENT = "ABSENT"
    PARTIAL_NO_MANIFEST = "PARTIAL_NO_MANIFEST"
    MANIFEST_PRESENT_UNVERIFIED = "MANIFEST_PRESENT_UNVERIFIED"
    STRUCTURALLY_VERIFIED = "STRUCTURALLY_VERIFIED"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True)
class _SourceFacts:
    path: str
    sha256: str
    byte_size: int
    record_count: int


@dataclass(frozen=True)
class _Layout:
    data_root: Path
    repo_root: Path
    target_parent_rel: str
    source_manifest_rel: str
    source_manifest_sha256: str
    completion_rel: str
    completion_sha256: str
    sha256sums_rel: str
    sha256sums_sha256: str
    formal_tree_sha256: str
    license_rel: str
    splits: Mapping[str, _SourceFacts]


_PRODUCTION_LAYOUT = _Layout(
    data_root=_DATA_ROOT,
    repo_root=_REPO_ROOT,
    target_parent_rel=_TARGET_PARENT_REL,
    source_manifest_rel=_SOURCE_MANIFEST_REL,
    source_manifest_sha256=_SOURCE_MANIFEST_SHA256,
    completion_rel=_COMPLETION_REL,
    completion_sha256=_COMPLETION_SHA256,
    sha256sums_rel=_SHA256SUMS_REL,
    sha256sums_sha256=_SHA256SUMS_SHA256,
    formal_tree_sha256=_FORMAL_TREE_SHA256,
    license_rel=_LICENSE_REL,
    splits={key: _SourceFacts(**value) for key, value in _SPLITS.items()},
)


def _fail(message: str) -> None:
    raise ConstructionAuditPersistenceError(message) from None


def _sha256_file(path: Path, limit: int) -> tuple[str, int]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail("bound input is not a single-link regular file")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while True:
                block = handle.read(min(1 << 20, limit - size + 1))
                if not block:
                    break
                size += len(block)
                if size > limit:
                    _fail("bound input exceeds its byte limit")
                digest.update(block)
        after = path.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        _fail("bound input cannot be read")
    if before != after:
        _fail("bound input changed while reading")
    return digest.hexdigest(), size


def _strict_json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    duplicates: list[str] = []

    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    def constant(_: str) -> Any:
        _fail(f"{label} contains a non-finite number")

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(f"{label} is not strict UTF-8 JSON")
    if duplicates or not isinstance(value, Mapping):
        _fail(f"{label} is not a unique-key JSON object")
    return value


def _canonical_object_file(path: Path, expected_sha256: str) -> Mapping[str, Any]:
    digest, size = _sha256_file(path, _MANIFEST_BYTE_LIMIT)
    if digest != expected_sha256:
        _fail("bound manifest SHA256 differs")
    payload = path.read_bytes()
    if len(payload) != size or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        _fail("bound manifest must be one LF-terminated JSON object")
    value = _strict_json_object(payload[:-1], "bound manifest")
    if canonical_json(value).encode("utf-8") + b"\n" != payload:
        _fail("bound manifest is not canonical")
    return value


def _validate_split(official_split: str, layout: _Layout) -> _SourceFacts:
    if not isinstance(official_split, str) or official_split not in layout.splits:
        _fail("official split must be train or test")
    return layout.splits[official_split]


def _validate_execution_commit(execution_commit: str) -> None:
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("execution commit must be lowercase 40-hex")


def _run_git(repo_root: Path, arguments: Sequence[str], timeout: float, limit: int) -> bytes:
    command = [
        "/usr/bin/git",
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repo_root),
        *arguments,
    ]
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            cwd=repo_root,
            check=False,
            timeout=timeout,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("Git provenance gate failed")
    if (
        result.returncode != 0
        or result.stderr
        or len(result.stdout) > limit
    ):
        _fail("Git provenance gate failed")
    return result.stdout


def _git_gate(layout: _Layout, execution_commit: str) -> None:
    _validate_execution_commit(execution_commit)
    first = _run_git(layout.repo_root, ("rev-parse", "--verify", "HEAD"), 5.0, 128)
    status = _run_git(
        layout.repo_root,
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--ignore-submodules=none",
        ),
        10.0,
        1_048_576,
    )
    second = _run_git(layout.repo_root, ("rev-parse", "--verify", "HEAD"), 5.0, 128)
    expected = execution_commit.encode("ascii") + b"\n"
    if first != expected or second != expected or status:
        _fail("Git provenance gate failed")


def _relative_components(value: str) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or len(value.encode("utf-8")) > 4096
    ):
        _fail("internal relative path is invalid")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} or len(part.encode("utf-8")) > 255 for part in parts):
        _fail("internal relative path is invalid")
    return parts


def _checked_path(layout: _Layout, relative: str, *, regular: bool) -> Path:
    parts = _relative_components(relative)
    current = layout.data_root
    try:
        root_info = current.lstat()
        if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.geteuid():
            _fail("data root binding is unsafe")
        for index, part in enumerate(parts):
            current = current / part
            info = current.lstat()
            final = index == len(parts) - 1
            if stat.S_ISLNK(info.st_mode):
                _fail("bound path contains a symbolic link")
            if final and regular:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    _fail("bound path is not a single-link regular file")
            elif not stat.S_ISDIR(info.st_mode):
                _fail("bound path component is not a directory")
            if info.st_uid != os.geteuid():
                _fail("bound path owner differs")
    except (FileNotFoundError, PermissionError, OSError):
        _fail("bound path cannot be inspected")
    return current


def _source_gate(layout: _Layout, official_split: str) -> tuple[_SourceFacts, str]:
    facts = _validate_split(official_split, layout)
    manifest_path = _checked_path(layout, layout.source_manifest_rel, regular=True)
    manifest = _canonical_object_file(manifest_path, layout.source_manifest_sha256)
    try:
        output = manifest["outputs"][f"example_{official_split}"]
        expected_output = {
            "path": Path(facts.path).name,
            "byte_size": facts.byte_size,
            "record_count": facts.record_count,
            "sha256": facts.sha256,
        }
        if (
            manifest["status"] != "COMPLETE"
            or manifest["dataset"] != "gsm8k"
            or manifest["revision"] != REVISION
            or output != expected_output
        ):
            _fail("processed source manifest binding differs")
    except (KeyError, TypeError):
        _fail("processed source manifest binding differs")
    completion = _checked_path(layout, layout.completion_rel, regular=True)
    if _sha256_file(completion, _MANIFEST_BYTE_LIMIT)[0] != layout.completion_sha256:
        _fail("acquisition completion binding differs")
    sha256sums = _checked_path(layout, layout.sha256sums_rel, regular=True)
    if _sha256_file(sha256sums, _MANIFEST_BYTE_LIMIT)[0] != layout.sha256sums_sha256:
        _fail("SHA256SUMS binding differs")
    license_path = _checked_path(layout, layout.license_rel, regular=True)
    license_sha256, _ = _sha256_file(license_path, _MANIFEST_BYTE_LIMIT)
    source_path = _checked_path(layout, facts.path, regular=True)
    digest, size = _sha256_file(source_path, max(facts.byte_size, 1))
    if digest != facts.sha256 or size != facts.byte_size:
        _fail("processed source JSONL binding differs")
    return facts, license_sha256


def _ensure_target_parent(layout: _Layout) -> Path:
    parts = _relative_components(layout.target_parent_rel)
    current = layout.data_root
    for part in parts:
        candidate = current / part
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            try:
                candidate.mkdir(mode=0o700)
                parent_fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                info = candidate.lstat()
            except (FileExistsError, PermissionError, OSError):
                _fail("publication parent creation failed")
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            _fail("publication parent binding is unsafe")
        current = candidate
    return current


def _target_path(layout: _Layout, official_split: str) -> Path:
    _validate_split(official_split, layout)
    return layout.data_root / layout.target_parent_rel / official_split


def _create_target(layout: _Layout, official_split: str) -> Path:
    parent = _ensure_target_parent(layout)
    target = parent / official_split
    try:
        target.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        _fail("construction audit publication target already exists")
    except (PermissionError, OSError):
        _fail("construction audit publication preflight failed")
    info = target.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        _fail("construction audit publication blocked partial")
    return target


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            _fail("construction audit publication blocked partial")
        view = view[written:]


def _publish_bytes(target: Path, final_name: str, payload: bytes) -> None:
    directory_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".kairos-{final_name}.{secrets.token_hex(16)}.tmp"
    fd = -1
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.link(temporary, final_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
        info = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size != len(payload)
        ):
            _fail("construction audit publication blocked partial")
    except FileExistsError:
        _fail("construction audit publication blocked partial")
    except (PermissionError, OSError):
        _fail("construction audit publication blocked partial")
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _read_source_line(handle: Any, limit: int, line_number: int) -> bytes:
    line = handle.readline(limit + 2)
    if len(line) > limit + 1:
        _fail(f"source line {line_number} exceeds its byte limit")
    if line and not line.endswith(b"\n"):
        _fail(f"source line {line_number} lacks LF")
    return line


def _source_example(line: bytes, line_number: int) -> TemporalExample:
    value = _strict_json_object(line[:-1], f"source line {line_number}")
    if canonical_json(value).encode("utf-8") + b"\n" != line:
        _fail(f"source line {line_number} is not canonical")
    try:
        return TemporalExample.from_dict(value)
    except (TypeError, ValueError):
        _fail(f"source line {line_number} has invalid schema")


def _scan_records(
    records: Iterable[ConstructionAuditRecord],
    source_path: Path,
    expected_count: int,
) -> tuple[bytes, Mapping[str, int], Mapping[str, int], Mapping[str, int], int]:
    output = bytearray()
    terminals: Counter[str] = Counter()
    input_ids: set[str] = set()
    audit_ids: set[str] = set()
    fingerprints: set[str] = set()
    outcomes = []
    maximum = 0
    try:
        iterator = iter(records)
    except TypeError:
        _fail("records must be iterable")
    with source_path.open("rb") as source:
        for index in range(expected_count):
            source_line = _read_source_line(source, _LINE_PHYSICAL_LIMIT, index + 1)
            if not source_line:
                _fail("processed source ended before its manifest count")
            try:
                record = next(iterator)
            except StopIteration:
                _fail("audit record stream ended before source")
            if not isinstance(record, ConstructionAuditRecord):
                _fail("audit stream contains a non-audit record")
            if record.input_order != index:
                _fail("audit input order is not contiguous zero-based")
            if record.input != _source_example(source_line, index + 1):
                _fail("audit input differs from the bound source record")
            if record.input.record_id in input_ids:
                _fail("audit input record ID is duplicated")
            if record.audit_record_id in audit_ids:
                _fail("audit record ID is duplicated")
            if record.record_fingerprint_sha256 in fingerprints:
                _fail("audit record fingerprint is duplicated")
            input_ids.add(record.input.record_id)
            audit_ids.add(record.audit_record_id)
            fingerprints.add(record.record_fingerprint_sha256)
            terminals[record.terminal.value] += 1
            outcomes.append(record.outcome)
            line = canonical_json(record.to_dict()).encode("utf-8") + b"\n"
            if len(line) > _LINE_PHYSICAL_LIMIT:
                _fail("audit JSONL line exceeds its byte limit")
            if len(output) + len(line) > _TOTAL_BYTE_LIMIT:
                _fail("audit JSONL exceeds its total byte limit")
            output.extend(line)
            maximum = max(maximum, len(line))
        if _read_source_line(source, _LINE_PHYSICAL_LIMIT, expected_count + 1):
            _fail("processed source exceeds its manifest count")
    try:
        next(iterator)
    except StopIteration:
        pass
    else:
        _fail("audit record stream exceeds source")
    funnel = compute_funnel(outcomes)
    terminal_counts = {terminal.value: terminals[terminal.value] for terminal in ConstructionTerminal}
    funnel_values = {
        "raw": funnel.raw,
        "temporal_filtered": funnel.temporal_filtered,
        "event_extraction_success": funnel.event_extraction_success,
        "reliable_relation_labels": funnel.reliable_relation_labels,
        "valid_counterfactuals": funnel.valid_counterfactuals,
        "final_retained": funnel.final_retained,
    }
    identities = {
        "input_record_id_unique_count": len(input_ids),
        "audit_record_id_unique_count": len(audit_ids),
        "record_fingerprint_unique_count": len(fingerprints),
    }
    return bytes(output), terminal_counts, funnel_values, identities, maximum


def _license_values(layout: _Layout, license_sha256: str) -> Mapping[str, Any]:
    return {
        "spdx_id": "MIT",
        "upstream_name": "GSM8K",
        "upstream_repository": "https://github.com/openai/grade-school-math",
        "upstream_revision": REVISION,
        "license_path": layout.license_rel,
        "license_sha256": license_sha256,
        "attribution_notice": (
            "GSM8K dataset from OpenAI grade-school-math, revision "
            f"{REVISION}; licensed under the MIT terms in the bound LICENSE file."
        ),
        "derivative_notice": (
            "Independent Kairos explicit-marker construction audit generated by "
            "explicit-marker-construction-v0; derived record content is identified "
            "by this manifest."
        ),
    }


def _manifest_values(
    layout: _Layout,
    official_split: str,
    facts: _SourceFacts,
    execution_commit: str,
    license_sha256: str,
    payload: bytes,
    terminal_counts: Mapping[str, int],
    funnel: Mapping[str, int],
    identities: Mapping[str, int],
    maximum_line: int,
) -> Mapping[str, Any]:
    return {
        "status": "COMPLETE",
        "schema_version": _MANIFEST_SCHEMA,
        "dataset": "gsm8k",
        "revision": REVISION,
        "official_split": official_split,
        "source": {
            "artifact_id": _ARTIFACT_ID,
            "artifact_manifest_path": layout.source_manifest_rel,
            "artifact_manifest_sha256": layout.source_manifest_sha256,
            "acquisition_completion_path": layout.completion_rel,
            "acquisition_completion_sha256": layout.completion_sha256,
            "sha256sums_path": layout.sha256sums_rel,
            "sha256sums_sha256": layout.sha256sums_sha256,
            "formal_tree_fingerprint_sha256": layout.formal_tree_sha256,
            "record_path": facts.path,
            "record_schema_version": "kairos-temporal-example-v1",
            "record_sha256": facts.sha256,
            "record_byte_size": facts.byte_size,
            "record_count": facts.record_count,
            "license": _license_values(layout, license_sha256),
        },
        "publisher": {
            "execution_commit": execution_commit,
            "module_version": _MODULE_VERSION,
            "record_schema_version": "construction-audit-v1",
            "construction_version": "explicit-marker-construction-v0",
            "canonical_json_version": _CANONICAL_JSON_VERSION,
            "ordering_version": _ORDERING_VERSION,
        },
        "output": {
            "path": _AUDIT_NAME,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byte_size": len(payload),
            "record_count": facts.record_count,
            "max_observed_physical_line_bytes": maximum_line,
            "physical_line_byte_limit": _LINE_PHYSICAL_LIMIT,
        },
        "identity": dict(identities),
        "terminal_counts": dict(terminal_counts),
        "funnel": dict(funnel),
    }


def _validate_manifest_shape(value: Mapping[str, Any]) -> None:
    expected = {
        "status", "schema_version", "dataset", "revision", "official_split",
        "source", "publisher", "output", "identity", "terminal_counts", "funnel",
    }
    if set(value) != expected:
        _fail("construction audit manifest keys differ")
    if (
        value.get("status") != "COMPLETE"
        or value.get("schema_version") != _MANIFEST_SCHEMA
        or value.get("dataset") != "gsm8k"
        or value.get("revision") != REVISION
    ):
        _fail("construction audit manifest literals differ")
    nested_keys = {
        "source": {
            "artifact_id", "artifact_manifest_path", "artifact_manifest_sha256",
            "acquisition_completion_path", "acquisition_completion_sha256",
            "sha256sums_path", "sha256sums_sha256",
            "formal_tree_fingerprint_sha256", "record_path",
            "record_schema_version", "record_sha256", "record_byte_size",
            "record_count", "license",
        },
        "publisher": {
            "execution_commit", "module_version", "record_schema_version",
            "construction_version", "canonical_json_version", "ordering_version",
        },
        "output": {
            "path", "sha256", "byte_size", "record_count",
            "max_observed_physical_line_bytes", "physical_line_byte_limit",
        },
        "identity": {
            "input_record_id_unique_count", "audit_record_id_unique_count",
            "record_fingerprint_unique_count",
        },
        "terminal_counts": {terminal.value for terminal in ConstructionTerminal},
        "funnel": {
            "raw", "temporal_filtered", "event_extraction_success",
            "reliable_relation_labels", "valid_counterfactuals", "final_retained",
        },
    }
    for key, keys in nested_keys.items():
        nested = value.get(key)
        if not isinstance(nested, Mapping) or set(nested) != keys:
            _fail("construction audit manifest nested keys differ")
    license_value = value["source"].get("license")
    if not isinstance(license_value, Mapping) or set(license_value) != {
        "spdx_id", "upstream_name", "upstream_repository", "upstream_revision",
        "license_path", "license_sha256", "attribution_notice", "derivative_notice",
    }:
        _fail("construction audit manifest license keys differ")


def _publish_layout(
    layout: _Layout,
    records: Iterable[ConstructionAuditRecord],
    official_split: str,
    execution_commit: str,
    git_gate: Callable[[_Layout, str], None] = _git_gate,
) -> Mapping[str, Any]:
    facts, license_sha256 = _source_gate(layout, official_split)
    git_gate(layout, execution_commit)
    source_path = layout.data_root / facts.path
    payload, terminals, funnel, identities, maximum = _scan_records(
        records, source_path, facts.record_count
    )
    target = _create_target(layout, official_split)
    _publish_bytes(target, _AUDIT_NAME, payload)
    git_gate(layout, execution_commit)
    manifest = _manifest_values(
        layout, official_split, facts, execution_commit, license_sha256,
        payload, terminals, funnel, identities, maximum,
    )
    _validate_manifest_shape(manifest)
    manifest_bytes = canonical_json(manifest).encode("utf-8") + b"\n"
    if len(manifest_bytes) > _MANIFEST_BYTE_LIMIT:
        _fail("construction audit manifest exceeds its byte limit")
    _publish_bytes(target, _MANIFEST_NAME, manifest_bytes)
    result = _verify_layout(layout, official_split)
    git_gate(layout, execution_commit)
    return result


def _read_audit_payload(path: Path, limit: int) -> bytes:
    digest, size = _sha256_file(path, limit)
    del digest
    payload = path.read_bytes()
    if len(payload) != size:
        _fail("construction audit output changed while reading")
    return payload


def _verify_layout(layout: _Layout, official_split: str) -> Mapping[str, Any]:
    facts, license_sha256 = _source_gate(layout, official_split)
    target = _target_path(layout, official_split)
    try:
        target_info = target.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        _fail("construction audit verification failed")
    if (
        not stat.S_ISDIR(target_info.st_mode)
        or stat.S_ISLNK(target_info.st_mode)
        or target_info.st_uid != os.geteuid()
        or stat.S_IMODE(target_info.st_mode) != 0o700
    ):
        _fail("construction audit verification failed")
    try:
        names = {entry.name for entry in os.scandir(target)}
    except (PermissionError, OSError):
        _fail("construction audit verification failed")
    if names != {_AUDIT_NAME, _MANIFEST_NAME}:
        _fail("construction audit verification failed")
    for name in (_AUDIT_NAME, _MANIFEST_NAME):
        try:
            info = (target / name).lstat()
        except (FileNotFoundError, PermissionError, OSError):
            _fail("construction audit verification failed")
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            _fail("construction audit verification failed")
    manifest_path = target / _MANIFEST_NAME
    manifest_payload = _read_audit_payload(manifest_path, _MANIFEST_BYTE_LIMIT)
    if not manifest_payload.endswith(b"\n") or manifest_payload.count(b"\n") != 1:
        _fail("construction audit verification failed")
    manifest = _strict_json_object(manifest_payload[:-1], "construction audit manifest")
    if canonical_json(manifest).encode("utf-8") + b"\n" != manifest_payload:
        _fail("construction audit verification failed")
    _validate_manifest_shape(manifest)
    audit_path = target / _AUDIT_NAME
    payload = _read_audit_payload(audit_path, _TOTAL_BYTE_LIMIT)
    source_path = layout.data_root / facts.path
    records: list[ConstructionAuditRecord] = []
    for line_number, line in enumerate(payload.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n") or len(line) > _LINE_PHYSICAL_LIMIT:
            _fail("construction audit verification failed")
        value = _strict_json_object(line[:-1], f"audit line {line_number}")
        if canonical_json(value).encode("utf-8") + b"\n" != line:
            _fail("construction audit verification failed")
        try:
            records.append(ConstructionAuditRecord.from_dict(value))
        except (TypeError, ValueError):
            _fail("construction audit verification failed")
    replay, terminals, funnel, identities, maximum = _scan_records(
        records, source_path, facts.record_count
    )
    if replay != payload:
        _fail("construction audit verification failed")
    execution_commit = manifest["publisher"].get("execution_commit")
    _validate_execution_commit(execution_commit)
    expected = _manifest_values(
        layout, official_split, facts, execution_commit, license_sha256,
        payload, terminals, funnel, identities, maximum,
    )
    if manifest != expected:
        _fail("construction audit verification failed")
    return {"observer_state": ObserverState.STRUCTURALLY_VERIFIED.value, "manifest": dict(manifest)}


def _observe_layout(layout: _Layout, official_split: str) -> ObserverState:
    _validate_split(official_split, layout)
    target = _target_path(layout, official_split)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return ObserverState.ABSENT
    except (PermissionError, OSError):
        return ObserverState.PARTIAL_NO_MANIFEST
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return ObserverState.PARTIAL_NO_MANIFEST
    manifest = target / _MANIFEST_NAME
    try:
        manifest.lstat()
    except FileNotFoundError:
        return ObserverState.PARTIAL_NO_MANIFEST
    except (PermissionError, OSError):
        return ObserverState.MANIFEST_PRESENT_UNVERIFIED
    try:
        _verify_layout(layout, official_split)
    except ConstructionAuditPersistenceError:
        return ObserverState.CORRUPT
    return ObserverState.STRUCTURALLY_VERIFIED


def publish(
    records: Iterable[ConstructionAuditRecord],
    *,
    official_split: str,
    execution_commit: str,
) -> Mapping[str, Any]:
    """Publish a new immutable audit target for one fixed GSM8K split."""

    return _publish_layout(
        _PRODUCTION_LAYOUT, records, official_split, execution_commit
    )


def verify(*, official_split: str) -> Mapping[str, Any]:
    """Replay and verify an existing fixed GSM8K audit publication offline."""

    return _verify_layout(_PRODUCTION_LAYOUT, official_split)


def observe(*, official_split: str) -> ObserverState:
    """Classify the current fixed-target publication state without mutation."""

    return _observe_layout(_PRODUCTION_LAYOUT, official_split)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kairos.construction_audit_persistence"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--split", required=True, choices=("train", "test"))
    observe_parser = commands.add_parser("observe")
    observe_parser.add_argument("--split", required=True, choices=("train", "test"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "verify":
            result: Any = verify(official_split=arguments.split)
        else:
            result = {"observer_state": observe(official_split=arguments.split).value}
    except (ConstructionAuditPersistenceError, FileNotFoundError, PermissionError, OSError):
        print("construction audit publication failed", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "ConstructionAuditPersistenceError",
    "ObserverState",
    "main",
    "observe",
    "publish",
    "verify",
)
