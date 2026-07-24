from dataclasses import replace
import json
import unittest

from kairos.ids import canonical_json
from kairos.rule_graph import (
    COT_RUN_ID,
    DIRECT_RUN_ID,
    SELF_CONSISTENCY_RUN_ID,
    RuleGraphConfig,
    RuleGraphError,
    RuleGraphInputs,
    make_run_spec,
    rerank_example,
    run_rule_graph,
)
from kairos.transfer_eval import TorqueExample


def _example(passage, question, suffix="1"):
    return TorqueExample(
        record_id=f"torque-example:{suffix}",
        passage_id=f"passage-{suffix}",
        cluster_id="cluster-1",
        question=question,
        passage=passage,
        gold_spans=(),
        gold_indices=(),
        is_default_question=False,
        derived_from_question="",
    )


def _candidates(direct, cot, *samples):
    values = [tuple(direct), tuple(cot), *samples]
    while len(values) < 10:
        values.append(None)
    return tuple(values)


class RuleGraphPureTests(unittest.TestCase):
    def test_infix_before_selects_supported_cot_set(self):
        example = _example(
            "Alice arrived before Bob departed.",
            "What happened before Bob departed?",
        )
        result = rerank_example(
            example,
            _candidates(("Bob departed",), ("Alice arrived",)),
        )
        self.assertEqual(result.prediction, ["Alice arrived"])
        self.assertEqual(result.selected_source, "cot")
        self.assertIsNone(result.fallback_reason)
        self.assertEqual(result.trace["cue"], "before")
        self.assertGreaterEqual(result.trace["direct_edge_count"], 1)
        self.assertEqual(
            result.trace["candidates"][1]["span_statuses"], ["support"]
        )

    def test_prefix_after_and_reversed_question_form(self):
        passage = "After Alice arrived, Bob departed."
        first = rerank_example(
            _example(passage, "What happened after Alice arrived?"),
            _candidates(("Alice arrived",), ("Bob departed",)),
        )
        self.assertEqual(first.prediction, ["Bob departed"])

        second = rerank_example(
            _example(passage, "After Alice arrived, what happened?", "2"),
            _candidates(("Alice arrived",), ("Bob departed",)),
        )
        self.assertEqual(second.prediction, ["Bob departed"])

    def test_distinct_repeated_occurrences_are_not_silently_coreferred(self):
        example = _example(
            "A launched before B landed. B landed before C spoke.",
            "What happened before C spoke?",
        )
        result = rerank_example(
            example,
            _candidates(
                ("C spoke",),
                ("A launched",),
                ("B landed",),
            ),
        )
        self.assertEqual(result.prediction, ["B landed"])
        self.assertEqual(result.selected_source, "self-consistency-0")
        self.assertGreaterEqual(
            result.trace["closure_edge_count"], result.trace["direct_edge_count"]
        )

    def test_constraint_score_prefers_less_unknown_and_rejects_inverse(self):
        example = _example(
            "A arrived before B departed. B departed before C returned.",
            "What happened before B departed?",
        )
        result = rerank_example(
            example,
            _candidates(
                ("A arrived", "B departed"),
                ("A arrived",),
                ("C returned",),
            ),
        )
        self.assertEqual(result.prediction, ["A arrived"])
        self.assertEqual(result.selected_source, "cot")
        self.assertEqual(
            result.trace["candidates"][2]["span_statuses"],
            ["contradiction"],
        )

    def test_unsupported_and_no_evidence_fall_back_exact_direct(self):
        unsupported = rerank_example(
            _example(
                "Alice arrived before Bob departed.",
                "What started before Bob departed?",
            ),
            _candidates(("Alice arrived", "Alice arrived"), ("Bob departed",)),
        )
        self.assertEqual(
            unsupported.prediction, ["Alice arrived", "Alice arrived"]
        )
        self.assertEqual(unsupported.selected_source, "direct")
        self.assertEqual(
            unsupported.fallback_reason, "unsupported-question-semantics"
        )
        self.assertEqual(len(unsupported.trace["candidates"]), 10)
        self.assertEqual(
            unsupported.trace["candidates"][0]["span_statuses"],
            ["not-evaluated"],
        )

        no_graph = rerank_example(
            _example(
                "Alice greeted Bob and Carol waved.",
                "What happened before Bob?",
                "2",
            ),
            _candidates(("Alice",), ("Carol",)),
        )
        self.assertEqual(no_graph.prediction, ["Alice"])
        self.assertEqual(
            no_graph.fallback_reason, "no-positive-supported-candidate"
        )

    def test_invalid_sample_position_and_nonexact_surface_are_unknown(self):
        example = _example(
            "Alice arrived before Bob departed.",
            "What happened before Bob departed?",
        )
        result = rerank_example(
            example,
            _candidates(("missing surface",), ("Alice arrived",), None, ("Alice arrived",)),
        )
        self.assertEqual(result.prediction, ["Alice arrived"])
        self.assertFalse(result.trace["candidates"][2]["available"])
        self.assertEqual(
            result.trace["candidates"][0]["span_statuses"], ["unknown"]
        )


class RuleGraphContractTests(unittest.TestCase):
    def test_config_and_run_spec_are_exact_and_gold_blind(self):
        config = RuleGraphConfig()
        value = config.to_dict()
        self.assertFalse(value["gold_access"])
        self.assertEqual(value["generation"], "none")
        self.assertEqual(value["upstream"]["direct"]["run_id"], DIRECT_RUN_ID)
        self.assertEqual(value["upstream"]["cot"]["run_id"], COT_RUN_ID)
        self.assertEqual(
            value["upstream"]["self_consistency"]["run_id"],
            SELF_CONSISTENCY_RUN_ID,
        )
        self.assertEqual(len(value["candidate_order"]), 10)
        self.assertNotIn("gold_answer", canonical_json(value).casefold())
        with self.assertRaisesRegex(RuleGraphError, "upstream"):
            replace(config, direct_manifest_sha256="0" * 64)

        spec = make_run_spec(
            "a" * 40,
            "2026-07-24T10:00:00Z",
            "2026-07-24T10:00:01Z",
        )
        self.assertEqual(spec.method_name, "rule-graph")
        self.assertEqual(spec.gpu_ids, ())
        self.assertEqual(spec.cpu_threads, 2)
        self.assertEqual(spec.config, value)

    def test_run_emits_canonical_zero_token_trace_and_counts(self):
        first = _example(
            "Alice arrived before Bob departed.",
            "What happened before Bob departed?",
            "1",
        )
        second = _example(
            "Alice arrived before Bob departed.",
            "What started before Bob departed?",
            "2",
        )
        inputs = RuleGraphInputs(
            (first, second),
            {
                first.record_id: _candidates(("Bob departed",), ("Alice arrived",)),
                second.record_id: _candidates(("Alice arrived",), ("Bob departed",)),
            },
        )
        result = run_rule_graph(inputs)
        self.assertEqual(result.selected_source_counts, {"cot": 1, "direct": 1})
        self.assertEqual(
            result.fallback_counts, {"unsupported-question-semantics": 1}
        )
        for evidence in result.evidence.values():
            self.assertEqual(evidence.parse_status, "NOT_APPLICABLE")
            self.assertEqual(evidence.input_token_count, 0)
            self.assertEqual(evidence.generated_token_count, 0)
            value = json.loads(evidence.raw_response)
            self.assertEqual(canonical_json(value), evidence.raw_response)
            self.assertNotIn("gold", evidence.raw_response.casefold())

    def test_input_coverage_and_fixed_positions_fail_closed(self):
        example = _example("A before B.", "What happened before B?")
        with self.assertRaisesRegex(RuleGraphError, "coverage"):
            RuleGraphInputs((example,), {})
        with self.assertRaisesRegex(RuleGraphError, "ten fixed"):
            rerank_example(example, (("A",), ("B",)))
        with self.assertRaisesRegex(RuleGraphError, "Direct and CoT"):
            RuleGraphInputs(
                (example,),
                {example.record_id: (None, ("B",)) + (None,) * 8},
            )


if __name__ == "__main__":
    unittest.main()
