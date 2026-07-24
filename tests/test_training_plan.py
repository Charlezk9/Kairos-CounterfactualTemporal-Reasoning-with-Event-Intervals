import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import torch

from kairos.ids import canonical_json, make_stable_id, sha256_canonical
from kairos.training_adapter import TrainingBatch
from kairos.training_execution import (
    TrainingArtifactBinding,
    TrainingProgress,
    TrainingStepResult,
)
from kairos.training_plan import (
    CandidateBinding,
    MaterializedTrainingBatch,
    TrainingCorpusBinding,
    TrainingCursor,
    TrainingExampleBinding,
    TrainingPlanError,
    build_training_plan,
    execute_planned_training_steps,
    training_plan_from_dict,
)


def _example(index, *, gold_injected=False):
    example_id = make_stable_id("example", {"index": index})
    gold = f"gold-{index}"
    wrong = f"wrong-{index}"
    if gold_injected:
        candidates = (
            CandidateBinding.from_text(example_id, wrong, ("direct", "cot")),
            CandidateBinding.from_text(example_id, gold, ("gold",)),
        )
        target = 1
    else:
        candidates = (
            CandidateBinding.from_text(example_id, gold, ("direct", "cot")),
            CandidateBinding.from_text(
                example_id, wrong, ("self-consistency",)
            ),
        )
        target = 0
    return TrainingExampleBinding(
        source_order_index=index,
        example_id=example_id,
        source_id=make_stable_id("source", {"index": index}),
        original_record_id=make_stable_id(
            "record", {"index": index, "variant": "original"}
        ),
        counterfactual_record_id=make_stable_id(
            "record", {"index": index, "variant": "counterfactual"}
        ),
        record_sha256=sha256_canonical({"record": index}),
        gold_answer_sha256=CandidateBinding.from_text(
            example_id, gold, ("direct",)
        ).content_sha256,
        candidates=candidates,
        answer_target_index=target,
        gold_injected=gold_injected,
    )


def _corpus(count=11):
    return TrainingCorpusBinding(
        execution_commit="d" * 40,
        dataset_id="synthetic",
        dataset_revision="e" * 40,
        official_split="train",
        source_artifact_id="DEV-SYNTHETIC-SOURCE-V1",
        source_manifest_sha256="f" * 64,
        examples=tuple(
            _example(index, gold_injected=index % 2 == 1)
            for index in range(count)
        ),
    )


def _tensor_batch(targets=(0, 0)):
    batch_size = len(targets)
    input_ids = torch.tensor([[1, 2]] * batch_size, dtype=torch.long)
    attention = torch.ones(batch_size, 2, dtype=torch.long)
    event_tokens = torch.tensor(
        [[[True, False]]] * batch_size, dtype=torch.bool
    )
    event_mask = torch.ones(batch_size, 1, dtype=torch.bool)
    candidate_ids = torch.tensor(
        [[[3, 4], [5, 6]]] * batch_size, dtype=torch.long
    )
    candidate_attention = torch.ones(batch_size, 2, 2, dtype=torch.long)
    candidate_tokens = torch.tensor(
        [[[False, True], [False, True]]] * batch_size, dtype=torch.bool
    )
    return TrainingBatch(
        input_ids=input_ids,
        attention_mask=attention,
        event_token_mask=event_tokens,
        event_mask=event_mask,
        candidate_input_ids=candidate_ids,
        candidate_attention_mask=candidate_attention,
        candidate_token_mask=candidate_tokens,
        candidate_mask=torch.ones(batch_size, 2, dtype=torch.bool),
        answer_targets=torch.tensor(targets, dtype=torch.long),
    )


class CandidateAndCorpusTests(unittest.TestCase):
    def test_candidate_and_gold_injection_contract(self):
        generated_gold = _example(0, gold_injected=False)
        self.assertFalse(generated_gold.gold_injected)
        self.assertEqual(generated_gold.answer_target_index, 0)
        self.assertNotIn("gold", generated_gold.candidates[0].origins)

        injected_gold = _example(1, gold_injected=True)
        self.assertTrue(injected_gold.gold_injected)
        self.assertEqual(
            injected_gold.answer_target_index, len(injected_gold.candidates) - 1
        )
        self.assertEqual(injected_gold.candidates[-1].origins, ("gold",))

        with self.assertRaisesRegex(TrainingPlanError, "canonically ordered"):
            CandidateBinding.from_text(
                generated_gold.example_id, "candidate", ("cot", "direct")
            )
        with self.assertRaisesRegex(TrainingPlanError, "example/content"):
            replace(
                generated_gold,
                candidates=(
                    replace(generated_gold.candidates[0], candidate_id="candidate:bad"),
                    generated_gold.candidates[1],
                ),
            )
        with self.assertRaisesRegex(TrainingPlanError, "must not claim gold"):
            replace(
                injected_gold,
                gold_injected=False,
            )

    def test_source_order_and_global_identities_are_strict(self):
        corpus = _corpus(3)
        self.assertEqual([item.source_order_index for item in corpus.examples], [0, 1, 2])
        with self.assertRaisesRegex(TrainingPlanError, "source order"):
            replace(
                corpus,
                examples=(corpus.examples[1], corpus.examples[0], corpus.examples[2]),
            )
        with self.assertRaisesRegex(TrainingPlanError, "source ID is duplicated"):
            replace(
                corpus,
                examples=(
                    corpus.examples[0],
                    replace(corpus.examples[1], source_id=corpus.examples[0].source_id),
                    corpus.examples[2],
                ),
            )


class DeterministicPlanTests(unittest.TestCase):
    def test_three_epochs_tail_padding_and_batch_binding(self):
        corpus = _corpus(11)
        first = build_training_plan(corpus, seed=13, micro_batch_size=2)
        second = build_training_plan(corpus, seed=13, micro_batch_size=2)
        other_seed = build_training_plan(corpus, seed=42, micro_batch_size=2)

        self.assertEqual(first, second)
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertNotEqual(
            [slot.example_id for slot in first.slots[:11]],
            [slot.example_id for slot in other_seed.slots[:11]],
        )
        self.assertEqual(first.real_slot_count, 33)
        self.assertEqual(first.repeat_padding_count, 31)
        self.assertEqual(len(first.slots), 64)
        self.assertEqual(len(first.micro_batches), 32)
        self.assertEqual(first.total_optimizer_steps, 2)
        self.assertEqual(first.gradient_accumulation_steps, 16)
        self.assertEqual(first.execution_config.total_optimizer_steps, 2)

        expected_ids = {example.example_id for example in corpus.examples}
        for epoch in range(3):
            epoch_slots = [slot for slot in first.slots if slot.epoch_index == epoch]
            self.assertEqual(len(epoch_slots), 11)
            self.assertEqual({slot.example_id for slot in epoch_slots}, expected_ids)
            self.assertTrue(all(not slot.repeat_padding for slot in epoch_slots))
        self.assertTrue(all(slot.repeat_padding for slot in first.slots[33:]))
        self.assertTrue(all(slot.epoch_index is None for slot in first.slots[33:]))

        by_id = {example.example_id: example for example in corpus.examples}
        for micro_batch in first.micro_batches:
            self.assertEqual(len(micro_batch.example_ids), 2)
            self.assertEqual(
                micro_batch.candidate_ids,
                tuple(
                    tuple(candidate.candidate_id for candidate in by_id[value].candidates)
                    for value in micro_batch.example_ids
                ),
            )

    def test_divisible_corpus_has_no_padding(self):
        plan = build_training_plan(_corpus(32), seed=2026, micro_batch_size=32)
        self.assertEqual(plan.real_slot_count, 96)
        self.assertEqual(plan.repeat_padding_count, 0)
        self.assertEqual(plan.total_optimizer_steps, 3)
        self.assertTrue(all(not slot.repeat_padding for slot in plan.slots))

    def test_manifest_round_trip_and_tamper_rejection(self):
        plan = build_training_plan(_corpus(11), seed=13, micro_batch_size=2)
        payload = json.loads(canonical_json(plan.to_dict()))
        replay = training_plan_from_dict(payload)
        self.assertEqual(replay, plan)
        self.assertEqual(replay.manifest_sha256, plan.manifest_sha256)

        changed_slot = copy.deepcopy(payload)
        changed_slot["slots"][0]["example_id"] = changed_slot["slots"][1]["example_id"]
        with self.assertRaisesRegex(TrainingPlanError, "reconstruction"):
            training_plan_from_dict(changed_slot)

        changed_candidate = copy.deepcopy(payload)
        changed_candidate["corpus"]["examples"][0]["candidates"][0][
            "content_sha256"
        ] = "0" * 64
        with self.assertRaises(TrainingPlanError):
            training_plan_from_dict(changed_candidate)

        extra = copy.deepcopy(payload)
        extra["unexpected"] = True
        with self.assertRaisesRegex(TrainingPlanError, "invalid training plan"):
            training_plan_from_dict(extra)


class CursorAndExecutionBindingTests(unittest.TestCase):
    def test_exact_optimizer_boundary_cursor(self):
        plan = build_training_plan(_corpus(11), seed=13, micro_batch_size=2)
        initial = plan.cursor(0)
        self.assertEqual(initial.consumed_slots, 0)
        self.assertEqual(initial.completed_epochs, 0)
        self.assertFalse(initial.done)

        middle = plan.cursor(1)
        self.assertEqual(middle.next_micro_batch_index, 16)
        self.assertEqual(middle.consumed_slots, 32)
        self.assertEqual(middle.consumed_real_slots, 32)
        self.assertEqual(middle.consumed_repeat_padding_slots, 0)
        self.assertEqual(middle.completed_epochs, 2)
        self.assertFalse(middle.next_is_repeat_padding)

        final = plan.cursor(2)
        self.assertEqual(final.consumed_slots, 64)
        self.assertEqual(final.consumed_real_slots, 33)
        self.assertEqual(final.consumed_repeat_padding_slots, 31)
        self.assertEqual(final.completed_epochs, 3)
        self.assertTrue(final.done)
        self.assertIsNone(final.next_example_id)
        plan.validate_cursor(final)

        with self.assertRaisesRegex(TrainingPlanError, "deterministic"):
            plan.validate_cursor(replace(final, consumed_real_slots=32))
        with self.assertRaisesRegex(TrainingPlanError, "exact plan cursor"):
            plan.validate_progress(replace(plan.progress(1), epoch=1))
        with self.assertRaisesRegex(TrainingPlanError, "outside"):
            plan.cursor(3)

        binding = TrainingArtifactBinding(
            model_id="Qwen/Qwen2.5-7B-Instruct",
            model_revision="a09a35458c702b33eeacc393d103063234e8bc28",
            model_sha256sums_sha256=(
                "3ee6c9510b7e50bfcd46d6df33cafa3e2019f13a6a09bf1d2f9e80cdfe1164e8"
            ),
            dataset_id=plan.corpus.dataset_id,
            dataset_revision=plan.corpus.dataset_revision,
            split="train",
            data_artifact_id="TRAINING-PLAN-V1",
            data_manifest_sha256=plan.manifest_sha256,
            core_type="kairos",
        )
        plan.validate_artifact_binding(binding)
        with self.assertRaisesRegex(TrainingPlanError, "data binding differs"):
            plan.validate_artifact_binding(
                replace(binding, data_manifest_sha256="0" * 64)
            )

    def test_materialized_identities_checked_before_execution(self):
        plan = build_training_plan(_corpus(11), seed=13, micro_batch_size=2)
        by_id = {example.example_id: example for example in plan.corpus.examples}
        batches = tuple(
            MaterializedTrainingBatch(
                expected.example_ids,
                expected.candidate_ids,
                _tensor_batch(
                    tuple(
                        by_id[example_id].answer_target_index
                        for example_id in expected.example_ids
                    )
                ),
            )
            for expected in plan.micro_batches
        )
        bad_first = replace(
            batches[0],
            example_ids=(batches[0].example_ids[1], batches[0].example_ids[0]),
        )
        with patch("kairos.training_plan.run_optimizer_steps") as execute:
            with self.assertRaisesRegex(TrainingPlanError, "identities differ"):
                execute_planned_training_steps(
                    object(),
                    (bad_first,) + batches[1:],
                    object(),
                    object(),
                    plan,
                    plan.progress(0),
                    1,
                )
            execute.assert_not_called()

        wrong_targets = replace(
            batches[0],
            batch=replace(
                batches[0].batch,
                answer_targets=1 - batches[0].batch.answer_targets,
            ),
        )
        with patch("kairos.training_plan.run_optimizer_steps") as execute:
            with self.assertRaisesRegex(TrainingPlanError, "answer targets differ"):
                execute_planned_training_steps(
                    object(),
                    (wrong_targets,) + batches[1:],
                    object(),
                    object(),
                    plan,
                    plan.progress(0),
                    1,
                )
            execute.assert_not_called()

        executor_result = TrainingStepResult(
            TrainingProgress(
                epoch=0,
                next_micro_batch_index=16,
                optimizer_steps_completed=1,
                samples_seen=32,
            ),
            (1.25,),
            (0.5,),
        )
        with patch(
            "kairos.training_plan.run_optimizer_steps",
            return_value=executor_result,
        ) as execute:
            result = execute_planned_training_steps(
                object(),
                batches,
                object(),
                object(),
                plan,
                plan.progress(0),
                1,
            )
        execute.assert_called_once()
        self.assertEqual(result.progress, plan.progress(1))
        self.assertEqual(result.progress.epoch, 2)


if __name__ == "__main__":
    unittest.main()
