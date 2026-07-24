import json
import unittest

from kairos.ids import canonical_json, make_stable_id
from kairos.relation_audit_results import (
    ADJUDICATION_SCHEMA_VERSION,
    RelationAuditResultError,
    evaluate_audit_submissions,
)
from kairos.relation_human_audit import REVIEW_SCHEMA_VERSION, SAMPLE_SIZE


FIELDS = (
    "event_spans_valid",
    "original_relation_valid",
    "counterfactual_relation_valid",
    "rewrite_grammatical",
    "non_target_content_preserved",
)


def _ids():
    return tuple(
        make_stable_id("audit-item", {"result-fixture": index})
        for index in range(SAMPLE_SIZE)
    )


def _review_payload(item_ids, slot, values, mutation=None):
    rows = []
    for index, (item_id, valid) in enumerate(zip(item_ids, values)):
        row = {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "audit_item_id": item_id,
            "reviewer_slot": slot,
            **{field: valid for field in FIELDS},
            "overall_valid": valid,
            "notes": None,
        }
        if mutation is not None:
            mutation(index, row)
        rows.append(canonical_json(row).encode("utf-8") + b"\n")
    return b"".join(rows)


def _adjudication_payload(item_ids, values, mutation=None):
    rows = []
    for index, (item_id, valid) in enumerate(zip(item_ids, values)):
        row = {
            "schema_version": ADJUDICATION_SCHEMA_VERSION,
            "audit_item_id": item_id,
            "overall_valid": valid,
            "notes": None,
        }
        if mutation is not None:
            mutation(index, row)
        rows.append(canonical_json(row).encode("utf-8") + b"\n")
    return b"".join(rows)


def _evaluate(a_values, b_values, adjudicated, **payload_overrides):
    item_ids = _ids()
    values = {
        "expected_item_ids": item_ids,
        "packet_manifest_sha256": "a" * 64,
        "audit_items_sha256": "b" * 64,
        "reviewer_a_payload": _review_payload(item_ids, "A", a_values),
        "reviewer_b_payload": _review_payload(item_ids, "B", b_values),
        "adjudication_payload": _adjudication_payload(item_ids, adjudicated),
    }
    values.update(payload_overrides)
    return evaluate_audit_submissions(**values)


class RelationAuditResultTests(unittest.TestCase):
    def test_threshold_boundary_passes_with_locked_hashes(self):
        a_values = tuple(index < 190 for index in range(SAMPLE_SIZE))
        b_values = tuple(index < 189 or index == 199 for index in range(SAMPLE_SIZE))
        adjudicated = tuple(index < 190 for index in range(SAMPLE_SIZE))
        result = _evaluate(a_values, b_values, adjudicated)
        self.assertTrue(result.training_gate_passed)
        self.assertEqual(result.adjudicated_valid_count, 190)
        self.assertEqual(result.adjudicated_validity, 0.95)
        self.assertAlmostEqual(result.observed_agreement, 0.99)
        self.assertAlmostEqual(result.expected_agreement, 0.905)
        self.assertAlmostEqual(result.cohen_kappa, 0.894736842105263)
        self.assertEqual(
            result.confusion,
            {
                "both_valid": 189,
                "a_valid_b_invalid": 1,
                "a_invalid_b_valid": 1,
                "both_invalid": 9,
            },
        )
        self.assertEqual(result.gate_failures, ())
        self.assertEqual(result.to_dict()["status"], "PASSED")
        self.assertEqual(len(result.sha256), 64)
        with self.assertRaises(TypeError):
            result.confusion["both_valid"] = 0
        with self.assertRaises(TypeError):
            result.field_agreement["overall_valid"]["agreement_count"] = 0

    def test_undefined_kappa_and_low_validity_block(self):
        all_true = (True,) * SAMPLE_SIZE
        undefined = _evaluate(all_true, all_true, all_true)
        self.assertIsNone(undefined.cohen_kappa)
        self.assertFalse(undefined.training_gate_passed)
        self.assertEqual(undefined.gate_failures, ("cohen-kappa-unavailable",))

        mixed = tuple(index < 180 for index in range(SAMPLE_SIZE))
        low_validity = _evaluate(mixed, mixed, mixed)
        self.assertEqual(low_validity.cohen_kappa, 1.0)
        self.assertEqual(low_validity.adjudicated_validity, 0.9)
        self.assertEqual(
            low_validity.gate_failures,
            ("adjudicated-validity-below-threshold",),
        )

    def test_kappa_threshold_is_inclusive_and_finite_low_kappa_blocks(self):
        a_values = tuple(index < 100 for index in range(SAMPLE_SIZE))
        b_values = tuple(index < 90 or 100 <= index < 110 for index in range(SAMPLE_SIZE))
        adjudicated = tuple(index < 110 for index in range(SAMPLE_SIZE))
        boundary = _evaluate(a_values, b_values, adjudicated)
        self.assertAlmostEqual(boundary.cohen_kappa, 0.8)
        self.assertNotIn("cohen-kappa-below-threshold", boundary.gate_failures)
        self.assertEqual(
            boundary.gate_failures,
            ("adjudicated-validity-below-threshold",),
        )

        opposite = tuple(not value for value in a_values)
        low_kappa = _evaluate(
            a_values,
            opposite,
            (True,) * SAMPLE_SIZE,
        )
        self.assertEqual(low_kappa.cohen_kappa, -1.0)
        self.assertEqual(low_kappa.adjudicated_validity, 1.0)
        self.assertEqual(
            low_kappa.gate_failures,
            ("cohen-kappa-below-threshold",),
        )

    def test_missing_boolean_overall_and_adjudication_changes_are_rejected(self):
        item_ids = _ids()
        values = tuple(index < 190 for index in range(SAMPLE_SIZE))
        bad_null = _review_payload(
            item_ids,
            "A",
            values,
            lambda index, row: row.update({"event_spans_valid": None})
            if index == 0
            else None,
        )
        with self.assertRaisesRegex(RelationAuditResultError, "not Boolean"):
            _evaluate(values, values, values, reviewer_a_payload=bad_null)

        bad_overall = _review_payload(
            item_ids,
            "A",
            values,
            lambda index, row: row.update({"overall_valid": not row["overall_valid"]})
            if index == 0
            else None,
        )
        with self.assertRaisesRegex(RelationAuditResultError, "overall validity"):
            _evaluate(values, values, values, reviewer_a_payload=bad_overall)

        changed = _adjudication_payload(
            item_ids,
            values,
            lambda index, row: row.update({"overall_valid": not row["overall_valid"]})
            if index == 0
            else None,
        )
        with self.assertRaisesRegex(RelationAuditResultError, "reviewer agreement"):
            _evaluate(values, values, values, adjudication_payload=changed)

    def test_order_schema_duplicate_and_hash_bindings_are_strict(self):
        item_ids = _ids()
        values = (True,) * SAMPLE_SIZE
        reordered = _review_payload(
            (item_ids[1], item_ids[0], *item_ids[2:]), "A", values
        )
        with self.assertRaisesRegex(RelationAuditResultError, "identity differs"):
            _evaluate(values, values, values, reviewer_a_payload=reordered)

        extra = _review_payload(
            item_ids,
            "A",
            values,
            lambda index, row: row.update({"extra": True}) if index == 0 else None,
        )
        with self.assertRaisesRegex(RelationAuditResultError, "keys differ"):
            _evaluate(values, values, values, reviewer_a_payload=extra)

        first = json.loads(
            _review_payload(item_ids, "A", values).splitlines()[0]
        )
        duplicate = canonical_json(first)[:-1] + ',"notes":null}'
        normal_lines = _review_payload(item_ids, "A", values).splitlines(keepends=True)
        duplicate_payload = duplicate.encode("utf-8") + b"\n" + b"".join(normal_lines[1:])
        with self.assertRaisesRegex(RelationAuditResultError, "duplicate JSON keys"):
            _evaluate(values, values, values, reviewer_a_payload=duplicate_payload)

        with self.assertRaisesRegex(RelationAuditResultError, "packet manifest"):
            _evaluate(values, values, values, packet_manifest_sha256="A" * 64)


if __name__ == "__main__":
    unittest.main()
