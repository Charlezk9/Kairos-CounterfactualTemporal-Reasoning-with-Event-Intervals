from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from kairos import generation, llm_graph, prediction_artifacts
from kairos.transfer_eval import TorqueExample


def _torque(record_id="torque:graph:1", gold=("SECRET_GOLD",)):
    return TorqueExample(
        record_id=record_id,
        passage_id="passage",
        cluster_id="cluster",
        question="What happened before Beta?",
        passage="Alpha happened before Beta.",
        gold_spans=gold,
        gold_indices=("0",),
        is_default_question=True,
        derived_from_question="",
    )


VALID = (
    "Reasoning.\n"
    'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"Alpha"},{"id":"E2","span":"Beta"}],'
    '"relations":[{"source":"E1","relation":"precedes","target":"E2"}]}\n'
    'FINAL_ANSWER: ["Alpha"]'
)


class FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 0
    padding_side = "right"

    def __init__(self, over_budget=False):
        self.over_budget = over_budget

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return "<user>" + messages[0]["content"] + "<assistant>"

    def __call__(
        self, texts, return_tensors, padding, truncation, add_special_tokens
    ):
        width = generation.MODEL_CONTEXT_TOKENS if self.over_budget else 3
        return {
            "input_ids": torch.ones(len(texts), width, dtype=torch.long),
            "attention_mask": torch.ones(len(texts), width, dtype=torch.long),
        }

    def decode(self, tokens, skip_special_tokens, clean_up_tokenization_spaces):
        first = int(tokens[0]) if len(tokens) else 0
        return VALID if first == 10 else "FINAL_ANSWER: [\"Alpha\"]"


class FakeModel:
    def __init__(self, starts=(10,), invalid_shape=False):
        self.starts = starts
        self.invalid_shape = invalid_shape
        self.last_kwargs = None

    def generate(self, input_ids, attention_mask, **kwargs):
        self.last_kwargs = kwargs
        rows = input_ids.shape[0] - int(self.invalid_shape)
        prefix = input_ids[:rows].cpu()
        suffix = torch.zeros(rows, 2, dtype=torch.long)
        for index in range(rows):
            suffix[index, 0] = self.starts[index % len(self.starts)]
        return torch.cat((prefix, suffix), dim=1)


class LlmGraphPromptAndParserTests(unittest.TestCase):
    def test_prompt_is_gold_free_and_freeze_is_exact(self):
        prompt = llm_graph.build_llm_graph_prompt(_torque())
        self.assertIn("TEMPORAL_GRAPH: ", prompt)
        self.assertIn("precedes, follows, overlaps, contains, during", prompt)
        self.assertIn(_torque().passage, prompt)
        self.assertIn(_torque().question, prompt)
        self.assertNotIn("SECRET_GOLD", prompt)
        value = llm_graph.LlmGraphConfig().to_dict(13)
        self.assertFalse(value["do_sample"])
        self.assertEqual(value["max_new_tokens"], 768)
        self.assertEqual(value["batch_size"], 8)
        self.assertEqual(value["relation_order"], list(llm_graph.RELATIONS))
        for changes in ({"batch_size": 1}, {"max_new_tokens": 512}):
            with self.subTest(changes=changes):
                with self.assertRaises(llm_graph.LlmGraphError):
                    replace(llm_graph.LlmGraphConfig(), **changes)

    def test_valid_graph_and_answer_are_parsed(self):
        parsed = llm_graph.parse_llm_graph_response(VALID, _torque().passage)
        self.assertEqual(parsed.answer, ("Alpha",))
        self.assertEqual([event.event_id for event in parsed.events], ["E1", "E2"])
        self.assertEqual(parsed.relations[0].relation, "precedes")
        empty = llm_graph.parse_llm_graph_response(
            'TEMPORAL_GRAPH: {"events":[],"relations":[]}\nFINAL_ANSWER: []',
            _torque().passage,
        )
        self.assertEqual(empty.answer, ())
        self.assertEqual(empty.events, ())

    def test_malformed_or_unbound_graphs_fail_closed(self):
        invalid = (
            'TEMPORAL_GRAPH: {"events":[],"events":[],"relations":[]}\nFINAL_ANSWER: []',
            'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"Alpha"}],"relations":[{"source":"E1","relation":"before","target":"E2"}]}\nFINAL_ANSWER: ["Alpha"]',
            'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"Alpha"}],"relations":[{"source":"E1","relation":"precedes","target":"E2"}]}\nFINAL_ANSWER: ["Alpha"]',
            'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"Missing"}],"relations":[]}\nFINAL_ANSWER: []',
            'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"Alpha"},{"id":"E1","span":"Beta"}],"relations":[]}\nFINAL_ANSWER: ["Alpha"]',
            'TEMPORAL_GRAPH: {"events":[{"id":"E1","span":"Alpha"}],"relations":[]}\nFINAL_ANSWER: ["Beta"]',
            'FINAL_ANSWER: ["Alpha"]\nTEMPORAL_GRAPH: {"events":[],"relations":[]}',
        )
        for response in invalid:
            with self.subTest(response=response):
                with self.assertRaises(llm_graph.LlmGraphError):
                    llm_graph.parse_llm_graph_response(response, _torque().passage)


class LlmGraphGenerationTests(unittest.TestCase):
    def test_greedy_generation_parsing_and_evidence(self):
        model = FakeModel((10, 11))
        result = llm_graph.run_llm_graph(
            model,
            FakeTokenizer(),
            (_torque("r1"), _torque("r2")),
            llm_graph.LlmGraphConfig(),
            "cpu",
            13,
        )
        self.assertEqual(result.predictions["r1"], ["Alpha"])
        self.assertEqual(
            result.predictions["r2"], [generation.PARSE_ERROR_SENTINEL]
        )
        self.assertEqual(result.parse_error_count, 1)
        self.assertEqual(result.generated_token_total, 4)
        self.assertEqual(result.evidence["r1"].parse_status, "PARSED")
        self.assertEqual(result.evidence["r2"].parse_status, "PARSE_ERROR")
        self.assertFalse(model.last_kwargs["do_sample"])
        self.assertIsNone(model.last_kwargs["temperature"])
        self.assertEqual(model.last_kwargs["max_new_tokens"], 768)

    def test_context_and_shape_failures(self):
        with self.assertRaisesRegex(llm_graph.LlmGraphError, "context budget"):
            llm_graph.run_llm_graph(
                FakeModel(),
                FakeTokenizer(over_budget=True),
                (_torque(),),
                llm_graph.LlmGraphConfig(),
                "cpu",
                13,
            )
        with self.assertRaisesRegex(llm_graph.LlmGraphError, "shape differs"):
            llm_graph.run_llm_graph(
                FakeModel(invalid_shape=True),
                FakeTokenizer(),
                (_torque(),),
                llm_graph.LlmGraphConfig(),
                "cpu",
                13,
            )


class LlmGraphArtifactReplayTests(unittest.TestCase):
    def setUp(self):
        example = _torque(gold=("Alpha",))
        result = llm_graph.run_llm_graph(
            FakeModel(),
            FakeTokenizer(),
            (example,),
            llm_graph.LlmGraphConfig(),
            "cpu",
            13,
        )
        config = llm_graph.LlmGraphConfig().to_dict(13)
        started = "2026-07-23T17:00:00Z"
        run_id = prediction_artifacts.make_run_id(
            started, llm_graph.METHOD_NAME, "torque-dev", 13, config
        )
        spec = prediction_artifacts.RunSpec(
            run_id=run_id,
            dataset="torque-dev",
            method_name=llm_graph.METHOD_NAME,
            model_id=generation.MODEL_ID,
            model_revision=generation.MODEL_REVISION,
            execution_commit="a" * 40,
            seed=13,
            started_at=started,
            completed_at="2026-07-23T17:01:00Z",
            config=config,
            gpu_ids=(4,),
            cpu_threads=2,
            memory_gib=24,
            dataloader_workers=0,
        )
        self.example = example
        self.artifact = prediction_artifacts.VerifiedPredictionArtifact(
            spec=spec,
            records=(
                prediction_artifacts.PredictionRecord(
                    example.record_id, result.predictions[example.record_id]
                ),
            ),
            evidence=(result.evidence[example.record_id],),
            config_sha256="b" * 64,
            predictions_sha256="c" * 64,
            evidence_sha256="d" * 64,
            manifest_sha256="e" * 64,
            artifact_path=Path("/data0/hk_data/kairos-zx/artifacts/fake"),
        )

    def test_replay_reparses_graph_and_rejects_tamper(self):
        with patch.object(llm_graph, "verify_predictions", return_value=self.artifact), patch.object(
            llm_graph, "load_torque_dev", return_value=(self.example,)
        ):
            replay = llm_graph.verify_llm_graph_predictions(
                self.artifact.spec.run_id
            )
        self.assertEqual(replay.parse_error_count, 0)
        self.assertEqual(replay.generated_token_total, 2)

        bad = replace(
            self.artifact,
            records=(
                prediction_artifacts.PredictionRecord(
                    self.example.record_id, ["Beta"]
                ),
            ),
        )
        with patch.object(llm_graph, "verify_predictions", return_value=bad), patch.object(
            llm_graph, "load_torque_dev", return_value=(self.example,)
        ):
            with self.assertRaisesRegex(llm_graph.LlmGraphError, "differs"):
                llm_graph.verify_llm_graph_predictions(bad.spec.run_id)


if __name__ == "__main__":
    unittest.main()
