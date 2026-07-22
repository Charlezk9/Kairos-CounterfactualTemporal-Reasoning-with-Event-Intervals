import unittest

from kairos.counterfactual import rewrite_counterfactual, update_answer
from kairos.events import extract_explicit_relation
from kairos.schema import (
    AnswerStatus,
    AnswerType,
    CounterfactualRewrite,
    ExtractionResult,
    Relation,
    RejectionReason,
)


def accepted(text):
    result = extract_explicit_relation(text)
    if not result.accepted:
        raise AssertionError(result.rejection)
    return result.extraction


class MarkerTests(unittest.TestCase):
    def test_extracts_clause_local_spans_and_direction(self):
        text = "Intro. Alpha prepared before Beta departed; trailing material."
        extraction = accepted(text)
        self.assertEqual(extraction.event_a.text, "Alpha prepared")
        self.assertEqual(extraction.event_b.text, "Beta departed")
        self.assertEqual(extraction.event_a.char_span.text_from(text), "Alpha prepared")
        self.assertEqual(extraction.event_b.char_span.text_from(text), "Beta departed")
        self.assertIs(extraction.relation.relation, Relation.PRECEDES)

    def test_marker_directions(self):
        cases = {
            "A before B": Relation.PRECEDES,
            "A after B": Relation.FOLLOWS,
            "A earlier than B": Relation.PRECEDES,
            "A later than B": Relation.FOLLOWS,
            "A prior to B": Relation.PRECEDES,
        }
        for text, relation in cases.items():
            with self.subTest(text=text):
                self.assertIs(accepted(text).relation.relation, relation)

    def test_multiple_markers_are_structurally_rejected(self):
        result = extract_explicit_relation("A before B, then C")
        self.assertFalse(result.accepted)
        self.assertIs(result.rejection.reason, RejectionReason.MULTIPLE_MARKERS)

    def test_unsupported_and_empty_sides_are_structurally_rejected(self):
        unsupported = extract_explicit_relation("A while B")
        self.assertIs(unsupported.rejection.reason, RejectionReason.UNSUPPORTED_MARKER)
        empty_left = extract_explicit_relation("before B")
        self.assertIs(empty_left.rejection.reason, RejectionReason.EMPTY_LEFT_EVENT)
        empty_right = extract_explicit_relation("A before ; B")
        self.assertIs(empty_right.rejection.reason, RejectionReason.EMPTY_RIGHT_EVENT)


class CounterfactualTests(unittest.TestCase):
    def test_rewrite_changes_only_target_and_inverts_relation(self):
        original = accepted("Alpha happened BEFORE Beta happened.")
        rewrite = rewrite_counterfactual(original)
        self.assertIsInstance(rewrite, CounterfactualRewrite)
        self.assertEqual(rewrite.rewritten_text, "Alpha happened AFTER Beta happened.")
        self.assertIs(rewrite.rewritten.relation.relation, Relation.FOLLOWS)
        start, end = original.marker_span.start, original.marker_span.end
        new_end = start + len("AFTER")
        self.assertEqual(original.text[:start], rewrite.rewritten_text[:start])
        self.assertEqual(original.text[end:], rewrite.rewritten_text[new_end:])

    def test_multiword_rewrite_and_prior_to_rejection(self):
        rewrite = rewrite_counterfactual(accepted("A earlier than B"))
        self.assertEqual(rewrite.rewritten_text, "A later than B")
        rejected = rewrite_counterfactual(accepted("A prior to B"))
        self.assertIsInstance(rejected, ExtractionResult)
        self.assertIs(rejected.rejection.reason, RejectionReason.UNSUPPORTED_REWRITE)

    def test_event_choice_update_requires_exact_original_answer(self):
        rewrite = rewrite_counterfactual(accepted("Alpha before Beta"))
        known = update_answer(
            original_answer="Alpha",
            question="Which happened first?",
            answer_type=AnswerType.EXTRACTIVE,
            rewrite=rewrite,
        )
        self.assertIs(known.status, AnswerStatus.KNOWN)
        self.assertEqual(known.value, "Beta")
        unknown = update_answer(
            original_answer="something about Alpha",
            question="Which happened first?",
            answer_type=AnswerType.EXTRACTIVE,
            rewrite=rewrite,
        )
        self.assertIs(unknown.status, AnswerStatus.UNKNOWN)
        self.assertIsNone(unknown.value)

    def test_yes_no_truth_table_is_exact_and_answer_unchanged_is_unknown(self):
        rewrite = rewrite_counterfactual(accepted("Alpha before Beta"))
        known = update_answer(
            original_answer="yes",
            question="Did Alpha happen before Beta?",
            answer_type=AnswerType.YES_NO,
            rewrite=rewrite,
        )
        self.assertEqual((known.status, known.value), (AnswerStatus.KNOWN, "no"))
        unrelated = update_answer(
            original_answer="yes",
            question="Is Gamma ready?",
            answer_type=AnswerType.YES_NO,
            rewrite=rewrite,
        )
        self.assertIs(unrelated.status, AnswerStatus.UNKNOWN)
        self.assertIsNone(unrelated.value)

    def test_yes_no_rejects_relations_unrelated_to_changed_target(self):
        rewrite = rewrite_counterfactual(accepted("Alpha before Beta"))
        unrelated_queries = (
            "Do Alpha and Beta overlap?",
            "Is Alpha during Beta?",
            "Does Alpha contain Beta?",
        )
        for question in unrelated_queries:
            with self.subTest(question=question):
                update = update_answer(
                    original_answer="no",
                    question=question,
                    answer_type=AnswerType.YES_NO,
                    rewrite=rewrite,
                )
                self.assertIs(update.status, AnswerStatus.UNKNOWN)
                self.assertIsNone(update.value)

    def test_yes_no_allows_inverse_query_of_the_changed_target(self):
        rewrite = rewrite_counterfactual(accepted("Alpha before Beta"))
        update = update_answer(
            original_answer="no",
            question="Did Alpha happen after Beta?",
            answer_type=AnswerType.YES_NO,
            rewrite=rewrite,
        )
        self.assertEqual((update.status, update.value), (AnswerStatus.KNOWN, "yes"))

    def test_numeric_and_free_generation_never_copy_unknown_gold(self):
        rewrite = rewrite_counterfactual(accepted("Alpha before Beta"))
        for answer_type in (AnswerType.NUMERIC, AnswerType.FREE_GENERATION):
            with self.subTest(answer_type=answer_type):
                update = update_answer(
                    original_answer="42",
                    question="What is the answer?",
                    answer_type=answer_type,
                    rewrite=rewrite,
                )
                self.assertIs(update.status, AnswerStatus.UNKNOWN)
                self.assertIsNone(update.value)


if __name__ == "__main__":
    unittest.main()
