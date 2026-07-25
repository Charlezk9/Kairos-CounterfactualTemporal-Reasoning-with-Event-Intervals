import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
import secrets
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from kairos.ids import canonical_json
from kairos import production_training as production


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")


def _gate_value(commit="a" * 40):
    before = 30 * 1024**3
    return {
        "schema_version": production.RESOURCE_SCHEMA,
        "status": "PASSED",
        "gate_id": "placeholder",
        "observed_at_utc": "2026-07-25T00:00:00Z",
        "execution_commit": commit,
        "resource_commands": ["nvidia-smi", "free -h", "df -h"],
        "resource_observations": {
            "nvidia-smi": {"argv": ["/usr/bin/nvidia-smi"], "stdout_sha256": "1" * 64},
            "free-h": {"argv": ["/usr/bin/free", "-h"], "stdout_sha256": "2" * 64},
            "df-h": {
                "argv": ["/usr/bin/df", "-h", str(production.ALLOWED_ROOT)],
                "stdout_sha256": "3" * 64,
            },
        },
        "selected_gpu": {
            "physical_index": 5,
            "uuid": "GPU-test",
            "pci_bus_id": "00000000:89:00.0",
            "name": "NVIDIA GeForce RTX 3090",
            "total_mib": 24576,
            "free_mib": 24243,
            "free_bytes": 24243 * 1024**2,
            "driver_version": "550.163.01",
            "torch_total_bytes": 25_430_786_048,
            "compute_process_count": 0,
        },
        "gpu_count": 1,
        "cpu_thread_limit": 8,
        "dataloader_workers": 2,
        "memory_task_limit_bytes": 64 * 1024**3,
        "memory_available_bytes": 200 * 1024**3,
        "data0_free_bytes": 160 * 1024**3,
        "new_disk_budget_bytes": 80 * 1024**3,
        "project_bytes_before": before,
        "projected_new_bytes": production.PROJECTED_NEW_BYTES,
        "projected_project_bytes_after": before + production.PROJECTED_NEW_BYTES,
        "model_files_verified": True,
        "model_file_count": 15,
        "model_sha256sums_sha256": production.MODEL_SHA256SUMS_SHA256,
        "model_ordered_binding_sha256": "b" * 64,
        "environment": production._environment(),
        "runtime_environment": production._runtime_environment(),
    }


class ProductionResourceGateTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = production.RESOURCE_ROOT / (
            "production-training-test-" + secrets.token_hex(8)
        )
        self.temporary.mkdir(mode=0o700)
        self.scratch = Path(
            tempfile.mkdtemp(prefix="production-runner-test-", dir=TEST_TMP)
        )
        self.scratch.chmod(0o700)

    def tearDown(self):
        shutil.rmtree(self.temporary)
        shutil.rmtree(self.scratch)

    def _write_gate(self, value):
        path = self.temporary / "resource-gate.json"
        value["gate_id"] = self.temporary.name
        payload = canonical_json(value).encode() + b"\n"
        path.write_bytes(payload)
        path.chmod(0o600)
        return path, payload

    def test_resource_gate_exact_round_trip_and_budget_tamper(self):
        value = _gate_value()
        path, payload = self._write_gate(value)
        verified = production.verify_resource_gate(path, "a" * 40)
        self.assertEqual(verified.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(verified.value, value)

        value["projected_new_bytes"] -= 1
        self._write_gate(value)
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "frozen contract"
        ):
            production.verify_resource_gate(path, "a" * 40)

    def test_resource_gate_rejects_nonfixed_namespace_and_runtime_env_drift(self):
        value = _gate_value()
        path, unused_payload = self._write_gate(value)
        outside = TEST_TMP / "resource-gate.json"
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "fixed namespace"
        ):
            production.verify_resource_gate(outside, "a" * 40)
        environment = production._runtime_environment()
        with mock.patch.dict("os.environ", environment, clear=False):
            production._runtime_environment_gate()
            with mock.patch.dict("os.environ", {"OMP_NUM_THREADS": "9"}):
                with self.assertRaisesRegex(
                    production.ProductionTrainingError, "runtime environment"
                ):
                    production._runtime_environment_gate()

    def test_training_attempt_requires_distinct_fresh_resource_gate(self):
        value = _gate_value()
        value["observed_at_utc"] = production._utc_now()
        path, unused_payload = self._write_gate(value)
        older = production.RESOURCE_ROOT / (
            "production-training-older-" + secrets.token_hex(8)
        )
        older.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, older)
        older_value = _gate_value()
        older_value["observed_at_utc"] = value["observed_at_utc"]
        older_value["gate_id"] = older.name
        older_path = older / "resource-gate.json"
        older_path.write_bytes(canonical_json(older_value).encode() + b"\n")
        older_path.chmod(0o600)
        verified = production._fresh_attempt_gate(
            path, "a" * 40, older_path, self.temporary.name
        )
        self.assertEqual(verified.path, path)
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "fresh resource gate"
        ):
            production._fresh_attempt_gate(
                path, "a" * 40, path, self.temporary.name
            )
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "fresh resource gate"
        ):
            production._fresh_attempt_gate(
                path, "a" * 40, older_path, "another-attempt-run"
            )
        with mock.patch.object(production.time, "time", return_value=10**12):
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "stale"
            ):
                production._fresh_attempt_gate(
                    path, "a" * 40, older_path, self.temporary.name
                )

    def test_copied_gate_bytes_under_new_slug_are_rejected(self):
        value = _gate_value()
        path, payload = self._write_gate(value)
        clone = production.RESOURCE_ROOT / (
            "production-training-clone-" + secrets.token_hex(8)
        )
        clone.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, clone)
        clone_path = clone / "resource-gate.json"
        clone_path.write_bytes(payload)
        clone_path.chmod(0o600)
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "frozen contract"
        ):
            production.verify_resource_gate(clone_path, "a" * 40)

    def test_trace_is_exact_complete_and_finite(self):
        rows = []
        for step in range(1, 32):
            rows.append(
                {
                    "schema_version": production.TRACE_SCHEMA,
                    "optimizer_step": step,
                    "samples_seen": step * 32,
                    "completed_epochs": min(min(step * 32, 990) // 330, 3),
                    "loss": float(step),
                    "gradient_norm": 1.0,
                    "learning_rates": [2e-5, 2e-4],
                }
            )
        payload = b"".join(
            canonical_json(value).encode() + b"\n" for value in rows
        )
        self.assertEqual(len(production._verify_trace(payload)), 31)
        rows[-1]["samples_seen"] = 991
        tampered = b"".join(
            canonical_json(value).encode() + b"\n" for value in rows
        )
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "trace row"
        ):
            production._verify_trace(tampered)

    @staticmethod
    def _rows(count):
        return [
            {
                "schema_version": production.TRACE_SCHEMA,
                "optimizer_step": step,
                "samples_seen": step * 32,
                "completed_epochs": min(min(step * 32, 990) // 330, 3),
                "loss": float(step),
                "gradient_norm": 1.0,
                "learning_rates": [2e-5, 2e-4],
            }
            for step in range(1, count + 1)
        ]

    def test_trace_receipt_binds_checkpoint_and_prefix(self):
        run_root = self.scratch / "runs"
        run_root.mkdir(mode=0o700)
        target = run_root / "run-id"
        target.mkdir(mode=0o700)
        (target / production.TRACE_PREFIX_DIR_NAME).mkdir(mode=0o700)
        checkpoint = SimpleNamespace(
            checkpoint_id=production._checkpoint_id(5),
            progress=SimpleNamespace(optimizer_steps_completed=5),
            manifest_sha256="4" * 64,
        )
        with mock.patch.object(production, "RUN_ROOT", run_root):
            production._publish_trace_receipt(
                target, "run-id", checkpoint, self._rows(5)
            )
            rows, digest = production._verify_trace_receipt("run-id", checkpoint)
            self.assertEqual(len(rows), 5)
            self.assertEqual(len(digest), 64)
            path = target / production.TRACE_PREFIX_DIR_NAME / "step-000005.json"
            value = json.loads(path.read_text())
            value["checkpoint_manifest_sha256"] = "5" * 64
            path.write_text(canonical_json(value) + "\n")
            path.chmod(0o600)
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "receipt binding"
            ):
                production._verify_trace_receipt("run-id", checkpoint)

    def test_final_trace_must_equal_every_checkpoint_prefix(self):
        rows = tuple(self._rows(31))
        located = tuple(
            production.LocatedCheckpoint(
                "run-id",
                SimpleNamespace(
                    progress=SimpleNamespace(optimizer_steps_completed=step)
                ),
                rows[:step],
                hashlib.sha256(production._trace_payload(rows[:step])).hexdigest(),
            )
            for step in production.CHECKPOINT_STEPS
        )
        production._crosscheck_trace_receipts(rows, located)
        changed = list(rows)
        changed[0] = {**changed[0], "loss": 999.0}
        with self.assertRaisesRegex(
            production.ProductionTrainingError, "diverges"
        ):
            production._crosscheck_trace_receipts(tuple(changed), located)

    def test_run_input_manifest_last_replay_tamper_and_no_replace(self):
        run_input_root = self.scratch / "run-inputs"
        gate_path, unused_payload = self._write_gate(_gate_value())
        gate = production.VerifiedResourceGate(gate_path, "9" * 64, _gate_value())
        value = {
            "artifact_id": "test-run-input",
            "execution_commit": "a" * 40,
            "resource_gate": {"path": str(gate_path)},
            "frozen_method": production._frozen_execution_configuration(),
        }
        with (
            mock.patch.object(production, "RUN_INPUT_ROOT", run_input_root),
            mock.patch.object(
                production, "_run_input_value", return_value=(value, tuple())
            ),
            mock.patch.object(production, "verify_resource_gate", return_value=gate),
            mock.patch.object(production.artifact_io, "_git_gate"),
        ):
            verified, records = production._publish_run_input("a" * 40, gate)
            self.assertEqual(records, tuple())
            self.assertEqual(verified.artifact_id, "test-run-input")
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "already exists"
            ):
                production._publish_run_input("a" * 40, gate)
            input_path = verified.artifact_path / production.RUN_INPUT_NAME
            input_path.write_text(canonical_json({**value, "tampered": True}) + "\n")
            input_path.chmod(0o600)
            with self.assertRaises(production.ProductionTrainingError):
                production.verify_run_input("test-run-input", "a" * 40)

    def test_frozen_method_configuration_is_complete(self):
        value = production._frozen_execution_configuration()
        execution = value["execution_config"]
        self.assertEqual(execution["optimizer"]["lora_learning_rate"], 2e-5)
        self.assertEqual(execution["optimizer"]["temporal_head_learning_rate"], 2e-4)
        self.assertEqual(execution["optimizer"]["betas"], [0.9, 0.999])
        self.assertEqual(execution["scheduler"]["warmup_ratio"], 0.05)
        self.assertEqual(execution["gradient_clip_norm"], 1.0)
        self.assertEqual(value["core"]["hidden_size"], 3584)
        self.assertFalse(value["loss"]["counterfactual_answer_loss"])
        self.assertTrue(value["deterministic_algorithms"])

    def test_recursive_ancestry_locks_two_resume_layers_and_source_config(self):
        commit = "a" * 40
        plan_id = "plan-id"
        plan = SimpleNamespace()

        def base_config(run_id, resume):
            return {
                "execution_commit": commit,
                "training_plan": {"plan_id": plan_id, "semantic_sha256": "1" * 64},
                "run_input": {"artifact_id": "input", "manifest_sha256": "2" * 64},
                "resource_gate": {"path": f"/gate/{run_id}", "sha256": "3" * 64},
                "resume": resume,
            }

        configs = {"run-a": base_config("run-a", None)}
        payloads = {"run-a": canonical_json(configs["run-a"]).encode() + b"\n"}

        def load(run_id):
            return payloads[run_id], configs[run_id]

        def located(run_id, step, unused_commit, unused_plan_id, unused_plan, visited=()):
            return production.LocatedCheckpoint(
                run_id,
                SimpleNamespace(manifest_sha256=hashlib.sha256(
                    f"{run_id}:{step}".encode()
                ).hexdigest()),
                tuple(),
                hashlib.sha256(f"trace:{run_id}:{step}".encode()).hexdigest(),
            )

        with (
            mock.patch.object(production, "_run_config_value", side_effect=load),
            mock.patch.object(production, "_resolve_checkpoint", side_effect=located),
            mock.patch.object(
                production,
                "verify_resource_gate",
                side_effect=lambda path, unused_commit: production.VerifiedResourceGate(
                    path, "3" * 64, {}
                ),
            ),
        ):
            ancestry_a = production._checkpoint_ancestry_sha256(
                "run-a", 5, commit, plan_id, plan
            )
            resume_b = {
                "source_run_id": "run-a",
                "checkpoint_id": "step-000005",
                "source_run_config_sha256": hashlib.sha256(payloads["run-a"]).hexdigest(),
                "checkpoint_manifest_sha256": hashlib.sha256(b"run-a:5").hexdigest(),
                "trace_prefix_sha256": hashlib.sha256(b"trace:run-a:5").hexdigest(),
                "ancestry_sha256": ancestry_a,
            }
            configs["run-b"] = base_config("run-b", resume_b)
            payloads["run-b"] = canonical_json(configs["run-b"]).encode() + b"\n"
            ancestry_b = production._checkpoint_ancestry_sha256(
                "run-b", 10, commit, plan_id, plan
            )
            resume_c = {
                "source_run_id": "run-b",
                "checkpoint_id": "step-000010",
                "source_run_config_sha256": hashlib.sha256(payloads["run-b"]).hexdigest(),
                "checkpoint_manifest_sha256": hashlib.sha256(b"run-b:10").hexdigest(),
                "trace_prefix_sha256": hashlib.sha256(b"trace:run-b:10").hexdigest(),
                "ancestry_sha256": ancestry_b,
            }
            configs["run-c"] = base_config("run-c", resume_c)
            payloads["run-c"] = canonical_json(configs["run-c"]).encode() + b"\n"
            self.assertEqual(
                len(production._checkpoint_ancestry_sha256(
                    "run-c", 15, commit, plan_id, plan
                )),
                64,
            )
            payloads["run-a"] = b"tampered-source-config\n"
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "source config"
            ):
                production._checkpoint_ancestry_sha256(
                    "run-c", 15, commit, plan_id, plan
                )

    def test_resume_training_uses_new_namespace_and_explicit_checkpoint(self):
        run_root = self.scratch / "runs"
        run_root.mkdir(mode=0o700)
        source = run_root / "source-run"
        source.mkdir(mode=0o700)
        for name in (production.CHECKPOINT_DIR_NAME, production.TRACE_PREFIX_DIR_NAME):
            (source / name).mkdir(mode=0o700)
        (source / production.RUN_CONFIG_NAME).write_text("{}\n")
        (source / production.RUN_CONFIG_NAME).chmod(0o600)
        commit = "a" * 40
        plan_id = "plan-id"

        def progress(step):
            return production.TrainingProgress(
                epoch=min(min(step * 32, 990) // 330, 3),
                next_micro_batch_index=step * 32,
                optimizer_steps_completed=step,
                samples_seen=step * 32,
            )

        plan = SimpleNamespace(
            total_optimizer_steps=31,
            execution_config=SimpleNamespace(),
            progress=progress,
        )
        input_gate_path = self.temporary / "resource-gate.json"
        attempt_gate_path = self.temporary / "attempt-resource-gate.json"
        run_input = production.VerifiedRunInput(
            "input-id", self.scratch, commit, input_gate_path, "1" * 64, "2" * 64
        )
        gate = production.VerifiedResourceGate(
            attempt_gate_path,
            "3" * 64,
            {"selected_gpu": {"uuid": "GPU-test"}},
        )
        old_gate = production.VerifiedResourceGate(
            self.temporary / "old-resource-gate.json",
            "4" * 64,
            {},
        )
        plan_artifact = SimpleNamespace(
            manifest_sha256="5" * 64, plan_semantic_sha256="6" * 64
        )
        source_config = {
            "execution_commit": commit,
            "training_plan": {
                "plan_id": plan_id,
                "manifest_sha256": "5" * 64,
                "semantic_sha256": "6" * 64,
            },
            "run_input": {"artifact_id": "input-id", "manifest_sha256": "2" * 64},
            "resource_gate": {"path": str(old_gate.path), "sha256": old_gate.sha256},
            "resume": None,
        }
        source_payload = canonical_json(source_config).encode() + b"\n"
        located = production.LocatedCheckpoint(
            "source-run",
            SimpleNamespace(
                checkpoint_id="step-000030",
                manifest_sha256="7" * 64,
                artifact_path=self.scratch / "source-checkpoints/step-000030",
                progress=progress(30),
            ),
            tuple(self._rows(30)),
            "8" * 64,
        )
        final_checkpoint = SimpleNamespace(
            checkpoint_id="step-000031", progress=progress(31), manifest_sha256="9" * 64
        )
        optimizer = SimpleNamespace(param_groups=[{"lr": 2e-5}, {"lr": 2e-4}])
        step_result = SimpleNamespace(
            progress=progress(31), optimizer_losses=(1.0,), gradient_norms=(2.0,)
        )
        patches = (
            mock.patch.object(production, "RUN_ROOT", run_root),
            mock.patch.object(production, "_load_plan_and_records", return_value=(plan, run_input, tuple())),
            mock.patch.object(production, "_fresh_attempt_gate", return_value=gate),
            mock.patch.object(production, "_runtime_environment_gate"),
            mock.patch.object(production.artifact_io, "_git_gate"),
            mock.patch.object(production, "_run_config_value", return_value=(source_payload, source_config)),
            mock.patch.object(production.training_plan_artifacts, "verify_training_plan", return_value=plan_artifact),
            mock.patch.object(production, "verify_resource_gate", return_value=old_gate),
            mock.patch.object(production, "_resolve_checkpoint", return_value=located),
            mock.patch.object(production, "_checkpoint_ancestry_sha256", return_value="a" * 64),
            mock.patch.object(production, "_initialize_adapter", return_value=(object(), object(), object())),
            mock.patch.object(production, "build_optimizer", return_value=optimizer),
            mock.patch.object(production, "build_scheduler", return_value=object()),
            mock.patch.object(production, "_checkpoint_binding", return_value=object()),
            mock.patch.object(production, "resume_training_checkpoint", return_value=progress(30)),
            mock.patch.object(production, "_records_by_id", return_value={}),
            mock.patch.object(production, "_materialized_window", return_value=object()),
            mock.patch.object(production, "execute_planned_training_steps", return_value=step_result),
            mock.patch.object(production, "save_training_checkpoint", return_value=final_checkpoint),
            mock.patch.object(production, "_publish_trace_receipt"),
            mock.patch.object(production.torch.cuda, "max_memory_allocated", return_value=1),
            mock.patch.object(production.torch.cuda, "max_memory_reserved", return_value=2),
        )
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            result = production.resume_training(
                commit,
                plan_id,
                "source-run",
                "step-000030",
                "resume-run",
                attempt_gate_path,
            )
        self.assertEqual(result["optimizer_steps_completed"], 31)
        self.assertTrue((run_root / "resume-run" / production.TRACE_NAME).is_file())
        config = json.loads(
            (run_root / "resume-run" / production.RUN_CONFIG_NAME).read_text()
        )
        self.assertEqual(config["resume"]["source_run_id"], "source-run")
        self.assertEqual(config["resource_gate"]["sha256"], gate.sha256)
        self.assertEqual(
            {entry.name for entry in source.iterdir()},
            {production.RUN_CONFIG_NAME, production.CHECKPOINT_DIR_NAME, production.TRACE_PREFIX_DIR_NAME},
        )

    def test_precheckpoint_failure_can_retry_from_zero_in_new_attempt_namespace(self):
        run_root = self.scratch / "runs"
        run_input = production.VerifiedRunInput(
            "input-id", self.scratch, "a" * 40, Path("/input-gate"),
            "1" * 64, "2" * 64,
        )
        gate = production.VerifiedResourceGate(
            Path("/attempt-gate"), "3" * 64,
            {"selected_gpu": {"uuid": "GPU-test"}},
        )
        plan_artifact = SimpleNamespace(
            manifest_sha256="4" * 64, plan_semantic_sha256="5" * 64
        )
        patches = (
            mock.patch.object(production, "RUN_ROOT", run_root),
            mock.patch.object(production, "_load_plan_and_records", return_value=(SimpleNamespace(), run_input, tuple())),
            mock.patch.object(production, "_fresh_attempt_gate", return_value=gate),
            mock.patch.object(production, "_runtime_environment_gate"),
            mock.patch.object(production.artifact_io, "_git_gate"),
            mock.patch.object(production.training_plan_artifacts, "verify_training_plan", return_value=plan_artifact),
            mock.patch.object(production, "_initialize_adapter", side_effect=RuntimeError("load failed")),
        )
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            for run_id in ("attempt-one", "attempt-two"):
                with self.assertRaisesRegex(RuntimeError, "load failed"):
                    production.train(
                        "a" * 40, "plan-id", run_id, Path("/attempt-gate")
                    )
        self.assertEqual(
            {entry.name for entry in run_root.iterdir()},
            {"attempt-one", "attempt-two"},
        )
        for run_id in ("attempt-one", "attempt-two"):
            self.assertEqual(
                {entry.name for entry in (run_root / run_id).iterdir()},
                {production.RUN_CONFIG_NAME, production.TRACE_PREFIX_DIR_NAME},
            )

    def test_recursive_ancestry_rejects_cycle(self):
        payload = b"cycle-config\n"
        config = {
            "execution_commit": "a" * 40,
            "training_plan": {"plan_id": "plan-id"},
            "run_input": {},
            "resource_gate": {"path": "/gate", "sha256": "1" * 64},
            "resume": {
                "source_run_id": "cycle-run",
                "checkpoint_id": "step-000005",
                "source_run_config_sha256": hashlib.sha256(payload).hexdigest(),
                "checkpoint_manifest_sha256": "2" * 64,
                "trace_prefix_sha256": "3" * 64,
                "ancestry_sha256": "4" * 64,
            },
        }
        located = production.LocatedCheckpoint(
            "cycle-run",
            SimpleNamespace(manifest_sha256="2" * 64),
            tuple(),
            "3" * 64,
        )
        with (
            mock.patch.object(production, "_run_config_value", return_value=(payload, config)),
            mock.patch.object(production, "_resolve_checkpoint", return_value=located),
            mock.patch.object(
                production,
                "verify_resource_gate",
                return_value=production.VerifiedResourceGate(Path("/gate"), "1" * 64, {}),
            ),
        ):
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "cyclic"
            ):
                production._checkpoint_ancestry_sha256(
                    "cycle-run", 10, "a" * 40, "plan-id", SimpleNamespace()
                )

    def test_failure_artifact_is_bounded_manifest_last_and_no_replace(self):
        failure_root = self.scratch / "failures"
        run_root = self.scratch / "failure-runs"
        run = run_root / "run-id"
        run.mkdir(mode=0o700, parents=True)
        run_config = run / production.RUN_CONFIG_NAME
        run_config.write_text("{}\n")
        run_config.chmod(0o600)
        gate_path, unused_payload = self._write_gate(_gate_value())
        with (
            mock.patch.object(production, "FAILURE_ROOT", failure_root),
            mock.patch.object(production, "RUN_ROOT", run_root),
            mock.patch.object(production.artifact_io, "_git_gate"),
        ):
            value = production.publish_failure(
                "failure-one",
                "a" * 40,
                "train",
                "run-id",
                RuntimeError("boom"),
                gate_path,
            )
            self.assertEqual(value["status"], "TRAINING_FAILED_DEVELOPMENT_ONLY")
            self.assertEqual(value["attempt_resource_gate"]["path"], str(gate_path))
            self.assertEqual(
                value["run_config_sha256"], hashlib.sha256(b"{}\n").hexdigest()
            )
            self.assertTrue((failure_root / "failure-one" / "manifest.json").is_file())
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "already exists"
            ):
                production.publish_failure(
                    "failure-one",
                    "a" * 40,
                    "train",
                    "run-id",
                    RuntimeError("again"),
                )
            run_config.write_text('{"tampered":true}\n')
            run_config.chmod(0o600)
            with self.assertRaisesRegex(
                production.ProductionTrainingError, "run-config binding"
            ):
                production.verify_failure("failure-one")

    def test_run_manifest_binds_every_checkpoint_and_final_cursor(self):
        checkpoints = tuple(
            production.LocatedCheckpoint(
                "run-id",
                SimpleNamespace(
                    checkpoint_id=production._checkpoint_id(step),
                    progress=SimpleNamespace(optimizer_steps_completed=step),
                    config_sha256=f"{step:064x}",
                    state_sha256=f"{step + 1:064x}",
                    manifest_sha256=f"{step + 2:064x}",
                ),
                tuple(),
                f"{step + 3:064x}",
            )
            for step in production.CHECKPOINT_STEPS
        )
        run_input = production.VerifiedRunInput(
            "input-id",
            self.temporary,
            "a" * 40,
            self.temporary / "gate.json",
            "b" * 64,
            "c" * 64,
        )
        value = production._run_manifest(
            "run-id",
            "a" * 40,
            "plan-id",
            run_input,
            canonical_json(
                {"resource_gate": {"path": "/gate", "sha256": "e" * 64}}
            ).encode()
            + b"\n",
            b"trace\n",
            b"post\n",
            checkpoints,
            "d" * 64,
        )
        self.assertEqual(value["final_checkpoint_id"], "step-000031")
        self.assertEqual(value["optimizer_steps_completed"], 31)
        self.assertEqual(value["samples_seen"], 992)
        self.assertEqual(
            [row["optimizer_steps_completed"] for row in value["checkpoints"]],
            list(production.CHECKPOINT_STEPS),
        )
        self.assertTrue(
            all(row["artifact_run_id"] == "run-id" for row in value["checkpoints"])
        )


if __name__ == "__main__":
    unittest.main()
