import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from kairos.ids import canonical_json
from kairos import gsm8k


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")
ADAPTER_COMMIT = "a" * 40
_TEMP_LABELS = {
    "source-train.jsonl": "source-train",
    "source-test.jsonl": "source-test",
    "examples-train.jsonl": "example-train",
    "examples-test.jsonl": "example-test",
    "processed-manifest.json": "processed-manifest",
}


def _jsonl(values):
    return b"".join(
        canonical_json(value).encode("utf-8") + b"\n" for value in values
    )


def _replace_same_content(path):
    path = Path(path)
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_bytes(path.read_bytes())
    os.chmod(replacement, stat.S_IMODE(path.stat().st_mode))
    os.replace(replacement, path)


def _artifact_temp(target, artifact):
    matches = list(Path(target).glob(f".kairos-{_TEMP_LABELS[artifact]}.*.tmp"))
    if len(matches) != 1:
        raise AssertionError(f"expected one synthetic temp for {artifact}")
    return matches[0]


class SyntheticLayout:
    def __init__(self, train=None, test=None):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(TEST_TMP, 0o700)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-gsm8k-test-", dir=TEST_TMP
        )
        self.root = Path(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.raw_revision_rel = f"data/raw/gsm8k/{gsm8k.REVISION}"
        self.target_parent_rel = f"data/processed/gsm8k/{gsm8k.REVISION}"
        self.target_leaf = "source-record-v1"
        self.source_paths = {
            "train": "extracted/upstream/grade_school_math/data/train.jsonl",
            "test": "extracted/upstream/grade_school_math/data/test.jsonl",
        }
        self.train = train or [
            {"question": "one plus one?", "answer": "work #### 2"},
            {"question": "two plus two?", "answer": "work #### 4"},
        ]
        self.test = test or [
            {"question": "three plus three?", "answer": "work #### 6"}
        ]
        self._mkdir_private(self.raw_revision_rel)
        self.raw_bytes = {
            "train": _jsonl(self.train),
            "test": _jsonl(self.test),
        }
        for split in ("train", "test"):
            path = self.root / self.raw_revision_rel / self.source_paths[split]
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._make_private(path.parent)
            path.write_bytes(self.raw_bytes[split])
            os.chmod(path, 0o600)
        completion = self.root / self.raw_revision_rel / "completion-manifest.json"
        self.completion_content = b'{"synthetic":true}\n'
        completion.write_bytes(self.completion_content)
        os.chmod(completion, 0o600)
        sources = {
            split: gsm8k._SourceBinding(
                split,
                self.source_paths[split],
                hashlib.sha256(self.raw_bytes[split]).hexdigest(),
                len(self.raw_bytes[split]),
                len(self.train if split == "train" else self.test),
            )
            for split in ("train", "test")
        }
        self.acquisition = gsm8k._AcquisitionBinding(
            provenance_commit="b" * 40,
            completion_manifest_path=(
                f"{self.raw_revision_rel}/completion-manifest.json"
            ),
            completion_manifest_sha256=hashlib.sha256(
                self.completion_content
            ).hexdigest(),
            sha256sums_sha256="c" * 64,
            formal_tree_fingerprint_sha256="d" * 64,
        )
        self.layout = gsm8k._Layout(
            self.root,
            self.raw_revision_rel,
            self.target_parent_rel,
            self.target_leaf,
            self.acquisition,
            sources,
        )
        self.values = {
            "status": "COMPLETE",
            "dataset": "gsm8k",
            "revision": gsm8k.REVISION,
            "kairos_git_commit": self.acquisition.provenance_commit,
            "sha256sums_sha256": self.acquisition.sha256sums_sha256,
            "formal_tree_fingerprint_sha256": (
                self.acquisition.formal_tree_fingerprint_sha256
            ),
            "train_path": self.source_paths["train"],
            "train_count": len(self.train),
            "test_path": self.source_paths["test"],
            "test_count": len(self.test),
        }
        self.verifier_calls = 0
        self.fail_on_call = None

    @property
    def target(self):
        return self.root / self.target_parent_rel / self.target_leaf

    def _make_private(self, path):
        current = self.root
        for component in path.relative_to(self.root).parts:
            current /= component
            os.chmod(current, 0o700)

    def _mkdir_private(self, relative):
        path = self.root / relative
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._make_private(path)
        return path

    def verifier(self):
        self.verifier_calls += 1
        if self.verifier_calls == self.fail_on_call:
            raise gsm8k.Gsm8kError("synthetic acquisition failure")
        return dict(self.values)

    def prepare(self):
        return gsm8k._prepare_layout(self.layout, ADAPTER_COMMIT, self.verifier)

    def verify(self):
        return gsm8k._verify_layout(self.layout, self.verifier)

    def close(self):
        self.temporary.cleanup()


class SyntheticTestCase(unittest.TestCase):
    fixture = None

    def make_fixture(self, **kwargs):
        self.fixture = SyntheticLayout(**kwargs)
        return self.fixture

    def tearDown(self):
        if self.fixture is not None:
            self.fixture.close()


class AnswerParserTests(unittest.TestCase):
    def test_single_delimiter_ascii_trim_is_reversible(self):
        answer = "reasoning\n#### \t42\r"
        parsed = gsm8k.parse_gsm8k_answer(answer)
        self.assertEqual(parsed.target, "42")
        self.assertEqual(parsed.reconstruct(), answer)
        self.assertEqual(parsed.separator, "####")

    def test_unicode_only_target_is_rejected(self):
        for suffix in ("\u00a0", "\u2003", "\u00a0\u2003"):
            with self.subTest(suffix=repr(suffix)):
                with self.assertRaises(gsm8k.Gsm8kError):
                    gsm8k.parse_gsm8k_answer("reason####" + suffix)

    def test_unicode_whitespace_is_preserved_when_target_has_content(self):
        parsed = gsm8k.parse_gsm8k_answer("reason#### \tX\u00a0\r")
        self.assertEqual(parsed.target, "X\u00a0")

    def test_bad_delimiters_and_prefixes_are_rejected(self):
        for answer in (
            "no delimiter",
            "a####b####c",
            "#### 4",
            " \t\r#### 4",
            4,
        ):
            with self.subTest(answer=answer):
                with self.assertRaises((TypeError, ValueError)):
                    gsm8k.parse_gsm8k_answer(answer)


class SourceRecordTests(unittest.TestCase):
    def test_source_record_round_trip_and_exact_keys(self):
        binding = gsm8k._SourceBinding(
            "train", "upstream/train.jsonl", "1" * 64, 29, 1
        )
        source, _ = gsm8k._expected_records(
            b'{"answer":"work #### 2","question":"q"}\n', binding, 1
        )
        self.assertEqual(gsm8k.Gsm8kSourceRecord.from_dict(source.to_dict()), source)
        for value in (
            {**source.to_dict(), "extra": 1},
            {key: item for key, item in source.to_dict().items() if key != "answer"},
        ):
            with self.subTest(keys=sorted(value)):
                with self.assertRaises(gsm8k.Gsm8kError):
                    gsm8k.Gsm8kSourceRecord.from_dict(value)

    def test_identity_is_literal_and_raw_line_bound(self):
        raw = b'{"question":"q","answer":"work #### 2"}\n'
        binding = gsm8k._SourceBinding(
            "test", "upstream/test.jsonl", hashlib.sha256(raw).hexdigest(), len(raw), 1
        )
        source, example = gsm8k._expected_records(raw, binding, 1)
        changed, _ = gsm8k._expected_records(raw.replace(b'"q"', b'"Q"'), binding, 1)
        self.assertEqual(source.dataset, "gsm8k")
        self.assertEqual(source.split.official, "test")
        self.assertIsNone(source.split.internal)
        self.assertEqual(source.source_id, example.source_id)
        self.assertEqual(source.source_sha256, hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(source.source_id, changed.source_id)

    def test_strict_raw_grammar_rejects_malformed_records(self):
        invalid = (
            b'{"question":"q","answer":"work #### 2"}',
            b'{"question":"q","answer":"a","answer":"b"}\n',
            b'{"question":"q","answer":"work #### 2","extra":1}\n',
            b'{"question":"","answer":"work #### 2"}\n',
            b'{"question":"q","answer":NaN}\n',
            b'\xff\n',
        )
        for value in invalid:
            with self.subTest(value=value[:50]):
                with self.assertRaises(gsm8k.Gsm8kError):
                    gsm8k._raw_record(value, "train", 1)

    def test_raw_line_exact_limit_passes_and_limit_plus_one_fails(self):
        prefix = b'{"answer":"work #### 2","question":"'
        suffix = b'"}\n'
        padding = gsm8k._RAW_LINE_LIMIT - len(prefix) - len(suffix)
        exact = prefix + (b"x" * padding) + suffix
        self.assertEqual(len(exact), gsm8k._RAW_LINE_LIMIT)
        question, answer = gsm8k._raw_record(exact, "train", 1)
        self.assertEqual(len(question), padding)
        self.assertEqual(answer, "work #### 2")
        with self.assertRaises(gsm8k.Gsm8kError):
            gsm8k._raw_record(
                prefix + (b"x" * (padding + 1)) + suffix, "train", 1
            )


class LayoutAndManifestTests(SyntheticTestCase):
    def test_prepare_and_verify_synthetic_layout(self):
        fixture = self.make_fixture()
        manifest = fixture.prepare()
        self.assertEqual(manifest["status"], "COMPLETE")
        self.assertEqual(manifest["adapter"]["git_commit"], ADAPTER_COMMIT)
        self.assertEqual(set(path.name for path in fixture.target.iterdir()), gsm8k._FINAL_NAMES)
        for path in fixture.target.iterdir():
            value = path.stat()
            self.assertEqual(stat.S_IMODE(value.st_mode), 0o600)
            self.assertEqual(value.st_nlink, 1)
        observed = fixture.verify()
        self.assertEqual(observed, manifest)
        self.assertGreaterEqual(fixture.verifier_calls, 6)

    def test_two_conversions_are_byte_identical(self):
        first = self.make_fixture()
        first.prepare()
        first_bytes = {
            name: (first.target / name).read_bytes() for name in gsm8k._FINAL_NAMES
        }
        second = SyntheticLayout()
        try:
            second.prepare()
            second_bytes = {
                name: (second.target / name).read_bytes()
                for name in gsm8k._FINAL_NAMES
            }
        finally:
            second.close()
        self.assertEqual(first_bytes, second_bytes)

    def test_duplicate_statistics_are_fixed(self):
        fixture = self.make_fixture(
            train=[
                {"question": "same", "answer": "work #### 1"},
                {"question": "same", "answer": "work #### 1"},
                {"question": "same", "answer": "other #### 2"},
                {"question": "unique", "answer": "work #### 3"},
            ]
        )
        duplicates = fixture.prepare()["duplicates"]
        self.assertEqual(duplicates["train_question_group_count"], 1)
        self.assertEqual(duplicates["train_question_record_count"], 3)
        self.assertEqual(duplicates["train_raw_record_group_count"], 1)
        self.assertEqual(duplicates["train_raw_record_record_count"], 2)

    def test_target_leaf_is_no_overwrite(self):
        fixture = self.make_fixture()
        fixture._mkdir_private(f"{fixture.target_parent_rel}/{fixture.target_leaf}")
        marker = fixture.target / "owned"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            fixture.prepare()
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_existing_private_parents_are_reused(self):
        fixture = self.make_fixture()
        fixture._mkdir_private(fixture.target_parent_rel)
        fixture.prepare()
        self.assertTrue((fixture.target / gsm8k._MANIFEST).is_file())

    def test_nonprivate_processed_parent_is_rejected(self):
        fixture = self.make_fixture()
        processed = fixture.root / "data/processed"
        processed.mkdir()
        os.chmod(processed, 0o755)
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.prepare()

    def test_symlinked_processed_parent_is_rejected(self):
        fixture = self.make_fixture()
        outside = fixture._mkdir_private("outside")
        (fixture.root / "data/processed").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            fixture.prepare()

    def test_initial_acquisition_failure_creates_no_processed_tree(self):
        fixture = self.make_fixture()
        fixture.fail_on_call = 1
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.prepare()
        self.assertFalse((fixture.root / "data/processed").exists())

    def test_second_acquisition_failure_withholds_manifest(self):
        fixture = self.make_fixture()
        fixture.fail_on_call = 2
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.prepare()
        self.assertEqual(
            {path.name for path in fixture.target.iterdir()},
            set(gsm8k._OUTPUT_NAMES.values()),
        )
        self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())

    def test_link_failure_never_publishes_manifest(self):
        fixture = self.make_fixture()
        with mock.patch.object(gsm8k.os, "link", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                fixture.prepare()
        self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())
        self.assertTrue(any(path.name.startswith(".kairos-") for path in fixture.target.iterdir()))

    def test_publication_unlink_and_fsync_failures_preserve_partial_state(self):
        fixture = self.make_fixture()
        fixture._mkdir_private(f"{fixture.target_parent_rel}/{fixture.target_leaf}")
        temporary = fixture.target / ".kairos-test.tmp"
        temporary.write_bytes(b"payload")
        os.chmod(temporary, 0o600)
        target_fd = os.open(fixture.target, gsm8k._dir_flags())
        try:
            with mock.patch.object(
                gsm8k.os, "unlink", side_effect=OSError("synthetic unlink")
            ):
                with self.assertRaises(OSError):
                    gsm8k._publish_temp(target_fd, temporary.name, "final")
        finally:
            os.close(target_fd)
        self.assertTrue(temporary.exists())
        self.assertTrue((fixture.target / "final").exists())
        self.assertEqual(temporary.stat().st_nlink, 2)
        self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fixture._mkdir_private(f"{fixture.target_parent_rel}/{fixture.target_leaf}")
        temporary = fixture.target / ".kairos-test.tmp"
        temporary.write_bytes(b"payload")
        os.chmod(temporary, 0o600)
        target_fd = os.open(fixture.target, gsm8k._dir_flags())
        try:
            with mock.patch.object(
                gsm8k.os, "fsync", side_effect=OSError("synthetic fsync")
            ):
                with self.assertRaises(OSError):
                    gsm8k._publish_temp(target_fd, temporary.name, "final")
        finally:
            os.close(target_fd)
        self.assertFalse(temporary.exists())
        self.assertTrue((fixture.target / "final").exists())
        self.assertEqual((fixture.target / "final").stat().st_nlink, 1)
        self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())

    def test_publication_never_replaces_existing_final(self):
        fixture = self.make_fixture()
        fixture._mkdir_private(f"{fixture.target_parent_rel}/{fixture.target_leaf}")
        temporary = fixture.target / ".kairos-test.tmp"
        final = fixture.target / "final"
        temporary.write_bytes(b"new")
        final.write_bytes(b"old")
        os.chmod(temporary, 0o600)
        os.chmod(final, 0o600)
        target_fd = os.open(fixture.target, gsm8k._dir_flags())
        try:
            with self.assertRaises(FileExistsError):
                gsm8k._publish_temp(target_fd, temporary.name, final.name)
        finally:
            os.close(target_fd)
        self.assertEqual(temporary.read_bytes(), b"new")
        self.assertEqual(final.read_bytes(), b"old")

    def test_manifest_extra_and_duplicate_keys_are_rejected(self):
        fixture = self.make_fixture()
        fixture.prepare()
        manifest_path = fixture.target / gsm8k._MANIFEST
        value = json.loads(manifest_path.read_bytes())
        value["unexpected"] = 1
        manifest_path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fixture.prepare()
        manifest_path = fixture.target / gsm8k._MANIFEST
        original = manifest_path.read_bytes()
        manifest_path.write_bytes(b'{"status":"COMPLETE",' + original[1:])
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

    def test_missing_output_mode_and_unknown_hardlink_are_rejected(self):
        fixture = self.make_fixture()
        fixture.prepare()
        (fixture.target / "examples-test.jsonl").unlink()
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fixture.prepare()
        output = fixture.target / "examples-test.jsonl"
        os.chmod(output, 0o644)
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fixture.prepare()
        os.link(
            fixture.target / "examples-test.jsonl",
            fixture.target / "unknown-hardlink",
        )
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

    def test_synchronized_output_and_manifest_tamper_is_rejected_by_raw_replay(self):
        fixture = self.make_fixture()
        fixture.prepare()
        source_path = fixture.target / "source-train.jsonl"
        example_path = fixture.target / "examples-train.jsonl"
        source_lines = source_path.read_bytes().splitlines()
        example_lines = example_path.read_bytes().splitlines()
        source_value = json.loads(source_lines[0])
        example_value = json.loads(example_lines[0])
        source_value["question"] = "attacker-synchronized-question"
        example_value["text"] = source_value["question"]
        example_value["question"] = source_value["question"]
        source_lines[0] = canonical_json(source_value).encode("utf-8")
        example_lines[0] = canonical_json(example_value).encode("utf-8")
        source_content = b"\n".join(source_lines) + b"\n"
        example_content = b"\n".join(example_lines) + b"\n"
        source_path.write_bytes(source_content)
        example_path.write_bytes(example_content)

        manifest_path = fixture.target / gsm8k._MANIFEST
        manifest = json.loads(manifest_path.read_bytes())
        for key, content in (
            ("source_train", source_content),
            ("example_train", example_content),
        ):
            manifest["outputs"][key]["byte_size"] = len(content)
            manifest["outputs"][key]["sha256"] = hashlib.sha256(content).hexdigest()
        manifest_path.write_bytes(canonical_json(manifest).encode("utf-8") + b"\n")
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

    def test_noncanonical_or_lockstep_eof_output_is_rejected(self):
        fixture = self.make_fixture()
        fixture.prepare()
        source_path = fixture.target / "source-test.jsonl"
        value = json.loads(source_path.read_bytes())
        source_path.write_bytes(
            json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
        )
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fixture.prepare()
        example_path = fixture.target / "examples-test.jsonl"
        example_path.write_bytes(b"")
        with self.assertRaises(gsm8k.Gsm8kError):
            fixture.verify()

    def test_five_artifact_fault_matrix_preserves_fail_closed_state(self):
        artifacts = (*gsm8k._OUTPUT_NAMES.values(), gsm8k._MANIFEST)
        phases = (
            "create",
            "write",
            "file-fsync",
            "close",
            "reopen",
            "content",
            "link",
            "unlink",
            "root-fsync",
        )
        for artifact in artifacts:
            for phase in phases:
                with self.subTest(artifact=artifact, phase=phase):
                    fixture = SyntheticLayout()
                    fired = []

                    def fault(point, observed_artifact):
                        if (
                            not fired
                            and point == phase
                            and observed_artifact == artifact
                        ):
                            fired.append((point, observed_artifact))
                            if point == "content":
                                with _artifact_temp(
                                    fixture.target, artifact
                                ).open("ab") as handle:
                                    handle.write(b"synthetic-content-tamper")
                                return
                            raise OSError("synthetic artifact fault")

                    try:
                        with mock.patch.object(gsm8k, "_FAULT_HOOK", fault):
                            expected_error = (
                                gsm8k.Gsm8kError
                                if phase == "content"
                                else OSError
                            )
                            with self.assertRaises(expected_error):
                                fixture.prepare()
                        self.assertEqual(fired, [(phase, artifact)])
                        manifest = fixture.target / gsm8k._MANIFEST
                        if artifact != gsm8k._MANIFEST or phase not in {
                            "unlink",
                            "root-fsync",
                        }:
                            self.assertFalse(manifest.exists())
                        if phase == "unlink":
                            with self.assertRaises(gsm8k.Gsm8kError):
                                fixture.verify()
                    finally:
                        fixture.close()

    def test_close_fault_occurs_at_real_artifact_cleanup_boundary(self):
        artifacts = (*gsm8k._OUTPUT_NAMES.values(), gsm8k._MANIFEST)
        pairs = {
            "source-train.jsonl": "examples-train.jsonl",
            "examples-train.jsonl": "source-train.jsonl",
            "source-test.jsonl": "examples-test.jsonl",
            "examples-test.jsonl": "source-test.jsonl",
        }
        original_create = gsm8k._create_temp
        original_close = gsm8k.os.close
        for artifact in artifacts:
            with self.subTest(artifact=artifact):
                fixture = SyntheticLayout()
                created = {}
                closed = []
                fired = []

                def create(target_fd, label, observed_artifact=None):
                    name, fd = original_create(
                        target_fd, label, observed_artifact
                    )
                    created[observed_artifact or label] = fd
                    return name, fd

                def close(fd):
                    closed.append((fd, len(fired)))
                    return original_close(fd)

                def fault(point, observed_artifact):
                    if (
                        point == "close"
                        and observed_artifact == artifact
                        and not fired
                    ):
                        fired.append(observed_artifact)
                        raise OSError("synthetic close boundary fault")

                try:
                    with mock.patch.object(gsm8k, "_create_temp", create):
                        with mock.patch.object(gsm8k.os, "close", side_effect=close):
                            with mock.patch.object(gsm8k, "_FAULT_HOOK", fault):
                                with self.assertRaisesRegex(
                                    OSError, "close boundary fault"
                                ):
                                    fixture.prepare()
                    self.assertEqual(fired, [artifact])
                    self.assertIn((created[artifact], 1), closed)
                    if artifact in pairs:
                        self.assertTrue(
                            any(fd == created[pairs[artifact]] for fd, _ in closed)
                        )
                    self.assertFalse(
                        (fixture.target / gsm8k._MANIFEST).exists()
                    )
                finally:
                    fixture.close()

    def test_mkdir_enoent_eexist_race_reuses_only_safe_directory(self):
        fixture = self.make_fixture()
        fired = []

        def safe_race(point, artifact):
            if point == "mkdir-enoent" and artifact == "processed" and not fired:
                fired.append(artifact)
                path = fixture.root / "data/processed"
                path.mkdir(mode=0o700)

        with mock.patch.object(gsm8k, "_FAULT_HOOK", safe_race):
            fixture.prepare()
        self.assertEqual(fired, ["processed"])

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fired.clear()

        def unsafe_race(point, artifact):
            if point == "mkdir-enoent" and artifact == "processed" and not fired:
                fired.append(artifact)
                path = fixture.root / "data/processed"
                path.mkdir(mode=0o755)
                os.chmod(path, 0o755)

        with mock.patch.object(gsm8k, "_FAULT_HOOK", unsafe_race):
            with self.assertRaises(gsm8k.Gsm8kError):
                fixture.prepare()
        self.assertEqual(fired, ["processed"])

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        outside = fixture._mkdir_private("outside-race")
        fired.clear()

        def symlink_race(point, artifact):
            if point == "mkdir-enoent" and artifact == "processed" and not fired:
                fired.append(artifact)
                (fixture.root / "data/processed").symlink_to(
                    outside, target_is_directory=True
                )

        with mock.patch.object(gsm8k, "_FAULT_HOOK", symlink_race):
            with self.assertRaises(OSError):
                fixture.prepare()
        self.assertEqual(fired, ["processed"])

    def test_late_target_rename_to_empty_replacement_is_rejected(self):
        fixture = self.make_fixture()
        fixture.prepare()
        fired = []

        def attack(point, artifact):
            if point == "terminal-canonical-open" and not fired:
                fired.append(point)
                orphan = fixture.target.with_name(fixture.target.name + ".orphan")
                fixture.target.rename(orphan)
                fixture.target.mkdir(mode=0o700)

        with mock.patch.object(gsm8k, "_FAULT_HOOK", attack):
            with self.assertRaises(gsm8k.Gsm8kError):
                fixture.verify()
        self.assertEqual(fired, ["terminal-canonical-open"])

    def test_open_canonical_fd_then_target_replacement_is_rejected(self):
        for attack_point in (
            "terminal-canonical-tree",
            "terminal-final-parent",
        ):
            with self.subTest(attack_point=attack_point):
                fixture = SyntheticLayout()
                try:
                    fixture.prepare()
                    fired = []

                    def attack(point, artifact):
                        if point == attack_point and not fired:
                            fired.append(point)
                            orphan = fixture.target.with_name(
                                fixture.target.name + f".{attack_point}.orphan"
                            )
                            fixture.target.rename(orphan)
                            fixture.target.mkdir(mode=0o700)

                    with mock.patch.object(gsm8k, "_FAULT_HOOK", attack):
                        with self.assertRaises(gsm8k.Gsm8kError):
                            fixture.verify()
                    self.assertEqual(fired, [attack_point])
                finally:
                    fixture.close()

    def test_prepare_outer_terminal_binding_rejects_late_target(self):
        fixture = self.make_fixture()
        calls = []

        def attack(point, artifact):
            if point == "terminal-canonical-open":
                calls.append(point)
                if len(calls) == 2:
                    orphan = fixture.target.with_name(
                        fixture.target.name + ".outer-orphan"
                    )
                    fixture.target.rename(orphan)
                    fixture.target.mkdir(mode=0o700)

        with mock.patch.object(gsm8k, "_FAULT_HOOK", attack):
            with self.assertRaises(gsm8k.Gsm8kError):
                fixture.prepare()
        self.assertEqual(len(calls), 2)

    def test_late_parent_final_and_extra_entry_attacks_are_rejected(self):
        attacks = ("parent", "final", "extra")
        for attack_name in attacks:
            with self.subTest(attack=attack_name):
                fixture = SyntheticLayout()
                try:
                    fixture.prepare()
                    fired = []

                    def attack(point, artifact):
                        if fired:
                            return
                        if attack_name == "parent" and point == "terminal-final-parent":
                            fired.append(point)
                            parent = fixture.target.parent
                            orphan = parent.with_name(parent.name + ".orphan")
                            parent.rename(orphan)
                            parent.mkdir(mode=0o700)
                        elif attack_name == "final" and point == "terminal-canonical-tree":
                            fired.append(point)
                            _replace_same_content(
                                fixture.target / "examples-test.jsonl"
                            )
                        elif attack_name == "extra" and point == "terminal-canonical-tree":
                            fired.append(point)
                            extra = fixture.target / "late-extra"
                            extra.write_bytes(b"extra")
                            os.chmod(extra, 0o600)

                    with mock.patch.object(gsm8k, "_FAULT_HOOK", attack):
                        with self.assertRaises((gsm8k.Gsm8kError, FileNotFoundError)):
                            fixture.verify()
                    self.assertTrue(fired)
                finally:
                    fixture.close()

    def test_completion_and_source_same_content_inode_swaps_are_rejected(self):
        fixture = self.make_fixture()
        fired = []

        def completion_attack(point, artifact):
            if point == "completion-binding" and not fired:
                fired.append(point)
                _replace_same_content(
                    fixture.root / fixture.acquisition.completion_manifest_path
                )

        with mock.patch.object(gsm8k, "_FAULT_HOOK", completion_attack):
            with self.assertRaises(gsm8k.Gsm8kError):
                fixture.prepare()
        self.assertEqual(fired, ["completion-binding"])

        fixture.close()
        self.fixture = SyntheticLayout()
        fixture = self.fixture
        fired.clear()

        def source_attack(point, artifact):
            if point == "source-binding" and artifact == "train" and not fired:
                fired.append(point)
                _replace_same_content(
                    fixture.root
                    / fixture.raw_revision_rel
                    / fixture.source_paths["train"]
                )

        with mock.patch.object(gsm8k, "_FAULT_HOOK", source_attack):
            with self.assertRaises(gsm8k.Gsm8kError):
                fixture.prepare()
        self.assertEqual(fired, ["source-binding"])
        self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())

    def test_publish_name_races_are_rejected(self):
        points = (
            "publish-before-link",
            "publish-after-link",
            "publish-before-unlink",
        )
        artifact = "source-train.jsonl"
        for point_to_attack in points:
            with self.subTest(point=point_to_attack):
                fixture = SyntheticLayout()
                fired = []
                try:

                    def attack(point, observed_artifact):
                        if (
                            fired
                            or point != point_to_attack
                            or observed_artifact != artifact
                        ):
                            return
                        fired.append(point)
                        candidates = list(
                            fixture.target.glob(".kairos-source-train.*.tmp")
                        )
                        self.assertEqual(len(candidates), 1)
                        temporary = candidates[0]
                        if point == "publish-before-link":
                            orphan = temporary.with_name(temporary.name + ".orphan")
                            temporary.rename(orphan)
                            temporary.write_bytes(orphan.read_bytes())
                            os.chmod(temporary, 0o600)
                        elif point == "publish-after-link":
                            _replace_same_content(fixture.target / artifact)
                        else:
                            orphan = temporary.with_name(temporary.name + ".orphan")
                            temporary.rename(orphan)
                            temporary.write_bytes(orphan.read_bytes())
                            os.chmod(temporary, 0o600)

                    with mock.patch.object(gsm8k, "_FAULT_HOOK", attack):
                        with self.assertRaises(gsm8k.Gsm8kError):
                            fixture.prepare()
                    self.assertEqual(fired, [point_to_attack])
                    self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())
                finally:
                    fixture.close()

    def test_post_validation_temp_tamper_breaks_publication_fingerprint(self):
        fixture = self.make_fixture()
        original_publish = gsm8k._publish_temp
        fired = []

        def publish(
            target_fd,
            temporary,
            final,
            artifact=None,
            expected_fingerprint=None,
        ):
            if final == "source-train.jsonl" and not fired:
                fired.append(final)
                with (fixture.target / temporary).open("ab") as handle:
                    handle.write(b"post-validation-tamper")
            return original_publish(
                target_fd,
                temporary,
                final,
                artifact,
                expected_fingerprint,
            )

        with mock.patch.object(gsm8k, "_publish_temp", publish):
            with self.assertRaises(gsm8k.Gsm8kError):
                fixture.prepare()
        self.assertEqual(fired, ["source-train.jsonl"])
        self.assertFalse((fixture.target / gsm8k._MANIFEST).exists())

    def test_manifest_nested_schema_types_and_duplicates_are_rejected(self):
        fixture = self.make_fixture()
        manifest = fixture.prepare()

        def mutate(path, operation, value=None):
            candidate = copy.deepcopy(manifest)
            current = candidate
            for component in path[:-1]:
                current = current[component]
            if operation == "delete":
                del current[path[-1]]
            else:
                current[path[-1]] = value
            return candidate

        cases = (
            mutate(("acquisition", "provenance_commit"), "delete"),
            mutate(("acquisition", "extra"), "set", 1),
            mutate(("adapter", "git_commit"), "set", True),
            mutate(("adapter", "extra"), "set", 1),
            mutate(("sources", "train", "byte_size"), "set", True),
            mutate(("sources", "test", "extra"), "set", 1),
            mutate(("outputs", "source_train", "record_count"), "set", True),
            mutate(("outputs", "example_test", "extra"), "set", 1),
            mutate(("duplicates", "train_question_group_count"), "set", True),
            mutate(("duplicates", "extra"), "set", 1),
            mutate(("sources",), "set", []),
        )
        for candidate in cases:
            with self.subTest(candidate=list(candidate)):
                with self.assertRaises(gsm8k.Gsm8kError):
                    gsm8k._validate_manifest(candidate, fixture.layout)
        with self.assertRaises(gsm8k.Gsm8kError):
            gsm8k._strict_object(b'{"outer":{"x":1,"x":2}}', "nested")


class ResourceLifecycleTests(SyntheticTestCase):
    def test_best_effort_cleanup_attempts_all_and_preserves_active_error(self):
        events = []

        class BrokenResource:
            def __init__(self, name):
                self.name = name

            def close(self):
                events.append(self.name)
                raise OSError(self.name)

        resources = (BrokenResource("first"), BrokenResource("second"))
        with self.assertRaisesRegex(OSError, "first"):
            gsm8k._close_resources_best_effort(resources)
        self.assertEqual(events, ["first", "second"])
        events.clear()
        primary = ValueError("primary")
        gsm8k._close_resources_best_effort(resources, primary)
        self.assertEqual(events, ["first", "second"])

    def test_open_absolute_dir_closes_child_after_parent_close_failure(self):
        closed = []

        def close(fd):
            closed.append(fd)
            if fd == 10:
                raise OSError("parent close")

        with mock.patch.object(gsm8k.os, "open", side_effect=(10, 20)):
            with mock.patch.object(gsm8k.os, "close", side_effect=close):
                with self.assertRaisesRegex(OSError, "parent close"):
                    gsm8k._open_absolute_dir(Path("/component"))
        self.assertEqual(closed, [10, 20])

    def test_open_relative_regular_closes_leaf_after_parent_close_failure(self):
        closed = []

        def close(fd):
            closed.append(fd)
            if fd == 20:
                raise OSError("parent close")
            if fd == 30:
                raise OSError("leaf close")

        with mock.patch.object(gsm8k.os, "dup", return_value=10):
            with mock.patch.object(gsm8k.os, "open", side_effect=(20, 30)):
                with mock.patch.object(gsm8k.os, "close", side_effect=close):
                    with self.assertRaisesRegex(OSError, "parent close"):
                        gsm8k._open_relative_regular(9, "dir/file")
        self.assertEqual(closed, [10, 20, 30])

    def test_directory_chain_builders_close_traversal_and_held_child(self):
        fake_stat = mock.Mock(
            st_mode=stat.S_IFDIR | 0o700,
            st_uid=os.geteuid(),
        )
        for builder in (gsm8k._open_relative_chain, gsm8k._open_or_create_chain):
            with self.subTest(builder=builder.__name__):
                closed = []

                def close(fd):
                    closed.append(fd)
                    if fd == 10:
                        raise OSError("traversal close")

                with mock.patch.object(gsm8k.os, "dup", side_effect=(10, 21)):
                    with mock.patch.object(gsm8k.os, "open", return_value=20):
                        with mock.patch.object(gsm8k.os, "fstat", return_value=fake_stat):
                            with mock.patch.object(gsm8k.os, "close", side_effect=close):
                                with self.assertRaisesRegex(
                                    OSError, "traversal close"
                                ):
                                    builder(9, "component")
                self.assertEqual(closed, [10, 21, 20])

    def test_invalid_created_chain_component_is_closed(self):
        closed = []
        invalid_stat = mock.Mock(
            st_mode=stat.S_IFDIR | 0o755,
            st_uid=os.geteuid(),
        )
        with mock.patch.object(gsm8k.os, "dup", return_value=10):
            with mock.patch.object(gsm8k.os, "open", return_value=20):
                with mock.patch.object(gsm8k.os, "fstat", return_value=invalid_stat):
                    with mock.patch.object(
                        gsm8k.os, "close", side_effect=lambda fd: closed.append(fd)
                    ):
                        with self.assertRaises(gsm8k.Gsm8kError):
                            gsm8k._open_or_create_chain(9, "component")
        self.assertEqual(closed, [20, 10])

    def test_lockstep_partial_fdopen_closes_prior_handles_and_failed_dup(self):
        fingerprint = gsm8k._Fingerprint(
            1, 1, stat.S_IFREG | 0o600, 1, 0, 1, 1
        )
        binding = gsm8k._SourceBinding("test", "test.jsonl", "0" * 64, 0, 0)
        for failure_index in (2, 3):
            with self.subTest(failure_index=failure_index):
                events = []
                calls = []

                class Handle:
                    def __init__(self, name):
                        self.name = name

                    def close(self):
                        events.append(("handle", self.name))

                def fdopen(fd, mode):
                    calls.append(fd)
                    if len(calls) == failure_index:
                        raise OSError("fdopen failure")
                    return Handle(str(fd))

                def close(fd):
                    events.append(("fd", fd))

                with mock.patch.object(
                    gsm8k, "_fingerprint_fd", return_value=fingerprint
                ):
                    with mock.patch.object(gsm8k.os, "lseek", return_value=0):
                        with mock.patch.object(
                            gsm8k.os, "dup", side_effect=(101, 102, 103)
                        ):
                            with mock.patch.object(gsm8k.os, "fdopen", side_effect=fdopen):
                                with mock.patch.object(gsm8k.os, "close", side_effect=close):
                                    with self.assertRaisesRegex(OSError, "fdopen failure"):
                                        gsm8k._verify_split_fds(
                                            1,
                                            2,
                                            3,
                                            binding,
                                            "source",
                                            "example",
                                        )
                self.assertIn(("fd", 100 + failure_index), events)
                for prior in range(1, failure_index):
                    self.assertIn(("handle", str(100 + prior)), events)

    def test_lockstep_close_attempts_all_and_keeps_active_read_error(self):
        fingerprint = gsm8k._Fingerprint(
            1, 1, stat.S_IFREG | 0o600, 1, 0, 1, 1
        )
        binding = gsm8k._SourceBinding("test", "test.jsonl", "0" * 64, 0, 0)
        events = []

        class Handle:
            def __init__(self, name, active=False):
                self.name = name
                self.active = active

            def readline(self, limit):
                if self.active:
                    raise ValueError("primary read")
                return b""

            def close(self):
                events.append(self.name)
                raise OSError(self.name)

        handles = (Handle("raw", True), Handle("source"), Handle("example"))
        with mock.patch.object(gsm8k, "_fingerprint_fd", return_value=fingerprint):
            with mock.patch.object(gsm8k.os, "lseek", return_value=0):
                with mock.patch.object(gsm8k.os, "dup", side_effect=(101, 102, 103)):
                    with mock.patch.object(gsm8k.os, "fdopen", side_effect=handles):
                        with self.assertRaisesRegex(ValueError, "primary read"):
                            gsm8k._verify_split_fds(
                                1, 2, 3, binding, "source", "example"
                            )
        self.assertEqual(events, ["example", "source", "raw"])

    def test_lockstep_multiple_close_failures_raise_first_after_all_attempts(self):
        fingerprint = gsm8k._Fingerprint(
            1, 1, stat.S_IFREG | 0o600, 1, 0, 1, 1
        )
        binding = gsm8k._SourceBinding("test", "test.jsonl", "0" * 64, 0, 0)
        events = []

        class Handle:
            def __init__(self, name):
                self.name = name

            def readline(self, limit):
                return b""

            def close(self):
                events.append(self.name)
                raise OSError(self.name)

        handles = (Handle("raw"), Handle("source"), Handle("example"))
        with mock.patch.object(gsm8k, "_fingerprint_fd", return_value=fingerprint):
            with mock.patch.object(gsm8k.os, "lseek", return_value=0):
                with mock.patch.object(gsm8k.os, "dup", side_effect=(101, 102, 103)):
                    with mock.patch.object(gsm8k.os, "fdopen", side_effect=handles):
                        with self.assertRaisesRegex(OSError, "example"):
                            gsm8k._verify_split_fds(
                                1, 2, 3, binding, "source", "example"
                            )
        self.assertEqual(events, ["example", "source", "raw"])

    def test_acquisition_cleanup_does_not_mask_primary_validation_error(self):
        fixture = self.make_fixture()
        with mock.patch.object(gsm8k, "_open_relative_regular", return_value=10):
            with mock.patch.object(
                gsm8k,
                "_stable_hash_fd",
                side_effect=gsm8k.Gsm8kError("primary validation"),
            ):
                with mock.patch.object(
                    gsm8k.os, "close", side_effect=OSError("cleanup close")
                ):
                    with self.assertRaisesRegex(
                        gsm8k.Gsm8kError, "primary validation"
                    ):
                        gsm8k._acquisition_gate(
                            fixture.layout, 1, fixture.verifier
                        )


class CliBoundaryTests(unittest.TestCase):
    def test_argparse_owns_usage_errors(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                gsm8k.main(["verify", "--project-root", "/tmp"])
        self.assertEqual(raised.exception.code, 2)

    def test_expected_error_is_sanitized(self):
        expected = (
            gsm8k.Gsm8kError("SECRET-PAYLOAD"),
            gsm8k.acquisition.AcquisitionError("SECRET-PAYLOAD"),
            gsm8k.ArchiveSafetyError("SECRET-PAYLOAD"),
            FileExistsError("SECRET-PAYLOAD"),
            FileNotFoundError("SECRET-PAYLOAD"),
            PermissionError("SECRET-PAYLOAD"),
            OSError("SECRET-PAYLOAD"),
        )
        for error in expected:
            with self.subTest(error=type(error).__name__):
                stderr = io.StringIO()
                with mock.patch.object(gsm8k, "verify", side_effect=error):
                    with contextlib.redirect_stderr(stderr):
                        self.assertEqual(gsm8k.main(["verify"]), 2)
                self.assertNotIn("SECRET-PAYLOAD", stderr.getvalue())
                self.assertIn(type(error).__name__, stderr.getvalue())

    def test_programming_and_control_flow_exceptions_propagate(self):
        for error in (
            ValueError("bug"),
            TypeError("bug"),
            RuntimeError("bug"),
            KeyboardInterrupt(),
            SystemExit(9),
        ):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(gsm8k, "verify", side_effect=error):
                    with self.assertRaises(type(error)):
                        gsm8k.main(["verify"])


if __name__ == "__main__":
    unittest.main()
