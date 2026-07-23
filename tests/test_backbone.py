import unittest

import torch

from kairos import backbone
from kairos.schema import CharSpan


class FakeTokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        if tokenize is not False or add_generation_prompt is not True:
            raise AssertionError("unexpected template arguments")
        if messages != [{"role": "user", "content": messages[0]["content"]}]:
            raise AssertionError("unexpected messages")
        return "<|user|>\n" + messages[0]["content"] + "\n<|assistant|>\n"


class ChatAndCandidateTests(unittest.TestCase):
    def test_chat_format_binds_literal_user_content_and_shifts_spans(self):
        prompt = "Alpha before Beta"
        formatted = backbone.format_chat_prompt(FakeTokenizer(), prompt)
        self.assertEqual(
            formatted.user_content_span.text_from(formatted.text), prompt
        )
        spans = backbone.shift_user_spans(
            formatted, prompt, (CharSpan(0, 5), CharSpan(13, 17))
        )
        self.assertEqual(spans[0].text_from(formatted.text), "Alpha")
        self.assertEqual(spans[1].text_from(formatted.text), "Beta")

    def test_chat_format_rejects_missing_or_duplicated_content(self):
        class Missing:
            def apply_chat_template(self, *unused_args, **unused_kwargs):
                return "no literal content"

        class Duplicate:
            def apply_chat_template(self, messages, **unused_kwargs):
                content = messages[0]["content"]
                return content + content

        with self.assertRaisesRegex(backbone.BackboneContractError, "exactly once"):
            backbone.format_chat_prompt(Missing(), "prompt")
        with self.assertRaisesRegex(backbone.BackboneContractError, "exactly once"):
            backbone.format_chat_prompt(Duplicate(), "prompt")
        with self.assertRaisesRegex(backbone.BackboneContractError, "no callable"):
            backbone.format_chat_prompt(object(), "prompt")

    def test_shift_rejects_stale_binding_and_out_of_range_span(self):
        formatted = backbone.format_chat_prompt(FakeTokenizer(), "first")
        with self.assertRaisesRegex(backbone.BackboneContractError, "not bound"):
            backbone.shift_user_spans(formatted, "other", (CharSpan(0, 1),))
        with self.assertRaisesRegex(backbone.BackboneContractError, "invalid"):
            backbone.shift_user_spans(formatted, "first", (CharSpan(0, 6),))

    def test_candidate_encoding_has_exact_explicit_answer_span(self):
        value = backbone.build_candidate_encoding_text("Question?", '""')
        self.assertEqual(value.candidate_span.text_from(value.text), '""')
        nonempty = backbone.build_candidate_encoding_text("Question?", '["A","B"]')
        self.assertEqual(
            nonempty.candidate_span.text_from(nonempty.text), '["A","B"]'
        )
        with self.assertRaisesRegex(backbone.BackboneContractError, "explicit"):
            backbone.build_candidate_encoding_text("Question?", "")


class AlignmentTests(unittest.TestCase):
    def test_alignment_selects_intersecting_tokens_and_pads_events(self):
        offsets = torch.tensor(
            [
                [[0, 0], [0, 5], [6, 12], [13, 17], [0, 0]],
                [[0, 3], [4, 8], [9, 12], [0, 0], [0, 0]],
            ],
            dtype=torch.long,
        )
        attention = torch.tensor(
            [[1, 1, 1, 1, 1], [1, 1, 1, 0, 0]], dtype=torch.long
        )
        aligned = backbone.align_char_spans(
            offsets,
            attention,
            (
                (CharSpan(0, 5), CharSpan(6, 17)),
                (CharSpan(4, 8),),
            ),
        )
        expected_tokens = torch.tensor(
            [
                [[False, True, False, False, False], [False, False, True, True, False]],
                [[False, True, False, False, False], [False, False, False, False, False]],
            ]
        )
        expected_events = torch.tensor([[True, True], [True, False]])
        self.assertTrue(torch.equal(aligned.event_token_mask, expected_tokens))
        self.assertTrue(torch.equal(aligned.event_mask, expected_events))

    def test_alignment_uses_overlap_for_subword_boundaries(self):
        offsets = torch.tensor([[[0, 2], [2, 5], [6, 9]]])
        aligned = backbone.align_char_spans(
            offsets,
            torch.tensor([[True, True, True]]),
            ((CharSpan(1, 4), CharSpan(6, 9)),),
        )
        self.assertTrue(
            torch.equal(
                aligned.event_token_mask,
                torch.tensor([[[True, True, False], [False, False, True]]]),
            )
        )

    def test_alignment_rejects_truncation_overlap_and_invalid_offset_masks(self):
        offsets = torch.tensor([[[0, 4], [5, 9], [0, 0]]])
        attention = torch.tensor([[1, 1, 0]])
        with self.assertRaisesRegex(backbone.BackboneContractError, "no aligned token"):
            backbone.align_char_spans(
                offsets, attention, ((CharSpan(10, 12),),)
            )
        with self.assertRaisesRegex(backbone.BackboneContractError, "overlap"):
            backbone.align_char_spans(
                offsets,
                attention,
                ((CharSpan(0, 6), CharSpan(5, 8)),),
            )
        bad_padding = offsets.clone()
        bad_padding[0, 2] = torch.tensor([1, 2])
        with self.assertRaisesRegex(backbone.BackboneContractError, "padded"):
            backbone.align_char_spans(
                bad_padding, attention, ((CharSpan(0, 4),),)
            )
        with self.assertRaisesRegex(backbone.BackboneContractError, "0/1"):
            backbone.align_char_spans(
                offsets, torch.tensor([[1, 2, 0]]), ((CharSpan(0, 4),),)
            )

    def test_alignment_requires_nonempty_bounded_event_lists_and_batch_match(self):
        offsets = torch.tensor([[[0, 2]]])
        attention = torch.tensor([[True]])
        with self.assertRaisesRegex(backbone.BackboneContractError, "batch size"):
            backbone.align_char_spans(offsets, attention, ())
        with self.assertRaisesRegex(backbone.BackboneContractError, "event count"):
            backbone.align_char_spans(offsets, attention, ((),))
        too_many = tuple(CharSpan(index * 2, index * 2 + 1) for index in range(257))
        with self.assertRaisesRegex(backbone.BackboneContractError, "event count"):
            backbone.align_char_spans(offsets, attention, (too_many,))


if __name__ == "__main__":
    unittest.main()
