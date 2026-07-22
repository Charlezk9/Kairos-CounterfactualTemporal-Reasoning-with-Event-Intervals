"""Offline finalization and verification for the pinned GSM8K acquisition."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, Iterable, Mapping, Optional, Sequence
import unicodedata
from urllib.parse import urlsplit

from .archive_safety import (
    ArchiveInspection,
    ArchiveSafetyError,
    inspect_archive_fd,
    safe_extract_fd,
)
from .ids import canonical_json


REVISION = "3101c7d5072418e28b9008a6636bde82a006892c"
SOURCE_URL = (
    "https://codeload.github.com/openai/grade-school-math/tar.gz/"
    "3101c7d5072418e28b9008a6636bde82a006892c"
)
UPSTREAM_ROOT = f"grade-school-math-{REVISION}"
ARCHIVE_LIMIT = 1_073_741_824
EXTRACTED_LIMIT = 2_147_483_648
MEMBER_LIMIT = 200_000
METADATA_LIMIT = 67_108_864
CHECKSUM_LIMIT = 67_108_864
PATH_LIMIT = 4096
COMPONENT_LIMIT = 255
LINE_LIMIT = 1_048_576
SMALL_FILE_LIMIT = 1_048_576
COPY_CHUNK = 1_048_576
TRAIN_COUNT = 7_473
TEST_COUNT = 1_319

_PROJECT_ROOT = Path("/data0/hk_data/kairos-zx")
_STAGE_REL = (
    "data/raw/gsm8k/"
    ".acquire-3101c7d5072418e28b9008a6636bde82a006892c"
)
_REVISION_REL = f"data/raw/gsm8k/{REVISION}"
_STAGE_ARCHIVE = "source.tar.gz.part"
_HTTP_OBSERVATION = "http-observation.json"
_FORMAL_ARCHIVE = "source.tar.gz"
_EXTRACTED = "extracted"
_CHECKSUMS = "SHA256SUMS"
_COMPLETION = "completion-manifest.json"
_COMPLETION_GUARD = "completion-manifest.guard"
_HEX40 = frozenset("0123456789abcdef")


class _ProtocolState(str, Enum):
    PRE_CHECKSUM = "PRE_CHECKSUM"
    FORMAL = "FORMAL"
    GUARD_ONLY = "GUARD_ONLY"
    PUBLISHED_PAIR = "PUBLISHED_PAIR"
    CURRENT_EXACT_TEMP = "CURRENT_EXACT_TEMP"


class AcquisitionError(ValueError):
    """An acquisition invariant failed."""


@dataclass(frozen=True)
class HttpObservation:
    curl_exit_code: int
    http_code: int
    fixed_url: str
    effective_url: str
    mime: str
    size_download: int


@dataclass(frozen=True)
class ArchiveCopyResult:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class DatasetValidation:
    train_path: str
    train_count: int
    test_path: str
    test_count: int


@dataclass(frozen=True)
class TreeEntry:
    path: str
    kind: str
    device: int
    inode: int
    mode: int
    size: int
    nlink: int
    mtime_ns: int
    ctime_ns: int
    sha256: Optional[str]


@dataclass(frozen=True)
class TreeSnapshot:
    entries: tuple[TreeEntry, ...]
    extracted_bytes: int
    metadata_bytes: int
    root_fingerprint: "_Fingerprint"


@dataclass(frozen=True)
class ChecksumReport:
    sha256: str
    entry_count: int
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CompletionManifest:
    values: Mapping[str, Any]


@dataclass(frozen=True)
class _Layout:
    project_root: Path
    stage_rel: str
    revision_rel: str

    @property
    def stage(self) -> Path:
        return self.project_root / self.stage_rel

    @property
    def revision(self) -> Path:
        return self.project_root / self.revision_rel


_PRODUCTION_LAYOUT = _Layout(_PROJECT_ROOT, _STAGE_REL, _REVISION_REL)


@dataclass(frozen=True)
class _Fingerprint:
    device: int
    inode: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _close_fds_best_effort(
    named_fds: Iterable[tuple[str, int]],
    active_exception: Optional[BaseException] = None,
) -> None:
    first_error: Optional[BaseException] = None
    for _name, fd in tuple(named_fds):
        if fd < 0:
            continue
        try:
            os.close(fd)
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None and active_exception is None:
        raise first_error


@dataclass
class _CompletionPair:
    guard_fd: int = -1
    final_fd: int = -1
    fingerprint: Optional[_Fingerprint] = None
    content: bytes = b""

    def close(self, active_exception: Optional[BaseException] = None) -> None:
        final_fd = self.final_fd
        guard_fd = self.guard_fd
        self.final_fd = -1
        self.guard_fd = -1
        self.fingerprint = None
        self.content = b""
        _close_fds_best_effort(
            (("final", final_fd), ("guard", guard_fd)),
            active_exception=active_exception,
        )

    def __enter__(self) -> "_CompletionPair":
        return self

    def __exit__(
        self,
        exception_type: Optional[type[BaseException]],
        exception: Optional[BaseException],
        traceback: object,
    ) -> bool:
        self.close(active_exception=exception)
        return False


@dataclass(frozen=True)
class _RevisionBindingChain:
    project_root_fingerprint: _Fingerprint
    parent_components: tuple[tuple[str, _Fingerprint], ...]
    revision_leaf: str
    revision_fingerprint: _Fingerprint


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


def _require_private_directory(fd: int, name: str) -> None:
    current = os.fstat(fd)
    if not stat.S_ISDIR(current.st_mode) or stat.S_IMODE(current.st_mode) != 0o700:
        raise AcquisitionError(f"{name} must be a directory with mode 0700")


def _validate_hex(value: str, length: int, name: str) -> None:
    if not isinstance(value, str) or len(value) != length or any(c not in _HEX40 for c in value):
        raise AcquisitionError(f"{name} must be {length} lowercase hexadecimal characters")


def _dir_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_absolute_dir(path: Path) -> int:
    raw = os.fspath(path)
    if not os.path.isabs(raw):
        raise AcquisitionError("root path must be absolute")
    components = raw.split("/")[1:]
    if components and components[-1] == "":
        components.pop()
    if any(component in {"", ".", ".."} for component in components):
        raise AcquisitionError("root path has an unsafe component")
    fd = os.open("/", _dir_flags())
    try:
        for component in components:
            next_fd = os.open(component, _dir_flags(), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _relative_components(path: str) -> list[str]:
    if not path or path.startswith("/") or "\\" in path:
        raise AcquisitionError("relative path is invalid")
    components = path.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise AcquisitionError("relative path has an unsafe component")
    return components


def _open_relative_dir(root_fd: int, path: str) -> int:
    fd = os.dup(root_fd)
    try:
        for component in _relative_components(path):
            next_fd = os.open(component, _dir_flags(), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_relative_regular(root_fd: int, path: str, flags: int = os.O_RDONLY) -> int:
    components = _relative_components(path)
    parent_fd = os.dup(root_fd)
    try:
        for component in components[:-1]:
            next_fd = os.open(component, _dir_flags(), dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(
            components[-1],
            flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    finally:
        os.close(parent_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise AcquisitionError(f"not a regular file: {path}")
    return fd


def _read_bounded_fd(fd: int, limit: int) -> bytes:
    baseline = _fingerprint_fd(fd)
    if baseline.size > limit:
        raise AcquisitionError("file exceeds its read limit")
    os.lseek(fd, 0, os.SEEK_SET)
    result = bytearray()
    while True:
        chunk = os.read(fd, min(COPY_CHUNK, limit + 1 - len(result)))
        if not chunk:
            break
        result.extend(chunk)
        if len(result) > limit:
            raise AcquisitionError("file exceeds its read limit")
    if _fingerprint_fd(fd) != baseline:
        raise AcquisitionError("file changed while reading")
    return bytes(result)


def _hash_fd(fd: int, limit: int) -> tuple[str, int, _Fingerprint]:
    baseline = _fingerprint_fd(fd)
    if not stat.S_ISREG(baseline.mode) or baseline.size > limit:
        raise AcquisitionError("regular file exceeds its byte limit")
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    count = 0
    while True:
        chunk = os.read(fd, COPY_CHUNK)
        if not chunk:
            break
        count += len(chunk)
        if count > limit:
            raise AcquisitionError("stream exceeds its byte limit")
        digest.update(chunk)
    if count != baseline.size or _fingerprint_fd(fd) != baseline:
        raise AcquisitionError("file changed while hashing")
    return digest.hexdigest(), count, baseline


def _strict_object(data: bytes, expected: set[str], name: str) -> Mapping[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AcquisitionError(f"duplicate JSON key in {name}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise AcquisitionError(f"non-finite JSON value in {name}: {value}")

    try:
        value = json.loads(data, object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"invalid JSON in {name}: {error}") from error
    if not isinstance(value, dict):
        raise AcquisitionError(f"{name} must be a JSON object")
    missing = expected.difference(value)
    extra = set(value).difference(expected)
    if missing or extra:
        raise AcquisitionError(f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}")
    return value


_HTTP_KEYS = {
    "curl_exit_code",
    "http_code",
    "fixed_url",
    "effective_url",
    "mime",
    "size_download",
}


def _validate_http(stage_fd: int) -> tuple[HttpObservation, str, _Fingerprint]:
    meta_fd = _open_relative_regular(stage_fd, _HTTP_OBSERVATION)
    try:
        value = _strict_object(_read_bounded_fd(meta_fd, SMALL_FILE_LIMIT), _HTTP_KEYS, "HTTP observation")
    finally:
        os.close(meta_fd)
    for key in ("curl_exit_code", "http_code", "size_download"):
        if isinstance(value[key], bool) or not isinstance(value[key], int):
            raise AcquisitionError(f"{key} must be an integer")
    for key in ("fixed_url", "effective_url", "mime"):
        if not isinstance(value[key], str):
            raise AcquisitionError(f"{key} must be a string")
    observation = HttpObservation(**value)
    if observation.curl_exit_code != 0 or observation.http_code != 200:
        raise AcquisitionError("curl and HTTP status must be zero/200")
    if observation.fixed_url != SOURCE_URL or observation.effective_url != SOURCE_URL:
        raise AcquisitionError("fixed/effective URL differs from the frozen URL")
    parsed = urlsplit(observation.effective_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "codeload.github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise AcquisitionError("effective URL authority is invalid")
    if observation.mime != "application/x-gzip":
        raise AcquisitionError("HTTP MIME is not application/x-gzip")
    if observation.size_download < 1 or observation.size_download > ARCHIVE_LIMIT:
        raise AcquisitionError("download size exceeds the archive limit")

    archive_fd = _open_relative_regular(stage_fd, _STAGE_ARCHIVE)
    try:
        digest, size, baseline = _hash_fd(archive_fd, ARCHIVE_LIMIT)
        os.lseek(archive_fd, 0, os.SEEK_SET)
        magic = os.read(archive_fd, 2)
        if _fingerprint_fd(archive_fd) != baseline:
            raise AcquisitionError("stage archive changed during gzip validation")
    finally:
        os.close(archive_fd)
    if size != observation.size_download:
        raise AcquisitionError("curl size_download differs from archive fstat")
    if magic != b"\x1f\x8b":
        raise AcquisitionError("stage archive does not have gzip magic")
    return observation, digest, baseline


def _copy_archive(stage_fd: int, revision_fd: int, expected_sha256: str) -> ArchiveCopyResult:
    _validate_hex(expected_sha256, 64, "expected SHA256")
    source_fd = _open_relative_regular(stage_fd, _STAGE_ARCHIVE)
    destination_fd = -1
    try:
        source_sha, source_size, source_baseline = _hash_fd(source_fd, ARCHIVE_LIMIT)
        if source_sha != expected_sha256:
            raise AcquisitionError("stage archive SHA256 differs from the approved value")
        destination_fd = os.open(
            _FORMAL_ARCHIVE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=revision_fd,
        )
        destination_initial = _fingerprint_fd(destination_fd)
        if (destination_initial.device, destination_initial.inode) == (
            source_baseline.device,
            source_baseline.inode,
        ):
            raise AcquisitionError("formal archive must not share the source inode")
        os.lseek(source_fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        copied = 0
        while True:
            chunk = os.read(source_fd, COPY_CHUNK)
            if not chunk:
                break
            copied += len(chunk)
            if copied > ARCHIVE_LIMIT:
                raise AcquisitionError("archive copy exceeds 1 GiB")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written < 1:
                    raise AcquisitionError("archive copy made no write progress")
                view = view[written:]
            digest.update(chunk)
        if copied != source_size or digest.hexdigest() != expected_sha256:
            raise AcquisitionError("archive changed while copying")
        if _fingerprint_fd(source_fd) != source_baseline:
            raise AcquisitionError("source archive fstat changed while copying")
        os.fchmod(destination_fd, 0o600)
        os.fsync(destination_fd)
        destination_written = _fingerprint_fd(destination_fd)
        if destination_written.nlink != 1 or destination_written.size != copied:
            raise AcquisitionError("formal archive link count or size is invalid")
        os.close(destination_fd)
        destination_fd = -1

        reopened_fd = _open_relative_regular(revision_fd, _FORMAL_ARCHIVE)
        try:
            destination_sha, destination_size, destination_reopened = _hash_fd(
                reopened_fd, ARCHIVE_LIMIT
            )
        finally:
            os.close(reopened_fd)
        if destination_reopened != destination_written:
            raise AcquisitionError("formal archive inode/fingerprint changed after reopen")
        if destination_sha != expected_sha256 or destination_size != source_size:
            raise AcquisitionError("formal archive failed close/reopen verification")
        if (destination_reopened.device, destination_reopened.inode) == (
            source_baseline.device,
            source_baseline.inode,
        ):
            raise AcquisitionError("formal archive is not an independent copy")
        final_source_sha, _, final_source_stat = _hash_fd(source_fd, ARCHIVE_LIMIT)
        if final_source_stat != source_baseline or final_source_sha != expected_sha256:
            raise AcquisitionError("stage archive changed after copying")
        os.fsync(revision_fd)
        return ArchiveCopyResult(_FORMAL_ARCHIVE, destination_size, destination_sha)
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        os.close(source_fd)


def _validate_component(name: str) -> bytes:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise AcquisitionError("unsafe path component")
    if unicodedata.normalize("NFC", name) != name:
        raise AcquisitionError("path component is not NFC")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in name):
        raise AcquisitionError("path contains forbidden Unicode characters")
    encoded = name.encode("utf-8")
    if len(encoded) > COMPONENT_LIMIT:
        raise AcquisitionError("path component exceeds 255 UTF-8 bytes")
    return encoded


def _validate_relative_path(path: str) -> bytes:
    components = path.split("/")
    encoded_components = [_validate_component(component) for component in components]
    encoded = b"/".join(encoded_components)
    if len(encoded) > PATH_LIMIT:
        raise AcquisitionError("path exceeds 4096 UTF-8 bytes")
    return encoded


def _file_limit(path: str) -> int:
    if path == _FORMAL_ARCHIVE:
        return ARCHIVE_LIMIT
    if path == _CHECKSUMS:
        return CHECKSUM_LIMIT
    if path in {_COMPLETION, _COMPLETION_GUARD}:
        return SMALL_FILE_LIMIT
    if path.startswith(f"{_EXTRACTED}/"):
        return EXTRACTED_LIMIT
    return METADATA_LIMIT


def _tree_entry_from_file(
    root_fd: int,
    path: str,
    observed: os.stat_result,
) -> TreeEntry:
    fd = _open_relative_regular(root_fd, path)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (observed.st_dev, observed.st_ino):
            raise AcquisitionError("tree entry changed between scan and open")
        digest, size, baseline = _hash_fd(fd, _file_limit(path))
    finally:
        os.close(fd)
    if baseline.nlink != 1:
        raise AcquisitionError(
            f"regular file has unexpected link count {baseline.nlink}: {path}"
        )
    return TreeEntry(
        path,
        "file",
        baseline.device,
        baseline.inode,
        baseline.mode,
        size,
        baseline.nlink,
        baseline.mtime_ns,
        baseline.ctime_ns,
        digest,
    )


def _scan_tree(
    root_fd: int,
    *,
    protocol_state: _ProtocolState,
    exact_temp: Optional[tuple[str, tuple[int, int]]] = None,
    protocol_inode: Optional[tuple[int, int]] = None,
) -> TreeSnapshot:
    formal_names = {_FORMAL_ARCHIVE, _EXTRACTED}
    if protocol_state is not _ProtocolState.PRE_CHECKSUM:
        formal_names.add(_CHECKSUMS)
    protocol_names: dict[str, tuple[tuple[int, int], int]] = {}
    if protocol_state is _ProtocolState.CURRENT_EXACT_TEMP:
        if exact_temp is None or protocol_inode is not None:
            raise AcquisitionError("CURRENT_EXACT_TEMP requires one exact temp")
        protocol_names[exact_temp[0]] = (exact_temp[1], 1)
    elif protocol_state is _ProtocolState.GUARD_ONLY:
        if protocol_inode is None or exact_temp is not None:
            raise AcquisitionError("GUARD_ONLY requires the guard inode")
        protocol_names[_COMPLETION_GUARD] = (protocol_inode, 1)
    elif protocol_state is _ProtocolState.PUBLISHED_PAIR:
        if protocol_inode is None or exact_temp is not None:
            raise AcquisitionError("PUBLISHED_PAIR requires the pair inode")
        protocol_names[_COMPLETION_GUARD] = (protocol_inode, 2)
        protocol_names[_COMPLETION] = (protocol_inode, 2)
    elif exact_temp is not None or protocol_inode is not None:
        raise AcquisitionError("protocol inode/temp is invalid for this state")

    if set(protocol_names).intersection(formal_names):
        raise AcquisitionError("protocol and formal root names collide")
    required_root_names = formal_names.union(protocol_names)
    seen_root_names: set[str] = set()
    root_before = _fingerprint_fd(root_fd)
    if not stat.S_ISDIR(root_before.mode):
        raise AcquisitionError("tree root is not a directory")
    entries: list[TreeEntry] = []
    encoded_paths: set[bytes] = set()
    extracted_bytes = 0
    metadata_bytes = 0
    member_count = 0

    def visit(directory_fd: int, prefix: str) -> None:
        nonlocal extracted_bytes, metadata_bytes, member_count
        directory_before = _fingerprint_fd(directory_fd)
        with os.scandir(directory_fd) as iterator:
            for item in iterator:
                member_count += 1
                if member_count > MEMBER_LIMIT:
                    raise AcquisitionError("tree exceeds the member limit")
                _validate_component(item.name)
                path = f"{prefix}/{item.name}" if prefix else item.name
                encoded = _validate_relative_path(path)
                if encoded in encoded_paths:
                    raise AcquisitionError("NFC/UTF-8 path collision")
                encoded_paths.add(encoded)
                metadata_bytes += len(encoded) + 128
                if metadata_bytes > METADATA_LIMIT:
                    raise AcquisitionError("tree metadata exceeds 64 MiB")
                observed = item.stat(follow_symlinks=False)
                if not prefix:
                    if item.name not in required_root_names:
                        raise AcquisitionError(
                            f"root entry is outside the {protocol_state.value} protocol: {item.name}"
                        )
                    seen_root_names.add(item.name)
                    protocol = protocol_names.get(item.name)
                    if protocol is not None:
                        expected_inode, expected_nlink = protocol
                        if (
                            not stat.S_ISREG(observed.st_mode)
                            or (observed.st_dev, observed.st_ino) != expected_inode
                            or observed.st_nlink != expected_nlink
                        ):
                            raise AcquisitionError(
                                f"protocol entry invariant failed: {item.name}"
                            )
                        continue
                    if item.name == _EXTRACTED and not stat.S_ISDIR(observed.st_mode):
                        raise AcquisitionError("extracted root must be a directory")
                    if item.name != _EXTRACTED and not stat.S_ISREG(observed.st_mode):
                        raise AcquisitionError(
                            f"formal root file has the wrong type: {item.name}"
                        )
                if stat.S_ISLNK(observed.st_mode):
                    raise AcquisitionError(f"symlink is forbidden: {path}")
                if stat.S_ISDIR(observed.st_mode):
                    child_fd = os.open(item.name, _dir_flags(), dir_fd=directory_fd)
                    try:
                        current = _fingerprint_fd(child_fd)
                        if (current.device, current.inode) != (
                            observed.st_dev,
                            observed.st_ino,
                        ):
                            raise AcquisitionError("directory changed during traversal")
                        visit(child_fd, path)
                        if _fingerprint_fd(child_fd) != current:
                            raise AcquisitionError("directory changed during traversal")
                        entries.append(
                            TreeEntry(
                                path,
                                "directory",
                                current.device,
                                current.inode,
                                current.mode,
                                current.size,
                                current.nlink,
                                current.mtime_ns,
                                current.ctime_ns,
                                None,
                            )
                        )
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(observed.st_mode):
                    entry = _tree_entry_from_file(root_fd, path, observed)
                    if path == _FORMAL_ARCHIVE and entry.size > ARCHIVE_LIMIT:
                        raise AcquisitionError("formal archive exceeds 1 GiB")
                    if path.startswith(f"{_EXTRACTED}/"):
                        extracted_bytes += entry.size
                        if extracted_bytes > EXTRACTED_LIMIT:
                            raise AcquisitionError("extracted bytes exceed 2 GiB")
                    entries.append(entry)
                else:
                    raise AcquisitionError(f"special filesystem entry is forbidden: {path}")
        if _fingerprint_fd(directory_fd) != directory_before:
            raise AcquisitionError("directory changed during traversal")

    visit(root_fd, "")
    if seen_root_names != required_root_names:
        raise AcquisitionError(
            f"root entries do not match {protocol_state.value}: "
            f"missing={sorted(required_root_names - seen_root_names)}"
        )
    if _fingerprint_fd(root_fd) != root_before:
        raise AcquisitionError("tree root changed during traversal")
    entries.sort(key=lambda entry: _validate_relative_path(entry.path))
    file_ancestors = _file_ancestor_paths(
        entry.path for entry in entries if entry.kind == "file"
    )
    for entry in entries:
        if entry.kind == "directory" and entry.path not in file_ancestors:
            raise AcquisitionError(f"extra empty directory is forbidden: {entry.path}")
    return TreeSnapshot(
        tuple(entries), extracted_bytes, metadata_bytes, root_before
    )


def _file_ancestor_paths(paths: Iterable[str]) -> set[str]:
    ancestors: set[str] = set()
    for path in paths:
        components = path.split("/")
        current: list[str] = []
        for component in components[:-1]:
            current.append(component)
            ancestors.add("/".join(current))
    return ancestors


def _read_jsonl(root_fd: int, path: str, expected_count: int) -> int:
    fd = _open_relative_regular(root_fd, path)
    count = 0
    try:
        with os.fdopen(fd, "rb", closefd=True) as handle:
            fd = -1
            while True:
                line = handle.readline(LINE_LIMIT + 1)
                if not line:
                    break
                if len(line) > LINE_LIMIT:
                    raise AcquisitionError(f"JSONL raw line exceeds 1 MiB: {path}")
                if not line.strip():
                    raise AcquisitionError(f"JSONL contains an empty line: {path}")
                count += 1
                if count > expected_count:
                    raise AcquisitionError(f"JSONL exceeds expected count: {path}")
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise AcquisitionError(f"invalid JSONL record in {path}") from error
                if not isinstance(value, dict):
                    raise AcquisitionError(f"JSONL record is not an object: {path}")
                for field in ("question", "answer"):
                    if not isinstance(value.get(field), str) or not value[field].strip():
                        raise AcquisitionError(f"invalid {field} in {path}")
    finally:
        if fd >= 0:
            os.close(fd)
    if count != expected_count:
        raise AcquisitionError(f"JSONL count mismatch for {path}: {count}")
    return count


def _validate_dataset(
    revision_fd: int,
    *,
    protocol_state: _ProtocolState,
    exact_temp: Optional[tuple[str, tuple[int, int]]] = None,
    protocol_inode: Optional[tuple[int, int]] = None,
) -> DatasetValidation:
    extracted_fd = _open_relative_dir(revision_fd, _EXTRACTED)
    try:
        with os.scandir(extracted_fd) as iterator:
            names = [entry.name for entry in iterator]
        if names != [UPSTREAM_ROOT]:
            raise AcquisitionError("extracted/ must contain only the fixed upstream root")

        base = f"{_EXTRACTED}/{UPSTREAM_ROOT}"
        for required in (f"{base}/LICENSE", f"{base}/README.md"):
            fd = _open_relative_regular(revision_fd, required)
            os.close(fd)
        train_path = f"{base}/grade_school_math/data/train.jsonl"
        test_path = f"{base}/grade_school_math/data/test.jsonl"
        train_count = _read_jsonl(revision_fd, train_path, TRAIN_COUNT)
        test_count = _read_jsonl(revision_fd, test_path, TEST_COUNT)
        _scan_tree(
            revision_fd,
            protocol_state=protocol_state,
            exact_temp=exact_temp,
            protocol_inode=protocol_inode,
        )
        return DatasetValidation(train_path, train_count, test_path, test_count)
    finally:
        os.close(extracted_fd)


def _checksum_lines(snapshot: TreeSnapshot) -> tuple[bytes, tuple[tuple[str, str], ...]]:
    excluded = {_CHECKSUMS, _COMPLETION, _COMPLETION_GUARD}
    pairs = tuple(
        (entry.path, entry.sha256 or "")
        for entry in snapshot.entries
        if entry.kind == "file" and entry.path not in excluded
    )
    content = b"".join(
        digest.encode("ascii") + b"  " + _validate_relative_path(path) + b"\n"
        for path, digest in pairs
    )
    if len(content) > CHECKSUM_LIMIT:
        raise AcquisitionError("SHA256SUMS exceeds 64 MiB")
    return content, pairs


def _parse_checksum_bytes(content: bytes) -> tuple[tuple[str, str], ...]:
    if len(content) > CHECKSUM_LIMIT:
        raise AcquisitionError("SHA256SUMS exceeds 64 MiB")
    if content and not content.endswith(b"\n"):
        raise AcquisitionError("SHA256SUMS must end with LF")
    result: list[tuple[str, str]] = []
    previous: Optional[bytes] = None
    for raw_line in content.splitlines(keepends=True):
        if len(raw_line) < 68 or raw_line[64:66] != b"  " or raw_line[-1:] != b"\n":
            raise AcquisitionError("invalid SHA256SUMS line grammar")
        digest_bytes = raw_line[:64]
        if any(byte not in b"0123456789abcdef" for byte in digest_bytes):
            raise AcquisitionError("invalid SHA256SUMS digest")
        path_bytes = raw_line[66:-1]
        try:
            path = path_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise AcquisitionError("invalid UTF-8 checksum path") from error
        if _validate_relative_path(path) != path_bytes:
            raise AcquisitionError("checksum path is not canonical")
        if previous is not None and path_bytes <= previous:
            raise AcquisitionError("checksum paths are duplicate or unsorted")
        previous = path_bytes
        result.append((path, digest_bytes.decode("ascii")))
    return tuple(result)


def _temp_name(label: str) -> str:
    return f".kairos-{label}.{secrets.token_hex(16)}.tmp"


def _write_temp(revision_fd: int, name: str, content: bytes) -> tuple[int, int]:
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=revision_fd,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written < 1:
                raise AcquisitionError("private temp write made no progress")
            view = view[written:]
        os.fsync(fd)
        current = os.fstat(fd)
        return current.st_dev, current.st_ino
    finally:
        os.close(fd)


def _publish_temp(revision_fd: int, temp: str, final: str, inode: tuple[int, int]) -> None:
    os.link(
        temp,
        final,
        src_dir_fd=revision_fd,
        dst_dir_fd=revision_fd,
        follow_symlinks=False,
    )
    temp_stat = os.stat(temp, dir_fd=revision_fd, follow_symlinks=False)
    final_stat = os.stat(final, dir_fd=revision_fd, follow_symlinks=False)
    if (temp_stat.st_dev, temp_stat.st_ino) != inode or (
        final_stat.st_dev,
        final_stat.st_ino,
    ) != inode:
        raise AcquisitionError("published temp/final inode mismatch")
    os.unlink(temp, dir_fd=revision_fd)
    final_stat = os.stat(final, dir_fd=revision_fd, follow_symlinks=False)
    if final_stat.st_nlink != 1:
        raise AcquisitionError("published final must have st_nlink=1")
    os.fsync(revision_fd)


def _verify_checksums(
    revision_fd: int,
    *,
    protocol_state: _ProtocolState,
    exact_temp: Optional[tuple[str, tuple[int, int]]] = None,
    protocol_inode: Optional[tuple[int, int]] = None,
) -> ChecksumReport:
    snapshot = _scan_tree(
        revision_fd,
        protocol_state=protocol_state,
        exact_temp=exact_temp,
        protocol_inode=protocol_inode,
    )
    checksum_fd = _open_relative_regular(revision_fd, _CHECKSUMS)
    try:
        checksum_hash, _, checksum_stat = _hash_fd(checksum_fd, CHECKSUM_LIMIT)
        os.lseek(checksum_fd, 0, os.SEEK_SET)
        content = _read_bounded_fd(checksum_fd, CHECKSUM_LIMIT)
    finally:
        os.close(checksum_fd)
    if checksum_stat.nlink != 1:
        raise AcquisitionError("SHA256SUMS must have st_nlink=1")
    parsed = _parse_checksum_bytes(content)
    expected_content, expected = _checksum_lines(snapshot)
    if content != expected_content or parsed != expected:
        raise AcquisitionError("SHA256SUMS does not exactly cover the current file set")
    return ChecksumReport(checksum_hash, len(parsed), parsed)


def _write_checksums(revision_fd: int) -> ChecksumReport:
    for final in (_CHECKSUMS, _COMPLETION, _COMPLETION_GUARD):
        try:
            os.stat(final, dir_fd=revision_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"final acquisition file already exists: {final}")
    snapshot = _scan_tree(
        revision_fd, protocol_state=_ProtocolState.PRE_CHECKSUM
    )
    content, _ = _checksum_lines(snapshot)
    temp = _temp_name("SHA256SUMS")
    inode = _write_temp(revision_fd, temp, content)
    temp_fd = _open_relative_regular(revision_fd, temp)
    try:
        if _read_bounded_fd(temp_fd, CHECKSUM_LIMIT) != content:
            raise AcquisitionError("SHA256SUMS temp failed readback")
    finally:
        os.close(temp_fd)
    _publish_temp(revision_fd, temp, _CHECKSUMS, inode)
    return _verify_checksums(
        revision_fd, protocol_state=_ProtocolState.FORMAL
    )


def _open_directory_for_path(root_fd: int, path: str) -> int:
    return _open_relative_dir(root_fd, path)


def _entry_fingerprint(entry: TreeEntry) -> _Fingerprint:
    return _Fingerprint(
        entry.device,
        entry.inode,
        entry.mode,
        entry.nlink,
        entry.size,
        entry.mtime_ns,
        entry.ctime_ns,
    )


def _root_identity(fingerprint: _Fingerprint) -> tuple[int, int, int, int]:
    return (
        fingerprint.device,
        fingerprint.inode,
        fingerprint.mode,
        fingerprint.nlink,
    )


def _formal_entries(snapshot: TreeSnapshot) -> tuple[TreeEntry, ...]:
    return snapshot.entries


def _formal_tree_fingerprint(snapshot: TreeSnapshot) -> str:
    payload = [
        {
            "path": entry.path,
            "type": entry.kind,
            "device": entry.device,
            "inode": entry.inode,
            "mode": entry.mode,
            "nlink": entry.nlink,
            "size": entry.size,
            "mtime_ns": entry.mtime_ns,
            "ctime_ns": entry.ctime_ns,
            "sha256": entry.sha256,
        }
        for entry in _formal_entries(snapshot)
    ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _fsync_formal_tree(revision_fd: int, snapshot: TreeSnapshot) -> None:
    files = [entry for entry in snapshot.entries if entry.kind == "file"]
    directories = [entry for entry in snapshot.entries if entry.kind == "directory"]
    for entry in files:
        fd = _open_relative_regular(revision_fd, entry.path)
        try:
            expected = _entry_fingerprint(entry)
            if _fingerprint_fd(fd) != expected:
                raise AcquisitionError("formal file changed before fsync")
            os.fsync(fd)
            if _fingerprint_fd(fd) != expected:
                raise AcquisitionError("formal file changed during fsync")
        finally:
            os.close(fd)
    directories.sort(key=lambda entry: entry.path.count("/"), reverse=True)
    for entry in directories:
        fd = _open_directory_for_path(revision_fd, entry.path)
        try:
            expected = _entry_fingerprint(entry)
            if _fingerprint_fd(fd) != expected:
                raise AcquisitionError("formal directory changed before fsync")
            os.fsync(fd)
            if _fingerprint_fd(fd) != expected:
                raise AcquisitionError("formal directory changed during fsync")
        finally:
            os.close(fd)
    if _fingerprint_fd(revision_fd) != snapshot.root_fingerprint:
        raise AcquisitionError("revision root changed before fsync")
    os.fsync(revision_fd)
    if _fingerprint_fd(revision_fd) != snapshot.root_fingerprint:
        raise AcquisitionError("revision root changed during fsync")


_MANIFEST_KEYS = {
    "schema_version",
    "status",
    "dataset",
    "revision",
    "source_url",
    "effective_url",
    "curl_exit_code",
    "http_code",
    "content_type",
    "size_download",
    "archive_path",
    "archive_size_bytes",
    "archive_sha256",
    "archive_format",
    "archive_member_count",
    "archive_declared_expanded_bytes",
    "extracted_root",
    "train_path",
    "train_count",
    "test_path",
    "test_count",
    "raw_line_max_bytes",
    "sha256sums_path",
    "sha256sums_sha256",
    "sha256sums_entry_count",
    "formal_tree_fingerprint_sha256",
    "archive_max_bytes",
    "expanded_max_bytes",
    "metadata_max_bytes",
    "max_members",
    "kairos_git_commit",
    "completed_at_utc",
}


def _validate_manifest(value: Mapping[str, Any]) -> None:
    missing = _MANIFEST_KEYS.difference(value)
    extra = set(value).difference(_MANIFEST_KEYS)
    if missing or extra:
        raise AcquisitionError(f"invalid completion fields; missing={sorted(missing)}, extra={sorted(extra)}")
    fixed = {
        "schema_version": "kairos-acquisition-completion-v1",
        "status": "COMPLETE",
        "dataset": "gsm8k",
        "revision": REVISION,
        "source_url": SOURCE_URL,
        "effective_url": SOURCE_URL,
        "curl_exit_code": 0,
        "http_code": 200,
        "content_type": "application/x-gzip",
        "archive_path": _FORMAL_ARCHIVE,
        "archive_format": "tar.gz",
        "extracted_root": f"{_EXTRACTED}/{UPSTREAM_ROOT}",
        "train_path": (
            f"{_EXTRACTED}/{UPSTREAM_ROOT}/grade_school_math/data/train.jsonl"
        ),
        "train_count": TRAIN_COUNT,
        "test_path": (
            f"{_EXTRACTED}/{UPSTREAM_ROOT}/grade_school_math/data/test.jsonl"
        ),
        "test_count": TEST_COUNT,
        "raw_line_max_bytes": LINE_LIMIT,
        "sha256sums_path": _CHECKSUMS,
        "archive_max_bytes": ARCHIVE_LIMIT,
        "expanded_max_bytes": EXTRACTED_LIMIT,
        "metadata_max_bytes": METADATA_LIMIT,
        "max_members": MEMBER_LIMIT,
    }
    for key, expected in fixed.items():
        if type(value.get(key)) is not type(expected) or value.get(key) != expected:
            raise AcquisitionError(f"invalid fixed completion field: {key}")
    for key in (
        "size_download",
        "archive_size_bytes",
        "archive_member_count",
        "archive_declared_expanded_bytes",
        "sha256sums_entry_count",
    ):
        if isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 1:
            raise AcquisitionError(f"invalid integer completion field: {key}")
    if value["size_download"] > ARCHIVE_LIMIT or value["archive_size_bytes"] > ARCHIVE_LIMIT:
        raise AcquisitionError("completion archive byte limit exceeded")
    if value["archive_member_count"] > MEMBER_LIMIT:
        raise AcquisitionError("completion member limit exceeded")
    if value["archive_declared_expanded_bytes"] > EXTRACTED_LIMIT:
        raise AcquisitionError("completion expanded byte limit exceeded")
    if value["sha256sums_entry_count"] > MEMBER_LIMIT:
        raise AcquisitionError("completion checksum entry limit exceeded")
    for key in (
        "archive_sha256",
        "sha256sums_sha256",
        "formal_tree_fingerprint_sha256",
    ):
        _validate_hex(value[key], 64, key)
    _validate_hex(value["kairos_git_commit"], 40, "kairos_git_commit")
    if not isinstance(value["completed_at_utc"], str):
        raise AcquisitionError("completed_at_utc must be an explicit UTC timestamp")
    try:
        completed_at = datetime.fromisoformat(value["completed_at_utc"])
    except ValueError as error:
        raise AcquisitionError("completed_at_utc is not an ISO-8601 timestamp") from error
    if completed_at.tzinfo is None or completed_at.utcoffset() != timezone.utc.utcoffset(None):
        raise AcquisitionError("completed_at_utc must be an explicit UTC timestamp")


def _completion_values(
    observation: HttpObservation,
    archive: ArchiveCopyResult,
    inspection: ArchiveInspection,
    dataset: DatasetValidation,
    checksums: ChecksumReport,
    commit: str,
    formal_tree_fingerprint_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "kairos-acquisition-completion-v1",
        "status": "COMPLETE",
        "dataset": "gsm8k",
        "revision": REVISION,
        "source_url": SOURCE_URL,
        "effective_url": observation.effective_url,
        "curl_exit_code": observation.curl_exit_code,
        "http_code": observation.http_code,
        "content_type": observation.mime.split(";", 1)[0].strip().casefold(),
        "size_download": observation.size_download,
        "archive_path": archive.path,
        "archive_size_bytes": archive.size_bytes,
        "archive_sha256": archive.sha256,
        "archive_format": inspection.format.value,
        "archive_member_count": inspection.member_count,
        "archive_declared_expanded_bytes": inspection.total_declared_bytes,
        "extracted_root": f"{_EXTRACTED}/{UPSTREAM_ROOT}",
        "train_path": dataset.train_path,
        "train_count": dataset.train_count,
        "test_path": dataset.test_path,
        "test_count": dataset.test_count,
        "raw_line_max_bytes": LINE_LIMIT,
        "sha256sums_path": _CHECKSUMS,
        "sha256sums_sha256": checksums.sha256,
        "sha256sums_entry_count": checksums.entry_count,
        "formal_tree_fingerprint_sha256": formal_tree_fingerprint_sha256,
        "archive_max_bytes": ARCHIVE_LIMIT,
        "expanded_max_bytes": EXTRACTED_LIMIT,
        "metadata_max_bytes": METADATA_LIMIT,
        "max_members": MEMBER_LIMIT,
        "kairos_git_commit": commit,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _publish_completion(
    revision_fd: int,
    values: Mapping[str, Any],
) -> CompletionManifest:
    _validate_manifest(values)
    for final in (_COMPLETION_GUARD, _COMPLETION):
        try:
            os.stat(final, dir_fd=revision_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"completion publication file exists: {final}")
    content = canonical_json(values).encode("utf-8") + b"\n"
    if len(content) > SMALL_FILE_LIMIT:
        raise AcquisitionError("completion manifest exceeds 1 MiB")
    temp = _temp_name("completion-manifest")
    inode = _write_temp(revision_fd, temp, content)
    temp_fd = _open_relative_regular(revision_fd, temp)
    try:
        reread = _read_bounded_fd(temp_fd, SMALL_FILE_LIMIT)
        temp_original = _fingerprint_fd(temp_fd)
    finally:
        os.close(temp_fd)
    if (
        (temp_original.device, temp_original.inode) != inode
        or temp_original.nlink != 1
        or reread != content
    ):
        raise AcquisitionError("completion temp failed original binding")
    parsed = _strict_object(reread, _MANIFEST_KEYS, "completion manifest")
    _validate_manifest(parsed)
    checksums = _verify_checksums(
        revision_fd,
        protocol_state=_ProtocolState.CURRENT_EXACT_TEMP,
        exact_temp=(temp, inode),
    )
    if checksums.sha256 != parsed["sha256sums_sha256"] or checksums.entry_count != parsed["sha256sums_entry_count"]:
        raise AcquisitionError("completion manifest does not match SHA256SUMS")
    before = _scan_tree(
        revision_fd,
        protocol_state=_ProtocolState.CURRENT_EXACT_TEMP,
        exact_temp=(temp, inode),
    )
    if _formal_tree_fingerprint(before) != parsed["formal_tree_fingerprint_sha256"]:
        raise AcquisitionError("completion manifest formal tree fingerprint differs")
    _fsync_formal_tree(revision_fd, before)
    after_fsync = _scan_tree(
        revision_fd,
        protocol_state=_ProtocolState.CURRENT_EXACT_TEMP,
        exact_temp=(temp, inode),
    )
    if after_fsync != before:
        raise AcquisitionError("formal tree changed while being synchronized")

    os.link(
        temp,
        _COMPLETION_GUARD,
        src_dir_fd=revision_fd,
        dst_dir_fd=revision_fd,
        follow_symlinks=False,
    )
    guard_stat = os.stat(
        _COMPLETION_GUARD, dir_fd=revision_fd, follow_symlinks=False
    )
    temp_stat = os.stat(temp, dir_fd=revision_fd, follow_symlinks=False)
    if (
        (guard_stat.st_dev, guard_stat.st_ino) != inode
        or (temp_stat.st_dev, temp_stat.st_ino) != inode
        or guard_stat.st_nlink != 2
        or temp_stat.st_nlink != 2
    ):
        raise AcquisitionError("completion guard link invariant failed")
    for name in (temp, _COMPLETION_GUARD):
        fd = _open_relative_regular(revision_fd, name)
        try:
            if _read_bounded_fd(fd, SMALL_FILE_LIMIT) != content:
                raise AcquisitionError("completion temp/guard content changed")
        finally:
            os.close(fd)
    os.unlink(temp, dir_fd=revision_fd)
    guard_before_fsync = _scan_tree(
        revision_fd,
        protocol_state=_ProtocolState.GUARD_ONLY,
        protocol_inode=inode,
    )
    os.fsync(revision_fd)
    guard_durable = _scan_tree(
        revision_fd,
        protocol_state=_ProtocolState.GUARD_ONLY,
        protocol_inode=inode,
    )
    if (
        _formal_entries(guard_before_fsync) != _formal_entries(before)
        or _formal_entries(guard_durable) != _formal_entries(before)
        or _root_identity(guard_durable.root_fingerprint)
        != _root_identity(before.root_fingerprint)
        or _formal_tree_fingerprint(guard_durable)
        != parsed["formal_tree_fingerprint_sha256"]
    ):
        raise AcquisitionError("formal tree changed in durable guard-only state")
    guard_fd = _open_relative_regular(revision_fd, _COMPLETION_GUARD)
    try:
        guard_fingerprint = _fingerprint_fd(guard_fd)
        if (
            (guard_fingerprint.device, guard_fingerprint.inode) != inode
            or guard_fingerprint.nlink != 1
            or _read_bounded_fd(guard_fd, SMALL_FILE_LIMIT) != content
            or _fingerprint_fd(guard_fd) != guard_fingerprint
        ):
            raise AcquisitionError("durable completion guard binding failed")
    finally:
        os.close(guard_fd)
    os.link(
        _COMPLETION_GUARD,
        _COMPLETION,
        src_dir_fd=revision_fd,
        dst_dir_fd=revision_fd,
        follow_symlinks=False,
    )
    os.fsync(revision_fd)
    with _open_completion_pair(revision_fd) as pair:
        if (
            pair.fingerprint is None
            or (pair.fingerprint.device, pair.fingerprint.inode) != inode
            or pair.content != content
        ):
            raise AcquisitionError("published completion pair lost original binding")
        _assert_completion_pair_binding(revision_fd, pair)
        published = _scan_tree(
            revision_fd,
            protocol_state=_ProtocolState.PUBLISHED_PAIR,
            protocol_inode=inode,
        )
        if (
            _formal_entries(published) != _formal_entries(before)
            or _root_identity(published.root_fingerprint)
            != _root_identity(before.root_fingerprint)
            or _formal_tree_fingerprint(published)
            != parsed["formal_tree_fingerprint_sha256"]
        ):
            raise AcquisitionError("formal tree changed while publishing completion")
        _assert_completion_pair_binding(revision_fd, pair)
    return CompletionManifest(parsed)


def _stable_pair_read(
    fd: int,
    expected: _Fingerprint,
    expected_content: Optional[bytes] = None,
) -> bytes:
    if _fingerprint_fd(fd) != expected:
        raise AcquisitionError("held completion descriptor fingerprint changed")
    content = _read_bounded_fd(fd, SMALL_FILE_LIMIT)
    if _fingerprint_fd(fd) != expected:
        raise AcquisitionError("held completion descriptor changed while reading")
    if expected_content is not None and content != expected_content:
        raise AcquisitionError("held completion descriptor content changed")
    return content


def _open_completion_pair(revision_fd: int) -> _CompletionPair:
    pair = _CompletionPair()
    try:
        pair.guard_fd = _open_relative_regular(revision_fd, _COMPLETION_GUARD)
        pair.final_fd = _open_relative_regular(revision_fd, _COMPLETION)
        guard_stat = _fingerprint_fd(pair.guard_fd)
        final_stat = _fingerprint_fd(pair.final_fd)
        if (
            (guard_stat.device, guard_stat.inode)
            != (final_stat.device, final_stat.inode)
            or guard_stat != final_stat
            or guard_stat.nlink != 2
        ):
            raise AcquisitionError("completion guard/final pair is invalid")
        guard_content = _stable_pair_read(pair.guard_fd, guard_stat)
        final_content = _stable_pair_read(pair.final_fd, final_stat)
        if guard_content != final_content:
            raise AcquisitionError("completion guard/final content differs")
        pair.fingerprint = guard_stat
        pair.content = guard_content
        return pair
    except BaseException as original_error:
        pair.close(active_exception=original_error)
        raise


def _assert_completion_pair_binding(
    revision_fd: int, pair: _CompletionPair
) -> None:
    if pair.guard_fd < 0 or pair.final_fd < 0 or pair.fingerprint is None:
        raise AcquisitionError("completion pair is closed or incomplete")
    _stable_pair_read(pair.guard_fd, pair.fingerprint, pair.content)
    _stable_pair_read(pair.final_fd, pair.fingerprint, pair.content)
    canonical_fds = [-1, -1]
    try:
        canonical_fds[0] = _open_relative_regular(
            revision_fd, _COMPLETION_GUARD
        )
        canonical_fds[1] = _open_relative_regular(revision_fd, _COMPLETION)
        for fd in canonical_fds:
            current = _fingerprint_fd(fd)
            if current != pair.fingerprint or current.nlink != 2:
                raise AcquisitionError(
                    "canonical completion name no longer maps to held pair"
                )
            _stable_pair_read(fd, current, pair.content)
    finally:
        active_exception = sys.exc_info()[1]
        guard_fd, final_fd = canonical_fds
        canonical_fds[:] = [-1, -1]
        _close_fds_best_effort(
            (("final", final_fd), ("guard", guard_fd)),
            active_exception=active_exception,
        )


def _verify_complete_fd(
    revision_fd: int, pair: _CompletionPair
) -> tuple[CompletionManifest, TreeSnapshot]:
    _require_private_directory(revision_fd, "revision root")
    if pair.fingerprint is None:
        raise AcquisitionError("completion pair has no fingerprint")
    pair_inode = (pair.fingerprint.device, pair.fingerprint.inode)
    values = _strict_object(
        pair.content, _MANIFEST_KEYS, "completion manifest"
    )
    _validate_manifest(values)
    first = _scan_tree(
        revision_fd,
        protocol_state=_ProtocolState.PUBLISHED_PAIR,
        protocol_inode=pair_inode,
    )
    if _formal_tree_fingerprint(first) != values["formal_tree_fingerprint_sha256"]:
        raise AcquisitionError("formal tree fingerprint differs from completion manifest")
    checksums = _verify_checksums(
        revision_fd,
        protocol_state=_ProtocolState.PUBLISHED_PAIR,
        protocol_inode=pair_inode,
    )
    if checksums.sha256 != values["sha256sums_sha256"] or checksums.entry_count != values["sha256sums_entry_count"]:
        raise AcquisitionError("completion manifest checksum metadata differs")
    archive_fd = _open_relative_regular(revision_fd, _FORMAL_ARCHIVE)
    extracted_fd = -1
    try:
        archive_sha, archive_size, archive_stat = _hash_fd(archive_fd, ARCHIVE_LIMIT)
        if archive_stat.nlink != 1 or archive_sha != values["archive_sha256"] or archive_size != values["archive_size_bytes"]:
            raise AcquisitionError("formal archive differs from completion manifest")
        if values["size_download"] != archive_size:
            raise AcquisitionError("HTTP size differs from the formal archive")
        inspection = inspect_archive_fd(
            archive_fd,
            expected_sha256=archive_sha,
            max_total_bytes=EXTRACTED_LIMIT,
            max_members=MEMBER_LIMIT,
            max_metadata_bytes=METADATA_LIMIT,
        )
        if (
            inspection.format.value != values["archive_format"]
            or inspection.member_count != values["archive_member_count"]
            or inspection.total_declared_bytes
            != values["archive_declared_expanded_bytes"]
            or inspection.total_declared_bytes != first.extracted_bytes
        ):
            raise AcquisitionError("archive inspection metadata differs from completion manifest")
        extracted_fd = _open_relative_dir(revision_fd, _EXTRACTED)
        dataset = _validate_dataset(
            revision_fd,
            protocol_state=_ProtocolState.PUBLISHED_PAIR,
            protocol_inode=pair_inode,
        )
        if dataset.train_path != values["train_path"] or dataset.test_path != values["test_path"]:
            raise AcquisitionError("dataset paths differ from completion manifest")
    finally:
        if extracted_fd >= 0:
            os.close(extracted_fd)
        os.close(archive_fd)
    second = _scan_tree(
        revision_fd,
        protocol_state=_ProtocolState.PUBLISHED_PAIR,
        protocol_inode=pair_inode,
    )
    if first != second:
        raise AcquisitionError("completed tree is not stable across verification scans")
    return CompletionManifest(values), second


def _revision_parent(root_fd: int, revision_rel: str) -> tuple[int, str]:
    components = _relative_components(revision_rel)
    parent_fd = os.dup(root_fd)
    try:
        for component in components[:-1]:
            next_fd = os.open(component, _dir_flags(), dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        return parent_fd, components[-1]
    except BaseException:
        os.close(parent_fd)
        raise


def _capture_revision_binding(
    layout: _Layout, root_fd: int, revision_fd: int
) -> _RevisionBindingChain:
    components = _relative_components(layout.revision_rel)
    parent_fd = os.dup(root_fd)
    parents: list[tuple[str, _Fingerprint]] = []
    try:
        for component in components[:-1]:
            next_fd = os.open(component, _dir_flags(), dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
            parents.append((component, _fingerprint_fd(parent_fd)))
        named_fd = os.open(components[-1], _dir_flags(), dir_fd=parent_fd)
        try:
            named_fingerprint = _fingerprint_fd(named_fd)
            revision_fingerprint = _fingerprint_fd(revision_fd)
            if named_fingerprint != revision_fingerprint:
                raise AcquisitionError(
                    "canonical revision name does not map to held revision"
                )
        finally:
            os.close(named_fd)
        return _RevisionBindingChain(
            _fingerprint_fd(root_fd),
            tuple(parents),
            components[-1],
            revision_fingerprint,
        )
    finally:
        os.close(parent_fd)


def _assert_revision_binding_chain(
    layout: _Layout,
    root_fd: int,
    revision_fd: int,
    binding: _RevisionBindingChain,
    terminal_root_fingerprint: _Fingerprint,
) -> None:
    if _fingerprint_fd(root_fd) != binding.project_root_fingerprint:
        raise AcquisitionError("held project root identity changed")
    absolute_fd = _open_absolute_dir(layout.project_root)
    try:
        if _fingerprint_fd(absolute_fd) != binding.project_root_fingerprint:
            raise AcquisitionError("canonical project root was replaced")
    finally:
        os.close(absolute_fd)

    parent_fd = os.dup(root_fd)
    try:
        for component, expected_fingerprint in binding.parent_components:
            next_fd = os.open(component, _dir_flags(), dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
            if _fingerprint_fd(parent_fd) != expected_fingerprint:
                raise AcquisitionError(
                    f"revision parent component was replaced: {component}"
                )
        named_fd = os.open(binding.revision_leaf, _dir_flags(), dir_fd=parent_fd)
        try:
            named_fingerprint = _fingerprint_fd(named_fd)
            held_fingerprint = _fingerprint_fd(revision_fd)
            if (
                named_fingerprint != binding.revision_fingerprint
                or held_fingerprint != binding.revision_fingerprint
                or terminal_root_fingerprint != binding.revision_fingerprint
            ):
                raise AcquisitionError(
                    "canonical revision name no longer maps to held revision"
                )
        finally:
            os.close(named_fd)
    finally:
        os.close(parent_fd)


def _verify_complete_bound(
    layout: _Layout,
    root_fd: int,
    revision_fd: int,
    binding: _RevisionBindingChain,
) -> CompletionManifest:
    with _open_completion_pair(revision_fd) as pair:
        result, stable_snapshot = _verify_complete_fd(revision_fd, pair)
        if pair.fingerprint is None:
            raise AcquisitionError("completion pair has no terminal fingerprint")
        pair_inode = (pair.fingerprint.device, pair.fingerprint.inode)
        terminal_snapshot = _scan_tree(
            revision_fd,
            protocol_state=_ProtocolState.PUBLISHED_PAIR,
            protocol_inode=pair_inode,
        )
        if (
            terminal_snapshot != stable_snapshot
            or _formal_tree_fingerprint(terminal_snapshot)
            != result.values["formal_tree_fingerprint_sha256"]
        ):
            raise AcquisitionError("terminal completed tree is not stable")
        _assert_completion_pair_binding(revision_fd, pair)
        _assert_revision_binding_chain(
            layout,
            root_fd,
            revision_fd,
            binding,
            terminal_snapshot.root_fingerprint,
        )
        _assert_completion_pair_binding(revision_fd, pair)
        return result


def _verify_complete_layout(layout: _Layout) -> CompletionManifest:
    root_fd = _open_absolute_dir(layout.project_root)
    revision_parent_fd = revision_fd = -1
    try:
        revision_parent_fd, revision_leaf = _revision_parent(
            root_fd, layout.revision_rel
        )
        revision_fd = os.open(revision_leaf, _dir_flags(), dir_fd=revision_parent_fd)
        binding = _capture_revision_binding(layout, root_fd, revision_fd)
        try:
            return _verify_complete_bound(
                layout, root_fd, revision_fd, binding
            )
        finally:
            os.close(revision_fd)
    finally:
        if revision_parent_fd >= 0:
            os.close(revision_parent_fd)
        os.close(root_fd)


def _validate_stage_layout(layout: _Layout, expected_sha256: str) -> Mapping[str, Any]:
    _validate_hex(expected_sha256, 64, "expected SHA256")
    root_fd = _open_absolute_dir(layout.project_root)
    stage_fd = -1
    try:
        stage_fd = _open_relative_dir(root_fd, layout.stage_rel)
        try:
            _require_private_directory(stage_fd, "stage root")
            observation, digest, _ = _validate_http(stage_fd)
        finally:
            os.close(stage_fd)
    finally:
        os.close(root_fd)
    if digest != expected_sha256:
        raise AcquisitionError("stage archive differs from the approved SHA256")
    return {"http": asdict(observation), "archive_sha256": digest}


def _finalize_layout(layout: _Layout, expected_sha256: str, commit: str) -> CompletionManifest:
    _validate_hex(expected_sha256, 64, "expected SHA256")
    _validate_hex(commit, 40, "kairos commit")
    root_fd = _open_absolute_dir(layout.project_root)
    stage_fd = revision_parent_fd = revision_fd = extracted_fd = archive_fd = -1
    try:
        stage_fd = _open_relative_dir(root_fd, layout.stage_rel)
        _require_private_directory(stage_fd, "stage root")
        observation, observed_sha, _ = _validate_http(stage_fd)
        if observed_sha != expected_sha256:
            raise AcquisitionError("stage archive differs from the approved SHA256")
        revision_parent_fd, revision_leaf = _revision_parent(
            root_fd, layout.revision_rel
        )
        os.mkdir(revision_leaf, 0o700, dir_fd=revision_parent_fd)
        revision_fd = os.open(revision_leaf, _dir_flags(), dir_fd=revision_parent_fd)
        os.fchmod(revision_fd, 0o700)
        _require_private_directory(revision_fd, "revision root")
        archive = _copy_archive(stage_fd, revision_fd, expected_sha256)
        archive_fd = _open_relative_regular(revision_fd, _FORMAL_ARCHIVE)
        inspection = safe_extract_fd(
            archive_fd,
            revision_fd,
            _EXTRACTED,
            expected_sha256=expected_sha256,
            max_total_bytes=EXTRACTED_LIMIT,
            max_members=MEMBER_LIMIT,
            max_metadata_bytes=METADATA_LIMIT,
        )
        extracted_fd = os.open(_EXTRACTED, _dir_flags(), dir_fd=revision_fd)
        dataset = _validate_dataset(
            revision_fd, protocol_state=_ProtocolState.PRE_CHECKSUM
        )
        # Repeat the complete stage observation/source stability gate inside finalize.
        repeated_observation, repeated_sha, _ = _validate_http(stage_fd)
        if repeated_observation != observation or repeated_sha != expected_sha256:
            raise AcquisitionError("stage observation/archive changed during finalize")
        checksums = _write_checksums(revision_fd)
        formal_tree_fingerprint = _formal_tree_fingerprint(
            _scan_tree(
                revision_fd, protocol_state=_ProtocolState.FORMAL
            )
        )
        values = _completion_values(
            observation,
            archive,
            inspection,
            dataset,
            checksums,
            commit,
            formal_tree_fingerprint,
        )
        _publish_completion(revision_fd, values)
        binding = _capture_revision_binding(layout, root_fd, revision_fd)
        result = _verify_complete_bound(
            layout, root_fd, revision_fd, binding
        )
    finally:
        if archive_fd >= 0:
            os.close(archive_fd)
        if extracted_fd >= 0:
            os.close(extracted_fd)
        if revision_fd >= 0:
            os.close(revision_fd)
        if revision_parent_fd >= 0:
            os.close(revision_parent_fd)
        if stage_fd >= 0:
            os.close(stage_fd)
        os.close(root_fd)
    return result


def validate_stage(expected_sha256: str) -> Mapping[str, Any]:
    return _validate_stage_layout(_PRODUCTION_LAYOUT, expected_sha256)


def finalize(expected_sha256: str, kairos_commit: str) -> CompletionManifest:
    return _finalize_layout(_PRODUCTION_LAYOUT, expected_sha256, kairos_commit)


def verify_complete() -> CompletionManifest:
    return _verify_complete_layout(_PRODUCTION_LAYOUT)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kairos.acquisition")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-stage")
    validate.add_argument("--expected-sha256", required=True)
    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--expected-sha256", required=True)
    finalize_parser.add_argument("--kairos-commit", required=True)
    commands.add_parser("verify")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "validate-stage":
            result: Any = validate_stage(arguments.expected_sha256)
        elif arguments.command == "finalize":
            result = finalize(arguments.expected_sha256, arguments.kairos_commit).values
        else:
            result = verify_complete().values
    except (
        AcquisitionError,
        ArchiveSafetyError,
        FileExistsError,
        FileNotFoundError,
        OSError,
    ) as error:
        print(f"acquisition failed: {error}", file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AcquisitionError",
    "ArchiveCopyResult",
    "ChecksumReport",
    "CompletionManifest",
    "DatasetValidation",
    "HttpObservation",
    "finalize",
    "main",
    "validate_stage",
    "verify_complete",
]
