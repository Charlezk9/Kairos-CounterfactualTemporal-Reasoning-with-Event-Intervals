import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import stat
import tempfile
import unittest

from kairos.ids import canonical_json
from kairos import metrics_artifacts, prediction_artifacts


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")
COMMIT = "a" * 40
AGGREGATION_COMMIT = "b" * 40


def _binding():
    return prediction_artifacts._DatasetBinding(
        name="torque-dev",
        split="synthetic",
        revision="c" * 40,
        source_sha256="d" * 64,
        record_count=2,
        adapter_schema_version="synthetic-adapter-v1",
        metric_contract_version="torque-set-metrics-v1",
        prediction_value_schema="string-array",
        loader=lambda: (
            SimpleNamespace(record_id="record-1"),
            SimpleNamespace(record_id="record-2"),
        ),
    )


def _spec():
    config = {"generation": {"do_sample": False, "max_new_tokens": 32}}
    started_at = "2026-07-23T10:20:30Z"
    return prediction_artifacts.RunSpec(
        run_id=prediction_artifacts.make_run_id(
            started_at, "direct", "torque-dev", 13, config
        ),
        dataset="torque-dev",
        method_name="direct",
        model_id="Qwen/Qwen2.5-7B-Instruct",
        model_revision="e" * 40,
        execution_commit=COMMIT,
        seed=13,
        started_at=started_at,
        completed_at="2026-07-23T10:21:30Z",
        config=config,
        gpu_ids=(0,),
        cpu_threads=2,
        memory_gib=16,
        dataloader_workers=0,
    )


def _evidence():
    return {
        "record-1": prediction_artifacts.GenerationEvidence(
            raw_response='FINAL_ANSWER: ["Alpha"]',
            parse_status="PARSED",
            input_token_count=120,
            generated_token_count=8,
        ),
        "record-2": prediction_artifacts.GenerationEvidence(
            raw_response="malformed",
            parse_status="PARSE_ERROR",
            input_token_count=100,
            generated_token_count=4,
        ),
    }


def _examples():
    return (
        SimpleNamespace(record_id="record-1"),
        SimpleNamespace(record_id="record-2"),
    )


def _evaluate(examples, predictions):
    if tuple(example.record_id for example in examples) != (
        "record-1",
        "record-2",
    ):
        raise AssertionError("synthetic source order differs")
    score = 100.0 * sum(bool(predictions[item.record_id]) for item in examples) / 2
    return {
        "schema_version": "torque-set-metrics-v1",
        "adapter_schema_version": "synthetic-adapter-v1",
        "question_count": 2,
        "cluster_count": 1,
        "question_exact_match": score,
        "question_set_f1": score,
        "cluster_exact_consistency": 0.0,
        "cluster_f1_80_consistency": 0.0,
    }


class MetricsFixture(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-metrics-artifact-test-", dir=TEST_TMP
        )
        self.base = Path(self.temporary.name)
        self.prediction_root = self.base / "predictions"
        self.metrics_root = self.base / "metrics"
        self.gate_calls = []
        self.prediction = prediction_artifacts._publish(
            self.prediction_root,
            _binding(),
            _spec(),
            {"record-1": ["Alpha"], "record-2": []},
            _evidence(),
            lambda unused: None,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def verifier(self, run_id):
        if run_id != self.prediction.spec.run_id:
            raise AssertionError("unexpected run ID")
        return prediction_artifacts._verify(
            self.prediction_root, _binding(), run_id
        )

    def gate(self, commit):
        self.gate_calls.append(commit)

    def publish(self, gate=None, verifier=None):
        return metrics_artifacts._publish(
            self.metrics_root,
            self.prediction.spec.run_id,
            AGGREGATION_COMMIT,
            "2026-07-23T10:30:00Z",
            verifier or self.verifier,
            _examples,
            _evaluate,
            gate or self.gate,
        )

    def rewrite(self, path, mutation):
        value = json.loads(path.read_text(encoding="utf-8"))
        mutation(value)
        path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
        os.chmod(path, 0o600)


class MetricsPublicationTests(MetricsFixture):
    def test_publish_and_independent_replay(self):
        artifact = self.publish()
        self.assertEqual(self.gate_calls, [AGGREGATION_COMMIT, AGGREGATION_COMMIT])
        self.assertEqual(artifact.metrics["question_exact_match"], 50.0)
        self.assertEqual(
            artifact.generation_summary["parse_status_counts"],
            {"PARSED": 1, "PARSE_ERROR": 1, "NOT_APPLICABLE": 0},
        )
        self.assertEqual(artifact.generation_summary["input_token_count_min"], 100)
        self.assertEqual(artifact.generation_summary["input_token_count_max"], 120)
        self.assertEqual(artifact.generation_summary["generated_token_count_total"], 12)
        self.assertEqual(stat.S_IMODE(self.metrics_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(artifact.artifact_path.stat().st_mode), 0o700)
        self.assertEqual(
            {path.name for path in artifact.artifact_path.iterdir()},
            {"metrics.json", "manifest.json"},
        )
        for path in artifact.artifact_path.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
        replay = metrics_artifacts._verify(
            self.metrics_root,
            self.prediction.spec.run_id,
            self.verifier,
            _examples,
            _evaluate,
        )
        self.assertEqual(replay.metrics_sha256, artifact.metrics_sha256)
        self.assertEqual(replay.manifest_sha256, artifact.manifest_sha256)

    def test_existing_artifact_is_never_replaced(self):
        artifact = self.publish()
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact.artifact_path.iterdir()
        }
        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "already exists"
        ):
            self.publish()
        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact.artifact_path.iterdir()
        }
        self.assertEqual(before, after)

    def test_git_gates_precede_create_and_manifest(self):
        def fail_first(unused):
            raise metrics_artifacts.MetricsArtifactError("dirty")

        with self.assertRaisesRegex(metrics_artifacts.MetricsArtifactError, "dirty"):
            self.publish(gate=fail_first)
        self.assertFalse(self.metrics_root.exists())

        calls = 0

        def fail_second(unused):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise metrics_artifacts.MetricsArtifactError("changed")

        with self.assertRaisesRegex(metrics_artifacts.MetricsArtifactError, "changed"):
            self.publish(gate=fail_second)
        target = self.metrics_root / self.prediction.spec.run_id
        self.assertEqual({path.name for path in target.iterdir()}, {"metrics.json"})

    def test_prediction_change_before_manifest_is_rejected(self):
        calls = 0

        def changing_verifier(run_id):
            nonlocal calls
            calls += 1
            value = self.verifier(run_id)
            if calls == 2:
                return prediction_artifacts.VerifiedPredictionArtifact(
                    spec=value.spec,
                    records=value.records,
                    evidence=value.evidence,
                    config_sha256=value.config_sha256,
                    predictions_sha256="f" * 64,
                    evidence_sha256=value.evidence_sha256,
                    manifest_sha256=value.manifest_sha256,
                    artifact_path=value.artifact_path,
                )
            return value

        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "changed before publication"
        ):
            self.publish(verifier=changing_verifier)
        target = self.metrics_root / self.prediction.spec.run_id
        self.assertEqual({path.name for path in target.iterdir()}, {"metrics.json"})


class MetricsVerificationTests(MetricsFixture):
    def test_rehashed_metric_tamper_fails_recomputation(self):
        artifact = self.publish()
        metrics_path = artifact.artifact_path / "metrics.json"
        self.rewrite(
            metrics_path,
            lambda value: value["metrics"].update({"question_exact_match": 99.0}),
        )
        payload = metrics_path.read_bytes()
        self.rewrite(
            artifact.artifact_path / "manifest.json",
            lambda value: value["metrics"].update(
                {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                }
            ),
        )
        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "independent recomputation"
        ):
            metrics_artifacts._verify(
                self.metrics_root,
                self.prediction.spec.run_id,
                self.verifier,
                _examples,
                _evaluate,
            )

    def test_manifest_prediction_binding_and_file_set_are_checked(self):
        artifact = self.publish()
        self.rewrite(
            artifact.artifact_path / "manifest.json",
            lambda value: value.update({"prediction_manifest_sha256": "f" * 64}),
        )
        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "manifest facts differ"
        ):
            metrics_artifacts._verify(
                self.metrics_root,
                self.prediction.spec.run_id,
                self.verifier,
                _examples,
                _evaluate,
            )

        self.tearDown()
        self.setUp()
        artifact = self.publish()
        (artifact.artifact_path / "extra").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "incomplete or extra"
        ):
            metrics_artifacts._verify(
                self.metrics_root,
                self.prediction.spec.run_id,
                self.verifier,
                _examples,
                _evaluate,
            )

    def test_mode_and_hardlink_are_rejected(self):
        artifact = self.publish()
        metrics_path = artifact.artifact_path / "metrics.json"
        os.chmod(metrics_path, 0o644)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "metadata is invalid"
        ):
            metrics_artifacts._verify(
                self.metrics_root,
                self.prediction.spec.run_id,
                self.verifier,
                _examples,
                _evaluate,
            )

        self.tearDown()
        self.setUp()
        artifact = self.publish()
        metrics_path = artifact.artifact_path / "metrics.json"
        os.link(metrics_path, self.base / "alias")
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "metadata is invalid"
        ):
            metrics_artifacts._verify(
                self.metrics_root,
                self.prediction.spec.run_id,
                self.verifier,
                _examples,
                _evaluate,
            )

    def test_aggregation_identity_is_strict(self):
        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "40 lowercase"
        ):
            metrics_artifacts._publish(
                self.metrics_root,
                self.prediction.spec.run_id,
                "A" * 40,
                "2026-07-23T10:30:00Z",
                self.verifier,
                _examples,
                _evaluate,
                self.gate,
            )
        with self.assertRaisesRegex(
            metrics_artifacts.MetricsArtifactError, "precedes"
        ):
            metrics_artifacts._publish(
                self.metrics_root,
                self.prediction.spec.run_id,
                AGGREGATION_COMMIT,
                "2026-07-23T10:00:00Z",
                self.verifier,
                _examples,
                _evaluate,
                self.gate,
            )


if __name__ == "__main__":
    unittest.main()
