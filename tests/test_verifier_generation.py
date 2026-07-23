import unittest

import torch

from kairos import generation, verifier_generation
from kairos.transfer_eval import TorqueExample


def _example(record_id, gold=("UNSEEN_GOLD",)):
    return TorqueExample(
        record_id=record_id,
        passage_id="passage",
        cluster_id="cluster",
        question="What happened before Beta?",
        passage="Alpha happened before Beta. Gamma happened later.",
        gold_spans=gold,
        gold_indices=tuple(str(index) for index in range(len(gold))),
        is_default_question=True,
        derived_from_question="",
    )


def _config(**overrides):
    values = {
        "reference_run_id": "direct-run",
        "reference_manifest_sha256": "a" * 64,
        "candidate_run_id": "cot-run",
        "candidate_manifest_sha256": "b" * 64,
        "max_new_tokens": 8,
        "batch_size": 2,
    }
    values.update(overrides)
    return verifier_generation.VerifierGenerationConfig(**values)


class FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 0
    padding_side = "right"

    def __init__(self, over_budget=False):
        self.over_budget = over_budget
        self.prompts = []

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return "<user>" + messages[0]["content"] + "<assistant>"

    def __call__(self, texts, return_tensors, padding, truncation, add_special_tokens):
        self.prompts.extend(texts)
        width = generation.MODEL_CONTEXT_TOKENS if self.over_budget else 4
        return {
            "input_ids": torch.ones(len(texts), width, dtype=torch.long),
            "attention_mask": torch.ones(len(texts), width, dtype=torch.long),
        }

    def decode(self, tokens, skip_special_tokens, clean_up_tokenization_spaces):
        first = int(tokens[0]) if len(tokens) else 0
        return {
            10: "Checked.\nFINAL_ANSWER: 1",
            20: "FINAL_ANSWER: true",
            30: "FINAL_ANSWER: 0",
        }.get(first, "invalid")


class FakeModel:
    def __init__(self, starts=(10,)):
        self.starts = starts
        self.calls = 0
        self.last_kwargs = None

    def generate(self, input_ids, attention_mask, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        suffix = torch.zeros(input_ids.shape[0], 2, dtype=torch.long)
        for index in range(input_ids.shape[0]):
            suffix[index, 0] = self.starts[index]
        return torch.cat((input_ids.cpu(), suffix), dim=1)


class ConfigAndPromptTests(unittest.TestCase):
    def test_config_is_fixed_and_binds_upstream_manifests(self):
        config = _config()
        value = config.to_dict()
        self.assertEqual(config.method_name, "cot-verifier")
        self.assertEqual(value["candidate_order"], ["reference-direct", "candidate-cot"])
        self.assertEqual(value["reference_manifest_sha256"], "a" * 64)
        self.assertFalse(value["do_sample"])
        for kwargs, message in (
            ({"candidate_run_id": "direct-run"}, "differ"),
            ({"reference_manifest_sha256": "A" * 64}, "SHA256"),
            ({"max_new_tokens": True}, "max_new"),
            ({"batch_size": 9}, "batch_size"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(
                    verifier_generation.VerifierGenerationError, message
                ):
                    _config(**kwargs)

    def test_prompt_contains_only_supplied_candidates_and_no_gold_field(self):
        prompt = verifier_generation.build_torque_verifier_prompt(
            _example("r1"), ["Alpha"], ["Gamma"]
        )
        self.assertIn('<CANDIDATE_0>\n["Alpha"]', prompt)
        self.assertIn('<CANDIDATE_1>\n["Gamma"]', prompt)
        self.assertNotIn("UNSEEN_GOLD", prompt)
        self.assertNotIn("gold", prompt.casefold())

    def test_terminal_index_parser_is_strict(self):
        self.assertEqual(
            verifier_generation.parse_verifier_response(
                "Reasoning.\nFINAL_ANSWER: 1\n"
            ),
            1,
        )
        for value in (
            "FINAL_ANSWER: true",
            'FINAL_ANSWER: "1"',
            "FINAL_ANSWER: 2",
            "FINAL_ANSWER: 0\nFINAL_ANSWER: 1",
            "FINAL_ANSWER: 0\ntrailing",
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaises(verifier_generation.VerifierGenerationError):
                    verifier_generation.parse_verifier_response(value)


class VerifierGenerationTests(unittest.TestCase):
    def test_equivalent_candidate_skips_generation_and_distinct_selects_cot(self):
        examples = (_example("r1"), _example("r2"))
        reference = {"r1": ["Alpha"], "r2": ["Alpha"]}
        candidate = {"r1": ["alpha"], "r2": ["Gamma"]}
        model = FakeModel((10,))
        tokenizer = FakeTokenizer()
        result = verifier_generation.run_torque_verifier_generation(
            model, tokenizer, examples, reference, candidate, _config(), "cpu"
        )
        self.assertEqual(result.predictions["r1"], ["Alpha"])
        self.assertEqual(result.predictions["r2"], ["Gamma"])
        self.assertEqual(result.evidence["r1"].parse_status, "NOT_APPLICABLE")
        self.assertEqual(result.evidence["r1"].input_token_count, 0)
        self.assertEqual(result.evidence["r2"].parse_status, "PARSED")
        self.assertEqual(result.parse_error_count, 0)
        self.assertEqual(model.calls, 1)
        self.assertIs(model.last_kwargs["do_sample"], False)
        self.assertIsNone(model.last_kwargs["temperature"])
        self.assertEqual(tokenizer.padding_side, "left")

    def test_parse_error_falls_back_to_reference(self):
        example = _example("r1")
        result = verifier_generation.run_torque_verifier_generation(
            FakeModel((20,)),
            FakeTokenizer(),
            (example,),
            {"r1": ["Alpha"]},
            {"r1": ["Gamma"]},
            _config(),
            torch.device("cpu"),
        )
        self.assertEqual(result.predictions, {"r1": ["Alpha"]})
        self.assertEqual(result.evidence["r1"].parse_status, "PARSE_ERROR")
        self.assertEqual(result.parse_error_count, 1)

    def test_coverage_types_and_context_fail_closed(self):
        example = _example("r1")
        with self.assertRaisesRegex(
            verifier_generation.VerifierGenerationError, "coverage"
        ):
            verifier_generation.run_torque_verifier_generation(
                FakeModel(), FakeTokenizer(), (example,), {}, {"r1": []}, _config(), "cpu"
            )
        with self.assertRaisesRegex(
            verifier_generation.VerifierGenerationError, "span sequence"
        ):
            verifier_generation.run_torque_verifier_generation(
                FakeModel(),
                FakeTokenizer(),
                (example,),
                {"r1": "Alpha"},
                {"r1": []},
                _config(),
                "cpu",
            )
        with self.assertRaisesRegex(
            verifier_generation.VerifierGenerationError, "context budget"
        ):
            verifier_generation.run_torque_verifier_generation(
                FakeModel(),
                FakeTokenizer(over_budget=True),
                (example,),
                {"r1": ["Alpha"]},
                {"r1": ["Gamma"]},
                _config(),
                "cpu",
            )


if __name__ == "__main__":
    unittest.main()
