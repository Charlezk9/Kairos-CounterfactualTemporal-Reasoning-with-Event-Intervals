import math
import unittest

import torch
import torch.nn.functional as F

from kairos import modeling


torch.set_num_threads(2)


def _inputs():
    token_hidden = torch.tensor(
        [
            [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0], [7.0, 8.0, 9.0], [0.0, 0.0, 0.0]],
            [[2.0, 3.0, 4.0], [4.0, 5.0, 6.0], [6.0, 7.0, 8.0], [8.0, 9.0, 10.0]],
        ]
    )
    event_token_mask = torch.tensor(
        [
            [[True, True, False, False], [False, False, True, False], [False, False, False, False]],
            [[False, True, True, False], [False, False, False, False], [False, False, False, False]],
        ]
    )
    event_mask = torch.tensor(
        [[True, True, False], [True, False, False]]
    )
    candidate_hidden = torch.tensor(
        [
            [[1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [9.0, 9.0, 9.0]],
            [[1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
        ]
    )
    candidate_mask = torch.tensor(
        [[True, True, False], [True, True, True]]
    )
    return (
        token_hidden,
        event_token_mask,
        event_mask,
        candidate_hidden,
        candidate_mask,
    )


class PoolAndGeometryTests(unittest.TestCase):
    def test_masked_event_pool_is_exact_and_zeroes_padding(self):
        token_hidden, event_token_mask, event_mask, unused, unused_mask = _inputs()
        pooled = modeling.masked_event_pool(
            token_hidden, event_token_mask, event_mask
        )
        expected = torch.tensor(
            [
                [[2.0, 3.0, 4.0], [7.0, 8.0, 9.0], [0.0, 0.0, 0.0]],
                [[5.0, 6.0, 7.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            ]
        )
        torch.testing.assert_close(pooled, expected)

    def test_event_pool_rejects_empty_valid_and_selected_padded_events(self):
        token_hidden, event_token_mask, event_mask, unused, unused_mask = _inputs()
        empty = event_token_mask.clone()
        empty[0, 0] = False
        with self.assertRaisesRegex(modeling.KairosModelError, "valid event"):
            modeling.masked_event_pool(token_hidden, empty, event_mask)

        padded = event_token_mask.clone()
        padded[0, 2, 0] = True
        with self.assertRaisesRegex(modeling.KairosModelError, "padded event"):
            modeling.masked_event_pool(token_hidden, padded, event_mask)

    def test_candidate_answer_span_pool_is_exact_and_strict(self):
        hidden = torch.tensor(
            [[[[1.0, 2.0], [3.0, 4.0], [9.0, 9.0]], [[7.0, 8.0], [5.0, 6.0], [0.0, 0.0]]]]
        )
        token_mask = torch.tensor([[[True, True, False], [False, False, False]]])
        candidate_mask = torch.tensor([[True, False]])
        pooled = modeling.masked_candidate_pool(hidden, token_mask, candidate_mask)
        torch.testing.assert_close(
            pooled, torch.tensor([[[2.0, 3.0], [0.0, 0.0]]])
        )
        invalid = token_mask.clone()
        invalid[0, 1, 0] = True
        with self.assertRaisesRegex(modeling.KairosModelError, "padded candidate"):
            modeling.masked_candidate_pool(hidden, invalid, candidate_mask)

    def test_pair_mask_is_directed_nonself(self):
        event_mask = torch.tensor([[True, True, False], [True, False, False]])
        mask = modeling.event_pair_mask(event_mask)
        expected = torch.tensor(
            [
                [[False, True, False], [True, False, False], [False, False, False]],
                [[False, False, False], [False, False, False], [False, False, False]],
            ]
        )
        self.assertTrue(torch.equal(mask, expected))

    def test_interval_projection_end_and_duration_invariants(self):
        config = modeling.KairosConfig(hidden_size=3, minimum_duration=1e-5)
        projection = modeling.IntervalProjection(config)
        with torch.no_grad():
            projection.start_projection.weight.copy_(torch.tensor([[1.0, 0.0, 0.0]]))
            projection.start_projection.bias.zero_()
            projection.duration_projection.weight.zero_()
            projection.duration_projection.bias.fill_(math.log(math.exp(1.0) - 1.0))
        event_hidden = torch.tensor(
            [[[1.0, 2.0, 3.0], [5.0, 0.0, 0.0], [9.0, 9.0, 9.0]]]
        )
        event_mask = torch.tensor([[True, True, False]])
        starts, durations, ends = projection(event_hidden, event_mask)
        torch.testing.assert_close(starts, torch.tensor([[1.0, 5.0, 0.0]]))
        torch.testing.assert_close(
            durations[:, :2], torch.full((1, 2), 1.0 + config.minimum_duration)
        )
        self.assertTrue(torch.all(durations[:, :2] > 0))
        torch.testing.assert_close(ends, starts + durations)
        self.assertEqual(durations[0, 2].item(), 0.0)

    def test_geometry_feature_order_matches_paper(self):
        starts = torch.tensor([[1.0, 5.0]])
        durations = torch.tensor([[2.0, 3.0]])
        ends = torch.tensor([[3.0, 8.0]])
        geometry = modeling.interval_geometry(starts, durations, ends)
        torch.testing.assert_close(
            geometry[0, 0, 1],
            torch.tensor([1.0, 3.0, 5.0, 8.0, 2.0, -7.0, 2.0, 3.0]),
        )
        torch.testing.assert_close(
            geometry[0, 1, 0],
            torch.tensor([5.0, 8.0, 1.0, 3.0, -7.0, 2.0, 3.0, 2.0]),
        )
        with self.assertRaisesRegex(modeling.KairosModelError, "ends"):
            modeling.interval_geometry(starts, durations, ends + 1)


class GraphAndScoringTests(unittest.TestCase):
    def test_graph_pool_ignores_self_padding_and_handles_no_pairs(self):
        probabilities = torch.zeros(2, 3, 3, 5)
        probabilities[..., 4] = 1.0
        probabilities[0, 0, 1] = torch.tensor([1.0, 0.0, 0.0, 0.0, 0.0])
        probabilities[0, 1, 0] = torch.tensor([0.0, 1.0, 0.0, 0.0, 0.0])
        pair_mask = modeling.event_pair_mask(
            torch.tensor([[True, True, False], [True, False, False]])
        )
        pooled = modeling.masked_graph_pool(probabilities, pair_mask)
        torch.testing.assert_close(
            pooled[0], torch.tensor([0.5, 0.5, 0.0, 0.0, 0.0])
        )
        torch.testing.assert_close(pooled[1], torch.zeros(5))

    def test_candidate_scorer_masks_padding_and_requires_candidate(self):
        torch.manual_seed(7)
        config = modeling.KairosConfig(hidden_size=3, shared_size=4)
        scorer = modeling.CandidateGraphScorer(config)
        unused_tokens, unused_event_tokens, unused_events, candidates, mask = _inputs()
        graph = torch.tensor(
            [[0.5, 0.5, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0]]
        )
        scores = scorer(candidates, mask, graph)
        self.assertEqual(scores.shape, (2, 3))
        self.assertEqual(scores[0, 2].item(), torch.finfo(scores.dtype).min)
        self.assertLess(scores.argmax(dim=1)[0].item(), 2)
        invalid = mask.clone()
        invalid[1] = False
        with self.assertRaisesRegex(modeling.KairosModelError, "at least one"):
            scorer(candidates, invalid, graph)


class ModelAndLossTests(unittest.TestCase):
    def test_full_kairos_forward_shapes_probabilities_and_gradients(self):
        torch.manual_seed(13)
        config = modeling.KairosConfig(hidden_size=3, shared_size=4)
        model = modeling.KairosModel(config)
        inputs = _inputs()
        output = model(*inputs)

        self.assertEqual(output.event_hidden.shape, (2, 3, 3))
        self.assertEqual(output.pair_geometry.shape, (2, 3, 3, 8))
        self.assertEqual(output.relation_logits.shape, (2, 3, 3, 5))
        self.assertEqual(output.graph_hidden.shape, (2, 5))
        self.assertEqual(output.candidate_scores.shape, (2, 3))
        torch.testing.assert_close(
            output.relation_probabilities.sum(dim=-1), torch.ones(2, 3, 3)
        )
        self.assertTrue(torch.all(output.durations[inputs[2]] > 0))
        torch.testing.assert_close(output.ends, output.starts + output.durations)
        torch.testing.assert_close(output.graph_hidden[1], torch.zeros(5))

        targets = torch.full((2, 3, 3), modeling.IGNORE_RELATION_INDEX, dtype=torch.long)
        targets[0, 0, 1] = modeling.RELATION_TO_INDEX["precedes"]
        targets[0, 1, 0] = modeling.RELATION_TO_INDEX["follows"]
        losses = modeling.kairos_loss(
            output.candidate_scores,
            inputs[4],
            torch.tensor([0, 2]),
            output.relation_logits,
            output.pair_mask,
            targets,
        )
        self.assertTrue(torch.isfinite(losses["loss"]))
        losses["loss"].backward()
        self.assertIsNotNone(model.interval_projection.start_projection.weight.grad)
        self.assertIsNotNone(model.relation_classifier.weight.grad)
        self.assertIsNotNone(model.candidate_scorer.score_projection.weight.grad)

    def test_pair_mlp_baseline_uses_same_masks_and_output_contract(self):
        torch.manual_seed(42)
        model = modeling.PairMlpBaseline(
            modeling.KairosConfig(
                hidden_size=3, shared_size=4, pair_mlp_hidden_size=5
            )
        )
        output = model(*_inputs())
        self.assertEqual(output.relation_logits.shape, (2, 3, 3, 5))
        self.assertEqual(output.candidate_scores.shape, (2, 3))
        torch.testing.assert_close(output.graph_hidden[1], torch.zeros(5))
        self.assertTrue(torch.equal(output.pair_mask, modeling.event_pair_mask(_inputs()[2])))

    def test_relation_loss_matches_manual_and_unknown_is_ignored(self):
        logits = torch.zeros(1, 2, 2, 5, requires_grad=True)
        logits.data[0, 0, 1] = torch.tensor([2.0, 0.0, 0.0, 0.0, 0.0])
        pair_mask = torch.tensor([[[False, True], [True, False]]])
        targets = torch.full((1, 2, 2), -100, dtype=torch.long)
        targets[0, 0, 1] = 0
        actual = modeling.relation_cross_entropy(logits, pair_mask, targets)
        expected = F.cross_entropy(logits[0, 0, 1].unsqueeze(0), torch.tensor([0]))
        torch.testing.assert_close(actual, expected)

        no_labels = torch.full((1, 2, 2), -100, dtype=torch.long)
        zero = modeling.relation_cross_entropy(logits, pair_mask, no_labels)
        self.assertEqual(zero.item(), 0.0)
        zero.backward()
        self.assertIsNotNone(logits.grad)

    def test_relation_loss_rejects_self_padding_and_bad_index(self):
        logits = torch.zeros(1, 2, 2, 5)
        pair_mask = torch.tensor([[[False, True], [True, False]]])
        self_label = torch.full((1, 2, 2), -100, dtype=torch.long)
        self_label[0, 0, 0] = 0
        with self.assertRaisesRegex(modeling.KairosModelError, "self or padded"):
            modeling.relation_cross_entropy(logits, pair_mask, self_label)
        bad = torch.full((1, 2, 2), -100, dtype=torch.long)
        bad[0, 0, 1] = 5
        with self.assertRaisesRegex(modeling.KairosModelError, "index"):
            modeling.relation_cross_entropy(logits, pair_mask, bad)

    def test_total_loss_includes_counterfactual_and_validates_optional_group(self):
        scores = torch.tensor([[2.0, 0.0]], requires_grad=True)
        candidate_mask = torch.tensor([[True, True]])
        relation_logits = torch.zeros(1, 2, 2, 5, requires_grad=True)
        pair_mask = torch.tensor([[[False, True], [True, False]]])
        targets = torch.full((1, 2, 2), -100, dtype=torch.long)
        targets[0, 0, 1] = 0
        cf_logits = torch.ones(1, 2, 2, 5, requires_grad=True)
        cf_targets = torch.full((1, 2, 2), -100, dtype=torch.long)
        cf_targets[0, 0, 1] = 1
        losses = modeling.kairos_loss(
            scores,
            candidate_mask,
            torch.tensor([0]),
            relation_logits,
            pair_mask,
            targets,
            cf_logits,
            pair_mask,
            cf_targets,
            lambda_relation=2.0,
            lambda_counterfactual=3.0,
        )
        expected = (
            losses["answer_loss"]
            + 2 * losses["relation_loss"]
            + 3 * losses["counterfactual_relation_loss"]
        )
        torch.testing.assert_close(losses["loss"], expected)
        with self.assertRaisesRegex(modeling.KairosModelError, "provided together"):
            modeling.kairos_loss(
                scores,
                candidate_mask,
                torch.tensor([0]),
                relation_logits,
                pair_mask,
                targets,
                counterfactual_relation_logits=cf_logits,
            )
        with self.assertRaisesRegex(modeling.KairosModelError, "non-negative"):
            modeling.kairos_loss(
                scores,
                candidate_mask,
                torch.tensor([0]),
                relation_logits,
                pair_mask,
                targets,
                lambda_relation=float("nan"),
            )

    def test_model_config_and_tensor_contract_fail_closed(self):
        for kwargs in (
            {"hidden_size": 0},
            {"hidden_size": 3, "relation_count": 6},
            {"hidden_size": 3, "minimum_duration": 0.0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(modeling.KairosModelError):
                    modeling.KairosConfig(**kwargs)
        token_hidden, event_token_mask, event_mask, candidates, candidate_mask = _inputs()
        with self.assertRaisesRegex(modeling.KairosModelError, "Boolean"):
            modeling.KairosModel(modeling.KairosConfig(hidden_size=3))(
                token_hidden,
                event_token_mask.float(),
                event_mask,
                candidates,
                candidate_mask,
            )


if __name__ == "__main__":
    unittest.main()
