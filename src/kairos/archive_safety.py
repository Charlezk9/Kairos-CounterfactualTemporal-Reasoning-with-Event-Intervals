"""Strict inspection and extraction for fixed ZIP, TAR, and TAR.GZ files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import gzip
import hashlib
import ntpath
import os
from pathlib import Path
import stat
import struct
import tarfile
from typing import BinaryIO, Optional, Sequence, Tuple
import unicodedata
import zipfile


_CHUNK_SIZE = 1024 * 1024
_DEFAULT_METADATA_BYTES = 64 * 1024 * 1024
_MAX_PATH_BYTES = 4096
_MAX_COMPONENT_BYTES = 255
_ZIP_EOCD = b"PK\x05\x06"
_ZIP_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_TAR_METADATA_TYPES = {b"x", b"g", b"L", b"K"}


class ArchiveSafetyError(ValueError):
    """Raised when an archive fails a safety or integrity invariant."""


class ArchiveFormat(str, Enum):
    ZIP = "zip"
    TAR = "tar"
    TAR_GZ = "tar.gz"


class MemberKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class MemberSummary:
    path: str
    kind: MemberKind
    declared_size: int
    sha256: Optional[str]


@dataclass(frozen=True)
class ArchiveInspection:
    format: ArchiveFormat
    sha256: str
    member_count: int
    total_declared_bytes: int
    members: Tuple[MemberSummary, ...]


@dataclass(frozen=True)
class _MemberSpec:
    source: object
    path: str
    kind: MemberKind
    declared_size: int


@dataclass(frozen=True)
class _FileFingerprint:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _fingerprint(handle: BinaryIO) -> _FileFingerprint:
    status = os.fstat(handle.fileno())
    return _FileFingerprint(
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _validate_limits(max_members: int, max_total_bytes: int, max_metadata_bytes: int) -> None:
    if isinstance(max_members, bool) or not isinstance(max_members, int) or max_members < 1:
        raise ValueError("max_members must be a positive integer")
    for value, name in (
        (max_total_bytes, "max_total_bytes"),
        (max_metadata_bytes, "max_metadata_bytes"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")


def _validate_expected_sha256(expected_sha256: Optional[str]) -> None:
    if expected_sha256 is None:
        return
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal characters")


def _absolute_components(path: str | Path, *, leaf_required: bool) -> tuple[list[str], str]:
    raw = os.fspath(path)
    if not isinstance(raw, str):
        raise TypeError("filesystem paths must be strings")
    if not os.path.isabs(raw):
        raise ArchiveSafetyError("filesystem path must be absolute")
    components = raw.split("/")[1:]
    if components and components[-1] == "":
        components.pop()
    if any(component in {"", ".", ".."} for component in components):
        raise ArchiveSafetyError("filesystem path contains an unsafe component")
    if leaf_required and not components:
        raise ArchiveSafetyError("filesystem path must name a leaf")
    return components[:-1], components[-1] if components else ""


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_absolute_directory_components(components: Sequence[str]) -> int:
    descriptor = os.open("/", _directory_flags())
    try:
        for component in components:
            next_descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_source_file(path: str | Path) -> BinaryIO:
    parents, leaf = _absolute_components(path, leaf_required=True)
    try:
        parent_descriptor = _open_absolute_directory_components(parents)
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(leaf, flags, dir_fd=parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError as error:
        raise ArchiveSafetyError(f"cannot safely open archive path: {error}") from error
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ArchiveSafetyError("archive source must be a regular file")
    return os.fdopen(descriptor, "rb", closefd=True)


def _open_destination_parent(path: str | Path) -> tuple[int, str]:
    parents, leaf = _absolute_components(path, leaf_required=True)
    try:
        return _open_absolute_directory_components(parents), leaf
    except FileNotFoundError as error:
        raise FileNotFoundError(f"destination parent does not exist: {path}") from error
    except OSError as error:
        raise ArchiveSafetyError(f"cannot safely open destination parent: {error}") from error


def normalize_member_path(name: str, *, is_directory: bool) -> str:
    """Return a safe canonical POSIX member path or raise."""

    if not isinstance(name, str):
        raise ArchiveSafetyError("archive member name must be a string")
    if not name:
        raise ArchiveSafetyError("archive member path is empty")
    if "\x00" in name:
        raise ArchiveSafetyError("archive member path contains NUL")
    if "\\" in name:
        raise ArchiveSafetyError("archive member path contains a backslash")
    if name.startswith("/") or ntpath.isabs(name):
        raise ArchiveSafetyError("archive member path is absolute")
    drive, _ = ntpath.splitdrive(name)
    if drive:
        raise ArchiveSafetyError("archive member path contains a Windows drive")

    normalized = unicodedata.normalize("NFC", name)
    if is_directory and normalized.endswith("/"):
        normalized = normalized[:-1]
    if not normalized:
        raise ArchiveSafetyError("archive member path resolves to an empty path")
    components = normalized.split("/")
    if any(component == "" for component in components):
        raise ArchiveSafetyError("archive member path contains an empty component")
    if any(component == "." for component in components):
        raise ArchiveSafetyError("archive member path contains a dot component")
    if any(component == ".." for component in components):
        raise ArchiveSafetyError("archive member path contains a parent component")
    encoded = normalized.encode("utf-8")
    if len(encoded) > _MAX_PATH_BYTES:
        raise ArchiveSafetyError("archive member path exceeds UTF-8 byte limit")
    if any(len(component.encode("utf-8")) > _MAX_COMPONENT_BYTES for component in components):
        raise ArchiveSafetyError("archive member component exceeds UTF-8 byte limit")
    return "/".join(components)


def _validate_path_set(specs: Sequence[_MemberSpec]) -> None:
    explicit_paths: set[str] = set()
    file_paths: set[str] = set()
    ancestor_prefixes: set[str] = set()
    for spec in specs:
        path = spec.path
        if path in explicit_paths:
            raise ArchiveSafetyError(f"duplicate normalized member path: {path}")
        components = path.split("/")
        ancestors = ["/".join(components[:index]) for index in range(1, len(components))]
        blocking_file = next((ancestor for ancestor in ancestors if ancestor in file_paths), None)
        if blocking_file is not None:
            raise ArchiveSafetyError(
                f"file/directory prefix conflict: file {blocking_file} prefixes {path}"
            )
        if spec.kind is MemberKind.FILE and path in ancestor_prefixes:
            raise ArchiveSafetyError(
                f"file/directory prefix conflict: file {path} has archived descendants"
            )
        explicit_paths.add(path)
        ancestor_prefixes.update(ancestors)
        if spec.kind is MemberKind.FILE:
            file_paths.add(path)


def _archive_sha256(handle: BinaryIO) -> str:
    handle.seek(0)
    digest = hashlib.sha256()
    while True:
        chunk = handle.read(_CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


def _stable_sha256(handle: BinaryIO, baseline: _FileFingerprint) -> str:
    if _fingerprint(handle) != baseline:
        raise ArchiveSafetyError("archive file metadata changed")
    digest = _archive_sha256(handle)
    if _fingerprint(handle) != baseline:
        raise ArchiveSafetyError("archive file changed while hashing")
    return digest


def _zip_eocd_preflight(
    handle: BinaryIO, *, max_members: int, max_metadata_bytes: int
) -> None:
    file_size = _fingerprint(handle).size
    tail_size = min(file_size, 22 + 65_535)
    handle.seek(file_size - tail_size)
    tail = handle.read(tail_size)
    search_end = len(tail)
    parsed = None
    while True:
        position = tail.rfind(_ZIP_EOCD, 0, search_end)
        if position < 0:
            break
        if position + 22 <= len(tail):
            fields = struct.unpack_from("<4s4H2LH", tail, position)
            comment_length = fields[-1]
            if position + 22 + comment_length == len(tail):
                parsed = (position, fields)
                break
        search_end = position
    if parsed is None:
        raise ArchiveSafetyError("ZIP end-of-central-directory record is missing or malformed")
    position, fields = parsed
    _, disk_number, central_disk, disk_entries, entry_count, central_size, central_offset, comment = fields
    if disk_number != 0 or central_disk != 0 or disk_entries != entry_count:
        raise ArchiveSafetyError("multi-disk ZIP archives are forbidden")
    if entry_count == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        raise ArchiveSafetyError("ZIP64 archives are not supported")
    if entry_count > max_members:
        raise ArchiveSafetyError(
            f"archive has {entry_count} members, exceeding limit {max_members}"
        )
    if central_size + 22 + comment > max_metadata_bytes:
        raise ArchiveSafetyError("ZIP central-directory metadata exceeds max_metadata_bytes")
    eocd_offset = file_size - tail_size + position
    if central_offset > file_size or central_size > file_size - central_offset:
        raise ArchiveSafetyError("ZIP central-directory range is outside the file")
    if central_offset + central_size != eocd_offset:
        raise ArchiveSafetyError("ZIP central-directory must end exactly at the EOCD")
    _zip_central_directory_preflight(
        handle,
        central_offset=central_offset,
        central_size=central_size,
        expected_entries=entry_count,
        max_members=max_members,
        file_size=file_size,
    )
    handle.seek(0)


def _zip_extra_fields(extra: bytes, context: str) -> None:
    position = 0
    while position < len(extra):
        if len(extra) - position < 4:
            raise ArchiveSafetyError(f"truncated ZIP extra field in {context}")
        field_id, field_size = struct.unpack_from("<HH", extra, position)
        position += 4
        if field_size > len(extra) - position:
            raise ArchiveSafetyError(f"ZIP extra field exceeds its boundary in {context}")
        if field_id == 0x0001:
            raise ArchiveSafetyError(f"ZIP64 extra field is forbidden in {context}")
        position += field_size
    if position != len(extra):
        raise ArchiveSafetyError(f"ZIP extra fields do not exhaust their boundary in {context}")


def _zip_local_header_preflight(
    handle: BinaryIO,
    *,
    local_offset: int,
    central_offset: int,
    file_size: int,
    central_filename: bytes,
    central_version_needed: int,
    central_flags: int,
    central_compression: int,
    central_crc32: int,
    central_compressed_size: int,
    central_uncompressed_size: int,
) -> None:
    central_cursor = handle.tell()
    try:
        if local_offset > file_size or 30 > file_size - local_offset:
            raise ArchiveSafetyError("ZIP local header range is outside the file")
        if local_offset + 30 > central_offset:
            raise ArchiveSafetyError("ZIP local header overlaps the central directory")
        handle.seek(local_offset)
        fixed = handle.read(30)
        if len(fixed) != 30:
            raise ArchiveSafetyError("truncated ZIP local header")
        (
            signature,
            version_needed,
            flags,
            compression,
            _modified_time,
            _modified_date,
            crc32,
            compressed_size,
            uncompressed_size,
            filename_length,
            extra_length,
        ) = struct.unpack("<4s5H3L2H", fixed)
        if signature != b"PK\x03\x04":
            raise ArchiveSafetyError("ZIP local header signature is invalid")
        if flags & 0x1:
            raise ArchiveSafetyError("encrypted ZIP local header is forbidden")
        if flags & 0x8:
            raise ArchiveSafetyError("ZIP data descriptors are forbidden")
        if compressed_size == 0xFFFFFFFF or uncompressed_size == 0xFFFFFFFF:
            raise ArchiveSafetyError("ZIP64 local size sentinel is forbidden")
        comparisons = (
            ("version-needed", version_needed, central_version_needed),
            ("flags", flags, central_flags),
            ("compression", compression, central_compression),
            ("CRC32", crc32, central_crc32),
            ("compressed size", compressed_size, central_compressed_size),
            ("uncompressed size", uncompressed_size, central_uncompressed_size),
        )
        for field_name, local_value, central_value in comparisons:
            if local_value != central_value:
                raise ArchiveSafetyError(
                    f"ZIP local/central {field_name} mismatch"
                )
        variable_size = filename_length + extra_length
        variable_start = local_offset + 30
        if variable_start > file_size or variable_size > file_size - variable_start:
            raise ArchiveSafetyError("ZIP local name/extra range is outside the file")
        if variable_start + variable_size > central_offset:
            raise ArchiveSafetyError("ZIP local name/extra overlaps the central directory")
        filename = handle.read(filename_length)
        extra = handle.read(extra_length)
        if len(filename) != filename_length or len(extra) != extra_length:
            raise ArchiveSafetyError("truncated ZIP local name or extra field")
        if filename != central_filename:
            raise ArchiveSafetyError("ZIP local and central filenames differ")
        _zip_extra_fields(extra, "local header")
    finally:
        handle.seek(central_cursor)


def _zip_central_directory_preflight(
    handle: BinaryIO,
    *,
    central_offset: int,
    central_size: int,
    expected_entries: int,
    max_members: int,
    file_size: int,
) -> None:
    central_end = central_offset + central_size
    handle.seek(central_offset)
    actual_entries = 0
    while handle.tell() < central_end:
        entry_start = handle.tell()
        if central_end - entry_start < 46:
            raise ArchiveSafetyError("truncated ZIP central-directory fixed header")
        fixed = handle.read(46)
        (
            signature,
            _version_made,
            version_needed,
            flags,
            compression,
            _modified_time,
            _modified_date,
            crc32,
            compressed_size,
            uncompressed_size,
            filename_length,
            extra_length,
            comment_length,
            disk_start,
            _internal_attributes,
            _external_attributes,
            local_header_offset,
        ) = struct.unpack("<4s6H3L5H2L", fixed)
        if signature != b"PK\x01\x02":
            raise ArchiveSafetyError("ZIP central-directory entry signature is invalid")
        actual_entries += 1
        if actual_entries > max_members:
            raise ArchiveSafetyError(f"archive has more than {max_members} members")
        if disk_start == 0xFFFF:
            raise ArchiveSafetyError("ZIP64 disk sentinel is forbidden")
        if disk_start != 0:
            raise ArchiveSafetyError("multi-disk ZIP member is forbidden")
        if flags & 0x1:
            raise ArchiveSafetyError("encrypted ZIP central-directory entry is forbidden")
        if flags & 0x8:
            raise ArchiveSafetyError("ZIP data descriptors are forbidden")
        if (
            compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF
            or local_header_offset == 0xFFFFFFFF
        ):
            raise ArchiveSafetyError("ZIP64 central-directory sentinel is forbidden")
        variable_size = filename_length + extra_length + comment_length
        variable_start = entry_start + 46
        if variable_size > central_end - variable_start:
            raise ArchiveSafetyError("ZIP central-directory variable fields exceed boundary")
        filename = handle.read(filename_length)
        extra = handle.read(extra_length)
        comment = handle.read(comment_length)
        if (
            len(filename) != filename_length
            or len(extra) != extra_length
            or len(comment) != comment_length
        ):
            raise ArchiveSafetyError("truncated ZIP central-directory variable fields")
        _zip_extra_fields(extra, "central directory")
        _zip_local_header_preflight(
            handle,
            local_offset=local_header_offset,
            central_offset=central_offset,
            file_size=file_size,
            central_filename=filename,
            central_version_needed=version_needed,
            central_flags=flags,
            central_compression=compression,
            central_crc32=crc32,
            central_compressed_size=compressed_size,
            central_uncompressed_size=uncompressed_size,
        )
        expected_cursor = variable_start + variable_size
        if handle.tell() != expected_cursor:
            raise ArchiveSafetyError("ZIP central-directory cursor was not restored")
    if handle.tell() != central_end:
        raise ArchiveSafetyError("ZIP central-directory bytes were not exactly exhausted")
    if actual_entries != expected_entries:
        raise ArchiveSafetyError(
            f"ZIP EOCD entry count mismatch: expected={expected_entries}, actual={actual_entries}"
        )


def _tar_number(field: bytes, name: str) -> int:
    if field and field[0] & 0x80:
        value = int.from_bytes(field, "big", signed=False) & ((1 << (8 * len(field) - 1)) - 1)
        return value
    stripped = field.rstrip(b"\x00 ").lstrip(b" ")
    if not stripped:
        return 0
    try:
        return int(stripped, 8)
    except ValueError as error:
        raise ArchiveSafetyError(f"invalid TAR {name} field") from error


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(min(_CHUNK_SIZE, size - len(chunks)))
        if not chunk:
            raise ArchiveSafetyError("truncated TAR archive")
        chunks.extend(chunk)
    return bytes(chunks)


def _discard_exact(stream: BinaryIO, size: int) -> None:
    remaining = size
    while remaining:
        chunk = stream.read(min(_CHUNK_SIZE, remaining))
        if not chunk:
            raise ArchiveSafetyError("truncated TAR member payload")
        remaining -= len(chunk)


def _tar_header_preflight(
    handle: BinaryIO,
    archive_format: ArchiveFormat,
    *,
    max_members: int,
    max_total_bytes: int,
    max_metadata_bytes: int,
) -> None:
    handle.seek(0)
    gzip_stream: Optional[gzip.GzipFile] = None
    stream: BinaryIO = handle
    if archive_format is ArchiveFormat.TAR_GZ:
        gzip_stream = gzip.GzipFile(fileobj=handle, mode="rb")
        stream = gzip_stream
    logical_members = 0
    declared_total = 0
    metadata_total = 0
    try:
        while True:
            header = _read_exact(stream, 512)
            metadata_total += 512
            if metadata_total > max_metadata_bytes:
                raise ArchiveSafetyError("TAR header metadata exceeds max_metadata_bytes")
            if header == b"\x00" * 512:
                break
            stored_checksum = _tar_number(header[148:156], "checksum")
            computed_checksum = sum(header[:148]) + (32 * 8) + sum(header[156:])
            if stored_checksum != computed_checksum:
                raise ArchiveSafetyError("invalid TAR header checksum")
            size = _tar_number(header[124:136], "size")
            type_flag = header[156:157]
            padded_size = ((size + 511) // 512) * 512
            if type_flag in _TAR_METADATA_TYPES:
                if size > max_metadata_bytes or metadata_total + padded_size > max_metadata_bytes:
                    raise ArchiveSafetyError("TAR extended metadata exceeds max_metadata_bytes")
                metadata_total += padded_size
            else:
                logical_members += 1
                if logical_members > max_members:
                    raise ArchiveSafetyError(
                        f"archive has more than {max_members} members"
                    )
                declared_total += size
                if declared_total > max_total_bytes:
                    raise ArchiveSafetyError("TAR declared payload exceeds max_total_bytes")
            _discard_exact(stream, padded_size)
    except (gzip.BadGzipFile, EOFError, OSError) as error:
        raise ArchiveSafetyError(f"invalid TAR.GZ stream: {error}") from error
    finally:
        if gzip_stream is not None:
            gzip_stream.close()
        handle.seek(0)


def _detect_and_preflight(
    handle: BinaryIO,
    *,
    max_members: int,
    max_total_bytes: int,
    max_metadata_bytes: int,
) -> ArchiveFormat:
    handle.seek(0)
    prefix = handle.read(6)
    handle.seek(0)
    if prefix[:4] in _ZIP_PREFIXES:
        _zip_eocd_preflight(
            handle, max_members=max_members, max_metadata_bytes=max_metadata_bytes
        )
        return ArchiveFormat.ZIP
    if prefix.startswith(b"\x1f\x8b"):
        archive_format = ArchiveFormat.TAR_GZ
    elif prefix.startswith(b"BZh") or prefix.startswith(b"\xfd7zXZ\x00"):
        raise ArchiveSafetyError("only uncompressed TAR and TAR.GZ are supported")
    else:
        archive_format = ArchiveFormat.TAR
    _tar_header_preflight(
        handle,
        archive_format,
        max_members=max_members,
        max_total_bytes=max_total_bytes,
        max_metadata_bytes=max_metadata_bytes,
    )
    return archive_format


def _zip_kind(info: zipfile.ZipInfo) -> MemberKind:
    if info.flag_bits & 0x1:
        raise ArchiveSafetyError(f"encrypted ZIP member is forbidden: {info.filename!r}")
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if info.is_dir():
        if file_type not in {0, stat.S_IFDIR}:
            raise ArchiveSafetyError(f"non-directory special ZIP member is forbidden: {info.filename!r}")
        return MemberKind.DIRECTORY
    if file_type not in {0, stat.S_IFREG}:
        raise ArchiveSafetyError(f"non-regular ZIP member is forbidden: {info.filename!r}")
    return MemberKind.FILE


def _zip_specs(archive: zipfile.ZipFile, max_members: int) -> list[_MemberSpec]:
    infos = archive.infolist()
    if len(infos) > max_members:
        raise ArchiveSafetyError(f"archive has more than {max_members} members")
    specs: list[_MemberSpec] = []
    for info in infos:
        kind = _zip_kind(info)
        path = normalize_member_path(info.filename, is_directory=kind is MemberKind.DIRECTORY)
        if info.file_size < 0:
            raise ArchiveSafetyError(f"negative ZIP member size: {path}")
        if kind is MemberKind.DIRECTORY and info.file_size != 0:
            raise ArchiveSafetyError(f"ZIP directory declares nonzero bytes: {path}")
        specs.append(_MemberSpec(info, path, kind, info.file_size))
    return specs


def _tar_kind(info: tarfile.TarInfo) -> MemberKind:
    sparse_headers = any(key.startswith("GNU.sparse") for key in info.pax_headers)
    if info.sparse is not None or sparse_headers:
        raise ArchiveSafetyError(f"sparse TAR member is forbidden: {info.name!r}")
    if info.type in {tarfile.REGTYPE, tarfile.AREGTYPE}:
        return MemberKind.FILE
    if info.type == tarfile.DIRTYPE:
        return MemberKind.DIRECTORY
    raise ArchiveSafetyError(f"non-regular TAR member is forbidden: {info.name!r}")


def _tar_specs(archive: tarfile.TarFile, max_members: int) -> list[_MemberSpec]:
    specs: list[_MemberSpec] = []
    for info in archive:
        if len(specs) >= max_members:
            raise ArchiveSafetyError(f"archive has more than {max_members} members")
        kind = _tar_kind(info)
        path = normalize_member_path(info.name, is_directory=kind is MemberKind.DIRECTORY)
        if info.size < 0:
            raise ArchiveSafetyError(f"negative TAR member size: {path}")
        if kind is MemberKind.DIRECTORY and info.size != 0:
            raise ArchiveSafetyError(f"TAR directory declares nonzero bytes: {path}")
        specs.append(_MemberSpec(info, path, kind, info.size))
    return specs


def _check_declared_budget(specs: Sequence[_MemberSpec], max_total_bytes: int) -> int:
    total = 0
    for spec in specs:
        total += spec.declared_size
        if total > max_total_bytes:
            raise ArchiveSafetyError(
                f"archive declares {total} bytes, exceeding limit {max_total_bytes}"
            )
    _validate_path_set(specs)
    return total


def _hash_member(
    stream: BinaryIO, spec: _MemberSpec, max_total_bytes: int, total: int
) -> tuple[str, int]:
    digest = hashlib.sha256()
    actual = 0
    while True:
        chunk = stream.read(_CHUNK_SIZE)
        if not chunk:
            break
        actual += len(chunk)
        total += len(chunk)
        if actual > spec.declared_size:
            raise ArchiveSafetyError(f"member exceeds declared size: {spec.path}")
        if total > max_total_bytes:
            raise ArchiveSafetyError("actual expanded bytes exceed max_total_bytes")
        digest.update(chunk)
    if actual != spec.declared_size:
        raise ArchiveSafetyError(
            f"member size mismatch for {spec.path}: declared={spec.declared_size}, actual={actual}"
        )
    return digest.hexdigest(), total


def _inspect_zip(
    handle: BinaryIO, *, max_members: int, max_total_bytes: int
) -> tuple[int, tuple[MemberSummary, ...]]:
    handle.seek(0)
    with zipfile.ZipFile(handle, mode="r") as archive:
        specs = _zip_specs(archive, max_members)
        declared_total = _check_declared_budget(specs, max_total_bytes)
        summaries: list[MemberSummary] = []
        actual_total = 0
        for spec in specs:
            if spec.kind is MemberKind.DIRECTORY:
                summaries.append(MemberSummary(spec.path, spec.kind, 0, None))
                continue
            try:
                with archive.open(spec.source, mode="r") as stream:
                    digest, actual_total = _hash_member(
                        stream, spec, max_total_bytes, actual_total
                    )
            except (RuntimeError, zipfile.BadZipFile, EOFError) as error:
                raise ArchiveSafetyError(f"cannot read ZIP member {spec.path}: {error}") from error
            summaries.append(MemberSummary(spec.path, spec.kind, spec.declared_size, digest))
        if actual_total != declared_total:
            raise ArchiveSafetyError("ZIP actual total does not match declared total")
        return declared_total, tuple(summaries)


def _inspect_tar(
    handle: BinaryIO, *, max_members: int, max_total_bytes: int
) -> tuple[int, tuple[MemberSummary, ...]]:
    handle.seek(0)
    with tarfile.open(fileobj=handle, mode="r:*") as archive:
        specs = _tar_specs(archive, max_members)
        declared_total = _check_declared_budget(specs, max_total_bytes)
        summaries: list[MemberSummary] = []
        actual_total = 0
        for spec in specs:
            if spec.kind is MemberKind.DIRECTORY:
                summaries.append(MemberSummary(spec.path, spec.kind, 0, None))
                continue
            stream = archive.extractfile(spec.source)
            if stream is None:
                raise ArchiveSafetyError(f"cannot read TAR member: {spec.path}")
            with stream:
                digest, actual_total = _hash_member(stream, spec, max_total_bytes, actual_total)
            summaries.append(MemberSummary(spec.path, spec.kind, spec.declared_size, digest))
        if actual_total != declared_total:
            raise ArchiveSafetyError("TAR actual total does not match declared total")
        return declared_total, tuple(summaries)


def _inspect_open_file(
    handle: BinaryIO,
    *,
    expected_sha256: Optional[str],
    max_members: int,
    max_total_bytes: int,
    max_metadata_bytes: int,
) -> tuple[ArchiveInspection, _FileFingerprint]:
    baseline = _fingerprint(handle)
    archive_sha256 = _stable_sha256(handle, baseline)
    if expected_sha256 is not None and archive_sha256 != expected_sha256:
        raise ArchiveSafetyError(
            f"archive SHA256 mismatch: expected={expected_sha256}, actual={archive_sha256}"
        )
    archive_format = _detect_and_preflight(
        handle,
        max_members=max_members,
        max_total_bytes=max_total_bytes,
        max_metadata_bytes=max_metadata_bytes,
    )
    if archive_format is ArchiveFormat.ZIP:
        declared_total, summaries = _inspect_zip(
            handle, max_members=max_members, max_total_bytes=max_total_bytes
        )
    else:
        declared_total, summaries = _inspect_tar(
            handle, max_members=max_members, max_total_bytes=max_total_bytes
        )
    if _stable_sha256(handle, baseline) != archive_sha256:
        raise ArchiveSafetyError("archive content changed during inspection")
    return (
        ArchiveInspection(
            format=archive_format,
            sha256=archive_sha256,
            member_count=len(summaries),
            total_declared_bytes=declared_total,
            members=summaries,
        ),
        baseline,
    )


def inspect_archive(
    archive_path: str | Path,
    *,
    max_total_bytes: int,
    max_members: int = 200_000,
    max_metadata_bytes: int = _DEFAULT_METADATA_BYTES,
    expected_sha256: Optional[str] = None,
) -> ArchiveInspection:
    """Fully inspect and hash an absolute, symlink-free archive path."""

    _validate_limits(max_members, max_total_bytes, max_metadata_bytes)
    _validate_expected_sha256(expected_sha256)
    with _open_source_file(archive_path) as handle:
        inspection, _ = _inspect_open_file(
            handle,
            expected_sha256=expected_sha256,
            max_members=max_members,
            max_total_bytes=max_total_bytes,
            max_metadata_bytes=max_metadata_bytes,
        )
        return inspection


def _open_or_create_directory(parent_descriptor: int, component: str) -> int:
    try:
        os.mkdir(component, mode=0o755, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    descriptor = os.open(component, _directory_flags(), dir_fd=parent_descriptor)
    os.fchmod(descriptor, 0o755)
    return descriptor


def _member_parent_descriptor(destination_descriptor: int, member_path: str) -> tuple[int, str]:
    components = member_path.split("/")
    descriptor = os.dup(destination_descriptor)
    try:
        for component in components[:-1]:
            next_descriptor = _open_or_create_directory(descriptor, component)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, components[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _create_directory_member(destination_descriptor: int, member_path: str) -> None:
    descriptor = os.dup(destination_descriptor)
    try:
        for component in member_path.split("/"):
            next_descriptor = _open_or_create_directory(descriptor, component)
            os.close(descriptor)
            descriptor = next_descriptor
    finally:
        os.close(descriptor)


def _write_member(
    stream: BinaryIO,
    parent_descriptor: int,
    leaf: str,
    summary: MemberSummary,
    *,
    max_total_bytes: int,
    total_actual: int,
) -> int:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(leaf, flags, 0o644, dir_fd=parent_descriptor)
    digest = hashlib.sha256()
    member_actual = 0
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                member_actual += len(chunk)
                total_actual += len(chunk)
                if member_actual > summary.declared_size:
                    raise ArchiveSafetyError(f"member exceeds declared size: {summary.path}")
                if total_actual > max_total_bytes:
                    raise ArchiveSafetyError("actual expanded bytes exceed max_total_bytes")
                output.write(chunk)
                digest.update(chunk)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if member_actual != summary.declared_size:
        raise ArchiveSafetyError(f"member size changed during extraction: {summary.path}")
    if digest.hexdigest() != summary.sha256:
        raise ArchiveSafetyError(f"member SHA256 changed during extraction: {summary.path}")
    return total_actual


def _verify_specs(specs: Sequence[_MemberSpec], inspection: ArchiveInspection) -> None:
    observed = tuple((spec.path, spec.kind, spec.declared_size) for spec in specs)
    expected = tuple(
        (summary.path, summary.kind, summary.declared_size) for summary in inspection.members
    )
    if observed != expected:
        raise ArchiveSafetyError("archive member metadata changed between inspection and extraction")


def _extract_zip(
    handle: BinaryIO,
    destination_descriptor: int,
    inspection: ArchiveInspection,
    max_members: int,
    max_total_bytes: int,
) -> None:
    handle.seek(0)
    total_actual = 0
    with zipfile.ZipFile(handle, mode="r") as archive:
        specs = _zip_specs(archive, max_members)
        _validate_path_set(specs)
        _verify_specs(specs, inspection)
        for spec, summary in zip(specs, inspection.members):
            if spec.kind is MemberKind.DIRECTORY:
                _create_directory_member(destination_descriptor, spec.path)
                continue
            parent_descriptor, leaf = _member_parent_descriptor(
                destination_descriptor, spec.path
            )
            try:
                with archive.open(spec.source, mode="r") as stream:
                    total_actual = _write_member(
                        stream,
                        parent_descriptor,
                        leaf,
                        summary,
                        max_total_bytes=max_total_bytes,
                        total_actual=total_actual,
                    )
            finally:
                os.close(parent_descriptor)
    if total_actual != inspection.total_declared_bytes:
        raise ArchiveSafetyError("ZIP total bytes changed during extraction")


def _extract_tar(
    handle: BinaryIO,
    destination_descriptor: int,
    inspection: ArchiveInspection,
    max_members: int,
    max_total_bytes: int,
) -> None:
    handle.seek(0)
    total_actual = 0
    with tarfile.open(fileobj=handle, mode="r:*") as archive:
        specs = _tar_specs(archive, max_members)
        _validate_path_set(specs)
        _verify_specs(specs, inspection)
        for spec, summary in zip(specs, inspection.members):
            if spec.kind is MemberKind.DIRECTORY:
                _create_directory_member(destination_descriptor, spec.path)
                continue
            stream = archive.extractfile(spec.source)
            if stream is None:
                raise ArchiveSafetyError(f"cannot read TAR member: {spec.path}")
            parent_descriptor, leaf = _member_parent_descriptor(
                destination_descriptor, spec.path
            )
            try:
                with stream:
                    total_actual = _write_member(
                        stream,
                        parent_descriptor,
                        leaf,
                        summary,
                        max_total_bytes=max_total_bytes,
                        total_actual=total_actual,
                    )
            finally:
                os.close(parent_descriptor)
    if total_actual != inspection.total_declared_bytes:
        raise ArchiveSafetyError("TAR total bytes changed during extraction")


def safe_extract(
    archive_path: str | Path,
    destination: str | Path,
    *,
    expected_sha256: str,
    max_total_bytes: int,
    max_members: int = 200_000,
    max_metadata_bytes: int = _DEFAULT_METADATA_BYTES,
) -> ArchiveInspection:
    """Inspect then safely extract using held source and destination dirfds."""

    _validate_limits(max_members, max_total_bytes, max_metadata_bytes)
    _validate_expected_sha256(expected_sha256)
    parent_descriptor, destination_leaf = _open_destination_parent(destination)
    destination_descriptor = -1
    try:
        try:
            os.stat(destination_leaf, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"destination already exists: {destination}")

        with _open_source_file(archive_path) as handle:
            inspection, baseline = _inspect_open_file(
                handle,
                expected_sha256=expected_sha256,
                max_members=max_members,
                max_total_bytes=max_total_bytes,
                max_metadata_bytes=max_metadata_bytes,
            )
            os.mkdir(destination_leaf, mode=0o755, dir_fd=parent_descriptor)
            destination_descriptor = os.open(
                destination_leaf, _directory_flags(), dir_fd=parent_descriptor
            )
            os.fchmod(destination_descriptor, 0o755)
            if inspection.format is ArchiveFormat.ZIP:
                _extract_zip(
                    handle,
                    destination_descriptor,
                    inspection,
                    max_members,
                    max_total_bytes,
                )
            else:
                _extract_tar(
                    handle,
                    destination_descriptor,
                    inspection,
                    max_members,
                    max_total_bytes,
                )
            if _stable_sha256(handle, baseline) != inspection.sha256:
                raise ArchiveSafetyError("archive content changed during extraction")
    finally:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
        os.close(parent_descriptor)
    return inspection


__all__ = [
    "ArchiveFormat",
    "ArchiveInspection",
    "ArchiveSafetyError",
    "MemberKind",
    "MemberSummary",
    "inspect_archive",
    "normalize_member_path",
    "safe_extract",
]
