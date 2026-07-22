import hashlib
from pathlib import Path
import tempfile
import unittest

from kairos.events import extract_explicit_relation
from kairos.ids import assign_split, make_stable_id
from kairos.io import (
    ConstructionFunnel,
    ConstructionOutcome,
    compute_funnel,
    read_examples,
    write_examples,
)
from kairos.schema import AnswerType, TemporalExample


def example():
    text = "Alpha before Beta"
    extraction = extract_explicit_relation(text).extraction
    source_id = make_stable_id("source", {"dataset": "fixture", "id": "1"})
    return TemporalExample(
        record_id=make_stable_id("record", {"source_id": source_id, "variant": "original"}),
        source_id=source_id,
        dataset="fixture",
        split=assign_split(source_id, "train"),
        revision="fixture-v1",
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        question="Which happened first?",
        answers=("Alpha",),
        answer_type=AnswerType.EXTRACTIVE,
        events=(extraction.event_a, extraction.event_b),
        relations=(extraction.relation,),
    )


class JsonlTests(unittest.TestCase):
    def test_round_trip_is_canonical_and_stable(self):
        original = example()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.jsonl"
            second = Path(directory) / "second.jsonl"
            write_examples(first, [original])
            loaded = read_examples(first)
            write_examples(second, loaded)
            self.assertEqual(loaded, [original])
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).hexdigest(),
                hashlib.sha256(second.read_bytes()).hexdigest(),
            )

    def test_reader_rejects_blank_and_invalid_records_with_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line at 1"):
                read_examples(path)
            path.write_text('{"record_id":"only"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 1"):
                read_examples(path)


class FunnelTests(unittest.TestCase):
    def test_computes_monotonic_funnel(self):
        outcomes = [
            ConstructionOutcome(),
            ConstructionOutcome(True),
            ConstructionOutcome(True, True, True),
            ConstructionOutcome(True, True, True, True, True),
        ]
        self.assertEqual(compute_funnel(outcomes), ConstructionFunnel(4, 3, 2, 2, 1, 1))

    def test_rejects_non_prefix_outcome_and_non_monotonic_counts(self):
        with self.assertRaises(ValueError):
            ConstructionOutcome(event_extraction_success=True)
        with self.assertRaises(ValueError):
            ConstructionFunnel(1, 2, 0, 0, 0, 0)

if __name__ == "__main__":
    unittest.main()
