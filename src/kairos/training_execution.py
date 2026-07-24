"""Synthetic-only optimizer, schedule, and resumable checkpoint execution."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
import copy
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import re
import stat
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor, nn

from .ids import canonical_json
from .training_adapter import (
    QwenCoreTrainingAdapter,
    TrainingAdapterError,
    TrainingBatch,
    load_trainable_state_dict,
    trainable_state_dict,
)


_ALLOWED_ROOT = Path("/data0/hk_data/kairos-zx")
_CONFIG_NAME = "config.json"
_STATE_NAME = "state.pt"
_MANIFEST_NAME = "manifest.json"
_FINAL_NAMES = frozenset({_CONFIG_NAME, _STATE_NAME, _MANIFEST_NAME})
_CONFIG_SCHEMA = "training-execution-config-v1"
_STATE_SCHEMA = "training-checkpoint-state-v1"
_MANIFEST_SCHEMA = "training-checkpoint-manifest-v1"
_STATUS = "TRAINING_CHECKPOINT_COMPLETE"
_CONFIG_LIMIT = 1_048_576
_STATE_LIMIT = 2 * 1024 * 1024 * 1024
_MANIFEST_LIMIT = 1_048_576
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_CHECKPOINT_ID = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
)
_SEEDS = frozenset({13, 42, 2026})
_MICRO_BATCHES = frozenset({1, 2, 4, 8, 16, 32})
_OPTIMIZER_GROUPS = ("lora", "temporal_heads")


class TrainingExecutionError(ValueError):
    """A frozen optimizer, execution, checkpoint, or resume invariant failed."""


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrainingExecutionError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise TrainingExecutionError(f"{name} is outside its allowed range")
    return value


def _exact_float(value: Any, expected: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, float) or value != expected:
        raise TrainingExecutionError(f"{name} differs from the frozen value")
    return value


def _exact_mapping(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC) or any(
        not isinstance(key, str) for key in value
    ):
        raise TrainingExecutionError(f"{name} must be a string-keyed mapping")
    missing = expected.difference(value)
    extra = set(value).difference(expected)
    if missing or extra:
        raise TrainingExecutionError(
            f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


@dataclass(frozen=True)
class TrainingExecutionConfig:
    seed: int
    micro_batch_size: int
    gradient_accumulation_steps: int
    total_optimizer_steps: int
    max_epochs: int = 3
    lora_learning_rate: float = 2e-5
    temporal_head_learning_rate: float = 2e-4
    weight_decay: float = 0.01
    warmup_ratio: float = 0.05
    gradient_clip_norm: float = 1.0
    adam_beta1: float = 0.9
    adam_beta2: float = 0.999
    adam_epsilon: float = 1e-8
    amp_dtype: str = "bfloat16"
    grad_scaler_enabled: bool = False

    def __post_init__(self) -> None:
        if self.seed not in _SEEDS:
            raise TrainingExecutionError("seed is not one of the frozen seeds")
        if self.micro_batch_size not in _MICRO_BATCHES:
            raise TrainingExecutionError("micro batch size is not a frozen divisor")
        expected_accumulation = 32 // self.micro_batch_size
        if (
            isinstance(self.gradient_accumulation_steps, bool)
            or self.gradient_accumulation_steps != expected_accumulation
        ):
            raise TrainingExecutionError("effective batch size must equal 32")
        _integer(self.total_optimizer_steps, "total optimizer steps", 1, 10_000_000)
        if self.max_epochs != 3:
            raise TrainingExecutionError("max epochs differs from the frozen value")
        _exact_float(self.lora_learning_rate, 2e-5, "LoRA learning rate")
        _exact_float(
            self.temporal_head_learning_rate,
            2e-4,
            "temporal head learning rate",
        )
        _exact_float(self.weight_decay, 0.01, "weight decay")
        _exact_float(self.warmup_ratio, 0.05, "warmup ratio")
        _exact_float(self.gradient_clip_norm, 1.0, "gradient clip norm")
        _exact_float(self.adam_beta1, 0.9, "Adam beta1")
        _exact_float(self.adam_beta2, 0.999, "Adam beta2")
        _exact_float(self.adam_epsilon, 1e-8, "Adam epsilon")
        if self.amp_dtype != "bfloat16" or self.grad_scaler_enabled is not False:
            raise TrainingExecutionError("AMP contract differs from frozen BF16")

    @property
    def effective_batch_size(self) -> int:
        return self.micro_batch_size * self.gradient_accumulation_steps

    @property
    def warmup_steps(self) -> int:
        return math.floor(self.total_optimizer_steps * self.warmup_ratio)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": _CONFIG_SCHEMA,
            "seed": self.seed,
            "micro_batch_size": self.micro_batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "effective_batch_size": self.effective_batch_size,
            "total_optimizer_steps": self.total_optimizer_steps,
            "max_epochs": self.max_epochs,
            "optimizer": {
                "name": "AdamW",
                "lora_learning_rate": self.lora_learning_rate,
                "temporal_head_learning_rate": self.temporal_head_learning_rate,
                "weight_decay": self.weight_decay,
                "betas": [self.adam_beta1, self.adam_beta2],
                "epsilon": self.adam_epsilon,
            },
            "scheduler": {
                "name": "linear-warmup-decay-v1",
                "warmup_ratio": self.warmup_ratio,
                "warmup_steps": self.warmup_steps,
            },
            "gradient_clip_norm": self.gradient_clip_norm,
            "amp_dtype": self.amp_dtype,
            "grad_scaler_enabled": self.grad_scaler_enabled,
            "checkpoint_boundary": "optimizer-step-only",
        }


@dataclass(frozen=True)
class TrainingProgress:
    epoch: int
    next_micro_batch_index: int
    optimizer_steps_completed: int
    samples_seen: int

    @classmethod
    def initial(cls) -> "TrainingProgress":
        return cls(0, 0, 0, 0)

    def validate(self, config: TrainingExecutionConfig) -> None:
        if not isinstance(config, TrainingExecutionConfig):
            raise TrainingExecutionError("progress requires a frozen configuration")
        _integer(self.epoch, "epoch", 0, config.max_epochs)
        _integer(
            self.optimizer_steps_completed,
            "optimizer steps completed",
            0,
            config.total_optimizer_steps,
        )
        expected_micro_batches = (
            self.optimizer_steps_completed * config.gradient_accumulation_steps
        )
        if self.next_micro_batch_index != expected_micro_batches:
            raise TrainingExecutionError("progress is not at an accumulation boundary")
        expected_samples = self.next_micro_batch_index * config.micro_batch_size
        if self.samples_seen != expected_samples:
            raise TrainingExecutionError("progress sample count differs from its cursor")

    def to_dict(self) -> Mapping[str, int]:
        return {
            "epoch": self.epoch,
            "next_micro_batch_index": self.next_micro_batch_index,
            "optimizer_steps_completed": self.optimizer_steps_completed,
            "samples_seen": self.samples_seen,
        }


@dataclass(frozen=True)
class TrainingStepResult:
    progress: TrainingProgress
    optimizer_losses: tuple[float, ...]
    gradient_norms: tuple[float, ...]


@dataclass(frozen=True)
class VerifiedTrainingCheckpoint:
    checkpoint_id: str
    execution_commit: str
    config: TrainingExecutionConfig
    progress: TrainingProgress
    config_sha256: str
    state_sha256: str
    manifest_sha256: str
    artifact_path: Path


def _lora_name(name: str) -> bool:
    return any(component.startswith("lora_") for component in name.split("."))


def build_optimizer(
    adapter: QwenCoreTrainingAdapter,
    config: TrainingExecutionConfig,
) -> torch.optim.AdamW:
    """Build the only accepted two-group AdamW optimizer."""

    if not isinstance(adapter, QwenCoreTrainingAdapter) or not isinstance(
        config, TrainingExecutionConfig
    ):
        raise TrainingExecutionError("optimizer inputs are invalid")
    lora: list[nn.Parameter] = []
    heads: list[nn.Parameter] = []
    assigned: set[int] = set()
    for name, parameter in adapter.backbone.named_parameters():
        if not parameter.requires_grad:
            continue
        if not _lora_name(name):
            raise TrainingExecutionError("trainable backbone parameter is not LoRA")
        if id(parameter) in assigned:
            raise TrainingExecutionError("trainable parameter is assigned more than once")
        assigned.add(id(parameter))
        lora.append(parameter)
    for parameter in adapter.core.parameters():
        if not parameter.requires_grad:
            continue
        if id(parameter) in assigned:
            raise TrainingExecutionError("trainable parameter is assigned more than once")
        assigned.add(id(parameter))
        heads.append(parameter)
    expected = {
        id(parameter)
        for parameter in adapter.parameters()
        if parameter.requires_grad
    }
    if not lora or not heads or assigned != expected:
        raise TrainingExecutionError("optimizer groups are empty or incomplete")
    return torch.optim.AdamW(
        [
            {
                "params": lora,
                "lr": config.lora_learning_rate,
                "weight_decay": config.weight_decay,
                "group_name": _OPTIMIZER_GROUPS[0],
            },
            {
                "params": heads,
                "lr": config.temporal_head_learning_rate,
                "weight_decay": config.weight_decay,
                "group_name": _OPTIMIZER_GROUPS[1],
            },
        ],
        betas=(config.adam_beta1, config.adam_beta2),
        eps=config.adam_epsilon,
        foreach=False,
    )


def _optimizer_group_names(optimizer: torch.optim.Optimizer) -> tuple[str, ...]:
    names = tuple(group.get("group_name") for group in optimizer.param_groups)
    if names != _OPTIMIZER_GROUPS:
        raise TrainingExecutionError("optimizer group names or order differ")
    return names


def build_scheduler(
    optimizer: torch.optim.Optimizer,
    config: TrainingExecutionConfig,
) -> torch.optim.lr_scheduler.LambdaLR:
    """Build the frozen linear warmup/decay schedule."""

    if not isinstance(optimizer, torch.optim.Optimizer) or not isinstance(
        config, TrainingExecutionConfig
    ):
        raise TrainingExecutionError("scheduler inputs are invalid")
    _optimizer_group_names(optimizer)
    warmup = config.warmup_steps
    total = config.total_optimizer_steps

    def factor(current_step: int) -> float:
        if warmup > 0 and current_step < warmup:
            return float(current_step) / float(max(1, warmup))
        return max(
            0.0,
            float(total - current_step) / float(max(1, total - warmup)),
        )

    return torch.optim.lr_scheduler.LambdaLR(optimizer, (factor, factor))


def seed_training(seed: int, dataloader_generator: torch.Generator) -> None:
    """Seed Python, Torch, initialized CUDA devices, and one loader generator."""

    if seed not in _SEEDS or not isinstance(dataloader_generator, torch.Generator):
        raise TrainingExecutionError("training seed inputs are invalid")
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_initialized():
        torch.cuda.manual_seed_all(seed)
    dataloader_generator.manual_seed(seed)


def _trainable_parameters(module: nn.Module) -> list[nn.Parameter]:
    parameters = [parameter for parameter in module.parameters() if parameter.requires_grad]
    if not parameters:
        raise TrainingExecutionError("module has no trainable parameters")
    return parameters


def run_optimizer_steps(
    adapter: QwenCoreTrainingAdapter,
    batches: Sequence[TrainingBatch],
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    config: TrainingExecutionConfig,
    progress: TrainingProgress,
    optimizer_steps: int,
) -> TrainingStepResult:
    """Run complete accumulation windows from one deterministic batch sequence."""

    if not isinstance(adapter, QwenCoreTrainingAdapter):
        raise TrainingExecutionError("training requires a Qwen core adapter")
    if isinstance(batches, (str, bytes, bytearray)) or not isinstance(
        batches, SequenceABC
    ):
        raise TrainingExecutionError("batches must be a sequence")
    if not isinstance(optimizer, torch.optim.Optimizer) or not isinstance(
        scheduler, torch.optim.lr_scheduler.LRScheduler
    ):
        raise TrainingExecutionError("optimizer or scheduler is invalid")
    if not isinstance(config, TrainingExecutionConfig) or not isinstance(
        progress, TrainingProgress
    ):
        raise TrainingExecutionError("execution configuration or progress is invalid")
    progress.validate(config)
    _optimizer_group_names(optimizer)
    _integer(optimizer_steps, "requested optimizer steps", 1, config.total_optimizer_steps)
    if progress.optimizer_steps_completed + optimizer_steps > config.total_optimizer_steps:
        raise TrainingExecutionError("requested steps exceed the frozen total")
    required_end = progress.next_micro_batch_index + (
        optimizer_steps * config.gradient_accumulation_steps
    )
    if required_end > len(batches):
        raise TrainingExecutionError("batch sequence does not cover requested steps")
    parameters = _trainable_parameters(adapter)
    devices = {parameter.device for parameter in parameters}
    if len(devices) != 1:
        raise TrainingExecutionError("trainable parameters span multiple devices")
    device = next(iter(devices))
    if device.type not in {"cpu", "cuda"}:
        raise TrainingExecutionError("BF16 execution device is unsupported")
    if any(parameter.grad is not None for parameter in parameters):
        raise TrainingExecutionError("execution must start at a zero-gradient boundary")

    adapter.train()
    optimizer_losses: list[float] = []
    gradient_norms: list[float] = []
    cursor = progress.next_micro_batch_index
    steps_completed = progress.optimizer_steps_completed
    optimizer.zero_grad(set_to_none=True)
    for _ in range(optimizer_steps):
        accumulated_loss = 0.0
        for _ in range(config.gradient_accumulation_steps):
            batch = batches[cursor]
            if not isinstance(batch, TrainingBatch):
                raise TrainingExecutionError("batch sequence contains an invalid item")
            if batch.input_ids.shape[0] != config.micro_batch_size:
                raise TrainingExecutionError("batch size differs from the frozen micro batch")
            if batch.input_ids.device != device:
                raise TrainingExecutionError("batch and adapter devices differ")
            try:
                with torch.autocast(
                    device_type=device.type,
                    dtype=torch.bfloat16,
                    enabled=True,
                ):
                    output = adapter(batch)
                    loss = output.losses["loss"]
                if not isinstance(loss, Tensor) or loss.ndim != 0 or not torch.isfinite(loss):
                    raise TrainingExecutionError("training loss is invalid")
                accumulated_loss += float(loss.detach().cpu())
                (loss / config.gradient_accumulation_steps).backward()
            except TrainingAdapterError as error:
                raise TrainingExecutionError("training adapter failed") from error
            cursor += 1
        norm = torch.nn.utils.clip_grad_norm_(
            parameters,
            config.gradient_clip_norm,
            error_if_nonfinite=True,
        )
        if not torch.isfinite(norm):
            raise TrainingExecutionError("gradient norm is not finite")
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        steps_completed += 1
        optimizer_losses.append(accumulated_loss / config.gradient_accumulation_steps)
        gradient_norms.append(float(norm.detach().cpu()))

    result_progress = TrainingProgress(
        epoch=progress.epoch,
        next_micro_batch_index=cursor,
        optimizer_steps_completed=steps_completed,
        samples_seen=cursor * config.micro_batch_size,
    )
    result_progress.validate(config)
    return TrainingStepResult(
        result_progress,
        tuple(optimizer_losses),
        tuple(gradient_norms),
    )


def _clone_to_cpu(value: Any) -> Any:
    if isinstance(value, Tensor):
        if value.is_floating_point() and not torch.isfinite(value).all():
            raise TrainingExecutionError("state contains a non-finite tensor")
        return value.detach().cpu().clone()
    if isinstance(value, MappingABC):
        return {key: _clone_to_cpu(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_to_cpu(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_to_cpu(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise TrainingExecutionError("state contains a non-finite scalar")
        return value
    raise TrainingExecutionError("state contains an unsupported object")


def _python_rng_payload() -> Mapping[str, Any]:
    version, internal, gaussian = random.getstate()
    return {
        "version": version,
        "internal_state": list(internal),
        "gaussian_next": gaussian,
    }


def _capture_rng(dataloader_generator: torch.Generator) -> Mapping[str, Any]:
    if not isinstance(dataloader_generator, torch.Generator):
        raise TrainingExecutionError("dataloader generator is invalid")
    cuda_initialized = torch.cuda.is_initialized()
    return {
        "python": _python_rng_payload(),
        "torch_cpu": torch.get_rng_state().cpu().clone(),
        "cuda_initialized": cuda_initialized,
        "torch_cuda": (
            [state.cpu().clone() for state in torch.cuda.get_rng_state_all()]
            if cuda_initialized
            else []
        ),
        "dataloader": dataloader_generator.get_state().cpu().clone(),
    }


def _python_state(value: Any) -> tuple[Any, ...]:
    value = _exact_mapping(
        value,
        {"version", "internal_state", "gaussian_next"},
        "Python RNG state",
    )
    version = _integer(value["version"], "Python RNG version", 1, 10)
    internal = value["internal_state"]
    if isinstance(internal, (str, bytes, bytearray)) or not isinstance(
        internal, SequenceABC
    ):
        raise TrainingExecutionError("Python RNG internal state is invalid")
    internal_values = tuple(
        _integer(item, "Python RNG word", 0, 2**32 - 1) for item in internal
    )
    if len(internal_values) < 2 or len(internal_values) > 10_000:
        raise TrainingExecutionError("Python RNG internal state length is invalid")
    gaussian = value["gaussian_next"]
    if gaussian is not None and (
        isinstance(gaussian, bool)
        or not isinstance(gaussian, (int, float))
        or not math.isfinite(float(gaussian))
    ):
        raise TrainingExecutionError("Python RNG Gaussian state is invalid")
    state = (version, internal_values, gaussian)
    validator = random.Random()
    try:
        validator.setstate(state)
    except (TypeError, ValueError) as error:
        raise TrainingExecutionError("Python RNG state is not restorable") from error
    return state


def _rng_restore_values(
    value: Any, *, require_cuda_runtime: bool = False
) -> Mapping[str, Any]:
    value = _exact_mapping(
        value,
        {"python", "torch_cpu", "cuda_initialized", "torch_cuda", "dataloader"},
        "RNG state",
    )
    python_state = _python_state(value["python"])

    def byte_state(item: Any, name: str) -> Tensor:
        if (
            not isinstance(item, Tensor)
            or item.device.type != "cpu"
            or item.dtype != torch.uint8
            or item.ndim != 1
            or item.numel() < 1
        ):
            raise TrainingExecutionError(f"{name} is invalid")
        return item.clone()

    torch_cpu = byte_state(value["torch_cpu"], "Torch CPU RNG state")
    dataloader = byte_state(value["dataloader"], "dataloader RNG state")
    cuda_initialized = value["cuda_initialized"]
    if not isinstance(cuda_initialized, bool):
        raise TrainingExecutionError("CUDA RNG initialized flag is invalid")
    cuda_values = value["torch_cuda"]
    if isinstance(cuda_values, (str, bytes, bytearray)) or not isinstance(
        cuda_values, SequenceABC
    ):
        raise TrainingExecutionError("CUDA RNG state list is invalid")
    cuda_states = [byte_state(item, "CUDA RNG state") for item in cuda_values]
    if bool(cuda_states) != cuda_initialized:
        raise TrainingExecutionError("CUDA RNG state and initialized flag differ")
    if require_cuda_runtime and cuda_initialized and not torch.cuda.is_initialized():
        raise TrainingExecutionError("checkpoint requires initialized CUDA RNG")
    if (
        require_cuda_runtime
        and cuda_initialized
        and len(cuda_states) != torch.cuda.device_count()
    ):
        raise TrainingExecutionError("CUDA RNG device count differs")
    loader_validator = torch.Generator(device="cpu")
    try:
        loader_validator.set_state(dataloader)
    except RuntimeError as error:
        raise TrainingExecutionError("dataloader RNG state is not restorable") from error
    return {
        "python": python_state,
        "torch_cpu": torch_cpu,
        "torch_cuda": cuda_states,
        "dataloader": dataloader,
    }


def _restore_rng(values: Mapping[str, Any], generator: torch.Generator) -> None:
    random.setstate(values["python"])
    torch.set_rng_state(values["torch_cpu"])
    if values["torch_cuda"]:
        torch.cuda.set_rng_state_all(values["torch_cuda"])
    generator.set_state(values["dataloader"])


def _config_bytes(config: TrainingExecutionConfig) -> bytes:
    if not isinstance(config, TrainingExecutionConfig):
        raise TrainingExecutionError("checkpoint configuration is invalid")
    payload = canonical_json(config.to_dict()).encode("utf-8") + b"\n"
    if len(payload) > _CONFIG_LIMIT:
        raise TrainingExecutionError("checkpoint configuration is too large")
    return payload


def _state_payload(
    adapter: QwenCoreTrainingAdapter,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    progress: TrainingProgress,
    dataloader_generator: torch.Generator,
) -> Mapping[str, Any]:
    parameters = _trainable_parameters(adapter)
    if any(parameter.grad is not None for parameter in parameters):
        raise TrainingExecutionError("checkpoint requires a zero-gradient boundary")
    _optimizer_group_names(optimizer)
    return {
        "schema_version": _STATE_SCHEMA,
        "trainable_state": trainable_state_dict(adapter),
        "optimizer_state": _clone_to_cpu(optimizer.state_dict()),
        "scheduler_state": _clone_to_cpu(scheduler.state_dict()),
        "optimizer_group_names": list(_OPTIMIZER_GROUPS),
        "rng": _capture_rng(dataloader_generator),
        "progress": dict(progress.to_dict()),
    }


def _serialize_state(value: Mapping[str, Any]) -> bytes:
    buffer = io.BytesIO()
    try:
        torch.save(value, buffer)
    except (RuntimeError, TypeError, ValueError) as error:
        raise TrainingExecutionError("checkpoint state serialization failed") from error
    payload = buffer.getvalue()
    if not payload or len(payload) > _STATE_LIMIT:
        raise TrainingExecutionError("checkpoint state size is invalid")
    return payload


def _parse_config(payload: bytes) -> TrainingExecutionConfig:
    value = _canonical_object(payload, "checkpoint config")
    value = _exact_mapping(
        value,
        {
            "schema_version", "seed", "micro_batch_size",
            "gradient_accumulation_steps", "effective_batch_size",
            "total_optimizer_steps", "max_epochs", "optimizer", "scheduler",
            "gradient_clip_norm", "amp_dtype", "grad_scaler_enabled",
            "checkpoint_boundary",
        },
        "checkpoint config",
    )
    optimizer = _exact_mapping(
        value["optimizer"],
        {
            "name", "lora_learning_rate", "temporal_head_learning_rate",
            "weight_decay", "betas", "epsilon",
        },
        "checkpoint optimizer config",
    )
    scheduler = _exact_mapping(
        value["scheduler"],
        {"name", "warmup_ratio", "warmup_steps"},
        "checkpoint scheduler config",
    )
    betas = optimizer["betas"]
    if isinstance(betas, (str, bytes, bytearray)) or not isinstance(
        betas, SequenceABC
    ) or len(betas) != 2:
        raise TrainingExecutionError("checkpoint Adam betas are invalid")
    config = TrainingExecutionConfig(
        seed=value["seed"],
        micro_batch_size=value["micro_batch_size"],
        gradient_accumulation_steps=value["gradient_accumulation_steps"],
        total_optimizer_steps=value["total_optimizer_steps"],
        max_epochs=value["max_epochs"],
        lora_learning_rate=optimizer["lora_learning_rate"],
        temporal_head_learning_rate=optimizer["temporal_head_learning_rate"],
        weight_decay=optimizer["weight_decay"],
        warmup_ratio=scheduler["warmup_ratio"],
        gradient_clip_norm=value["gradient_clip_norm"],
        adam_beta1=betas[0],
        adam_beta2=betas[1],
        adam_epsilon=optimizer["epsilon"],
        amp_dtype=value["amp_dtype"],
        grad_scaler_enabled=value["grad_scaler_enabled"],
    )
    if (
        value["schema_version"] != _CONFIG_SCHEMA
        or value["effective_batch_size"] != 32
        or optimizer["name"] != "AdamW"
        or scheduler["name"] != "linear-warmup-decay-v1"
        or scheduler["warmup_steps"] != config.warmup_steps
        or value["checkpoint_boundary"] != "optimizer-step-only"
        or canonical_json(config.to_dict()).encode("utf-8") + b"\n" != payload
    ):
        raise TrainingExecutionError("checkpoint config fixed values differ")
    return config


def _progress_from_mapping(
    value: Any, config: TrainingExecutionConfig
) -> TrainingProgress:
    value = _exact_mapping(
        value,
        {"epoch", "next_micro_batch_index", "optimizer_steps_completed", "samples_seen"},
        "checkpoint progress",
    )
    progress = TrainingProgress(
        epoch=value["epoch"],
        next_micro_batch_index=value["next_micro_batch_index"],
        optimizer_steps_completed=value["optimizer_steps_completed"],
        samples_seen=value["samples_seen"],
    )
    progress.validate(config)
    return progress


def _strict_json(payload: bytes, name: str) -> Any:
    duplicates: list[str] = []

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    def reject_constant(unused: str) -> Any:
        raise TrainingExecutionError(f"{name} contains a non-finite number")

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainingExecutionError(f"{name} is not strict UTF-8 JSON") from error
    if duplicates:
        raise TrainingExecutionError(f"{name} contains duplicate keys")
    return value


def _canonical_object(payload: bytes, name: str) -> Mapping[str, Any]:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise TrainingExecutionError(f"{name} is not one LF-terminated object")
    value = _strict_json(payload[:-1], name)
    if not isinstance(value, MappingABC):
        raise TrainingExecutionError(f"{name} must be an object")
    if canonical_json(value).encode("utf-8") + b"\n" != payload:
        raise TrainingExecutionError(f"{name} is not canonical JSON")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        os.fspath(path),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        os.fspath(path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise OSError("checkpoint write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _within_allowed(path: Path) -> None:
    if not path.is_absolute():
        raise TrainingExecutionError("checkpoint root must be absolute")
    try:
        relative = path.relative_to(_ALLOWED_ROOT)
    except ValueError as error:
        raise TrainingExecutionError("checkpoint root is outside the project data root") from error
    try:
        allowed_status = _ALLOWED_ROOT.lstat()
    except FileNotFoundError as error:
        raise TrainingExecutionError("project data root is absent") from error
    if stat.S_ISLNK(allowed_status.st_mode) or not stat.S_ISDIR(allowed_status.st_mode):
        raise TrainingExecutionError("project data root is not a real directory")
    current = _ALLOWED_ROOT
    for component in relative.parts:
        current = current / component
        try:
            status = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise TrainingExecutionError("checkpoint path contains a non-directory or symlink")


def _prepare_root(root: Path) -> None:
    _within_allowed(root)
    try:
        status = root.lstat()
    except FileNotFoundError:
        parent = root.parent
        _within_allowed(parent)
        if not parent.is_dir():
            raise TrainingExecutionError("checkpoint root parent is absent")
        try:
            root.mkdir(mode=0o700)
        except OSError as error:
            raise TrainingExecutionError("cannot create checkpoint root") from error
        _fsync_directory(parent)
        status = root.lstat()
    if (
        not stat.S_ISDIR(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or stat.S_IMODE(status.st_mode) != 0o700
    ):
        raise TrainingExecutionError("checkpoint root must be a private directory")


def _read_file(path: Path, limit: int, name: str) -> bytes:
    try:
        descriptor = os.open(
            os.fspath(path),
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as error:
        raise TrainingExecutionError(f"cannot open checkpoint {name}") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > limit
        ):
            raise TrainingExecutionError(f"checkpoint {name} metadata is invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1_048_576, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise TrainingExecutionError(f"checkpoint {name} exceeds its byte limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        fields = (
            "st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
            "st_mtime_ns", "st_ctime_ns",
        )
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise TrainingExecutionError(f"checkpoint {name} changed while reading")
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _manifest(
    checkpoint_id: str,
    execution_commit: str,
    config: bytes,
    state: bytes,
    progress: TrainingProgress,
) -> Mapping[str, Any]:
    return {
        "schema_version": _MANIFEST_SCHEMA,
        "status": _STATUS,
        "checkpoint_id": checkpoint_id,
        "execution_commit": execution_commit,
        "files": [_CONFIG_NAME, _STATE_NAME, _MANIFEST_NAME],
        "config": {
            "path": _CONFIG_NAME,
            "sha256": hashlib.sha256(config).hexdigest(),
            "byte_size": len(config),
        },
        "state": {
            "path": _STATE_NAME,
            "sha256": hashlib.sha256(state).hexdigest(),
            "byte_size": len(state),
        },
        "progress": dict(progress.to_dict()),
    }


def save_training_checkpoint(
    root: Path,
    checkpoint_id: str,
    execution_commit: str,
    config: TrainingExecutionConfig,
    adapter: QwenCoreTrainingAdapter,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    progress: TrainingProgress,
    dataloader_generator: torch.Generator,
) -> VerifiedTrainingCheckpoint:
    """Publish one optimizer-boundary checkpoint without replacement."""

    root = Path(root)
    if not isinstance(checkpoint_id, str) or not _CHECKPOINT_ID.fullmatch(checkpoint_id):
        raise TrainingExecutionError("checkpoint ID is invalid")
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        raise TrainingExecutionError("execution commit is invalid")
    if not isinstance(config, TrainingExecutionConfig) or not isinstance(
        progress, TrainingProgress
    ):
        raise TrainingExecutionError("checkpoint config or progress is invalid")
    progress.validate(config)
    config_payload = _config_bytes(config)
    state_payload = _serialize_state(
        _state_payload(
            adapter,
            optimizer,
            scheduler,
            progress,
            dataloader_generator,
        )
    )
    manifest_payload = canonical_json(
        _manifest(
            checkpoint_id,
            execution_commit,
            config_payload,
            state_payload,
            progress,
        )
    ).encode("utf-8") + b"\n"
    if len(manifest_payload) > _MANIFEST_LIMIT:
        raise TrainingExecutionError("checkpoint manifest is too large")
    _prepare_root(root)
    target = root / checkpoint_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as error:
        raise TrainingExecutionError("checkpoint already exists") from error
    except OSError as error:
        raise TrainingExecutionError("cannot create checkpoint directory") from error
    _write_exclusive(target / _CONFIG_NAME, config_payload)
    _write_exclusive(target / _STATE_NAME, state_payload)
    _fsync_directory(target)
    _write_exclusive(target / _MANIFEST_NAME, manifest_payload)
    _fsync_directory(target)
    _fsync_directory(root)
    return verify_training_checkpoint(root, checkpoint_id)


def verify_training_checkpoint(
    root: Path, checkpoint_id: str
) -> VerifiedTrainingCheckpoint:
    """Verify namespace, canonical metadata, hashes, and restricted state load."""

    root = Path(root)
    if not isinstance(checkpoint_id, str) or not _CHECKPOINT_ID.fullmatch(checkpoint_id):
        raise TrainingExecutionError("checkpoint ID is invalid")
    _prepare_root(root)
    target = root / checkpoint_id
    try:
        target_status = target.lstat()
    except FileNotFoundError as error:
        raise TrainingExecutionError("checkpoint directory is absent") from error
    if (
        not stat.S_ISDIR(target_status.st_mode)
        or stat.S_ISLNK(target_status.st_mode)
        or stat.S_IMODE(target_status.st_mode) != 0o700
    ):
        raise TrainingExecutionError("checkpoint directory metadata is invalid")
    names = {entry.name for entry in target.iterdir()}
    if names != _FINAL_NAMES:
        raise TrainingExecutionError("checkpoint namespace is incomplete or contains extras")
    config_payload = _read_file(target / _CONFIG_NAME, _CONFIG_LIMIT, _CONFIG_NAME)
    state_payload = _read_file(target / _STATE_NAME, _STATE_LIMIT, _STATE_NAME)
    manifest_payload = _read_file(
        target / _MANIFEST_NAME, _MANIFEST_LIMIT, _MANIFEST_NAME
    )
    config = _parse_config(config_payload)
    manifest = _exact_mapping(
        _canonical_object(manifest_payload, "checkpoint manifest"),
        {
            "schema_version", "status", "checkpoint_id", "execution_commit",
            "files", "config", "state", "progress",
        },
        "checkpoint manifest",
    )
    if (
        manifest["schema_version"] != _MANIFEST_SCHEMA
        or manifest["status"] != _STATUS
        or manifest["checkpoint_id"] != checkpoint_id
        or not isinstance(manifest["execution_commit"], str)
        or not _HEX40.fullmatch(manifest["execution_commit"])
        or manifest["files"] != [_CONFIG_NAME, _STATE_NAME, _MANIFEST_NAME]
    ):
        raise TrainingExecutionError("checkpoint manifest fixed values differ")
    for key, name, payload in (
        ("config", _CONFIG_NAME, config_payload),
        ("state", _STATE_NAME, state_payload),
    ):
        binding = _exact_mapping(
            manifest[key], {"path", "sha256", "byte_size"}, f"manifest {key}"
        )
        if (
            binding["path"] != name
            or binding["sha256"] != hashlib.sha256(payload).hexdigest()
            or binding["byte_size"] != len(payload)
        ):
            raise TrainingExecutionError(f"checkpoint {key} binding differs")
    progress = _progress_from_mapping(manifest["progress"], config)
    state = _load_state_payload(state_payload)
    if state["progress"] != dict(progress.to_dict()):
        raise TrainingExecutionError("state and manifest progress differ")
    _rng_restore_values(state["rng"])
    return VerifiedTrainingCheckpoint(
        checkpoint_id=checkpoint_id,
        execution_commit=manifest["execution_commit"],
        config=config,
        progress=progress,
        config_sha256=hashlib.sha256(config_payload).hexdigest(),
        state_sha256=hashlib.sha256(state_payload).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_path=target,
    )


def _load_state_payload(payload: bytes) -> Mapping[str, Any]:
    try:
        value = torch.load(
            io.BytesIO(payload),
            map_location="cpu",
            weights_only=True,
        )
    except Exception as error:
        raise TrainingExecutionError("checkpoint state restricted load failed") from error
    _validate_loaded_state(value)
    value = _exact_mapping(
        value,
        {
            "schema_version", "trainable_state", "optimizer_state",
            "scheduler_state", "optimizer_group_names", "rng", "progress",
        },
        "checkpoint state",
    )
    if value["schema_version"] != _STATE_SCHEMA:
        raise TrainingExecutionError("checkpoint state schema differs")
    if value["optimizer_group_names"] != list(_OPTIMIZER_GROUPS):
        raise TrainingExecutionError("checkpoint optimizer groups differ")
    if not isinstance(value["trainable_state"], MappingABC):
        raise TrainingExecutionError("checkpoint trainable state is invalid")
    if not isinstance(value["optimizer_state"], MappingABC) or not isinstance(
        value["scheduler_state"], MappingABC
    ):
        raise TrainingExecutionError("checkpoint optimizer or scheduler state is invalid")
    if not isinstance(value["progress"], MappingABC):
        raise TrainingExecutionError("checkpoint progress state is invalid")
    return value


def _validate_loaded_state(value: Any) -> None:
    if isinstance(value, Tensor):
        if value.device.type != "cpu":
            raise TrainingExecutionError("loaded checkpoint tensor is not on CPU")
        if value.is_floating_point() and not torch.isfinite(value).all():
            raise TrainingExecutionError("loaded checkpoint tensor is non-finite")
        return
    if isinstance(value, MappingABC):
        for key, item in value.items():
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise TrainingExecutionError("loaded checkpoint mapping key is invalid")
            _validate_loaded_state(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_loaded_state(item)
        return
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise TrainingExecutionError("loaded checkpoint object is unsupported or non-finite")


def _validate_trainable_state(module: nn.Module, state: Mapping[str, Tensor]) -> None:
    expected = {
        name: parameter
        for name, parameter in module.named_parameters()
        if parameter.requires_grad
    }
    if set(state) != set(expected):
        raise TrainingExecutionError("checkpoint trainable keys differ")
    for name, parameter in expected.items():
        value = state[name]
        if (
            not isinstance(value, Tensor)
            or value.device.type != "cpu"
            or value.shape != parameter.shape
            or value.dtype != parameter.dtype
            or (value.is_floating_point() and not torch.isfinite(value).all())
        ):
            raise TrainingExecutionError("checkpoint trainable tensor differs")


def _validate_state_for_resume(
    state: Mapping[str, Any],
    config: TrainingExecutionConfig,
    adapter: QwenCoreTrainingAdapter,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
) -> tuple[TrainingProgress, Mapping[str, Any]]:
    progress = _progress_from_mapping(state["progress"], config)
    _validate_trainable_state(adapter, state["trainable_state"])
    if state["optimizer_group_names"] != list(_optimizer_group_names(optimizer)):
        raise TrainingExecutionError("resume optimizer groups differ")
    parameter_groups = state["optimizer_state"].get("param_groups")
    if not isinstance(parameter_groups, list) or [
        group.get("group_name") if isinstance(group, MappingABC) else None
        for group in parameter_groups
    ] != list(_OPTIMIZER_GROUPS):
        raise TrainingExecutionError("stored optimizer group schema differs")
    try:
        shadow_optimizer = copy.deepcopy(optimizer)
        shadow_optimizer.load_state_dict(copy.deepcopy(state["optimizer_state"]))
        shadow_scheduler = copy.deepcopy(scheduler)
        shadow_scheduler.load_state_dict(copy.deepcopy(state["scheduler_state"]))
    except (ValueError, TypeError, RuntimeError, KeyError) as error:
        raise TrainingExecutionError("stored optimizer or scheduler is not restorable") from error
    if shadow_scheduler.last_epoch != progress.optimizer_steps_completed:
        raise TrainingExecutionError("scheduler step differs from progress")
    rng_values = _rng_restore_values(state["rng"], require_cuda_runtime=True)
    return progress, rng_values


def resume_training_checkpoint(
    root: Path,
    checkpoint_id: str,
    expected_execution_commit: str,
    config: TrainingExecutionConfig,
    adapter: QwenCoreTrainingAdapter,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    dataloader_generator: torch.Generator,
) -> TrainingProgress:
    """Verify the complete checkpoint, then atomically restore live training state."""

    verified = verify_training_checkpoint(root, checkpoint_id)
    if (
        verified.execution_commit != expected_execution_commit
        or verified.config != config
    ):
        raise TrainingExecutionError("resume checkpoint binding differs")
    state_payload = _read_file(
        verified.artifact_path / _STATE_NAME, _STATE_LIMIT, _STATE_NAME
    )
    if hashlib.sha256(state_payload).hexdigest() != verified.state_sha256:
        raise TrainingExecutionError("checkpoint state changed after verification")
    state = _load_state_payload(state_payload)
    progress, rng_values = _validate_state_for_resume(
        state, config, adapter, optimizer, scheduler
    )
    parameters = _trainable_parameters(adapter)
    if any(parameter.grad is not None for parameter in parameters):
        raise TrainingExecutionError("resume requires a zero-gradient boundary")
    previous_model = trainable_state_dict(adapter)
    previous_optimizer = copy.deepcopy(optimizer.state_dict())
    previous_scheduler = copy.deepcopy(scheduler.state_dict())
    previous_rng = _capture_rng(dataloader_generator)
    previous_rng_values = _rng_restore_values(previous_rng)
    try:
        load_trainable_state_dict(adapter, state["trainable_state"])
        optimizer.load_state_dict(state["optimizer_state"])
        scheduler.load_state_dict(state["scheduler_state"])
        _restore_rng(rng_values, dataloader_generator)
    except Exception as error:
        load_trainable_state_dict(adapter, previous_model)
        optimizer.load_state_dict(previous_optimizer)
        scheduler.load_state_dict(previous_scheduler)
        _restore_rng(previous_rng_values, dataloader_generator)
        raise TrainingExecutionError("checkpoint restore failed and was rolled back") from error
    return progress


__all__ = (
    "TrainingExecutionConfig",
    "TrainingExecutionError",
    "TrainingProgress",
    "TrainingStepResult",
    "VerifiedTrainingCheckpoint",
    "build_optimizer",
    "build_scheduler",
    "resume_training_checkpoint",
    "run_optimizer_steps",
    "save_training_checkpoint",
    "seed_training",
    "verify_training_checkpoint",
)
