import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from kairos.ids import canonical_json, make_stable_id, sha256_canonical
from kairos.training_plan import (
    CandidateBinding,
    TrainingCorpusBinding,
    TrainingExampleBinding,
    build_training_plan,
)
from kairos import training_plan_artifacts as artifacts


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")


def _plan():
    examples = []
    for index in range(3):
        example_id = make_stable_id("example", {"plan-artifact": index})
        gold = str(index)
        candidate = CandidateBinding.from_text(
            example_id, gold, ("direct",)
        )
        examples.append(
            TrainingExampleBinding(
                source_order_index=index,
                example_id=example_id,
                source_id=make_stable_id("source", {"plan-artifact": index}),
                original_record_id=make_stable_id(
                    "record", {"plan-artifact": index, "variant": "original"}
                ),
                counterfactual_record_id=make_stable_id(
                    "record", {"plan-artifact": index, "variant": "cf"}
                ),
                record_sha256=sha256_canonical({"record": index}),
                gold_answer_sha256=candidate.content_sha256,
                candidates=(candidate,),
                answer_target_index=0,
                gold_injected=False,
            )
        )
    corpus = TrainingCorpusBinding(
        execution_commit="d" * 40,
        dataset_id="synthetic",
        dataset_revision="e" * 40,
        official_split="train",
        source_artifact_id="DEV-SYNTHETIC-SOURCE-V1",
        source_manifest_sha256="f" * 64,
        examples=tuple(examples),
    )
    return build_training_plan(corpus, 13, 2)


class TrainingPlanArtifactTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-training-plan-artifact-test-", dir=TEST_TMP
        )
        self.root = Path(self.temporary.name) / "plans"
        self.gate_calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def gate(self, commit):
        self.gate_calls.append(commit)

    def test_publish_and_independent_replay_are_private_and_exact(self):
        plan = _plan()
        value = artifacts._publish(self.root, plan, self.gate)
        self.assertEqual(self.gate_calls, ["d" * 40, "d" * 40])
        self.assertEqual(value.plan, plan)
        self.assertEqual(value.plan_semantic_sha256, plan.manifest_sha256)
        self.assertEqual(value.plan_id, artifacts.make_plan_id(plan))
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(value.artifact_path.stat().st_mode), 0o700)
        self.assertEqual(
            {path.name for path in value.artifact_path.iterdir()},
            {artifacts.PLAN_NAME, artifacts.MANIFEST_NAME},
        )
        self.assertTrue(
            all(
                stat.S_IMODE(path.stat().st_mode) == 0o600
                for path in value.artifact_path.iterdir()
            )
        )
        replay = artifacts._verify(self.root, value.plan_id)
        self.assertEqual(replay.plan_file_sha256, value.plan_file_sha256)
        self.assertEqual(replay.manifest_sha256, value.manifest_sha256)

    def test_existing_target_and_extra_namespace_are_rejected(self):
        plan = _plan()
        value = artifacts._publish(self.root, plan, self.gate)
        with self.assertRaisesRegex(
            artifacts.TrainingPlanArtifactError, "already exists"
        ):
            artifacts._publish(self.root, plan, self.gate)
        extra = value.artifact_path / "extra"
        extra.write_text("x", encoding="utf-8")
        os.chmod(extra, 0o600)
        with self.assertRaisesRegex(
            artifacts.TrainingPlanArtifactError, "namespace"
        ):
            artifacts._verify(self.root, value.plan_id)

    def test_plan_and_manifest_tampering_fail_reconstruction(self):
        value = artifacts._publish(self.root, _plan(), self.gate)
        plan_path = value.artifact_path / artifacts.PLAN_NAME
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
        raw["slots"][0]["example_id"] = raw["slots"][1]["example_id"]
        plan_path.write_bytes(canonical_json(raw).encode("utf-8") + b"\n")
        os.chmod(plan_path, 0o600)
        with self.assertRaisesRegex(
            artifacts.TrainingPlanArtifactError, "reconstruction"
        ):
            artifacts._verify(self.root, value.plan_id)

        self.tearDown()
        self.setUp()
        value = artifacts._publish(self.root, _plan(), self.gate)
        manifest_path = value.artifact_path / artifacts.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["plan"]["byte_size"] += 1
        manifest_path.write_bytes(canonical_json(manifest).encode("utf-8") + b"\n")
        os.chmod(manifest_path, 0o600)
        with self.assertRaisesRegex(
            artifacts.TrainingPlanArtifactError, "facts differ"
        ):
            artifacts._verify(self.root, value.plan_id)

    def test_second_git_gate_failure_retains_plan_only(self):
        calls = []

        def gate(commit):
            calls.append(commit)
            if len(calls) == 2:
                raise OSError("synthetic gate failure")

        with self.assertRaisesRegex(
            artifacts.TrainingPlanArtifactError, "partial state"
        ):
            artifacts._publish(self.root, _plan(), gate)
        target = next(self.root.iterdir())
        self.assertEqual({path.name for path in target.iterdir()}, {artifacts.PLAN_NAME})


if __name__ == "__main__":
    unittest.main()
