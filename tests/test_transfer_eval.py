import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from kairos.ids import make_stable_id
from kairos import transfer_eval


TEST_TMP = Path("/data0/hk_data/kairos-zx/.tmp")


def _torque_question(
    passage_id,
    cluster_id,
    spans,
    indices,
    *,
    default=False,
    derived="",
):
    return {
        "answer": {
            "agreed_by": list(range(len(spans))),
            "indices": indices,
            "spans": spans,
        },
        "cluster_id": cluster_id,
        "derived_from_question": derived,
        "individual_answers": [],
        "is_default_question": default,
        "passageID": passage_id,
        "validated_by": 0,
    }


def _torque_data():
    return {
        "passage-1": {
            "events": {
                "answer": {"indices": ["0"], "spans": ["Alpha"]},
                "passageID": "passage-1",
            },
            "passage": "Alpha happened before Beta.",
            "question_answer_pairs": {
                "What happened first?": _torque_question(
                    "passage-1", "1", ["Alpha", "Alpha"], ["0", "1"], default=True
                ),
                "What was simultaneous?": _torque_question(
                    "passage-1", "1", [], [], derived="What happened first?"
                ),
            },
        },
        "passage-2": {
            "events": {
                "answer": {"indices": ["0"], "spans": ["A"]},
                "passageID": "passage-2",
            },
            "passage": "A, B, and C occurred.",
            "question_answer_pairs": {
                "Which events occurred?": _torque_question(
                    "passage-2", "1", ["A", "B", "C"], ["0", "1", "2"]
                )
            },
        },
    }


def _timeqa_records():
    return [
        {
            "context": "A context.",
            "idx": "hard-1",
            "paragraphs": [{"title": "Title", "text": "Body"}],
            "question": "What is the answer?",
            "targets": ["The Answer!", "alternative"],
        },
        {
            "context": "Another context.",
            "idx": "hard-2",
            "paragraphs": [],
            "question": "Which tokens?",
            "targets": ["alpha beta"],
        },
    ]


def _timeqa_bytes(records):
    return b"".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for record in records
    )


class SyntheticFiles(unittest.TestCase):
    def setUp(self):
        TEST_TMP.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="kairos-transfer-eval-test-", dir=TEST_TMP
        )
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, payload):
        path = self.root / name
        path.write_bytes(payload)
        return path, hashlib.sha256(payload).hexdigest()

    def test_torque_loader_preserves_empty_and_duplicate_span_answers(self):
        payload = json.dumps(
            _torque_data(), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        path, digest = self.write("dev.json", payload)
        examples = transfer_eval._load_torque_dev_file(path, digest)

        self.assertEqual(len(examples), 3)
        self.assertEqual(examples[0].gold_spans, ("Alpha", "Alpha"))
        self.assertEqual(examples[1].gold_spans, ())
        self.assertEqual(examples[0].passage_id, "passage-1")
        self.assertEqual(
            examples[0].record_id,
            make_stable_id(
                "torque-example",
                {
                    "revision": transfer_eval.TORQUE_REVISION,
                    "passage_id": "passage-1",
                    "question": "What happened first?",
                },
            ),
        )

    def test_torque_loader_rejects_hash_duplicate_keys_and_nonfinite(self):
        valid = json.dumps(_torque_data(), separators=(",", ":")).encode()
        path, digest = self.write("dev.json", valid)
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "SHA256"):
            transfer_eval._load_torque_dev_file(path, "0" * 64)

        duplicate = valid.replace(
            b'"passage":"Alpha happened before Beta."',
            b'"passage":"x","passage":"Alpha happened before Beta."',
        )
        path, digest = self.write("duplicate.json", duplicate)
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "duplicate"):
            transfer_eval._load_torque_dev_file(path, digest)

        nonfinite = valid.replace(b'"validated_by":0', b'"validated_by":NaN', 1)
        path, digest = self.write("nonfinite.json", nonfinite)
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "non-finite"):
            transfer_eval._load_torque_dev_file(path, digest)

    def test_torque_loader_rejects_schema_and_answer_invariant_changes(self):
        cases = []
        extra = _torque_data()
        extra["passage-1"]["extra"] = True
        cases.append((extra, "invalid TORQUE passage record keys"))

        wrong_passage = _torque_data()
        wrong_passage["passage-1"]["question_answer_pairs"][
            "What happened first?"
        ]["passageID"] = "passage-2"
        cases.append((wrong_passage, "passageID differs"))

        mismatched = _torque_data()
        mismatched["passage-1"]["question_answer_pairs"][
            "What happened first?"
        ]["answer"]["indices"] = ["0"]
        cases.append((mismatched, "collection lengths differ"))

        duplicated_index = _torque_data()
        duplicated_index["passage-1"]["question_answer_pairs"][
            "What happened first?"
        ]["answer"]["indices"] = ["0", "0"]
        cases.append((duplicated_index, "indices are duplicated"))

        for number, (value, message) in enumerate(cases):
            with self.subTest(message=message):
                payload = json.dumps(value, separators=(",", ":")).encode()
                path, digest = self.write(f"invalid-{number}.json", payload)
                with self.assertRaisesRegex(transfer_eval.TransferEvalError, message):
                    transfer_eval._load_torque_dev_file(path, digest)

    def test_timeqa_loader_is_strict_and_stable(self):
        payload = _timeqa_bytes(_timeqa_records())
        path, digest = self.write("hard.json", payload)
        examples = transfer_eval._load_timeqa_hard_file(path, digest)

        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[0].idx, "hard-1")
        self.assertEqual(examples[0].paragraphs[0].title, "Title")
        self.assertEqual(examples[1].paragraphs, ())
        self.assertEqual(examples[0].targets, ("The Answer!", "alternative"))

    def test_timeqa_loader_rejects_delimiter_duplicate_idx_schema_and_hash(self):
        records = _timeqa_records()
        payload = _timeqa_bytes(records)
        path, unused = self.write("hard.json", payload)
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "SHA256"):
            transfer_eval._load_timeqa_hard_file(path, "0" * 64)

        path, digest = self.write("no-lf.json", payload[:-1])
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "LF-delimited"):
            transfer_eval._load_timeqa_hard_file(path, digest)

        duplicate = copy.deepcopy(records)
        duplicate[1]["idx"] = duplicate[0]["idx"]
        path, digest = self.write("duplicate-idx.json", _timeqa_bytes(duplicate))
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "idx is duplicated"):
            transfer_eval._load_timeqa_hard_file(path, digest)

        extra = copy.deepcopy(records)
        extra[0]["extra"] = True
        path, digest = self.write("extra.json", _timeqa_bytes(extra))
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "invalid TimeQA"):
            transfer_eval._load_timeqa_hard_file(path, digest)

        duplicate_key = payload.replace(
            b'"idx":"hard-1"', b'"idx":"wrong","idx":"hard-1"', 1
        )
        path, digest = self.write("duplicate-key.json", duplicate_key)
        with self.assertRaisesRegex(transfer_eval.TransferEvalError, "duplicate"):
            transfer_eval._load_timeqa_hard_file(path, digest)


class TorqueMetricTests(unittest.TestCase):
    @staticmethod
    def examples():
        payload = json.dumps(_torque_data(), separators=(",", ":")).encode()
        return transfer_eval._parse_torque(payload)

    def test_set_metrics_group_by_passage_and_emit_both_consistency_rules(self):
        examples = self.examples()
        predictions = {
            examples[0].record_id: [" alpha "],
            examples[1].record_id: [],
            examples[2].record_id: ["a", "B"],
        }
        metrics = transfer_eval.evaluate_torque(examples, predictions)

        self.assertEqual(metrics["question_count"], 3)
        self.assertEqual(metrics["cluster_count"], 2)
        self.assertAlmostEqual(metrics["question_exact_match"], 200 / 3)
        self.assertAlmostEqual(metrics["question_set_f1"], 280 / 3)
        self.assertEqual(metrics["cluster_exact_consistency"], 50.0)
        self.assertEqual(metrics["cluster_f1_80_consistency"], 100.0)

    def test_torque_normalizer_preserves_punctuation_and_deduplicates_sets(self):
        example = transfer_eval.TorqueExample(
            record_id="r",
            passage_id="p",
            cluster_id="c",
            question="q",
            passage="text",
            gold_spans=("A!", "A!"),
            gold_indices=("0", "1"),
            is_default_question=True,
            derived_from_question="",
        )
        duplicate = transfer_eval.evaluate_torque([example], {"r": ["a!", "A!"]})
        punctuation = transfer_eval.evaluate_torque([example], {"r": ["a"]})
        self.assertEqual(duplicate["question_set_f1"], 100.0)
        self.assertEqual(punctuation["question_set_f1"], 0.0)

    def test_empty_gold_and_prediction_are_perfect(self):
        example = self.examples()[1]
        metrics = transfer_eval.evaluate_torque([example], {example.record_id: []})
        self.assertEqual(metrics["question_exact_match"], 100.0)
        self.assertEqual(metrics["question_set_f1"], 100.0)

    def test_prediction_contract_rejects_missing_extra_string_and_blank(self):
        examples = self.examples()
        base = {example.record_id: [] for example in examples}
        cases = [
            ({key: value for key, value in list(base.items())[1:]}, "key mismatch"),
            ({**base, "extra": []}, "key mismatch"),
            ({**base, examples[0].record_id: "not-a-list"}, "non-string sequence"),
            ({**base, examples[0].record_id: ["  "]}, "empty answer"),
        ]
        for predictions, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(transfer_eval.TransferEvalError, message):
                    transfer_eval.evaluate_torque(examples, predictions)


class TimeQaMetricTests(unittest.TestCase):
    @staticmethod
    def examples():
        return transfer_eval._parse_timeqa(_timeqa_bytes(_timeqa_records()))

    def test_official_normalization_semantics(self):
        self.assertEqual(
            transfer_eval.normalize_timeqa_answer(" The, ANSWER!  "), "answer"
        )
        self.assertEqual(
            transfer_eval.normalize_timeqa_answer("red-fox"), "redfox"
        )
        self.assertEqual(transfer_eval.timeqa_f1("", ""), 1.0)
        self.assertEqual(transfer_eval.timeqa_f1("alpha", "beta"), 0.0)

    def test_multi_target_exact_and_token_f1(self):
        examples = self.examples()
        metrics = transfer_eval.evaluate_timeqa(
            examples,
            {
                examples[0].record_id: "answer",
                examples[1].record_id: "alpha",
            },
        )
        self.assertEqual(metrics["total"], 2)
        self.assertEqual(metrics["exact_match"], 50.0)
        self.assertAlmostEqual(metrics["token_f1"], 100 * (1 + 2 / 3) / 2)

    def test_prediction_contract_rejects_missing_extra_and_non_string(self):
        examples = self.examples()
        valid = {example.record_id: "" for example in examples}
        cases = [
            ({examples[0].record_id: ""}, "key mismatch"),
            ({**valid, "extra": ""}, "key mismatch"),
            ({**valid, examples[0].record_id: []}, "must be strings"),
        ]
        for predictions, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(transfer_eval.TransferEvalError, message):
                    transfer_eval.evaluate_timeqa(examples, predictions)


if __name__ == "__main__":
    unittest.main()
