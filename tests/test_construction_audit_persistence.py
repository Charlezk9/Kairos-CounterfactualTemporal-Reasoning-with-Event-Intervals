import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kairos.construction import construct_explicit_counterfactual
from kairos.construction_audit import make_construction_audit_record
import kairos.construction_audit_persistence as persistence
from kairos.ids import canonical_json, make_stable_id
from kairos.schema import AnswerType, SplitAssignment, TemporalExample


def synthetic_example(index, text):
    source_id = make_stable_id("source", {"fixture": index})
    return TemporalExample(
        record_id=make_stable_id("record", {"source_id": source_id}),
        source_id=source_id,
        dataset="gsm8k",
        split=SplitAssignment(official="train", internal=None),
        revision=persistence.REVISION,
        source_sha256=hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        text=text,
        question="Which happened first?",
        answers=("Alpha",),
        answer_type=AnswerType.EXTRACTIVE,
    )


class SyntheticLayout:
    def __init__(self, root):
        self.root = Path(root)
        os.chmod(self.root, 0o700)
        self.examples = (
            synthetic_example(0, "Alpha before Beta"),
            synthetic_example(1, "No temporal relation"),
        )
        source_rel = "data/processed/source/examples-train.jsonl"
        source_path = self.root / source_rel
        source_path.parent.mkdir(parents=True, mode=0o700)
        for parent in (self.root / "data", self.root / "data/processed", source_path.parent):
            os.chmod(parent, 0o700)
        source_payload = b"".join(
            canonical_json(value).encode() + b"\n" for value in self.examples
        )
        source_path.write_bytes(source_payload)
        os.chmod(source_path, 0o600)

        manifest_rel = "data/processed/source/processed-manifest.json"
        manifest = {
            "status": "COMPLETE",
            "dataset": "gsm8k",
            "revision": persistence.REVISION,
            "outputs": {
                "example_train": {
                    "path": "examples-train.jsonl",
                    "byte_size": len(source_payload),
                    "record_count": len(self.examples),
                    "sha256": hashlib.sha256(source_payload).hexdigest(),
                }
            },
        }
        manifest_payload = canonical_json(manifest).encode() + b"\n"
        manifest_path = self.root / manifest_rel
        manifest_path.write_bytes(manifest_payload)
        os.chmod(manifest_path, 0o600)

        completion_rel = "data/raw/completion-manifest.json"
        sums_rel = "data/raw/SHA256SUMS"
        license_rel = "data/raw/LICENSE"
        (self.root / "data/raw").mkdir(parents=True, mode=0o700)
        os.chmod(self.root / "data/raw", 0o700)
        evidence = {}
        for relative, payload, mode in (
            (completion_rel, b"completion\n", 0o600),
            (sums_rel, b"0" * 64 + b"  fixture\n", 0o600),
            (license_rel, b"MIT fixture\n", 0o644),
        ):
            path = self.root / relative
            path.write_bytes(payload)
            os.chmod(path, mode)
            evidence[relative] = hashlib.sha256(payload).hexdigest()

        self.layout = persistence._Layout(
            data_root=self.root,
            repo_root=self.root,
            target_parent_rel="data/processed/audit",
            source_manifest_rel=manifest_rel,
            source_manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
            completion_rel=completion_rel,
            completion_sha256=evidence[completion_rel],
            sha256sums_rel=sums_rel,
            sha256sums_sha256=evidence[sums_rel],
            formal_tree_sha256="f" * 64,
            license_rel=license_rel,
            splits={
                "train": persistence._SourceFacts(
                    path=source_rel,
                    sha256=hashlib.sha256(source_payload).hexdigest(),
                    byte_size=len(source_payload),
                    record_count=len(self.examples),
                )
            },
        )

    def records(self):
        return [
            make_construction_audit_record(
                input_order=index,
                input=value,
                result=construct_explicit_counterfactual(value),
            )
            for index, value in enumerate(self.examples)
        ]


def no_git_gate(layout, execution_commit):
    persistence._validate_execution_commit(execution_commit)


class ConstructionAuditPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir="/data0/hk_data/kairos-zx/.tmp",
            prefix="d013-p2.",
        )
        self.fixture = SyntheticLayout(self.temporary.name)
        self.commit = "a" * 40

    def tearDown(self):
        self.temporary.cleanup()

    def publish(self):
        return persistence._publish_layout(
            self.fixture.layout,
            self.fixture.records(),
            "train",
            self.commit,
            no_git_gate,
        )

    def test_manifest_last_publication_and_full_replay(self):
        result = self.publish()
        self.assertEqual(result["observer_state"], "STRUCTURALLY_VERIFIED")
        manifest = result["manifest"]
        self.assertEqual(
            set(manifest),
            {
                "status", "schema_version", "dataset", "revision",
                "official_split", "source", "publisher", "output",
                "identity", "terminal_counts", "funnel",
            },
        )
        self.assertEqual(manifest["output"]["record_count"], 2)
        self.assertEqual(manifest["funnel"]["raw"], 2)
        self.assertEqual(manifest["funnel"]["final_retained"], 1)
        self.assertEqual(manifest["terminal_counts"]["retained"], 1)
        self.assertEqual(manifest["terminal_counts"]["no_marker"], 1)
        self.assertEqual(manifest["identity"]["audit_record_id_unique_count"], 2)
        self.assertEqual(manifest["source"]["license"]["spdx_id"], "MIT")
        target = Path(self.temporary.name) / "data/processed/audit/train"
        self.assertEqual({path.name for path in target.iterdir()}, {
            "construction-audit.jsonl", "construction-audit-manifest.json"
        })
        self.assertEqual(stat_mode(target), 0o700)
        self.assertEqual(stat_mode(target / "construction-audit.jsonl"), 0o600)
        self.assertEqual(stat_mode(target / "construction-audit-manifest.json"), 0o600)
        self.assertEqual(
            persistence._verify_layout(self.fixture.layout, "train"), result
        )
        self.assertIs(
            persistence._observe_layout(self.fixture.layout, "train"),
            persistence.ObserverState.STRUCTURALLY_VERIFIED,
        )

    def test_publication_is_no_replace(self):
        self.publish()
        with self.assertRaisesRegex(
            persistence.ConstructionAuditPersistenceError,
            "^construction audit publication target already exists$",
        ):
            self.publish()

    def test_order_source_identity_and_duplicate_stream_fail_before_target(self):
        records = self.fixture.records()
        target = Path(self.temporary.name) / "data/processed/audit/train"
        cases = (
            list(reversed(records)),
            records[:1],
            records + records[:1],
        )
        for values in cases:
            with self.subTest(length=len(values)):
                with self.assertRaises(persistence.ConstructionAuditPersistenceError):
                    persistence._publish_layout(
                        self.fixture.layout, values, "train", self.commit, no_git_gate
                    )
                self.assertFalse(target.exists())

    def test_manifest_failure_preserves_partial_target(self):
        real_publish = persistence._publish_bytes
        calls = []

        def fail_manifest(target, name, payload):
            calls.append(name)
            if name == "construction-audit-manifest.json":
                raise persistence.ConstructionAuditPersistenceError(
                    "construction audit publication blocked partial"
                )
            return real_publish(target, name, payload)

        with patch.object(persistence, "_publish_bytes", side_effect=fail_manifest):
            with self.assertRaisesRegex(
                persistence.ConstructionAuditPersistenceError,
                "^construction audit publication blocked partial$",
            ):
                self.publish()
        self.assertEqual(calls, [
            "construction-audit.jsonl", "construction-audit-manifest.json"
        ])
        target = Path(self.temporary.name) / "data/processed/audit/train"
        self.assertTrue((target / "construction-audit.jsonl").is_file())
        self.assertFalse((target / "construction-audit-manifest.json").exists())
        self.assertIs(
            persistence._observe_layout(self.fixture.layout, "train"),
            persistence.ObserverState.PARTIAL_NO_MANIFEST,
        )

    def test_tampering_is_corrupt_and_never_repaired(self):
        self.publish()
        target = Path(self.temporary.name) / "data/processed/audit/train"
        audit = target / "construction-audit.jsonl"
        with audit.open("ab") as handle:
            handle.write(b"{}\n")
        self.assertIs(
            persistence._observe_layout(self.fixture.layout, "train"),
            persistence.ObserverState.CORRUPT,
        )
        with self.assertRaises(persistence.ConstructionAuditPersistenceError):
            persistence._verify_layout(self.fixture.layout, "train")

    def test_observer_absent_and_non_directory_target(self):
        self.assertIs(
            persistence._observe_layout(self.fixture.layout, "train"),
            persistence.ObserverState.ABSENT,
        )
        target = Path(self.temporary.name) / "data/processed/audit/train"
        target.parent.mkdir(parents=True, mode=0o700)
        target.write_text("not a directory", encoding="utf-8")
        self.assertIs(
            persistence._observe_layout(self.fixture.layout, "train"),
            persistence.ObserverState.PARTIAL_NO_MANIFEST,
        )

    def test_git_commit_and_split_validation_are_fail_closed(self):
        for value in ("A" * 40, "a" * 39, "", None, True):
            with self.subTest(value=value):
                with self.assertRaises(persistence.ConstructionAuditPersistenceError):
                    persistence._validate_execution_commit(value)
        with self.assertRaises(persistence.ConstructionAuditPersistenceError):
            persistence._validate_split("test", self.fixture.layout)

    def test_cli_success_and_redacted_failure(self):
        expected = {"observer_state": "ABSENT"}
        with patch.object(persistence, "observe", return_value=persistence.ObserverState.ABSENT):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertEqual(persistence.main(["observe", "--split", "train"]), 0)
                self.assertEqual(stdout.getvalue(), canonical_json(expected) + "\n")
                self.assertEqual(stderr.getvalue(), "")
        with patch.object(
            persistence,
            "verify",
            side_effect=persistence.ConstructionAuditPersistenceError("sensitive value"),
        ):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertEqual(persistence.main(["verify", "--split", "train"]), 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(
                    stderr.getvalue(), "construction audit publication failed\n"
                )


def stat_mode(path):
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
