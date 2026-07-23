from dataclasses import replace
from types import SimpleNamespace
import unittest

import torch
from torch import nn

from kairos.modeling import (
    IGNORE_RELATION_INDEX,
    KairosConfig,
    KairosModel,
    PairMlpBaseline,
)
from kairos import training_adapter


class FakeEncoder(nn.Module):
    def __init__(self, hidden_size=8):
        super().__init__()
        self.embedding = nn.Embedding(64, hidden_size)
        self.last_kwargs = None

    def forward(self, input_ids, attention_mask, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(last_hidden_state=self.embedding(input_ids))


class FakeBackbone(nn.Module):
    def __init__(self, hidden_size=8):
        super().__init__()
        self.config = SimpleNamespace(hidden_size=hidden_size)
        self.model = FakeEncoder(hidden_size)


class QwenLikeBlock(nn.Module):
    def __init__(self, hidden_size=8):
        super().__init__()
        for name in training_adapter.LORA_TARGET_MODULES:
            setattr(self, name, nn.Linear(hidden_size, hidden_size))


def _batch(counterfactual=True):
    input_ids = torch.tensor([[1, 2, 3, 0], [4, 5, 6, 7]])
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
            [[8, 9, 0], [10, 11, 0], [0, 0, 0]],
            [[12, 13, 0], [0, 0, 0], [0, 0, 0]],
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
    values = dict(
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
    )
    if counterfactual:
        cf_targets = torch.full((2, 2, 2), IGNORE_RELATION_INDEX, dtype=torch.long)
        cf_targets[:, 0, 1] = 1
        values.update(
            counterfactual_input_ids=input_ids.clone(),
            counterfactual_attention_mask=attention.clone(),
            counterfactual_event_token_mask=event_tokens.clone(),
            counterfactual_event_mask=event_mask.clone(),
            counterfactual_relation_targets=cf_targets,
        )
    return training_adapter.TrainingBatch(**values)


class TrainingBatchTests(unittest.TestCase):
    def test_batch_freezes_padding_targets_and_counterfactual_group(self):
        batch = _batch()
        self.assertTrue(batch.has_counterfactual)
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "padded candidate"):
            replace(batch, answer_targets=torch.tensor([2, 0]))
        broken_attention = batch.candidate_attention_mask.clone()
        broken_attention[0, 2, 0] = 1
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "candidate padding"):
            replace(batch, candidate_attention_mask=broken_attention)
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "provided together"):
            replace(batch, counterfactual_relation_targets=None)

    def test_event_tokens_cannot_select_padding(self):
        batch = _batch()
        invalid = batch.event_token_mask.clone()
        invalid[0, 0, 3] = True
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "padded token"):
            replace(batch, event_token_mask=invalid)


class AdapterForwardTests(unittest.TestCase):
    def test_kairos_and_pair_mlp_share_batch_and_backpropagate(self):
        for core_type in (KairosModel, PairMlpBaseline):
            with self.subTest(core_type=core_type.__name__):
                backbone = FakeBackbone()
                core = core_type(KairosConfig(hidden_size=8, shared_size=4, pair_mlp_hidden_size=6))
                adapter = training_adapter.QwenCoreTrainingAdapter(backbone, core)
                result = adapter(_batch())
                self.assertEqual(result.original.candidate_scores.shape, (2, 3))
                self.assertIsNotNone(result.counterfactual)
                self.assertTrue(torch.isfinite(result.losses["loss"]))
                self.assertGreater(result.losses["relation_loss"].item(), 0)
                self.assertGreater(
                    result.losses["counterfactual_relation_loss"].item(), 0
                )
                result.losses["loss"].backward()
                self.assertIsNotNone(backbone.model.embedding.weight.grad)
                self.assertTrue(
                    any(parameter.grad is not None for parameter in core.parameters())
                )
                self.assertFalse(backbone.model.last_kwargs["use_cache"])
                self.assertFalse(backbone.model.last_kwargs["output_hidden_states"])

    def test_relation_only_counterfactual_is_optional(self):
        adapter = training_adapter.QwenCoreTrainingAdapter(
            FakeBackbone(), KairosModel(KairosConfig(hidden_size=8, shared_size=4))
        )
        result = adapter(_batch(counterfactual=False))
        self.assertIsNone(result.counterfactual)
        self.assertEqual(result.losses["counterfactual_relation_loss"].item(), 0.0)

    def test_hidden_size_and_hidden_output_fail_closed(self):
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "hidden sizes"):
            training_adapter.QwenCoreTrainingAdapter(
                FakeBackbone(7), KairosModel(KairosConfig(hidden_size=8))
            )
        backbone = FakeBackbone()
        backbone.model.forward = lambda **kwargs: SimpleNamespace(
            last_hidden_state=torch.zeros(1, 1, 7)
        )
        adapter = training_adapter.QwenCoreTrainingAdapter(
            backbone, KairosModel(KairosConfig(hidden_size=8))
        )
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "hidden state"):
            adapter(_batch(counterfactual=False))


class LoraAndStateTests(unittest.TestCase):
    def test_lora_defaults_and_target_validation(self):
        spec = training_adapter.LoraSpec()
        value = spec.to_dict()
        self.assertEqual(value["target_modules"], list(training_adapter.LORA_TARGET_MODULES))
        self.assertTrue(value["gradient_checkpointing"])
        self.assertFalse(value["use_cache"])
        counts = training_adapter.validate_lora_targets(QwenLikeBlock(), spec)
        self.assertEqual(counts, {name: 1 for name in training_adapter.LORA_TARGET_MODULES})
        with self.assertRaises(training_adapter.TrainingAdapterError):
            replace(spec, rank=8)
        broken = QwenLikeBlock()
        broken.q_proj = nn.GELU()
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "not Linear"):
            training_adapter.validate_lora_targets(broken, spec)

    def test_trainable_state_round_trip_is_exact(self):
        adapter = training_adapter.QwenCoreTrainingAdapter(
            FakeBackbone(), KairosModel(KairosConfig(hidden_size=8, shared_size=4))
        )
        adapter.backbone.model.embedding.weight.requires_grad_(False)
        state = training_adapter.trainable_state_dict(adapter)
        self.assertTrue(state)
        self.assertFalse(any("embedding" in name for name in state))
        expected = {name: value.clone() for name, value in state.items()}
        with torch.no_grad():
            for parameter in adapter.core.parameters():
                parameter.add_(1.0)
        training_adapter.load_trainable_state_dict(adapter, state)
        restored = training_adapter.trainable_state_dict(adapter)
        for name in expected:
            self.assertTrue(torch.equal(expected[name], restored[name]))
        with self.assertRaisesRegex(training_adapter.TrainingAdapterError, "keys differ"):
            training_adapter.load_trainable_state_dict(
                adapter, {name: value for name, value in state.items() if name != next(iter(state))}
            )


if __name__ == "__main__":
    unittest.main()
