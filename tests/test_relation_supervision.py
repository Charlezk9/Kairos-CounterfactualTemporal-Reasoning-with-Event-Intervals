from dataclasses import fields, replace
import json
import unittest

from kairos.ids import canonical_json, make_stable_id
from kairos.relation_supervision import (
    CONSTRUCTION_VERSION,
    SCHEMA_VERSION,
    CounterfactualAnswerStatus,
    RelationOnlyConstructionResult,
    RelationOnlyPair,
    RelationOnlyTerminal,
    RelationSupervisionError,
    construct_gsm8k_relation_only,
)
from kairos.schema import (
    AnswerType,
    CharSpan,
    EventMention,
    Relation,
    RejectionReason,
    SplitAssignment,
    TemporalExample,
)


def _example(text="Alpha happened before Beta happened."):
    return TemporalExample(
        record_id="record:gsm8k-synthetic",
        source_id="source:gsm8k-synthetic",
        dataset="gsm8k",
        split=SplitAssignment(official="train", internal=None),
        revision="synthetic-revision",
        source_sha256="a" * 64,
        text=text,
        question=text,
        answers=("42",),
        answer_type=AnswerType.NUMERIC,
    )


class RelationOnlyConstructionTests(unittest.TestCase):
    def test_public_surface_and_terminal_values_are_exact(self):
        self.assertEqual(SCHEMA_VERSION, "gsm8k-relation-only-pair-v1")
        self.assertEqual(CONSTRUCTION_VERSION, "explicit-marker-relation-only-v1")
        self.assertEqual(
            [item.value for item in RelationOnlyTerminal],
            ["no_marker", "extraction_rejected", "rewrite_rejected", "retained"],
        )
        self.assertEqual(
            [field.name for field in fields(RelationOnlyConstructionResult)],
            ["input_record_id", "terminal", "rejection_reason", "pair"],
        )

    def test_retained_pair_rewrites_query_and_withholds_cf_answer(self):
        source = _example()
        first = construct_gsm8k_relation_only(source)
        second = construct_gsm8k_relation_only(source)
        self.assertEqual(first, second)
        self.assertIs(first.terminal, RelationOnlyTerminal.RETAINED)
        self.assertIsNone(first.rejection_reason)
        pair = first.pair
        self.assertEqual(pair.original_query, source.text)
        self.assertEqual(pair.counterfactual_query, "Alpha happened after Beta happened.")
        self.assertEqual(pair.original_answer, "42")
        self.assertIs(
            pair.counterfactual_answer_status, CounterfactualAnswerStatus.UNAVAILABLE
        )
        self.assertIs(pair.original_relation.relation, Relation.PRECEDES)
        self.assertIs(pair.counterfactual_relation.relation, Relation.FOLLOWS)
        self.assertNotIn("counterfactual_answer", pair.to_dict())
        self.assertEqual(
            set(pair.to_dict()),
            {
                "schema_version", "pair_id", "original_record_id",
                "counterfactual_record_id", "source_id", "dataset", "split",
                "revision", "source_sha256", "original_query",
                "counterfactual_query", "original_answer", "answer_type",
                "template_id", "original_events", "counterfactual_events",
                "original_relation", "counterfactual_relation",
                "counterfactual_answer_status",
            },
        )

    def test_identity_payloads_are_literal(self):
        source = _example()
        pair = construct_gsm8k_relation_only(source).pair
        expected_pair = make_stable_id(
            "relation-supervision-pair",
            {
                "version": CONSTRUCTION_VERSION,
                "source_id": source.source_id,
                "original_record_id": source.record_id,
                "template_id": "marker:before->after",
            },
        )
        expected_cf = make_stable_id(
            "record",
            {
                "version": CONSTRUCTION_VERSION,
                "source_id": source.source_id,
                "original_record_id": source.record_id,
                "pair_id": expected_pair,
                "template_id": "marker:before->after",
                "variant": "counterfactual-relation-only",
            },
        )
        self.assertEqual(pair.pair_id, expected_pair)
        self.assertEqual(pair.counterfactual_record_id, expected_cf)

    def test_terminal_classification_is_fail_closed(self):
        cases = (
            ("No temporal marker.", RelationOnlyTerminal.NO_MARKER, RejectionReason.NO_MARKER),
            ("Alpha while Beta.", RelationOnlyTerminal.EXTRACTION_REJECTED, RejectionReason.UNSUPPORTED_MARKER),
            ("Alpha before Beta, then Gamma.", RelationOnlyTerminal.EXTRACTION_REJECTED, RejectionReason.MULTIPLE_MARKERS),
            ("Alpha prior to Beta.", RelationOnlyTerminal.REWRITE_REJECTED, RejectionReason.UNSUPPORTED_REWRITE),
        )
        for text, terminal, reason in cases:
            with self.subTest(text=text):
                result = construct_gsm8k_relation_only(_example(text))
                self.assertIs(result.terminal, terminal)
                self.assertIs(result.rejection_reason, reason)
                self.assertIsNone(result.pair)

    def test_input_preconditions_reject_semantic_reuse(self):
        source = _example()
        invalid = (
            replace(source, dataset="other"),
            replace(source, answer_type=AnswerType.FREE_GENERATION),
            replace(source, question="separate question"),
            replace(source, answers=("42", "43")),
            replace(source, events=(EventMention("e1", "Alpha", CharSpan(0, 5)),)),
            replace(source, counterfactual_pair_id="existing"),
        )
        with self.assertRaises(TypeError):
            construct_gsm8k_relation_only("not an example")
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(RelationSupervisionError):
                    construct_gsm8k_relation_only(value)


class RelationOnlySerializationTests(unittest.TestCase):
    def setUp(self):
        self.pair = construct_gsm8k_relation_only(_example()).pair
        self.value = self.pair.to_dict()

    def test_round_trip_is_canonical_and_exact(self):
        payload = canonical_json(self.value)
        replay = RelationOnlyPair.from_dict(json.loads(payload))
        self.assertEqual(replay, self.pair)
        self.assertEqual(canonical_json(replay.to_dict()), payload)

    def test_missing_extra_nested_and_enum_mutations_fail(self):
        mutations = []
        missing = dict(self.value)
        missing.pop("template_id")
        mutations.append(missing)
        extra = dict(self.value)
        extra["counterfactual_answer"] = "42"
        mutations.append(extra)
        nested = json.loads(canonical_json(self.value))
        nested["original_events"][0]["char_span"]["extra"] = 1
        mutations.append(nested)
        status = dict(self.value)
        status["counterfactual_answer_status"] = "known"
        mutations.append(status)
        schema = dict(self.value)
        schema["schema_version"] = "future"
        mutations.append(schema)
        source_hash = dict(self.value)
        source_hash["source_sha256"] = "A" * 64
        mutations.append(source_hash)
        for value in mutations:
            with self.subTest(keys=set(value)):
                with self.assertRaises(RelationSupervisionError):
                    RelationOnlyPair.from_dict(value)

    def test_recomputed_stale_identity_and_relation_fail_replay(self):
        stale = dict(self.value)
        stale["pair_id"] = "relation-supervision-pair:" + "f" * 64
        with self.assertRaisesRegex(RelationSupervisionError, "replay"):
            RelationOnlyPair.from_dict(stale)

        relation = json.loads(canonical_json(self.value))
        relation["counterfactual_relation"]["relation"] = "precedes"
        with self.assertRaisesRegex(RelationSupervisionError, "invert"):
            RelationOnlyPair.from_dict(relation)


if __name__ == "__main__":
    unittest.main()
