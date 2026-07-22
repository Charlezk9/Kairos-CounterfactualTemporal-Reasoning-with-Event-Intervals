"""Bounded StrategyQA transfer staging and offline stage verification.

This module deliberately stops before extraction, schema discovery, licensing,
or formal revision publication.  The public ``fetch`` entry point remains
fail-closed until the separately reviewed curl redirect runtime semantic is
verified.  Unit tests inject all policy and transfer subprocesses.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlsplit
import warnings

from .archive_safety import (
    ArchiveFormat,
    ArchiveInspection,
    ArchiveSafetyError,
    inspect_archive_fd,
)
from .ids import canonical_json


DATASET = "strategyqa"
REVISION = "official-20210107"
SOURCE_URL = (
    "https://storage.googleapis.com/ai2i/strategyqa/data/"
    "strategyqa_dataset.zip"
)
SOURCE_HOST = "storage.googleapis.com"
EXPECTED_ETAG_TOKEN = "f4ae9d9296c06f90d80aee1e4a25d58a"
EXPECTED_LAST_MODIFIED_DATE = "2021-01-07"
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    }
)

GIT_PATH = "/usr/bin/git"
GETENT_PATH = "/usr/bin/getent"
PRLIMIT_PATH = "/usr/bin/prlimit"
CURL_PATH = "/usr/bin/curl"
REPOSITORY_ROOT = Path("/home/yangbin/zx-tmp/kairos")
PROJECT_ROOT = Path("/data0/hk_data/kairos-zx")

ARCHIVE_LIMIT = 1_073_741_824
EXTRACTED_LIMIT = 2_147_483_648
MEMBER_LIMIT = 200_000
METADATA_LIMIT = 67_108_864
INVENTORY_LIMIT = 67_108_864
HEADER_LIMIT = 1_048_576
WRITEOUT_LIMIT = 4_096
STDERR_LIMIT = 65_536
PROCESS_RESULT_LIMIT = 4_096
MANIFEST_LIMIT = 1_048_576
COMMAND_OUTPUT_LIMIT = 4_096
PASSWD_OUTPUT_LIMIT = 8_388_608
GROUP_OUTPUT_LIMIT = 65_536
COMMAND_TIMEOUT_SECONDS = 10.0
TRANSFER_DEADLINE_SECONDS = 1_900.0
TRANSFER_GRACE_SECONDS = 10.0
COPY_CHUNK = 1_048_576

RESOURCE_AS_LIMIT = 8_589_934_592
RESOURCE_CPU_LIMIT = 900
RESOURCE_CORE_LIMIT = 0
RESOURCE_NOFILE_LIMIT = 64
RESOURCE_FSIZE_LIMIT = 1_073_741_824
RESOURCE_AFFINITY_LIMIT = 2

RUNTIME_REDIRECT_SEMANTICS_VERIFIED = False

_PARENT_RELATIVE = "data/raw/strategyqa"
_STAGE_LEAF = ".acquire-official-20210107"
_FORMAL_LEAF = REVISION
_ARCHIVE_NAME = "source.zip.part"
_HEADER_NAME = "http-headers.bin"
_WRITEOUT_NAME = "curl-writeout.txt"
_STDERR_NAME = "curl-stderr.bin"
_PROCESS_RESULT_NAME = "process-result.json"
_INVENTORY_NAME = "archive-members.jsonl"
_MANIFEST_GUARD = "stage-manifest.guard"
_MANIFEST_FINAL = "stage-manifest.json"
_INCOMPLETE_MARKER = ".stage-manifest.incomplete"
_TRANSACTION_MARKER = ".kairos-strategyqa-official-20210107.incomplete"
_TRANSACTION_VERSION = "kairos-strategyqa-transfer-v1"
_COMMON_EVIDENCE = (
    _ARCHIVE_NAME,
    _HEADER_NAME,
    _WRITEOUT_NAME,
    _STDERR_NAME,
    _PROCESS_RESULT_NAME,
)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEADER_NAME_RE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_HTTP_VERSIONS = frozenset({"HTTP/1.1", "HTTP/2"})
_INTERIM_STATUS = frozenset({100, 102, 103})
_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_ACL_NAMES = ("system.posix_acl_access", "system.posix_acl_default")

FROZEN_MEMBERSHIP: Mapping[str, Any] = {
    "uid": 1001,
    "gid": 1001,
    "username": "yangbin",
    "group_name": "yangbin",
    "explicit_members": [],
    "primary_users": ["yangbin"],
}
FROZEN_ACL: Mapping[str, Any] = {
    "checked_anchor_count": 4,
    "named_access_acl": "ABSENT",
    "default_acl": "ABSENT",
}

_WRITEOUT_BEGIN = "KAIROS_STRATEGYQA_WRITEOUT_V1"
_WRITEOUT_END = "KAIROS_STRATEGYQA_WRITEOUT_END"
_WRITEOUT_FORMAT = (
    f"{_WRITEOUT_BEGIN}\n"
    "http_code:%{http_code}\n"
    "num_redirects:%{num_redirects}\n"
    "url_effective:%{url_effective}\n"
    "content_type:%{content_type}\n"
    "size_download:%{size_download}\n"
    f"{_WRITEOUT_END}\n"
)


class StrategyQaAcquisitionError(ValueError):
    """A transfer-stage safety or integrity invariant failed."""


class _SourceBlocked(StrategyQaAcquisitionError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code


class _ControlledTransferStop(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class StageStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"
    STAGE_OK = "STAGE_OK"


@dataclass(frozen=True)
class StageReport:
    status: StageStatus
    reason_code: str
    observation: Optional[Mapping[str, Any]]

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "observation": self.observation,
        }


@dataclass(frozen=True)
class ChainAnchor:
    path: str
    device: int
    inode: int
    uid: int
    gid: int
    mode: int


FROZEN_CHAIN_ANCHORS = (
    ChainAnchor("/", 66_306, 2, 0, 0, stat.S_IFDIR | 0o755),
    ChainAnchor("/data0", 2_048, 2, 0, 1_002, stat.S_IFDIR | 0o775),
    ChainAnchor(
        "/data0/hk_data",
        2_048,
        176_553_985,
        1_001,
        1_001,
        stat.S_IFDIR | 0o775,
    ),
    ChainAnchor(
        "/data0/hk_data/kairos-zx",
        2_048,
        176_553_986,
        1_001,
        1_001,
        stat.S_IFDIR | 0o775,
    ),
)


@dataclass(frozen=True)
class _Layout:
    project_root: Path
    parent_relative: str
    stage_leaf: str
    formal_leaf: str

    @property
    def stage(self) -> Path:
        return self.project_root / self.parent_relative / self.stage_leaf


_PRODUCTION_LAYOUT = _Layout(
    PROJECT_ROOT, _PARENT_RELATIVE, _STAGE_LEAF, _FORMAL_LEAF
)


@dataclass(frozen=True)
class _Fingerprint:
    device: int
    inode: int
    uid: int
    gid: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _FileFacts:
    size: int
    sha256: str
    fingerprint: _Fingerprint
    content: Optional[bytes] = None


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    watchdog_action: str
    reason_code: str


@dataclass(frozen=True)
class _HeaderObservation:
    http_version: str
    status_code: int
    retry_failure_statuses: tuple[int, ...]
    etag_token: str
    last_modified: str
    content_type: str
    content_length: int


@dataclass(frozen=True)
class _WriteoutObservation:
    http_code: int
    num_redirects: int
    effective_url: str
    content_type: str
    size_download: int


@dataclass(frozen=True)
class _Evaluation:
    status: StageStatus
    reason_code: str
    http: Optional[Mapping[str, Any]]
    archive: Optional[Mapping[str, Any]]
    inventory: Optional[bytes]


@dataclass(frozen=True)
class _PublishedManifest:
    guard_fd: int
    final_fd: int
    pair_fingerprint: _Fingerprint
    stage_fingerprint: _Fingerprint
    content: bytes


GitChecker = Callable[[str], str]
MembershipChecker = Callable[[], Mapping[str, Any]]
AclChecker = Callable[[Sequence[int]], Mapping[str, Any]]
TransferRunner = Callable[[int, int, int, int], _ProcessResult]


def _fingerprint_fd(fd: int) -> _Fingerprint:
    value = os.fstat(fd)
    return _Fingerprint(
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _fingerprint_stat(value: os.stat_result) -> _Fingerprint:
    return _Fingerprint(
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _identity(value: _Fingerprint) -> tuple[int, int, int, int, int]:
    return value.device, value.inode, value.uid, value.gid, value.mode


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


def _close_objects_best_effort(
    named_objects: Iterable[tuple[str, Any]],
    active_exception: Optional[BaseException] = None,
) -> None:
    first_error: Optional[BaseException] = None
    for _name, value in tuple(named_objects):
        if value is None:
            continue
        try:
            value.close()
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None and active_exception is None:
        raise first_error


def _dir_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _regular_read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _anchor_matches(fd: int, anchor: ChainAnchor) -> bool:
    current = _fingerprint_fd(fd)
    return (
        current.device,
        current.inode,
        current.uid,
        current.gid,
        current.mode,
    ) == (
        anchor.device,
        anchor.inode,
        anchor.uid,
        anchor.gid,
        anchor.mode,
    )


def _open_absolute_chain(
    project_root: Path, anchors: Sequence[ChainAnchor]
) -> list[int]:
    raw = os.fspath(project_root)
    if not os.path.isabs(raw):
        raise StrategyQaAcquisitionError("project root must be absolute")
    components = [component for component in raw.split("/")[1:] if component]
    expected_paths = ["/"]
    current_path = ""
    for component in components:
        current_path += "/" + component
        expected_paths.append(current_path)
    if tuple(expected_paths) != tuple(anchor.path for anchor in anchors):
        raise StrategyQaAcquisitionError("absolute anchor paths differ")
    held: list[int] = []
    try:
        held.append(os.open("/", _dir_flags()))
        if not _anchor_matches(held[-1], anchors[0]):
            raise StrategyQaAcquisitionError("filesystem root anchor differs")
        for component, anchor in zip(components, anchors[1:]):
            held.append(os.open(component, _dir_flags(), dir_fd=held[-1]))
            if not _anchor_matches(held[-1], anchor):
                raise StrategyQaAcquisitionError(
                    f"absolute chain anchor differs: {anchor.path}"
                )
        return held
    except BaseException:
        active = sys.exc_info()[1]
        owned = [("absolute-chain", fd) for fd in reversed(held)]
        held.clear()
        _close_fds_best_effort(owned, active)
        raise


def _assert_absolute_chain(
    project_root: Path, held: Sequence[int], anchors: Sequence[ChainAnchor]
) -> None:
    if len(held) != len(anchors):
        raise StrategyQaAcquisitionError("held absolute chain length differs")
    for fd, anchor in zip(held, anchors):
        if not _anchor_matches(fd, anchor):
            raise StrategyQaAcquisitionError(
                f"held absolute chain changed: {anchor.path}"
            )
    reopened = _open_absolute_chain(project_root, anchors)
    try:
        if tuple(_identity(_fingerprint_fd(fd)) for fd in reopened) != tuple(
            _identity(_fingerprint_fd(fd)) for fd in held
        ):
            raise StrategyQaAcquisitionError("canonical absolute chain changed")
    finally:
        active = sys.exc_info()[1]
        owned = [("canonical-absolute", fd) for fd in reversed(reopened)]
        reopened.clear()
        _close_fds_best_effort(owned, active)


def _relative_components(path: str) -> tuple[str, ...]:
    if not path or path.startswith("/") or "\\" in path:
        raise StrategyQaAcquisitionError("relative path is invalid")
    components = tuple(path.split("/"))
    if any(component in {"", ".", ".."} for component in components):
        raise StrategyQaAcquisitionError("relative path contains an unsafe component")
    return components


def _require_private_directory(fd: int, label: str) -> None:
    current = _fingerprint_fd(fd)
    if (
        current.uid != os.geteuid()
        or current.mode != stat.S_IFDIR | 0o700
    ):
        raise StrategyQaAcquisitionError(f"{label} must be an owned 0700 directory")


def _open_or_create_parent_chain(
    project_fd: int, relative: str
) -> list[int]:
    held = [os.dup(project_fd)]
    try:
        for component in _relative_components(relative):
            created = False
            try:
                next_fd = os.open(component, _dir_flags(), dir_fd=held[-1])
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=held[-1])
                os.fsync(held[-1])
                next_fd = os.open(component, _dir_flags(), dir_fd=held[-1])
                created = True
            held.append(next_fd)
            _require_private_directory(next_fd, component)
            if created and stat.S_IMODE(os.fstat(next_fd).st_mode) != 0o700:
                raise StrategyQaAcquisitionError("created parent mode differs")
        return held
    except BaseException:
        active = sys.exc_info()[1]
        owned = [("parent-chain", fd) for fd in reversed(held)]
        held.clear()
        _close_fds_best_effort(owned, active)
        raise


def _open_parent_chain(project_fd: int, relative: str) -> list[int]:
    held = [os.dup(project_fd)]
    try:
        for component in _relative_components(relative):
            held.append(os.open(component, _dir_flags(), dir_fd=held[-1]))
            _require_private_directory(held[-1], component)
        return held
    except BaseException:
        active = sys.exc_info()[1]
        owned = [("open-parent", fd) for fd in reversed(held)]
        held.clear()
        _close_fds_best_effort(owned, active)
        raise


def _assert_parent_chain(
    project_fd: int,
    relative: str,
    held: Sequence[int],
    expected: Sequence[tuple[int, int, int, int, int]],
) -> None:
    if tuple(_identity(_fingerprint_fd(fd)) for fd in held) != tuple(expected):
        raise StrategyQaAcquisitionError("held parent chain changed")
    reopened = _open_parent_chain(project_fd, relative)
    try:
        if tuple(_identity(_fingerprint_fd(fd)) for fd in reopened) != tuple(expected):
            raise StrategyQaAcquisitionError("canonical parent chain changed")
    finally:
        active = sys.exc_info()[1]
        owned = [("canonical-parent", fd) for fd in reversed(reopened)]
        reopened.clear()
        _close_fds_best_effort(owned, active)


def _entry_fingerprint(parent_fd: int, name: str) -> Optional[_Fingerprint]:
    try:
        value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return _fingerprint_stat(value)


def _require_absent(parent_fd: int, name: str, label: str) -> None:
    if _entry_fingerprint(parent_fd, name) is not None:
        raise FileExistsError(f"{label} already exists")


def _assert_stage_binding(
    parent_fd: int, stage_leaf: str, stage_fd: int, expected_identity: tuple[int, ...]
) -> None:
    _require_private_directory(stage_fd, "StrategyQA stage")
    if _identity(_fingerprint_fd(stage_fd)) != tuple(expected_identity):
        raise StrategyQaAcquisitionError("held stage identity changed")
    canonical_fd = -1
    try:
        canonical_fd = os.open(stage_leaf, _dir_flags(), dir_fd=parent_fd)
        _require_private_directory(canonical_fd, "canonical StrategyQA stage")
        if _identity(_fingerprint_fd(canonical_fd)) != tuple(expected_identity):
            raise StrategyQaAcquisitionError("canonical stage identity changed")
    finally:
        active = sys.exc_info()[1]
        owned = canonical_fd
        canonical_fd = -1
        _close_fds_best_effort((("canonical-stage", owned),), active)


def _create_private_file(stage_fd: int, name: str) -> int:
    fd = os.open(
        name,
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=stage_fd,
    )
    try:
        os.fchmod(fd, 0o600)
        current = _fingerprint_fd(fd)
        if (
            current.uid != os.geteuid()
            or current.mode != stat.S_IFREG | 0o600
            or current.nlink != 1
        ):
            raise StrategyQaAcquisitionError("created evidence file is not private")
        return fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort(((name, owned),), active)
        raise


def _open_private_file(stage_fd: int, name: str, flags: int = os.O_RDONLY) -> int:
    fd = os.open(
        name,
        flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=stage_fd,
    )
    try:
        current = _fingerprint_fd(fd)
        if (
            current.uid != os.geteuid()
            or current.mode != stat.S_IFREG | 0o600
            or current.nlink != 1
        ):
            raise StrategyQaAcquisitionError(f"invalid private file: {name}")
        return fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort(((name, owned),), active)
        raise


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(fd, content[offset:])
        if written <= 0:
            raise StrategyQaAcquisitionError("short evidence write")
        offset += written


def _pread_bounded(fd: int, limit: int) -> bytes:
    result = bytearray()
    offset = 0
    while offset <= limit:
        chunk = os.pread(fd, min(COPY_CHUNK, limit + 1 - offset), offset)
        if not chunk:
            break
        result.extend(chunk)
        offset += len(chunk)
        if offset > limit:
            raise StrategyQaAcquisitionError("file exceeds its read limit")
    return bytes(result)


def _file_facts(fd: int, limit: int, include_content: bool = False) -> _FileFacts:
    before = _fingerprint_fd(fd)
    if (
        before.mode != stat.S_IFREG | 0o600
        or before.uid != os.geteuid()
        or before.nlink != 1
        or before.size > limit
    ):
        raise StrategyQaAcquisitionError("file binding or size differs")
    digest = hashlib.sha256()
    content = bytearray() if include_content else None
    offset = 0
    while offset <= limit:
        chunk = os.pread(fd, min(COPY_CHUNK, limit + 1 - offset), offset)
        if not chunk:
            break
        offset += len(chunk)
        if offset > limit:
            raise StrategyQaAcquisitionError("file exceeds its hash limit")
        digest.update(chunk)
        if content is not None:
            content.extend(chunk)
    after = _fingerprint_fd(fd)
    if before != after or offset != after.size:
        raise StrategyQaAcquisitionError("file changed while hashing")
    return _FileFacts(
        offset,
        digest.hexdigest(),
        after,
        bytes(content) if content is not None else None,
    )


def _strict_json_object(content: bytes, label: str) -> Mapping[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise StrategyQaAcquisitionError(
                    f"duplicate JSON key in {label}: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise StrategyQaAcquisitionError(
            f"non-finite JSON value in {label}: {value}"
        )

    try:
        value = json.loads(
            content,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StrategyQaAcquisitionError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise StrategyQaAcquisitionError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise StrategyQaAcquisitionError(f"{label} keys differ")


def _validate_commit(value: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise StrategyQaAcquisitionError(
            "approved commit must be 40 lowercase hexadecimal characters"
        )
    return value


def _owned_process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_group_gone(
    process: subprocess.Popen[Any], pgid: int, timeout_seconds: float
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        process.poll()
        if not _owned_process_group_alive(pgid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _terminate_owned_group(
    process: subprocess.Popen[Any], pgid: int, grace_seconds: float
) -> str:
    first_error: Optional[BaseException] = None
    action = "SIGTERM"
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except BaseException as error:
        first_error = error
    gone = False
    if first_error is None:
        try:
            gone = _wait_group_gone(process, pgid, grace_seconds)
        except BaseException as error:
            first_error = error
    if not gone:
        action = "SIGKILL"
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except BaseException as error:
            if first_error is None:
                first_error = error
        try:
            if not _wait_group_gone(process, pgid, grace_seconds):
                if first_error is None:
                    first_error = StrategyQaAcquisitionError(
                        "owned subprocess group survived SIGKILL"
                    )
        except BaseException as error:
            if first_error is None:
                first_error = error
    try:
        process.wait(timeout=grace_seconds)
    except BaseException as error:
        if first_error is None:
            first_error = error
    if first_error is not None:
        raise first_error
    return action


def _strict_command_environment(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    result = {"LC_ALL": "C", "LANG": "C", "TZ": "UTC"}
    if extra:
        result.update(extra)
    return result


def _run_bounded_command(
    arguments: Sequence[str],
    *,
    timeout_seconds: float,
    output_limit: int,
    environment: Mapping[str, str],
) -> tuple[int, bytes]:
    if timeout_seconds <= 0 or output_limit < 0:
        raise StrategyQaAcquisitionError("bounded command limit is invalid")
    process = subprocess.Popen(
        tuple(arguments),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=os.fspath(REPOSITORY_ROOT),
        env=dict(environment),
        shell=False,
        close_fds=True,
        start_new_session=True,
    )
    pgid = process.pid
    selector: Optional[selectors.BaseSelector] = None
    stdout = None
    output = bytearray()
    try:
        stdout = process.stdout
        if stdout is None:
            raise StrategyQaAcquisitionError("bounded command stdout is unavailable")
        selector = selectors.DefaultSelector()
        fd = stdout.fileno()
        os.set_blocking(fd, False)
        selector.register(fd, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        eof = False
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StrategyQaAcquisitionError("bounded command timed out")
            events = selector.select(remaining)
            if not events:
                raise StrategyQaAcquisitionError("bounded command timed out")
            for key, _mask in events:
                try:
                    chunk = os.read(
                        key.fd,
                        min(65_536, output_limit + 1 - len(output)),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    eof = True
                    break
                output.extend(chunk)
                if len(output) > output_limit:
                    raise StrategyQaAcquisitionError(
                        "bounded command output exceeds its limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StrategyQaAcquisitionError("bounded command timed out")
        returncode = process.wait(timeout=remaining)
        if _owned_process_group_alive(pgid):
            raise StrategyQaAcquisitionError(
                "bounded command group outlived its leader"
            )
        return returncode, bytes(output)
    except BaseException:
        try:
            _terminate_owned_group(process, pgid, 1.0)
        except BaseException as cleanup_error:
            raise StrategyQaAcquisitionError(
                "bounded command cleanup is unconfirmed"
            ) from cleanup_error
        raise
    finally:
        active = sys.exc_info()[1]
        _close_objects_best_effort(
            (("selector", selector), ("stdout", stdout)), active
        )


def _git_environment() -> Mapping[str, str]:
    return _strict_command_environment(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )


def _run_git(arguments: Sequence[str]) -> tuple[int, bytes]:
    return _run_bounded_command(
        (
            GIT_PATH,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-C",
            os.fspath(REPOSITORY_ROOT),
            *arguments,
        ),
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        output_limit=COMMAND_OUTPUT_LIMIT,
        environment=_git_environment(),
    )


def _git_clean_head(approved_commit: str) -> str:
    approved = _validate_commit(approved_commit)
    expected = (approved + "\n").encode("ascii")
    first_code, first = _run_git(("rev-parse", "--verify", "HEAD"))
    status_code, status_output = _run_git(
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--ignore-submodules=none",
        )
    )
    second_code, second = _run_git(("rev-parse", "--verify", "HEAD"))
    if (
        first_code != 0
        or status_code != 0
        or second_code != 0
        or first != expected
        or second != expected
        or status_output
    ):
        raise StrategyQaAcquisitionError("repository is not the approved clean HEAD")
    return approved


def _run_getent(arguments: Sequence[str], output_limit: int) -> tuple[int, bytes]:
    return _run_bounded_command(
        (GETENT_PATH, *arguments),
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        output_limit=output_limit,
        environment=_strict_command_environment(),
    )


def _decode_getent_lines(content: bytes, label: str) -> list[str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StrategyQaAcquisitionError(f"invalid UTF-8 in {label}") from error
    if text and not text.endswith("\n"):
        raise StrategyQaAcquisitionError(f"unterminated {label} output")
    lines = text.splitlines()
    if any(not line or "\x00" in line for line in lines):
        raise StrategyQaAcquisitionError(f"invalid {label} output line")
    return lines


def _verify_private_group() -> Mapping[str, Any]:
    group_code, group_output = _run_getent(("group", "1001"), GROUP_OUTPUT_LIMIT)
    passwd_code, passwd_output = _run_getent(("passwd",), PASSWD_OUTPUT_LIMIT)
    if group_code != 0 or passwd_code != 0:
        raise StrategyQaAcquisitionError("NSS private-group query failed")
    group_lines = _decode_getent_lines(group_output, "group")
    if len(group_lines) != 1:
        raise StrategyQaAcquisitionError("GID 1001 group lookup is ambiguous")
    group_fields = group_lines[0].split(":")
    if (
        len(group_fields) != 4
        or group_fields[0] != "yangbin"
        or group_fields[2] != "1001"
    ):
        raise StrategyQaAcquisitionError("GID 1001 group record differs")
    if group_fields[3]:
        raw_members = group_fields[3].split(",")
        if any(not member for member in raw_members) or len(raw_members) != len(
            set(raw_members)
        ):
            raise StrategyQaAcquisitionError("GID 1001 member list is malformed")
        explicit_members = tuple(raw_members)
    else:
        explicit_members = ()
    if explicit_members:
        raise StrategyQaAcquisitionError("GID 1001 has an explicit member")
    primary_users: list[tuple[str, int]] = []
    uid_1001: list[tuple[str, int]] = []
    for line in _decode_getent_lines(passwd_output, "passwd"):
        fields = line.split(":")
        if len(fields) != 7 or not fields[2].isdigit() or not fields[3].isdigit():
            raise StrategyQaAcquisitionError("passwd record is malformed")
        uid = int(fields[2])
        gid = int(fields[3])
        if gid == 1001:
            primary_users.append((fields[0], uid))
        if uid == 1001:
            uid_1001.append((fields[0], gid))
    if primary_users != [("yangbin", 1001)] or uid_1001 != [("yangbin", 1001)]:
        raise StrategyQaAcquisitionError("private GID/UID population differs")
    if os.geteuid() != 1001:
        raise StrategyQaAcquisitionError("effective UID is not the frozen owner")
    return dict(FROZEN_MEMBERSHIP)


def _verify_chain_acl(chain_fds: Sequence[int]) -> Mapping[str, Any]:
    if len(chain_fds) != len(FROZEN_CHAIN_ANCHORS):
        raise StrategyQaAcquisitionError("ACL anchor count differs")
    accepted = {errno.ENODATA}
    enoattr = getattr(errno, "ENOATTR", None)
    if enoattr is not None:
        accepted.add(enoattr)
    for anchor_fd in chain_fds:
        for name in _ACL_NAMES:
            try:
                os.getxattr(anchor_fd, name)
            except OSError as error:
                if error.errno in accepted:
                    continue
                raise StrategyQaAcquisitionError(
                    f"absolute-chain ACL query is unconfirmed: {name}"
                ) from error
            else:
                raise StrategyQaAcquisitionError(
                    f"absolute-chain ACL xattr is present: {name}"
                )
    return dict(FROZEN_ACL)


def _child_environment() -> Mapping[str, str]:
    return {
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "NUMEXPR_NUM_THREADS": "2",
        "TOKENIZERS_PARALLELISM": "false",
    }


_RESOURCE_RULES = (
    ("address_space", resource.RLIMIT_AS, RESOURCE_AS_LIMIT),
    ("cpu_seconds", resource.RLIMIT_CPU, RESOURCE_CPU_LIMIT),
    ("core_bytes", resource.RLIMIT_CORE, RESOURCE_CORE_LIMIT),
    ("open_files", resource.RLIMIT_NOFILE, RESOURCE_NOFILE_LIMIT),
    ("file_size_bytes", resource.RLIMIT_FSIZE, RESOURCE_FSIZE_LIMIT),
)
_RUNTIME_ENVIRONMENT = {
    "CUDA_VISIBLE_DEVICES": "",
    "OMP_NUM_THREADS": "2",
    "MKL_NUM_THREADS": "2",
    "OPENBLAS_NUM_THREADS": "2",
    "NUMEXPR_NUM_THREADS": "2",
    "TOKENIZERS_PARALLELISM": "false",
}


def _resource_observation() -> Mapping[str, Any]:
    limits: dict[str, Mapping[str, int]] = {}
    for name, resource_id, _maximum in _RESOURCE_RULES:
        soft, hard = resource.getrlimit(resource_id)
        limits[name] = {"soft": int(soft), "hard": int(hard)}
    affinity = tuple(sorted(os.sched_getaffinity(0)))
    return {
        "limits": limits,
        "cpu_affinity": list(affinity),
        "environment": {
            name: os.environ.get(name) for name in sorted(_RUNTIME_ENVIRONMENT)
        },
    }


def _validate_resource_observation(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "limits",
        "cpu_affinity",
        "environment",
    }:
        raise StrategyQaAcquisitionError("runtime resource observation differs")
    limits = value["limits"]
    if not isinstance(limits, Mapping) or set(limits) != {
        name for name, _resource_id, _maximum in _RESOURCE_RULES
    }:
        raise StrategyQaAcquisitionError("runtime resource limits differ")
    normalized_limits: dict[str, Mapping[str, int]] = {}
    for name, _resource_id, maximum in _RESOURCE_RULES:
        pair = limits[name]
        if not isinstance(pair, Mapping) or set(pair) != {"soft", "hard"}:
            raise StrategyQaAcquisitionError("runtime resource pair differs")
        soft, hard = pair["soft"], pair["hard"]
        if (
            isinstance(soft, bool)
            or not isinstance(soft, int)
            or isinstance(hard, bool)
            or not isinstance(hard, int)
            or soft == resource.RLIM_INFINITY
            or soft < 0
            or soft > maximum
            or hard == resource.RLIM_INFINITY
            or hard < soft
            or hard < 0
            or hard > maximum
        ):
            raise StrategyQaAcquisitionError(f"runtime {name} limit is unsafe")
        if name == "core_bytes" and soft != 0:
            raise StrategyQaAcquisitionError("runtime core limit is unsafe")
        normalized_limits[name] = {"soft": soft, "hard": hard}
    affinity = value["cpu_affinity"]
    if (
        not isinstance(affinity, list)
        or not affinity
        or len(affinity) > RESOURCE_AFFINITY_LIMIT
        or any(isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0 for cpu in affinity)
        or affinity != sorted(set(affinity))
    ):
        raise StrategyQaAcquisitionError("runtime CPU affinity is unsafe")
    environment = value["environment"]
    if environment != {
        name: _RUNTIME_ENVIRONMENT[name] for name in sorted(_RUNTIME_ENVIRONMENT)
    }:
        raise StrategyQaAcquisitionError("runtime thread/GPU environment differs")
    return {
        "limits": normalized_limits,
        "cpu_affinity": list(affinity),
        "environment": dict(environment),
    }


def _validate_runtime_gate() -> Mapping[str, Any]:
    return _validate_resource_observation(_resource_observation())


def _apply_cli_resource_gate() -> Mapping[str, Any]:
    for name, value in _RUNTIME_ENVIRONMENT.items():
        os.environ[name] = value
    for _name, resource_id, maximum in _RESOURCE_RULES:
        soft, hard = resource.getrlimit(resource_id)
        target_hard = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        target_soft = target_hard if soft == resource.RLIM_INFINITY else min(soft, target_hard)
        resource.setrlimit(resource_id, (target_soft, target_hard))
    affinity = tuple(sorted(os.sched_getaffinity(0)))
    if not affinity:
        raise StrategyQaAcquisitionError("runtime CPU affinity is empty")
    if len(affinity) > RESOURCE_AFFINITY_LIMIT:
        os.sched_setaffinity(0, affinity[:RESOURCE_AFFINITY_LIMIT])
    return _validate_runtime_gate()


def _build_curl_argv(archive_fd: int, header_write_fd: int) -> tuple[str, ...]:
    for value in (archive_fd, header_write_fd):
        if type(value) is not int or value < 0:
            raise StrategyQaAcquisitionError("curl descriptor is invalid")
    return (
        PRLIMIT_PATH,
        "--fsize=1073741824:1073741824",
        "--as=8589934592:8589934592",
        "--cpu=300:300",
        "--nofile=64:64",
        "--core=0:0",
        "--",
        CURL_PATH,
        "--disable",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--fail",
        "--location",
        "--max-redirs",
        "0",
        "--retry",
        "3",
        "--retry-connrefused",
        "--retry-delay",
        "2",
        "--retry-max-time",
        "120",
        "--connect-timeout",
        "20",
        "--max-time",
        "1800",
        "--speed-limit",
        "1024",
        "--speed-time",
        "30",
        "--max-filesize",
        str(ARCHIVE_LIMIT),
        "--silent",
        "--show-error",
        "--dump-header",
        f"/proc/self/fd/{header_write_fd}",
        "--output",
        f"/proc/self/fd/{archive_fd}",
        "--write-out",
        _WRITEOUT_FORMAT,
        SOURCE_URL,
    )


def _verify_procfd_alias(fd: int, flags: int) -> None:
    alias = os.open(f"/proc/self/fd/{fd}", flags | getattr(os, "O_CLOEXEC", 0))
    try:
        left = os.fstat(fd)
        right = os.fstat(alias)
        if (left.st_dev, left.st_ino, stat.S_IFMT(left.st_mode)) != (
            right.st_dev,
            right.st_ino,
            stat.S_IFMT(right.st_mode),
        ):
            raise StrategyQaAcquisitionError("procfd alias binding differs")
    finally:
        os.close(alias)


def _run_transfer(
    archive_fd: int,
    header_evidence_fd: int,
    writeout_evidence_fd: int,
    stderr_evidence_fd: int,
    *,
    timeout_seconds: float = TRANSFER_DEADLINE_SECONDS,
    grace_seconds: float = TRANSFER_GRACE_SECONDS,
) -> _ProcessResult:
    header_read_fd = header_write_fd = -1
    process: Optional[subprocess.Popen[Any]] = None
    selector: Optional[selectors.BaseSelector] = None
    stdout = stderr = None
    pgid: Optional[int] = None
    counts = {"HEADER": 0, "WRITEOUT": 0, "STDERR": 0}
    limits = {
        "HEADER": HEADER_LIMIT,
        "WRITEOUT": WRITEOUT_LIMIT,
        "STDERR": STDERR_LIMIT,
    }
    destinations = {
        "HEADER": header_evidence_fd,
        "WRITEOUT": writeout_evidence_fd,
        "STDERR": stderr_evidence_fd,
    }
    watchdog_action = "NONE"
    try:
        header_read_fd, header_write_fd = os.pipe2(getattr(os, "O_CLOEXEC", 0))
        _verify_procfd_alias(archive_fd, os.O_WRONLY)
        _verify_procfd_alias(header_write_fd, os.O_WRONLY)
        process = subprocess.Popen(
            _build_curl_argv(archive_fd, header_write_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.fspath(PROJECT_ROOT),
            env=dict(_child_environment()),
            shell=False,
            close_fds=True,
            pass_fds=(archive_fd, header_write_fd),
            start_new_session=True,
        )
        pgid = process.pid
        stdout = process.stdout
        stderr = process.stderr
        if stdout is None or stderr is None:
            raise StrategyQaAcquisitionError("curl pipe is unavailable")
        owned_header_write_fd = header_write_fd
        header_write_fd = -1
        os.close(owned_header_write_fd)
        selector = selectors.DefaultSelector()
        routes = {
            header_read_fd: "HEADER",
            stdout.fileno(): "WRITEOUT",
            stderr.fileno(): "STDERR",
        }
        for fd, route in routes.items():
            os.set_blocking(fd, False)
            selector.register(fd, selectors.EVENT_READ, data=route)
        deadline = time.monotonic() + timeout_seconds
        open_routes = set(routes)
        while open_routes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _ControlledTransferStop("TIMEOUT")
            events = selector.select(remaining)
            if not events:
                raise _ControlledTransferStop("TIMEOUT")
            for key, _mask in events:
                route = key.data
                try:
                    remaining_capacity = limits[route] - counts[route]
                    chunk = os.read(
                        key.fd,
                        min(65_536, remaining_capacity + 1),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    open_routes.discard(key.fd)
                    continue
                if len(chunk) > remaining_capacity:
                    if remaining_capacity:
                        _write_all(destinations[route], chunk[:remaining_capacity])
                    raise _ControlledTransferStop(f"{route}_LIMIT")
                _write_all(destinations[route], chunk)
                counts[route] += len(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _ControlledTransferStop("TIMEOUT")
        returncode = process.wait(timeout=remaining)
        if _owned_process_group_alive(pgid):
            raise _ControlledTransferStop("GROUP_OUTLIVED")
        return _ProcessResult(returncode, "NONE", "NONE")
    except _ControlledTransferStop as error:
        if process is None or pgid is None:
            raise StrategyQaAcquisitionError("controlled stop preceded curl spawn")
        watchdog_action = _terminate_owned_group(process, pgid, grace_seconds)
        return _ProcessResult(
            int(process.returncode if process.returncode is not None else -1),
            watchdog_action,
            error.reason_code,
        )
    except BaseException:
        if process is not None and pgid is not None:
            try:
                _terminate_owned_group(process, pgid, grace_seconds)
            except BaseException as cleanup_error:
                raise StrategyQaAcquisitionError(
                    "curl process-group cleanup is unconfirmed"
                ) from cleanup_error
        raise
    finally:
        active = sys.exc_info()[1]
        owned_fds = (
            ("header-write", header_write_fd),
            ("header-read", header_read_fd),
        )
        header_write_fd = header_read_fd = -1
        first_cleanup: Optional[BaseException] = None
        try:
            _close_objects_best_effort(
                (("selector", selector), ("stdout", stdout), ("stderr", stderr)),
                active,
            )
        except BaseException as error:
            first_cleanup = error
        try:
            _close_fds_best_effort(owned_fds, active or first_cleanup)
        except BaseException as error:
            if first_cleanup is None:
                first_cleanup = error
        if first_cleanup is not None and active is None:
            raise first_cleanup


def _process_result_bytes(result: _ProcessResult) -> bytes:
    return canonical_json(
        {
            "returncode": result.returncode,
            "watchdog_action": result.watchdog_action,
            "reason_code": result.reason_code,
        }
    ).encode("utf-8") + b"\n"


def _parse_process_result(content: bytes) -> _ProcessResult:
    value = _strict_json_object(content, "process result")
    _exact_keys(value, {"returncode", "watchdog_action", "reason_code"}, "process result")
    if isinstance(value["returncode"], bool) or not isinstance(value["returncode"], int):
        raise StrategyQaAcquisitionError("process returncode must be an integer")
    if value["watchdog_action"] not in {"NONE", "SIGTERM", "SIGKILL"}:
        raise StrategyQaAcquisitionError("watchdog action differs")
    if value["reason_code"] not in {
        "NONE",
        "TIMEOUT",
        "HEADER_LIMIT",
        "WRITEOUT_LIMIT",
        "STDERR_LIMIT",
        "GROUP_OUTLIVED",
    }:
        raise StrategyQaAcquisitionError("process reason differs")
    if (value["reason_code"] == "NONE") != (
        value["watchdog_action"] == "NONE"
    ):
        raise StrategyQaAcquisitionError("process watchdog state is inconsistent")
    return _ProcessResult(
        value["returncode"], value["watchdog_action"], value["reason_code"]
    )


def _parse_header_blocks(content: bytes) -> _HeaderObservation:
    if not content or len(content) > HEADER_LIMIT:
        raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header evidence is absent or large")
    if b"\x00" in content or re.search(br"(?<!\r)\n", content):
        raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header line ending is invalid")
    if not content.endswith(b"\r\n\r\n"):
        raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header transcript is unterminated")
    raw_blocks = content[:-4].split(b"\r\n\r\n")
    parsed: list[tuple[str, int, Mapping[str, list[str]]]] = []
    for raw in raw_blocks:
        lines = raw.split(b"\r\n")
        try:
            decoded = [line.decode("ascii") for line in lines]
        except UnicodeDecodeError as error:
            raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header is not ASCII") from error
        if not decoded or any(len(line) > 8_192 for line in decoded):
            raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header line differs")
        match = re.fullmatch(
            r"(HTTP/(?:1\.1|2)) ([0-9]{3})(?: [\x20-\x7e]*)?",
            decoded[0],
        )
        if match is None or match.group(1) not in _HTTP_VERSIONS:
            raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP status line differs")
        headers: dict[str, list[str]] = {}
        for line in decoded[1:]:
            if not line or line[0] in " \t" or ":" not in line:
                raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header field differs")
            name, raw_value = line.split(":", 1)
            if _HEADER_NAME_RE.fullmatch(name) is None:
                raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header name differs")
            value = raw_value.strip(" \t")
            if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
                raise _SourceBlocked("HTTP_HEADER_INVALID", "HTTP header value differs")
            headers.setdefault(name.lower(), []).append(value)
        parsed.append((match.group(1), int(match.group(2)), headers))

    retry_statuses: list[int] = []
    identity_index: Optional[int] = None
    etag_count = 0
    last_modified_count = 0
    identity_names = {
        "etag",
        "last-modified",
        "content-type",
        "content-length",
        "location",
    }
    for index, (_version, status_code, headers) in enumerate(parsed):
        etag_count += len(headers.get("etag", []))
        last_modified_count += len(headers.get("last-modified", []))
        if status_code in _INTERIM_STATUS:
            if identity_names.intersection(headers):
                raise _SourceBlocked("HTTP_HEADER_INVALID", "interim identity header exists")
        elif status_code in _RETRY_STATUS:
            retry_statuses.append(status_code)
            if {"etag", "last-modified", "location"}.intersection(headers):
                raise _SourceBlocked("HTTP_HEADER_INVALID", "retry identity header exists")
        elif status_code == 200:
            if identity_index is not None:
                raise _SourceBlocked("HTTP_HEADER_INVALID", "multiple identity responses exist")
            identity_index = index
        else:
            raise _SourceBlocked("HTTP_STATUS_BLOCKED", "HTTP terminal status is not accepted")
    if identity_index is None or identity_index != len(parsed) - 1:
        raise _SourceBlocked("HTTP_HEADER_INVALID", "final identity response differs")
    if etag_count != 1 or last_modified_count != 1:
        raise _SourceBlocked("HTTP_IDENTITY_MISMATCH", "ETag/Last-Modified count differs")
    version, status_code, headers = parsed[identity_index]
    required = ("etag", "last-modified", "content-type", "content-length")
    if any(len(headers.get(name, [])) != 1 for name in required):
        raise _SourceBlocked("HTTP_IDENTITY_MISMATCH", "identity header count differs")
    if "location" in headers:
        raise _SourceBlocked("HTTP_REDIRECT_BLOCKED", "Location header is forbidden")
    etag = headers["etag"][0]
    expected_etag = f'"{EXPECTED_ETAG_TOKEN}"'
    if etag != expected_etag or etag.startswith("W/"):
        raise _SourceBlocked("HTTP_IDENTITY_MISMATCH", "ETag differs")
    last_modified = headers["last-modified"][0]
    try:
        parsed_date = parsedate_to_datetime(last_modified)
    except (TypeError, ValueError, OverflowError) as error:
        raise _SourceBlocked("HTTP_IDENTITY_MISMATCH", "Last-Modified is invalid") from error
    if (
        parsed_date.tzinfo is None
        or parsed_date.astimezone(timezone.utc).date().isoformat()
        != EXPECTED_LAST_MODIFIED_DATE
    ):
        raise _SourceBlocked("HTTP_IDENTITY_MISMATCH", "Last-Modified date differs")
    mime = headers["content-type"][0]
    if mime != mime.lower() or mime not in ALLOWED_MIME_TYPES:
        raise _SourceBlocked("HTTP_MIME_BLOCKED", "Content-Type differs")
    length = headers["content-length"][0]
    if not length.isascii() or not length.isdigit():
        raise _SourceBlocked("HTTP_SIZE_MISMATCH", "Content-Length is invalid")
    content_length = int(length)
    if content_length < 1 or content_length > ARCHIVE_LIMIT:
        raise _SourceBlocked("HTTP_SIZE_MISMATCH", "Content-Length exceeds limit")
    return _HeaderObservation(
        version,
        status_code,
        tuple(retry_statuses),
        EXPECTED_ETAG_TOKEN,
        last_modified,
        mime,
        content_length,
    )


def _parse_writeout(content: bytes) -> _WriteoutObservation:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise _SourceBlocked("WRITEOUT_INVALID", "curl writeout is not ASCII") from error
    lines = text.splitlines(keepends=True)
    if len(lines) != 7 or any(not line.endswith("\n") for line in lines):
        raise _SourceBlocked("WRITEOUT_INVALID", "curl writeout shape differs")
    stripped = [line[:-1] for line in lines]
    if stripped[0] != _WRITEOUT_BEGIN or stripped[-1] != _WRITEOUT_END:
        raise _SourceBlocked("WRITEOUT_INVALID", "curl writeout boundary differs")
    keys = ("http_code", "num_redirects", "url_effective", "content_type", "size_download")
    values: dict[str, str] = {}
    for expected_key, line in zip(keys, stripped[1:-1]):
        prefix = expected_key + ":"
        if not line.startswith(prefix):
            raise _SourceBlocked("WRITEOUT_INVALID", "curl writeout key differs")
        values[expected_key] = line[len(prefix):]
    if not re.fullmatch(r"[0-9]{3}", values["http_code"]):
        raise _SourceBlocked("WRITEOUT_INVALID", "HTTP code differs")
    for key in ("num_redirects", "size_download"):
        if not values[key].isascii() or not values[key].isdigit():
            raise _SourceBlocked("WRITEOUT_INVALID", f"{key} differs")
    return _WriteoutObservation(
        int(values["http_code"]),
        int(values["num_redirects"]),
        values["url_effective"],
        values["content_type"],
        int(values["size_download"]),
    )


def _validate_effective_url(value: str) -> None:
    if value != SOURCE_URL:
        raise _SourceBlocked("HTTP_URL_MISMATCH", "effective URL differs")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != SOURCE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise _SourceBlocked("HTTP_URL_MISMATCH", "effective URL authority differs")


def _inventory_bytes(inspection: ArchiveInspection) -> bytes:
    result = bytearray()
    for member in sorted(inspection.members, key=lambda item: item.path.encode("utf-8")):
        line = canonical_json(
            {
                "path": member.path,
                "kind": member.kind.value,
                "declared_size": member.declared_size,
                "sha256": member.sha256,
            }
        ).encode("utf-8") + b"\n"
        if len(line) > INVENTORY_LIMIT - len(result):
            raise _SourceBlocked(
                "ARCHIVE_INVENTORY_LIMIT", "member inventory exceeds limit"
            )
        result.extend(line)
    return bytes(result)


def _evaluate_stage(
    process_result: _ProcessResult,
    archive_fd: int,
    header_fd: int,
    writeout_fd: int,
) -> _Evaluation:
    if process_result.reason_code != "NONE":
        return _Evaluation(
            StageStatus.BLOCKED,
            "TRANSFER_" + process_result.reason_code,
            None,
            None,
            None,
        )
    if process_result.returncode != 0:
        return _Evaluation(StageStatus.BLOCKED, "CURL_EXIT_NONZERO", None, None, None)
    try:
        header_content = _file_facts(header_fd, HEADER_LIMIT, True).content
        writeout_content = _file_facts(writeout_fd, WRITEOUT_LIMIT, True).content
        if header_content is None or writeout_content is None:
            raise StrategyQaAcquisitionError("small evidence content is unavailable")
        header = _parse_header_blocks(header_content)
        writeout = _parse_writeout(writeout_content)
        _validate_effective_url(writeout.effective_url)
        if (
            writeout.http_code != 200
            or writeout.num_redirects != 0
            or writeout.content_type != header.content_type
        ):
            raise _SourceBlocked("HTTP_OBSERVATION_MISMATCH", "header/writeout differ")
        archive_facts = _file_facts(archive_fd, ARCHIVE_LIMIT)
        if (
            archive_facts.size != writeout.size_download
            or archive_facts.size != header.content_length
        ):
            raise _SourceBlocked("HTTP_SIZE_MISMATCH", "archive size differs")
        magic = os.pread(archive_fd, 4, 0)
        if magic not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
            raise _SourceBlocked("ARCHIVE_FORMAT_BLOCKED", "archive is not ZIP")
        inspection = inspect_archive_fd(
            archive_fd,
            expected_sha256=archive_facts.sha256,
            max_total_bytes=EXTRACTED_LIMIT,
            max_members=MEMBER_LIMIT,
            max_metadata_bytes=METADATA_LIMIT,
        )
        if inspection.format is not ArchiveFormat.ZIP:
            raise _SourceBlocked("ARCHIVE_FORMAT_BLOCKED", "archive format differs")
        inventory = _inventory_bytes(inspection)
        http_values = {
            "http_version": header.http_version,
            "http_code": header.status_code,
            "retry_failure_statuses": list(header.retry_failure_statuses),
            "num_redirects": writeout.num_redirects,
            "effective_url": writeout.effective_url,
            "etag_token": header.etag_token,
            "last_modified": header.last_modified,
            "content_type": header.content_type,
            "content_length": header.content_length,
            "size_download": writeout.size_download,
        }
        archive_values = {
            "path": _ARCHIVE_NAME,
            "size_bytes": archive_facts.size,
            "sha256": archive_facts.sha256,
            "format": inspection.format.value,
            "member_count": inspection.member_count,
            "declared_expanded_bytes": inspection.total_declared_bytes,
            "inventory_path": _INVENTORY_NAME,
            "inventory_size_bytes": len(inventory),
            "inventory_sha256": hashlib.sha256(inventory).hexdigest(),
        }
        return _Evaluation(
            StageStatus.STAGE_OK,
            "SOURCE_ENVELOPE_VERIFIED",
            http_values,
            archive_values,
            inventory,
        )
    except _SourceBlocked as error:
        return _Evaluation(StageStatus.BLOCKED, error.reason_code, None, None, None)
    except ArchiveSafetyError:
        return _Evaluation(StageStatus.BLOCKED, "ARCHIVE_REJECTED", None, None, None)


def _facts_mapping(facts: Mapping[str, _FileFacts]) -> Mapping[str, Any]:
    return {
        name: {"size_bytes": value.size, "sha256": value.sha256}
        for name, value in sorted(facts.items())
    }


def _policy_hash(membership: Mapping[str, Any], acl: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json({"membership": membership, "acl": acl}).encode("utf-8")
    ).hexdigest()


def _fingerprint_mapping(value: _Fingerprint) -> Mapping[str, int]:
    return {
        "device": value.device,
        "inode": value.inode,
        "uid": value.uid,
        "gid": value.gid,
        "mode": value.mode,
        "nlink": value.nlink,
        "size": value.size,
        "mtime_ns": value.mtime_ns,
        "ctime_ns": value.ctime_ns,
    }


def _identity_mapping(value: _Fingerprint) -> Mapping[str, int]:
    return {
        "device": value.device,
        "inode": value.inode,
        "uid": value.uid,
        "gid": value.gid,
        "mode": value.mode,
    }


def _anchor_values(anchors: Sequence[ChainAnchor]) -> list[Mapping[str, Any]]:
    return [
        {
            "path": anchor.path,
            "device": anchor.device,
            "inode": anchor.inode,
            "uid": anchor.uid,
            "gid": anchor.gid,
            "mode": anchor.mode,
        }
        for anchor in anchors
    ]


def _build_manifest(
    evaluation: _Evaluation,
    facts: Mapping[str, _FileFacts],
    approved_commit: str,
    anchors: Sequence[ChainAnchor],
    parent_fingerprint: _Fingerprint,
    stage_fingerprint: _Fingerprint,
    resource_gate: Mapping[str, Any],
) -> Mapping[str, Any]:
    frozen_policy = {
        "membership": dict(FROZEN_MEMBERSHIP),
        "acl": dict(FROZEN_ACL),
    }
    return {
        "schema_version": "kairos-strategyqa-stage-v1",
        "status": evaluation.status.value,
        "reason_code": evaluation.reason_code,
        "dataset": DATASET,
        "revision": REVISION,
        "fixed_url": SOURCE_URL,
        "expected_etag_token": EXPECTED_ETAG_TOKEN,
        "expected_last_modified_date": EXPECTED_LAST_MODIFIED_DATE,
        "runtime_redirect_semantics": "UNVERIFIED",
        "schema_status": "UNVERIFIED",
        "license_status": "UNVERIFIED",
        "kairos_git_commit": approved_commit,
        "git_checkpoints": ["pre_stage", "pre_child", "pre_manifest"],
        "policy": frozen_policy,
        "policy_evidence_sha256": _policy_hash(FROZEN_MEMBERSHIP, FROZEN_ACL),
        "absolute_chain_anchors": _anchor_values(anchors),
        "path_bindings": {
            "parent": _fingerprint_mapping(parent_fingerprint),
            "stage_identity": _identity_mapping(stage_fingerprint),
        },
        "artifacts": _facts_mapping(facts),
        "http": evaluation.http,
        "archive": evaluation.archive,
        "limits": {
            "archive_max_bytes": ARCHIVE_LIMIT,
            "declared_expanded_max_bytes": EXTRACTED_LIMIT,
            "member_max_count": MEMBER_LIMIT,
            "metadata_max_bytes": METADATA_LIMIT,
            "inventory_max_bytes": INVENTORY_LIMIT,
            "header_max_bytes": HEADER_LIMIT,
            "writeout_max_bytes": WRITEOUT_LIMIT,
            "stderr_max_bytes": STDERR_LIMIT,
            "address_space_max_bytes": RESOURCE_AS_LIMIT,
            "cpu_time_max_seconds": RESOURCE_CPU_LIMIT,
            "file_size_max_bytes": RESOURCE_FSIZE_LIMIT,
            "open_file_max_count": RESOURCE_NOFILE_LIMIT,
            "core_max_bytes": RESOURCE_CORE_LIMIT,
            "cpu_thread_max_count": 2,
            "gpu_count": 0,
        },
        "runtime_resources": _validate_resource_observation(resource_gate),
    }


def _manifest_bytes(value: Mapping[str, Any]) -> bytes:
    content = canonical_json(value).encode("utf-8") + b"\n"
    if len(content) > MANIFEST_LIMIT:
        raise StrategyQaAcquisitionError("stage manifest exceeds its limit")
    return content


def _same_inode(left: _Fingerprint, right: _Fingerprint) -> bool:
    return (left.device, left.inode) == (right.device, right.inode)


def _canonical_maps_to_fd(stage_fd: int, name: str, held_fd: int) -> bool:
    current = _entry_fingerprint(stage_fd, name)
    return current is not None and _same_inode(current, _fingerprint_fd(held_fd))


def _transaction_marker_bytes(approved_commit: str) -> bytes:
    return canonical_json(
        {
            "kairos_git_commit": _validate_commit(approved_commit),
            "transaction_version": _TRANSACTION_VERSION,
        }
    ).encode("utf-8") + b"\n"


def _transaction_marker_present(project_fd: int) -> bool:
    return _entry_fingerprint(project_fd, _TRANSACTION_MARKER) is not None


def _assert_transaction_marker(
    project_fd: int,
    marker_fd: int,
    expected_content: bytes,
    expected_facts: Optional[_FileFacts] = None,
) -> None:
    if not _canonical_maps_to_fd(project_fd, _TRANSACTION_MARKER, marker_fd):
        raise StrategyQaAcquisitionError("transaction marker binding differs")
    facts = _file_facts(marker_fd, MANIFEST_LIMIT, True)
    if facts.content != expected_content or (
        expected_facts is not None and facts != expected_facts
    ):
        raise StrategyQaAcquisitionError("transaction marker content differs")


def _create_transaction_marker(
    project_fd: int, approved_commit: str
) -> tuple[int, bytes, _FileFacts]:
    if _transaction_marker_present(project_fd):
        raise FileExistsError("StrategyQA transaction marker already exists")
    content = _transaction_marker_bytes(approved_commit)
    marker_fd = -1
    try:
        marker_fd = _create_private_file(project_fd, _TRANSACTION_MARKER)
        _write_all(marker_fd, content)
        os.fsync(marker_fd)
        os.fsync(project_fd)
        _assert_transaction_marker(project_fd, marker_fd, content)
        facts = _file_facts(marker_fd, MANIFEST_LIMIT, True)
        return marker_fd, content, facts
    except BaseException:
        active = sys.exc_info()[1]
        owned = marker_fd
        marker_fd = -1
        _close_fds_best_effort((("transaction-marker", owned),), active)
        raise


def _restore_transaction_marker(
    project_fd: int,
    held_marker_fd: int,
    expected_content: bytes,
    expected_facts: _FileFacts,
) -> bool:
    canonical_fd = restored_fd = -1
    try:
        current = _entry_fingerprint(project_fd, _TRANSACTION_MARKER)
        if current is not None:
            held_fingerprint = _fingerprint_fd(held_marker_fd)
            if (
                not _same_inode(current, held_fingerprint)
                or not _same_inode(current, expected_facts.fingerprint)
            ):
                return False
            canonical_fd = _open_private_file(project_fd, _TRANSACTION_MARKER)
            canonical_fingerprint = _fingerprint_fd(canonical_fd)
            rebound = _entry_fingerprint(project_fd, _TRANSACTION_MARKER)
            if (
                rebound is None
                or not _same_inode(rebound, canonical_fingerprint)
                or not _same_inode(canonical_fingerprint, held_fingerprint)
                or not _same_inode(
                    canonical_fingerprint, expected_facts.fingerprint
                )
            ):
                return False
            canonical_facts = _file_facts(canonical_fd, MANIFEST_LIMIT, True)
            held_facts = _file_facts(held_marker_fd, MANIFEST_LIMIT, True)
            if (
                not _same_inode(canonical_facts.fingerprint, held_facts.fingerprint)
                or canonical_facts != expected_facts
                or held_facts != expected_facts
                or canonical_facts.content != expected_content
            ):
                return False
            owned_canonical_fd = canonical_fd
            canonical_fd = -1
            os.close(owned_canonical_fd)
            os.fsync(held_marker_fd)
            os.fsync(project_fd)
            rebound = _entry_fingerprint(project_fd, _TRANSACTION_MARKER)
            if (
                rebound is None
                or not _same_inode(rebound, held_fingerprint)
                or not _same_inode(rebound, expected_facts.fingerprint)
            ):
                return False
            canonical_fd = _open_private_file(project_fd, _TRANSACTION_MARKER)
            canonical_fingerprint = _fingerprint_fd(canonical_fd)
            current = _entry_fingerprint(project_fd, _TRANSACTION_MARKER)
            try:
                if (
                    current is None
                    or not _same_inode(current, canonical_fingerprint)
                    or not _same_inode(canonical_fingerprint, held_fingerprint)
                    or not _same_inode(
                        canonical_fingerprint, expected_facts.fingerprint
                    )
                ):
                    return False
                rebound_facts = _file_facts(canonical_fd, MANIFEST_LIMIT, True)
                if (
                    rebound_facts != expected_facts
                    or rebound_facts.content != expected_content
                ):
                    return False
            finally:
                owned_canonical_fd = canonical_fd
                canonical_fd = -1
                os.close(owned_canonical_fd)
            return True

        restored_fd = _create_private_file(project_fd, _TRANSACTION_MARKER)
        _write_all(restored_fd, expected_content)
        os.fsync(restored_fd)
        os.fsync(project_fd)
        restored_facts = _file_facts(restored_fd, MANIFEST_LIMIT, True)
        restored_fingerprint = _fingerprint_fd(restored_fd)
        current = _entry_fingerprint(project_fd, _TRANSACTION_MARKER)
        if current is None or not _same_inode(current, restored_fingerprint):
            return False
        canonical_fd = _open_private_file(project_fd, _TRANSACTION_MARKER)
        canonical_fingerprint = _fingerprint_fd(canonical_fd)
        rebound = _entry_fingerprint(project_fd, _TRANSACTION_MARKER)
        if (
            rebound is None
            or not _same_inode(rebound, canonical_fingerprint)
            or not _same_inode(canonical_fingerprint, restored_fingerprint)
        ):
            return False
        canonical_facts = _file_facts(canonical_fd, MANIFEST_LIMIT, True)
        if (
            canonical_facts != restored_facts
            or canonical_facts.content != expected_content
            or not _same_inode(
                canonical_facts.fingerprint, restored_facts.fingerprint
            )
        ):
            return False
        owned_canonical_fd = canonical_fd
        canonical_fd = -1
        os.close(owned_canonical_fd)
        owned_restored_fd = restored_fd
        restored_fd = -1
        os.close(owned_restored_fd)
        return True
    except BaseException:
        return False
    finally:
        active = sys.exc_info()[1]
        owned = (
            ("restored-transaction-marker", restored_fd),
            ("canonical-transaction-marker", canonical_fd),
        )
        try:
            _close_fds_best_effort(owned, active)
        except BaseException:
            pass


def _commit_transaction_marker(
    layout: _Layout,
    anchors: Sequence[ChainAnchor],
    project_fd: int,
    marker_fd: int,
    expected_content: bytes,
    expected_facts: _FileFacts,
) -> None:
    canonical_chain = _open_absolute_chain(layout.project_root, anchors)
    try:
        if _identity(_fingerprint_fd(canonical_chain[-1])) != _identity(
            _fingerprint_fd(project_fd)
        ):
            raise StrategyQaAcquisitionError(
                "transaction recovery root binding differs"
            )
        _assert_transaction_marker(
            canonical_chain[-1], marker_fd, expected_content, expected_facts
        )
    finally:
        owned = [
            ("transaction-chain", fd) for fd in reversed(canonical_chain)
        ]
        canonical_chain.clear()
        _close_fds_best_effort(owned, sys.exc_info()[1])
    _assert_transaction_marker(
        project_fd, marker_fd, expected_content, expected_facts
    )
    os.unlink(_TRANSACTION_MARKER, dir_fd=project_fd)
    os.fsync(project_fd)
    if _transaction_marker_present(project_fd):
        raise StrategyQaAcquisitionError("transaction marker removal differs")


def _close_after_commit_warning(fd: int, label: str) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError as error:
        try:
            warnings.warn(
                f"{label} close failed after durable transaction commit: {error}",
                RuntimeWarning,
                stacklevel=2,
            )
        except RuntimeWarning:
            pass


def _assert_manifest_pair(stage_fd: int, expected_content: bytes) -> None:
    guard_fd = final_fd = -1
    try:
        guard_fd = os.open(_MANIFEST_GUARD, _regular_read_flags(), dir_fd=stage_fd)
        final_fd = os.open(_MANIFEST_FINAL, _regular_read_flags(), dir_fd=stage_fd)
        guard = _fingerprint_fd(guard_fd)
        final = _fingerprint_fd(final_fd)
        if (
            guard != final
            or guard.uid != os.geteuid()
            or guard.mode != stat.S_IFREG | 0o600
            or guard.nlink != 2
            or _pread_bounded(guard_fd, MANIFEST_LIMIT) != expected_content
            or _pread_bounded(final_fd, MANIFEST_LIMIT) != expected_content
        ):
            raise StrategyQaAcquisitionError("stage manifest pair differs")
    finally:
        active = sys.exc_info()[1]
        owned = (("manifest-final", final_fd), ("manifest-guard", guard_fd))
        final_fd = guard_fd = -1
        _close_fds_best_effort(owned, active)


def _assert_held_manifest_pair(
    stage_fd: int,
    guard_fd: int,
    final_fd: int,
    expected_fingerprint: _Fingerprint,
    expected_content: bytes,
) -> None:
    guard = _fingerprint_fd(guard_fd)
    final = _fingerprint_fd(final_fd)
    canonical_guard = _entry_fingerprint(stage_fd, _MANIFEST_GUARD)
    canonical_final = _entry_fingerprint(stage_fd, _MANIFEST_FINAL)
    if (
        guard != expected_fingerprint
        or final != expected_fingerprint
        or canonical_guard != expected_fingerprint
        or canonical_final != expected_fingerprint
        or expected_fingerprint.uid != os.geteuid()
        or expected_fingerprint.mode != stat.S_IFREG | 0o600
        or expected_fingerprint.nlink != 2
        or _pread_bounded(guard_fd, MANIFEST_LIMIT) != expected_content
        or _pread_bounded(final_fd, MANIFEST_LIMIT) != expected_content
    ):
        raise StrategyQaAcquisitionError("held manifest pair differs")


def _artifact_limit(name: str) -> int:
    limits = {
        _ARCHIVE_NAME: ARCHIVE_LIMIT,
        _HEADER_NAME: HEADER_LIMIT,
        _WRITEOUT_NAME: WRITEOUT_LIMIT,
        _STDERR_NAME: STDERR_LIMIT,
        _PROCESS_RESULT_NAME: PROCESS_RESULT_LIMIT,
        _INVENTORY_NAME: INVENTORY_LIMIT,
    }
    try:
        return limits[name]
    except KeyError as error:
        raise StrategyQaAcquisitionError("unknown stage artifact") from error


def _canonical_file_facts(
    stage_fd: int,
    name: str,
    held_fd: int,
    expected: Optional[_FileFacts] = None,
) -> _FileFacts:
    held = _file_facts(held_fd, _artifact_limit(name))
    canonical_fd = _open_private_file(stage_fd, name)
    try:
        canonical = _file_facts(canonical_fd, _artifact_limit(name))
    finally:
        os.close(canonical_fd)
    if held != canonical or (expected is not None and held != expected):
        raise StrategyQaAcquisitionError(f"canonical artifact binding differs: {name}")
    return held


def _assert_stage_artifacts(
    stage_fd: int,
    held_fds: Mapping[str, int],
    expected_facts: Optional[Mapping[str, _FileFacts]] = None,
) -> Mapping[str, _FileFacts]:
    facts: dict[str, _FileFacts] = {}
    for name in sorted(held_fds):
        facts[name] = _canonical_file_facts(
            stage_fd,
            name,
            held_fds[name],
            None if expected_facts is None else expected_facts[name],
        )
    return facts


def _full_fingerprints(fds: Sequence[int]) -> tuple[_Fingerprint, ...]:
    return tuple(_fingerprint_fd(fd) for fd in fds)


def _assert_full_fingerprints(
    fds: Sequence[int], expected: Sequence[_Fingerprint], label: str
) -> None:
    if _full_fingerprints(fds) != tuple(expected):
        raise StrategyQaAcquisitionError(f"{label} full fingerprint changed")


def _publish_manifest(
    parent_fd: int,
    stage_leaf: str,
    stage_fd: int,
    expected_stage_identity: tuple[int, ...],
    value: Mapping[str, Any],
) -> _PublishedManifest:
    content = _manifest_bytes(value)
    temp_name = f".stage-manifest.{secrets.token_hex(16)}.tmp"
    temp_fd = guard_fd = final_fd = -1
    try:
        _assert_stage_binding(
            parent_fd, stage_leaf, stage_fd, expected_stage_identity
        )
        initial_names = _scan_stage_names(stage_fd)
        for name in (_MANIFEST_GUARD, _MANIFEST_FINAL, _INCOMPLETE_MARKER):
            if name in initial_names:
                raise FileExistsError(f"stage publication entry exists: {name}")
        temp_fd = _create_private_file(stage_fd, temp_name)
        _write_all(temp_fd, content)
        os.fsync(temp_fd)
        if _pread_bounded(temp_fd, MANIFEST_LIMIT) != content:
            raise StrategyQaAcquisitionError("manifest temp differs")
        os.link(
            temp_name,
            _MANIFEST_GUARD,
            src_dir_fd=stage_fd,
            dst_dir_fd=stage_fd,
            follow_symlinks=False,
        )
        os.unlink(temp_name, dir_fd=stage_fd)
        os.fsync(stage_fd)
        guard_fd = os.open(_MANIFEST_GUARD, _regular_read_flags(), dir_fd=stage_fd)
        guard_only = _fingerprint_fd(guard_fd)
        if (
            guard_only != _fingerprint_fd(temp_fd)
            or guard_only.uid != os.geteuid()
            or guard_only.mode != stat.S_IFREG | 0o600
            or guard_only.nlink != 1
            or _entry_fingerprint(stage_fd, _MANIFEST_GUARD) != guard_only
            or _entry_fingerprint(stage_fd, temp_name) is not None
            or _pread_bounded(guard_fd, MANIFEST_LIMIT) != content
            or _scan_stage_names(stage_fd)
            != {**initial_names, _MANIFEST_GUARD: guard_only}
        ):
            raise StrategyQaAcquisitionError("durable guard-only state differs")
        os.link(
            _MANIFEST_GUARD,
            _MANIFEST_FINAL,
            src_dir_fd=stage_fd,
            dst_dir_fd=stage_fd,
            follow_symlinks=False,
        )
        os.fsync(stage_fd)
        final_fd = os.open(_MANIFEST_FINAL, _regular_read_flags(), dir_fd=stage_fd)
        pair_fingerprint = _fingerprint_fd(guard_fd)
        expected_names = {
            **initial_names,
            _MANIFEST_GUARD: pair_fingerprint,
            _MANIFEST_FINAL: pair_fingerprint,
        }
        if (
            _fingerprint_fd(temp_fd) != pair_fingerprint
            or _pread_bounded(temp_fd, MANIFEST_LIMIT) != content
            or _entry_fingerprint(stage_fd, temp_name) is not None
            or _scan_stage_names(stage_fd) != expected_names
        ):
            raise StrategyQaAcquisitionError("published manifest layout differs")
        _assert_held_manifest_pair(
            stage_fd, guard_fd, final_fd, pair_fingerprint, content
        )
        _assert_stage_binding(
            parent_fd, stage_leaf, stage_fd, expected_stage_identity
        )
        owned_temp_fd = temp_fd
        temp_fd = -1
        os.close(owned_temp_fd)
        stage_fingerprint = _fingerprint_fd(stage_fd)
        published = _PublishedManifest(
            guard_fd,
            final_fd,
            pair_fingerprint,
            stage_fingerprint,
            content,
        )
        guard_fd = final_fd = -1
        return published
    finally:
        active = sys.exc_info()[1]
        owned = (
            ("manifest-final", final_fd),
            ("manifest-guard", guard_fd),
            ("manifest-temp", temp_fd),
        )
        temp_fd = guard_fd = final_fd = -1
        _close_fds_best_effort(owned, active)


def _scan_stage_names(stage_fd: int) -> Mapping[str, _Fingerprint]:
    result: dict[str, _Fingerprint] = {}
    iterator = os.scandir(stage_fd)
    try:
        for entry in iterator:
            if entry.name in result:
                raise StrategyQaAcquisitionError("duplicate stage entry")
            result[entry.name] = _fingerprint_stat(entry.stat(follow_symlinks=False))
    finally:
        iterator.close()
    return result


def _validate_manifest_shape(value: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "status",
        "reason_code",
        "dataset",
        "revision",
        "fixed_url",
        "expected_etag_token",
        "expected_last_modified_date",
        "runtime_redirect_semantics",
        "schema_status",
        "license_status",
        "kairos_git_commit",
        "git_checkpoints",
        "policy",
        "policy_evidence_sha256",
        "absolute_chain_anchors",
        "path_bindings",
        "artifacts",
        "http",
        "archive",
        "limits",
        "runtime_resources",
    }
    _exact_keys(value, expected, "stage manifest")
    if value["schema_version"] != "kairos-strategyqa-stage-v1":
        raise StrategyQaAcquisitionError("manifest schema differs")
    if value["status"] not in {StageStatus.BLOCKED.value, StageStatus.STAGE_OK.value}:
        raise StrategyQaAcquisitionError("manifest status differs")
    fixed = {
        "dataset": DATASET,
        "revision": REVISION,
        "fixed_url": SOURCE_URL,
        "expected_etag_token": EXPECTED_ETAG_TOKEN,
        "expected_last_modified_date": EXPECTED_LAST_MODIFIED_DATE,
        "runtime_redirect_semantics": "UNVERIFIED",
        "schema_status": "UNVERIFIED",
        "license_status": "UNVERIFIED",
    }
    for key, expected_value in fixed.items():
        if value[key] != expected_value:
            raise StrategyQaAcquisitionError(f"manifest fixed field differs: {key}")
    _validate_commit(value["kairos_git_commit"])
    if value["git_checkpoints"] != ["pre_stage", "pre_child", "pre_manifest"]:
        raise StrategyQaAcquisitionError("manifest Git checkpoints differ")
    if not isinstance(value["policy_evidence_sha256"], str) or _HEX64.fullmatch(
        value["policy_evidence_sha256"]
    ) is None:
        raise StrategyQaAcquisitionError("policy evidence SHA differs")
    expected_policy = {
        "membership": dict(FROZEN_MEMBERSHIP),
        "acl": dict(FROZEN_ACL),
    }
    if (
        value["policy"] != expected_policy
        or value["policy_evidence_sha256"]
        != _policy_hash(FROZEN_MEMBERSHIP, FROZEN_ACL)
    ):
        raise StrategyQaAcquisitionError("manifest frozen policy differs")
    _validate_resource_observation(value["runtime_resources"])


def _verify_stage_layout_strict(
    layout: _Layout,
    anchors: Sequence[ChainAnchor],
    owned_transaction: Optional[tuple[int, bytes]] = None,
) -> StageReport:
    absolute_chain: list[int] = []
    parent_chain: list[int] = []
    stage_fd = guard_fd = final_fd = -1
    evidence_fds: dict[str, int] = {}
    try:
        absolute_chain = _open_absolute_chain(layout.project_root, anchors)
        project_fd = absolute_chain[-1]
        if _transaction_marker_present(project_fd):
            if owned_transaction is None:
                return StageReport(
                    StageStatus.INCOMPLETE, "TRANSACTION_IN_PROGRESS", None
                )
            _assert_transaction_marker(
                project_fd, owned_transaction[0], owned_transaction[1]
            )
        elif owned_transaction is not None:
            raise StrategyQaAcquisitionError("owned transaction marker is absent")
        parent_chain = _open_parent_chain(project_fd, layout.parent_relative)
        parent_fd = parent_chain[-1]
        _require_absent(parent_fd, layout.formal_leaf, "formal StrategyQA revision")
        if _entry_fingerprint(parent_fd, layout.stage_leaf) is None:
            return StageReport(StageStatus.INCOMPLETE, "STAGE_ABSENT", None)
        stage_fd = os.open(layout.stage_leaf, _dir_flags(), dir_fd=parent_fd)
        _require_private_directory(stage_fd, "StrategyQA stage")
        direct_parent_start = (_fingerprint_fd(parent_fd),)
        stage_start = _fingerprint_fd(stage_fd)
        names = _scan_stage_names(stage_fd)
        if _INCOMPLETE_MARKER in names:
            return StageReport(StageStatus.INCOMPLETE, "FAIL_CLOSE_MARKER", None)
        guard_present = _MANIFEST_GUARD in names
        final_present = _MANIFEST_FINAL in names
        if not guard_present or not final_present:
            return StageReport(StageStatus.INCOMPLETE, "MANIFEST_PAIR_ABSENT", None)
        guard_fd = os.open(_MANIFEST_GUARD, _regular_read_flags(), dir_fd=stage_fd)
        final_fd = os.open(_MANIFEST_FINAL, _regular_read_flags(), dir_fd=stage_fd)
        pair_guard = _fingerprint_fd(guard_fd)
        pair_final = _fingerprint_fd(final_fd)
        content = _pread_bounded(final_fd, MANIFEST_LIMIT)
        if (
            pair_guard != pair_final
            or pair_guard.mode != stat.S_IFREG | 0o600
            or pair_guard.uid != os.geteuid()
            or pair_guard.nlink != 2
            or _pread_bounded(guard_fd, MANIFEST_LIMIT) != content
        ):
            raise StrategyQaAcquisitionError("manifest pair binding differs")
        manifest = _strict_json_object(content, "stage manifest")
        if _manifest_bytes(manifest) != content:
            raise StrategyQaAcquisitionError("stage manifest is not canonical")
        _validate_manifest_shape(manifest)
        stage_status = StageStatus(manifest["status"])
        evidence_names = set(_COMMON_EVIDENCE)
        if stage_status is StageStatus.STAGE_OK:
            evidence_names.add(_INVENTORY_NAME)
        expected_names = evidence_names | {_MANIFEST_GUARD, _MANIFEST_FINAL}
        if set(names) != expected_names:
            raise StrategyQaAcquisitionError("stage file set differs")
        for name, fingerprint in names.items():
            if name in {_MANIFEST_GUARD, _MANIFEST_FINAL}:
                continue
            if (
                fingerprint.mode != stat.S_IFREG | 0o600
                or fingerprint.uid != os.geteuid()
                or fingerprint.nlink != 1
            ):
                raise StrategyQaAcquisitionError(f"stage evidence differs: {name}")
        for name in sorted(evidence_names):
            evidence_fds[name] = _open_private_file(stage_fd, name)
        facts = dict(_assert_stage_artifacts(stage_fd, evidence_fds))
        process_bytes = _pread_bounded(
            evidence_fds[_PROCESS_RESULT_NAME], PROCESS_RESULT_LIMIT
        )
        process = _parse_process_result(process_bytes)
        if _process_result_bytes(process) != process_bytes:
            raise StrategyQaAcquisitionError("process result is not canonical")
        evaluation = _evaluate_stage(
            process,
            evidence_fds[_ARCHIVE_NAME],
            evidence_fds[_HEADER_NAME],
            evidence_fds[_WRITEOUT_NAME],
        )
        if evaluation.status is not stage_status:
            raise StrategyQaAcquisitionError("replayed stage status differs")
        if evaluation.inventory is not None:
            if (
                _pread_bounded(evidence_fds[_INVENTORY_NAME], INVENTORY_LIMIT)
                != evaluation.inventory
            ):
                raise StrategyQaAcquisitionError("member inventory differs")
        expected = _build_manifest(
            evaluation,
            facts,
            manifest["kairos_git_commit"],
            anchors,
            direct_parent_start[0],
            stage_start,
            manifest["runtime_resources"],
        )
        if _manifest_bytes(expected) != content:
            raise StrategyQaAcquisitionError("stage manifest differs from replay")
        if _scan_stage_names(stage_fd) != names:
            raise StrategyQaAcquisitionError("terminal stage scan differs")
        _assert_stage_artifacts(stage_fd, evidence_fds, facts)
        _assert_manifest_pair(stage_fd, content)
        if (
            _fingerprint_fd(guard_fd) != pair_guard
            or _fingerprint_fd(final_fd) != pair_final
            or _pread_bounded(guard_fd, MANIFEST_LIMIT) != content
            or _pread_bounded(final_fd, MANIFEST_LIMIT) != content
        ):
            raise StrategyQaAcquisitionError("held manifest pair changed")
        _assert_full_fingerprints(
            (parent_fd,), direct_parent_start, "direct source parent"
        )
        _assert_full_fingerprints((stage_fd,), (stage_start,), "stage")
        _assert_absolute_chain(layout.project_root, absolute_chain, anchors)
        parent_expected = tuple(
            _identity(_fingerprint_fd(fd)) for fd in parent_chain
        )
        _assert_parent_chain(
            project_fd, layout.parent_relative, parent_chain, parent_expected
        )
        _require_absent(parent_fd, layout.formal_leaf, "formal StrategyQA revision")
        _assert_stage_binding(
            parent_fd,
            layout.stage_leaf,
            stage_fd,
            _identity(_fingerprint_fd(stage_fd)),
        )
        canonical_parent = _open_parent_chain(project_fd, layout.parent_relative)
        try:
            _assert_full_fingerprints(
                (canonical_parent[-1],),
                direct_parent_start,
                "canonical direct source parent",
            )
        finally:
            _close_fds_best_effort(
                (("canonical-parent", fd) for fd in reversed(canonical_parent)),
                sys.exc_info()[1],
            )
        if _transaction_marker_present(project_fd):
            if owned_transaction is None:
                return StageReport(
                    StageStatus.INCOMPLETE, "TRANSACTION_IN_PROGRESS", None
                )
            _assert_transaction_marker(
                project_fd, owned_transaction[0], owned_transaction[1]
            )
        elif owned_transaction is not None:
            raise StrategyQaAcquisitionError("owned transaction marker disappeared")
        return StageReport(stage_status, evaluation.reason_code, manifest)
    finally:
        active = sys.exc_info()[1]
        owned: list[tuple[str, int]] = [
            (name, evidence_fds[name]) for name in reversed(tuple(evidence_fds))
        ]
        owned.extend([
            ("manifest-final", final_fd),
            ("manifest-guard", guard_fd),
            ("stage", stage_fd),
        ])
        evidence_fds.clear()
        owned.extend(("parent", fd) for fd in reversed(parent_chain))
        owned.extend(("absolute", fd) for fd in reversed(absolute_chain))
        parent_chain.clear()
        absolute_chain.clear()
        _close_fds_best_effort(owned, active)


def _verify_stage_layout(
    layout: _Layout, anchors: Sequence[ChainAnchor]
) -> StageReport:
    try:
        return _verify_stage_layout_strict(layout, anchors)
    except (
        StrategyQaAcquisitionError,
        ArchiveSafetyError,
        FileExistsError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ):
        return StageReport(StageStatus.INCOMPLETE, "OFFLINE_INTEGRITY_FAILURE", None)


def _policy_gate(
    layout: _Layout,
    absolute_chain: Sequence[int],
    anchors: Sequence[ChainAnchor],
    membership_checker: MembershipChecker,
    acl_checker: AclChecker,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    _assert_absolute_chain(layout.project_root, absolute_chain, anchors)
    membership = membership_checker()
    acl = acl_checker(absolute_chain)
    if membership != FROZEN_MEMBERSHIP or acl != FROZEN_ACL:
        raise StrategyQaAcquisitionError("runtime policy differs from frozen policy")
    return membership, acl


def _fetch_layout(
    layout: _Layout,
    anchors: Sequence[ChainAnchor],
    approved_commit: str,
    git_checker: GitChecker,
    membership_checker: MembershipChecker,
    acl_checker: AclChecker,
    transfer_runner: TransferRunner,
    resource_gate: Mapping[str, Any],
    redirect_semantics_verified: bool,
) -> StageReport:
    approved = _validate_commit(approved_commit)
    if redirect_semantics_verified is not True:
        raise StrategyQaAcquisitionError("runtime redirect semantics are unverified")
    runtime_resources = _validate_resource_observation(resource_gate)
    absolute_chain: list[int] = []
    parent_chain: list[int] = []
    stage_fd = -1
    manifest_guard_fd = manifest_final_fd = -1
    evidence_fds: dict[str, int] = {}
    marker_fd = recovery_root_fd = -1
    marker_content: Optional[bytes] = None
    marker_facts: Optional[_FileFacts] = None
    committed = False
    try:
        absolute_chain = _open_absolute_chain(layout.project_root, anchors)
        pre_membership, pre_acl = _policy_gate(
            layout, absolute_chain, anchors, membership_checker, acl_checker
        )
        if _transaction_marker_present(absolute_chain[-1]):
            raise FileExistsError("StrategyQA transaction is already in progress")
        if git_checker(approved) != approved:
            raise StrategyQaAcquisitionError("pre_stage Git checker differs")
        project_fd = absolute_chain[-1]
        preflight_parent: list[int] = []
        try:
            preflight_parent = _open_parent_chain(
                project_fd, layout.parent_relative
            )
            _require_absent(
                preflight_parent[-1], layout.stage_leaf, "StrategyQA stage"
            )
            _require_absent(
                preflight_parent[-1],
                layout.formal_leaf,
                "formal StrategyQA revision",
            )
        except FileNotFoundError:
            pass
        finally:
            active = sys.exc_info()[1]
            owned = [("preflight-parent", fd) for fd in reversed(preflight_parent)]
            preflight_parent.clear()
            _close_fds_best_effort(owned, active)
        recovery_root_fd = os.dup(project_fd)
        marker_fd, marker_content, marker_facts = _create_transaction_marker(
            project_fd, approved
        )
        parent_chain = _open_or_create_parent_chain(
            project_fd, layout.parent_relative
        )
        parent_fd = parent_chain[-1]
        _require_absent(parent_fd, layout.stage_leaf, "StrategyQA stage")
        _require_absent(parent_fd, layout.formal_leaf, "formal StrategyQA revision")
        os.mkdir(layout.stage_leaf, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
        stage_fd = os.open(layout.stage_leaf, _dir_flags(), dir_fd=parent_fd)
        os.fchmod(stage_fd, 0o700)
        _require_private_directory(stage_fd, "StrategyQA stage")
        stage_identity = _identity(_fingerprint_fd(stage_fd))
        parent_expected = tuple(_identity(_fingerprint_fd(fd)) for fd in parent_chain)
        direct_parent_full = (_fingerprint_fd(parent_fd),)
        for name in _COMMON_EVIDENCE:
            evidence_fds[name] = _create_private_file(stage_fd, name)
        stage_full = _fingerprint_fd(stage_fd)
        child_membership, child_acl = _policy_gate(
            layout, absolute_chain, anchors, membership_checker, acl_checker
        )
        if (
            child_membership != pre_membership
            or child_acl != pre_acl
        ):
            raise StrategyQaAcquisitionError("pre-child policy gate differs")
        if git_checker(approved) != approved:
            raise StrategyQaAcquisitionError("pre_child Git checker differs")
        _assert_parent_chain(
            project_fd, layout.parent_relative, parent_chain, parent_expected
        )
        _assert_stage_binding(
            parent_fd, layout.stage_leaf, stage_fd, stage_identity
        )
        _require_absent(parent_fd, layout.formal_leaf, "formal StrategyQA revision")
        process = transfer_runner(
            evidence_fds[_ARCHIVE_NAME],
            evidence_fds[_HEADER_NAME],
            evidence_fds[_WRITEOUT_NAME],
            evidence_fds[_STDERR_NAME],
        )
        _write_all(evidence_fds[_PROCESS_RESULT_NAME], _process_result_bytes(process))
        for name in _COMMON_EVIDENCE:
            os.fsync(evidence_fds[name])
        os.fsync(stage_fd)
        _assert_full_fingerprints(
            (parent_fd,), direct_parent_full, "direct source parent"
        )
        _assert_full_fingerprints((stage_fd,), (stage_full,), "stage")
        evaluation = _evaluate_stage(
            process,
            evidence_fds[_ARCHIVE_NAME],
            evidence_fds[_HEADER_NAME],
            evidence_fds[_WRITEOUT_NAME],
        )
        if evaluation.inventory is not None:
            evidence_fds[_INVENTORY_NAME] = _create_private_file(
                stage_fd, _INVENTORY_NAME
            )
            _write_all(evidence_fds[_INVENTORY_NAME], evaluation.inventory)
            os.fsync(evidence_fds[_INVENTORY_NAME])
            os.fsync(stage_fd)
            stage_full = _fingerprint_fd(stage_fd)
        facts = dict(_assert_stage_artifacts(stage_fd, evidence_fds))
        if set(_scan_stage_names(stage_fd)) != set(evidence_fds):
            raise StrategyQaAcquisitionError("pre-manifest stage file set differs")
        _assert_full_fingerprints(
            (parent_fd,), direct_parent_full, "direct source parent"
        )
        _assert_full_fingerprints((stage_fd,), (stage_full,), "stage")
        if git_checker(approved) != approved:
            raise StrategyQaAcquisitionError("pre_manifest Git checker differs")
        manifest_membership, manifest_acl = _policy_gate(
            layout, absolute_chain, anchors, membership_checker, acl_checker
        )
        if (
            manifest_membership != pre_membership
            or manifest_acl != pre_acl
        ):
            raise StrategyQaAcquisitionError("pre-manifest policy gate differs")
        _assert_parent_chain(
            project_fd, layout.parent_relative, parent_chain, parent_expected
        )
        _assert_stage_binding(
            parent_fd, layout.stage_leaf, stage_fd, stage_identity
        )
        _require_absent(parent_fd, layout.formal_leaf, "formal StrategyQA revision")
        manifest = _build_manifest(
            evaluation,
            facts,
            approved,
            anchors,
            direct_parent_full[0],
            stage_full,
            runtime_resources,
        )
        published = _publish_manifest(
            parent_fd, layout.stage_leaf, stage_fd, stage_identity, manifest
        )
        manifest_guard_fd = published.guard_fd
        manifest_final_fd = published.final_fd
        manifest_pair_fingerprint = published.pair_fingerprint
        manifest_content = published.content
        stage_full = published.stage_fingerprint
        _assert_held_manifest_pair(
            stage_fd,
            manifest_guard_fd,
            manifest_final_fd,
            manifest_pair_fingerprint,
            manifest_content,
        )
        terminal_membership, terminal_acl = _policy_gate(
            layout, absolute_chain, anchors, membership_checker, acl_checker
        )
        if terminal_membership != pre_membership or terminal_acl != pre_acl:
            raise StrategyQaAcquisitionError("terminal policy gate differs")
        _assert_parent_chain(
            project_fd, layout.parent_relative, parent_chain, parent_expected
        )
        _assert_stage_binding(
            parent_fd, layout.stage_leaf, stage_fd, stage_identity
        )
        _require_absent(parent_fd, layout.formal_leaf, "formal StrategyQA revision")
        expected_names = set(evidence_fds) | {_MANIFEST_GUARD, _MANIFEST_FINAL}
        if set(_scan_stage_names(stage_fd)) != expected_names:
            raise StrategyQaAcquisitionError("terminal stage file set differs")
        _assert_stage_artifacts(stage_fd, evidence_fds, facts)
        _assert_manifest_pair(stage_fd, manifest_content)
        _assert_held_manifest_pair(
            stage_fd,
            manifest_guard_fd,
            manifest_final_fd,
            manifest_pair_fingerprint,
            manifest_content,
        )
        terminal_process_content = _pread_bounded(
            evidence_fds[_PROCESS_RESULT_NAME], PROCESS_RESULT_LIMIT
        )
        terminal_process = _parse_process_result(terminal_process_content)
        if _process_result_bytes(terminal_process) != terminal_process_content:
            raise StrategyQaAcquisitionError("terminal process result is not canonical")
        replay = _evaluate_stage(
            terminal_process,
            evidence_fds[_ARCHIVE_NAME],
            evidence_fds[_HEADER_NAME],
            evidence_fds[_WRITEOUT_NAME],
        )
        if replay != evaluation:
            raise StrategyQaAcquisitionError("terminal stage replay differs")
        if replay.inventory is not None and _pread_bounded(
            evidence_fds[_INVENTORY_NAME], INVENTORY_LIMIT
        ) != replay.inventory:
            raise StrategyQaAcquisitionError("terminal inventory replay differs")
        rebuilt_manifest = _build_manifest(
            replay,
            facts,
            approved,
            anchors,
            direct_parent_full[0],
            stage_full,
            runtime_resources,
        )
        if _manifest_bytes(rebuilt_manifest) != manifest_content:
            raise StrategyQaAcquisitionError("terminal manifest replay differs")
        _assert_full_fingerprints(
            (parent_fd,), direct_parent_full, "direct source parent"
        )
        _assert_full_fingerprints((stage_fd,), (stage_full,), "stage")
        _assert_transaction_marker(
            project_fd, marker_fd, marker_content, marker_facts
        )

        owned_final = manifest_final_fd
        manifest_final_fd = -1
        os.close(owned_final)
        owned_guard = manifest_guard_fd
        manifest_guard_fd = -1
        os.close(owned_guard)
        for name in reversed(tuple(evidence_fds)):
            owned = evidence_fds.pop(name)
            os.close(owned)
        owned_stage = stage_fd
        stage_fd = -1
        os.close(owned_stage)
        while parent_chain:
            os.close(parent_chain.pop())
        while absolute_chain:
            os.close(absolute_chain.pop())
        commit_replay = _verify_stage_layout_strict(
            layout, anchors, (marker_fd, marker_content)
        )
        if (
            commit_replay.status is not evaluation.status
            or commit_replay.observation is None
            or _manifest_bytes(commit_replay.observation) != manifest_content
        ):
            raise StrategyQaAcquisitionError("commit-point stage replay differs")
        _commit_transaction_marker(
            layout,
            anchors,
            recovery_root_fd,
            marker_fd,
            marker_content,
            marker_facts,
        )
        committed = True
        report = StageReport(evaluation.status, evaluation.reason_code, manifest)
        owned_marker = marker_fd
        marker_fd = -1
        _close_after_commit_warning(owned_marker, "transaction marker")
        owned_recovery = recovery_root_fd
        recovery_root_fd = -1
        _close_after_commit_warning(owned_recovery, "transaction recovery root")
        return report
    except BaseException as original_error:
        if (
            not committed
            and marker_fd >= 0
            and recovery_root_fd >= 0
            and marker_content is not None
            and marker_facts is not None
        ):
            try:
                restored = _restore_transaction_marker(
                    recovery_root_fd,
                    marker_fd,
                    marker_content,
                    marker_facts,
                )
            except BaseException as recovery_error:
                raise StrategyQaAcquisitionError(
                    "transaction marker recovery is unconfirmed"
                ) from recovery_error
            if restored is not True:
                raise StrategyQaAcquisitionError(
                    "transaction marker recovery is unconfirmed"
                ) from original_error
        raise
    finally:
        active = sys.exc_info()[1]
        owned: list[tuple[str, int]] = [
            (name, evidence_fds[name]) for name in reversed(tuple(evidence_fds))
        ]
        owned.extend(
            (
                ("manifest-final", manifest_final_fd),
                ("manifest-guard", manifest_guard_fd),
            )
        )
        owned.append(("stage", stage_fd))
        owned.extend(("parent", fd) for fd in reversed(parent_chain))
        owned.extend(("absolute", fd) for fd in reversed(absolute_chain))
        if not committed:
            owned.extend(
                (
                    ("transaction-marker", marker_fd),
                    ("transaction-recovery-root", recovery_root_fd),
                )
            )
        evidence_fds.clear()
        parent_chain.clear()
        absolute_chain.clear()
        _close_fds_best_effort(owned, active)


def fetch(approved_commit: str) -> StageReport:
    """Run the fixed transfer only after redirect semantics receive approval."""

    if not RUNTIME_REDIRECT_SEMANTICS_VERIFIED:
        raise StrategyQaAcquisitionError(
            "runtime redirect semantics are UNVERIFIED; production GET is blocked"
        )
    approved = _validate_commit(approved_commit)
    runtime_resources = _validate_runtime_gate()
    return _fetch_layout(
        _PRODUCTION_LAYOUT,
        FROZEN_CHAIN_ANCHORS,
        approved,
        _git_clean_head,
        _verify_private_group,
        _verify_chain_acl,
        _run_transfer,
        runtime_resources,
        True,
    )


def verify_stage() -> StageReport:
    """Verify the fixed stage without Git, NSS, subprocesses, or network."""

    _validate_runtime_gate()
    return _verify_stage_layout(_PRODUCTION_LAYOUT, FROZEN_CHAIN_ANCHORS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kairos.strategyqa_acquisition"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--kairos-commit", required=True)
    commands.add_parser("verify-stage")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "fetch":
            if RUNTIME_REDIRECT_SEMANTICS_VERIFIED:
                _apply_cli_resource_gate()
            report = fetch(arguments.kairos_commit)
        else:
            _apply_cli_resource_gate()
            report = verify_stage()
    except (
        StrategyQaAcquisitionError,
        ArchiveSafetyError,
        FileExistsError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ) as error:
        print(f"strategyqa acquisition failed: {error}", file=sys.stderr)
        return 2
    print(canonical_json(report.as_mapping()))
    if report.status is StageStatus.STAGE_OK:
        return 0
    if report.status is StageStatus.BLOCKED:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ChainAnchor",
    "StageReport",
    "StageStatus",
    "StrategyQaAcquisitionError",
    "fetch",
    "main",
    "verify_stage",
]
