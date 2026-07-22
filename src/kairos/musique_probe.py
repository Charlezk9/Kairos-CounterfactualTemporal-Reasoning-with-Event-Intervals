"""Single-attempt, bounded response-body acquisition for the pinned MuSiQue object.

The production ``execute`` entry point is intentionally narrow.  It writes a
65,536-byte response prefix and non-sensitive process evidence to a fixed
private stage, but it never publishes a raw dataset revision or inspects an
archive beyond its leading ZIP signature.  Production execution requires a
separate, explicit approval; normal development tests exercise only private
layout-aware helpers with a synthetic process runner.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence


OFFICIAL_REPOSITORY_COMMIT = "922ac98f19a201998dbdae6d7f2887a5258dbdeb"
DRIVE_OBJECT_ID = "1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h"
FIXED_URL = (
    "https://drive.google.com/file/d/"
    "1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h/view?usp=sharing"
)

PROJECT_ROOT = Path("/data0/hk_data/kairos-zx")
REPOSITORY_ROOT = Path("/home/yangbin/zx-tmp/kairos")
STAGE_RELATIVE_PATH = (
    "data/raw/musique/"
    ".probe-view-1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h-v1"
)
FORMAL_RELATIVE_PATH = (
    "data/raw/musique/922ac98f19a201998dbdae6d7f2887a5258dbdeb"
)

GIT_PATH = "/usr/bin/git"
PRLIMIT_PATH = "/usr/bin/prlimit"
CURL_PATH = "/usr/bin/curl"

RANGE_START = 0
RANGE_END = 65_535
BODY_SIZE = 65_536
CONNECT_TIMEOUT_SECONDS = 10
TOTAL_TIMEOUT_SECONDS = 45
WATCHDOG_SECONDS = 50
WATCHDOG_GRACE_SECONDS = 2
SPEED_LIMIT_BYTES_PER_SECOND = 1_024
SPEED_TIME_SECONDS = 10

_BODY_NAME = "response-prefix.bin"
_WRITEOUT_NAME = "curl-writeout.txt"
_STDERR_NAME = "curl-stderr.bin"
_PROCESS_RESULT_NAME = "process-result.json"
_OBSERVATION_NAME = "probe-observation.json"
_OBSERVATION_TEMP = ".probe-observation.json.tmp"
_EVIDENCE_NAMES = (
    _BODY_NAME,
    _WRITEOUT_NAME,
    _STDERR_NAME,
    _PROCESS_RESULT_NAME,
)
_FINAL_NAMES = frozenset((*_EVIDENCE_NAMES, _OBSERVATION_NAME))
_INCOMPLETE_NAMES = frozenset((*_FINAL_NAMES, _OBSERVATION_TEMP))

_WRITEOUT_LIMIT = 4_096
_STDERR_LIMIT = 65_536
_PROCESS_RESULT_LIMIT = 4_096
_OBSERVATION_LIMIT = 65_536
_OVERFLOW_READ_LIMIT = 65_537
_GIT_OUTPUT_LIMIT = 4_096
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_MIME = frozenset(
    {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    }
)
_ZIP_MAGIC = b"PK\x03\x04"

_WRITEOUT_BEGIN = "KAIROS-MUSIQUE-PROBE-V1-BEGIN"
_WRITEOUT_END = "KAIROS-MUSIQUE-PROBE-V1-END"
_WRITEOUT_KEYS = (
    "http_code",
    "num_redirects",
    "url_effective",
    "content_type",
    "size_download",
)
_WRITEOUT_FORMAT = (
    f"{_WRITEOUT_BEGIN}\n"
    "http_code:%{http_code}\n"
    "num_redirects:%{num_redirects}\n"
    "url_effective:%{url_effective}\n"
    "content_type:%{content_type}\n"
    "size_download:%{size_download}\n"
    f"{_WRITEOUT_END}\n"
)


class ProbeError(ValueError):
    """A probe safety or integrity invariant failed."""


class ProbeStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"
    PROBE_OK = "PROBE_OK"


@dataclass(frozen=True)
class ProbeReport:
    status: ProbeStatus
    reason_code: str
    observation: Optional[Mapping[str, Any]]

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "observation": self.observation,
        }


@dataclass(frozen=True)
class _Layout:
    project_root: Path
    repository_root: Path
    stage_relative_path: str
    formal_relative_path: str

    def __post_init__(self) -> None:
        def components(value: str) -> tuple[str, ...]:
            if (
                not isinstance(value, str)
                or not value
                or value.startswith("/")
                or "\\" in value
                or "\x00" in value
            ):
                raise ProbeError("layout path is invalid")
            result = tuple(value.split("/"))
            if any(component in {"", ".", ".."} for component in result):
                raise ProbeError("layout path contains an unsafe component")
            return result

        stage = components(self.stage_relative_path)
        formal = components(self.formal_relative_path)
        if stage[:-1] != formal[:-1] or stage[-1] == formal[-1]:
            raise ProbeError("stage and formal paths must be distinct siblings")

    @property
    def parent_relative_path(self) -> str:
        return "/".join(_relative_components(self.stage_relative_path)[:-1])

    @property
    def stage_leaf(self) -> str:
        return _relative_components(self.stage_relative_path)[-1]

    @property
    def formal_leaf(self) -> str:
        return _relative_components(self.formal_relative_path)[-1]


_PRODUCTION_LAYOUT = _Layout(
    PROJECT_ROOT,
    REPOSITORY_ROOT,
    STAGE_RELATIVE_PATH,
    FORMAL_RELATIVE_PATH,
)


@dataclass(frozen=True)
class _Fingerprint:
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _ArtifactFacts:
    path: str
    byte_size: int
    hash_read_count: int
    sha256: str
    fingerprint: _Fingerprint
    content: bytes


@dataclass(frozen=True)
class _CurlWriteout:
    http_code: int
    num_redirects: int
    effective_url: str
    mime: str
    size_download: int


@dataclass(frozen=True)
class _ProcessResult:
    process_started: bool
    returncode: Optional[int]
    watchdog_action: str
    spawn_error_type: Optional[str]

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "process_started": self.process_started,
            "returncode": self.returncode,
            "watchdog_action": self.watchdog_action,
            "spawn_error_type": self.spawn_error_type,
        }


def _relative_components(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ProbeError("relative path is invalid")
    if "\\" in value or "\x00" in value:
        raise ProbeError("relative path contains a forbidden character")
    components = tuple(value.split("/"))
    if any(component in {"", ".", ".."} for component in components):
        raise ProbeError("relative path contains an unsafe component")
    return components


def _validate_commit(value: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise ProbeError("approved commit must be 40 lowercase hexadecimal characters")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as error:
        raise ProbeError("value is not canonical JSON") from error
    return encoded


def _reject_constant(_value: str) -> None:
    raise ProbeError("non-finite JSON value is forbidden")


def _pairs_object(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProbeError("duplicate JSON key is forbidden")
        result[key] = value
    return result


def _strict_json_object(content: bytes, name: str) -> Mapping[str, Any]:
    if not content.endswith(b"\n") or content.count(b"\n") != 1:
        raise ProbeError(f"{name} must be one LF-terminated JSON object")
    try:
        decoded = content[:-1].decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_pairs_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProbeError(f"{name} is not strict JSON") from error
    if not isinstance(value, Mapping):
        raise ProbeError(f"{name} must be a JSON object")
    if _canonical_json_bytes(value) != content:
        raise ProbeError(f"{name} must be canonical JSON")
    return value


def _exact_mapping(value: Any, keys: Iterable[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ProbeError(f"{name} keys differ")
    if any(not isinstance(key, str) for key in value):
        raise ProbeError(f"{name} keys must be strings")
    return value


def _exact_int(value: Any, name: str, minimum: Optional[int] = None) -> int:
    if type(value) is not int:
        raise ProbeError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ProbeError(f"{name} is below its minimum")
    return value


def _exact_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProbeError(f"{name} must be a boolean")
    return value


def _exact_string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ProbeError(f"{name} must be a string")
    return value


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


def _fingerprint_fd(fd: int) -> _Fingerprint:
    value = os.fstat(fd)
    return _Fingerprint(
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _fingerprint_stat(value: os.stat_result) -> _Fingerprint:
    return _Fingerprint(
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_trusted_directory(fd: int, name: str) -> None:
    value = os.fstat(fd)
    if not stat.S_ISDIR(value.st_mode):
        raise ProbeError(f"{name} is not a directory")
    if value.st_uid not in {0, os.geteuid()}:
        raise ProbeError(f"{name} has an untrusted owner")
    if stat.S_IMODE(value.st_mode) & 0o022:
        raise ProbeError(f"{name} is group/other writable")


def _require_owned_directory(fd: int, name: str, exact_private: bool = False) -> None:
    value = os.fstat(fd)
    mode = stat.S_IMODE(value.st_mode)
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid():
        raise ProbeError(f"{name} must be an owned directory")
    if exact_private:
        if mode != 0o700:
            raise ProbeError(f"{name} must have mode 0700")
    elif mode & 0o022:
        raise ProbeError(f"{name} is group/other writable")


def _require_evidence_fingerprint(value: _Fingerprint, name: str) -> None:
    if (
        not stat.S_ISREG(value.mode)
        or stat.S_IMODE(value.mode) != 0o600
        or value.uid != os.geteuid()
        or value.nlink != 1
    ):
        raise ProbeError(f"{name} is not a private single-link regular file")


def _open_absolute_chain(path: Path) -> list[int]:
    raw = os.fspath(path)
    if not os.path.isabs(raw):
        raise ProbeError("absolute root path is required")
    components = tuple(component for component in raw.split("/")[1:] if component)
    if any(component in {".", ".."} for component in components):
        raise ProbeError("absolute path contains an unsafe component")
    held: list[int] = []
    try:
        held.append(os.open("/", _dir_flags()))
        _require_trusted_directory(held[-1], "filesystem root")
        for component in components:
            held.append(os.open(component, _dir_flags(), dir_fd=held[-1]))
            _require_trusted_directory(held[-1], component)
        return held
    except BaseException:
        active = sys.exc_info()[1]
        owned = [("absolute-chain", fd) for fd in reversed(held)]
        held.clear()
        _close_fds_best_effort(owned, active)
        raise


def _open_relative_chain(root_fd: int, relative_path: str) -> list[int]:
    components = _relative_components(relative_path)
    held: list[int] = []
    current = os.dup(root_fd)
    held.append(current)
    try:
        _require_owned_directory(current, "project root")
        for component in components:
            current = os.open(component, _dir_flags(), dir_fd=current)
            held.append(current)
            _require_owned_directory(current, component)
        return held
    except BaseException:
        active = sys.exc_info()[1]
        owned = [("relative-chain", fd) for fd in reversed(held)]
        held.clear()
        _close_fds_best_effort(owned, active)
        raise


def _open_or_create_relative_chain(root_fd: int, relative_path: str) -> list[int]:
    components = _relative_components(relative_path)
    held: list[int] = []
    current = os.dup(root_fd)
    held.append(current)
    try:
        _require_owned_directory(current, "project root")
        for component in components:
            created = False
            try:
                next_fd = os.open(component, _dir_flags(), dir_fd=current)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=current)
                os.fsync(current)
                next_fd = os.open(component, _dir_flags(), dir_fd=current)
                created = True
            held.append(next_fd)
            current = next_fd
            _require_owned_directory(current, component, exact_private=created)
        return held
    except BaseException:
        active = sys.exc_info()[1]
        owned = [("created-chain", fd) for fd in reversed(held)]
        held.clear()
        _close_fds_best_effort(owned, active)
        raise


def _binding_fingerprints(fds: Sequence[int]) -> tuple[_Fingerprint, ...]:
    return tuple(_fingerprint_fd(fd) for fd in fds)


def _assert_absolute_chain(
    path: Path, held: Sequence[int], expected: Sequence[_Fingerprint]
) -> None:
    if _binding_fingerprints(held) != tuple(expected):
        raise ProbeError("held absolute directory chain changed")
    reopened = _open_absolute_chain(path)
    try:
        if _binding_fingerprints(reopened) != tuple(expected):
            raise ProbeError("canonical absolute directory chain changed")
    finally:
        active = sys.exc_info()[1]
        owned = [("canonical-absolute", fd) for fd in reversed(reopened)]
        reopened.clear()
        _close_fds_best_effort(owned, active)


def _assert_relative_chain(
    root_fd: int,
    relative_path: str,
    held: Sequence[int],
    expected: Sequence[_Fingerprint],
) -> None:
    if _binding_fingerprints(held) != tuple(expected):
        raise ProbeError("held relative directory chain changed")
    reopened = _open_relative_chain(root_fd, relative_path)
    try:
        if _binding_fingerprints(reopened) != tuple(expected):
            raise ProbeError("canonical relative directory chain changed")
    finally:
        active = sys.exc_info()[1]
        owned = [("canonical-relative", fd) for fd in reversed(reopened)]
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


def _mkdir_exclusive_private(parent_fd: int, name: str) -> int:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    os.fsync(parent_fd)
    fd = -1
    try:
        fd = os.open(name, _dir_flags(), dir_fd=parent_fd)
        _require_owned_directory(fd, name, exact_private=True)
        return fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort(((name, owned),), active)
        raise


def _open_stage(parent_fd: int, name: str) -> int:
    fd = os.open(name, _dir_flags(), dir_fd=parent_fd)
    try:
        _require_owned_directory(fd, "probe stage", exact_private=True)
        return fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort((("stage", owned),), active)
        raise


def _assert_stage_binding(
    parent_fd: int, leaf: str, stage_fd: int, expected: _Fingerprint
) -> None:
    if _fingerprint_fd(stage_fd) != expected:
        raise ProbeError("held stage changed")
    canonical = -1
    try:
        canonical = _open_stage(parent_fd, leaf)
        if _fingerprint_fd(canonical) != expected:
            raise ProbeError("canonical stage name changed")
    finally:
        active = sys.exc_info()[1]
        owned = canonical
        canonical = -1
        _close_fds_best_effort((("canonical-stage", owned),), active)


def _create_evidence_fd(stage_fd: int, name: str) -> int:
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    fd = os.open(name, flags, 0o600, dir_fd=stage_fd)
    try:
        os.fchmod(fd, 0o600)
        _require_evidence_fingerprint(_fingerprint_fd(fd), name)
        return fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort(((name, owned),), active)
        raise


def _open_evidence_fd(stage_fd: int, name: str) -> int:
    fd = os.open(name, _regular_read_flags(), dir_fd=stage_fd)
    try:
        _require_evidence_fingerprint(_fingerprint_fd(fd), name)
        return fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort(((name, owned),), active)
        raise


def _scan_stage(stage_fd: int, allow_incomplete: bool) -> Mapping[str, _Fingerprint]:
    allowed = _INCOMPLETE_NAMES if allow_incomplete else _FINAL_NAMES
    result: dict[str, _Fingerprint] = {}
    entries = os.scandir(stage_fd)
    try:
        for entry in entries:
            if entry.name not in allowed or entry.name in result:
                raise ProbeError("probe stage contains an unexpected entry")
            value = entry.stat(follow_symlinks=False)
            fingerprint = _fingerprint_stat(value)
            if (
                not stat.S_ISREG(fingerprint.mode)
                or stat.S_IMODE(fingerprint.mode) != 0o600
                or fingerprint.uid != os.geteuid()
                or fingerprint.nlink not in ({1, 2} if allow_incomplete else {1})
            ):
                raise ProbeError("probe stage entry binding is invalid")
            result[entry.name] = fingerprint
    finally:
        active = sys.exc_info()[1]
        owned = entries
        entries = None
        try:
            owned.close()
        except BaseException:
            if active is None:
                raise
    if not allow_incomplete and set(result) != set(_FINAL_NAMES):
        raise ProbeError("completed probe stage file set differs")
    inodes: dict[tuple[int, int], list[str]] = {}
    for name, value in result.items():
        inodes.setdefault((value.device, value.inode), []).append(name)
    for names in inodes.values():
        fingerprint = result[names[0]]
        if len(names) == 1 and fingerprint.nlink != 1:
            raise ProbeError("probe stage contains an external hardlink")
        if len(names) > 1 and (
            set(names) != {_OBSERVATION_NAME, _OBSERVATION_TEMP}
            or fingerprint.nlink != 2
        ):
            raise ProbeError("probe stage contains an unknown hardlink")
    return result


def _bounded_pread(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset <= limit:
        chunk = os.pread(fd, min(65_536, limit + 1 - offset), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
        if offset > limit:
            raise ProbeError("evidence exceeds its read limit")
    return b"".join(chunks)


def _stable_read_hash(fd: int, name: str, limit: int) -> _ArtifactFacts:
    before = _fingerprint_fd(fd)
    _require_evidence_fingerprint(before, name)
    content = _bounded_pread(fd, limit)
    after = _fingerprint_fd(fd)
    if before != after or after.size != len(content):
        raise ProbeError(f"{name} changed while reading")
    return _ArtifactFacts(
        path=name,
        byte_size=after.size,
        hash_read_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        fingerprint=after,
        content=content,
    )


def _assert_canonical_file_binding(
    stage_fd: int, facts: _ArtifactFacts, limit: int
) -> None:
    canonical = -1
    try:
        canonical = _open_evidence_fd(stage_fd, facts.path)
        observed = _stable_read_hash(canonical, facts.path, limit)
        if observed != facts:
            raise ProbeError(f"canonical {facts.path} binding changed")
    finally:
        active = sys.exc_info()[1]
        owned = canonical
        canonical = -1
        _close_fds_best_effort(((facts.path, owned),), active)


def _artifact_limit(name: str) -> int:
    if name == _BODY_NAME:
        return _OVERFLOW_READ_LIMIT
    if name in {_WRITEOUT_NAME, _STDERR_NAME}:
        return _OVERFLOW_READ_LIMIT
    if name == _PROCESS_RESULT_NAME:
        return _PROCESS_RESULT_LIMIT
    raise ProbeError("unknown evidence artifact")


def _freeze_evidence(
    stage_fd: int, evidence_fds: Mapping[str, int], sync: bool
) -> Mapping[str, _ArtifactFacts]:
    if set(evidence_fds) != set(_EVIDENCE_NAMES):
        raise ProbeError("evidence descriptor set differs")
    facts: dict[str, _ArtifactFacts] = {}
    for name in _EVIDENCE_NAMES:
        fd = evidence_fds[name]
        if sync:
            os.fsync(fd)
        facts[name] = _stable_read_hash(fd, name, _artifact_limit(name))
        _assert_canonical_file_binding(stage_fd, facts[name], _artifact_limit(name))
    return facts


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(fd, content[offset:])
        if written <= 0:
            raise ProbeError("short evidence write")
        offset += written


def _child_environment() -> Mapping[str, str]:
    return {"LC_ALL": "C", "LANG": "C", "TZ": "UTC"}


def _git_argv(*arguments: str) -> tuple[str, ...]:
    return (GIT_PATH, "-C", os.fspath(REPOSITORY_ROOT), *arguments)


def _owned_process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_owned_process_group_gone(
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


def _reap_owned_leader(process: subprocess.Popen[Any]) -> None:
    process.wait(timeout=WATCHDOG_GRACE_SECONDS)


def _terminate_and_reap_owned_process_group(
    process: subprocess.Popen[Any], pgid: int
) -> str:
    first_error: Optional[BaseException] = None
    action = "SIGTERM"
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except BaseException as error:
        first_error = error
    group_gone = False
    if first_error is None:
        try:
            group_gone = _wait_owned_process_group_gone(
                process, pgid, WATCHDOG_GRACE_SECONDS
            )
        except BaseException as error:
            first_error = error
    if not group_gone:
        action = "SIGKILL"
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except BaseException as error:
            if first_error is None:
                first_error = error
        try:
            if not _wait_owned_process_group_gone(
                process, pgid, WATCHDOG_GRACE_SECONDS
            ) and first_error is None:
                first_error = ProbeError("owned subprocess group survived SIGKILL")
        except BaseException as error:
            if first_error is None:
                first_error = error
    try:
        _reap_owned_leader(process)
    except BaseException as error:
        if first_error is None:
            first_error = error
    if first_error is not None:
        raise first_error
    return action


def _stop_and_reap_owned_process(
    process: subprocess.Popen[Any], pgid: Optional[int] = None
) -> None:
    _terminate_and_reap_owned_process_group(
        process, process.pid if pgid is None else pgid
    )


def _run_git_bounded(
    arguments: Sequence[str], *, timeout_seconds: float = 10.0
) -> tuple[int, bytes]:
    if not isinstance(timeout_seconds, (int, float)) or isinstance(
        timeout_seconds, bool
    ) or timeout_seconds <= 0:
        raise ProbeError("bounded subprocess timeout is invalid")
    process = subprocess.Popen(
        tuple(arguments),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=os.fspath(REPOSITORY_ROOT),
        env={
            **_child_environment(),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        },
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
            raise ProbeError("git stdout pipe is unavailable")
        selector = selectors.DefaultSelector()
        pipe_fd = stdout.fileno()
        deadline = time.monotonic() + float(timeout_seconds)
        os.set_blocking(pipe_fd, False)
        selector.register(pipe_fd, selectors.EVENT_READ)
        pipe_eof = False
        while not pipe_eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("bounded subprocess timed out")
            events = selector.select(remaining)
            if not events:
                raise ProbeError("bounded subprocess timed out")
            for key, _mask in events:
                try:
                    chunk = os.read(
                        key.fd,
                        min(65_536, _GIT_OUTPUT_LIMIT + 1 - len(output)),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    pipe_eof = True
                    break
                output.extend(chunk)
                if len(output) > _GIT_OUTPUT_LIMIT:
                    raise ProbeError("bounded subprocess output exceeds its limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("bounded subprocess timed out")
        returncode = process.wait(timeout=remaining)
        if _owned_process_group_alive(pgid):
            raise ProbeError("bounded subprocess group outlived its leader")
        return returncode, bytes(output)
    except BaseException:
        active = sys.exc_info()[1]
        try:
            _stop_and_reap_owned_process(process, pgid)
        except BaseException:
            if active is None:
                raise
        raise
    finally:
        active = sys.exc_info()[1]
        _close_objects_best_effort(
            (("selector", selector), ("stdout", stdout)), active
        )


def _git_clean_head(approved_commit: str) -> str:
    approved = _validate_commit(approved_commit)
    returncode, output = _run_git_bounded(
        _git_argv("rev-parse", "--verify", "HEAD")
    )
    if returncode != 0 or output != (approved + "\n").encode("ascii"):
        raise ProbeError("clean HEAD differs from the approved commit")
    returncode, output = _run_git_bounded(
        _git_argv("status", "--porcelain=v1", "--untracked-files=normal")
    )
    if returncode != 0 or output:
        raise ProbeError("repository is not clean")
    return approved


def _build_curl_argv(body_fd: int) -> tuple[str, ...]:
    if type(body_fd) is not int or body_fd < 0:
        raise ProbeError("body descriptor is invalid")
    return (
        PRLIMIT_PATH,
        f"--fsize={BODY_SIZE}:{BODY_SIZE}",
        "--cpu=50:50",
        "--",
        CURL_PATH,
        "-q",
        "--silent",
        "--show-error",
        "--fail",
        "--request",
        "GET",
        "--proto",
        "=https",
        "--http1.1",
        "--range",
        f"{RANGE_START}-{RANGE_END}",
        "--output",
        f"/proc/self/fd/{body_fd}",
        "--write-out",
        _WRITEOUT_FORMAT,
        "--connect-timeout",
        str(CONNECT_TIMEOUT_SECONDS),
        "--max-time",
        str(TOTAL_TIMEOUT_SECONDS),
        "--speed-limit",
        str(SPEED_LIMIT_BYTES_PER_SECOND),
        "--speed-time",
        str(SPEED_TIME_SECONDS),
        "--retry",
        "0",
        "--max-filesize",
        str(BODY_SIZE),
        "--max-redirs",
        "0",
        "--proxy",
        "",
        "--noproxy",
        "*",
        FIXED_URL,
    )


def _verify_procfd_alias(body_fd: int) -> None:
    proc_path = f"/proc/self/fd/{body_fd}"
    value = os.stat(proc_path, follow_symlinks=True)
    if _fingerprint_stat(value) != _fingerprint_fd(body_fd):
        raise ProbeError("procfd does not map to the held body descriptor")


def _kill_owned_process_group(process: subprocess.Popen[Any]) -> str:
    return _terminate_and_reap_owned_process_group(process, process.pid)


def _run_probe_process(
    body_fd: int, writeout_fd: int, stderr_fd: int
) -> _ProcessResult:
    _verify_procfd_alias(body_fd)
    try:
        process = subprocess.Popen(
            _build_curl_argv(body_fd),
            stdin=subprocess.DEVNULL,
            stdout=writeout_fd,
            stderr=stderr_fd,
            cwd=os.fspath(REPOSITORY_ROOT),
            env=_child_environment(),
            shell=False,
            close_fds=True,
            pass_fds=(body_fd,),
            start_new_session=True,
        )
    except OSError as error:
        return _ProcessResult(False, None, "NOT_STARTED", type(error).__name__)
    try:
        try:
            returncode = process.wait(timeout=WATCHDOG_SECONDS)
            return _ProcessResult(True, returncode, "NONE", None)
        except subprocess.TimeoutExpired:
            action = _kill_owned_process_group(process)
            return _ProcessResult(True, process.returncode, action, None)
    except BaseException:
        active = sys.exc_info()[1]
        try:
            _kill_owned_process_group(process)
        except BaseException:
            if active is None:
                raise
        raise


def _write_process_result(fd: int, result: _ProcessResult) -> None:
    content = _canonical_json_bytes(result.as_mapping())
    if len(content) > _PROCESS_RESULT_LIMIT:
        raise ProbeError("process result exceeds its limit")
    if _fingerprint_fd(fd).size != 0:
        raise ProbeError("process result evidence is not empty")
    _write_all(fd, content)


def _parse_process_result(content: bytes) -> _ProcessResult:
    value = _strict_json_object(content, "process result")
    value = _exact_mapping(
        value,
        {"process_started", "returncode", "watchdog_action", "spawn_error_type"},
        "process result",
    )
    started = _exact_bool(value["process_started"], "process_started")
    returncode_value = value["returncode"]
    if returncode_value is not None:
        returncode = _exact_int(returncode_value, "returncode")
    else:
        returncode = None
    watchdog = _exact_string(value["watchdog_action"], "watchdog_action")
    if watchdog not in {"NONE", "NOT_STARTED", "SIGTERM", "SIGKILL"}:
        raise ProbeError("watchdog action differs")
    spawn_error_value = value["spawn_error_type"]
    if spawn_error_value is not None and not isinstance(spawn_error_value, str):
        raise ProbeError("spawn error type differs")
    if started:
        if returncode is None or watchdog == "NOT_STARTED" or spawn_error_value is not None:
            raise ProbeError("started process result is inconsistent")
    elif returncode is not None or watchdog != "NOT_STARTED" or spawn_error_value is None:
        raise ProbeError("unstarted process result is inconsistent")
    return _ProcessResult(started, returncode, watchdog, spawn_error_value)


def _parse_writeout(content: bytes) -> _CurlWriteout:
    if len(content) > _WRITEOUT_LIMIT:
        raise ProbeError("curl write-out exceeds its application limit")
    try:
        decoded = content.decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise ProbeError("curl write-out is not ASCII") from error
    if not decoded.endswith("\n"):
        raise ProbeError("curl write-out is not LF terminated")
    if any(character != "\n" and not 0x20 <= ord(character) <= 0x7E for character in decoded):
        raise ProbeError("curl write-out contains a control character")
    lines = decoded[:-1].split("\n")
    if len(lines) != 7 or lines[0] != _WRITEOUT_BEGIN or lines[-1] != _WRITEOUT_END:
        raise ProbeError("curl write-out sentinel differs")
    values: dict[str, str] = {}
    for expected_key, line in zip(_WRITEOUT_KEYS, lines[1:-1]):
        if ":" not in line:
            raise ProbeError("curl write-out field is malformed")
        key, value = line.split(":", 1)
        if key != expected_key or key in values:
            raise ProbeError("curl write-out fields differ")
        values[key] = value
    if re.fullmatch(r"[0-9]{3}", values["http_code"]) is None:
        raise ProbeError("HTTP code is malformed")
    for name in ("num_redirects", "size_download"):
        if re.fullmatch(r"[0-9]+", values[name]) is None:
            raise ProbeError(f"{name} is malformed")
    return _CurlWriteout(
        int(values["http_code"]),
        int(values["num_redirects"]),
        values["url_effective"],
        values["content_type"],
        int(values["size_download"]),
    )


def _looks_like_html(content: bytes) -> bool:
    prefix = content[:512].lstrip(b" \t\r\n").lower()
    return any(
        prefix.startswith(marker)
        for marker in (b"<!doctype html", b"<html", b"<head", b"<body")
    )


def _decide_status(
    process: _ProcessResult,
    writeout: Optional[_CurlWriteout],
    writeout_valid: bool,
    artifacts: Mapping[str, _ArtifactFacts],
) -> tuple[ProbeStatus, str]:
    body = artifacts[_BODY_NAME]
    if not process.process_started:
        return ProbeStatus.BLOCKED, "PROCESS_SPAWN_FAILED"
    if process.watchdog_action != "NONE":
        return ProbeStatus.BLOCKED, "WATCHDOG_TIMEOUT"
    if process.returncode != 0:
        return ProbeStatus.BLOCKED, "PROCESS_EXIT_NONZERO"
    if not writeout_valid or writeout is None:
        return ProbeStatus.BLOCKED, "WRITEOUT_INVALID"
    if artifacts[_STDERR_NAME].byte_size > _STDERR_LIMIT:
        return ProbeStatus.BLOCKED, "STDERR_LIMIT_EXCEEDED"
    if writeout.http_code != 206:
        return ProbeStatus.BLOCKED, "HTTP_STATUS_NOT_206"
    if writeout.num_redirects != 0:
        return ProbeStatus.BLOCKED, "REDIRECT_OBSERVED"
    if writeout.effective_url != FIXED_URL:
        return ProbeStatus.BLOCKED, "EFFECTIVE_URL_MISMATCH"
    if (
        writeout.size_download != BODY_SIZE
        or body.byte_size != BODY_SIZE
        or body.hash_read_count != BODY_SIZE
    ):
        return ProbeStatus.BLOCKED, "BODY_SIZE_NOT_EXACT"
    if writeout.mime not in _ALLOWED_MIME:
        return ProbeStatus.BLOCKED, "MIME_NOT_ALLOWED"
    if not body.content.startswith(_ZIP_MAGIC):
        return ProbeStatus.BLOCKED, "ZIP_MAGIC_MISSING"
    if _looks_like_html(body.content):
        return ProbeStatus.BLOCKED, "HTML_LIKE_BODY"
    return ProbeStatus.PROBE_OK, "ALL_GATES_PASSED"


def _artifact_mapping(facts: _ArtifactFacts) -> Mapping[str, Any]:
    return {
        "path": facts.path,
        "mode": stat.S_IMODE(facts.fingerprint.mode),
        "device": facts.fingerprint.device,
        "inode": facts.fingerprint.inode,
        "uid": facts.fingerprint.uid,
        "gid": facts.fingerprint.gid,
        "nlink": facts.fingerprint.nlink,
        "byte_size": facts.byte_size,
        "hash_read_count": facts.hash_read_count,
        "mtime_ns": facts.fingerprint.mtime_ns,
        "ctime_ns": facts.fingerprint.ctime_ns,
        "sha256": facts.sha256,
    }


def _build_observation(
    approved_commit: str,
    process: _ProcessResult,
    writeout: Optional[_CurlWriteout],
    writeout_valid: bool,
    artifacts: Mapping[str, _ArtifactFacts],
) -> Mapping[str, Any]:
    body = artifacts[_BODY_NAME]
    status, reason = _decide_status(process, writeout, writeout_valid, artifacts)
    accepted_mime = (
        writeout.mime if writeout is not None and writeout.mime in _ALLOWED_MIME else None
    )
    return {
        "schema_version": "kairos-musique-drive-prefix-probe-v1",
        "status": status.value,
        "reason_code": reason,
        "source": {
            "official_repository_commit": OFFICIAL_REPOSITORY_COMMIT,
            "drive_object_id": DRIVE_OBJECT_ID,
            "fixed_url": FIXED_URL,
            "stage_relative_path": STAGE_RELATIVE_PATH,
            "formal_relative_path": FORMAL_RELATIVE_PATH,
        },
        "execution": {
            "approved_git_commit": approved_commit,
            "git_path": GIT_PATH,
            "prlimit_path": PRLIMIT_PATH,
            "curl_path": CURL_PATH,
            **process.as_mapping(),
        },
        "http": {
            "writeout_valid": writeout_valid,
            "http_code": writeout.http_code if writeout is not None else None,
            "num_redirects": writeout.num_redirects if writeout is not None else None,
            "effective_url_matches_fixed": (
                writeout.effective_url == FIXED_URL if writeout is not None else False
            ),
            "accepted_mime": accepted_mime,
            "size_download": writeout.size_download if writeout is not None else None,
            "content_range": None,
            "archive_total_size_bytes": None,
            "archive_total_size_status": "UNVERIFIED_NO_CONTENT_RANGE",
        },
        "body": {
            "byte_size": body.byte_size,
            "hash_read_count": body.hash_read_count,
            "sha256": body.sha256,
            "zip_magic": body.content.startswith(_ZIP_MAGIC),
            "html_like": _looks_like_html(body.content),
        },
        "artifacts": {
            name: _artifact_mapping(artifacts[name]) for name in _EVIDENCE_NAMES
        },
        "limits": {
            "range_start": RANGE_START,
            "range_end": RANGE_END,
            "exact_body_bytes": BODY_SIZE,
            "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
            "total_timeout_seconds": TOTAL_TIMEOUT_SECONDS,
            "watchdog_seconds": WATCHDOG_SECONDS,
            "speed_limit_bytes_per_second": SPEED_LIMIT_BYTES_PER_SECOND,
            "speed_time_seconds": SPEED_TIME_SECONDS,
        },
    }


_OBSERVATION_KEYS = {
    "schema_version",
    "status",
    "reason_code",
    "source",
    "execution",
    "http",
    "body",
    "artifacts",
    "limits",
}


def _validate_observation_literals(value: Mapping[str, Any]) -> None:
    value = _exact_mapping(value, _OBSERVATION_KEYS, "probe observation")
    if value["schema_version"] != "kairos-musique-drive-prefix-probe-v1":
        raise ProbeError("observation schema version differs")
    status = _exact_string(value["status"], "observation status")
    if status not in {ProbeStatus.BLOCKED.value, ProbeStatus.PROBE_OK.value}:
        raise ProbeError("observation status differs")
    _exact_string(value["reason_code"], "reason code")

    source = _exact_mapping(
        value["source"],
        {
            "official_repository_commit",
            "drive_object_id",
            "fixed_url",
            "stage_relative_path",
            "formal_relative_path",
        },
        "observation source",
    )
    if source != {
        "official_repository_commit": OFFICIAL_REPOSITORY_COMMIT,
        "drive_object_id": DRIVE_OBJECT_ID,
        "fixed_url": FIXED_URL,
        "stage_relative_path": STAGE_RELATIVE_PATH,
        "formal_relative_path": FORMAL_RELATIVE_PATH,
    }:
        raise ProbeError("observation source literals differ")

    execution = _exact_mapping(
        value["execution"],
        {
            "approved_git_commit",
            "git_path",
            "prlimit_path",
            "curl_path",
            "process_started",
            "returncode",
            "watchdog_action",
            "spawn_error_type",
        },
        "observation execution",
    )
    _validate_commit(_exact_string(execution["approved_git_commit"], "approved commit"))
    if (
        execution["git_path"] != GIT_PATH
        or execution["prlimit_path"] != PRLIMIT_PATH
        or execution["curl_path"] != CURL_PATH
    ):
        raise ProbeError("observation executable paths differ")
    _parse_process_result(
        _canonical_json_bytes(
            {
                key: execution[key]
                for key in (
                    "process_started",
                    "returncode",
                    "watchdog_action",
                    "spawn_error_type",
                )
            }
        )
    )

    http = _exact_mapping(
        value["http"],
        {
            "writeout_valid",
            "http_code",
            "num_redirects",
            "effective_url_matches_fixed",
            "accepted_mime",
            "size_download",
            "content_range",
            "archive_total_size_bytes",
            "archive_total_size_status",
        },
        "observation HTTP",
    )
    _exact_bool(http["writeout_valid"], "writeout_valid")
    _exact_bool(http["effective_url_matches_fixed"], "effective URL match")
    for key in ("http_code", "num_redirects", "size_download"):
        if http[key] is not None:
            _exact_int(http[key], key, 0)
    if http["accepted_mime"] is not None and http["accepted_mime"] not in _ALLOWED_MIME:
        raise ProbeError("accepted MIME differs")
    if (
        http["content_range"] is not None
        or http["archive_total_size_bytes"] is not None
        or http["archive_total_size_status"] != "UNVERIFIED_NO_CONTENT_RANGE"
    ):
        raise ProbeError("total archive size must remain unverified")

    body = _exact_mapping(
        value["body"],
        {"byte_size", "hash_read_count", "sha256", "zip_magic", "html_like"},
        "observation body",
    )
    _exact_int(body["byte_size"], "body byte size", 0)
    _exact_int(body["hash_read_count"], "body hash read count", 0)
    if not isinstance(body["sha256"], str) or _HEX64.fullmatch(body["sha256"]) is None:
        raise ProbeError("body SHA256 differs")
    _exact_bool(body["zip_magic"], "zip_magic")
    _exact_bool(body["html_like"], "html_like")

    artifacts = _exact_mapping(value["artifacts"], _EVIDENCE_NAMES, "artifacts")
    for name in _EVIDENCE_NAMES:
        artifact = _exact_mapping(
            artifacts[name],
            {
                "path",
                "mode",
                "device",
                "inode",
                "uid",
                "gid",
                "nlink",
                "byte_size",
                "hash_read_count",
                "mtime_ns",
                "ctime_ns",
                "sha256",
            },
            f"artifact {name}",
        )
        if artifact["path"] != name or artifact["mode"] != 0o600:
            raise ProbeError(f"artifact {name} literals differ")
        _exact_int(artifact["byte_size"], f"{name} byte size", 0)
        _exact_int(artifact["hash_read_count"], f"{name} read count", 0)
        for key in ("device", "inode", "uid", "gid", "nlink", "mtime_ns", "ctime_ns"):
            _exact_int(artifact[key], f"{name} {key}", 0)
        if artifact["uid"] != os.geteuid() or artifact["nlink"] != 1:
            raise ProbeError(f"artifact {name} ownership/link count differs")
        if artifact["byte_size"] != artifact["hash_read_count"]:
            raise ProbeError(f"artifact {name} count differs")
        if not isinstance(artifact["sha256"], str) or _HEX64.fullmatch(artifact["sha256"]) is None:
            raise ProbeError(f"artifact {name} SHA256 differs")
    if (
        artifacts[_BODY_NAME]["byte_size"] != body["byte_size"]
        or artifacts[_BODY_NAME]["hash_read_count"] != body["hash_read_count"]
        or artifacts[_BODY_NAME]["sha256"] != body["sha256"]
    ):
        raise ProbeError("body and artifact facts differ")

    limits = _exact_mapping(
        value["limits"],
        {
            "range_start",
            "range_end",
            "exact_body_bytes",
            "connect_timeout_seconds",
            "total_timeout_seconds",
            "watchdog_seconds",
            "speed_limit_bytes_per_second",
            "speed_time_seconds",
        },
        "observation limits",
    )
    if limits != {
        "range_start": RANGE_START,
        "range_end": RANGE_END,
        "exact_body_bytes": BODY_SIZE,
        "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
        "total_timeout_seconds": TOTAL_TIMEOUT_SECONDS,
        "watchdog_seconds": WATCHDOG_SECONDS,
        "speed_limit_bytes_per_second": SPEED_LIMIT_BYTES_PER_SECOND,
        "speed_time_seconds": SPEED_TIME_SECONDS,
    }:
        raise ProbeError("observation limits differ")


def _validate_observation_against_artifacts(
    observation: Mapping[str, Any], artifacts: Mapping[str, _ArtifactFacts]
) -> None:
    _validate_observation_literals(observation)
    for name in _EVIDENCE_NAMES:
        if observation["artifacts"][name] != _artifact_mapping(artifacts[name]):
            raise ProbeError(f"observation artifact {name} differs")
    process = _parse_process_result(artifacts[_PROCESS_RESULT_NAME].content)
    try:
        writeout = _parse_writeout(artifacts[_WRITEOUT_NAME].content)
        writeout_valid = True
    except ProbeError:
        writeout = None
        writeout_valid = False
    expected = _build_observation(
        observation["execution"]["approved_git_commit"],
        process,
        writeout,
        writeout_valid,
        artifacts,
    )
    if observation != expected:
        raise ProbeError("probe observation differs from replayed evidence")


def _recovery_pair_is_bound(stage_fd: int, held_final_fd: int) -> None:
    temp_fd = canonical_final_fd = -1
    try:
        temp_fd = os.open(
            _OBSERVATION_TEMP, _regular_read_flags(), dir_fd=stage_fd
        )
        canonical_final_fd = os.open(
            _OBSERVATION_NAME, _regular_read_flags(), dir_fd=stage_fd
        )
        held = _fingerprint_fd(held_final_fd)
        temp = _fingerprint_fd(temp_fd)
        canonical = _fingerprint_fd(canonical_final_fd)
        if (
            held != temp
            or held != canonical
            or held.nlink != 2
            or not stat.S_ISREG(held.mode)
            or stat.S_IMODE(held.mode) != 0o600
            or held.uid != os.geteuid()
        ):
            raise ProbeError("recovery observation pair differs")
    finally:
        active = sys.exc_info()[1]
        owned = (
            ("recovery-final", canonical_final_fd),
            ("recovery-temp", temp_fd),
        )
        canonical_final_fd = temp_fd = -1
        _close_fds_best_effort(owned, active)


def _publication_namespace_is_incomplete(stage_fd: int) -> bool:
    temp = _entry_fingerprint(stage_fd, _OBSERVATION_TEMP)
    final = _entry_fingerprint(stage_fd, _OBSERVATION_NAME)
    if temp is not None or final is None:
        return True
    return (
        not stat.S_ISREG(final.mode)
        or stat.S_IMODE(final.mode) != 0o600
        or final.uid != os.geteuid()
        or final.nlink != 1
    )


def _same_inode(left: _Fingerprint, right: _Fingerprint) -> bool:
    return (left.device, left.inode) == (right.device, right.inode)


def _canonical_entry_maps_to_fd(stage_fd: int, name: str, held_fd: int) -> bool:
    canonical = _entry_fingerprint(stage_fd, name)
    return canonical is not None and _same_inode(canonical, _fingerprint_fd(held_fd))


def _durably_confirm_recovery_pair(stage_fd: int, held_final_fd: int) -> bool:
    os.fsync(held_final_fd)
    os.fsync(stage_fd)
    _recovery_pair_is_bound(stage_fd, held_final_fd)
    return _publication_namespace_is_incomplete(stage_fd)


def _recovery_marker_is_bound(stage_fd: int, held_marker_fd: int) -> None:
    canonical_fd = -1
    try:
        canonical_fd = os.open(
            _OBSERVATION_TEMP, _regular_read_flags(), dir_fd=stage_fd
        )
        held = _fingerprint_fd(held_marker_fd)
        canonical = _fingerprint_fd(canonical_fd)
        if (
            held != canonical
            or not stat.S_ISREG(held.mode)
            or stat.S_IMODE(held.mode) != 0o600
            or held.uid != os.geteuid()
            or held.nlink != 1
            or _bounded_pread(canonical_fd, _OBSERVATION_LIMIT) != b"INCOMPLETE\n"
        ):
            raise ProbeError("recovery observation marker differs")
    finally:
        active = sys.exc_info()[1]
        owned = canonical_fd
        canonical_fd = -1
        _close_fds_best_effort((("recovery-marker-canonical", owned),), active)


def _durably_create_recovery_marker(stage_fd: int) -> bool:
    marker_fd = -1
    try:
        marker_fd = _create_evidence_fd(stage_fd, _OBSERVATION_TEMP)
        _write_all(marker_fd, b"INCOMPLETE\n")
        os.fsync(marker_fd)
        os.fsync(stage_fd)
        _recovery_marker_is_bound(stage_fd, marker_fd)
        return _publication_namespace_is_incomplete(stage_fd)
    finally:
        active = sys.exc_info()[1]
        owned = marker_fd
        marker_fd = -1
        _close_fds_best_effort((("recovery-marker", owned),), active)


def _durably_confirm_final_absent(stage_fd: int) -> bool:
    os.fsync(stage_fd)
    return (
        _entry_fingerprint(stage_fd, _OBSERVATION_NAME) is None
        and _publication_namespace_is_incomplete(stage_fd)
    )


def _open_bound_final_writer(stage_fd: int, held_final_fd: int) -> int:
    writer_fd = os.open(
        _OBSERVATION_NAME,
        os.O_WRONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=stage_fd,
    )
    try:
        if not _same_inode(
            _fingerprint_fd(writer_fd), _fingerprint_fd(held_final_fd)
        ):
            raise ProbeError("recovery writer binding differs")
        return writer_fd
    except BaseException:
        active = sys.exc_info()[1]
        owned = writer_fd
        writer_fd = -1
        _close_fds_best_effort((("recovery-writer", owned),), active)
        raise


def _durably_invalidate_final_content(
    stage_fd: int, held_final_fd: int, writer_fd: int
) -> bool:
    if not _canonical_entry_maps_to_fd(
        stage_fd, _OBSERVATION_NAME, held_final_fd
    ):
        raise ProbeError("recovery final binding differs before truncate")
    os.ftruncate(writer_fd, 0)
    _write_all(writer_fd, b"INCOMPLETE\n")
    os.fsync(writer_fd)
    os.fsync(stage_fd)
    return (
        _canonical_entry_maps_to_fd(stage_fd, _OBSERVATION_NAME, held_final_fd)
        and _bounded_pread(held_final_fd, _OBSERVATION_LIMIT) == b"INCOMPLETE\n"
    )


def _durably_invalidate_final_mode(stage_fd: int, held_final_fd: int) -> bool:
    if not _canonical_entry_maps_to_fd(
        stage_fd, _OBSERVATION_NAME, held_final_fd
    ):
        raise ProbeError("recovery final binding differs before chmod")
    os.fchmod(held_final_fd, 0o000)
    os.fsync(held_final_fd)
    os.fsync(stage_fd)
    canonical = _entry_fingerprint(stage_fd, _OBSERVATION_NAME)
    return (
        canonical is not None
        and _same_inode(canonical, _fingerprint_fd(held_final_fd))
        and stat.S_IMODE(canonical.mode) == 0o000
        and _publication_namespace_is_incomplete(stage_fd)
    )


def _durably_emergency_invalidate_final(
    stage_fd: int, held_final_fd: int, writer_fd: int
) -> bool:
    if not _canonical_entry_maps_to_fd(
        stage_fd, _OBSERVATION_NAME, held_final_fd
    ):
        raise ProbeError("recovery final binding differs before emergency write")
    if os.pwrite(writer_fd, b"!", 0) != 1:
        raise ProbeError("recovery emergency write was short")
    os.fsync(writer_fd)
    os.fsync(stage_fd)
    return (
        _canonical_entry_maps_to_fd(stage_fd, _OBSERVATION_NAME, held_final_fd)
        and _bounded_pread(held_final_fd, _OBSERVATION_LIMIT).startswith(b"!")
    )


def _fail_closed_observation_publication(
    stage_fd: int, held_final_fd: int = -1
) -> bool:
    owned_final_fd = -1
    writer_fd = -1
    final_fd = held_final_fd
    try:
        if final_fd < 0:
            try:
                owned_final_fd = os.open(
                    _OBSERVATION_NAME, _regular_read_flags(), dir_fd=stage_fd
                )
                final_fd = owned_final_fd
            except (FileNotFoundError, PermissionError, OSError):
                final_fd = -1

        # A visible invalid marker is insufficient: every successful branch
        # syncs the affected file (when one exists), syncs the stage directory,
        # and then revalidates the terminal namespace state.
        if final_fd >= 0:
            try:
                if _entry_fingerprint(stage_fd, _OBSERVATION_TEMP) is None:
                    os.link(
                        _OBSERVATION_NAME,
                        _OBSERVATION_TEMP,
                        src_dir_fd=stage_fd,
                        dst_dir_fd=stage_fd,
                        follow_symlinks=False,
                    )
                if _durably_confirm_recovery_pair(stage_fd, final_fd):
                    return True
            except (ProbeError, FileNotFoundError, PermissionError, OSError):
                pass

        try:
            if _durably_create_recovery_marker(stage_fd):
                return True
        except (ProbeError, FileExistsError, FileNotFoundError, PermissionError, OSError):
            pass

        if final_fd >= 0:
            try:
                if _canonical_entry_maps_to_fd(
                    stage_fd, _OBSERVATION_NAME, final_fd
                ):
                    os.unlink(_OBSERVATION_NAME, dir_fd=stage_fd)
                    if _durably_confirm_final_absent(stage_fd):
                        return True
            except (ProbeError, FileNotFoundError, PermissionError, OSError):
                pass

        # If unlink became live but its directory sync failed, retrying the
        # durable absent-state proof is safe and does not rely on that failure.
        try:
            if _durably_confirm_final_absent(stage_fd):
                return True
        except (ProbeError, FileNotFoundError, PermissionError, OSError):
            pass

        if final_fd >= 0:
            try:
                writer_fd = _open_bound_final_writer(stage_fd, final_fd)
            except (ProbeError, FileNotFoundError, PermissionError, OSError):
                pass

        if final_fd >= 0 and writer_fd >= 0:
            try:
                if _durably_invalidate_final_content(
                    stage_fd, final_fd, writer_fd
                ):
                    return True
            except (ProbeError, FileNotFoundError, PermissionError, OSError):
                pass

        if final_fd >= 0:
            try:
                if _durably_invalidate_final_mode(stage_fd, final_fd):
                    return True
            except (ProbeError, FileNotFoundError, PermissionError, OSError):
                pass

        # Last live-state emergency uses the already-bound writer, so it still
        # works after a partial chmod.  A write or fsync failure may leave the
        # current verifier seeing INCOMPLETE, but it must not be called durable.
        if final_fd >= 0 and writer_fd >= 0:
            try:
                if _durably_emergency_invalidate_final(
                    stage_fd, final_fd, writer_fd
                ):
                    return True
            except (ProbeError, FileNotFoundError, PermissionError, OSError):
                pass

        # False means durability is unconfirmed.  Callers must stop: an offline
        # result from this namespace cannot authorize continued execution until
        # the stage is manually isolated and recovered.  No filesystem can
        # promise persistence when every available mutation or fsync fails.
        return False
    finally:
        active = sys.exc_info()[1]
        owned = (
            ("recovery-writer", writer_fd),
            ("owned-recovery-final", owned_final_fd),
        )
        writer_fd = owned_final_fd = -1
        _close_fds_best_effort(owned, active)


def _publish_observation(stage_fd: int, observation: Mapping[str, Any]) -> None:
    content = _canonical_json_bytes(observation)
    if len(content) > _OBSERVATION_LIMIT:
        raise ProbeError("probe observation exceeds its limit")
    temp_fd = final_fd = -1
    try:
        temp_fd = _create_evidence_fd(stage_fd, _OBSERVATION_TEMP)
        _write_all(temp_fd, content)
        os.fsync(temp_fd)
        temp_facts = _stable_read_hash(
            temp_fd, _OBSERVATION_TEMP, _OBSERVATION_LIMIT
        )
        _assert_canonical_file_binding(stage_fd, temp_facts, _OBSERVATION_LIMIT)
        _strict_json_object(temp_facts.content, "probe observation temporary")
        os.link(
            _OBSERVATION_TEMP,
            _OBSERVATION_NAME,
            src_dir_fd=stage_fd,
            dst_dir_fd=stage_fd,
            follow_symlinks=False,
        )
        os.fsync(stage_fd)
        final_fd = os.open(_OBSERVATION_NAME, _regular_read_flags(), dir_fd=stage_fd)
        pair_temp = _fingerprint_fd(temp_fd)
        pair_final = _fingerprint_fd(final_fd)
        if (
            (pair_temp.device, pair_temp.inode) != (pair_final.device, pair_final.inode)
            or pair_temp != pair_final
            or pair_temp.nlink != 2
            or _bounded_pread(final_fd, _OBSERVATION_LIMIT) != content
        ):
            raise ProbeError("observation publication pair differs")
        os.unlink(_OBSERVATION_TEMP, dir_fd=stage_fd)
        os.fsync(stage_fd)
        final_facts = _stable_read_hash(
            final_fd, _OBSERVATION_NAME, _OBSERVATION_LIMIT
        )
        if final_facts.content != content or final_facts.fingerprint.nlink != 1:
            raise ProbeError("published observation differs")
        _assert_canonical_file_binding(stage_fd, final_facts, _OBSERVATION_LIMIT)
    except BaseException as publication_error:
        if temp_fd >= 0 or final_fd >= 0:
            recovery_fd = final_fd if final_fd >= 0 else temp_fd
            try:
                fail_closed = _fail_closed_observation_publication(
                    stage_fd, recovery_fd
                )
            except BaseException as recovery_error:
                raise ProbeError(
                    "publication fail-close unconfirmed"
                ) from recovery_error
            if fail_closed is not True:
                raise ProbeError(
                    "publication fail-close unconfirmed"
                ) from publication_error
        raise
    finally:
        active = sys.exc_info()[1]
        owned = (("observation-final", final_fd), ("observation-temp", temp_fd))
        final_fd = temp_fd = -1
        _close_fds_best_effort(owned, active)


def _prepare_stage(
    layout: _Layout,
) -> tuple[list[int], list[int], int]:
    absolute_chain: list[int] = []
    parent_chain: list[int] = []
    stage_fd = -1
    try:
        absolute_chain = _open_absolute_chain(layout.project_root)
        project_fd = absolute_chain[-1]
        _require_owned_directory(project_fd, "project root")
        parent_chain = _open_or_create_relative_chain(
            project_fd, layout.parent_relative_path
        )
        parent_fd = parent_chain[-1]
        _require_absent(parent_fd, layout.formal_leaf, "formal MuSiQue revision")
        _require_absent(parent_fd, layout.stage_leaf, "MuSiQue probe stage")
        stage_fd = _mkdir_exclusive_private(parent_fd, layout.stage_leaf)
        return absolute_chain, parent_chain, stage_fd
    except BaseException:
        active = sys.exc_info()[1]
        owned: list[tuple[str, int]] = [("stage", stage_fd)]
        owned.extend(("parent", fd) for fd in reversed(parent_chain))
        owned.extend(("absolute", fd) for fd in reversed(absolute_chain))
        stage_fd = -1
        parent_chain.clear()
        absolute_chain.clear()
        _close_fds_best_effort(owned, active)
        raise


def _terminal_binding(
    layout: _Layout,
    absolute_chain: Sequence[int],
    absolute_baselines: Sequence[_Fingerprint],
    parent_chain: Sequence[int],
    parent_baselines: Sequence[_Fingerprint],
    stage_fd: int,
    stage_baseline: _Fingerprint,
) -> None:
    parent_fd = parent_chain[-1]
    _require_absent(parent_fd, layout.formal_leaf, "formal MuSiQue revision")
    _assert_absolute_chain(layout.project_root, absolute_chain, absolute_baselines)
    _assert_relative_chain(
        absolute_chain[-1],
        layout.parent_relative_path,
        parent_chain,
        parent_baselines,
    )
    _assert_stage_binding(parent_fd, layout.stage_leaf, stage_fd, stage_baseline)
    _scan_stage(stage_fd, allow_incomplete=False)


def _read_observation(stage_fd: int) -> Mapping[str, Any]:
    fd = -1
    try:
        fd = _open_evidence_fd(stage_fd, _OBSERVATION_NAME)
        facts = _stable_read_hash(fd, _OBSERVATION_NAME, _OBSERVATION_LIMIT)
        _assert_canonical_file_binding(stage_fd, facts, _OBSERVATION_LIMIT)
        return _strict_json_object(facts.content, "probe observation")
    finally:
        active = sys.exc_info()[1]
        owned = fd
        fd = -1
        _close_fds_best_effort((("observation", owned),), active)


def _execute_layout(
    layout: _Layout,
    approved_commit: str,
    git_checker: Callable[[str], str],
    process_runner: Callable[[int, int, int], _ProcessResult],
) -> ProbeReport:
    approved = _validate_commit(approved_commit)
    if git_checker(approved) != approved:
        raise ProbeError("git checker returned a different commit")
    absolute_chain: list[int] = []
    parent_chain: list[int] = []
    stage_fd = -1
    evidence_fds: dict[str, int] = {}
    observation_published = False
    try:
        absolute_chain, parent_chain, stage_fd = _prepare_stage(layout)
        parent_fd = parent_chain[-1]
        for name in _EVIDENCE_NAMES:
            evidence_fds[name] = _create_evidence_fd(stage_fd, name)
        process = process_runner(
            evidence_fds[_BODY_NAME],
            evidence_fds[_WRITEOUT_NAME],
            evidence_fds[_STDERR_NAME],
        )
        _write_process_result(evidence_fds[_PROCESS_RESULT_NAME], process)
        artifacts = _freeze_evidence(stage_fd, evidence_fds, sync=True)
        try:
            writeout = _parse_writeout(artifacts[_WRITEOUT_NAME].content)
            writeout_valid = True
        except ProbeError:
            writeout = None
            writeout_valid = False
        _require_absent(parent_fd, layout.formal_leaf, "formal MuSiQue revision")
        if git_checker(approved) != approved:
            raise ProbeError("git checker changed before observation publication")
        absolute_baselines = _binding_fingerprints(absolute_chain)
        parent_baselines = _binding_fingerprints(parent_chain)
        observation = _build_observation(
            approved, process, writeout, writeout_valid, artifacts
        )
        _validate_observation_against_artifacts(observation, artifacts)
        _publish_observation(stage_fd, observation)
        observation_published = True
        stage_baseline = _fingerprint_fd(stage_fd)
        _terminal_binding(
            layout,
            absolute_chain,
            absolute_baselines,
            parent_chain,
            parent_baselines,
            stage_fd,
            stage_baseline,
        )
        report = _verify_layout(layout)
        if report.observation != observation:
            raise ProbeError("offline verifier differs after publication")
        return report
    except BaseException as terminal_error:
        if observation_published:
            if stage_fd < 0:
                raise ProbeError(
                    "terminal fail-close unconfirmed"
                ) from terminal_error
            try:
                fail_closed = _fail_closed_observation_publication(stage_fd)
            except BaseException as recovery_error:
                raise ProbeError(
                    "terminal fail-close unconfirmed"
                ) from recovery_error
            if fail_closed is not True:
                raise ProbeError(
                    "terminal fail-close unconfirmed"
                ) from terminal_error
        raise
    finally:
        active = sys.exc_info()[1]
        owned: list[tuple[str, int]] = [
            (name, evidence_fds[name])
            for name in reversed(_EVIDENCE_NAMES)
            if name in evidence_fds
        ]
        owned.append(("stage", stage_fd))
        owned.extend(("parent", fd) for fd in reversed(parent_chain))
        owned.extend(("absolute", fd) for fd in reversed(absolute_chain))
        evidence_fds.clear()
        stage_fd = -1
        parent_chain.clear()
        absolute_chain.clear()
        _close_fds_best_effort(owned, active)


def _incomplete(reason: str) -> ProbeReport:
    return ProbeReport(ProbeStatus.INCOMPLETE, reason, None)


def _verify_layout_strict(layout: _Layout) -> ProbeReport:
    absolute_chain: list[int] = []
    parent_chain: list[int] = []
    stage_fd = -1
    evidence_fds: dict[str, int] = {}
    try:
        absolute_chain = _open_absolute_chain(layout.project_root)
        project_fd = absolute_chain[-1]
        _require_owned_directory(project_fd, "project root")
        try:
            parent_chain = _open_relative_chain(
                project_fd, layout.parent_relative_path
            )
        except FileNotFoundError:
            return _incomplete("STAGE_PARENT_ABSENT")
        parent_fd = parent_chain[-1]
        if _entry_fingerprint(parent_fd, layout.formal_leaf) is not None:
            return _incomplete("FORMAL_REVISION_PRESENT")
        if _entry_fingerprint(parent_fd, layout.stage_leaf) is None:
            return _incomplete("STAGE_ABSENT")
        stage_fd = _open_stage(parent_fd, layout.stage_leaf)
        stage_entries = _scan_stage(stage_fd, allow_incomplete=True)
        final_present = _OBSERVATION_NAME in stage_entries
        temp_present = _OBSERVATION_TEMP in stage_entries
        if not final_present:
            return _incomplete("OBSERVATION_ABSENT")
        if temp_present:
            return _incomplete("OBSERVATION_PUBLICATION_INCOMPLETE")
        if set(stage_entries) != set(_FINAL_NAMES):
            return _incomplete("COMPLETED_FILE_SET_DIFFERS")
        for name in _EVIDENCE_NAMES:
            evidence_fds[name] = _open_evidence_fd(stage_fd, name)
        artifacts = _freeze_evidence(stage_fd, evidence_fds, sync=False)
        observation = _read_observation(stage_fd)
        _validate_observation_against_artifacts(observation, artifacts)
        absolute_baselines = _binding_fingerprints(absolute_chain)
        parent_baselines = _binding_fingerprints(parent_chain)
        stage_baseline = _fingerprint_fd(stage_fd)
        _terminal_binding(
            layout,
            absolute_chain,
            absolute_baselines,
            parent_chain,
            parent_baselines,
            stage_fd,
            stage_baseline,
        )
        status = ProbeStatus(observation["status"])
        return ProbeReport(status, observation["reason_code"], observation)
    finally:
        active = sys.exc_info()[1]
        owned: list[tuple[str, int]] = [
            (name, evidence_fds[name])
            for name in reversed(_EVIDENCE_NAMES)
            if name in evidence_fds
        ]
        owned.append(("stage", stage_fd))
        owned.extend(("parent", fd) for fd in reversed(parent_chain))
        owned.extend(("absolute", fd) for fd in reversed(absolute_chain))
        evidence_fds.clear()
        stage_fd = -1
        parent_chain.clear()
        absolute_chain.clear()
        _close_fds_best_effort(owned, active)


def _verify_layout(layout: _Layout) -> ProbeReport:
    try:
        return _verify_layout_strict(layout)
    except (ProbeError, FileExistsError, FileNotFoundError, PermissionError, OSError):
        return _incomplete("OFFLINE_INTEGRITY_FAILURE")


def execute(approved_commit: str) -> ProbeReport:
    """Execute the fixed production probe after an external execution approval."""

    return _execute_layout(
        _PRODUCTION_LAYOUT,
        approved_commit,
        _git_clean_head,
        _run_probe_process,
    )


def verify() -> ProbeReport:
    """Verify the fixed probe stage without Git, subprocesses, or network access."""

    return _verify_layout(_PRODUCTION_LAYOUT)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kairos.musique_probe")
    commands = parser.add_subparsers(dest="command", required=True)
    execute_parser = commands.add_parser("execute")
    execute_parser.add_argument("--approved-commit", required=True)
    commands.add_parser("verify")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "execute":
            report = execute(arguments.approved_commit)
        else:
            report = verify()
    except (
        ProbeError,
        FileExistsError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ) as error:
        print(f"MuSiQue probe failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(_canonical_json_bytes(report.as_mapping()).decode("utf-8"), end="")
    if report.status is ProbeStatus.PROBE_OK:
        return 0
    if report.status is ProbeStatus.BLOCKED:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProbeError",
    "ProbeReport",
    "ProbeStatus",
    "execute",
    "main",
    "verify",
]
