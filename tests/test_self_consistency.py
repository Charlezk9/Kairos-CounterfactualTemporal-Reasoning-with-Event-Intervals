from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from kairos import generation, prediction_artifacts, self_consistency
from kairos.transfer_eval import TorqueExample


def _torque(record_id="torque:sc:1"):
    return TorqueExample(
        record_id=record_id,
        passage_id="passage",
        cluster_id="cluster",
        question="What happened?",
        passage="Alpha happened before Beta.",
        gold_spans=("Alpha",),
        gold_indices=("0",),
        is_default_question=True,
        derived_from_question="",
    )


class FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 0
    padding_side = "right"

    def __init__(self, over_budget=False):
        self.over_budget = over_budget

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return "<user>" + messages[0]["content"] + "<assistant>"

    def __call__(
        self, texts, return_tensors, padding, truncation, add_special_tokens
    ):
        width = generation.MODEL_CONTEXT_TOKENS if self.over_budget else 3
        return {
            "input_ids": torch.ones(len(texts), width, dtype=torch.long),
            "attention_mask": torch.ones(len(texts), width, dtype=torch.long),
        }

    def decode(self, tokens, skip_special_tokens, clean_up_tokenization_spaces):
        first = int(tokens[0]) if len(tokens) else 0
        return {
            10: 'FINAL_ANSWER: ["Alpha"]',
            11: 'FINAL_ANSWER: ["Beta"]',
            12: "not parseable",
            13: 'FINAL_ANSWER: [" alpha "]',
        }.get(first, "")


class FakeModel:
    def __init__(self, starts=None, invalid_shape=False):
        self.starts = starts or (10, 11, 10, 11, 12, 12, 12, 12)
        self.invalid_shape = invalid_shape
        self.last_kwargs = None
        self.last_input_batch = None

    def generate(self, input_ids, attention_mask, **kwargs):
        self.last_kwargs = kwargs
        self.last_input_batch = input_ids.shape[0]
        expected_rows = input_ids.shape[0] * self_consistency.SAMPLE_COUNT
        rows = expected_rows - 1 if self.invalid_shape else expected_rows
        prefix = input_ids.cpu().repeat_interleave(
            self_consistency.SAMPLE_COUNT, dim=0
        )[:rows]
        suffix = torch.zeros(rows, 2, dtype=torch.long)
        for index in range(rows):
            suffix[index, 0] = self.starts[index % len(self.starts)]
        return torch.cat((prefix, suffix), dim=1)


class SelfConsistencyAggregationTests(unittest.TestCase):
    def test_normalized_plurality_parse_exclusion_and_earliest_tie(self):
        responses = (
            'FINAL_ANSWER: ["Alpha", "Beta"]',
            'FINAL_ANSWER: ["beta", "alpha"]',
            'FINAL_ANSWER: ["Gamma"]',
            'FINAL_ANSWER: ["gamma"]',
            "bad one",
            "bad two",
            "bad three",
            "bad four",
        )
        prediction, errors, valid = self_consistency.aggregate_responses(responses)
        self.assertEqual(prediction, ["Alpha", "Beta"])
        self.assertEqual(errors, 4)
        self.assertEqual(valid, 4)

    def test_all_invalid_uses_fixed_sentinel(self):
        prediction, errors, valid = self_consistency.aggregate_responses(
            tuple("invalid" for unused in range(8))
        )
        self.assertEqual(prediction, [generation.PARSE_ERROR_SENTINEL])
        self.assertEqual(errors, 8)
        self.assertEqual(valid, 0)

    def test_response_shape_and_config_are_frozen(self):
        config = self_consistency.SelfConsistencyConfig()
        value = config.to_dict(13)
        self.assertEqual(value["sample_count"], 8)
        self.assertEqual(value["temperature"], 0.7)
        self.assertEqual(value["top_p"], 0.9)
        self.assertEqual(value["top_k"], 0)
        self.assertTrue(value["do_sample"])
        for changes in (
            {"sample_count": 7},
            {"temperature": 1.0},
            {"top_p": 1.0},
            {"batch_size": 1},
            {"sample_count": 8.0},
            {"temperature": 1},
            {"top_k": 0.0},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(self_consistency.SelfConsistencyError):
                    replace(config, **changes)
        with self.assertRaisesRegex(
            self_consistency.SelfConsistencyError, "exactly eight"
        ):
            self_consistency.aggregate_responses(("invalid",))


class SelfConsistencyGenerationTests(unittest.TestCase):
    def test_sampling_kwargs_vote_and_evidence_replay(self):
        model = FakeModel()
        tokenizer = FakeTokenizer()
        result = self_consistency.run_self_consistency(
            model,
            tokenizer,
            (_torque(),),
            self_consistency.SelfConsistencyConfig(),
            "cpu",
            13,
        )
        self.assertEqual(result.predictions[_torque().record_id], ["Alpha"])
        self.assertEqual(result.sample_parse_error_count, 4)
        self.assertEqual(result.all_invalid_record_count, 0)
        self.assertEqual(result.input_token_min, 3)
        self.assertEqual(result.input_token_max, 3)
        self.assertEqual(result.generated_token_total, 16)
        evidence = result.evidence[_torque().record_id]
        self.assertEqual(evidence.parse_status, "PARSED")
        self.assertEqual(evidence.generated_token_count, 16)
        responses, input_count, token_counts = self_consistency._parse_envelope(
            evidence.raw_response
        )
        self.assertEqual(input_count, 3)
        self.assertEqual(token_counts, (2,) * 8)
        self.assertEqual(
            self_consistency.aggregate_responses(responses)[0], ["Alpha"]
        )
        self.assertTrue(model.last_kwargs["do_sample"])
        self.assertEqual(model.last_kwargs["temperature"], 0.7)
        self.assertEqual(model.last_kwargs["top_p"], 0.9)
        self.assertEqual(model.last_kwargs["top_k"], 0)
        self.assertEqual(model.last_kwargs["num_return_sequences"], 8)
        self.assertEqual(tokenizer.padding_side, "left")

    def test_all_invalid_context_and_shape_failures(self):
        all_invalid = self_consistency.run_self_consistency(
            FakeModel(starts=(12,) * 8),
            FakeTokenizer(),
            (_torque(),),
            self_consistency.SelfConsistencyConfig(),
            "cpu",
            13,
        )
        self.assertEqual(all_invalid.all_invalid_record_count, 1)
        self.assertEqual(
            all_invalid.predictions[_torque().record_id],
            [generation.PARSE_ERROR_SENTINEL],
        )
        with self.assertRaisesRegex(
            self_consistency.SelfConsistencyError, "context budget"
        ):
            self_consistency.run_self_consistency(
                FakeModel(),
                FakeTokenizer(over_budget=True),
                (_torque(),),
                self_consistency.SelfConsistencyConfig(),
                "cpu",
                13,
            )

    def test_multiple_prompts_share_one_generation_batch_without_vote_mixing(self):
        model = FakeModel()
        result = self_consistency.run_self_consistency(
            model,
            FakeTokenizer(),
            (_torque("r1"), _torque("r2")),
            self_consistency.SelfConsistencyConfig(),
            "cpu",
            13,
        )
        self.assertEqual(model.last_input_batch, 2)
        self.assertEqual(result.predictions, {"r1": ["Alpha"], "r2": ["Alpha"]})
        self.assertEqual(result.sample_parse_error_count, 8)
        self.assertEqual(result.generated_token_total, 32)
        with self.assertRaisesRegex(
            self_consistency.SelfConsistencyError, "shape differs"
        ):
            self_consistency.run_self_consistency(
                FakeModel(invalid_shape=True),
                FakeTokenizer(),
                (_torque(),),
                self_consistency.SelfConsistencyConfig(),
                "cpu",
                13,
            )


class SelfConsistencyArtifactReplayTests(unittest.TestCase):
    def setUp(self):
        self.config = self_consistency.SelfConsistencyConfig()
        self.result = self_consistency.run_self_consistency(
            FakeModel(),
            FakeTokenizer(),
            (_torque(),),
            self.config,
            "cpu",
            13,
        )
        started = "2026-07-23T15:00:00Z"
        config_value = self.config.to_dict(13)
        run_id = prediction_artifacts.make_run_id(
            started,
            self_consistency.METHOD_NAME,
            "torque-dev",
            13,
            config_value,
        )
        spec = prediction_artifacts.RunSpec(
            run_id=run_id,
            dataset="torque-dev",
            method_name=self_consistency.METHOD_NAME,
            model_id=generation.MODEL_ID,
            model_revision=generation.MODEL_REVISION,
            execution_commit="a" * 40,
            seed=13,
            started_at=started,
            completed_at="2026-07-23T15:01:00Z",
            config=config_value,
            gpu_ids=(4,),
            cpu_threads=2,
            memory_gib=24,
            dataloader_workers=0,
        )
        record_id = _torque().record_id
        self.artifact = prediction_artifacts.VerifiedPredictionArtifact(
            spec=spec,
            records=(
                prediction_artifacts.PredictionRecord(
                    record_id, self.result.predictions[record_id]
                ),
            ),
            evidence=(self.result.evidence[record_id],),
            config_sha256="b" * 64,
            predictions_sha256="c" * 64,
            evidence_sha256="d" * 64,
            manifest_sha256="e" * 64,
            artifact_path=Path("/data0/hk_data/kairos-zx/artifacts/fake"),
        )

    def test_verified_artifact_recomputes_votes(self):
        with patch.object(
            self_consistency, "verify_predictions", return_value=self.artifact
        ):
            replay = self_consistency.verify_self_consistency_predictions(
                self.artifact.spec.run_id
            )
        self.assertEqual(replay.sample_parse_error_count, 4)
        self.assertEqual(replay.all_invalid_record_count, 0)
        self.assertEqual(replay.generated_token_total, 16)

    def test_prediction_and_config_tamper_fail_replay(self):
        bad_record = replace(
            self.artifact,
            records=(
                prediction_artifacts.PredictionRecord(
                    _torque().record_id, ["Beta"]
                ),
            ),
        )
        with patch.object(
            self_consistency, "verify_predictions", return_value=bad_record
        ):
            with self.assertRaisesRegex(
                self_consistency.SelfConsistencyError, "vote differs"
            ):
                self_consistency.verify_self_consistency_predictions(
                    bad_record.spec.run_id
                )

        bad_spec = SimpleNamespace(
            **{
                **self.artifact.spec.__dict__,
                "config": {**self.artifact.spec.config, "top_p": 1.0},
            }
        )
        bad_config = replace(self.artifact, spec=bad_spec)
        with patch.object(
            self_consistency, "verify_predictions", return_value=bad_config
        ):
            with self.assertRaisesRegex(
                self_consistency.SelfConsistencyError, "spec differs"
            ):
                self_consistency.verify_self_consistency_predictions(
                    bad_config.spec.run_id
                )


if __name__ == "__main__":
    unittest.main()
