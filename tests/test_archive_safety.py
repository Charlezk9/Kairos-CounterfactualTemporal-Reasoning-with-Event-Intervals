from io import BytesIO
import hashlib
import inspect as python_inspect
import os
from pathlib import Path
import stat
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import kairos.archive_safety as archive_safety
from kairos.archive_safety import (
    ArchiveFormat,
    ArchiveSafetyError,
    MemberKind,
    inspect_archive,
    normalize_member_path,
    safe_extract,
)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def eocd_position(content):
    position = content.rfind(b"PK\x05\x06")
    if position < 0:
        raise AssertionError("test ZIP has no EOCD")
    return position


def zip_header_offsets(content):
    eocd = eocd_position(content)
    central = struct.unpack_from("<L", content, eocd + 16)[0]
    if content[central : central + 4] != b"PK\x01\x02":
        raise AssertionError("test ZIP has no central header")
    local = struct.unpack_from("<L", content, central + 42)[0]
    if content[local : local + 4] != b"PK\x03\x04":
        raise AssertionError("test ZIP has no local header")
    return eocd, central, local


def write_zip(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)


def write_tar(path, members, *, gzip=False):
    mode = "w:gz" if gzip else "w"
    with tarfile.open(path, mode=mode) as archive:
        for name, content in members:
            if content is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o777
                archive.addfile(info)
            else:
                encoded = content if isinstance(content, bytes) else content.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(encoded)
                info.mode = 0o777
                archive.addfile(info, BytesIO(encoded))


class ArchiveRoundTripTests(unittest.TestCase):
    def test_zip_tar_and_tar_gz_round_trip_and_permissions(self):
        cases = (
            ("sample.zip", ArchiveFormat.ZIP, lambda path: write_zip(path, [("folder/", b""), ("folder/a.txt", b"alpha")])),
            ("sample.tar", ArchiveFormat.TAR, lambda path: write_tar(path, [("folder/", None), ("folder/a.txt", b"alpha")])),
            ("sample.tar.gz", ArchiveFormat.TAR_GZ, lambda path: write_tar(path, [("folder/", None), ("folder/a.txt", b"alpha")], gzip=True)),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename, expected_format, writer in cases:
                with self.subTest(filename=filename):
                    source = root / filename
                    writer(source)
                    inspection = inspect_archive(source, max_total_bytes=1024)
                    self.assertIs(inspection.format, expected_format)
                    self.assertEqual(inspection.sha256, file_sha256(source))
                    self.assertEqual(inspection.member_count, 2)
                    self.assertEqual(inspection.total_declared_bytes, 5)
                    self.assertEqual(inspection.members[1].sha256, hashlib.sha256(b"alpha").hexdigest())

                    destination = root / f"out-{filename}"
                    extracted = safe_extract(
                        source,
                        destination,
                        expected_sha256=inspection.sha256,
                        max_total_bytes=1024,
                    )
                    self.assertEqual(extracted, inspection)
                    self.assertEqual((destination / "folder/a.txt").read_bytes(), b"alpha")
                    self.assertEqual(stat.S_IMODE(os.lstat(destination).st_mode), 0o755)
                    self.assertEqual(stat.S_IMODE(os.lstat(destination / "folder").st_mode), 0o755)
                    self.assertEqual(stat.S_IMODE(os.lstat(destination / "folder/a.txt").st_mode), 0o644)

    def test_destination_must_not_exist_and_sha_mismatch_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.zip"
            write_zip(source, [("a.txt", b"alpha")])
            existing = root / "existing"
            existing.mkdir()
            sentinel = existing / "sentinel"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                safe_extract(
                    source,
                    existing,
                    expected_sha256=file_sha256(source),
                    max_total_bytes=100,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

            absent = root / "absent"
            with self.assertRaisesRegex(ArchiveSafetyError, "SHA256 mismatch"):
                safe_extract(
                    source,
                    absent,
                    expected_sha256="0" * 64,
                    max_total_bytes=100,
                )
            self.assertFalse(absent.exists())

    def test_extract_failure_preserves_partial_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.zip"
            write_zip(source, [("first.txt", b"first"), ("second.txt", b"second")])
            destination = root / "partial"
            original = archive_safety._write_member
            call_count = 0

            def fail_second(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise ArchiveSafetyError("injected extraction failure")
                return original(*args, **kwargs)

            with mock.patch("kairos.archive_safety._write_member", side_effect=fail_second):
                with self.assertRaisesRegex(ArchiveSafetyError, "injected"):
                    safe_extract(
                        source,
                        destination,
                        expected_sha256=file_sha256(source),
                        max_total_bytes=100,
                    )
            self.assertTrue(destination.is_dir())
            self.assertEqual((destination / "first.txt").read_bytes(), b"first")
            self.assertFalse((destination / "second.txt").exists())


class ArchivePathTests(unittest.TestCase):
    def test_rejects_unsafe_path_forms(self):
        paths = ("", "/absolute", "../escape", "a/../b", ".", "a/./b", "a//b", "a\\b", "C:/drive", "nul\x00name")
        for path in paths:
            with self.subTest(path=repr(path)):
                with self.assertRaises(ArchiveSafetyError):
                    normalize_member_path(path, is_directory=False)

    def test_rejects_oversized_utf8_paths_and_components(self):
        with self.assertRaisesRegex(ArchiveSafetyError, "component"):
            normalize_member_path("é" * 128, is_directory=False)
        oversized_path = "/".join("a" * 250 for _ in range(17))
        with self.assertRaisesRegex(ArchiveSafetyError, "path exceeds"):
            normalize_member_path(oversized_path, is_directory=False)

    def test_archive_traversal_variants_are_rejected(self):
        names = ("/absolute", "../escape", "a/../b", "a/./b", "a//b", "a\\b", "C:/drive")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, name in enumerate(names):
                with self.subTest(name=name):
                    source = root / f"unsafe-{index}.zip"
                    write_zip(source, [(name, b"bad")])
                    with self.assertRaises(ArchiveSafetyError):
                        inspect_archive(source, max_total_bytes=100)

    def test_duplicate_normalized_and_prefix_conflicts_are_rejected(self):
        cases = (
            [("same", b"one"), ("same", b"two")],
            [("node", b"file"), ("node/child", b"child")],
            [("node/child", b"child"), ("node", b"file")],
            [("e\u0301.txt", b"one"), ("é.txt", b"two")],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, members in enumerate(cases):
                with self.subTest(index=index):
                    source = root / f"conflict-{index}.zip"
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        write_zip(source, members)
                    with self.assertRaises(ArchiveSafetyError):
                        inspect_archive(source, max_total_bytes=100)


class ArchiveTypeTests(unittest.TestCase):
    def test_tar_rejects_links_device_fifo_and_sparse(self):
        cases = (
            (tarfile.SYMTYPE, {}),
            (tarfile.LNKTYPE, {}),
            (tarfile.CHRTYPE, {}),
            (tarfile.FIFOTYPE, {}),
            (tarfile.REGTYPE, {"GNU.sparse.map": "0,1"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (member_type, pax_headers) in enumerate(cases):
                with self.subTest(member_type=member_type):
                    source = root / f"special-{index}.tar"
                    with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as archive:
                        info = tarfile.TarInfo("special")
                        info.type = member_type
                        info.linkname = "target"
                        info.pax_headers = pax_headers
                        if member_type == tarfile.REGTYPE:
                            info.size = 1
                            archive.addfile(info, BytesIO(b"x"))
                        else:
                            archive.addfile(info)
                    with self.assertRaises(ArchiveSafetyError):
                        inspect_archive(source, max_total_bytes=100)

    def test_zip_rejects_symlink_fifo_and_encrypted_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, mode in (("symlink", stat.S_IFLNK | 0o777), ("fifo", stat.S_IFIFO | 0o666)):
                with self.subTest(kind=kind):
                    source = root / f"{kind}.zip"
                    info = zipfile.ZipInfo(kind)
                    info.create_system = 3
                    info.external_attr = mode << 16
                    with zipfile.ZipFile(source, "w") as archive:
                        archive.writestr(info, b"target")
                    with self.assertRaises(ArchiveSafetyError):
                        inspect_archive(source, max_total_bytes=100)

            encrypted = root / "encrypted.zip"
            write_zip(encrypted, [("secret.txt", b"secret")])
            content = bytearray(encrypted.read_bytes())
            local = content.index(b"PK\x03\x04")
            central = content.index(b"PK\x01\x02")
            struct.pack_into("<H", content, local + 6, struct.unpack_from("<H", content, local + 6)[0] | 1)
            struct.pack_into("<H", content, central + 8, struct.unpack_from("<H", content, central + 8)[0] | 1)
            encrypted.write_bytes(content)
            with self.assertRaisesRegex(ArchiveSafetyError, "encrypted"):
                inspect_archive(encrypted, max_total_bytes=100)


class ArchiveBudgetTests(unittest.TestCase):
    def test_member_and_declared_byte_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "budget.zip"
            write_zip(source, [("a", b"123"), ("b", b"456")])
            with self.assertRaisesRegex(ArchiveSafetyError, "members"):
                inspect_archive(source, max_members=1, max_total_bytes=100)
            with self.assertRaisesRegex(ArchiveSafetyError, "bytes"):
                inspect_archive(source, max_total_bytes=5)

    def test_zip_limits_are_checked_before_zipfile_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "many.zip"
            write_zip(source, [("a", b"a"), ("b", b"b")])
            content = bytearray(source.read_bytes())
            eocd = eocd_position(content)
            struct.pack_into("<H", content, eocd + 8, 1)
            struct.pack_into("<H", content, eocd + 10, 1)
            source.write_bytes(content)
            with mock.patch.object(
                archive_safety.zipfile,
                "ZipFile",
                side_effect=AssertionError("ZipFile must not be constructed"),
            ):
                with self.assertRaisesRegex(ArchiveSafetyError, "members"):
                    inspect_archive(source, max_members=1, max_total_bytes=100)
                with self.assertRaisesRegex(ArchiveSafetyError, "metadata"):
                    inspect_archive(
                        source,
                        max_members=10,
                        max_total_bytes=100,
                        max_metadata_bytes=10,
                    )

    def test_zip_central_count_and_size_malformed_before_zipfile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "malformed.zip"
            write_zip(source, [("a", b"a"), ("b", b"b")])
            original = source.read_bytes()
            with mock.patch.object(
                archive_safety.zipfile,
                "ZipFile",
                side_effect=AssertionError("ZipFile must not be constructed"),
            ):
                wrong_count = bytearray(original)
                eocd = eocd_position(wrong_count)
                struct.pack_into("<H", wrong_count, eocd + 8, 1)
                struct.pack_into("<H", wrong_count, eocd + 10, 1)
                source.write_bytes(wrong_count)
                with self.assertRaisesRegex(ArchiveSafetyError, "entry count mismatch"):
                    inspect_archive(source, max_members=10, max_total_bytes=100)

                wrong_size = bytearray(original)
                eocd = eocd_position(wrong_size)
                central_size = struct.unpack_from("<L", wrong_size, eocd + 12)[0]
                struct.pack_into("<L", wrong_size, eocd + 12, central_size - 1)
                source.write_bytes(wrong_size)
                with self.assertRaisesRegex(ArchiveSafetyError, "exactly at the EOCD"):
                    inspect_archive(source, max_members=10, max_total_bytes=100)

    def test_force_zip64_local_extra_is_rejected_before_zipfile(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "forced.zip"
            with zipfile.ZipFile(source, "w") as archive:
                with archive.open("value.txt", "w", force_zip64=True) as output:
                    output.write(b"value")
            with mock.patch.object(
                archive_safety.zipfile,
                "ZipFile",
                side_effect=AssertionError("ZipFile must not be constructed"),
            ):
                with self.assertRaisesRegex(ArchiveSafetyError, "ZIP64"):
                    inspect_archive(source, max_total_bytes=100)

    def test_zip_central_directory_must_be_adjacent_to_eocd(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "gap.zip"
            write_zip(source, [("value", b"value")])
            content = source.read_bytes()
            eocd = eocd_position(content)
            source.write_bytes(content[:eocd] + b"\x00" + content[eocd:])
            with mock.patch.object(
                archive_safety.zipfile,
                "ZipFile",
                side_effect=AssertionError("ZipFile must not be constructed"),
            ):
                with self.assertRaisesRegex(ArchiveSafetyError, "exactly at the EOCD"):
                    inspect_archive(source, max_total_bytes=100)

    def test_zip_local_central_fields_match_before_zipfile(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mismatch.zip"
            write_zip(source, [("value", b"value")])
            original = source.read_bytes()

            def set_flag(content, offset, flag):
                current = struct.unpack_from("<H", content, offset)[0]
                struct.pack_into("<H", content, offset, current | flag)

            def encryption(content, central, local):
                set_flag(content, central + 8, 0x1)
                set_flag(content, local + 6, 0x1)

            def data_descriptor(content, central, local):
                set_flag(content, central + 8, 0x8)
                set_flag(content, local + 6, 0x8)

            def flags_mismatch(content, central, local):
                set_flag(content, local + 6, 0x800)

            def compression_mismatch(content, central, local):
                value = struct.unpack_from("<H", content, local + 8)[0]
                struct.pack_into("<H", content, local + 8, value + 1)

            def crc_mismatch(content, central, local):
                value = struct.unpack_from("<L", content, local + 14)[0]
                struct.pack_into("<L", content, local + 14, value ^ 1)

            def compressed_size_mismatch(content, central, local):
                value = struct.unpack_from("<L", content, local + 18)[0]
                struct.pack_into("<L", content, local + 18, value + 1)

            def uncompressed_size_mismatch(content, central, local):
                value = struct.unpack_from("<L", content, local + 22)[0]
                struct.pack_into("<L", content, local + 22, value + 1)

            cases = (
                ("encryption", encryption, "encrypted"),
                ("bit3", data_descriptor, "data descriptors"),
                ("flags", flags_mismatch, "flags mismatch"),
                ("compression", compression_mismatch, "compression mismatch"),
                ("CRC", crc_mismatch, "CRC32 mismatch"),
                ("compressed size", compressed_size_mismatch, "compressed size mismatch"),
                (
                    "uncompressed size",
                    uncompressed_size_mismatch,
                    "uncompressed size mismatch",
                ),
            )
            with mock.patch.object(
                archive_safety.zipfile,
                "ZipFile",
                side_effect=AssertionError("ZipFile must not be constructed"),
            ):
                for label, mutate, message in cases:
                    with self.subTest(label=label):
                        content = bytearray(original)
                        _eocd, central, local = zip_header_offsets(content)
                        mutate(content, central, local)
                        source.write_bytes(content)
                        with self.assertRaisesRegex(ArchiveSafetyError, message):
                            inspect_archive(source, max_total_bytes=100)

    def test_tar_limits_are_checked_before_tarfile_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "many.tar"
            write_tar(source, [("a", b"a"), ("b", b"b")])
            with mock.patch.object(
                archive_safety.tarfile,
                "open",
                side_effect=AssertionError("tarfile.open must not be called"),
            ):
                with self.assertRaisesRegex(ArchiveSafetyError, "members"):
                    inspect_archive(source, max_members=1, max_total_bytes=100)
                with self.assertRaisesRegex(ArchiveSafetyError, "metadata"):
                    inspect_archive(
                        source,
                        max_members=10,
                        max_total_bytes=100,
                        max_metadata_bytes=511,
                    )

    def test_tar_implementation_never_calls_getmembers(self):
        source = python_inspect.getsource(archive_safety)
        self.assertNotIn(".getmembers(", source)


class ArchiveToctouTests(unittest.TestCase):
    def test_in_place_rewrite_after_first_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            replacement = root / "replacement.zip"
            write_zip(source, [("value.txt", b"aaaaa")])
            write_zip(replacement, [("value.txt", b"bbbbb")])
            self.assertEqual(source.stat().st_size, replacement.stat().st_size)
            original_hash = archive_safety._archive_sha256
            calls = 0

            def rewrite_after_hash(handle):
                nonlocal calls
                digest = original_hash(handle)
                calls += 1
                if calls == 1:
                    source.write_bytes(replacement.read_bytes())
                return digest

            with mock.patch(
                "kairos.archive_safety._archive_sha256", side_effect=rewrite_after_hash
            ):
                with self.assertRaisesRegex(ArchiveSafetyError, "changed"):
                    inspect_archive(source, max_total_bytes=100)

    def test_source_leaf_and_parent_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_parent = root / "real"
            real_parent.mkdir()
            source = real_parent / "source.zip"
            write_zip(source, [("value.txt", b"value")])
            leaf_link = root / "leaf.zip"
            leaf_link.symlink_to(source)
            parent_link = root / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            for path in (leaf_link, parent_link / "source.zip"):
                with self.subTest(path=path):
                    with self.assertRaises(ArchiveSafetyError):
                        inspect_archive(path, max_total_bytes=100)

    def test_destination_parent_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            write_zip(source, [("value.txt", b"value")])
            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(ArchiveSafetyError):
                safe_extract(
                    source,
                    linked_parent / "out",
                    expected_sha256=file_sha256(source),
                    max_total_bytes=100,
                )
            self.assertFalse((real_parent / "out").exists())

    def test_held_destination_dirfd_prevents_escape_after_parent_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            write_zip(source, [("value.txt", b"value")])
            work = root / "work"
            moved = root / "moved"
            escape = root / "escape"
            work.mkdir()
            escape.mkdir()
            destination = work / "out"
            original_write = archive_safety._write_member
            renamed = False

            def rename_parent(*args, **kwargs):
                nonlocal renamed
                if not renamed:
                    work.rename(moved)
                    work.symlink_to(escape, target_is_directory=True)
                    renamed = True
                return original_write(*args, **kwargs)

            with mock.patch(
                "kairos.archive_safety._write_member", side_effect=rename_parent
            ):
                safe_extract(
                    source,
                    destination,
                    expected_sha256=file_sha256(source),
                    max_total_bytes=100,
                )
            self.assertEqual((moved / "out/value.txt").read_bytes(), b"value")
            self.assertFalse((escape / "out").exists())

    def test_archive_and_destination_paths_must_be_absolute(self):
        with self.assertRaisesRegex(ArchiveSafetyError, "absolute"):
            inspect_archive("relative.zip", max_total_bytes=100)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.zip"
            write_zip(source, [("value", b"value")])
            with self.assertRaisesRegex(ArchiveSafetyError, "absolute"):
                safe_extract(
                    source,
                    "relative-out",
                    expected_sha256=file_sha256(source),
                    max_total_bytes=100,
                )


if __name__ == "__main__":
    unittest.main()
