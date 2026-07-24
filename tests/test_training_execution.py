import copy
from dataclasses import replace
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch import nn
from transformers import Qwen2Config, Qwen2ForCausalLM

from kairos.modeling import IGNORE_RELATION_INDEX, KairosConfig, KairosModel, PairMlpBaseline
from kairos.training_adapter import (
    LoraSpec,
    QwenCoreTrainingAdapter,
    TrainingBatch,
    inject_qwen_lora,
    trainable_state_dict,
)
from kairos import training_execution


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")
COMMIT = "a" * 40
MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
MODEL_SHA256SUMS_SHA256 = (
    "3ee6c9510b7e50bfcd46d6df33cafa3e2019f13a6a09bf1d2f9e80cdfe1164e8"
)


class SyntheticEncoder(nn.Module):
    def __init__(self, hidden_size=8):
        super().__init__()
        self.embedding = nn.Embedding(96, hidden_size)
        self.embedding.weight.requires_grad_(False)
        self.lora_A = nn.Parameter(torch.empty(hidden_size, 3))
        self.lora_B = nn.Parameter(torch.empty(3, hidden_size))
        self.dropout = nn.Dropout(0.2)
        nn.init.normal_(self.lora_A, mean=0.0, std=0.05)
        nn.init.normal_(self.lora_B, mean=0.0, std=0.05)

    def forward(self, input_ids, attention_mask, **kwargs):
        hidden = self.embedding(input_ids)
        update = torch.matmul(torch.matmul(hidden, self.lora_A), self.lora_B)
        return SimpleNamespace(last_hidden_state=hidden + self.dropout(update))


class SyntheticBackbone(nn.Module):
    def __init__(self, hidden_size=8):
        super().__init__()
        self.config = SimpleNamespace(hidden_size=hidden_size)
        self.model = SyntheticEncoder(hidden_size)


def _batch(offset=0):
    input_ids = torch.tensor(
        [[1 + offset, 2 + offset, 3 + offset, 0], [4 + offset, 5 + offset, 6 + offset, 7 + offset]]
    )
    attention = torch.tensor([[1, 1, 1, 0], [1, 1, 1, 1]])
    event_tokens = torch.tensor(
        [
            [[True, False, False, False], [False, True, False, False]],
            [[True, False, False, False], [False, False, True, False]],
        ]
    )
    event_mask = torch.ones(2, 2, dtype=torch.bool)
    candidate_ids = torch.tensor(
        [
            [[20 + offset, 21 + offset, 0], [22 + offset, 23 + offset, 0], [0, 0, 0]],
            [[24 + offset, 25 + offset, 0], [0, 0, 0], [0, 0, 0]],
        ]
    )
    candidate_attention = torch.tensor(
        [
            [[1, 1, 0], [1, 1, 0], [0, 0, 0]],
            [[1, 1, 0], [0, 0, 0], [0, 0, 0]],
        ]
    )
    candidate_tokens = torch.tensor(
        [
            [[False, True, False], [False, True, False], [False, False, False]],
            [[False, True, False], [False, False, False], [False, False, False]],
        ]
    )
    candidate_mask = torch.tensor([[True, True, False], [True, False, False]])
    relation_targets = torch.full((2, 2, 2), IGNORE_RELATION_INDEX, dtype=torch.long)
    relation_targets[:, 0, 1] = 0
    counterfactual_targets = torch.full(
        (2, 2, 2), IGNORE_RELATION_INDEX, dtype=torch.long
    )
    counterfactual_targets[:, 0, 1] = 1
    return TrainingBatch(
        input_ids=input_ids,
        attention_mask=attention,
        event_token_mask=event_tokens,
        event_mask=event_mask,
        candidate_input_ids=candidate_ids,
        candidate_attention_mask=candidate_attention,
        candidate_token_mask=candidate_tokens,
        candidate_mask=candidate_mask,
        answer_targets=torch.tensor([1, 0]),
        relation_targets=relation_targets,
        counterfactual_input_ids=input_ids.clone(),
        counterfactual_attention_mask=attention.clone(),
        counterfactual_event_token_mask=event_tokens.clone(),
        counterfactual_event_mask=event_mask.clone(),
        counterfactual_relation_targets=counterfactual_targets,
    )


def _batches(count=32):
    return tuple(_batch(index % 5) for index in range(count))


def _config(seed=13, **changes):
    values = {
        "seed": seed,
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 16,
        "total_optimizer_steps": 20,
    }
    values.update(changes)
    return training_execution.TrainingExecutionConfig(**values)


def _binding(core_type=KairosModel, **changes):
    core_name = "pair-mlp" if core_type is PairMlpBaseline else "kairos"
    values = {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_sha256sums_sha256": MODEL_SHA256SUMS_SHA256,
        "dataset_id": "synthetic",
        "dataset_revision": "b" * 40,
        "split": "train",
        "data_artifact_id": "DEV-SYNTHETIC-TRAINING",
        "data_manifest_sha256": "c" * 64,
        "core_type": core_name,
    }
    values.update(changes)
    return training_execution.TrainingArtifactBinding(**values)


def _bundle(seed=13, core_type=KairosModel):
    generator = torch.Generator(device="cpu")
    training_execution.seed_training(seed, generator)
    config = _config(seed)
    core = core_type(KairosConfig(hidden_size=8, shared_size=4, pair_mlp_hidden_size=6))
    adapter = QwenCoreTrainingAdapter(SyntheticBackbone(), core)
    optimizer = training_execution.build_optimizer(adapter, config)
    scheduler = training_execution.build_scheduler(optimizer, config)
    return config, adapter, optimizer, scheduler, generator


def _peft_bundle(seed=13):
    generator = torch.Generator(device="cpu")
    training_execution.seed_training(seed, generator)
    config = _config(seed)
    backbone = Qwen2ForCausalLM(
        Qwen2Config(
            vocab_size=96,
            hidden_size=8,
            intermediate_size=16,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=32,
        )
    )
    injected = inject_qwen_lora(backbone, LoraSpec())
    core = KairosModel(KairosConfig(hidden_size=8, shared_size=4))
    adapter = QwenCoreTrainingAdapter(injected, core)
    optimizer = training_execution.build_optimizer(adapter, config)
    scheduler = training_execution.build_scheduler(optimizer, config)
    return config, adapter, optimizer, scheduler, generator


class TrainingExecutionFixture(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-training-execution-test-", dir=TEST_TMP
        )
        self.root = Path(self.temporary.name) / "checkpoints"

    def tearDown(self):
        self.temporary.cleanup()

    def assert_nested_equal(self, left, right):
        if isinstance(left, torch.Tensor):
            self.assertIsInstance(right, torch.Tensor)
            self.assertTrue(torch.equal(left, right))
            return
        if isinstance(left, dict):
            self.assertEqual(set(left), set(right))
            for key in left:
                self.assert_nested_equal(left[key], right[key])
            return
        if isinstance(left, (list, tuple)):
            self.assertEqual(len(left), len(right))
            for left_item, right_item in zip(left, right):
                self.assert_nested_equal(left_item, right_item)
            return
        self.assertEqual(left, right)


class FrozenConfigAndOptimizerTests(TrainingExecutionFixture):
    def test_frozen_effective_batch_and_optimizer_groups(self):
        config, adapter, optimizer, scheduler, unused = _bundle()
        self.assertEqual(config.effective_batch_size, 32)
        self.assertEqual(config.warmup_steps, 1)
        self.assertEqual(
            [group["group_name"] for group in optimizer.param_groups],
            ["lora", "temporal_heads"],
        )
        self.assertEqual(
            [group["initial_lr"] for group in optimizer.param_groups],
            [2e-5, 2e-4],
        )
        self.assertEqual(scheduler.last_epoch, 0)
        lora_ids = {id(adapter.backbone.model.lora_A), id(adapter.backbone.model.lora_B)}
        self.assertEqual(
            {id(parameter) for parameter in optimizer.param_groups[0]["params"]},
            lora_ids,
        )
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "effective batch"
        ):
            _config(gradient_accumulation_steps=8)
        with self.assertRaisesRegex(training_execution.TrainingExecutionError, "seed"):
            _config(seed=7)

    def test_non_lora_trainable_backbone_parameter_fails_closed(self):
        config, adapter, unused_optimizer, unused_scheduler, unused_generator = _bundle()
        adapter.backbone.model.embedding.weight.requires_grad_(True)
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "not LoRA"
        ):
            training_execution.build_optimizer(adapter, config)


class CheckpointTests(TrainingExecutionFixture):
    def test_checkpoint_is_private_manifest_last_bound_and_no_replace(self):
        config, adapter, optimizer, scheduler, generator = _bundle()
        binding = _binding()
        progress = training_execution.TrainingProgress.initial()
        verified = training_execution.save_training_checkpoint(
            self.root,
            "synthetic-step-000000",
            COMMIT,
            config,
            binding,
            adapter,
            optimizer,
            scheduler,
            progress,
            generator,
        )
        self.assertEqual(verified.progress, progress)
        self.assertEqual(verified.artifact_binding, binding)
        self.assertEqual(
            {entry.name for entry in verified.artifact_path.iterdir()},
            {"config.json", "state.pt", "manifest.json"},
        )
        self.assertEqual(os.stat(verified.artifact_path).st_mode & 0o777, 0o700)
        for name in ("config.json", "state.pt", "manifest.json"):
            self.assertEqual(
                os.stat(verified.artifact_path / name).st_mode & 0o777,
                0o600,
            )
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "already exists"
        ):
            training_execution.save_training_checkpoint(
                self.root,
                "synthetic-step-000000",
                COMMIT,
                config,
                binding,
                adapter,
                optimizer,
                scheduler,
                progress,
                generator,
            )

    def test_hash_tamper_and_namespace_extra_are_rejected(self):
        config, adapter, optimizer, scheduler, generator = _bundle()
        verified = training_execution.save_training_checkpoint(
            self.root,
            "synthetic-step-000001",
            COMMIT,
            config,
            _binding(),
            adapter,
            optimizer,
            scheduler,
            training_execution.TrainingProgress.initial(),
            generator,
        )
        state_path = verified.artifact_path / "state.pt"
        state_path.write_bytes(state_path.read_bytes() + b"tamper")
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "state binding"
        ):
            training_execution.verify_training_checkpoint(
                self.root, "synthetic-step-000001"
            )

        config, adapter, optimizer, scheduler, generator = _bundle()
        verified = training_execution.save_training_checkpoint(
            self.root,
            "synthetic-step-000002",
            COMMIT,
            config,
            _binding(),
            adapter,
            optimizer,
            scheduler,
            training_execution.TrainingProgress.initial(),
            generator,
        )
        (verified.artifact_path / "extra").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "namespace"
        ):
            training_execution.verify_training_checkpoint(
                self.root, "synthetic-step-000002"
            )

    def test_wrong_model_resume_does_not_mutate_live_state(self):
        config, adapter, optimizer, scheduler, generator = _bundle()
        binding = _binding()
        training_execution.save_training_checkpoint(
            self.root,
            "synthetic-step-000003",
            COMMIT,
            config,
            binding,
            adapter,
            optimizer,
            scheduler,
            training_execution.TrainingProgress.initial(),
            generator,
        )
        other_config, other_adapter, other_optimizer, other_scheduler, other_generator = _bundle(
            core_type=PairMlpBaseline
        )
        before = trainable_state_dict(other_adapter)
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "core type"
        ):
            training_execution.resume_training_checkpoint(
                self.root,
                "synthetic-step-000003",
                COMMIT,
                binding,
                other_config,
                other_adapter,
                other_optimizer,
                other_scheduler,
                other_generator,
            )
        self.assert_nested_equal(before, trainable_state_dict(other_adapter))

    def test_binding_mismatch_and_config_tamper_fail_closed(self):
        config, adapter, optimizer, scheduler, generator = _bundle()
        binding = _binding()
        verified = training_execution.save_training_checkpoint(
            self.root,
            "synthetic-step-000004",
            COMMIT,
            config,
            binding,
            adapter,
            optimizer,
            scheduler,
            training_execution.TrainingProgress.initial(),
            generator,
        )
        before_model = trainable_state_dict(adapter)
        before_optimizer = copy.deepcopy(optimizer.state_dict())
        before_scheduler = copy.deepcopy(scheduler.state_dict())
        before_loader = generator.get_state().clone()
        original_read = training_execution._read_file
        read_names = []

        def recording_read(path, limit, name):
            read_names.append(name)
            return original_read(path, limit, name)

        with patch.object(training_execution, "_read_file", side_effect=recording_read):
            with self.assertRaisesRegex(
                training_execution.TrainingExecutionError, "binding differs"
            ):
                training_execution.resume_training_checkpoint(
                    self.root,
                    "synthetic-step-000004",
                    COMMIT,
                    replace(binding, data_manifest_sha256="d" * 64),
                    config,
                    adapter,
                    optimizer,
                    scheduler,
                    generator,
                )
        self.assertNotIn("state.pt", read_names)
        self.assert_nested_equal(before_model, trainable_state_dict(adapter))
        self.assert_nested_equal(before_optimizer, optimizer.state_dict())
        self.assert_nested_equal(before_scheduler, scheduler.state_dict())
        self.assertTrue(torch.equal(before_loader, generator.get_state()))

        config_path = verified.artifact_path / "config.json"
        config_path.write_bytes(
            config_path.read_bytes().replace(b'"synthetic"', b'"tamperedx"')
        )
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "artifact bindings differ"
        ):
            training_execution.verify_training_checkpoint(
                self.root, "synthetic-step-000004"
            )

    def test_core_binding_is_checked_before_checkpoint_publication(self):
        config, adapter, optimizer, scheduler, generator = _bundle()
        with self.assertRaisesRegex(
            training_execution.TrainingExecutionError, "core type"
        ):
            training_execution.save_training_checkpoint(
                self.root,
                "synthetic-step-000005",
                COMMIT,
                config,
                _binding(PairMlpBaseline),
                adapter,
                optimizer,
                scheduler,
                training_execution.TrainingProgress.initial(),
                generator,
            )
        self.assertFalse(self.root.exists())

    def test_real_peft_state_round_trips_through_checkpoint_resume(self):
        config, adapter, optimizer, scheduler, generator = _peft_bundle()
        first = training_execution.run_optimizer_steps(
            adapter,
            _batches(16),
            optimizer,
            scheduler,
            config,
            training_execution.TrainingProgress.initial(),
            1,
        )
        expected_model = trainable_state_dict(adapter)
        expected_optimizer = copy.deepcopy(optimizer.state_dict())
        training_execution.save_training_checkpoint(
            self.root,
            "peft-kairos-step-000001",
            COMMIT,
            config,
            _binding(),
            adapter,
            optimizer,
            scheduler,
            first.progress,
            generator,
        )

        resumed = _peft_bundle()
        (
            resumed_config,
            resumed_adapter,
            resumed_optimizer,
            resumed_scheduler,
            resumed_generator,
        ) = resumed
        progress = training_execution.resume_training_checkpoint(
            self.root,
            "peft-kairos-step-000001",
            COMMIT,
            _binding(),
            resumed_config,
            resumed_adapter,
            resumed_optimizer,
            resumed_scheduler,
            resumed_generator,
        )
        self.assertEqual(progress, first.progress)
        self.assert_nested_equal(
            expected_model, trainable_state_dict(resumed_adapter)
        )
        self.assert_nested_equal(expected_optimizer, resumed_optimizer.state_dict())


class InterruptedResumeEquivalenceTests(TrainingExecutionFixture):
    def test_cpu_bf16_interrupted_resume_matches_uninterrupted_exactly(self):
        batches = _batches()
        for core_type, checkpoint_id in (
            (KairosModel, "synthetic-kairos-interrupted-step-000001"),
            (PairMlpBaseline, "synthetic-pair-mlp-interrupted-step-000001"),
        ):
            with self.subTest(core_type=core_type.__name__):
                config, adapter, optimizer, scheduler, generator = _bundle(
                    core_type=core_type
                )
                binding = _binding(core_type)
                full = training_execution.run_optimizer_steps(
                    adapter,
                    batches,
                    optimizer,
                    scheduler,
                    config,
                    training_execution.TrainingProgress.initial(),
                    2,
                )
                full_model = trainable_state_dict(adapter)
                full_optimizer = copy.deepcopy(optimizer.state_dict())
                full_scheduler = copy.deepcopy(scheduler.state_dict())
                full_python_draw = random.random()
                full_torch_draw = torch.rand(4)
                full_loader_draw = torch.rand(4, generator=generator)

                config, adapter, optimizer, scheduler, generator = _bundle(
                    core_type=core_type
                )
                first = training_execution.run_optimizer_steps(
                    adapter,
                    batches,
                    optimizer,
                    scheduler,
                    config,
                    training_execution.TrainingProgress.initial(),
                    1,
                )
                verified = training_execution.save_training_checkpoint(
                    self.root,
                    checkpoint_id,
                    COMMIT,
                    config,
                    binding,
                    adapter,
                    optimizer,
                    scheduler,
                    first.progress,
                    generator,
                )
                self.assertEqual(verified.progress.optimizer_steps_completed, 1)

                resumed_config, resumed_adapter, resumed_optimizer, resumed_scheduler, resumed_generator = _bundle(
                    core_type=core_type
                )
                # A restart reloads the same frozen backbone revision, but its
                # process RNGs may have moved arbitrarily before restore.
                random.seed(42)
                torch.manual_seed(42)
                resumed_generator.manual_seed(42)
                progress = training_execution.resume_training_checkpoint(
                    self.root,
                    checkpoint_id,
                    COMMIT,
                    binding,
                    resumed_config,
                    resumed_adapter,
                    resumed_optimizer,
                    resumed_scheduler,
                    resumed_generator,
                )
                second = training_execution.run_optimizer_steps(
                    resumed_adapter,
                    batches,
                    resumed_optimizer,
                    resumed_scheduler,
                    resumed_config,
                    progress,
                    1,
                )

                self.assertEqual(full.progress, second.progress)
                self.assertEqual(
                    full.optimizer_losses,
                    first.optimizer_losses + second.optimizer_losses,
                )
                self.assertEqual(
                    full.gradient_norms,
                    first.gradient_norms + second.gradient_norms,
                )
                self.assert_nested_equal(
                    full_model, trainable_state_dict(resumed_adapter)
                )
                self.assert_nested_equal(
                    full_optimizer, resumed_optimizer.state_dict()
                )
                self.assert_nested_equal(
                    full_scheduler, resumed_scheduler.state_dict()
                )
                self.assertEqual(full_python_draw, random.random())
                self.assertTrue(torch.equal(full_torch_draw, torch.rand(4)))
                self.assertTrue(
                    torch.equal(
                        full_loader_draw,
                        torch.rand(4, generator=resumed_generator),
                    )
                )


if __name__ == "__main__":
    unittest.main()
