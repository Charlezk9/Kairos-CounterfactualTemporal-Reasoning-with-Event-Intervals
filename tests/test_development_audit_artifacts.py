import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from kairos.ids import canonical_json, make_stable_id
from kairos import development_audit_artifacts as artifacts
from kairos.relation_audit_results import (
    AGREEMENT_PROJECTION_SCHEMA_VERSION,
    RelationAuditResultError,
    evaluate_development_agreement,
)
from kairos.relation_human_audit import REVIEW_SCHEMA_VERSION, SAMPLE_SIZE


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")
FIELDS = (
    "event_spans_valid",
    "original_relation_valid",
    "counterfactual_relation_valid",
    "rewrite_grammatical",
    "non_target_content_preserved",
)


def _write(path, payload):
    path.write_bytes(payload)
    os.chmod(path, 0o600)


def _ids():
    return tuple(
        make_stable_id("audit-item", {"development-artifact": index})
        for index in range(SAMPLE_SIZE)
    )


def _review_payload(item_ids, slot, values):
    return b"".join(
        canonical_json(
            {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "audit_item_id": item_id,
                "reviewer_slot": slot,
                **{field: valid for field in FIELDS},
                "overall_valid": valid,
                "notes": None,
            }
        ).encode("utf-8")
        + b"\n"
        for item_id, valid in zip(item_ids, values)
    )


def _source_fixture(root):
    packet = root / "packet"
    intake = root / "intake"
    packet.mkdir(mode=0o700)
    intake.mkdir(mode=0o700)
    item_ids = _ids()
    items = b"".join(
        canonical_json(
            {
                "schema_version": "synthetic-audit-item-v1",
                "audit_item_id": item_id,
            }
        ).encode("utf-8")
        + b"\n"
        for item_id in item_ids
    )
    packet_manifest = canonical_json({"fixture": "packet"}).encode("utf-8") + b"\n"
    _write(packet / "audit-items.jsonl", items)
    _write(packet / "human-audit-manifest.json", packet_manifest)
    _write(packet / "review-instructions.md", b"fixture\n")
    _write(packet / "reviewer-a-template.jsonl", b"fixture\n")
    _write(packet / "reviewer-b-template.jsonl", b"fixture\n")
    values = tuple(index < 196 for index in range(SAMPLE_SIZE))
    reviewer_a = _review_payload(item_ids, "A", values)
    reviewer_b = _review_payload(item_ids, "B", values)
    reviewer_a_sha = hashlib.sha256(reviewer_a).hexdigest()
    reviewer_b_sha = hashlib.sha256(reviewer_b).hexdigest()
    _write(intake / artifacts._REVIEW_A_NAME, reviewer_a)
    _write(intake / artifacts._REVIEW_B_NAME, reviewer_b)
    _write(
        intake / artifacts._REVIEW_A_SIDECAR,
        (reviewer_a_sha + "\n").encode("ascii"),
    )
    _write(
        intake / artifacts._REVIEW_B_SIDECAR,
        (reviewer_b_sha + "\n").encode("ascii"),
    )
    metadata = canonical_json(
        {
            "audit_items_sha256": hashlib.sha256(items).hexdigest(),
            "human_independence_verified": False,
            "packet_manifest_sha256": hashlib.sha256(packet_manifest).hexdigest(),
            "provenance_status": "USER_ATTESTED / INDEPENDENCE_UNVERIFIED",
        }
    ).encode("utf-8") + b"\n"
    _write(intake / artifacts._INTAKE_METADATA_NAME, metadata)
    return artifacts.AuditSources(
        packet_dir=packet,
        intake_dir=intake,
        packet_manifest_sha256=hashlib.sha256(packet_manifest).hexdigest(),
        audit_items_sha256=hashlib.sha256(items).hexdigest(),
        reviewer_a_sha256=reviewer_a_sha,
        reviewer_b_sha256=reviewer_b_sha,
        intake_metadata_sha256=hashlib.sha256(metadata).hexdigest(),
    )


class DevelopmentAgreementTests(unittest.TestCase):
    def test_zero_disagreement_projection_is_development_only(self):
        item_ids = _ids()
        values = tuple(index < 196 for index in range(SAMPLE_SIZE))
        evaluation = evaluate_development_agreement(
            item_ids,
            "a" * 64,
            "b" * 64,
            _review_payload(item_ids, "A", values),
            _review_payload(item_ids, "B", values),
        )
        self.assertTrue(evaluation.result.development_gate_passed)
        self.assertEqual(evaluation.result.valid_count, 196)
        self.assertEqual(evaluation.result.validity, 0.98)
        self.assertEqual(evaluation.result.cohen_kappa, 1.0)
        self.assertEqual(evaluation.result.expected_agreement, 0.9608)
        self.assertFalse(evaluation.result.to_dict()["paper_metric_eligible"])
        first = json.loads(evaluation.projection_payload.splitlines()[0])
        self.assertEqual(
            first["schema_version"], AGREEMENT_PROJECTION_SCHEMA_VERSION
        )
        self.assertNotIn("notes", first)

    def test_any_overall_disagreement_blocks_projection(self):
        item_ids = _ids()
        first = (True,) * SAMPLE_SIZE
        second = (False, *first[1:])
        with self.assertRaisesRegex(RelationAuditResultError, "zero overall"):
            evaluate_development_agreement(
                item_ids,
                "a" * 64,
                "b" * 64,
                _review_payload(item_ids, "A", first),
                _review_payload(item_ids, "B", second),
            )


class DevelopmentAuditArtifactTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-development-audit-test-", dir=TEST_TMP
        )
        self.base = Path(self.temporary.name)
        self.sources = _source_fixture(self.base)
        self.root = self.base / "results"
        self.gate_calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def gate(self, commit):
        self.gate_calls.append(commit)

    def test_publish_and_fresh_replay_are_private_and_exact(self):
        commit = "d" * 40
        value = artifacts._publish(self.root, self.sources, commit, self.gate)
        self.assertEqual(self.gate_calls, [commit, commit])
        self.assertEqual(value.result["status"], "PASSED_DEVELOPMENT")
        self.assertFalse(value.result["human_independence_verified"])
        self.assertEqual(
            {path.name for path in value.artifact_path.iterdir()},
            artifacts._OUTPUT_NAMES,
        )
        self.assertTrue(
            all(
                (path.stat().st_mode & 0o777) == 0o600
                for path in value.artifact_path.iterdir()
            )
        )
        replay = artifacts._verify(self.root, self.sources, commit)
        self.assertEqual(replay.manifest_sha256, value.manifest_sha256)
        self.assertEqual(replay.result_semantic_sha256, value.result_semantic_sha256)
        with self.assertRaisesRegex(
            artifacts.DevelopmentAuditArtifactError, "already exists"
        ):
            artifacts._publish(self.root, self.sources, commit, self.gate)

    def test_source_and_output_tampering_fail_closed(self):
        commit = "e" * 40
        value = artifacts._publish(self.root, self.sources, commit, self.gate)
        result_path = value.artifact_path / artifacts.RESULT_NAME
        payload = result_path.read_bytes()
        result_path.write_bytes(payload.replace(b"PASSED_DEVELOPMENT", b"BLOCKED_DEVELOPMENT"))
        os.chmod(result_path, 0o600)
        with self.assertRaises(artifacts.DevelopmentAuditArtifactError):
            artifacts._verify(self.root, self.sources, commit)

        self.tearDown()
        self.setUp()
        extra = self.sources.intake_dir / "extra"
        _write(extra, b"x")
        with self.assertRaisesRegex(
            artifacts.DevelopmentAuditArtifactError, "namespace"
        ):
            artifacts._publish(self.root, self.sources, commit, self.gate)


if __name__ == "__main__":
    unittest.main()
