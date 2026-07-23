import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kairos.construction import ConstructionTerminal
import kairos.gsm8k_construction as driver
from kairos.ids import canonical_json, make_stable_id
from kairos.schema import AnswerType, SplitAssignment, TemporalExample


def example(index, *, text="Alpha before Beta", question="Which happened first?"):
    source_id = make_stable_id("source", {"driver-fixture": index})
    return TemporalExample(
        record_id=make_stable_id("record", {"source_id": source_id}),
        source_id=source_id,
        dataset="gsm8k",
        split=SplitAssignment(official="train", internal=None),
        revision=driver.REVISION,
        source_sha256=f"{index + 1:064x}",
        text=text,
        question=question,
        answers=("Alpha",),
        answer_type=AnswerType.EXTRACTIVE,
    )


class Gsm8kConstructionDriverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir="/data0/hk_data/kairos-zx/.tmp",
            prefix="d014-driver.",
        )
        self.path = Path(self.temporary.name) / "examples.jsonl"

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, values):
        self.path.write_bytes(
            b"".join(canonical_json(value).encode() + b"\n" for value in values)
        )

    def test_record_stream_runs_real_construction_and_audit_in_order(self):
        values = [example(0), example(1, text="No temporal relation")]
        self.write(values)
        records = list(driver._record_stream(self.path))
        self.assertEqual([record.input_order for record in records], [0, 1])
        self.assertEqual([record.input for record in records], values)
        self.assertEqual(
            [record.terminal for record in records],
            [ConstructionTerminal.RETAINED, ConstructionTerminal.NO_MARKER],
        )

    def test_real_gsm8k_shape_hits_frozen_alias_gate(self):
        value = example(
            0,
            text="Alpha before Beta",
            question="Alpha before Beta",
        )
        self.write([value])
        record = next(driver._record_stream(self.path))
        self.assertIs(
            record.terminal,
            ConstructionTerminal.TEXT_QUESTION_ALIAS_UNSUPPORTED,
        )
        self.assertFalse(record.outcome.final_retained)

    def test_source_rejects_noncanonical_duplicate_blank_and_no_lf(self):
        invalid = (
            b'{"x":1, "x":2}\n',
            b"\n",
            canonical_json(example(0)).encode(),
            b"[]\n",
        )
        for payload in invalid:
            with self.subTest(payload=payload[:16]):
                self.path.write_bytes(payload)
                with self.assertRaisesRegex(
                    driver.Gsm8kConstructionError,
                    "^GSM8K construction input is invalid$",
                ):
                    list(driver._record_stream(self.path))

    def test_prepare_has_fixed_split_and_passes_lazy_records(self):
        value = example(0)
        self.write([value])
        expected = {"observer_state": "STRUCTURALLY_VERIFIED", "manifest": {}}

        def consume(records, *, official_split, execution_commit):
            materialized = list(records)
            self.assertEqual(len(materialized), 1)
            self.assertEqual(materialized[0].input, value)
            self.assertEqual(official_split, "train")
            self.assertEqual(execution_commit, "a" * 40)
            return expected

        with patch.dict(driver._SOURCE_PATHS, {"train": self.path}, clear=True):
            with patch.object(driver, "publish", side_effect=consume):
                self.assertEqual(
                    driver.prepare(
                        official_split="train", execution_commit="a" * 40
                    ),
                    expected,
                )
            with self.assertRaisesRegex(
                driver.Gsm8kConstructionError,
                "^official split must be train or test$",
            ):
                driver.prepare(official_split="test", execution_commit="a" * 40)

    def test_cli_redacts_failures_and_emits_only_summary(self):
        result = {"observer_state": "STRUCTURALLY_VERIFIED", "manifest": {}}
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(driver, "verify", return_value=result):
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertEqual(driver.main(["verify", "--split", "train"]), 0)
        self.assertEqual(stdout.getvalue(), canonical_json(result) + "\n")
        self.assertEqual(stderr.getvalue(), "")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(
            driver,
            "prepare",
            side_effect=driver.Gsm8kConstructionError("secret source text"),
        ):
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertEqual(
                    driver.main(
                        [
                            "prepare", "--split", "train",
                            "--execution-commit", "a" * 40,
                        ]
                    ),
                    1,
                )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "GSM8K construction failed\n")


if __name__ == "__main__":
    unittest.main()
