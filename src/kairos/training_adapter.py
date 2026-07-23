"""Synthetic-testable Qwen hidden-state adapter for Kairos and Pair-MLP."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import torch
from torch import Tensor, nn

from .modeling import (
    KairosConfig,
    KairosModel,
    KairosOutput,
    PairMlpBaseline,
    PairMlpOutput,
    kairos_loss,
    masked_candidate_pool,
)


LORA_TARGET_MODULES = (
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
)


class TrainingAdapterError(ValueError):
    """A batch, backbone, LoRA, or trainable-state invariant failed."""


def _integer_tensor(value: Any, ndim: int, name: str) -> Tensor:
    if not isinstance(value, Tensor) or value.dtype != torch.long or value.ndim != ndim:
        raise TrainingAdapterError(f"{name} must be a torch.long rank-{ndim} tensor")
    return value


def _boolean_tensor(value: Any, ndim: int, name: str) -> Tensor:
    if not isinstance(value, Tensor) or value.dtype != torch.bool or value.ndim != ndim:
        raise TrainingAdapterError(f"{name} must be a Boolean rank-{ndim} tensor")
    return value


def _attention(value: Any, shape: torch.Size, name: str) -> Tensor:
    if not isinstance(value, Tensor) or value.shape != shape:
        raise TrainingAdapterError(f"{name} shape differs from input IDs")
    if value.dtype == torch.bool:
        return value
    if value.dtype not in {torch.int32, torch.int64} or torch.any(
        (value != 0) & (value != 1)
    ):
        raise TrainingAdapterError(f"{name} must contain only Boolean or integer 0/1")
    return value.bool()


def _same_device(values: Sequence[Tensor]) -> None:
    devices = {value.device for value in values}
    if len(devices) != 1:
        raise TrainingAdapterError("all training batch tensors must share one device")


@dataclass(frozen=True)
class LoraSpec:
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: tuple[str, ...] = LORA_TARGET_MODULES

    def __post_init__(self) -> None:
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank != 16
            or isinstance(self.alpha, bool)
            or not isinstance(self.alpha, int)
            or self.alpha != 32
            or not isinstance(self.dropout, float)
            or self.dropout != 0.05
            or self.target_modules != LORA_TARGET_MODULES
        ):
            raise TrainingAdapterError("LoRA spec differs from the frozen default")

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": "qwen-lora-spec-v1",
            "rank": self.rank,
            "alpha": self.alpha,
            "dropout": self.dropout,
            "bias": "none",
            "target_modules": list(self.target_modules),
            "gradient_checkpointing": True,
            "use_cache": False,
        }


def validate_lora_targets(module: nn.Module, spec: LoraSpec) -> Mapping[str, int]:
    """Confirm every frozen Qwen projection suffix resolves only to Linear layers."""

    if not isinstance(module, nn.Module) or not isinstance(spec, LoraSpec):
        raise TrainingAdapterError("LoRA target validation inputs are invalid")
    counts = {name: 0 for name in spec.target_modules}
    for full_name, child in module.named_modules():
        leaf = full_name.rsplit(".", 1)[-1]
        if leaf in counts:
            if not isinstance(child, nn.Linear):
                raise TrainingAdapterError("a frozen LoRA target is not Linear")
            counts[leaf] += 1
    if any(count == 0 for count in counts.values()):
        raise TrainingAdapterError("one or more frozen LoRA targets are absent")
    return counts


@dataclass(frozen=True)
class TrainingBatch:
    input_ids: Tensor
    attention_mask: Tensor
    event_token_mask: Tensor
    event_mask: Tensor
    candidate_input_ids: Tensor
    candidate_attention_mask: Tensor
    candidate_token_mask: Tensor
    candidate_mask: Tensor
    answer_targets: Tensor
    relation_targets: Optional[Tensor] = None
    counterfactual_input_ids: Optional[Tensor] = None
    counterfactual_attention_mask: Optional[Tensor] = None
    counterfactual_event_token_mask: Optional[Tensor] = None
    counterfactual_event_mask: Optional[Tensor] = None
    counterfactual_relation_targets: Optional[Tensor] = None

    def __post_init__(self) -> None:
        input_ids = _integer_tensor(self.input_ids, 2, "input_ids")
        attention = _attention(
            self.attention_mask, input_ids.shape, "attention_mask"
        )
        if torch.any(attention.sum(dim=1) == 0):
            raise TrainingAdapterError("each source input must contain a real token")
        event_tokens = _boolean_tensor(
            self.event_token_mask, 3, "event_token_mask"
        )
        events = _boolean_tensor(self.event_mask, 2, "event_mask")
        if (
            event_tokens.shape[0] != input_ids.shape[0]
            or event_tokens.shape[2] != input_ids.shape[1]
            or events.shape != event_tokens.shape[:2]
        ):
            raise TrainingAdapterError("source event mask shapes differ")
        event_counts = event_tokens.sum(dim=-1)
        if torch.any(events & (event_counts == 0)) or torch.any(
            (~events) & (event_counts != 0)
        ):
            raise TrainingAdapterError("source event validity and tokens differ")
        if torch.any(event_tokens & (~attention.unsqueeze(1))):
            raise TrainingAdapterError("source event selects a padded token")

        candidate_ids = _integer_tensor(
            self.candidate_input_ids, 3, "candidate_input_ids"
        )
        candidate_attention = _attention(
            self.candidate_attention_mask,
            candidate_ids.shape,
            "candidate_attention_mask",
        )
        candidate_tokens = _boolean_tensor(
            self.candidate_token_mask, 3, "candidate_token_mask"
        )
        candidates = _boolean_tensor(self.candidate_mask, 2, "candidate_mask")
        if (
            candidate_ids.shape[0] != input_ids.shape[0]
            or candidate_tokens.shape != candidate_ids.shape
            or candidates.shape != candidate_ids.shape[:2]
        ):
            raise TrainingAdapterError("candidate tensor shapes differ")
        if torch.any(candidates.sum(dim=1) == 0):
            raise TrainingAdapterError("each example must contain a candidate")
        candidate_attention_count = candidate_attention.sum(dim=-1)
        candidate_token_count = candidate_tokens.sum(dim=-1)
        if (
            torch.any(candidates & (candidate_attention_count == 0))
            or torch.any(candidates & (candidate_token_count == 0))
            or torch.any((~candidates) & (candidate_attention_count != 0))
            or torch.any((~candidates) & (candidate_token_count != 0))
            or torch.any(candidate_tokens & (~candidate_attention))
        ):
            raise TrainingAdapterError("candidate padding, attention, and span differ")

        answers = _integer_tensor(self.answer_targets, 1, "answer_targets")
        if answers.shape != (input_ids.shape[0],):
            raise TrainingAdapterError("answer target shape differs")
        if torch.any(answers < 0) or torch.any(answers >= candidates.shape[1]):
            raise TrainingAdapterError("answer target index is invalid")
        if not torch.all(candidates.gather(1, answers.unsqueeze(1)).squeeze(1)):
            raise TrainingAdapterError("answer target selects a padded candidate")

        if self.relation_targets is not None:
            relation_targets = _integer_tensor(
                self.relation_targets, 3, "relation_targets"
            )
            if relation_targets.shape != (
                input_ids.shape[0], events.shape[1], events.shape[1]
            ):
                raise TrainingAdapterError("relation target shape differs")

        counterfactual = (
            self.counterfactual_input_ids,
            self.counterfactual_attention_mask,
            self.counterfactual_event_token_mask,
            self.counterfactual_event_mask,
            self.counterfactual_relation_targets,
        )
        if any(value is not None for value in counterfactual):
            if any(value is None for value in counterfactual):
                raise TrainingAdapterError(
                    "counterfactual tensors must be provided together"
                )
            cf_ids = _integer_tensor(
                self.counterfactual_input_ids, 2, "counterfactual_input_ids"
            )
            cf_attention = _attention(
                self.counterfactual_attention_mask,
                cf_ids.shape,
                "counterfactual_attention_mask",
            )
            cf_event_tokens = _boolean_tensor(
                self.counterfactual_event_token_mask,
                3,
                "counterfactual_event_token_mask",
            )
            cf_events = _boolean_tensor(
                self.counterfactual_event_mask, 2, "counterfactual_event_mask"
            )
            cf_targets = _integer_tensor(
                self.counterfactual_relation_targets,
                3,
                "counterfactual_relation_targets",
            )
            if (
                cf_ids.shape[0] != input_ids.shape[0]
                or torch.any(cf_attention.sum(dim=1) == 0)
                or cf_event_tokens.shape[0] != input_ids.shape[0]
                or cf_event_tokens.shape[2] != cf_ids.shape[1]
                or cf_events.shape != cf_event_tokens.shape[:2]
                or cf_targets.shape
                != (input_ids.shape[0], cf_events.shape[1], cf_events.shape[1])
            ):
                raise TrainingAdapterError("counterfactual tensor shapes differ")
            cf_counts = cf_event_tokens.sum(dim=-1)
            if (
                torch.any(cf_events & (cf_counts == 0))
                or torch.any((~cf_events) & (cf_counts != 0))
                or torch.any(cf_event_tokens & (~cf_attention.unsqueeze(1)))
            ):
                raise TrainingAdapterError(
                    "counterfactual event validity and tokens differ"
                )

        tensors = [
            value
            for value in (
                self.input_ids,
                self.attention_mask,
                self.event_token_mask,
                self.event_mask,
                self.candidate_input_ids,
                self.candidate_attention_mask,
                self.candidate_token_mask,
                self.candidate_mask,
                self.answer_targets,
                self.relation_targets,
                *counterfactual,
            )
            if isinstance(value, Tensor)
        ]
        _same_device(tensors)

    @property
    def has_counterfactual(self) -> bool:
        return self.counterfactual_input_ids is not None


@dataclass(frozen=True)
class TrainingAdapterOutput:
    original: KairosOutput | PairMlpOutput
    counterfactual: KairosOutput | PairMlpOutput | None
    losses: Mapping[str, Tensor]


class QwenCoreTrainingAdapter(nn.Module):
    """Encode one strict batch and route shared representations to either core."""

    def __init__(
        self,
        backbone: nn.Module,
        core: KairosModel | PairMlpBaseline,
    ) -> None:
        super().__init__()
        if not isinstance(backbone, nn.Module):
            raise TrainingAdapterError("backbone must be an nn.Module")
        if not isinstance(core, (KairosModel, PairMlpBaseline)):
            raise TrainingAdapterError("core must be KairosModel or PairMlpBaseline")
        hidden_size = getattr(getattr(backbone, "config", None), "hidden_size", None)
        if (
            isinstance(hidden_size, bool)
            or not isinstance(hidden_size, int)
            or hidden_size != core.config.hidden_size
        ):
            raise TrainingAdapterError("backbone and core hidden sizes differ")
        self.backbone = backbone
        self.core = core
        self.hidden_size = hidden_size

    def _encode(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        encoder = getattr(self.backbone, "model", self.backbone)
        if not callable(encoder):
            raise TrainingAdapterError("backbone encoder is not callable")
        try:
            output = encoder(
                input_ids=input_ids,
                attention_mask=attention_mask,
                use_cache=False,
                output_hidden_states=False,
                return_dict=True,
            )
        except Exception as error:
            raise TrainingAdapterError("backbone hidden-state encoding failed") from error
        hidden = None
        if isinstance(output, MappingABC):
            hidden = output.get("last_hidden_state")
            hidden_states = output.get("hidden_states")
        else:
            hidden = getattr(output, "last_hidden_state", None)
            hidden_states = getattr(output, "hidden_states", None)
        if hidden is None and isinstance(hidden_states, SequenceABC) and hidden_states:
            hidden = hidden_states[-1]
        if (
            not isinstance(hidden, Tensor)
            or not hidden.is_floating_point()
            or hidden.shape != (*input_ids.shape, self.hidden_size)
            or not torch.isfinite(hidden).all()
        ):
            raise TrainingAdapterError("backbone last hidden state is invalid")
        return hidden

    def _candidate_hidden(self, batch: TrainingBatch) -> Tensor:
        batch_size, candidate_count, token_count = batch.candidate_input_ids.shape
        valid = batch.candidate_mask.reshape(-1)
        flat_ids = batch.candidate_input_ids.reshape(-1, token_count)[valid]
        flat_attention = batch.candidate_attention_mask.reshape(-1, token_count)[valid]
        encoded = self._encode(flat_ids, flat_attention)
        all_hidden = encoded.new_zeros(
            (batch_size * candidate_count, token_count, self.hidden_size)
        )
        all_hidden[valid] = encoded
        token_hidden = all_hidden.reshape(
            batch_size, candidate_count, token_count, self.hidden_size
        )
        try:
            return masked_candidate_pool(
                token_hidden, batch.candidate_token_mask, batch.candidate_mask
            )
        except ValueError as error:
            raise TrainingAdapterError("candidate hidden pooling failed") from error

    def forward(self, batch: TrainingBatch) -> TrainingAdapterOutput:
        if not isinstance(batch, TrainingBatch):
            raise TrainingAdapterError("forward requires a TrainingBatch")
        source_hidden = self._encode(batch.input_ids, batch.attention_mask)
        candidate_hidden = self._candidate_hidden(batch)
        original = self.core(
            source_hidden,
            batch.event_token_mask,
            batch.event_mask,
            candidate_hidden,
            batch.candidate_mask,
        )
        counterfactual = None
        if batch.has_counterfactual:
            cf_hidden = self._encode(
                batch.counterfactual_input_ids,
                batch.counterfactual_attention_mask,
            )
            counterfactual = self.core(
                cf_hidden,
                batch.counterfactual_event_token_mask,
                batch.counterfactual_event_mask,
                candidate_hidden,
                batch.candidate_mask,
            )
        try:
            losses = kairos_loss(
                original.candidate_scores,
                batch.candidate_mask,
                batch.answer_targets,
                original.relation_logits,
                original.pair_mask,
                batch.relation_targets,
                None if counterfactual is None else counterfactual.relation_logits,
                None if counterfactual is None else counterfactual.pair_mask,
                batch.counterfactual_relation_targets,
                lambda_relation=1.0,
                lambda_counterfactual=1.0,
            )
        except ValueError as error:
            raise TrainingAdapterError("Kairos loss contract failed") from error
        return TrainingAdapterOutput(original, counterfactual, losses)


def trainable_state_dict(module: nn.Module) -> Mapping[str, Tensor]:
    """Clone only requires-grad parameters for a later immutable checkpoint layer."""

    if not isinstance(module, nn.Module):
        raise TrainingAdapterError("trainable state source must be an nn.Module")
    state = {
        name: parameter.detach().cpu().clone()
        for name, parameter in module.named_parameters()
        if parameter.requires_grad
    }
    if not state:
        raise TrainingAdapterError("module has no trainable parameters")
    return state


def load_trainable_state_dict(module: nn.Module, state: Mapping[str, Tensor]) -> None:
    """Strictly restore the exact requires-grad parameter set in memory."""

    if not isinstance(module, nn.Module) or not isinstance(state, MappingABC):
        raise TrainingAdapterError("trainable state restore inputs are invalid")
    expected = {
        name: parameter
        for name, parameter in module.named_parameters()
        if parameter.requires_grad
    }
    if set(state) != set(expected):
        raise TrainingAdapterError("trainable state keys differ")
    for name, parameter in expected.items():
        value = state[name]
        if (
            not isinstance(value, Tensor)
            or value.device.type != "cpu"
            or value.shape != parameter.shape
            or value.dtype != parameter.dtype
            or (value.is_floating_point() and not torch.isfinite(value).all())
        ):
            raise TrainingAdapterError("trainable state tensor differs")
    with torch.no_grad():
        for name, parameter in expected.items():
            parameter.copy_(state[name].to(device=parameter.device))


__all__ = (
    "LORA_TARGET_MODULES",
    "LoraSpec",
    "QwenCoreTrainingAdapter",
    "TrainingAdapterError",
    "TrainingAdapterOutput",
    "TrainingBatch",
    "load_trainable_state_dict",
    "trainable_state_dict",
    "validate_lora_targets",
)
