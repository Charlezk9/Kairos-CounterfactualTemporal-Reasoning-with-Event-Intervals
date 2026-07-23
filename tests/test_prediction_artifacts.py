import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import stat
import tempfile
import unittest

from kairos.ids import canonical_json
from kairos import prediction_artifacts


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")
COMMIT = "a" * 40


def _binding(dataset="torque-dev"):
    prediction_schema = "string-array" if dataset == "torque-dev" else "string"
    return prediction_artifacts._DatasetBinding(
        name=dataset,
        split="synthetic",
        revision="b" * 40,
        source_sha256="c" * 64,
        record_count=2,
        adapter_schema_version="synthetic-adapter-v1",
        metric_contract_version="synthetic-metric-v1",
        prediction_value_schema=prediction_schema,
        loader=lambda: (
            SimpleNamespace(record_id="record-1"),
            SimpleNamespace(record_id="record-2"),
        ),
    )


def _spec(dataset="torque-dev", **changes):
    values = {
        "dataset": dataset,
        "method_name": "direct",
        "model_id": "Qwen/Qwen2.5-7B-Instruct",
        "model_revision": "d" * 40,
        "execution_commit": COMMIT,
        "seed": 13,
        "started_at": "2026-07-23T10:20:30Z",
        "completed_at": "2026-07-23T10:21:30Z",
        "config": {"generation": {"do_sample": False, "max_new_tokens": 32}},
        "gpu_ids": (0,),
        "cpu_threads": 4,
        "memory_gib": 16,
        "dataloader_workers": 2,
    }
    values.update(changes)
    values["run_id"] = prediction_artifacts.make_run_id(
        values["started_at"],
        values["method_name"],
        values["dataset"],
        values["seed"],
        values["config"],
    )
    if "run_id" in changes:
        values["run_id"] = changes["run_id"]
    return prediction_artifacts.RunSpec(**values)


def _evidence(status="PARSED"):
    return {
        "record-1": prediction_artifacts.GenerationEvidence(
            raw_response='FINAL_ANSWER: ["Alpha"]',
            parse_status=status,
            input_token_count=120,
            generated_token_count=8,
        ),
        "record-2": prediction_artifacts.GenerationEvidence(
            raw_response="FINAL_ANSWER: []",
            parse_status=status,
            input_token_count=100,
            generated_token_count=4,
        ),
    }


class ArtifactFixture(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-prediction-artifact-test-", dir=TEST_TMP
        )
        self.base = Path(self.temporary.name)
        self.root = self.base / "artifacts"
        self.gate_calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def gate(self, commit):
        self.gate_calls.append(commit)

    def publish(self, dataset="torque-dev", predictions=None, gate=None):
        binding = _binding(dataset)
        spec = _spec(dataset)
        if predictions is None:
            predictions = (
                {"record-1": ["Alpha"], "record-2": []}
                if dataset == "torque-dev"
                else {"record-1": "answer", "record-2": ""}
            )
        artifact = prediction_artifacts._publish(
            self.root,
            binding,
            spec,
            predictions,
            _evidence(),
            gate or self.gate,
        )
        return binding, spec, artifact

    def rewrite_manifest(self, target, mutation):
        path = target / "manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutation(value)
        path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
        os.chmod(path, 0o600)


class RunSpecTests(unittest.TestCase):
    def test_run_id_is_literal_stable_and_config_sensitive(self):
        first = _spec()
        second = _spec()
        changed = _spec(config={"generation": {"do_sample": False, "max_new_tokens": 64}})
        self.assertEqual(first.run_id, second.run_id)
        self.assertRegex(
            first.run_id,
            r"^20260723T102030Z-direct-torque-dev-s13-[0-9a-f]{12}$",
        )
        self.assertNotEqual(first.run_id, changed.run_id)

    def test_spec_rejects_run_timestamp_commit_and_resource_changes(self):
        cases = [
            ({"run_id": "wrong"}, "run ID"),
            ({"started_at": "2026-07-23 10:20:30"}, "UTC"),
            ({"completed_at": "2026-07-23T10:19:30Z"}, "precedes"),
            ({"execution_commit": "A" * 40}, "40 lowercase"),
            ({"gpu_ids": (0, 0)}, "uniqueness"),
            ({"gpu_ids": (0, 1, 2, 3, 4)}, "count"),
            ({"cpu_threads": 17}, "allowed range"),
            ({"memory_gib": 65}, "allowed range"),
            ({"dataloader_workers": 9}, "allowed range"),
            ({"seed": True}, "integer"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(
                    prediction_artifacts.PredictionArtifactError, message
                ):
                    _spec(**changes)

    def test_config_must_be_canonical_json_mapping(self):
        for config in ([1, 2], {"bad": object()}, {"bad": float("nan")}):
            with self.subTest(config=type(config).__name__):
                with self.assertRaises(prediction_artifacts.PredictionArtifactError):
                    _spec(config=config)

    def test_generation_evidence_schema_is_bounded(self):
        valid = prediction_artifacts.GenerationEvidence(
            raw_response="FINAL_ANSWER: []",
            parse_status="PARSED",
            input_token_count=20,
            generated_token_count=4,
        )
        self.assertEqual(valid.parse_status, "PARSED")
        cases = [
            ({"raw_response": "", "parse_status": "PARSED"}, "non-empty"),
            ({"raw_response": "x", "parse_status": "UNKNOWN"}, "invalid"),
            ({"raw_response": "x", "input_token_count": 32769}, "allowed range"),
            ({"raw_response": "x", "generated_token_count": 4097}, "allowed range"),
        ]
        base = {
            "raw_response": "x",
            "parse_status": "PARSE_ERROR",
            "input_token_count": 20,
            "generated_token_count": 4,
        }
        for changes, message in cases:
            with self.subTest(changes=changes):
                values = dict(base)
                values.update(changes)
                with self.assertRaisesRegex(
                    prediction_artifacts.PredictionArtifactError, message
                ):
                    prediction_artifacts.GenerationEvidence(**values)


class PublicationTests(ArtifactFixture):
    def test_torque_publish_and_offline_verify(self):
        binding, spec, artifact = self.publish()

        self.assertEqual(self.gate_calls, [COMMIT, COMMIT])
        self.assertEqual(artifact.spec, spec)
        self.assertEqual(
            tuple(record.record_id for record in artifact.records),
            ("record-1", "record-2"),
        )
        self.assertEqual(artifact.records[0].prediction, ["Alpha"])
        self.assertEqual(artifact.records[1].prediction, [])
        self.assertEqual(artifact.evidence[0].parse_status, "PARSED")
        self.assertEqual(artifact.evidence[0].input_token_count, 120)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(artifact.artifact_path.stat().st_mode), 0o700)
        self.assertEqual(
            {path.name for path in artifact.artifact_path.iterdir()},
            {
                "config.json",
                "predictions.jsonl",
                "generation-evidence.jsonl",
                "manifest.json",
            },
        )
        for path in artifact.artifact_path.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)

        repeated = prediction_artifacts._verify(self.root, binding, spec.run_id)
        self.assertEqual(repeated.predictions_sha256, artifact.predictions_sha256)
        self.assertEqual(repeated.manifest_sha256, artifact.manifest_sha256)

    def test_timeqa_empty_prediction_round_trips(self):
        unused, unused_spec, artifact = self.publish("timeqa-hard")
        self.assertEqual(artifact.records[0].prediction, "answer")
        self.assertEqual(artifact.records[1].prediction, "")

    def test_prediction_contract_rejects_coverage_and_value_types_before_create(self):
        cases = [
            ({"record-1": ["A"]}, "key mismatch"),
            ({"record-1": ["A"], "record-2": [], "extra": []}, "key mismatch"),
            ({"record-1": "A", "record-2": []}, "non-string sequence"),
            ({"record-1": [""], "record-2": []}, "non-empty"),
        ]
        for number, (predictions, message) in enumerate(cases):
            with self.subTest(message=message):
                root = self.base / f"invalid-{number}"
                with self.assertRaisesRegex(
                    prediction_artifacts.PredictionArtifactError, message
                ):
                    prediction_artifacts._publish(
                        root,
                        _binding(),
                        _spec(),
                        predictions,
                        _evidence(),
                        self.gate,
                    )
                self.assertFalse(root.exists())

        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "must be a string"
        ):
            prediction_artifacts._publish(
                self.base / "invalid-timeqa",
                _binding("timeqa-hard"),
                _spec("timeqa-hard"),
                {"record-1": [], "record-2": ""},
                _evidence(),
                self.gate,
            )

    def test_generation_evidence_coverage_and_types_fail_before_create(self):
        predictions = {"record-1": ["A"], "record-2": []}
        cases = [
            ({"record-1": _evidence()["record-1"]}, "key mismatch"),
            ({**_evidence(), "extra": _evidence()["record-1"]}, "key mismatch"),
            ({"record-1": "raw", "record-2": _evidence()["record-2"]}, "values"),
        ]
        for number, (evidence, message) in enumerate(cases):
            root = self.base / f"invalid-evidence-{number}"
            with self.subTest(message=message):
                with self.assertRaisesRegex(
                    prediction_artifacts.PredictionArtifactError, message
                ):
                    prediction_artifacts._publish(
                        root,
                        _binding(),
                        _spec(),
                        predictions,
                        evidence,
                        self.gate,
                    )
                self.assertFalse(root.exists())

    def test_git_gates_precede_create_and_manifest(self):
        def fail_first(unused):
            raise prediction_artifacts.PredictionArtifactError("dirty")

        with self.assertRaisesRegex(prediction_artifacts.PredictionArtifactError, "dirty"):
            self.publish(gate=fail_first)
        self.assertFalse(self.root.exists())

        calls = 0

        def fail_second(unused):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise prediction_artifacts.PredictionArtifactError("changed")

        with self.assertRaisesRegex(prediction_artifacts.PredictionArtifactError, "changed"):
            self.publish(gate=fail_second)
        target = self.root / _spec().run_id
        self.assertEqual(
            {path.name for path in target.iterdir()},
            {"config.json", "predictions.jsonl", "generation-evidence.jsonl"},
        )

    def test_existing_run_is_never_replaced(self):
        unused, spec, artifact = self.publish()
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact.artifact_path.iterdir()
        }
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "already exists"
        ):
            prediction_artifacts._publish(
                self.root,
                _binding(),
                spec,
                {"record-1": ["changed"], "record-2": []},
                _evidence(),
                self.gate,
            )
        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact.artifact_path.iterdir()
        }
        self.assertEqual(before, after)


class VerificationTests(ArtifactFixture):
    def test_tampered_config_is_rejected(self):
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        (target / "config.json").write_bytes(b'{"changed":true}\n')
        os.chmod(target / "config.json", 0o600)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError,
            "configuration manifest facts differ",
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

    def test_tampered_evidence_prediction_and_manifest_are_rejected(self):
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        path = target / "generation-evidence.jsonl"
        path.write_bytes(path.read_bytes().replace(b"PARSED", b"PARSE_ERROR", 1))
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError,
            "generation evidence manifest facts differ",
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

        self.tearDown()
        self.setUp()
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        content = (target / "predictions.jsonl").read_bytes()
        (target / "predictions.jsonl").write_bytes(content.replace(b"Alpha", b"Beta"))
        os.chmod(target / "predictions.jsonl", 0o600)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError,
            "prediction manifest facts differ",
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

        self.tearDown()
        self.setUp()
        binding, spec, artifact = self.publish()
        self.rewrite_manifest(
            artifact.artifact_path,
            lambda value: value["dataset"].update({"revision": "e" * 40}),
        )
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "dataset binding differs"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

    def test_rehashed_prediction_reorder_still_fails_source_lockstep(self):
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        path = target / "predictions.jsonl"
        lines = path.read_bytes().splitlines(keepends=True)
        reordered = b"".join(reversed(lines))
        path.write_bytes(reordered)
        os.chmod(path, 0o600)

        def update(value):
            value["predictions"]["sha256"] = hashlib.sha256(reordered).hexdigest()

        self.rewrite_manifest(target, update)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "order or coverage"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

    def test_extra_missing_mode_hardlink_and_symlink_are_rejected(self):
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        (target / "extra").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "incomplete or extra"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

        self.tearDown()
        self.setUp()
        binding, spec, artifact = self.publish()
        path = artifact.artifact_path / "config.json"
        os.chmod(path, 0o644)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "metadata is invalid"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

        self.tearDown()
        self.setUp()
        binding, spec, artifact = self.publish()
        path = artifact.artifact_path / "config.json"
        os.link(path, self.base / "alias")
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "metadata is invalid"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

        self.tearDown()
        self.setUp()
        binding, spec, artifact = self.publish()
        path = artifact.artifact_path / "config.json"
        path.unlink()
        path.symlink_to(self.base / "outside")
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "cannot open"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

    def test_duplicate_noncanonical_and_wrong_record_binding_are_rejected(self):
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        path = target / "manifest.json"
        content = path.read_bytes().replace(
            b'"status":"PREDICTIONS_COMPLETE"',
            b'"status":"PREDICTIONS_COMPLETE","status":"PREDICTIONS_COMPLETE"',
        )
        path.write_bytes(content)
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "duplicate"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)

        self.tearDown()
        self.setUp()
        binding, spec, artifact = self.publish()
        target = artifact.artifact_path
        path = target / "predictions.jsonl"
        lines = path.read_bytes().splitlines(keepends=True)
        first = json.loads(lines[0])
        first["run_id"] = _spec(config={"different": True}).run_id
        changed = canonical_json(first).encode("utf-8") + b"\n" + lines[1]
        path.write_bytes(changed)
        os.chmod(path, 0o600)

        def update(value):
            value["predictions"]["sha256"] = hashlib.sha256(changed).hexdigest()
            value["predictions"]["byte_size"] = len(changed)

        self.rewrite_manifest(target, update)
        with self.assertRaisesRegex(
            prediction_artifacts.PredictionArtifactError, "record binding differs"
        ):
            prediction_artifacts._verify(self.root, binding, spec.run_id)


if __name__ == "__main__":
    unittest.main()
