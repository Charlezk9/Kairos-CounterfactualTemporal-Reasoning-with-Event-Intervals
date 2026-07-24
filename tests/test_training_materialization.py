from dataclasses import replace
import hashlib
import unittest

import torch

from kairos.ids import make_stable_id
from kairos.modeling import IGNORE_RELATION_INDEX, RELATION_TO_INDEX
from kairos.relation_supervision import construct_gsm8k_relation_only
from kairos.relation_supervision_artifacts import REVISION
from kairos.schema import AnswerType, SplitAssignment, TemporalExample
from kairos.training_materialization import (
    BoundTrainingRecord,
    CandidateProposal,
    TrainingMaterializationError,
    bind_relation_pair,
    build_relation_training_corpus,
    materialize_micro_batch,
)
from kairos.training_plan import build_training_plan


def _pair(index=0, answer=None):
    source_id = make_stable_id("source", {"materialization": index})
    source = TemporalExample(
        record_id=make_stable_id("record", {"materialization": index}),
        source_id=source_id,
        dataset="gsm8k",
        split=SplitAssignment(official="train", internal=None),
        revision=REVISION,
        source_sha256=hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        text=f"Alpha{index} happened before Beta{index} happened.",
        question=f"Alpha{index} happened before Beta{index} happened.",
        answers=(str(40 + index) if answer is None else answer,),
        answer_type=AnswerType.NUMERIC,
    )
    result = construct_gsm8k_relation_only(source)
    if result.pair is None:
        raise AssertionError("synthetic pair was not retained")
    return result.pair


class FakeFastTokenizer:
    is_fast = True
    padding_side = "right"
    pad_token_id = 0

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        if tokenize is not False or add_generation_prompt is not True:
            raise AssertionError("unexpected chat arguments")
        return "<USER>" + messages[0]["content"] + "</USER><ASSISTANT>"

    def __call__(
        self,
        texts,
        *,
        padding,
        truncation,
        add_special_tokens,
        return_offsets_mapping,
        return_tensors,
    ):
        if (
            padding is not True
            or truncation is not False
            or add_special_tokens is not False
            or return_offsets_mapping is not True
            or return_tensors != "pt"
        ):
            raise AssertionError("unexpected tokenizer arguments")
        width = max(len(text) for text in texts)
        ids = torch.zeros((len(texts), width), dtype=torch.long)
        attention = torch.zeros_like(ids)
        offsets = torch.zeros((len(texts), width, 2), dtype=torch.long)
        for row, text in enumerate(texts):
            for column, character in enumerate(text):
                ids[row, column] = 1 + (ord(character) % 255)
                attention[row, column] = 1
                offsets[row, column] = torch.tensor([column, column + 1])
        return {
            "input_ids": ids,
            "attention_mask": attention,
            "offset_mapping": offsets,
        }


def _record(index, proposals):
    return bind_relation_pair(_pair(index), proposals, index)


def _corpus(records):
    return build_relation_training_corpus(
        records,
        "d" * 40,
        "PROC-SYNTHETIC-RELATION-V1",
        "e" * 64,
    )


class CandidateBindingTests(unittest.TestCase):
    def test_exact_dedup_origin_merge_and_gold_rules(self):
        record = _record(
            0,
            (
                CandidateProposal("wrong", "direct"),
                CandidateProposal("40", "cot"),
                CandidateProposal("wrong", "self-consistency"),
            ),
        )
        self.assertEqual(record.candidate_texts, ("wrong", "40"))
        self.assertEqual(
            record.binding.candidates[0].origins,
            ("direct", "self-consistency"),
        )
        self.assertEqual(record.binding.candidates[1].origins, ("cot",))
        self.assertEqual(record.binding.answer_target_index, 1)
        self.assertFalse(record.binding.gold_injected)

        injected = _record(1, (CandidateProposal("wrong", "direct"),))
        self.assertEqual(injected.candidate_texts, ("wrong", "41"))
        self.assertEqual(injected.binding.candidates[-1].origins, ("gold",))
        self.assertEqual(injected.binding.answer_target_index, 1)
        self.assertTrue(injected.binding.gold_injected)

        reordered = _record(
            2,
            (
                CandidateProposal("same", "self-consistency"),
                CandidateProposal("same", "direct"),
            ),
        )
        self.assertEqual(
            reordered.binding.candidates[0].origins,
            ("direct", "self-consistency"),
        )

    def test_invalid_proposals_and_source_order_fail_closed(self):
        with self.assertRaisesRegex(TrainingMaterializationError, "origin"):
            CandidateProposal("answer", "gold")
        with self.assertRaisesRegex(TrainingMaterializationError, "non-empty"):
            CandidateProposal("", "direct")
        with self.assertRaisesRegex(TrainingMaterializationError, "must be non-empty"):
            bind_relation_pair(_pair(), (), 0)

        records = (
            _record(0, (CandidateProposal("40", "direct"),)),
            bind_relation_pair(
                _pair(1), (CandidateProposal("41", "direct"),), 2
            ),
        )
        with self.assertRaisesRegex(TrainingMaterializationError, "source order"):
            _corpus(records)


class TokenMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.records = (
            _record(
                0,
                (
                    CandidateProposal("wrong", "direct"),
                    CandidateProposal("40", "cot"),
                ),
            ),
            _record(1, (CandidateProposal("wrong", "direct"),)),
        )
        self.plan = build_training_plan(_corpus(self.records), 13, 2)
        self.by_id = {record.binding.example_id: record for record in self.records}

    def test_one_micro_batch_has_exact_masks_targets_and_ids(self):
        value = materialize_micro_batch(
            self.plan, 0, self.by_id, FakeFastTokenizer()
        )
        expected = self.plan.micro_batches[0]
        self.assertEqual(value.example_ids, expected.example_ids)
        self.assertEqual(value.candidate_ids, expected.candidate_ids)
        self.assertEqual(value.batch.input_ids.device.type, "cpu")
        self.assertTrue(value.batch.has_counterfactual)
        self.assertTrue(torch.all(value.batch.event_mask))
        self.assertTrue(torch.all(value.batch.counterfactual_event_mask))
        self.assertEqual(value.batch.relation_targets.shape, (2, 2, 2))
        self.assertEqual(
            set(value.batch.relation_targets.flatten().tolist()),
            {
                IGNORE_RELATION_INDEX,
                RELATION_TO_INDEX["precedes"],
                RELATION_TO_INDEX["follows"],
            },
        )
        self.assertTrue(
            torch.equal(
                value.batch.counterfactual_relation_targets[:, 0, 1],
                value.batch.relation_targets[:, 1, 0],
            )
        )
        for row, example_id in enumerate(expected.example_ids):
            record = self.by_id[example_id]
            self.assertEqual(
                int(value.batch.answer_targets[row]),
                record.binding.answer_target_index,
            )
            self.assertEqual(
                int(value.batch.candidate_mask[row].sum()),
                len(record.binding.candidates),
            )

    def test_explicit_repeat_slots_materialize_without_identity_drift(self):
        record = self.records[:1]
        plan = build_training_plan(_corpus(record), 42, 2)
        by_id = {record[0].binding.example_id: record[0]}
        value = materialize_micro_batch(
            plan, len(plan.micro_batches) - 1, by_id, FakeFastTokenizer()
        )
        self.assertEqual(value.example_ids, plan.micro_batches[-1].example_ids)
        self.assertEqual(value.example_ids[0], value.example_ids[1])
        self.assertTrue(all(plan.micro_batches[-1].repeat_padding))

    def test_coverage_tokenizer_and_binding_mismatch_fail_before_training(self):
        with self.assertRaisesRegex(TrainingMaterializationError, "coverage"):
            materialize_micro_batch(
                self.plan,
                0,
                {next(iter(self.by_id)): next(iter(self.by_id.values()))},
                FakeFastTokenizer(),
            )
        tokenizer = FakeFastTokenizer()
        tokenizer.padding_side = "left"
        with self.assertRaisesRegex(TrainingMaterializationError, "right padding"):
            materialize_micro_batch(self.plan, 0, self.by_id, tokenizer)

        record = next(iter(self.by_id.values()))
        with self.assertRaisesRegex(TrainingMaterializationError, "content binding"):
            replace(record, candidate_texts=("tampered",) + record.candidate_texts[1:])


if __name__ == "__main__":
    unittest.main()
