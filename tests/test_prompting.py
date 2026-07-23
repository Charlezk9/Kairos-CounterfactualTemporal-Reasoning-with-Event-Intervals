import unittest

from kairos import prompting
from kairos.transfer_eval import (
    TimeQaExample,
    TimeQaParagraph,
    TorqueExample,
)


def _torque_example():
    return TorqueExample(
        record_id="torque:1",
        passage_id="passage-1",
        cluster_id="cluster-1",
        question="What happened first?",
        passage="Alpha happened before Beta.",
        gold_spans=("Alpha",),
        gold_indices=("0",),
        is_default_question=True,
        derived_from_question="",
    )


def _timeqa_example(paragraphs=None):
    if paragraphs is None:
        paragraphs = (
            TimeQaParagraph(title="Document A", text="An event happened in 1999."),
            TimeQaParagraph(title="Document B", text="Another event happened later."),
        )
    return TimeQaExample(
        record_id="timeqa:1",
        idx="hard-1",
        question="When did the event happen?",
        context="The question is anchored in 2001.",
        paragraphs=paragraphs,
        targets=("1999",),
    )


class PromptBuilderTests(unittest.TestCase):
    def test_torque_direct_prompt_is_deterministic_and_has_no_gold_field(self):
        example = _torque_example()
        first = prompting.build_torque_prompt(example, "direct")
        second = prompting.build_torque_prompt(
            example, prompting.PromptStyle.DIRECT
        )
        self.assertEqual(first, second)
        self.assertEqual(first.dataset, "torque-dev")
        self.assertEqual(first.record_id, example.record_id)
        self.assertIn(example.passage, first.text)
        self.assertIn(example.question, first.text)
        self.assertIn("JSON array of strings", first.text)
        self.assertNotIn("gold_spans", first.text)
        self.assertNotIn("Gold answer", first.text)

    def test_cot_instruction_changes_only_reasoning_policy(self):
        example = _torque_example()
        direct = prompting.build_torque_prompt(example, "direct")
        cot = prompting.build_torque_prompt(example, "cot")
        self.assertNotEqual(direct.text, cot.text)
        self.assertIn("Reason step by step", cot.text)
        self.assertNotIn("Reason step by step", direct.text)
        self.assertIn(example.passage, cot.text)
        self.assertIn(example.question, cot.text)

    def test_timeqa_prompt_includes_context_documents_and_empty_document_marker(self):
        example = _timeqa_example()
        bundle = prompting.build_timeqa_prompt(example, "direct")
        self.assertEqual(bundle.dataset, "timeqa-hard")
        self.assertIn(example.context, bundle.text)
        self.assertIn("Document A", bundle.text)
        self.assertIn("An event happened in 1999.", bundle.text)
        self.assertIn("<DOCUMENT index=\"2\">", bundle.text)
        self.assertIn("one JSON string", bundle.text)

        empty = prompting.build_timeqa_prompt(
            _timeqa_example(paragraphs=()), "direct"
        )
        self.assertIn("<NO_SUPPORTING_DOCUMENTS />", empty.text)

    def test_prompt_builders_reject_wrong_examples_and_style(self):
        with self.assertRaisesRegex(prompting.PromptError, "TorqueExample"):
            prompting.build_torque_prompt(_timeqa_example(), "direct")
        with self.assertRaisesRegex(prompting.PromptError, "TimeQaExample"):
            prompting.build_timeqa_prompt(_torque_example(), "direct")
        with self.assertRaisesRegex(prompting.PromptError, "direct or cot"):
            prompting.build_torque_prompt(_torque_example(), "self-consistency")


class ResponseParserTests(unittest.TestCase):
    def test_torque_direct_cot_empty_and_duplicate_spans(self):
        self.assertEqual(
            prompting.parse_torque_response('FINAL_ANSWER: ["Alpha", "Beta"]'),
            ("Alpha", "Beta"),
        )
        cot = "Alpha precedes Beta.\nTherefore Alpha is first.\nFINAL_ANSWER: [\"Alpha\"]\n"
        self.assertEqual(prompting.parse_torque_response(cot), ("Alpha",))
        self.assertEqual(prompting.parse_torque_response("FINAL_ANSWER: []"), ())
        self.assertEqual(
            prompting.parse_torque_response('FINAL_ANSWER: ["A", "A"]'),
            ("A", "A"),
        )

    def test_timeqa_string_and_empty_string(self):
        self.assertEqual(
            prompting.parse_timeqa_response('FINAL_ANSWER: "The Answer!"'),
            "The Answer!",
        )
        self.assertEqual(prompting.parse_timeqa_response('FINAL_ANSWER: ""'), "")

    def test_final_answer_must_be_unique_terminal_and_correct_json_type(self):
        cases = [
            ("[\"A\"]", "exactly one"),
            ("FINAL_ANSWER: [\"A\"]\ntrailing", "exactly one"),
            (
                "FINAL_ANSWER: [\"A\"]\nFINAL_ANSWER: [\"B\"]",
                "exactly one",
            ),
            (" FINAL_ANSWER: [\"A\"]", "exactly one"),
            ("FINAL_ANSWER: ", "payload"),
            ("FINAL_ANSWER: [", "strict JSON"),
            ("FINAL_ANSWER: NaN", "non-finite"),
        ]
        for response, message in cases:
            with self.subTest(response=response):
                with self.assertRaisesRegex(prompting.PromptError, message):
                    prompting.parse_torque_response(response)
        with self.assertRaisesRegex(prompting.PromptError, "JSON array"):
            prompting.parse_torque_response('FINAL_ANSWER: "Alpha"')
        with self.assertRaisesRegex(prompting.PromptError, "JSON string"):
            prompting.parse_timeqa_response('FINAL_ANSWER: ["Alpha"]')

    def test_torque_span_constraints(self):
        with self.assertRaisesRegex(prompting.PromptError, "non-empty"):
            prompting.parse_torque_response('FINAL_ANSWER: [""]')
        with self.assertRaisesRegex(prompting.PromptError, "non-empty"):
            prompting.parse_torque_response('FINAL_ANSWER: ["  "]')
        too_many = ",".join('"x"' for unused in range(65))
        with self.assertRaisesRegex(prompting.PromptError, "too many"):
            prompting.parse_torque_response(f"FINAL_ANSWER: [{too_many}]")


class CandidateTests(unittest.TestCase):
    def test_timeqa_dedup_uses_official_normalizer_and_preserves_first_surface(self):
        values = ("The Answer!", "answer", "Other", "the", "")
        self.assertEqual(
            prompting.deduplicate_timeqa_candidates(values),
            ("The Answer!", "Other", "the"),
        )

    def test_torque_dedup_uses_normalized_sets_and_deduplicates_spans(self):
        values = (
            (" Alpha ", "Beta", "alpha"),
            ("beta", "ALPHA"),
            (),
            (),
            ("A!",),
            ("A",),
        )
        self.assertEqual(
            prompting.deduplicate_torque_candidates(values),
            ((" Alpha ", "Beta"), (), ("A!",), ("A",)),
        )

    def test_candidate_contracts_reject_wrong_shapes_and_empty_pool(self):
        with self.assertRaisesRegex(prompting.PromptError, "count"):
            prompting.deduplicate_timeqa_candidates(())
        with self.assertRaisesRegex(prompting.PromptError, "strings"):
            prompting.deduplicate_timeqa_candidates(("a", 1))
        with self.assertRaisesRegex(prompting.PromptError, "span sequence"):
            prompting.deduplicate_torque_candidates(("not-a-sequence",))
        with self.assertRaisesRegex(prompting.PromptError, "non-empty"):
            prompting.deduplicate_torque_candidates((("" ,),))

    def test_candidate_serialization_is_stable_json(self):
        self.assertEqual(
            prompting.serialize_candidate("timeqa-hard", "A\nB"), '"A\\nB"'
        )
        self.assertEqual(
            prompting.serialize_candidate("torque-dev", ("B", "A")),
            '["B","A"]',
        )
        with self.assertRaisesRegex(prompting.PromptError, "dataset"):
            prompting.serialize_candidate("unknown", "A")


if __name__ == "__main__":
    unittest.main()
