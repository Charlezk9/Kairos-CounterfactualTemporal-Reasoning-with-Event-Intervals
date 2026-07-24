"""Independent tensor implementation of the Kairos interval architecture."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Optional

import torch
from torch import Tensor, nn
import torch.nn.functional as F


RELATION_LABELS = (
    "precedes",
    "follows",
    "overlaps",
    "contains",
    "during",
)
RELATION_TO_INDEX = {label: index for index, label in enumerate(RELATION_LABELS)}
IGNORE_RELATION_INDEX = -100


class KairosModelError(ValueError):
    """A Kairos tensor contract was violated."""


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise KairosModelError(f"{name} must be a positive integer")
    return value


def _floating(tensor: Tensor, name: str) -> None:
    if not isinstance(tensor, Tensor) or not tensor.is_floating_point():
        raise KairosModelError(f"{name} must be a floating-point tensor")
    if not torch.isfinite(tensor).all():
        raise KairosModelError(f"{name} contains a non-finite value")


def _boolean(tensor: Tensor, name: str) -> None:
    if not isinstance(tensor, Tensor) or tensor.dtype != torch.bool:
        raise KairosModelError(f"{name} must be a Boolean tensor")


@dataclass(frozen=True)
class KairosConfig:
    hidden_size: int
    shared_size: int = 256
    relation_count: int = len(RELATION_LABELS)
    minimum_duration: float = 1e-6
    pair_mlp_hidden_size: int = 256

    def __post_init__(self) -> None:
        _positive_integer(self.hidden_size, "hidden_size")
        _positive_integer(self.shared_size, "shared_size")
        _positive_integer(self.pair_mlp_hidden_size, "pair_mlp_hidden_size")
        if self.relation_count != len(RELATION_LABELS):
            raise KairosModelError("relation_count must match the five known relations")
        if (
            isinstance(self.minimum_duration, bool)
            or not isinstance(self.minimum_duration, (int, float))
            or not 0.0 < float(self.minimum_duration) <= 1.0
        ):
            raise KairosModelError("minimum_duration must be in (0, 1]")


def masked_event_pool(
    token_hidden: Tensor,
    event_token_mask: Tensor,
    event_mask: Tensor,
) -> Tensor:
    """Mean-pool token spans into event representations with strict masks."""

    _floating(token_hidden, "token_hidden")
    _boolean(event_token_mask, "event_token_mask")
    _boolean(event_mask, "event_mask")
    if token_hidden.ndim != 3:
        raise KairosModelError("token_hidden must have shape [batch, tokens, hidden]")
    if event_token_mask.ndim != 3:
        raise KairosModelError(
            "event_token_mask must have shape [batch, events, tokens]"
        )
    if event_mask.ndim != 2:
        raise KairosModelError("event_mask must have shape [batch, events]")
    batch, tokens, unused_hidden = token_hidden.shape
    if event_token_mask.shape[0] != batch or event_token_mask.shape[2] != tokens:
        raise KairosModelError("event_token_mask differs from token_hidden shape")
    if event_mask.shape != event_token_mask.shape[:2]:
        raise KairosModelError("event_mask differs from event_token_mask shape")
    token_counts = event_token_mask.sum(dim=-1)
    if torch.any(event_mask & (token_counts == 0)):
        raise KairosModelError("a valid event has no token")
    if torch.any((~event_mask) & (token_counts != 0)):
        raise KairosModelError("a padded event selects tokens")
    weights = event_token_mask.to(dtype=token_hidden.dtype)
    pooled = torch.einsum("bet,bth->beh", weights, token_hidden)
    pooled = pooled / token_counts.clamp_min(1).unsqueeze(-1).to(token_hidden.dtype)
    return pooled * event_mask.unsqueeze(-1).to(token_hidden.dtype)


def masked_candidate_pool(
    candidate_token_hidden: Tensor,
    candidate_token_mask: Tensor,
    candidate_mask: Tensor,
) -> Tensor:
    """Mean-pool answer spans from independently encoded query/candidate inputs."""

    _floating(candidate_token_hidden, "candidate_token_hidden")
    _boolean(candidate_token_mask, "candidate_token_mask")
    _boolean(candidate_mask, "candidate_mask")
    if candidate_token_hidden.ndim != 4:
        raise KairosModelError(
            "candidate_token_hidden must have shape [batch, candidates, tokens, hidden]"
        )
    if candidate_token_mask.shape != candidate_token_hidden.shape[:3]:
        raise KairosModelError(
            "candidate_token_mask differs from candidate_token_hidden shape"
        )
    if candidate_mask.shape != candidate_token_hidden.shape[:2]:
        raise KairosModelError("candidate_mask differs from candidate tensor shape")
    token_counts = candidate_token_mask.sum(dim=-1)
    if torch.any(candidate_mask & (token_counts == 0)):
        raise KairosModelError("a valid candidate has no answer-span token")
    if torch.any((~candidate_mask) & (token_counts != 0)):
        raise KairosModelError("a padded candidate selects answer-span tokens")
    weights = candidate_token_mask.to(candidate_token_hidden.dtype)
    pooled = torch.einsum("bct,bcth->bch", weights, candidate_token_hidden)
    pooled = pooled / token_counts.clamp_min(1).unsqueeze(-1).to(
        candidate_token_hidden.dtype
    )
    return pooled * candidate_mask.unsqueeze(-1).to(candidate_token_hidden.dtype)


def event_pair_mask(event_mask: Tensor) -> Tensor:
    """Return valid directed non-self event pairs."""

    _boolean(event_mask, "event_mask")
    if event_mask.ndim != 2:
        raise KairosModelError("event_mask must have shape [batch, events]")
    event_count = event_mask.shape[1]
    diagonal = torch.eye(event_count, dtype=torch.bool, device=event_mask.device)
    return (
        event_mask.unsqueeze(2)
        & event_mask.unsqueeze(1)
        & (~diagonal.unsqueeze(0))
    )


class IntervalProjection(nn.Module):
    """Project event representations to latent start, duration and end."""

    def __init__(self, config: KairosConfig) -> None:
        super().__init__()
        self.hidden_size = config.hidden_size
        self.minimum_duration = float(config.minimum_duration)
        self.start_projection = nn.Linear(config.hidden_size, 1)
        self.duration_projection = nn.Linear(config.hidden_size, 1)

    def forward(self, event_hidden: Tensor, event_mask: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        _floating(event_hidden, "event_hidden")
        _boolean(event_mask, "event_mask")
        if event_hidden.ndim != 3 or event_hidden.shape[-1] != self.hidden_size:
            raise KairosModelError(
                "event_hidden must have shape [batch, events, hidden_size]"
            )
        if event_mask.shape != event_hidden.shape[:2]:
            raise KairosModelError("event_mask differs from event_hidden shape")
        starts = self.start_projection(event_hidden).squeeze(-1)
        durations = (
            F.softplus(self.duration_projection(event_hidden).squeeze(-1))
            + self.minimum_duration
        )
        ends = starts + durations
        # Autocast can project FP32 hidden states to BF16.  Keep the mask in the
        # coordinate dtype so multiplying it does not promote quantized starts,
        # durations, and ends back to FP32 and break end == start + duration.
        mask = event_mask.to(dtype=starts.dtype)
        return starts * mask, durations * mask, ends * mask


def interval_geometry(
    starts: Tensor,
    durations: Tensor,
    ends: Tensor,
) -> Tensor:
    """Construct the paper's exact ordered 8-dimensional pair features."""

    for tensor, name in (
        (starts, "starts"),
        (durations, "durations"),
        (ends, "ends"),
    ):
        _floating(tensor, name)
        if tensor.ndim != 2:
            raise KairosModelError(f"{name} must have shape [batch, events]")
    if starts.shape != durations.shape or starts.shape != ends.shape:
        raise KairosModelError("interval coordinate shapes differ")
    if not torch.allclose(ends, starts + durations, rtol=1e-5, atol=1e-6):
        raise KairosModelError("interval ends must equal starts plus durations")
    start_i = starts.unsqueeze(2).expand(-1, -1, starts.shape[1])
    start_j = starts.unsqueeze(1).expand(-1, starts.shape[1], -1)
    end_i = ends.unsqueeze(2).expand_as(start_i)
    end_j = ends.unsqueeze(1).expand_as(start_j)
    duration_i = durations.unsqueeze(2).expand_as(start_i)
    duration_j = durations.unsqueeze(1).expand_as(start_j)
    return torch.stack(
        (
            start_i,
            end_i,
            start_j,
            end_j,
            start_j - end_i,
            start_i - end_j,
            duration_i,
            duration_j,
        ),
        dim=-1,
    )


def masked_graph_pool(relation_probabilities: Tensor, pair_mask: Tensor) -> Tensor:
    """Mean-pool relation distributions over valid directed event pairs."""

    _floating(relation_probabilities, "relation_probabilities")
    _boolean(pair_mask, "pair_mask")
    if relation_probabilities.ndim != 4:
        raise KairosModelError(
            "relation_probabilities must have shape [batch, events, events, relations]"
        )
    if pair_mask.shape != relation_probabilities.shape[:3]:
        raise KairosModelError("pair_mask differs from relation tensor shape")
    if relation_probabilities.shape[-1] != len(RELATION_LABELS):
        raise KairosModelError("relation probability dimension is invalid")
    masked = relation_probabilities * pair_mask.unsqueeze(-1).to(
        relation_probabilities.dtype
    )
    counts = pair_mask.sum(dim=(1, 2), keepdim=False)
    pooled = masked.sum(dim=(1, 2)) / counts.clamp_min(1).unsqueeze(-1).to(
        relation_probabilities.dtype
    )
    return pooled * (counts > 0).unsqueeze(-1).to(relation_probabilities.dtype)


class CandidateGraphScorer(nn.Module):
    """Score candidates from answer and graph representations in shared space."""

    def __init__(self, config: KairosConfig) -> None:
        super().__init__()
        self.hidden_size = config.hidden_size
        self.relation_count = config.relation_count
        self.answer_projection = nn.Linear(config.hidden_size, config.shared_size)
        self.graph_projection = nn.Linear(config.relation_count, config.shared_size)
        self.score_projection = nn.Linear(3 * config.shared_size, 1)

    def forward(
        self,
        candidate_hidden: Tensor,
        candidate_mask: Tensor,
        graph_hidden: Tensor,
    ) -> Tensor:
        _floating(candidate_hidden, "candidate_hidden")
        _boolean(candidate_mask, "candidate_mask")
        _floating(graph_hidden, "graph_hidden")
        if candidate_hidden.ndim != 3 or candidate_hidden.shape[-1] != self.hidden_size:
            raise KairosModelError(
                "candidate_hidden must have shape [batch, candidates, hidden_size]"
            )
        if candidate_mask.shape != candidate_hidden.shape[:2]:
            raise KairosModelError("candidate_mask differs from candidate_hidden shape")
        if graph_hidden.shape != (candidate_hidden.shape[0], self.relation_count):
            raise KairosModelError("graph_hidden shape is invalid")
        if torch.any(candidate_mask.sum(dim=1) == 0):
            raise KairosModelError("each example must have at least one candidate")
        candidate = self.answer_projection(candidate_hidden)
        graph = self.graph_projection(graph_hidden).unsqueeze(1).expand_as(candidate)
        features = torch.cat((candidate, graph, candidate * graph), dim=-1)
        scores = self.score_projection(features).squeeze(-1)
        return scores.masked_fill(~candidate_mask, torch.finfo(scores.dtype).min)


@dataclass(frozen=True)
class KairosOutput:
    event_hidden: Tensor
    starts: Tensor
    durations: Tensor
    ends: Tensor
    pair_geometry: Tensor
    pair_mask: Tensor
    relation_logits: Tensor
    relation_probabilities: Tensor
    graph_hidden: Tensor
    candidate_scores: Tensor


class KairosModel(nn.Module):
    """Interval projection, relation graph and graph-aware candidate scorer."""

    def __init__(self, config: KairosConfig) -> None:
        super().__init__()
        self.config = config
        self.interval_projection = IntervalProjection(config)
        self.relation_classifier = nn.Linear(8, config.relation_count)
        self.candidate_scorer = CandidateGraphScorer(config)

    def forward(
        self,
        token_hidden: Tensor,
        event_token_mask: Tensor,
        event_mask: Tensor,
        candidate_hidden: Tensor,
        candidate_mask: Tensor,
    ) -> KairosOutput:
        event_hidden = masked_event_pool(token_hidden, event_token_mask, event_mask)
        starts, durations, ends = self.interval_projection(event_hidden, event_mask)
        geometry = interval_geometry(starts, durations, ends)
        pair_mask = event_pair_mask(event_mask)
        relation_logits = self.relation_classifier(geometry)
        relation_probabilities = relation_logits.softmax(dim=-1)
        graph_hidden = masked_graph_pool(relation_probabilities, pair_mask)
        candidate_scores = self.candidate_scorer(
            candidate_hidden, candidate_mask, graph_hidden
        )
        return KairosOutput(
            event_hidden=event_hidden,
            starts=starts,
            durations=durations,
            ends=ends,
            pair_geometry=geometry,
            pair_mask=pair_mask,
            relation_logits=relation_logits,
            relation_probabilities=relation_probabilities,
            graph_hidden=graph_hidden,
            candidate_scores=candidate_scores,
        )


@dataclass(frozen=True)
class PairMlpOutput:
    event_hidden: Tensor
    pair_mask: Tensor
    relation_logits: Tensor
    relation_probabilities: Tensor
    graph_hidden: Tensor
    candidate_scores: Tensor


class PairMlpBaseline(nn.Module):
    """Same-supervision relation baseline without latent intervals."""

    def __init__(self, config: KairosConfig) -> None:
        super().__init__()
        self.config = config
        self.relation_mlp = nn.Sequential(
            nn.Linear(4 * config.hidden_size, config.pair_mlp_hidden_size),
            nn.GELU(),
            nn.Linear(config.pair_mlp_hidden_size, config.relation_count),
        )
        self.candidate_scorer = CandidateGraphScorer(config)

    def forward(
        self,
        token_hidden: Tensor,
        event_token_mask: Tensor,
        event_mask: Tensor,
        candidate_hidden: Tensor,
        candidate_mask: Tensor,
    ) -> PairMlpOutput:
        event_hidden = masked_event_pool(token_hidden, event_token_mask, event_mask)
        event_i = event_hidden.unsqueeze(2).expand(-1, -1, event_hidden.shape[1], -1)
        event_j = event_hidden.unsqueeze(1).expand(-1, event_hidden.shape[1], -1, -1)
        pair_features = torch.cat(
            (event_i, event_j, event_i - event_j, event_i * event_j), dim=-1
        )
        pair_mask = event_pair_mask(event_mask)
        relation_logits = self.relation_mlp(pair_features)
        relation_probabilities = relation_logits.softmax(dim=-1)
        graph_hidden = masked_graph_pool(relation_probabilities, pair_mask)
        candidate_scores = self.candidate_scorer(
            candidate_hidden, candidate_mask, graph_hidden
        )
        return PairMlpOutput(
            event_hidden=event_hidden,
            pair_mask=pair_mask,
            relation_logits=relation_logits,
            relation_probabilities=relation_probabilities,
            graph_hidden=graph_hidden,
            candidate_scores=candidate_scores,
        )


def relation_cross_entropy(
    relation_logits: Tensor,
    pair_mask: Tensor,
    targets: Optional[Tensor],
) -> Tensor:
    """Relation CE that rejects labels on self/padding and ignores unknown."""

    _floating(relation_logits, "relation_logits")
    _boolean(pair_mask, "pair_mask")
    if relation_logits.ndim != 4 or relation_logits.shape[-1] != len(RELATION_LABELS):
        raise KairosModelError("relation_logits shape is invalid")
    if pair_mask.shape != relation_logits.shape[:3]:
        raise KairosModelError("pair_mask differs from relation_logits shape")
    if targets is None:
        return relation_logits.sum() * 0.0
    if not isinstance(targets, Tensor) or targets.dtype != torch.long:
        raise KairosModelError("relation targets must be a torch.long tensor")
    if targets.shape != pair_mask.shape:
        raise KairosModelError("relation target shape is invalid")
    supervised = targets != IGNORE_RELATION_INDEX
    if torch.any(supervised & (~pair_mask)):
        raise KairosModelError("a self or padded pair has a relation label")
    if torch.any(supervised & ((targets < 0) | (targets >= len(RELATION_LABELS)))):
        raise KairosModelError("relation target index is invalid")
    if not torch.any(supervised):
        return relation_logits.sum() * 0.0
    return F.cross_entropy(relation_logits[supervised], targets[supervised])


def kairos_loss(
    candidate_scores: Tensor,
    candidate_mask: Tensor,
    answer_targets: Tensor,
    relation_logits: Tensor,
    pair_mask: Tensor,
    relation_targets: Optional[Tensor] = None,
    counterfactual_relation_logits: Optional[Tensor] = None,
    counterfactual_pair_mask: Optional[Tensor] = None,
    counterfactual_relation_targets: Optional[Tensor] = None,
    lambda_relation: float = 1.0,
    lambda_counterfactual: float = 1.0,
) -> Mapping[str, Tensor]:
    """Compute answer, relation and counterfactual relation objectives."""

    _floating(candidate_scores, "candidate_scores")
    _boolean(candidate_mask, "candidate_mask")
    if candidate_scores.ndim != 2 or candidate_mask.shape != candidate_scores.shape:
        raise KairosModelError("candidate score/mask shapes are invalid")
    if not isinstance(answer_targets, Tensor) or answer_targets.dtype != torch.long:
        raise KairosModelError("answer_targets must be a torch.long tensor")
    if answer_targets.shape != (candidate_scores.shape[0],):
        raise KairosModelError("answer target shape is invalid")
    if torch.any(answer_targets < 0) or torch.any(
        answer_targets >= candidate_scores.shape[1]
    ):
        raise KairosModelError("answer target index is invalid")
    selected = candidate_mask.gather(1, answer_targets.unsqueeze(1)).squeeze(1)
    if not torch.all(selected):
        raise KairosModelError("an answer target selects a padded candidate")
    for value, name in (
        (lambda_relation, "lambda_relation"),
        (lambda_counterfactual, "lambda_counterfactual"),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise KairosModelError(f"{name} must be a non-negative number")
    answer_loss = F.cross_entropy(candidate_scores, answer_targets)
    relation_loss = relation_cross_entropy(
        relation_logits, pair_mask, relation_targets
    )
    counterfactual_inputs = (
        counterfactual_relation_logits,
        counterfactual_pair_mask,
        counterfactual_relation_targets,
    )
    if all(value is None for value in counterfactual_inputs):
        counterfactual_loss = relation_logits.sum() * 0.0
    elif any(value is None for value in counterfactual_inputs):
        raise KairosModelError(
            "counterfactual logits, mask and targets must be provided together"
        )
    else:
        counterfactual_loss = relation_cross_entropy(
            counterfactual_relation_logits,
            counterfactual_pair_mask,
            counterfactual_relation_targets,
        )
    total = (
        answer_loss
        + float(lambda_relation) * relation_loss
        + float(lambda_counterfactual) * counterfactual_loss
    )
    return {
        "loss": total,
        "answer_loss": answer_loss,
        "relation_loss": relation_loss,
        "counterfactual_relation_loss": counterfactual_loss,
    }
