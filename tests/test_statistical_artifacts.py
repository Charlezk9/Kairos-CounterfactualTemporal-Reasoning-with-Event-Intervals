import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from kairos.ids import canonical_json
from kairos import metrics_artifacts, prediction_artifacts, statistical_artifacts
from kairos.transfer_eval import (
    TimeQaExample,
    TorqueExample,
    evaluate_timeqa,
    evaluate_torque,
)


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")
AGGREGATION_COMMIT = "a" * 40
MODEL_REVISION = "b" * 40


def _torque_examples():
    return (
        TorqueExample("record-1", "passage-1", "cluster-1", "q1", "p1", ("A",), ("0",), True, ""),
        TorqueExample("record-2", "passage-1", "cluster-1", "q2", "p1", ("B",), ("1",), False, "q1"),
        TorqueExample("record-3", "passage-2", "cluster-2", "q3", "p2", ("C",), ("0",), True, ""),
    )


def _timeqa_examples():
    return tuple(
        TimeQaExample(
            record_id=f"record-{number}",
            idx=str(number),
            question=f"q{number}",
            context="context",
            paragraphs=(),
            targets=(answer,),
        )
        for number, answer in enumerate(("alpha", "beta", "gamma", "delta"), start=1)
    )


def _spec(dataset, method, completed_at):
    config = {"generation": {"do_sample": False, "max_new_tokens": 32}}
    started_at = "2026-07-23T10:00:00Z"
    return prediction_artifacts.RunSpec(
        run_id=prediction_artifacts.make_run_id(started_at, method, dataset, 13, config),
        dataset=dataset,
        method_name=method,
        model_id="Qwen/Qwen2.5-7B-Instruct",
        model_revision=MODEL_REVISION,
        execution_commit="c" * 40,
        seed=13,
        started_at=started_at,
        completed_at=completed_at,
        config=config,
        gpu_ids=(0,),
        cpu_threads=2,
        memory_gib=16,
        dataloader_workers=0,
    )


def _verified_prediction(spec, predictions, suffix):
    return prediction_artifacts.VerifiedPredictionArtifact(
        spec=spec,
        records=tuple(
            prediction_artifacts.PredictionRecord(record_id, value)
            for record_id, value in predictions.items()
        ),
        evidence=(),
        config_sha256=suffix * 64,
        predictions_sha256=chr(ord(suffix) + 1) * 64,
        evidence_sha256=chr(ord(suffix) + 2) * 64,
        manifest_sha256=chr(ord(suffix) + 3) * 64,
        artifact_path=Path("/unused"),
    )


def _verified_metrics(prediction, examples, completed_at, suffix):
    predictions = {record.record_id: record.prediction for record in prediction.records}
    evaluator = evaluate_torque if prediction.spec.dataset == "torque-dev" else evaluate_timeqa
    return metrics_artifacts.VerifiedMetricsArtifact(
        run_id=prediction.spec.run_id,
        aggregation_commit="d" * 40,
        completed_at=completed_at,
        metrics=evaluator(examples, predictions),
        generation_summary={},
        prediction_manifest_sha256=prediction.manifest_sha256,
        metrics_sha256=suffix * 64,
        manifest_sha256=chr(ord(suffix) + 1) * 64,
        artifact_path=Path("/unused"),
    )


class StatisticalFixture(unittest.TestCase):
    dataset = "torque-dev"

    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-statistics-artifact-test-", dir=TEST_TMP
        )
        self.root = Path(self.temporary.name) / "statistics"
        if self.dataset == "torque-dev":
            self.examples = _torque_examples()
            reference_values = {
                "record-1": ["A"], "record-2": ["B"], "record-3": ["C"]
            }
            candidate_values = {
                "record-1": [], "record-2": [], "record-3": ["C"]
            }
        else:
            self.examples = _timeqa_examples()
            reference_values = {
                "record-1": "alpha", "record-2": "beta",
                "record-3": "wrong", "record-4": "wrong",
            }
            candidate_values = {
                "record-1": "alpha", "record-2": "beta",
                "record-3": "gamma", "record-4": "wrong",
            }
        reference_spec = _spec(self.dataset, "direct", "2026-07-23T10:10:00Z")
        candidate_spec = _spec(self.dataset, "cot", "2026-07-23T10:20:00Z")
        self.reference = _verified_prediction(reference_spec, reference_values, "1")
        self.candidate = _verified_prediction(candidate_spec, candidate_values, "5")
        self.reference_metrics = _verified_metrics(
            self.reference, self.examples, "2026-07-23T10:30:00Z", "9"
        )
        self.candidate_metrics = _verified_metrics(
            self.candidate, self.examples, "2026-07-23T10:31:00Z", "b"
        )
        self.predictions = {
            self.reference.spec.run_id: self.reference,
            self.candidate.spec.run_id: self.candidate,
        }
        self.metrics = {
            self.reference.spec.run_id: self.reference_metrics,
            self.candidate.spec.run_id: self.candidate_metrics,
        }
        self.gate_calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def prediction_verifier(self, run_id):
        return self.predictions[run_id]

    def metrics_verifier(self, run_id):
        return self.metrics[run_id]

    def gate(self, commit):
        self.gate_calls.append(commit)

    def publish(self, prediction_verifier=None):
        return statistical_artifacts._publish(
            self.root,
            self.reference.spec.run_id,
            self.candidate.spec.run_id,
            20260723,
            10_000,
            AGGREGATION_COMMIT,
            "2026-07-23T10:40:00Z",
            prediction_verifier or self.prediction_verifier,
            self.metrics_verifier,
            lambda: self.examples,
            self.gate,
        )

    def rewrite(self, path, mutation):
        value = json.loads(path.read_text(encoding="utf-8"))
        mutation(value)
        path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
        os.chmod(path, 0o600)


class StatisticalPublicationTests(StatisticalFixture):
    def test_publish_and_independent_replay(self):
        artifact = self.publish()
        self.assertEqual(self.gate_calls, [AGGREGATION_COMMIT, AGGREGATION_COMMIT])
        self.assertEqual(artifact.dataset, "torque-dev")
        self.assertAlmostEqual(
            artifact.results["question_exact_match"]["difference_candidate_minus_reference"],
            -200.0 / 3.0,
        )
        for result in artifact.results.values():
            self.assertLessEqual(result["confidence_interval_95"]["lower"], result["confidence_interval_95"]["upper"])
            self.assertGreaterEqual(result["p_value_holm"], result["p_value_raw"])
            self.assertLessEqual(result["p_value_holm"], 1.0)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(
            {path.name for path in artifact.artifact_path.iterdir()},
            {"statistics.json", "manifest.json"},
        )
        replay = statistical_artifacts._verify(
            self.root,
            artifact.comparison_id,
            self.prediction_verifier,
            self.metrics_verifier,
            lambda: self.examples,
        )
        self.assertEqual(replay.statistics_sha256, artifact.statistics_sha256)
        self.assertEqual(replay.manifest_sha256, artifact.manifest_sha256)

    def test_existing_artifact_is_never_replaced(self):
        artifact = self.publish()
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact.artifact_path.iterdir()
        }
        with self.assertRaisesRegex(
            statistical_artifacts.StatisticalArtifactError, "already exists"
        ):
            self.publish()
        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact.artifact_path.iterdir()
        }
        self.assertEqual(before, after)

    def test_input_change_before_manifest_is_rejected(self):
        calls = {self.reference.spec.run_id: 0, self.candidate.spec.run_id: 0}

        def changing(run_id):
            calls[run_id] += 1
            value = self.prediction_verifier(run_id)
            if run_id == self.candidate.spec.run_id and calls[run_id] == 2:
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
            statistical_artifacts.StatisticalArtifactError, "changed before publication"
        ):
            self.publish(prediction_verifier=changing)
        target = next(self.root.iterdir())
        self.assertEqual({path.name for path in target.iterdir()}, {"statistics.json"})


class StatisticalVerificationTests(StatisticalFixture):
    def test_rehashed_statistics_tamper_fails_recomputation(self):
        artifact = self.publish()
        statistics_path = artifact.artifact_path / "statistics.json"
        self.rewrite(
            statistics_path,
            lambda value: value["results"]["question_exact_match"].update(
                {"difference_candidate_minus_reference": 99.0}
            ),
        )
        payload = statistics_path.read_bytes()
        self.rewrite(
            artifact.artifact_path / "manifest.json",
            lambda value: value["statistics"].update(
                {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                }
            ),
        )
        with self.assertRaisesRegex(
            statistical_artifacts.StatisticalArtifactError, "independent recomputation"
        ):
            statistical_artifacts._verify(
                self.root,
                artifact.comparison_id,
                self.prediction_verifier,
                self.metrics_verifier,
                lambda: self.examples,
            )

    def test_manifest_and_file_metadata_are_checked(self):
        artifact = self.publish()
        self.rewrite(
            artifact.artifact_path / "manifest.json",
            lambda value: value["input_manifests"].update(
                {"candidate_metrics": "f" * 64}
            ),
        )
        with self.assertRaisesRegex(
            statistical_artifacts.StatisticalArtifactError, "manifest facts differ"
        ):
            statistical_artifacts._verify(
                self.root,
                artifact.comparison_id,
                self.prediction_verifier,
                self.metrics_verifier,
                lambda: self.examples,
            )

        self.tearDown()
        self.setUp()
        artifact = self.publish()
        os.chmod(artifact.artifact_path / "statistics.json", 0o644)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "metadata is invalid"
        ):
            statistical_artifacts._verify(
                self.root,
                artifact.comparison_id,
                self.prediction_verifier,
                self.metrics_verifier,
                lambda: self.examples,
            )


class TimeQaStatisticalPublicationTests(StatisticalFixture):
    dataset = "timeqa-hard"

    def test_timeqa_record_bootstrap(self):
        artifact = self.publish()
        self.assertEqual(
            set(artifact.results), {"exact_match", "token_f1"}
        )
        self.assertEqual(
            artifact.results["exact_match"]["difference_candidate_minus_reference"],
            25.0,
        )
        self.assertEqual(
            artifact.results["token_f1"]["difference_candidate_minus_reference"],
            25.0,
        )


if __name__ == "__main__":
    unittest.main()
