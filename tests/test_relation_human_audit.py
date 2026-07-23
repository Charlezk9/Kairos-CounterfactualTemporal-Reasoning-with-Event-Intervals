import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kairos.ids import canonical_json, make_stable_id
import kairos.relation_human_audit as audit
from kairos.relation_supervision import construct_gsm8k_relation_only
import kairos.relation_supervision_artifacts as relation_artifacts
from kairos.schema import AnswerType, SplitAssignment, TemporalExample
from tests.test_relation_supervision_artifacts import (
    SyntheticLayout as RelationSyntheticLayout,
    _no_git_gate as relation_no_git_gate,
)


def _pair(index, marker):
    source_id = make_stable_id("source", {"audit-selection": index})
    text = f"EventA{index} happened {marker} EventB{index} happened."
    example = TemporalExample(
        record_id=make_stable_id("record", {"source_id": source_id}),
        source_id=source_id,
        dataset="gsm8k",
        split=SplitAssignment(official="train", internal=None),
        revision=relation_artifacts.REVISION,
        source_sha256=hashlib.sha256(f"audit-source-{index}".encode()).hexdigest(),
        text=text,
        question=text,
        answers=(str(index),),
        answer_type=AnswerType.NUMERIC,
    )
    result = construct_gsm8k_relation_only(example)
    if result.pair is None:
        raise AssertionError("synthetic selection pair was not retained")
    return result.pair


def _no_git_gate(layout, execution_commit):
    audit._validate_execution_commit(execution_commit)


def _mode(path):
    return path.stat(follow_symlinks=False).st_mode & 0o777


class HumanAuditSelectionTests(unittest.TestCase):
    def test_hamilton_stratification_and_hash_ranking_are_deterministic(self):
        population = tuple(
            [_pair(index, "before") for index in range(8)]
            + [_pair(index, "after") for index in range(8, 10)]
        )
        first = audit._select_pairs(population, 5, 20260723)
        second = audit._select_pairs(tuple(reversed(population)), 5, 20260723)
        self.assertEqual(first, second)
        self.assertEqual(len(first.pairs), 5)
        self.assertEqual(len({pair.pair_id for pair in first.pairs}), 5)
        counts = {
            row["stratum"]: row["sample_count"] for row in first.strata
        }
        self.assertEqual(sum(counts.values()), 5)
        self.assertEqual(sorted(counts.values()), [1, 4])

    def test_invalid_sample_and_duplicate_population_fail_closed(self):
        pair = _pair(0, "before")
        for size in (0, 2, -1, True):
            with self.subTest(size=size):
                with self.assertRaises(audit.HumanAuditError):
                    audit._select_pairs((pair,), size, 1)
        with self.assertRaisesRegex(audit.HumanAuditError, "duplicate pair"):
            audit._select_pairs((pair, pair), 1, 1)


class HumanAuditArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir="/data0/hk_data/kairos-zx/.tmp",
            prefix="human-audit.",
        )
        self.relation_fixture = RelationSyntheticLayout(self.temporary.name)
        self.commit = "a" * 40
        relation_artifacts._publish_layout(
            self.relation_fixture.layout,
            self.commit,
            relation_no_git_gate,
        )
        self.layout = audit._Layout(
            relation_layout=self.relation_fixture.layout,
            target_parent_rel="data/processed/human-audit",
            sample_size=1,
            sampling_seed=123,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def target(self):
        return Path(self.temporary.name) / "data/processed/human-audit/train"

    def publish(self):
        return audit._publish_layout(self.layout, self.commit, _no_git_gate)

    def test_manifest_last_packet_replays_and_templates_are_blank(self):
        result = self.publish()
        self.assertEqual(result["observer_state"], "STRUCTURALLY_VERIFIED")
        manifest = result["manifest"]
        self.assertEqual(manifest["official_split"], "train")
        self.assertEqual(manifest["sampler"]["sample_size"], 1)
        self.assertEqual(manifest["source"]["population_count"], 1)
        self.assertTrue(manifest["review_contract"]["templates_are_blank"])
        self.assertTrue(
            manifest["review_contract"]["training_blocked_until_complete"]
        )
        target = self.target()
        self.assertEqual({path.name for path in target.iterdir()}, audit._EXPECTED_NAMES)
        self.assertEqual(_mode(target), 0o700)
        self.assertTrue(all(_mode(path) == 0o600 for path in target.iterdir()))

        item = json.loads(
            (target / "audit-items.jsonl").read_text(encoding="utf-8")
        )
        self.assertNotIn("original_answer", item)
        self.assertNotIn("counterfactual_answer", item)
        for slot, name in (
            ("A", "reviewer-a-template.jsonl"),
            ("B", "reviewer-b-template.jsonl"),
        ):
            review = json.loads((target / name).read_text(encoding="utf-8"))
            self.assertEqual(review["reviewer_slot"], slot)
            self.assertEqual(review["audit_item_id"], item["audit_item_id"])
            for field in manifest["review_contract"]["boolean_fields"]:
                self.assertIsNone(review[field])
            self.assertIsNone(review["notes"])
        self.assertEqual(audit._verify_layout(self.layout), result)
        self.assertIs(
            audit._observe_layout(self.layout),
            audit.ObserverState.STRUCTURALLY_VERIFIED,
        )

    def test_publication_is_no_replace(self):
        self.publish()
        with self.assertRaisesRegex(audit.HumanAuditError, "target already exists"):
            self.publish()

    def test_manifest_failure_preserves_blank_partial_packet(self):
        real_publish = audit._publish_bytes
        calls = []

        def fail_manifest(target, name, payload):
            calls.append(name)
            if name == "human-audit-manifest.json":
                raise audit.HumanAuditError("injected")
            return real_publish(target, name, payload)

        with patch.object(audit, "_publish_bytes", side_effect=fail_manifest):
            with self.assertRaisesRegex(audit.HumanAuditError, "^injected$"):
                self.publish()
        self.assertEqual(
            calls,
            [
                "audit-items.jsonl",
                "reviewer-a-template.jsonl",
                "reviewer-b-template.jsonl",
                "review-instructions.md",
                "human-audit-manifest.json",
            ],
        )
        self.assertIs(
            audit._observe_layout(self.layout),
            audit.ObserverState.PARTIAL_NO_MANIFEST,
        )
        self.assertFalse((self.target() / "human-audit-manifest.json").exists())

    def test_output_tamper_extra_namespace_and_rehashed_manifest_fail(self):
        self.publish()
        reviewer = self.target() / "reviewer-a-template.jsonl"
        with reviewer.open("ab") as handle:
            handle.write(b"{}\n")
        with self.assertRaisesRegex(audit.HumanAuditError, "full replay"):
            audit._verify_layout(self.layout)
        self.assertIs(
            audit._observe_layout(self.layout), audit.ObserverState.CORRUPT
        )

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory(
            dir="/data0/hk_data/kairos-zx/.tmp",
            prefix="human-audit.",
        )
        self.relation_fixture = RelationSyntheticLayout(self.temporary.name)
        relation_artifacts._publish_layout(
            self.relation_fixture.layout, self.commit, relation_no_git_gate
        )
        self.layout = audit._Layout(
            self.relation_fixture.layout,
            "data/processed/human-audit",
            1,
            123,
        )
        self.publish()
        extra = self.target() / "unexpected"
        extra.write_bytes(b"x")
        os.chmod(extra, 0o600)
        with self.assertRaisesRegex(audit.HumanAuditError, "namespace differs"):
            audit._verify_layout(self.layout)

        extra.unlink()
        manifest_path = self.target() / "human-audit-manifest.json"
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        value["sampler"]["sample_size"] = 2
        manifest_path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
        os.chmod(manifest_path, 0o600)
        with self.assertRaisesRegex(audit.HumanAuditError, "manifest differs"):
            audit._verify_layout(self.layout)

    def test_observer_and_commit_validation_are_fail_closed(self):
        self.assertIs(
            audit._observe_layout(self.layout), audit.ObserverState.ABSENT
        )
        for value in ("A" * 40, "a" * 39, "", None, True):
            with self.subTest(value=value):
                with self.assertRaises(audit.HumanAuditError):
                    audit._validate_execution_commit(value)
        invalid = audit._Layout(
            self.relation_fixture.layout,
            "data/processed/invalid",
            2,
            1,
        )
        with self.assertRaisesRegex(audit.HumanAuditError, "sample size"):
            audit._build_packet(invalid)


if __name__ == "__main__":
    unittest.main()
