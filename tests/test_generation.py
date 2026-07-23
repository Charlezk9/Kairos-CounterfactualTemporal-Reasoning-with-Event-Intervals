import unittest

import torch

from kairos import generation
from kairos.prompting import PromptStyle
from kairos.transfer_eval import (
    TimeQaExample,
    TorqueExample,
)


def _torque(record_id, gold=("Alpha",)):
    return TorqueExample(
        record_id=record_id,
        passage_id="passage",
        cluster_id="cluster",
        question="What happened?",
        passage="Alpha happened before Beta.",
        gold_spans=gold,
        gold_indices=tuple(str(index) for index in range(len(gold))),
        is_default_question=True,
        derived_from_question="",
    )


def _timeqa(record_id, targets=("answer",)):
    return TimeQaExample(
        record_id=record_id,
        idx=record_id,
        question="When?",
        context="Context",
        paragraphs=(),
        targets=targets,
    )


class FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 0
    padding_side = "right"

    def __init__(self, over_budget=False):
        self.over_budget = over_budget
        self.calls = []

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return "<user>" + messages[0]["content"] + "<assistant>"

    def __call__(
        self,
        texts,
        return_tensors,
        padding,
        truncation,
        add_special_tokens,
    ):
        self.calls.append(tuple(texts))
        if self.over_budget:
            width = generation.MODEL_CONTEXT_TOKENS
            return {
                "input_ids": torch.ones(len(texts), width, dtype=torch.long),
                "attention_mask": torch.ones(len(texts), width, dtype=torch.long),
            }
        width = 3
        input_ids = torch.zeros(len(texts), width, dtype=torch.long)
        attention = torch.zeros(len(texts), width, dtype=torch.long)
        for index in range(len(texts)):
            if index == 0:
                input_ids[index] = torch.tensor([0, 1, 2])
                attention[index] = torch.tensor([0, 1, 1])
            else:
                input_ids[index] = torch.tensor([3, 4, 5])
                attention[index] = torch.tensor([1, 1, 1])
        return {"input_ids": input_ids, "attention_mask": attention}

    def decode(self, tokens, skip_special_tokens, clean_up_tokenization_spaces):
        first = int(tokens[0]) if len(tokens) else 0
        return {
            10: 'FINAL_ANSWER: ["Alpha"]',
            20: "not parseable",
            30: 'FINAL_ANSWER: "answer"',
        }.get(first, "")


class FakeModel:
    def __init__(self, suffix_starts=(10, 20), invalid_shape=False):
        self.suffix_starts = suffix_starts
        self.invalid_shape = invalid_shape
        self.calls = 0
        self.last_kwargs = None

    def generate(self, input_ids, attention_mask, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.invalid_shape:
            return torch.zeros(input_ids.shape[0] + 1, input_ids.shape[1])
        suffix = torch.zeros(input_ids.shape[0], 2, dtype=torch.long)
        for index in range(input_ids.shape[0]):
            suffix[index, 0] = self.suffix_starts[index]
        return torch.cat((input_ids.cpu(), suffix), dim=1)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_greedy_and_style_specific(self):
        direct = generation.default_generation_config("torque-dev", "direct")
        cot = generation.default_generation_config("timeqa-hard", "cot")
        self.assertEqual(direct.max_new_tokens, 128)
        self.assertEqual(cot.max_new_tokens, 512)
        self.assertEqual(direct.method_name, "direct")
        self.assertFalse(direct.to_dict()["do_sample"])
        self.assertEqual(
            direct.max_input_tokens + direct.max_new_tokens,
            generation.MODEL_CONTEXT_TOKENS,
        )

    def test_config_rejects_unknown_values_and_bool_integers(self):
        cases = [
            ({"dataset": "unknown", "style": PromptStyle.DIRECT, "max_new_tokens": 1}, "dataset"),
            ({"dataset": "torque-dev", "style": "direct", "max_new_tokens": 1}, "PromptStyle"),
            ({"dataset": "torque-dev", "style": PromptStyle.DIRECT, "max_new_tokens": True}, "max_new"),
            ({"dataset": "torque-dev", "style": PromptStyle.DIRECT, "max_new_tokens": 4097}, "max_new"),
            ({"dataset": "torque-dev", "style": PromptStyle.DIRECT, "max_new_tokens": 1, "batch_size": 9}, "batch_size"),
        ]
        for values, message in cases:
            with self.subTest(values=values):
                with self.assertRaisesRegex(generation.GenerationError, message):
                    generation.GreedyGenerationConfig(**values)


class GenerationTests(unittest.TestCase):
    def test_torque_success_and_parse_error_are_both_auditable(self):
        config = generation.GreedyGenerationConfig(
            dataset="torque-dev",
            style=PromptStyle.DIRECT,
            max_new_tokens=8,
            batch_size=2,
        )
        tokenizer = FakeTokenizer()
        model = FakeModel()
        result = generation.run_greedy_generation(
            model,
            tokenizer,
            (_torque("r1"), _torque("r2")),
            config,
            "cpu",
        )
        self.assertEqual(result.predictions["r1"], ["Alpha"])
        self.assertEqual(
            result.predictions["r2"], [generation.PARSE_ERROR_SENTINEL]
        )
        self.assertEqual(result.evidence["r1"].parse_status, "PARSED")
        self.assertEqual(result.evidence["r2"].parse_status, "PARSE_ERROR")
        self.assertEqual(result.evidence["r1"].input_token_count, 2)
        self.assertEqual(result.evidence["r2"].input_token_count, 3)
        self.assertEqual(result.evidence["r1"].generated_token_count, 2)
        self.assertEqual(result.parse_error_count, 1)
        self.assertEqual(result.input_token_min, 2)
        self.assertEqual(result.input_token_max, 3)
        self.assertEqual(result.generated_token_total, 4)
        self.assertEqual(model.calls, 1)
        self.assertIs(model.last_kwargs["do_sample"], False)
        self.assertIsNone(model.last_kwargs["temperature"])
        self.assertIsNone(model.last_kwargs["top_p"])
        self.assertIsNone(model.last_kwargs["top_k"])
        self.assertEqual(tokenizer.padding_side, "left")

    def test_timeqa_parsed_string(self):
        config = generation.GreedyGenerationConfig(
            dataset="timeqa-hard",
            style=PromptStyle.COT,
            max_new_tokens=8,
        )
        result = generation.run_greedy_generation(
            FakeModel(suffix_starts=(30,)),
            FakeTokenizer(),
            (_timeqa("t1"),),
            config,
            torch.device("cpu"),
        )
        self.assertEqual(result.predictions, {"t1": "answer"})
        self.assertEqual(result.parse_error_count, 0)

    def test_context_budget_fails_before_model_generation(self):
        config = generation.GreedyGenerationConfig(
            dataset="torque-dev",
            style=PromptStyle.DIRECT,
            max_new_tokens=8,
        )
        model = FakeModel(suffix_starts=(10,))
        with self.assertRaisesRegex(generation.GenerationError, "context budget"):
            generation.run_greedy_generation(
                model, FakeTokenizer(over_budget=True), (_torque("r1"),), config, "cpu"
            )
        self.assertEqual(model.calls, 0)

    def test_sentinel_collision_duplicate_ids_and_wrong_example_type_fail(self):
        torque_config = generation.GreedyGenerationConfig(
            dataset="torque-dev",
            style=PromptStyle.DIRECT,
            max_new_tokens=8,
        )
        with self.assertRaisesRegex(generation.GenerationError, "collides"):
            generation.run_greedy_generation(
                FakeModel((10,)),
                FakeTokenizer(),
                (_torque("r", (generation.PARSE_ERROR_SENTINEL,)),),
                torque_config,
                "cpu",
            )
        with self.assertRaisesRegex(generation.GenerationError, "duplicated"):
            generation.run_greedy_generation(
                FakeModel(),
                FakeTokenizer(),
                (_torque("r"), _torque("r")),
                torque_config,
                "cpu",
            )
        with self.assertRaisesRegex(generation.GenerationError, "type differs"):
            generation.run_greedy_generation(
                FakeModel((10,)),
                FakeTokenizer(),
                (_timeqa("t"),),
                torque_config,
                "cpu",
            )

    def test_runtime_contract_rejects_invalid_model_tokenizer_and_output(self):
        config = generation.GreedyGenerationConfig(
            dataset="torque-dev",
            style=PromptStyle.DIRECT,
            max_new_tokens=8,
        )
        with self.assertRaisesRegex(generation.GenerationError, "generate"):
            generation.run_greedy_generation(
                object(), FakeTokenizer(), (_torque("r"),), config, "cpu"
            )
        with self.assertRaisesRegex(generation.GenerationError, "not callable"):
            generation.run_greedy_generation(
                FakeModel((10,)), object(), (_torque("r"),), config, "cpu"
            )
        with self.assertRaisesRegex(generation.GenerationError, "shape"):
            generation.run_greedy_generation(
                FakeModel(invalid_shape=True),
                FakeTokenizer(),
                (_torque("r"),),
                config,
                "cpu",
            )


if __name__ == "__main__":
    unittest.main()
