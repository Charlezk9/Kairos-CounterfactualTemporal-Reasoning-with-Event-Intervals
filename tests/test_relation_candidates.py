import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from kairos.ids import canonical_json
from kairos import relation_candidates as candidates


def _evidence(answer_by_position):
    rows = []
    for index, position in enumerate(candidates.POSITIONS):
        answer = answer_by_position.get(index)
        rows.append(
            {
                "method": position.method,
                "sample_position": position.sample_position,
                "generation_seed": None,
                "max_new_tokens": position.max_new_tokens,
                "raw_response": "invalid" if answer is None else json.dumps(answer),
                "parse_status": "PARSE_ERROR" if answer is None else "PARSED",
                "parse_error": "invalid" if answer is None else None,
                "parsed_answer": answer,
                "input_token_count": 10,
                "generated_token_count": 2,
            }
        )
    return rows


class RelationCandidateProtocolTests(unittest.TestCase):
    def test_seed_is_exact_and_position_bound(self):
        self.assertEqual(
            candidates._seed("source:test", 0), 3271569535578620851
        )
        self.assertNotEqual(
            candidates._seed("source:test", 0), candidates._seed("source:test", 1)
        )
        self.assertNotEqual(
            candidates._seed("source:test", 0), candidates._seed("source:other", 0)
        )
        with self.assertRaisesRegex(candidates.RelationCandidateError, "seed identity"):
            candidates._seed("source:test", 8)

    def test_strict_direct_and_cot_parsers(self):
        self.assertEqual(candidates._parse_response("direct", '  "42"\n'), "42")
        self.assertEqual(
            candidates._parse_response(
                "cot", 'Reasoning\nFINAL_ANSWER: "forty two"\n'
            ),
            "forty two",
        )
        self.assertEqual(
            candidates._parse_response(
                "self-consistency", 'Work\nFINAL_ANSWER: "42"'
            ),
            "42",
        )
        failures = (
            ("direct", 'answer is "42"'),
            ("direct", "42"),
            ("direct", '""'),
            ("cot", 'FINAL_ANSWER:"42"'),
            ("cot", 'FINAL_ANSWER: "42"\ntrailer'),
            ("cot", "FINAL_ANSWER: 42"),
            ("direct", '"\\ud800"'),
        )
        for method, response in failures:
            with self.subTest(method=method, response=response):
                with self.assertRaises(candidates.RelationCandidateError):
                    candidates._parse_response(method, response)

    def test_pool_keeps_frozen_order_and_merges_origins(self):
        rows = _evidence({0: "42", 1: "42", 2: "41", 3: "42", 9: "43"})
        value = candidates._pool("pair", "source", "train", rows).to_dict()
        self.assertEqual(
            [proposal["text"] for proposal in value["proposals"]],
            ["42", "42", "41", "42", "43"],
        )
        self.assertEqual(
            [candidate["text"] for candidate in value["candidates"]],
            ["42", "41", "43"],
        )
        self.assertEqual(
            value["candidates"][0]["origins"],
            ["direct", "cot", "self-consistency"],
        )
        self.assertEqual(value["gold_access"], "NONE")
        self.assertEqual(
            value["candidates"][0]["content_sha256"],
            hashlib.sha256(b"42").hexdigest(),
        )
        with self.assertRaisesRegex(
            candidates.RelationCandidateError, "evidence coverage"
        ):
            candidates._pool("pair", "source", "train", rows[:-1])

    def test_protocol_hashes_and_resource_gate_are_fail_closed(self):
        protocols = candidates._protocols()
        self.assertEqual(protocols["candidate"]["schema_version"], "kairos-candidate-prompt-v1")
        temporary_root = Path(
            tempfile.mkdtemp(
                prefix="relation-candidate-gate-test-",
                dir="/data0/hk_data/kairos-zx/.tmp",
            )
        )
        try:
            temporary_root.chmod(0o700)
            path = temporary_root / "gate.json"
            value = {
                "schema_version": "kairos-model-resource-gate-v1",
                "status": "PASSED",
                "execution_commit": "a" * 40,
                "model_files_verified": True,
                "selected_gpu": {
                    "physical_index": 5,
                    "uuid": "GPU-test",
                    "pci_bus_id": "00000000:89:00.0",
                    "name": "NVIDIA GeForce RTX 3090",
                    "total_mib": 24576,
                    "torch_total_bytes": 24_000_000_000,
                    "free_mib": 22528,
                    "free_bytes": 22528 * 1024**2,
                    "compute_process_count": 0,
                },
                "data0_free_bytes": 120 * 1024**3,
                "memory_available_bytes": 64 * 1024**3,
                "project_bytes_before": 10 * 1024**3,
                "projected_new_bytes": 2 * 1024**3,
                "projected_project_bytes_after": 12 * 1024**3,
                "gpu_count": 1,
                "cpu_thread_limit": 8,
                "dataloader_workers": 2,
            }
            payload = canonical_json(value).encode("utf-8") + b"\n"
            path.write_bytes(payload)
            path.chmod(0o600)
            replayed, digest = candidates._resource_gate(path, "a" * 40)
            self.assertEqual(replayed, value)
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

            value["selected_gpu"]["free_bytes"] -= 1
            path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")
            path.chmod(0o600)
            with self.assertRaisesRegex(
                candidates.RelationCandidateError, "frozen candidate boundary"
            ):
                candidates._resource_gate(path, "a" * 40)
        finally:
            shutil.rmtree(temporary_root)


if __name__ == "__main__":
    unittest.main()
