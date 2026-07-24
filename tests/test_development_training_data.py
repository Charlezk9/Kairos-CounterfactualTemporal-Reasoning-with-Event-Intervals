import hashlib
import json
import unittest

from kairos.ids import canonical_json
from kairos import development_training_data as data


def _records():
    result = []
    for index in range(370):
        split = "train" if index < 334 else "dev"
        pair_id = f"pair:{index:03d}"
        value = {
            "pair_id": pair_id,
            "source_id": f"source:{index:03d}",
            "split": split,
        }
        raw = canonical_json(value).encode("utf-8") + b"\n"
        result.append(data._Record(raw, pair_id, value["source_id"], split))
    return tuple(result)


def _invalid():
    return tuple((f"audit:{index}", f"pair:{index:03d}") for index in range(4))


class DevelopmentTrainingPartitionTests(unittest.TestCase):
    def test_frozen_filter_and_partition_are_ordered_and_disjoint(self):
        derived = data._derive(_records(), _invalid())
        self.assertEqual(len(derived.all_records), 366)
        self.assertEqual(len(derived.train_records), 330)
        self.assertEqual(len(derived.dev_records), 36)
        self.assertEqual(derived.all_records[0].pair_id, "pair:004")
        self.assertEqual(derived.train_records[-1].pair_id, "pair:333")
        self.assertEqual(derived.dev_records[0].pair_id, "pair:334")
        partition = json.loads(derived.partition_payload)
        self.assertFalse(partition["paper_metric_eligible"])
        self.assertFalse(partition["counterfactual_answer_available"])
        self.assertEqual(partition["partitions"]["train"]["count"], 330)
        self.assertEqual(partition["partitions"]["internal-dev"]["count"], 36)
        expected_hash = hashlib.sha256(
            canonical_json(
                [record.pair_id for record in derived.train_records]
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            partition["partitions"]["train"]["ordered_pair_ids_sha256"],
            expected_hash,
        )

    def test_missing_duplicate_or_unknown_exclusions_fail_closed(self):
        records = _records()
        with self.assertRaisesRegex(
            data.DevelopmentTrainingDataError, "unique source pairs"
        ):
            data._derive(records, (*_invalid()[:3], ("audit:x", "pair:000")))
        with self.assertRaisesRegex(
            data.DevelopmentTrainingDataError, "unique source pairs"
        ):
            data._derive(records, (*_invalid()[:3], ("audit:x", "pair:999")))

    def test_source_identity_and_partition_counts_fail_closed(self):
        records = list(_records())
        original = records[-1]
        records[-1] = data._Record(
            original.raw,
            original.pair_id,
            records[0].source_id,
            original.internal_split,
        )
        with self.assertRaisesRegex(
            data.DevelopmentTrainingDataError, "identities are not unique"
        ):
            data._derive(records, _invalid())

        with self.assertRaisesRegex(
            data.DevelopmentTrainingDataError, "partition counts differ"
        ):
            data._derive(_records()[:-1], _invalid())


if __name__ == "__main__":
    unittest.main()
