import copy
import hashlib
import unittest

from kairos.ids import assign_split, canonical_json, make_stable_id
from kairos.schema import (
    AnswerStatus,
    AnswerUpdate,
    CharSpan,
    EventMention,
    InternalSplit,
    Relation,
    RelationAnnotation,
    TemporalExample,
)


def valid_payload():
    return {
        "record_id": "record-1",
        "source_id": "source-1",
        "dataset": "fixture",
        "split": {"official": "validation", "internal": None},
        "revision": "v1",
        "source_sha256": "0" * 64,
        "text": "A before B",
        "question": "Which happened first?",
        "answers": ["A"],
        "answer_type": "extractive",
        "events": [
            {"event_id": "e1", "text": "A", "char_span": {"start": 0, "end": 1}},
            {"event_id": "e2", "text": "B", "char_span": {"start": 9, "end": 10}},
        ],
        "relations": [
            {
                "source_event_id": "e1",
                "target_event_id": "e2",
                "relation": "precedes",
                "marker": "before",
                "provenance": "fixture",
            }
        ],
        "counterfactual_pair_id": None,
    }


class SchemaTests(unittest.TestCase):
    def test_relation_inverse_and_symmetry(self):
        expected = {
            Relation.PRECEDES: Relation.FOLLOWS,
            Relation.FOLLOWS: Relation.PRECEDES,
            Relation.OVERLAPS: Relation.OVERLAPS,
            Relation.CONTAINS: Relation.DURING,
            Relation.DURING: Relation.CONTAINS,
            Relation.UNKNOWN: Relation.UNKNOWN,
        }
        for relation, inverse in expected.items():
            with self.subTest(relation=relation):
                self.assertIs(relation.inverse(), inverse)
                self.assertIs(relation.inverse().inverse(), relation)
        self.assertTrue(Relation.OVERLAPS.symmetric)
        self.assertFalse(Relation.CONTAINS.symmetric)

    def test_relation_annotation_inverse_swaps_endpoints(self):
        annotation = RelationAnnotation("left", "right", Relation.CONTAINS, "during")
        inverse = annotation.inverse()
        self.assertEqual((inverse.source_event_id, inverse.target_event_id), ("right", "left"))
        self.assertIs(inverse.relation, Relation.DURING)

    def test_event_span_must_round_trip(self):
        source = "Alpha before Beta"
        EventMention("e1", "Alpha", CharSpan(0, 5)).validate_against(source)
        with self.assertRaisesRegex(ValueError, "does not match"):
            EventMention("e1", "Alphi", CharSpan(0, 5)).validate_against(source)

    def test_unknown_answer_cannot_copy_gold(self):
        with self.assertRaises(ValueError):
            AnswerUpdate(AnswerStatus.UNKNOWN, value="gold", reason="not provable")

    def test_strict_record_rejects_missing_and_invalid_relation(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            TemporalExample.from_dict({"record_id": "incomplete"})
        payload = valid_payload()
        payload["relations"][0]["relation"] = "not-a-relation"
        with self.assertRaises(ValueError):
            TemporalExample.from_dict(payload)

    def test_from_dict_rejects_nested_missing_and_extra_keys(self):
        mutations = (
            ("split extra", lambda value: value["split"].update({"extra": 1})),
            ("event missing", lambda value: value["events"][0].pop("text")),
            (
                "span extra",
                lambda value: value["events"][0]["char_span"].update({"extra": 1}),
            ),
            ("relation missing", lambda value: value["relations"][0].pop("marker")),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                payload = copy.deepcopy(valid_payload())
                mutate(payload)
                with self.assertRaisesRegex(ValueError, "missing=|extra="):
                    TemporalExample.from_dict(payload)

    def test_from_dict_requires_mappings_at_every_nested_level(self):
        mutations = (
            ("top", lambda value: [value]),
            ("split", lambda value: value.update({"split": []}) or value),
            ("event", lambda value: value["events"].__setitem__(0, []) or value),
            (
                "span",
                lambda value: value["events"][0].update({"char_span": []}) or value,
            ),
            (
                "relation",
                lambda value: value["relations"].__setitem__(0, []) or value,
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                payload = mutate(copy.deepcopy(valid_payload()))
                with self.assertRaisesRegex(TypeError, "must be a mapping"):
                    TemporalExample.from_dict(payload)

    def test_from_dict_rejects_string_answers_and_non_sequences(self):
        payload = valid_payload()
        payload["answers"] = "A"
        with self.assertRaisesRegex(TypeError, "non-string sequence"):
            TemporalExample.from_dict(payload)

        for field in ("events", "relations"):
            with self.subTest(field=field):
                payload = valid_payload()
                payload[field] = {"not": "a sequence"}
                with self.assertRaisesRegex(TypeError, "non-string sequence"):
                    TemporalExample.from_dict(payload)


class IdentityTests(unittest.TestCase):
    def test_canonical_json_and_id_are_order_independent(self):
        first = {"é": [1, True], "a": "x"}
        second = {"a": "x", "é": [1, True]}
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(make_stable_id("source", first), make_stable_id("source", second))

    def test_canonical_json_rejects_non_string_mapping_keys(self):
        invalid = ({1: "integer"}, {1: "integer", "1": "string"})
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "string keys"):
                    canonical_json(value)

    def test_split_uses_first_eight_sha256_bytes(self):
        source_id = "源:example-17"
        expected_bucket = int.from_bytes(
            hashlib.sha256(source_id.encode("utf-8")).digest()[:8], "big"
        ) % 10
        assignment = assign_split(source_id, "train")
        expected = InternalSplit.DEV if expected_bucket == 0 else InternalSplit.TRAIN
        self.assertIs(assignment.internal, expected)
        self.assertEqual(assign_split(source_id, "train"), assignment)

    def test_official_non_train_split_is_preserved(self):
        assignment = assign_split("source-1", "validation")
        self.assertEqual(assignment.official, "validation")
        self.assertIsNone(assignment.internal)


if __name__ == "__main__":
    unittest.main()
