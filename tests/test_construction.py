from dataclasses import fields, replace
import unittest

from kairos.construction import (
    ConstructionResult,
    ConstructionTerminal,
    construct_explicit_counterfactual,
    is_reliable_relation,
)
from kairos.ids import make_stable_id
from kairos.io import ConstructionOutcome
from kairos.schema import (
    AnswerStatus,
    AnswerType,
    CharSpan,
    EventMention,
    Extraction,
    Relation,
    RelationAnnotation,
    RejectionReason,
    SplitAssignment,
    TemporalExample,
)


def example(
    *,
    text="Alpha before Beta",
    question="Which happened first?",
    answers=("Alpha",),
    answer_type=AnswerType.EXTRACTIVE,
):
    return TemporalExample(
        record_id="record:synthetic-original",
        source_id="source:synthetic",
        dataset="synthetic",
        split=SplitAssignment(official="validation", internal=None),
        revision="synthetic-v1",
        source_sha256="0" * 64,
        text=text,
        question=question,
        answers=answers,
        answer_type=answer_type,
    )


class ConstructionContractTests(unittest.TestCase):
    def test_exact_enum_values_and_result_fields(self):
        self.assertEqual(
            [terminal.value for terminal in ConstructionTerminal],
            [
                "no_marker",
                "extraction_rejected",
                "text_question_alias_unsupported",
                "rewrite_rejected",
                "multiple_answers_unsupported",
                "answer_update_unknown",
                "retained",
            ],
        )
        self.assertEqual(
            [field.name for field in fields(ConstructionResult)],
            [
                "input_record_id",
                "outcome",
                "terminal",
                "extraction_result",
                "rewrite_result",
                "answer_update",
                "template_id",
                "prospective_pair_id",
                "prospective_counterfactual_record_id",
                "original",
                "counterfactual",
            ],
        )

    def test_input_type_and_preconditions(self):
        with self.assertRaises(TypeError):
            construct_explicit_counterfactual("not an example")

        base = example()
        event = EventMention("e1", "Alpha", CharSpan(0, 5))
        invalid = (
            replace(base, events=(event,)),
            replace(base, events=[]),
            replace(
                base,
                events=(event, EventMention("e2", "Beta", CharSpan(13, 17))),
                relations=(RelationAnnotation("e1", "e2", Relation.PRECEDES, "before"),),
            ),
            replace(base, relations=[]),
            replace(base, counterfactual_pair_id="counterfactual-pair:existing"),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    construct_explicit_counterfactual(value)

    def test_no_marker_precedes_text_question_alias_check(self):
        result = construct_explicit_counterfactual(
            example(text="No temporal relation", question="No temporal relation")
        )
        self.assertIs(result.terminal, ConstructionTerminal.NO_MARKER)
        self.assertEqual(result.outcome, ConstructionOutcome())
        self.assertIs(result.extraction_result.rejection.reason, RejectionReason.NO_MARKER)
        self.assertIsNone(result.rewrite_result)
        self.assertEqual(
            (
                result.template_id,
                result.prospective_pair_id,
                result.prospective_counterfactual_record_id,
            ),
            (None, None, None),
        )
        self.assertIsNone(result.original)
        self.assertIsNone(result.counterfactual)

    def test_other_extraction_rejections_have_only_temporal_stage(self):
        cases = (
            ("Alpha while Beta", RejectionReason.UNSUPPORTED_MARKER),
            ("Alpha before Beta, then Gamma", RejectionReason.MULTIPLE_MARKERS),
            ("before Beta", RejectionReason.EMPTY_LEFT_EVENT),
        )
        for text, reason in cases:
            with self.subTest(text=text):
                result = construct_explicit_counterfactual(example(text=text))
                self.assertIs(result.terminal, ConstructionTerminal.EXTRACTION_REJECTED)
                self.assertEqual(result.outcome, ConstructionOutcome(True))
                self.assertIs(result.extraction_result.rejection.reason, reason)
                self.assertIsNone(result.rewrite_result)
                self.assertEqual(
                    (
                        result.template_id,
                        result.prospective_pair_id,
                        result.prospective_counterfactual_record_id,
                    ),
                    (None, None, None),
                )

    def test_text_question_alias_is_rejected_after_extraction(self):
        result = construct_explicit_counterfactual(
            example(text="Alpha before Beta", question="Alpha before Beta")
        )
        self.assertIs(result.terminal, ConstructionTerminal.TEXT_QUESTION_ALIAS_UNSUPPORTED)
        self.assertEqual(result.outcome, ConstructionOutcome(True, True, True))
        self.assertTrue(result.extraction_result.accepted)
        self.assertIsNone(result.rewrite_result)
        self.assertEqual(
            (
                result.template_id,
                result.prospective_pair_id,
                result.prospective_counterfactual_record_id,
            ),
            (None, None, None),
        )

    def test_rewrite_rejection_retains_the_rejected_result(self):
        result = construct_explicit_counterfactual(example(text="Alpha prior to Beta"))
        self.assertIs(result.terminal, ConstructionTerminal.REWRITE_REJECTED)
        self.assertEqual(result.outcome, ConstructionOutcome(True, True, True))
        self.assertFalse(result.rewrite_result.accepted)
        self.assertIs(result.rewrite_result.rejection.reason, RejectionReason.UNSUPPORTED_REWRITE)
        self.assertEqual(
            (
                result.template_id,
                result.prospective_pair_id,
                result.prospective_counterfactual_record_id,
            ),
            (None, None, None),
        )
        self.assertIsNone(result.answer_update)

    def test_multiple_answers_stop_after_rewrite_and_keep_prospective_ids(self):
        original = example(answers=("Alpha", "alternate"))
        result = construct_explicit_counterfactual(original)
        self.assertIs(result.terminal, ConstructionTerminal.MULTIPLE_ANSWERS_UNSUPPORTED)
        self.assertEqual(result.outcome, ConstructionOutcome(True, True, True, True))
        self.assertIsNone(result.answer_update)
        self.assertIsNotNone(result.rewrite_result)
        self.assertIsNotNone(result.template_id)
        self.assertIsNotNone(result.prospective_pair_id)
        self.assertIsNotNone(result.prospective_counterfactual_record_id)
        self.assertIsNone(result.original)
        self.assertIsNone(result.counterfactual)

    def test_real_updater_unknown_paths_never_emit_a_partial_pair(self):
        cases = (
            example(
                question="How many items?",
                answers=("3",),
                answer_type=AnswerType.NUMERIC,
            ),
            example(
                question="Explain the result.",
                answers=("Alpha",),
                answer_type=AnswerType.FREE_GENERATION,
            ),
            example(question="What happened?", answers=("Alpha",)),
        )
        for original in cases:
            with self.subTest(answer_type=original.answer_type, question=original.question):
                result = construct_explicit_counterfactual(original)
                self.assertIs(result.terminal, ConstructionTerminal.ANSWER_UPDATE_UNKNOWN)
                self.assertEqual(result.outcome, ConstructionOutcome(True, True, True, True))
                self.assertIs(result.answer_update.status, AnswerStatus.UNKNOWN)
                self.assertIsNotNone(result.template_id)
                self.assertIsNotNone(result.prospective_pair_id)
                self.assertIsNotNone(result.prospective_counterfactual_record_id)
                self.assertIsNone(result.original)
                self.assertIsNone(result.counterfactual)

    def test_retained_extractive_pair_has_exact_fields_and_ids(self):
        source = example()
        first = construct_explicit_counterfactual(source)
        second = construct_explicit_counterfactual(source)
        self.assertEqual(first, second)
        self.assertIs(first.terminal, ConstructionTerminal.RETAINED)
        self.assertEqual(first.outcome, ConstructionOutcome(True, True, True, True, True))

        expected_pair_id = make_stable_id(
            "counterfactual-pair",
            {
                "version": "explicit-marker-construction-v0",
                "source_id": source.source_id,
                "original_record_id": source.record_id,
                "template_id": first.rewrite_result.template_id,
            },
        )
        expected_counterfactual_id = make_stable_id(
            "record",
            {
                "version": "counterfactual-explicit-marker-v0",
                "source_id": source.source_id,
                "original_record_id": source.record_id,
                "counterfactual_pair_id": expected_pair_id,
                "template_id": first.rewrite_result.template_id,
                "variant": "counterfactual",
            },
        )
        self.assertEqual(first.prospective_pair_id, expected_pair_id)
        self.assertEqual(first.prospective_counterfactual_record_id, expected_counterfactual_id)

        original = first.original
        counterfactual = first.counterfactual
        self.assertEqual(original.record_id, source.record_id)
        self.assertEqual(original.source_id, source.source_id)
        self.assertEqual(original.dataset, source.dataset)
        self.assertEqual(original.split, source.split)
        self.assertEqual(original.revision, source.revision)
        self.assertEqual(original.source_sha256, source.source_sha256)
        self.assertEqual(original.text, source.text)
        self.assertEqual(original.question, source.question)
        self.assertEqual(original.answers, source.answers)
        self.assertEqual(original.answer_type, source.answer_type)
        self.assertEqual(counterfactual.record_id, expected_counterfactual_id)
        self.assertEqual(counterfactual.source_id, source.source_id)
        self.assertEqual(counterfactual.dataset, source.dataset)
        self.assertEqual(counterfactual.split, source.split)
        self.assertEqual(counterfactual.revision, source.revision)
        self.assertEqual(counterfactual.source_sha256, source.source_sha256)
        self.assertEqual(counterfactual.question, source.question)
        self.assertEqual(counterfactual.answer_type, source.answer_type)
        self.assertEqual(original.counterfactual_pair_id, expected_pair_id)
        self.assertEqual(counterfactual.counterfactual_pair_id, expected_pair_id)
        self.assertEqual(counterfactual.text, "Alpha after Beta")
        self.assertEqual(counterfactual.answers, ("Beta",))
        self.assertEqual(original.events, (
            first.extraction_result.extraction.event_a,
            first.extraction_result.extraction.event_b,
        ))
        self.assertEqual(original.relations, (first.extraction_result.extraction.relation,))
        self.assertEqual(counterfactual.events, (
            first.rewrite_result.rewritten.event_a,
            first.rewrite_result.rewritten.event_b,
        ))
        self.assertEqual(counterfactual.relations, (first.rewrite_result.rewritten.relation,))

    def test_retained_yes_no_pair_uses_truth_table(self):
        result = construct_explicit_counterfactual(
            example(
                question="Did Alpha happen before Beta?",
                answers=("yes",),
                answer_type=AnswerType.YES_NO,
            )
        )
        self.assertIs(result.terminal, ConstructionTerminal.RETAINED)
        self.assertEqual(result.counterfactual.answers, ("no",))
        self.assertEqual(result.counterfactual.question, "Did Alpha happen before Beta?")

    def test_reliable_relation_helper_rejects_hand_built_unknown(self):
        text = "Alpha before Beta"
        event_a = EventMention("e1", "Alpha", CharSpan(0, 5))
        event_b = EventMention("e2", "Beta", CharSpan(13, 17))
        extraction = Extraction(
            text=text,
            marker="before",
            marker_span=CharSpan(6, 12),
            event_a=event_a,
            event_b=event_b,
            relation=RelationAnnotation("e1", "e2", Relation.UNKNOWN, "before"),
        )
        self.assertFalse(is_reliable_relation(extraction))
        self.assertTrue(
            is_reliable_relation(
                replace(
                    extraction,
                    relation=RelationAnnotation("e1", "e2", Relation.PRECEDES, "before"),
                )
            )
        )
        with self.assertRaises(TypeError):
            is_reliable_relation("not an extraction")

    def test_result_rejects_inconsistent_optional_matrix(self):
        retained = construct_explicit_counterfactual(example())
        unknown = construct_explicit_counterfactual(
            example(
                question="How many items?",
                answers=("3",),
                answer_type=AnswerType.NUMERIC,
            )
        )
        no_marker = construct_explicit_counterfactual(
            example(text="No temporal relation", question="No temporal relation")
        )
        mutations = (
            lambda: replace(retained, original=None),
            lambda: replace(unknown, answer_update=None),
            lambda: replace(no_marker, rewrite_result=retained.rewrite_result),
            lambda: replace(no_marker, outcome=ConstructionOutcome(True)),
            lambda: replace(retained, template_id="different-template"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises(ValueError):
                    mutate()


if __name__ == "__main__":
    unittest.main()
