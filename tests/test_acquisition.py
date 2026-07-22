from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

import kairos.acquisition as acquisition
from kairos.acquisition import AcquisitionError


DATA0_TMP = "/data0/hk_data/kairos-zx/.tmp"
TEST_COMMIT = "1" * 40


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(count: int) -> bytes:
    return b'{"question":"q","answer":"a"}\n' * count


def write_tar_gz(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, mode="w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(content)
            archive.addfile(info, BytesIO(content))


class AcquisitionFixture(unittest.TestCase):
    def setUp(self) -> None:
        Path(DATA0_TMP).mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=DATA0_TMP)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir(mode=0o700)
        self.layout = acquisition._Layout(self.root, "stage", "revision")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_stage(
        self,
        *,
        train: bytes | None = None,
        test: bytes | None = None,
        observation_updates: dict[str, object] | None = None,
    ) -> tuple[Path, str]:
        stage = self.layout.stage
        stage.mkdir(mode=0o700)
        stage.chmod(0o700)
        base = acquisition.UPSTREAM_ROOT
        members = {
            f"{base}/LICENSE": b"MIT\n",
            f"{base}/README.md": b"GSM8K\n",
            f"{base}/grade_school_math/data/train.jsonl": (
                jsonl(acquisition.TRAIN_COUNT) if train is None else train
            ),
            f"{base}/grade_school_math/data/test.jsonl": (
                jsonl(acquisition.TEST_COUNT) if test is None else test
            ),
        }
        archive = stage / acquisition._STAGE_ARCHIVE
        write_tar_gz(archive, members)
        digest = sha256(archive)
        observation: dict[str, object] = {
            "curl_exit_code": 0,
            "http_code": 200,
            "fixed_url": acquisition.SOURCE_URL,
            "effective_url": acquisition.SOURCE_URL,
            "mime": "application/x-gzip",
            "size_download": archive.stat().st_size,
        }
        observation.update(observation_updates or {})
        (stage / acquisition._HTTP_OBSERVATION).write_text(
            json.dumps(observation, separators=(",", ":")), encoding="utf-8"
        )
        return archive, digest

    def make_revision_dataset(
        self,
        name: str = "revision",
        *,
        train: bytes | None = None,
        test: bytes | None = None,
    ) -> Path:
        revision = self.root / name
        base = revision / acquisition._EXTRACTED / acquisition.UPSTREAM_ROOT
        data = base / "grade_school_math" / "data"
        data.mkdir(parents=True)
        revision.chmod(0o700)
        (revision / acquisition._FORMAL_ARCHIVE).write_bytes(b"archive")
        (base / "LICENSE").write_bytes(b"MIT\n")
        (base / "README.md").write_bytes(b"GSM8K\n")
        (data / "train.jsonl").write_bytes(
            jsonl(acquisition.TRAIN_COUNT) if train is None else train
        )
        (data / "test.jsonl").write_bytes(
            jsonl(acquisition.TEST_COUNT) if test is None else test
        )
        return revision

    def revision_fd(self, revision: Path) -> int:
        return acquisition._open_absolute_dir(revision)


class StageValidationTests(AcquisitionFixture):
    def test_valid_stage_reports_frozen_observation_and_digest(self) -> None:
        _, digest = self.make_stage()
        result = acquisition._validate_stage_layout(self.layout, digest)
        self.assertEqual(result["archive_sha256"], digest)
        self.assertEqual(result["http"]["effective_url"], acquisition.SOURCE_URL)

    def test_observation_rejects_duplicate_extra_bool_and_nonfinite_fields(self) -> None:
        archive, digest = self.make_stage()
        valid = {
            "curl_exit_code": 0,
            "http_code": 200,
            "fixed_url": acquisition.SOURCE_URL,
            "effective_url": acquisition.SOURCE_URL,
            "mime": "application/x-gzip",
            "size_download": archive.stat().st_size,
        }
        cases = (
            b'{"curl_exit_code":0,"curl_exit_code":0,"http_code":200,'
            + json.dumps(
                {
                    "fixed_url": acquisition.SOURCE_URL,
                    "effective_url": acquisition.SOURCE_URL,
                    "mime": "application/x-gzip",
                    "size_download": archive.stat().st_size,
                },
                separators=(",", ":"),
            ).encode()[1:],
            json.dumps({**valid, "extra": 1}).encode(),
            json.dumps({**valid, "curl_exit_code": False}).encode(),
            json.dumps({**valid, "size_download": float("nan")}).encode(),
        )
        for content in cases:
            with self.subTest(content=content[:40]):
                (self.layout.stage / acquisition._HTTP_OBSERVATION).write_bytes(content)
                with self.assertRaises(AcquisitionError):
                    acquisition._validate_stage_layout(self.layout, digest)

    def test_observation_rejects_status_url_authority_and_mime_changes(self) -> None:
        cases = (
            {"curl_exit_code": 1},
            {"http_code": 206},
            {"fixed_url": acquisition.SOURCE_URL + "?mirror=1"},
            {"effective_url": "https://example.com/archive.tar.gz"},
            {"mime": "application/octet-stream"},
            {"mime": "application/x-gzip; charset=binary"},
        )
        for index, updates in enumerate(cases):
            with self.subTest(updates=updates):
                layout = acquisition._Layout(self.root, f"stage-{index}", f"revision-{index}")
                original = self.layout
                self.layout = layout
                _, digest = self.make_stage(observation_updates=updates)
                self.layout = original
                with self.assertRaises(AcquisitionError):
                    acquisition._validate_stage_layout(layout, digest)

    def test_observation_rejects_size_mismatch_and_bad_gzip_magic(self) -> None:
        archive, digest = self.make_stage(observation_updates={"size_download": 1})
        with self.assertRaisesRegex(AcquisitionError, "size_download"):
            acquisition._validate_stage_layout(self.layout, digest)
        archive.write_bytes(b"not-gzip")
        digest = sha256(archive)
        observation = {
            "curl_exit_code": 0,
            "http_code": 200,
            "fixed_url": acquisition.SOURCE_URL,
            "effective_url": acquisition.SOURCE_URL,
            "mime": "application/x-gzip",
            "size_download": archive.stat().st_size,
        }
        (self.layout.stage / acquisition._HTTP_OBSERVATION).write_text(
            json.dumps(observation), encoding="utf-8"
        )
        with self.assertRaisesRegex(AcquisitionError, "gzip magic"):
            acquisition._validate_stage_layout(self.layout, digest)

    def test_stage_mode_and_strict_expected_digest_are_enforced(self) -> None:
        _, digest = self.make_stage()
        self.layout.stage.chmod(0o755)
        with self.assertRaisesRegex(AcquisitionError, "0700"):
            acquisition._validate_stage_layout(self.layout, digest)
        self.layout.stage.chmod(0o700)
        for invalid in ("A" * 64, "0" * 63, "../" + "0" * 61):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AcquisitionError):
                    acquisition._validate_stage_layout(self.layout, invalid)

    def test_sparse_archive_exact_limit_passes_and_limit_plus_one_fails(self) -> None:
        stage = self.layout.stage
        stage.mkdir(mode=0o700)
        archive = stage / acquisition._STAGE_ARCHIVE
        descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, b"\x1f\x8b")
            os.ftruncate(descriptor, 4096)
        finally:
            os.close(descriptor)

        def write_observation() -> str:
            digest = sha256(archive)
            (stage / acquisition._HTTP_OBSERVATION).write_text(
                json.dumps(
                    {
                        "curl_exit_code": 0,
                        "http_code": 200,
                        "fixed_url": acquisition.SOURCE_URL,
                        "effective_url": acquisition.SOURCE_URL,
                        "mime": "application/x-gzip",
                        "size_download": archive.stat().st_size,
                    }
                ),
                encoding="utf-8",
            )
            return digest

        digest = write_observation()
        with mock.patch.object(acquisition, "ARCHIVE_LIMIT", 4096):
            acquisition._validate_stage_layout(self.layout, digest)
        with archive.open("ab") as handle:
            handle.write(b"x")
        digest = write_observation()
        with mock.patch.object(acquisition, "ARCHIVE_LIMIT", 4096):
            with self.assertRaises(AcquisitionError):
                acquisition._validate_stage_layout(self.layout, digest)


class ArchiveCopyTests(AcquisitionFixture):
    def open_stage_and_revision(self) -> tuple[int, int, str]:
        _, digest = self.make_stage()
        self.layout.revision.mkdir(mode=0o700)
        return (
            acquisition._open_absolute_dir(self.layout.stage),
            acquisition._open_absolute_dir(self.layout.revision),
            digest,
        )

    def test_archive_copy_is_independent_fsynced_and_rehashed(self) -> None:
        stage_fd, revision_fd, digest = self.open_stage_and_revision()
        try:
            result = acquisition._copy_archive(stage_fd, revision_fd, digest)
        finally:
            os.close(stage_fd)
            os.close(revision_fd)
        source = self.layout.stage / acquisition._STAGE_ARCHIVE
        formal = self.layout.revision / acquisition._FORMAL_ARCHIVE
        self.assertEqual(result.sha256, digest)
        self.assertNotEqual((source.stat().st_dev, source.stat().st_ino), (formal.stat().st_dev, formal.stat().st_ino))
        self.assertEqual(formal.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(formal.stat().st_mode), 0o600)

    def test_archive_copy_rejects_hash_mismatch_and_existing_destination(self) -> None:
        stage_fd, revision_fd, digest = self.open_stage_and_revision()
        try:
            with self.assertRaisesRegex(AcquisitionError, "approved"):
                acquisition._copy_archive(stage_fd, revision_fd, "0" * 64)
            (self.layout.revision / acquisition._FORMAL_ARCHIVE).write_bytes(b"sentinel")
            with self.assertRaises(FileExistsError):
                acquisition._copy_archive(stage_fd, revision_fd, digest)
        finally:
            os.close(stage_fd)
            os.close(revision_fd)
        self.assertEqual((self.layout.revision / acquisition._FORMAL_ARCHIVE).read_bytes(), b"sentinel")

    def test_source_mutation_during_copy_is_detected_and_partial_is_preserved(self) -> None:
        stage_fd, revision_fd, digest = self.open_stage_and_revision()
        original_hash = acquisition._hash_fd
        calls = 0

        def mutate_after_first(fd: int, limit: int):
            nonlocal calls
            result = original_hash(fd, limit)
            calls += 1
            if calls == 1:
                with (self.layout.stage / acquisition._STAGE_ARCHIVE).open("ab") as handle:
                    handle.write(b"changed")
            return result

        try:
            with mock.patch("kairos.acquisition._hash_fd", side_effect=mutate_after_first):
                with self.assertRaises(AcquisitionError):
                    acquisition._copy_archive(stage_fd, revision_fd, digest)
        finally:
            os.close(stage_fd)
            os.close(revision_fd)
        self.assertTrue((self.layout.revision / acquisition._FORMAL_ARCHIVE).exists())

    def test_destination_rehash_mismatch_is_detected(self) -> None:
        stage_fd, revision_fd, digest = self.open_stage_and_revision()
        original_hash = acquisition._hash_fd
        calls = 0

        def corrupt_second_hash(fd: int, limit: int):
            nonlocal calls
            calls += 1
            actual_digest, size, fingerprint = original_hash(fd, limit)
            if calls == 2:
                actual_digest = "0" * 64
            return actual_digest, size, fingerprint

        try:
            with mock.patch("kairos.acquisition._hash_fd", side_effect=corrupt_second_hash):
                with self.assertRaisesRegex(AcquisitionError, "close/reopen"):
                    acquisition._copy_archive(stage_fd, revision_fd, digest)
        finally:
            os.close(stage_fd)
            os.close(revision_fd)

    def test_same_content_destination_inode_swap_is_rejected(self) -> None:
        stage_fd, revision_fd, digest = self.open_stage_and_revision()
        original_open = acquisition._open_relative_regular
        swapped = False

        def swap_before_reopen(root_fd: int, path: str, flags: int = os.O_RDONLY):
            nonlocal swapped
            if path == acquisition._FORMAL_ARCHIVE and not swapped:
                swapped = True
                formal = self.layout.revision / acquisition._FORMAL_ARCHIVE
                replacement = self.layout.revision / "replacement"
                replacement.write_bytes(formal.read_bytes())
                replacement.chmod(0o600)
                os.replace(replacement, formal)
            return original_open(root_fd, path, flags)

        try:
            with mock.patch(
                "kairos.acquisition._open_relative_regular",
                side_effect=swap_before_reopen,
            ):
                with self.assertRaisesRegex(AcquisitionError, "fingerprint"):
                    acquisition._copy_archive(stage_fd, revision_fd, digest)
        finally:
            os.close(stage_fd)
            os.close(revision_fd)


class DatasetAndTreeTests(AcquisitionFixture):
    def test_fixed_dataset_layout_and_counts_validate(self) -> None:
        revision = self.make_revision_dataset()
        fd = self.revision_fd(revision)
        try:
            result = acquisition._validate_dataset(
                fd, protocol_state=acquisition._ProtocolState.PRE_CHECKSUM
            )
        finally:
            os.close(fd)
        self.assertEqual(result.train_count, acquisition.TRAIN_COUNT)
        self.assertEqual(result.test_count, acquisition.TEST_COUNT)

    def test_dataset_rejects_short_and_long_split_counts(self) -> None:
        cases = (jsonl(acquisition.TRAIN_COUNT - 1), jsonl(acquisition.TRAIN_COUNT + 1))
        for index, train in enumerate(cases):
            with self.subTest(index=index):
                revision = self.make_revision_dataset(f"revision-{index}", train=train)
                fd = self.revision_fd(revision)
                try:
                    with self.assertRaisesRegex(AcquisitionError, "count"):
                        acquisition._validate_dataset(
                            fd,
                            protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                        )
                finally:
                    os.close(fd)

    def test_dataset_rejects_nonobject_missing_and_blank_fields(self) -> None:
        records = (b"[]\n", b'{"answer":"a"}\n', b'{"question":"q","answer":" "}\n')
        for index, first in enumerate(records):
            with self.subTest(index=index):
                train = first + jsonl(acquisition.TRAIN_COUNT - 1)
                revision = self.make_revision_dataset(f"revision-{index}", train=train)
                fd = self.revision_fd(revision)
                try:
                    with self.assertRaises(AcquisitionError):
                        acquisition._validate_dataset(
                            fd,
                            protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                        )
                finally:
                    os.close(fd)

    def test_raw_line_limit_is_checked_before_json_parsing(self) -> None:
        revision = self.make_revision_dataset(
            train=b"x" * (acquisition.LINE_LIMIT + 1) + b"\n"
        )
        fd = self.revision_fd(revision)
        try:
            with mock.patch("kairos.acquisition.json.loads") as loads:
                with self.assertRaisesRegex(AcquisitionError, "exceeds 1 MiB"):
                    acquisition._read_jsonl(
                        fd,
                        f"{acquisition._EXTRACTED}/{acquisition.UPSTREAM_ROOT}/grade_school_math/data/train.jsonl",
                        acquisition.TRAIN_COUNT,
                    )
                loads.assert_not_called()
        finally:
            os.close(fd)

    def test_dataset_rejects_wrong_top_level_and_missing_required_files(self) -> None:
        revision = self.make_revision_dataset()
        (revision / acquisition._EXTRACTED / "unexpected").mkdir()
        fd = self.revision_fd(revision)
        try:
            with self.assertRaisesRegex(AcquisitionError, "only the fixed"):
                acquisition._validate_dataset(
                    fd, protocol_state=acquisition._ProtocolState.PRE_CHECKSUM
                )
        finally:
            os.close(fd)
        wrong = self.make_revision_dataset("revision-missing")
        (wrong / acquisition._EXTRACTED / acquisition.UPSTREAM_ROOT / "LICENSE").unlink()
        fd = self.revision_fd(wrong)
        try:
            with self.assertRaises(FileNotFoundError):
                acquisition._validate_dataset(
                    fd, protocol_state=acquisition._ProtocolState.PRE_CHECKSUM
                )
        finally:
            os.close(fd)

    def test_tree_scan_rejects_symlinks_fifo_and_hardlinks(self) -> None:
        makers = (
            lambda extracted: (extracted / "bad").symlink_to("target"),
            lambda extracted: os.mkfifo(extracted / "bad"),
            lambda extracted: os.link(extracted / "file", extracted / "bad"),
        )
        for index, maker in enumerate(makers):
            with self.subTest(index=index):
                revision = self.root / f"tree-{index}"
                revision.mkdir(mode=0o700)
                (revision / acquisition._FORMAL_ARCHIVE).write_bytes(b"archive")
                extracted = revision / acquisition._EXTRACTED
                extracted.mkdir()
                (extracted / "file").write_bytes(b"value")
                maker(extracted)
                fd = self.revision_fd(revision)
                try:
                    with self.assertRaises(AcquisitionError):
                        acquisition._scan_tree(
                            fd,
                            protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                        )
                finally:
                    os.close(fd)

    def test_tree_scan_rejects_empty_directories_and_enforces_all_budgets(self) -> None:
        revision = self.root / "tree"
        revision.mkdir(mode=0o700)
        (revision / acquisition._FORMAL_ARCHIVE).write_bytes(b"archive")
        (revision / acquisition._EXTRACTED / "empty").mkdir(parents=True)
        fd = self.revision_fd(revision)
        try:
            with self.assertRaisesRegex(AcquisitionError, "empty directory"):
                acquisition._scan_tree(
                    fd,
                    protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                )
        finally:
            os.close(fd)

        (revision / acquisition._EXTRACTED / "empty").rmdir()
        (revision / acquisition._EXTRACTED / "file").write_bytes(b"12")
        fd = self.revision_fd(revision)
        try:
            with mock.patch.object(acquisition, "EXTRACTED_LIMIT", 1):
                with self.assertRaisesRegex(AcquisitionError, "byte limit|extracted bytes"):
                    acquisition._scan_tree(
                        fd,
                        protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                    )
            with mock.patch.object(acquisition, "MEMBER_LIMIT", 1):
                with self.assertRaisesRegex(AcquisitionError, "member limit"):
                    acquisition._scan_tree(
                        fd,
                        protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                    )
            with mock.patch.object(acquisition, "METADATA_LIMIT", 1):
                with self.assertRaisesRegex(AcquisitionError, "metadata"):
                    acquisition._scan_tree(
                        fd,
                        protocol_state=acquisition._ProtocolState.PRE_CHECKSUM,
                    )
        finally:
            os.close(fd)

    def test_relative_path_grammar_rejects_noncanonical_and_oversized_names(self) -> None:
        cases = ("", "a//b", "../a", "a\\b", "e\u0301", "control\n")
        for value in cases:
            with self.subTest(value=repr(value)):
                with self.assertRaises(AcquisitionError):
                    acquisition._validate_relative_path(value)
        with self.assertRaisesRegex(AcquisitionError, "255"):
            acquisition._validate_relative_path("é" * 128)
        with self.assertRaisesRegex(AcquisitionError, "4096"):
            acquisition._validate_relative_path("/".join("a" * 250 for _ in range(17)))

    def test_file_ancestor_set_is_exact_for_large_path_collection(self) -> None:
        paths = [f"root/group-{index}/leaf/file-{index}.json" for index in range(5000)]
        ancestors = acquisition._file_ancestor_paths(paths)
        self.assertEqual(len(ancestors), 10_001)
        self.assertIn("root", ancestors)
        self.assertIn("root/group-4999/leaf", ancestors)
        self.assertNotIn(paths[-1], ancestors)


class ChecksumTests(AcquisitionFixture):
    def make_checksum_tree(self, name: str = "checksums") -> tuple[Path, int]:
        revision = self.root / name
        (revision / acquisition._EXTRACTED / "sub").mkdir(parents=True)
        revision.chmod(0o700)
        (revision / acquisition._FORMAL_ARCHIVE).write_bytes(b"archive")
        (revision / acquisition._EXTRACTED / "z.txt").write_bytes(b"z")
        (revision / acquisition._EXTRACTED / "sub" / "a.txt").write_bytes(b"a")
        return revision, self.revision_fd(revision)

    def test_checksum_generation_is_sorted_exact_and_self_excluding(self) -> None:
        revision, fd = self.make_checksum_tree()
        try:
            report = acquisition._write_checksums(fd)
            verified = acquisition._verify_checksums(
                fd, protocol_state=acquisition._ProtocolState.FORMAL
            )
        finally:
            os.close(fd)
        paths = [path for path, _ in verified.entries]
        self.assertEqual(paths, sorted(paths, key=lambda value: value.encode("utf-8")))
        self.assertNotIn(acquisition._CHECKSUMS, paths)
        self.assertEqual(report, verified)
        self.assertEqual(stat.S_IMODE((revision / acquisition._CHECKSUMS).stat().st_mode), 0o600)

    def test_checksum_parser_rejects_loose_grammar_duplicates_and_order(self) -> None:
        digest = b"0" * 64
        cases = (
            digest + b" a\n",
            digest + b"  a",
            b"A" * 64 + b"  a\n",
            digest + b"  a\\b\n",
            digest + b"  e\xcc\x81\n",
            digest + b"  b\n" + digest + b"  a\n",
            digest + b"  a\n" + digest + b"  a\n",
            digest + b"  a\r\n",
        )
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(AcquisitionError):
                    acquisition._parse_checksum_bytes(content)

    def test_checksum_verification_detects_tamper_missing_and_extra_files(self) -> None:
        mutations = (
            lambda revision: (revision / acquisition._EXTRACTED / "z.txt").write_bytes(b"changed"),
            lambda revision: (revision / acquisition._EXTRACTED / "z.txt").unlink(),
            lambda revision: (revision / "extra.txt").write_bytes(b"extra"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                revision, fd = self.make_checksum_tree(f"checksums-{index}")
                try:
                    acquisition._write_checksums(fd)
                    mutate(revision)
                    with self.assertRaises(AcquisitionError):
                        acquisition._verify_checksums(
                            fd,
                            protocol_state=acquisition._ProtocolState.FORMAL,
                        )
                finally:
                    os.close(fd)

    def test_private_temp_is_ignored_only_for_its_exact_inode(self) -> None:
        _, fd = self.make_checksum_tree()
        try:
            acquisition._write_checksums(fd)
            temp = ".kairos-test.tmp"
            inode = acquisition._write_temp(fd, temp, b"private")
            acquisition._verify_checksums(
                fd,
                protocol_state=acquisition._ProtocolState.CURRENT_EXACT_TEMP,
                exact_temp=(temp, inode),
            )
            with self.assertRaises(AcquisitionError):
                acquisition._verify_checksums(
                    fd,
                    protocol_state=acquisition._ProtocolState.CURRENT_EXACT_TEMP,
                    exact_temp=(temp, (inode[0], inode[1] + 1)),
                )
        finally:
            os.close(fd)

    def test_publish_is_no_replace_and_failed_unlink_preserves_both_links(self) -> None:
        revision, fd = self.make_checksum_tree()
        try:
            (revision / "final").write_bytes(b"sentinel")
            inode = acquisition._write_temp(fd, "temp-one", b"new")
            with self.assertRaises(FileExistsError):
                acquisition._publish_temp(fd, "temp-one", "final", inode)
            self.assertEqual((revision / "final").read_bytes(), b"sentinel")
            inode = acquisition._write_temp(fd, "temp-two", b"new")
            original_unlink = os.unlink

            def fail_own_temp(path, *args, **kwargs):
                if path == "temp-two":
                    raise OSError("injected unlink failure")
                return original_unlink(path, *args, **kwargs)

            with mock.patch("kairos.acquisition.os.unlink", side_effect=fail_own_temp):
                with self.assertRaisesRegex(OSError, "injected"):
                    acquisition._publish_temp(fd, "temp-two", "final-two", inode)
            self.assertTrue((revision / "temp-two").exists())
            self.assertTrue((revision / "final-two").exists())
            self.assertEqual((revision / "temp-two").stat().st_ino, (revision / "final-two").stat().st_ino)
        finally:
            os.close(fd)

    def test_checksum_size_limit_and_fsync_failure_preserve_partial_state(self) -> None:
        revision, fd = self.make_checksum_tree()
        try:
            with mock.patch.object(acquisition, "CHECKSUM_LIMIT", 1):
                with self.assertRaisesRegex(AcquisitionError, "exceeds 64 MiB"):
                    acquisition._write_checksums(fd)
            before = set(path.name for path in revision.iterdir())
            with mock.patch("kairos.acquisition.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    acquisition._write_checksums(fd)
            after = set(path.name for path in revision.iterdir())
        finally:
            os.close(fd)
        self.assertTrue(any(name.startswith(".kairos-SHA256SUMS.") for name in after - before))

    def test_file_directory_and_root_fsync_failures_are_fatal(self) -> None:
        revision, fd = self.make_checksum_tree()
        try:
            snapshot = acquisition._scan_tree(
                fd, protocol_state=acquisition._ProtocolState.PRE_CHECKSUM
            )
            targets = {
                "file": (revision / acquisition._EXTRACTED / "z.txt").stat().st_ino,
                "directory": (revision / acquisition._EXTRACTED / "sub").stat().st_ino,
                "root": revision.stat().st_ino,
            }
            original_fsync = os.fsync
            for label, target_inode in targets.items():
                with self.subTest(label=label):
                    def fail_target(candidate_fd: int, target: int = target_inode):
                        if os.fstat(candidate_fd).st_ino == target:
                            raise OSError(f"injected {label} fsync failure")
                        return original_fsync(candidate_fd)

                    with mock.patch(
                        "kairos.acquisition.os.fsync", side_effect=fail_target
                    ):
                        with self.assertRaisesRegex(OSError, "injected"):
                            acquisition._fsync_formal_tree(fd, snapshot)
        finally:
            os.close(fd)

    def test_fingerprint_change_during_file_fsync_is_detected(self) -> None:
        revision, fd = self.make_checksum_tree()
        try:
            snapshot = acquisition._scan_tree(
                fd, protocol_state=acquisition._ProtocolState.PRE_CHECKSUM
            )
            target = revision / acquisition._EXTRACTED / "z.txt"
            target_inode = target.stat().st_ino
            original_fsync = os.fsync
            changed = False

            def mutate_after_fsync(candidate_fd: int):
                nonlocal changed
                result = original_fsync(candidate_fd)
                if not changed and os.fstat(candidate_fd).st_ino == target_inode:
                    changed = True
                    current = target.stat()
                    os.utime(
                        target,
                        ns=(current.st_atime_ns, current.st_mtime_ns + 1),
                    )
                return result

            with mock.patch(
                "kairos.acquisition.os.fsync", side_effect=mutate_after_fsync
            ):
                with self.assertRaisesRegex(AcquisitionError, "during fsync"):
                    acquisition._fsync_formal_tree(fd, snapshot)
        finally:
            os.close(fd)


class CompletionTests(AcquisitionFixture):
    def finalize_fixture(self):
        _, digest = self.make_stage()
        manifest = acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        return digest, manifest

    def make_open_completion_pair(
        self,
    ) -> tuple[acquisition._CompletionPair, int, int]:
        guard_fd = os.open(
            self.root / "guard-fd", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        final_fd = os.open(
            self.root / "final-fd", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        return (
            acquisition._CompletionPair(
                guard_fd=guard_fd,
                final_fd=final_fd,
                content=b"held",
            ),
            guard_fd,
            final_fd,
        )

    def assert_completion_pair_cleared(
        self, pair: acquisition._CompletionPair
    ) -> None:
        self.assertEqual(pair.guard_fd, -1)
        self.assertEqual(pair.final_fd, -1)
        self.assertIsNone(pair.fingerprint)
        self.assertEqual(pair.content, b"")

    def assert_canonical_close_failures(
        self, failed_paths: set[str], expected_message: str
    ) -> None:
        self.finalize_fixture()
        revision_fd = self.revision_fd(self.layout.revision)
        pair = acquisition._open_completion_pair(revision_fd)
        original_open = acquisition._open_relative_regular
        original_close = os.close
        canonical_fds: dict[str, int] = {}
        attempted: list[str] = []

        def record_canonical_open(
            parent_fd: int, path: str, flags: int = os.O_RDONLY
        ) -> int:
            opened_fd = original_open(parent_fd, path, flags)
            if path in (acquisition._COMPLETION_GUARD, acquisition._COMPLETION):
                canonical_fds[path] = opened_fd
            return opened_fd

        def inject_canonical_close(candidate_fd: int) -> None:
            path = next(
                (
                    name
                    for name, opened_fd in canonical_fds.items()
                    if candidate_fd == opened_fd
                ),
                None,
            )
            if path is not None:
                attempted.append(path)
                if path in failed_paths:
                    raise OSError(f"canonical {path} close failed")
            original_close(candidate_fd)

        try:
            with mock.patch(
                "kairos.acquisition._open_relative_regular",
                side_effect=record_canonical_open,
            ), mock.patch(
                "kairos.acquisition.os.close",
                side_effect=inject_canonical_close,
            ):
                with self.assertRaisesRegex(OSError, expected_message):
                    acquisition._assert_completion_pair_binding(
                        revision_fd, pair
                    )
        finally:
            for opened_fd in canonical_fds.values():
                try:
                    original_close(opened_fd)
                except OSError:
                    pass
            pair.close()
            original_close(revision_fd)
        self.assertEqual(
            attempted,
            [acquisition._COMPLETION, acquisition._COMPLETION_GUARD],
        )

    def test_finalize_and_offline_verify_complete_end_to_end(self) -> None:
        digest, manifest = self.finalize_fixture()
        verified = acquisition._verify_complete_layout(self.layout)
        self.assertEqual(manifest.values, verified.values)
        self.assertEqual(verified.values["archive_sha256"], digest)
        self.assertEqual(verified.values["kairos_git_commit"], TEST_COMMIT)
        self.assertEqual(
            len(verified.values["formal_tree_fingerprint_sha256"]), 64
        )
        self.assertEqual(stat.S_IMODE(self.layout.revision.stat().st_mode), 0o700)
        guard = self.layout.revision / acquisition._COMPLETION_GUARD
        final = self.layout.revision / acquisition._COMPLETION
        self.assertEqual(guard.stat().st_ino, final.stat().st_ino)
        self.assertEqual(guard.stat().st_nlink, 2)

    def test_finalize_rejects_existing_revision_without_replacement(self) -> None:
        _, manifest = self.finalize_fixture()
        completion_before = (self.layout.revision / acquisition._COMPLETION).read_bytes()
        with self.assertRaises(FileExistsError):
            acquisition._finalize_layout(
                self.layout, manifest.values["archive_sha256"], TEST_COMMIT
            )
        self.assertEqual((self.layout.revision / acquisition._COMPLETION).read_bytes(), completion_before)

    def test_extraction_failure_preserves_stage_and_partial_revision(self) -> None:
        archive, digest = self.make_stage()
        with mock.patch("kairos.acquisition.safe_extract_fd", side_effect=ValueError("injected extract")):
            with self.assertRaisesRegex(ValueError, "injected"):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertTrue(archive.exists())
        self.assertTrue((self.layout.revision / acquisition._FORMAL_ARCHIVE).exists())
        self.assertFalse((self.layout.revision / acquisition._COMPLETION).exists())

    def test_finalize_repeats_stage_validation_after_extraction(self) -> None:
        archive, digest = self.make_stage()
        original_validate = acquisition._validate_http
        calls = 0

        def mutate_before_second(stage_fd: int):
            nonlocal calls
            calls += 1
            if calls == 2:
                with archive.open("ab") as handle:
                    handle.write(b"late mutation")
            return original_validate(stage_fd)

        with mock.patch("kairos.acquisition._validate_http", side_effect=mutate_before_second):
            with self.assertRaises(AcquisitionError):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertTrue(self.layout.revision.exists())
        self.assertFalse((self.layout.revision / acquisition._COMPLETION).exists())

    def test_verify_rejects_checksum_content_tampering(self) -> None:
        self.finalize_fixture()
        target = self.layout.revision / acquisition._EXTRACTED / acquisition.UPSTREAM_ROOT / "README.md"
        target.write_bytes(b"tampered\n")
        with self.assertRaises(AcquisitionError):
            acquisition._verify_complete_layout(self.layout)

    def test_formal_tree_fingerprint_rejects_same_content_new_inode(self) -> None:
        self.finalize_fixture()
        target = (
            self.layout.revision
            / acquisition._EXTRACTED
            / acquisition.UPSTREAM_ROOT
            / "README.md"
        )
        replacement = target.with_name("README.replacement")
        replacement.write_bytes(target.read_bytes())
        replacement.chmod(stat.S_IMODE(target.stat().st_mode))
        os.replace(replacement, target)
        with self.assertRaisesRegex(AcquisitionError, "formal tree fingerprint"):
            acquisition._verify_complete_layout(self.layout)

    def test_guard_only_and_unrecognized_private_temp_are_rejected(self) -> None:
        self.finalize_fixture()
        private = self.layout.revision / ".kairos-unexpected.tmp"
        private.write_bytes(b"unexpected")
        with self.assertRaisesRegex(AcquisitionError, "protocol"):
            acquisition._verify_complete_layout(self.layout)
        private.unlink()
        (self.layout.revision / acquisition._COMPLETION).unlink()
        with self.assertRaises((AcquisitionError, FileNotFoundError)):
            acquisition._verify_complete_layout(self.layout)

    def test_canonical_revision_replacement_before_verify_return_is_rejected(self) -> None:
        self.finalize_fixture()
        original_assert = acquisition._assert_revision_binding_chain
        replacement = self.root / "replacement-revision"
        replacement.mkdir(mode=0o700)
        replaced = False

        def replace_before_chain(*args, **kwargs) -> None:
            nonlocal replaced
            if not replaced:
                replaced = True
                self.layout.revision.rename(self.root / "moved-revision")
                replacement.rename(self.layout.revision)
            original_assert(*args, **kwargs)

        with mock.patch(
            "kairos.acquisition._assert_revision_binding_chain",
            side_effect=replace_before_chain,
        ):
            with self.assertRaisesRegex(
                AcquisitionError, "project root|canonical revision"
            ):
                acquisition._verify_complete_layout(self.layout)
        self.assertTrue(replaced)

    def test_canonical_revision_replacement_before_finalize_return_is_rejected(self) -> None:
        _, digest = self.make_stage()
        original_assert = acquisition._assert_revision_binding_chain
        replacement = self.root / "replacement-finalized-revision"
        replacement.mkdir(mode=0o700)
        replaced = False

        def replace_before_chain(*args, **kwargs) -> None:
            nonlocal replaced
            if not replaced:
                replaced = True
                self.layout.revision.rename(self.root / "moved-finalized-revision")
                replacement.rename(self.layout.revision)
            original_assert(*args, **kwargs)

        with mock.patch(
            "kairos.acquisition._assert_revision_binding_chain",
            side_effect=replace_before_chain,
        ):
            with self.assertRaisesRegex(
                AcquisitionError, "project root|canonical revision"
            ):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertTrue(replaced)

    def test_pair_swap_after_held_open_is_rejected(self) -> None:
        self.finalize_fixture()
        original_scan = acquisition._scan_tree
        published_scans = 0

        def swap_after_terminal_published_scan(*args, **kwargs):
            nonlocal published_scans
            snapshot = original_scan(*args, **kwargs)
            if kwargs.get(
                "protocol_state"
            ) is acquisition._ProtocolState.PUBLISHED_PAIR:
                published_scans += 1
            if published_scans == 5:
                guard = self.layout.revision / acquisition._COMPLETION_GUARD
                final = self.layout.revision / acquisition._COMPLETION
                content = final.read_bytes()
                final.unlink()
                guard.unlink()
                guard.write_bytes(content)
                guard.chmod(0o600)
                os.link(guard, final)
            return snapshot

        with mock.patch(
            "kairos.acquisition._scan_tree",
            side_effect=swap_after_terminal_published_scan,
        ):
            with self.assertRaisesRegex(AcquisitionError, "completion"):
                acquisition._verify_complete_layout(self.layout)
        self.assertEqual(published_scans, 5)

    def test_intermediate_parent_replacement_is_rejected(self) -> None:
        self.layout = acquisition._Layout(
            self.root, "stage-nested", "data/raw/revision"
        )
        (self.root / "data/raw").mkdir(parents=True)
        (self.root / "replacement-data/raw").mkdir(parents=True)
        _, digest = self.make_stage()
        acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        original_assert = acquisition._assert_revision_binding_chain
        replaced = False

        def replace_parent_before_chain(*args, **kwargs) -> None:
            nonlocal replaced
            if not replaced:
                replaced = True
                (self.root / "data").rename(self.root / "moved-data")
                (self.root / "replacement-data").rename(self.root / "data")
            original_assert(*args, **kwargs)

        with mock.patch(
            "kairos.acquisition._assert_revision_binding_chain",
            side_effect=replace_parent_before_chain,
        ):
            with self.assertRaisesRegex(
                AcquisitionError, "project root|parent component"
            ):
                acquisition._verify_complete_layout(self.layout)
        self.assertTrue(replaced)

    def test_project_root_replacement_is_rejected(self) -> None:
        self.finalize_fixture()
        original_assert = acquisition._assert_revision_binding_chain
        moved_root = self.root.with_name("project-moved")
        replaced = False

        def replace_root_before_chain(*args, **kwargs) -> None:
            nonlocal replaced
            if not replaced:
                replaced = True
                self.root.rename(moved_root)
                self.root.mkdir(mode=0o700)
            original_assert(*args, **kwargs)

        with mock.patch(
            "kairos.acquisition._assert_revision_binding_chain",
            side_effect=replace_root_before_chain,
        ):
            with self.assertRaisesRegex(AcquisitionError, "project root"):
                acquisition._verify_complete_layout(self.layout)
        self.assertTrue(replaced)

    def test_late_root_directory_addition_is_rejected_by_terminal_binding(self) -> None:
        self.finalize_fixture()
        original_assert = acquisition._assert_completion_pair_binding
        before_nlink = self.layout.revision.stat().st_nlink
        mutated = False

        def add_after_terminal_scan(
            revision_fd: int, pair: acquisition._CompletionPair
        ) -> None:
            nonlocal mutated
            original_assert(revision_fd, pair)
            if not mutated:
                mutated = True
                os.mkdir("late-directory", dir_fd=revision_fd)

        with mock.patch(
            "kairos.acquisition._assert_completion_pair_binding",
            side_effect=add_after_terminal_scan,
        ):
            with self.assertRaisesRegex(AcquisitionError, "canonical revision"):
                acquisition._verify_complete_layout(self.layout)
        self.assertTrue(mutated)
        self.assertEqual(self.layout.revision.stat().st_nlink, before_nlink + 1)

    def test_late_root_regular_file_is_rejected_by_terminal_binding(self) -> None:
        self.finalize_fixture()
        original_assert = acquisition._assert_completion_pair_binding
        before_nlink = self.layout.revision.stat().st_nlink
        mutated = False

        def add_after_terminal_scan(
            revision_fd: int, pair: acquisition._CompletionPair
        ) -> None:
            nonlocal mutated
            original_assert(revision_fd, pair)
            if not mutated:
                mutated = True
                fd = os.open(
                    "late-regular",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=revision_fd,
                )
                os.close(fd)

        with mock.patch(
            "kairos.acquisition._assert_completion_pair_binding",
            side_effect=add_after_terminal_scan,
        ):
            with self.assertRaisesRegex(AcquisitionError, "canonical revision"):
                acquisition._verify_complete_layout(self.layout)
        self.assertTrue(mutated)
        self.assertEqual(self.layout.revision.stat().st_nlink, before_nlink)

    def test_canonical_close_attempts_guard_after_final_failure(self) -> None:
        self.assert_canonical_close_failures(
            {acquisition._COMPLETION},
            "canonical completion-manifest.json close failed",
        )

    def test_canonical_close_reports_guard_failure_after_final_close(self) -> None:
        self.assert_canonical_close_failures(
            {acquisition._COMPLETION_GUARD},
            "canonical completion-manifest.guard close failed",
        )

    def test_canonical_close_attempts_both_when_both_fail(self) -> None:
        self.assert_canonical_close_failures(
            {acquisition._COMPLETION, acquisition._COMPLETION_GUARD},
            "canonical completion-manifest.json close failed",
        )

    def test_canonical_close_preserves_active_validation_exception(self) -> None:
        self.finalize_fixture()
        revision_fd = self.revision_fd(self.layout.revision)
        pair = acquisition._open_completion_pair(revision_fd)
        original_open = acquisition._open_relative_regular
        original_read = acquisition._stable_pair_read
        original_close = os.close
        canonical_fds: dict[str, int] = {}
        attempted: list[str] = []
        read_calls = 0

        def record_canonical_open(
            parent_fd: int, path: str, flags: int = os.O_RDONLY
        ) -> int:
            opened_fd = original_open(parent_fd, path, flags)
            if path in (acquisition._COMPLETION_GUARD, acquisition._COMPLETION):
                canonical_fds[path] = opened_fd
            return opened_fd

        def fail_canonical_validation(*args, **kwargs) -> bytes:
            nonlocal read_calls
            read_calls += 1
            if read_calls == 3:
                raise AcquisitionError("active canonical validation failure")
            return original_read(*args, **kwargs)

        def fail_both_canonical_closes(candidate_fd: int) -> None:
            path = next(
                (
                    name
                    for name, opened_fd in canonical_fds.items()
                    if candidate_fd == opened_fd
                ),
                None,
            )
            if path is not None:
                attempted.append(path)
                raise OSError(f"canonical {path} close failed")
            original_close(candidate_fd)

        try:
            with mock.patch(
                "kairos.acquisition._open_relative_regular",
                side_effect=record_canonical_open,
            ), mock.patch(
                "kairos.acquisition._stable_pair_read",
                side_effect=fail_canonical_validation,
            ), mock.patch(
                "kairos.acquisition.os.close",
                side_effect=fail_both_canonical_closes,
            ):
                with self.assertRaises(AcquisitionError) as caught:
                    acquisition._assert_completion_pair_binding(
                        revision_fd, pair
                    )
        finally:
            for opened_fd in canonical_fds.values():
                original_close(opened_fd)
            pair.close()
            original_close(revision_fd)
        self.assertEqual(
            str(caught.exception), "active canonical validation failure"
        )
        self.assertEqual(
            attempted,
            [acquisition._COMPLETION, acquisition._COMPLETION_GUARD],
        )

    def test_canonical_partial_open_preserves_original_failure(self) -> None:
        self.finalize_fixture()
        revision_fd = self.revision_fd(self.layout.revision)
        pair = acquisition._open_completion_pair(revision_fd)
        original_open = acquisition._open_relative_regular
        original_close = os.close
        guard_fd = -1
        attempted: list[int] = []

        def fail_canonical_final_open(
            parent_fd: int, path: str, flags: int = os.O_RDONLY
        ) -> int:
            nonlocal guard_fd
            if path == acquisition._COMPLETION:
                raise FileNotFoundError("canonical final open failure")
            opened_fd = original_open(parent_fd, path, flags)
            if path == acquisition._COMPLETION_GUARD:
                guard_fd = opened_fd
            return opened_fd

        def fail_canonical_guard_cleanup(candidate_fd: int) -> None:
            if candidate_fd == guard_fd:
                attempted.append(candidate_fd)
                raise OSError("canonical guard cleanup close failed")
            original_close(candidate_fd)

        try:
            with mock.patch(
                "kairos.acquisition._open_relative_regular",
                side_effect=fail_canonical_final_open,
            ), mock.patch(
                "kairos.acquisition.os.close",
                side_effect=fail_canonical_guard_cleanup,
            ):
                with self.assertRaises(FileNotFoundError) as caught:
                    acquisition._assert_completion_pair_binding(
                        revision_fd, pair
                    )
        finally:
            if guard_fd >= 0:
                original_close(guard_fd)
            pair.close()
            original_close(revision_fd)
        self.assertEqual(str(caught.exception), "canonical final open failure")
        self.assertEqual(attempted, [guard_fd])

    def test_completion_pair_close_attempts_guard_after_final_failure(self) -> None:
        pair, guard_fd, final_fd = self.make_open_completion_pair()
        original_close = os.close
        attempted: list[int] = []

        def fail_final(candidate_fd: int) -> None:
            attempted.append(candidate_fd)
            if candidate_fd == final_fd:
                raise OSError("final close failed")
            original_close(candidate_fd)

        try:
            with mock.patch("kairos.acquisition.os.close", side_effect=fail_final):
                with self.assertRaisesRegex(OSError, "final close failed"):
                    pair.close()
        finally:
            original_close(final_fd)
        self.assertEqual(attempted, [final_fd, guard_fd])
        self.assert_completion_pair_cleared(pair)

    def test_completion_pair_close_reports_guard_failure_after_final_close(self) -> None:
        pair, guard_fd, final_fd = self.make_open_completion_pair()
        original_close = os.close
        attempted: list[int] = []

        def fail_guard(candidate_fd: int) -> None:
            attempted.append(candidate_fd)
            if candidate_fd == guard_fd:
                raise OSError("guard close failed")
            original_close(candidate_fd)

        try:
            with mock.patch("kairos.acquisition.os.close", side_effect=fail_guard):
                with self.assertRaisesRegex(OSError, "guard close failed"):
                    pair.close()
        finally:
            original_close(guard_fd)
        self.assertEqual(attempted, [final_fd, guard_fd])
        self.assert_completion_pair_cleared(pair)

    def test_completion_pair_close_attempts_both_when_both_fail(self) -> None:
        pair, guard_fd, final_fd = self.make_open_completion_pair()
        original_close = os.close
        attempted: list[int] = []

        def fail_both(candidate_fd: int) -> None:
            attempted.append(candidate_fd)
            if candidate_fd == final_fd:
                raise OSError("final close failed")
            if candidate_fd == guard_fd:
                raise OSError("guard close failed")
            original_close(candidate_fd)

        try:
            with mock.patch("kairos.acquisition.os.close", side_effect=fail_both):
                with self.assertRaisesRegex(OSError, "final close failed"):
                    pair.close()
        finally:
            original_close(final_fd)
            original_close(guard_fd)
        self.assertEqual(attempted, [final_fd, guard_fd])
        self.assert_completion_pair_cleared(pair)

    def test_completion_pair_close_preserves_active_exception(self) -> None:
        pair, guard_fd, final_fd = self.make_open_completion_pair()
        original_close = os.close
        attempted: list[int] = []

        def fail_both(candidate_fd: int) -> None:
            attempted.append(candidate_fd)
            if candidate_fd in (final_fd, guard_fd):
                raise OSError("injected close failure")
            original_close(candidate_fd)

        try:
            with mock.patch("kairos.acquisition.os.close", side_effect=fail_both):
                with self.assertRaises(ValueError) as caught:
                    with pair:
                        raise ValueError("body failure")
        finally:
            original_close(final_fd)
            original_close(guard_fd)
        self.assertEqual(str(caught.exception), "body failure")
        self.assertEqual(attempted, [final_fd, guard_fd])
        self.assert_completion_pair_cleared(pair)

    def test_completion_pair_partial_open_preserves_original_failure(self) -> None:
        revision = self.root / "partial-open"
        revision.mkdir(mode=0o700)
        (revision / acquisition._COMPLETION_GUARD).write_bytes(b"guard")
        revision_fd = self.revision_fd(revision)
        original_open = acquisition._open_relative_regular
        original_close = os.close
        guard_fd = -1
        attempted: list[int] = []

        def fail_final_open(parent_fd: int, path: str, flags: int = os.O_RDONLY) -> int:
            nonlocal guard_fd
            if path == acquisition._COMPLETION:
                raise FileNotFoundError("original final open failure")
            opened_fd = original_open(parent_fd, path, flags)
            if path == acquisition._COMPLETION_GUARD:
                guard_fd = opened_fd
            return opened_fd

        def fail_guard_cleanup(candidate_fd: int) -> None:
            attempted.append(candidate_fd)
            if candidate_fd == guard_fd:
                raise OSError("guard cleanup close failed")
            original_close(candidate_fd)

        try:
            with mock.patch(
                "kairos.acquisition._open_relative_regular",
                side_effect=fail_final_open,
            ), mock.patch(
                "kairos.acquisition.os.close", side_effect=fail_guard_cleanup
            ):
                with self.assertRaises(FileNotFoundError) as caught:
                    acquisition._open_completion_pair(revision_fd)
        finally:
            if guard_fd >= 0:
                original_close(guard_fd)
            original_close(revision_fd)
        self.assertEqual(str(caught.exception), "original final open failure")
        self.assertIn(guard_fd, attempted)

    def test_extra_root_entry_before_checksum_prevents_publication(self) -> None:
        _, digest = self.make_stage()
        original_extract = acquisition.safe_extract_fd

        def add_extra_after_extract(*args, **kwargs):
            result = original_extract(*args, **kwargs)
            revision_fd = args[1]
            extra_fd = os.open(
                "protocol-extra",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=revision_fd,
            )
            os.close(extra_fd)
            return result

        with mock.patch(
            "kairos.acquisition.safe_extract_fd",
            side_effect=add_extra_after_extract,
        ):
            with self.assertRaisesRegex(AcquisitionError, "protocol"):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertFalse((self.layout.revision / acquisition._CHECKSUMS).exists())
        self.assertFalse(
            (self.layout.revision / acquisition._COMPLETION_GUARD).exists()
        )
        self.assertFalse((self.layout.revision / acquisition._COMPLETION).exists())

    def test_extra_root_directory_before_checksum_prevents_publication(self) -> None:
        _, digest = self.make_stage()
        original_extract = acquisition.safe_extract_fd

        def add_extra_directory_after_extract(*args, **kwargs):
            result = original_extract(*args, **kwargs)
            os.mkdir("protocol-extra-directory", dir_fd=args[1])
            return result

        with mock.patch(
            "kairos.acquisition.safe_extract_fd",
            side_effect=add_extra_directory_after_extract,
        ):
            with self.assertRaisesRegex(AcquisitionError, "protocol"):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertFalse((self.layout.revision / acquisition._CHECKSUMS).exists())
        self.assertFalse(
            (self.layout.revision / acquisition._COMPLETION_GUARD).exists()
        )
        self.assertFalse((self.layout.revision / acquisition._COMPLETION).exists())

    def test_completion_publication_protocol_order_and_final_link_source(self) -> None:
        _, digest = self.make_stage()
        original_link = os.link
        original_unlink = os.unlink
        original_fsync = os.fsync
        original_scan = acquisition._scan_tree
        events: list[str] = []

        def record_link(source, destination, *args, **kwargs):
            if destination == acquisition._COMPLETION_GUARD:
                events.append("link-guard")
            elif destination == acquisition._COMPLETION:
                self.assertEqual(source, acquisition._COMPLETION_GUARD)
                events.append("link-final-from-guard")
            return original_link(source, destination, *args, **kwargs)

        def record_unlink(path, *args, **kwargs):
            if isinstance(path, str) and path.startswith(
                ".kairos-completion-manifest."
            ):
                events.append("unlink-temp")
            return original_unlink(path, *args, **kwargs)

        def record_fsync(candidate_fd: int):
            if stat.S_ISDIR(os.fstat(candidate_fd).st_mode):
                try:
                    guard = os.stat(
                        acquisition._COMPLETION_GUARD,
                        dir_fd=candidate_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    guard = None
                if guard is not None:
                    try:
                        os.stat(
                            acquisition._COMPLETION,
                            dir_fd=candidate_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        events.append("fsync-guard-only")
                    else:
                        events.append("fsync-pair")
            return original_fsync(candidate_fd)

        def record_scan(*args, **kwargs):
            state = kwargs.get("protocol_state")
            if state is acquisition._ProtocolState.GUARD_ONLY:
                events.append("scan-guard-only")
            return original_scan(*args, **kwargs)

        with mock.patch(
            "kairos.acquisition.os.link", side_effect=record_link
        ), mock.patch(
            "kairos.acquisition.os.unlink", side_effect=record_unlink
        ), mock.patch(
            "kairos.acquisition.os.fsync", side_effect=record_fsync
        ), mock.patch(
            "kairos.acquisition._scan_tree", side_effect=record_scan
        ):
            acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)

        required = [
            "link-guard",
            "unlink-temp",
            "scan-guard-only",
            "fsync-guard-only",
            "scan-guard-only",
            "link-final-from-guard",
            "fsync-pair",
        ]
        cursor = 0
        for event in events:
            if cursor < len(required) and event == required[cursor]:
                cursor += 1
        self.assertEqual(cursor, len(required), events)

    def test_between_fsync_and_completion_link_mutation_leaves_invalid_guarded_state(self) -> None:
        _, digest = self.make_stage()
        original_link = os.link
        mutated = False

        def mutate_at_guard(source, destination, *args, **kwargs):
            nonlocal mutated
            result = original_link(source, destination, *args, **kwargs)
            if destination == acquisition._COMPLETION_GUARD and not mutated:
                mutated = True
                target = (
                    self.layout.revision
                    / acquisition._EXTRACTED
                    / acquisition.UPSTREAM_ROOT
                    / "README.md"
                )
                target.write_bytes(b"mutated between fsync and link\n")
            return result

        with mock.patch("kairos.acquisition.os.link", side_effect=mutate_at_guard):
            with self.assertRaisesRegex(AcquisitionError, "formal tree changed"):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertTrue(
            (self.layout.revision / acquisition._COMPLETION_GUARD).exists()
        )
        self.assertEqual(
            (self.layout.revision / acquisition._COMPLETION_GUARD).stat().st_nlink,
            1,
        )
        self.assertFalse((self.layout.revision / acquisition._COMPLETION).exists())
        self.assertFalse(
            any(
                path.name.startswith(".kairos-completion-manifest.")
                for path in self.layout.revision.iterdir()
            )
        )
        with self.assertRaises((AcquisitionError, FileNotFoundError)):
            acquisition._verify_complete_layout(self.layout)

    def test_final_root_fsync_failure_can_leave_a_fully_verifiable_pair(self) -> None:
        _, digest = self.make_stage()
        original_link = os.link
        original_fsync = os.fsync
        final_linked = False
        injected = False

        def track_link(source, destination, *args, **kwargs):
            nonlocal final_linked
            result = original_link(source, destination, *args, **kwargs)
            if destination == acquisition._COMPLETION:
                final_linked = True
            return result

        def fail_final_root_fsync(candidate_fd: int):
            nonlocal injected
            if (
                final_linked
                and not injected
                and stat.S_ISDIR(os.fstat(candidate_fd).st_mode)
            ):
                injected = True
                raise OSError("injected final root fsync failure")
            return original_fsync(candidate_fd)

        with mock.patch(
            "kairos.acquisition.os.link", side_effect=track_link
        ), mock.patch(
            "kairos.acquisition.os.fsync", side_effect=fail_final_root_fsync
        ):
            with self.assertRaisesRegex(OSError, "final root"):
                acquisition._finalize_layout(self.layout, digest, TEST_COMMIT)
        self.assertTrue(injected)
        verified = acquisition._verify_complete_layout(self.layout)
        self.assertEqual(verified.values["archive_sha256"], digest)

    def test_verify_rejects_manifest_tampering_extra_files_and_hardlinks(self) -> None:
        _, manifest = self.finalize_fixture()
        completion = self.layout.revision / acquisition._COMPLETION
        values = dict(manifest.values)
        values["status"] = "PRELIMINARY"
        completion.write_text(json.dumps(values), encoding="utf-8")
        with self.assertRaises(AcquisitionError):
            acquisition._verify_complete_layout(self.layout)

        completion.write_text(
            acquisition.canonical_json(manifest.values) + "\n", encoding="utf-8"
        )
        (self.layout.revision / "extra.txt").write_bytes(b"extra")
        with self.assertRaises(AcquisitionError):
            acquisition._verify_complete_layout(self.layout)
        (self.layout.revision / "extra.txt").unlink()
        os.link(completion, self.layout.revision / "completion-link")
        with self.assertRaises(AcquisitionError):
            acquisition._verify_complete_layout(self.layout)

    def test_verify_rejects_untruthful_manifest_archive_metadata(self) -> None:
        _, manifest = self.finalize_fixture()
        completion = self.layout.revision / acquisition._COMPLETION
        cases = (
            ("size_download", 1),
            ("archive_member_count", 1),
            ("archive_declared_expanded_bytes", 1),
        )
        for key, increment in cases:
            with self.subTest(key=key):
                values = dict(manifest.values)
                values[key] += increment
                completion.write_text(
                    acquisition.canonical_json(values) + "\n", encoding="utf-8"
                )
                with self.assertRaises(AcquisitionError):
                    acquisition._verify_complete_layout(self.layout)

    def test_verify_requires_private_revision_mode(self) -> None:
        self.finalize_fixture()
        self.layout.revision.chmod(0o755)
        with self.assertRaisesRegex(AcquisitionError, "0700"):
            acquisition._verify_complete_layout(self.layout)

    def test_completion_manifest_parser_is_exact_and_rejects_duplicate_keys(self) -> None:
        _, manifest = self.finalize_fixture()
        values = dict(manifest.values)
        values["unexpected"] = 1
        with self.assertRaises(AcquisitionError):
            acquisition._validate_manifest(values)
        duplicate = b'{"status":"COMPLETE","status":"COMPLETE"}'
        with self.assertRaisesRegex(AcquisitionError, "duplicate"):
            acquisition._strict_object(duplicate, {"status"}, "completion manifest")

    def test_cli_has_fixed_layout_and_rejects_paths_and_invalid_hex(self) -> None:
        with self.assertRaises(SystemExit):
            acquisition._parser().parse_args(
                ["verify", "--project-root", os.fspath(self.root)]
            )
        self.assertEqual(
            acquisition.main(["validate-stage", "--expected-sha256", "A" * 64]),
            2,
        )
        self.assertEqual(
            acquisition.main(
                [
                    "finalize",
                    "--expected-sha256",
                    "0" * 64,
                    "--kairos-commit",
                    "../" + "0" * 37,
                ]
            ),
            2,
        )
        self.assertFalse((self.root / ("0" * 64)).exists())


if __name__ == "__main__":
    unittest.main()
