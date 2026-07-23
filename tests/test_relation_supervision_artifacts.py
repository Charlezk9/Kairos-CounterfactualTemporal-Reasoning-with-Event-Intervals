import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kairos import construction_audit_persistence as source_binding
from kairos.ids import canonical_json, make_stable_id
from kairos.relation_supervision import RelationOnlyPair
import kairos.relation_supervision_artifacts as artifacts
from kairos.schema import AnswerType, SplitAssignment, TemporalExample


def _example(index, text):
    source_id = make_stable_id("source", {"relation-fixture": index})
    return TemporalExample(
        record_id=make_stable_id("record", {"source_id": source_id}),
        source_id=source_id,
        dataset="gsm8k",
        split=SplitAssignment(official="train", internal=None),
        revision=artifacts.REVISION,
        source_sha256=hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        text=text,
        question=text,
        answers=(str(index + 10),),
        answer_type=AnswerType.NUMERIC,
    )


class SyntheticLayout:
    def __init__(self, root):
        self.root = Path(root)
        os.chmod(self.root, 0o700)
        self.examples = (
            _example(0, "Alpha happened before Beta happened."),
            _example(1, "No temporal marker."),
            _example(2, "Alpha while Beta."),
            _example(3, "Alpha prior to Beta."),
        )
        source_rel = "data/processed/source/examples-train.jsonl"
        source_path = self.root / source_rel
        source_path.parent.mkdir(parents=True, mode=0o700)
        for parent in (
            self.root / "data",
            self.root / "data/processed",
            source_path.parent,
        ):
            os.chmod(parent, 0o700)
        source_payload = b"".join(
            canonical_json(example).encode("utf-8") + b"\n"
            for example in self.examples
        )
        source_path.write_bytes(source_payload)
        os.chmod(source_path, 0o600)

        manifest_rel = "data/processed/source/processed-manifest.json"
        source_manifest = {
            "status": "COMPLETE",
            "dataset": "gsm8k",
            "revision": artifacts.REVISION,
            "outputs": {
                "example_train": {
                    "path": "examples-train.jsonl",
                    "byte_size": len(source_payload),
                    "record_count": len(self.examples),
                    "sha256": hashlib.sha256(source_payload).hexdigest(),
                }
            },
        }
        manifest_payload = canonical_json(source_manifest).encode("utf-8") + b"\n"
        manifest_path = self.root / manifest_rel
        manifest_path.write_bytes(manifest_payload)
        os.chmod(manifest_path, 0o600)

        raw = self.root / "data/raw"
        raw.mkdir(parents=True, mode=0o700)
        os.chmod(raw, 0o700)
        evidence = {}
        for name, payload, mode in (
            ("completion-manifest.json", b"completion\n", 0o600),
            ("SHA256SUMS", b"0" * 64 + b"  fixture\n", 0o600),
            ("LICENSE", b"MIT fixture\n", 0o644),
        ):
            path = raw / name
            path.write_bytes(payload)
            os.chmod(path, mode)
            evidence[name] = hashlib.sha256(payload).hexdigest()
        os.link(raw / "completion-manifest.json", raw / "completion-manifest.guard")

        source_layout = source_binding._Layout(
            data_root=self.root,
            repo_root=self.root,
            target_parent_rel="unused",
            source_manifest_rel=manifest_rel,
            source_manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
            completion_rel="data/raw/completion-manifest.json",
            completion_sha256=evidence["completion-manifest.json"],
            sha256sums_rel="data/raw/SHA256SUMS",
            sha256sums_sha256=evidence["SHA256SUMS"],
            formal_tree_sha256="f" * 64,
            license_rel="data/raw/LICENSE",
            splits={
                "train": source_binding._SourceFacts(
                    path=source_rel,
                    sha256=hashlib.sha256(source_payload).hexdigest(),
                    byte_size=len(source_payload),
                    record_count=len(self.examples),
                )
            },
        )
        self.layout = artifacts._Layout(
            source_layout=source_layout,
            target_parent_rel="data/processed/relation-only",
        )


def _no_git_gate(layout, execution_commit):
    artifacts._validate_execution_commit(execution_commit)


def _mode(path):
    return path.stat(follow_symlinks=False).st_mode & 0o777


class RelationSupervisionArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir="/data0/hk_data/kairos-zx/.tmp",
            prefix="relation-artifact.",
        )
        self.fixture = SyntheticLayout(self.temporary.name)
        self.commit = "a" * 40

    def tearDown(self):
        self.temporary.cleanup()

    def publish(self):
        return artifacts._publish_layout(
            self.fixture.layout, self.commit, _no_git_gate
        )

    def target(self):
        return (
            Path(self.temporary.name)
            / "data/processed/relation-only/train"
        )

    def test_fixed_contract_is_train_only_and_sha_bound(self):
        self.assertEqual(
            set(artifacts._PRODUCTION_LAYOUT.source_layout.splits),
            {"train"},
        )
        publication = artifacts._publication_source_layout(
            artifacts._PRODUCTION_LAYOUT
        )
        self.assertEqual(set(publication.splits), {"train"})
        self.assertNotIn("test", artifacts._TARGET_PARENT_REL)
        self.assertTrue(
            source_binding._HEX64.fullmatch(
                publication.source_manifest_sha256
            )
        )

    def test_manifest_last_publication_and_full_source_replay(self):
        result = self.publish()
        self.assertEqual(result["observer_state"], "STRUCTURALLY_VERIFIED")
        manifest = result["manifest"]
        self.assertEqual(
            set(manifest),
            {
                "status", "schema_version", "artifact_id", "dataset",
                "revision", "official_split", "source", "publisher",
                "supervision", "terminal_counts", "identity", "output",
            },
        )
        self.assertEqual(manifest["official_split"], "train")
        self.assertEqual(
            manifest["terminal_counts"],
            {
                "no_marker": 1,
                "extraction_rejected": 1,
                "rewrite_rejected": 1,
                "retained": 1,
            },
        )
        self.assertEqual(manifest["output"]["record_count"], 1)
        self.assertFalse(manifest["supervision"]["counterfactual_answer_available"])
        self.assertTrue(manifest["supervision"]["counterfactual_answer_loss_masked"])
        target = self.target()
        self.assertEqual(
            {path.name for path in target.iterdir()},
            {"relation-supervision.jsonl", "relation-supervision-manifest.json"},
        )
        self.assertEqual(_mode(target), 0o700)
        self.assertEqual(_mode(target / "relation-supervision.jsonl"), 0o600)
        self.assertEqual(
            _mode(target / "relation-supervision-manifest.json"), 0o600
        )
        pair_value = json.loads(
            (target / "relation-supervision.jsonl").read_text(encoding="utf-8")
        )
        pair = RelationOnlyPair.from_dict(pair_value)
        self.assertEqual(pair.original_answer, "10")
        self.assertNotIn("counterfactual_answer", pair_value)
        self.assertEqual(artifacts._verify_layout(self.fixture.layout), result)
        self.assertIs(
            artifacts._observe_layout(self.fixture.layout),
            artifacts.ObserverState.STRUCTURALLY_VERIFIED,
        )

    def test_publication_is_no_replace(self):
        self.publish()
        with self.assertRaisesRegex(
            artifacts.RelationSupervisionArtifactError,
            "^relation supervision publication target already exists$",
        ):
            self.publish()

    def test_manifest_failure_preserves_partial_without_repair(self):
        real_publish = artifacts._publish_bytes
        calls = []

        def fail_manifest(target, name, payload):
            calls.append(name)
            if name == "relation-supervision-manifest.json":
                raise artifacts.RelationSupervisionArtifactError("injected")
            return real_publish(target, name, payload)

        with patch.object(artifacts, "_publish_bytes", side_effect=fail_manifest):
            with self.assertRaisesRegex(
                artifacts.RelationSupervisionArtifactError, "^injected$"
            ):
                self.publish()
        self.assertEqual(
            calls,
            ["relation-supervision.jsonl", "relation-supervision-manifest.json"],
        )
        self.assertTrue((self.target() / "relation-supervision.jsonl").is_file())
        self.assertFalse(
            (self.target() / "relation-supervision-manifest.json").exists()
        )
        self.assertIs(
            artifacts._observe_layout(self.fixture.layout),
            artifacts.ObserverState.PARTIAL_NO_MANIFEST,
        )

    def test_jsonl_tamper_and_extra_namespace_are_corrupt(self):
        self.publish()
        pair_path = self.target() / "relation-supervision.jsonl"
        with pair_path.open("ab") as handle:
            handle.write(b"{}\n")
        self.assertIs(
            artifacts._observe_layout(self.fixture.layout),
            artifacts.ObserverState.CORRUPT,
        )
        with self.assertRaises(artifacts.RelationSupervisionArtifactError):
            artifacts._verify_layout(self.fixture.layout)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory(
            dir="/data0/hk_data/kairos-zx/.tmp",
            prefix="relation-artifact.",
        )
        self.fixture = SyntheticLayout(self.temporary.name)
        self.publish()
        extra = self.target() / "unexpected"
        extra.write_bytes(b"x")
        os.chmod(extra, 0o600)
        with self.assertRaisesRegex(
            artifacts.RelationSupervisionArtifactError, "namespace differs"
        ):
            artifacts._verify_layout(self.fixture.layout)

    def test_source_tamper_fails_before_target_creation(self):
        source = (
            Path(self.temporary.name)
            / self.fixture.layout.source_layout.splits["train"].path
        )
        with source.open("ab") as handle:
            handle.write(b"{}\n")
        with self.assertRaisesRegex(
            artifacts.RelationSupervisionArtifactError,
            "bound processed train source failed relation replay",
        ):
            self.publish()
        self.assertFalse(self.target().exists())

    def test_manifest_rehash_does_not_hide_replayed_count_tamper(self):
        self.publish()
        manifest_path = self.target() / "relation-supervision-manifest.json"
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        value["terminal_counts"]["retained"] = 0
        manifest_path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
        os.chmod(manifest_path, 0o600)
        with self.assertRaisesRegex(
            artifacts.RelationSupervisionArtifactError,
            "manifest differs from full replay",
        ):
            artifacts._verify_layout(self.fixture.layout)

    def test_commit_observer_and_non_directory_are_fail_closed(self):
        for value in ("A" * 40, "a" * 39, "", None, True):
            with self.subTest(value=value):
                with self.assertRaises(artifacts.RelationSupervisionArtifactError):
                    artifacts._validate_execution_commit(value)
        self.assertIs(
            artifacts._observe_layout(self.fixture.layout),
            artifacts.ObserverState.ABSENT,
        )
        self.target().parent.mkdir(parents=True, mode=0o700)
        self.target().write_text("not a directory", encoding="utf-8")
        self.assertIs(
            artifacts._observe_layout(self.fixture.layout),
            artifacts.ObserverState.CORRUPT,
        )


if __name__ == "__main__":
    unittest.main()
