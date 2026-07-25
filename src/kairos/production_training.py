"""Provenance-bound Kairos development training orchestration.

This module intentionally publishes only DEVELOPMENT / NOT PAPER-ELIGIBLE
artifacts.  It does not evaluate internal-dev or official test data.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from . import development_training_data
from . import generation
from . import prediction_artifacts as artifact_io
from . import relation_candidates
from . import training_plan_artifacts
from .development_audit_artifacts import _private_directory
from .ids import canonical_json, sha256_canonical
from .modeling import KairosConfig, KairosModel
from .prediction_artifacts import PredictionArtifactError
from .relation_supervision import RelationOnlyPair
from .training_adapter import (
    LoraSpec,
    QwenCoreTrainingAdapter,
    TrainingBatch,
    inject_qwen_lora,
)
from .training_execution import (
    TrainingArtifactBinding,
    TrainingExecutionConfig,
    TrainingProgress,
    VerifiedTrainingCheckpoint,
    build_optimizer,
    build_scheduler,
    resume_training_checkpoint,
    save_training_checkpoint,
    seed_training,
    verify_training_checkpoint,
)
from .training_materialization import (
    BoundTrainingRecord,
    CandidateProposal,
    EMPTY_POOL_POLICY,
    _bind_authorized_empty_train_pair,
    bind_relation_pair,
    build_relation_training_corpus,
    materialize_micro_batch,
)
from .training_plan import (
    ARTIFACT_ID as TRAINING_PLAN_ARTIFACT_ID,
    MaterializedTrainingBatch,
    TrainingPlan,
    build_training_plan,
    execute_planned_training_steps,
)


ALLOWED_ROOT = Path("/data0/hk_data/kairos-zx")
CONDA_PREFIX = ALLOWED_ROOT / ".conda/envs/kairos"
RESOURCE_ROOT = ALLOWED_ROOT / "artifacts/resource-gates"
RUN_INPUT_ROOT = ALLOWED_ROOT / "artifacts/training-run-inputs"
RUN_ROOT = ALLOWED_ROOT / "artifacts/training-runs"
FAILURE_ROOT = ALLOWED_ROOT / "artifacts/training-failures"
MODEL_SHA256SUMS_SHA256 = relation_candidates.MODEL_SHA256SUMS_SHA256
CANDIDATE_EXECUTION_COMMIT = "67f995d1fe6082837c02fab2899c70f2449a888d"
CANDIDATE_MANIFEST_SHA256 = (
    "bdf45755a08dae3e0cb4478f2c5c038c8eb519f57b34d8f8e007d0de20581e2e"
)
DATA_MANIFEST_SHA256 = relation_candidates.DATA_MANIFEST_SHA256
TRAIN_CANDIDATES_SHA256 = (
    "e5955a6a1320bf7e3046c86f424a24ae3b6572eb06cbb5ea6efbd69662a29d86"
)
TRAIN_EVIDENCE_SHA256 = (
    "928bb79528e4d94f6ddd980d3f5048aa7fa06d0bbd5f0f1713fb05c47859e469"
)
DEV_CANDIDATES_SHA256 = (
    "101fd8216d67efccaf109c8e01fe09f68de39009bdb4e15e968432f89ea4f01a"
)
DEV_EVIDENCE_SHA256 = (
    "d9e1d72be6651225dbfc67728374683d5a4c03f966c472502c72d5fafcb0de51"
)
EMPTY_TRAIN_COUNT = 3
EMPTY_TRAIN_IDS_SHA256 = (
    "22b4edc8c53acf2971d1d618da17388ea34c759188fab4b32ed41f384d22161a"
)
SEED = 13
MICRO_BATCH_SIZE = 1
CHECKPOINT_STEPS = (5, 10, 15, 20, 25, 30, 31)
PROJECTED_NEW_BYTES = 8 * 1024**3
MIN_FREE_GPU_MIB = 22 * 1024
RESOURCE_SCHEMA = "kairos-training-resource-gate-v1"
RUN_INPUT_SCHEMA = "kairos-training-run-input-v2"
RUN_INPUT_MANIFEST_SCHEMA = "kairos-training-run-input-manifest-v2"
RUN_CONFIG_SCHEMA = "kairos-training-run-config-v2"
TRACE_SCHEMA = "kairos-training-trace-row-v1"
POST_RESOURCE_SCHEMA = "kairos-training-post-resource-v1"
RUN_MANIFEST_SCHEMA = "kairos-training-run-manifest-v2"
RUN_INPUT_STATUS = "TRAINING_RUN_INPUT_COMPLETE_DEVELOPMENT_ONLY"
RUN_STATUS = "TRAINING_RUN_COMPLETE_DEVELOPMENT_ONLY"
TRACE_PREFIX_SCHEMA = "kairos-training-trace-prefix-v1"
FAILURE_SCHEMA = "kairos-training-failure-v1"
RUN_INPUT_NAME = "run-input.json"
MANIFEST_NAME = "manifest.json"
RUN_CONFIG_NAME = "run-config.json"
TRACE_NAME = "trace.jsonl"
POST_RESOURCE_NAME = "post-resource.json"
CHECKPOINT_DIR_NAME = "checkpoints"
TRACE_PREFIX_DIR_NAME = "trace-prefixes"
FAILURE_NAME = "failure.json"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
_JSON_LIMIT = 8 * 1024 * 1024
_TRACE_LIMIT = 4 * 1024 * 1024
_CONDARC_SHA256 = "280d122fae6c9ca21dca263304d49efdf0a92455d7d1351ee22e70bd9841a452"
_RUNTIME_PATHS = {
    "CONDARC": str(ALLOWED_ROOT / ".conda/.condarc"),
    "CONDA_PREFIX": str(CONDA_PREFIX),
    "CONDA_PKGS_DIRS": str(ALLOWED_ROOT / ".conda/pkgs"),
    "PIP_CACHE_DIR": str(ALLOWED_ROOT / ".cache/pip"),
    "HF_HOME": str(ALLOWED_ROOT / ".cache/huggingface"),
    "HF_HUB_CACHE": str(ALLOWED_ROOT / ".cache/huggingface/hub"),
    "XDG_CACHE_HOME": str(ALLOWED_ROOT / ".cache"),
    "TMPDIR": str(ALLOWED_ROOT / ".tmp"),
    "TEMP": str(ALLOWED_ROOT / ".tmp"),
    "TMP": str(ALLOWED_ROOT / ".tmp"),
}
_RUNTIME_LITERALS = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
    "PYTHONHASHSEED": str(SEED),
    "OMP_NUM_THREADS": "8",
    "MKL_NUM_THREADS": "8",
    "OPENBLAS_NUM_THREADS": "8",
    "NUMEXPR_NUM_THREADS": "8",
}


class ProductionTrainingError(ValueError):
    """A production-training provenance, resource, or publication gate failed."""


def _fail(message: str) -> None:
    raise ProductionTrainingError(message) from None


@dataclass(frozen=True)
class VerifiedResourceGate:
    path: Path
    sha256: str
    value: Mapping[str, Any]


@dataclass(frozen=True)
class VerifiedRunInput:
    artifact_id: str
    artifact_path: Path
    execution_commit: str
    resource_gate_path: Path
    input_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class PreparedTraining:
    run_input: VerifiedRunInput
    plan_artifact: training_plan_artifacts.VerifiedTrainingPlanArtifact


@dataclass(frozen=True)
class VerifiedTrainingRun:
    run_id: str
    artifact_path: Path
    execution_commit: str
    plan_id: str
    final_checkpoint_id: str
    manifest_sha256: str
    trace_sha256: str


@dataclass(frozen=True)
class LocatedCheckpoint:
    artifact_run_id: str
    checkpoint: VerifiedTrainingCheckpoint
    trace_rows: tuple[Mapping[str, Any], ...]
    trace_prefix_sha256: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _payload(value: Mapping[str, Any], name: str, limit: int = _JSON_LIMIT) -> bytes:
    try:
        result = canonical_json(value).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ProductionTrainingError(f"{name} is not canonical JSON") from error
    if len(result) > limit:
        _fail(f"{name} exceeds its byte limit")
    return result


def _binding(payload: bytes, *, count: int | None = None) -> Mapping[str, Any]:
    result: dict[str, Any] = {
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if count is not None:
        result["record_count"] = count
    return result


def _read(path: Path, limit: int, name: str) -> bytes:
    try:
        return artifact_io._read_artifact_file(path, limit, name)
    except PredictionArtifactError as error:
        raise ProductionTrainingError(f"{name} is invalid") from error


def _object(payload: bytes, name: str) -> Mapping[str, Any]:
    try:
        return artifact_io._canonical_object(payload, name)
    except PredictionArtifactError as error:
        raise ProductionTrainingError(f"{name} is invalid") from error


def _private_namespace(path: Path, expected: set[str], name: str) -> None:
    _private_directory(path, name)
    try:
        entries = tuple(os.scandir(path))
    except OSError as error:
        raise ProductionTrainingError(f"{name} cannot be scanned") from error
    if {entry.name for entry in entries} != expected:
        _fail(f"{name} namespace differs")
    for entry in entries:
        info = entry.stat(follow_symlinks=False)
        if entry.name in {CHECKPOINT_DIR_NAME, TRACE_PREFIX_DIR_NAME}:
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                _fail(f"{name} checkpoint directory metadata differs")
        elif (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            _fail(f"{name} file metadata differs")


def _resource_gate_payload(path: Path) -> bytes:
    """Read exactly RESOURCE_ROOT/<slug>/resource-gate.json via no-follow FDs."""

    path = Path(path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path.name != "resource-gate.json"
        or path.parent.parent != RESOURCE_ROOT
        or not _SLUG.fullmatch(path.parent.name)
    ):
        _fail("resource gate path is outside the fixed namespace")
    for index, directory in enumerate(
        (ALLOWED_ROOT, RESOURCE_ROOT.parent, RESOURCE_ROOT)
    ):
        try:
            info = directory.lstat()
        except OSError as error:
            raise ProductionTrainingError("resource gate ancestor is unavailable") from error
        expected_mode = 0o775 if index == 0 else 0o700
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or stat.S_IMODE(info.st_mode) != expected_mode
        ):
            _fail("resource gate ancestor metadata differs")
    root_fd = gate_fd = file_fd = None
    try:
        root_fd = os.open(
            RESOURCE_ROOT,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        root_info = os.fstat(root_fd)
        root_lstat = RESOURCE_ROOT.lstat()
        if (root_info.st_dev, root_info.st_ino) != (
            root_lstat.st_dev,
            root_lstat.st_ino,
        ):
            _fail("resource gate root changed during open")
        gate_fd = os.open(
            path.parent.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=root_fd,
        )
        gate_info = os.fstat(gate_fd)
        if stat.S_IMODE(gate_info.st_mode) != 0o700:
            _fail("resource gate directory metadata differs")
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=gate_fd,
        )
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 1 <= before.st_size <= _JSON_LIMIT
        ):
            _fail("resource gate file metadata differs")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_fd, min(remaining, 1024 * 1024))
            if not chunk:
                _fail("resource gate file is truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            _fail("resource gate file grew during read")
        after = os.fstat(file_fd)
        fields_value = (
            "st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
            "st_mtime_ns", "st_ctime_ns",
        )
        if any(getattr(before, key) != getattr(after, key) for key in fields_value):
            _fail("resource gate file changed during read")
        return b"".join(chunks)
    except OSError as error:
        raise ProductionTrainingError("resource gate no-follow read failed") from error
    finally:
        for descriptor in (file_fd, gate_fd, root_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _command(arguments: Sequence[str], name: str, limit: int = 1024 * 1024) -> str:
    try:
        result = subprocess.run(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProductionTrainingError(f"{name} command failed") from error
    if result.returncode != 0 or len(result.stdout) > limit:
        _fail(f"{name} command failed")
    try:
        return result.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProductionTrainingError(f"{name} output is not UTF-8") from error


def _gpu_identity(uuid: str) -> Mapping[str, Any]:
    raw = relation_candidates._nvidia_query(
        (
            f"--id={uuid}",
            "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        )
    ).strip()
    fields_value = [item.strip() for item in raw.split(",")]
    if len(fields_value) != 7:
        _fail("selected GPU identity is malformed")
    try:
        physical_index = int(fields_value[0])
        total_mib = int(fields_value[4])
        free_mib = int(fields_value[5])
    except ValueError:
        _fail("selected GPU numeric identity is malformed")
    return {
        "physical_index": physical_index,
        "uuid": fields_value[1],
        "pci_bus_id": fields_value[2],
        "name": fields_value[3],
        "total_mib": total_mib,
        "free_mib": free_mib,
        "free_bytes": free_mib * 1024**2,
        "driver_version": fields_value[6],
    }


def _gpu_processes(uuid: str) -> tuple[int, ...]:
    raw = relation_candidates._nvidia_query(
        (
            "--query-compute-apps=gpu_uuid,pid",
            "--format=csv,noheader,nounits",
        )
    )
    result = []
    for line in raw.splitlines():
        values = [item.strip() for item in line.split(",")]
        if values and values[0] == uuid:
            try:
                result.append(int(values[1]))
            except (IndexError, ValueError):
                _fail("selected GPU process list is malformed")
    return tuple(sorted(set(result)))


def _memory_available_bytes() -> int:
    lines = _command(("/usr/bin/free", "-b"), "free").splitlines()
    if len(lines) < 2:
        _fail("free output is incomplete")
    fields_value = lines[1].split()
    try:
        return int(fields_value[-1])
    except (IndexError, ValueError):
        _fail("free output is malformed")


def _project_bytes() -> int:
    raw = _command(
        ("/usr/bin/du", "-sb", str(ALLOWED_ROOT)), "project disk usage"
    ).split()
    try:
        return int(raw[0])
    except (IndexError, ValueError):
        _fail("project disk usage is malformed")


def _resource_command_observations() -> Mapping[str, Mapping[str, Any]]:
    commands = {
        "nvidia-smi": ("/usr/bin/nvidia-smi",),
        "free-h": ("/usr/bin/free", "-h"),
        "df-h": ("/usr/bin/df", "-h", str(ALLOWED_ROOT)),
    }
    result = {}
    for name, command in commands.items():
        output = _command(command, name)
        result[name] = {
            "argv": list(command),
            "stdout_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        }
    return result


def _environment() -> Mapping[str, Any]:
    return {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "torch": metadata.version("torch"),
        "torch_cuda": torch.version.cuda,
        "transformers": metadata.version("transformers"),
        "peft": metadata.version("peft"),
        "accelerate": metadata.version("accelerate"),
        "safetensors": metadata.version("safetensors"),
        "huggingface_hub": metadata.version("huggingface-hub"),
        "attention_implementation": "sdpa",
    }


def _runtime_environment() -> Mapping[str, str]:
    return {**_RUNTIME_PATHS, **_RUNTIME_LITERALS}


def _runtime_environment_gate(*, selected_gpu_uuid: str | None = None) -> None:
    """Fail before artifact creation/model access if isolation is incomplete."""

    expected = _runtime_environment()
    if any(os.environ.get(key) != value for key, value in expected.items()):
        _fail("fixed local runtime environment differs")
    try:
        executable = Path(sys.executable)
        executable_info = executable.lstat()
    except OSError as error:
        raise ProductionTrainingError("fixed Conda Python is unavailable") from error
    if (
        not executable.is_absolute()
        or executable_info.st_mode == 0
        or executable != CONDA_PREFIX / "bin/python"
    ):
        _fail("runner is not using the fixed Conda Python")
    for key, raw in _RUNTIME_PATHS.items():
        path = Path(raw)
        if not path.is_relative_to(ALLOWED_ROOT) or ".." in path.parts:
            _fail("runtime path escapes the allowed root")
        relative = path.relative_to(ALLOWED_ROOT)
        ancestor = ALLOWED_ROOT
        for component in relative.parts[:-1]:
            ancestor = ancestor / component
            try:
                ancestor_info = ancestor.lstat()
            except OSError as error:
                raise ProductionTrainingError("runtime ancestor is unavailable") from error
            if not stat.S_ISDIR(ancestor_info.st_mode) or stat.S_ISLNK(
                ancestor_info.st_mode
            ):
                _fail("runtime ancestor metadata differs")
        if key == "CONDARC":
            try:
                info = path.lstat()
            except OSError as error:
                raise ProductionTrainingError("local Conda configuration is unavailable") from error
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or hashlib.sha256(path.read_bytes()).hexdigest() != _CONDARC_SHA256
            ):
                _fail("local Conda configuration is invalid")
        else:
            _private_directory(path, f"runtime path {key}")
    if selected_gpu_uuid is not None and (
        os.environ.get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID"
        or os.environ.get("CUDA_VISIBLE_DEVICES") != selected_gpu_uuid
    ):
        _fail("CUDA UUID environment differs")


def _frozen_execution_configuration() -> Mapping[str, Any]:
    config = TrainingExecutionConfig(
        seed=SEED,
        micro_batch_size=MICRO_BATCH_SIZE,
        gradient_accumulation_steps=32,
        total_optimizer_steps=31,
    )
    return {
        "execution_config": dict(config.to_dict()),
        "lora": LoraSpec().to_dict(),
        "core": asdict(KairosConfig(hidden_size=3584)),
        "loss": {
            "answer_weight": 1.0,
            "relation_weight": 1.0,
            "counterfactual_relation_weight": 1.0,
            "counterfactual_answer_loss": False,
        },
        "precision": "bfloat16-autocast",
        "deterministic_algorithms": True,
        "gradient_checkpointing": True,
        "attention_implementation": "sdpa",
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "real_slot_count": 990,
        "repeat_padding_count": 2,
        "empty_pool_policy": EMPTY_POOL_POLICY,
    }


def _ordered_model_hash(model_files: Mapping[str, str]) -> str:
    return sha256_canonical({key: model_files[key] for key in sorted(model_files)})


def capture_resource_gate(
    execution_commit: str, selected_gpu_uuid: str, gate_id: str
) -> VerifiedResourceGate:
    """Capture one no-replace training resource gate before model allocation."""

    if not _HEX40.fullmatch(execution_commit):
        _fail("execution commit is invalid")
    if not isinstance(selected_gpu_uuid, str) or not selected_gpu_uuid.startswith("GPU-"):
        _fail("selected GPU UUID is invalid")
    if not _SLUG.fullmatch(gate_id):
        _fail("resource gate ID is invalid")
    _runtime_environment_gate(selected_gpu_uuid=selected_gpu_uuid)
    artifact_io._git_gate(execution_commit)
    identity = dict(_gpu_identity(selected_gpu_uuid))
    if identity["free_mib"] < MIN_FREE_GPU_MIB or _gpu_processes(selected_gpu_uuid):
        _fail("selected GPU is not idle with at least 22 GiB free")
    if torch.cuda.device_count() != 1:
        _fail("capture process does not see exactly one CUDA device")
    properties = torch.cuda.get_device_properties(0)
    if properties.name != identity["name"]:
        _fail("Torch GPU name differs from selected device")
    identity["torch_total_bytes"] = properties.total_memory
    own_or_none = set(_gpu_processes(selected_gpu_uuid)).difference({os.getpid()})
    if own_or_none:
        _fail("another process acquired the selected GPU during capture")
    identity["compute_process_count"] = 0
    observations = _resource_command_observations()
    data0_free = os.statvfs(ALLOWED_ROOT)
    free_bytes = data0_free.f_bavail * data0_free.f_frsize
    available_memory = _memory_available_bytes()
    project_before = _project_bytes()
    model_files = relation_candidates._verify_model_files()
    if (
        free_bytes < 120 * 1024**3
        or available_memory < 64 * 1024**3
        or project_before + PROJECTED_NEW_BYTES > 80 * 1024**3
    ):
        _fail("training resource budget is not satisfied")
    value = {
        "schema_version": RESOURCE_SCHEMA,
        "status": "PASSED",
        "gate_id": gate_id,
        "observed_at_utc": _utc_now(),
        "execution_commit": execution_commit,
        "resource_commands": ["nvidia-smi", "free -h", "df -h"],
        "resource_observations": observations,
        "selected_gpu": identity,
        "gpu_count": 1,
        "cpu_thread_limit": 8,
        "dataloader_workers": 2,
        "memory_task_limit_bytes": 64 * 1024**3,
        "memory_available_bytes": available_memory,
        "data0_free_bytes": free_bytes,
        "new_disk_budget_bytes": 80 * 1024**3,
        "project_bytes_before": project_before,
        "projected_new_bytes": PROJECTED_NEW_BYTES,
        "projected_project_bytes_after": project_before + PROJECTED_NEW_BYTES,
        "model_files_verified": True,
        "model_file_count": len(model_files),
        "model_sha256sums_sha256": MODEL_SHA256SUMS_SHA256,
        "model_ordered_binding_sha256": _ordered_model_hash(model_files),
        "environment": _environment(),
        "runtime_environment": _runtime_environment(),
    }
    root = RESOURCE_ROOT / gate_id
    _private_directory(RESOURCE_ROOT, "resource gate root")
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        _fail("resource gate target already exists")
    except OSError as error:
        raise ProductionTrainingError("resource gate directory cannot be created") from error
    path = root / "resource-gate.json"
    artifact_io._write_exclusive(path, _payload(value, "resource gate"))
    artifact_io._fsync_directory(root)
    artifact_io._fsync_directory(RESOURCE_ROOT)
    return verify_resource_gate(path, execution_commit)


def verify_resource_gate(path: Path, execution_commit: str) -> VerifiedResourceGate:
    path = Path(path)
    payload = _resource_gate_payload(path)
    value = _object(payload, "training resource gate")
    expected_keys = {
        "schema_version", "status", "gate_id", "observed_at_utc", "execution_commit",
        "resource_commands", "resource_observations", "selected_gpu", "gpu_count", "cpu_thread_limit",
        "dataloader_workers", "memory_task_limit_bytes", "memory_available_bytes",
        "data0_free_bytes", "new_disk_budget_bytes", "project_bytes_before",
        "projected_new_bytes", "projected_project_bytes_after",
        "model_files_verified", "model_file_count", "model_sha256sums_sha256",
        "model_ordered_binding_sha256", "environment", "runtime_environment",
    }
    gpu = value.get("selected_gpu")
    if (
        set(value) != expected_keys
        or value.get("schema_version") != RESOURCE_SCHEMA
        or value.get("status") != "PASSED"
        or value.get("gate_id") != path.parent.name
        or value.get("execution_commit") != execution_commit
        or value.get("resource_commands") != ["nvidia-smi", "free -h", "df -h"]
        or not isinstance(value.get("resource_observations"), MappingABC)
        or set(value["resource_observations"]) != {"nvidia-smi", "free-h", "df-h"}
        or any(
            not isinstance(item, MappingABC)
            or set(item) != {"argv", "stdout_sha256"}
            or not isinstance(item.get("argv"), list)
            or not isinstance(item.get("stdout_sha256"), str)
            or not _HEX64.fullmatch(item["stdout_sha256"])
            for item in value["resource_observations"].values()
        )
        or value["resource_observations"]["nvidia-smi"].get("argv")
        != ["/usr/bin/nvidia-smi"]
        or value["resource_observations"]["free-h"].get("argv")
        != ["/usr/bin/free", "-h"]
        or value["resource_observations"]["df-h"].get("argv")
        != ["/usr/bin/df", "-h", str(ALLOWED_ROOT)]
        or value.get("gpu_count") != 1
        or value.get("cpu_thread_limit") != 8
        or value.get("dataloader_workers") != 2
        or value.get("memory_task_limit_bytes") != 64 * 1024**3
        or value.get("new_disk_budget_bytes") != 80 * 1024**3
        or value.get("projected_new_bytes") != PROJECTED_NEW_BYTES
        or type(value.get("project_bytes_before")) is not int
        or value.get("projected_project_bytes_after")
        != value.get("project_bytes_before") + PROJECTED_NEW_BYTES
        or value["projected_project_bytes_after"] > 80 * 1024**3
        or type(value.get("data0_free_bytes")) is not int
        or value["data0_free_bytes"] < 120 * 1024**3
        or type(value.get("memory_available_bytes")) is not int
        or value["memory_available_bytes"] < 64 * 1024**3
        or value.get("model_files_verified") is not True
        or value.get("model_file_count") != 15
        or value.get("model_sha256sums_sha256") != MODEL_SHA256SUMS_SHA256
        or not isinstance(value.get("model_ordered_binding_sha256"), str)
        or not _HEX64.fullmatch(value["model_ordered_binding_sha256"])
        or value.get("environment") != _environment()
        or value.get("runtime_environment") != _runtime_environment()
        or not isinstance(gpu, MappingABC)
        or set(gpu) != {
            "physical_index", "uuid", "pci_bus_id", "name", "total_mib",
            "free_mib", "free_bytes", "driver_version", "torch_total_bytes",
            "compute_process_count",
        }
        or type(gpu.get("physical_index")) is not int
        or not isinstance(gpu.get("uuid"), str)
        or not isinstance(gpu.get("pci_bus_id"), str)
        or not isinstance(gpu.get("name"), str)
        or type(gpu.get("total_mib")) is not int
        or type(gpu.get("free_mib")) is not int
        or gpu.get("free_bytes") != gpu.get("free_mib") * 1024**2
        or gpu.get("free_mib") < MIN_FREE_GPU_MIB
        or not 20 * 1024**3 <= gpu.get("torch_total_bytes", 0) <= 26 * 1024**3
        or gpu.get("compute_process_count") != 0
    ):
        _fail("training resource gate differs from the frozen contract")
    return VerifiedResourceGate(path, hashlib.sha256(payload).hexdigest(), value)


def _fresh_attempt_gate(
    path: Path,
    execution_commit: str,
    run_input_gate_path: Path,
    attempt_run_id: str,
) -> VerifiedResourceGate:
    gate = verify_resource_gate(path, execution_commit)
    input_gate = verify_resource_gate(run_input_gate_path, execution_commit)
    if (
        not _SLUG.fullmatch(attempt_run_id)
        or gate.value["gate_id"] != attempt_run_id
        or gate.path == input_gate.path
        or gate.sha256 == input_gate.sha256
    ):
        _fail("training attempt requires a fresh resource gate")
    try:
        observed = datetime.fromisoformat(
            gate.value["observed_at_utc"].replace("Z", "+00:00")
        ).timestamp()
        modified = gate.path.stat(follow_symlinks=False).st_mtime
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ProductionTrainingError("attempt resource-gate time is invalid") from error
    now = time.time()
    if not 0 <= now - observed <= 900 or not 0 <= now - modified <= 900:
        _fail("training attempt resource gate is stale")
    return gate


def _candidate_payloads() -> Mapping[str, bytes]:
    verified = relation_candidates._verify(CANDIDATE_EXECUTION_COMMIT)
    if verified.manifest_sha256 != CANDIDATE_MANIFEST_SHA256:
        _fail("candidate manifest identity differs")
    result = {
        name: _read(
            verified.artifact_path / name,
            512 * 1024 * 1024 if name.endswith(".jsonl") else _JSON_LIMIT,
            name,
        )
        for name in relation_candidates._OUTPUT_NAMES
    }
    expected = {
        relation_candidates.TRAIN_CANDIDATES_NAME: TRAIN_CANDIDATES_SHA256,
        relation_candidates.TRAIN_EVIDENCE_NAME: TRAIN_EVIDENCE_SHA256,
        relation_candidates.DEV_CANDIDATES_NAME: DEV_CANDIDATES_SHA256,
        relation_candidates.DEV_EVIDENCE_NAME: DEV_EVIDENCE_SHA256,
        relation_candidates.MANIFEST_NAME: CANDIDATE_MANIFEST_SHA256,
    }
    for name, digest in expected.items():
        if hashlib.sha256(result[name]).hexdigest() != digest:
            _fail("candidate output SHA256 differs")
    return result


def _candidate_rows(payload: bytes, name: str) -> tuple[Mapping[str, Any], ...]:
    rows = []
    for raw in payload.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            _fail(f"{name} line framing differs")
        try:
            value = artifact_io._strict_json(raw[:-1], name)
        except PredictionArtifactError as error:
            raise ProductionTrainingError(f"{name} JSON is invalid") from error
        if not isinstance(value, MappingABC) or canonical_json(value).encode() + b"\n" != raw:
            _fail(f"{name} row is invalid")
        rows.append(value)
    return tuple(rows)


def _bound_records() -> tuple[tuple[BoundTrainingRecord, ...], tuple[str, ...]]:
    train_pairs, dev_pairs = relation_candidates._data_records()
    payloads = _candidate_payloads()
    train_rows = _candidate_rows(
        payloads[relation_candidates.TRAIN_CANDIDATES_NAME], "train candidates"
    )
    dev_rows = _candidate_rows(
        payloads[relation_candidates.DEV_CANDIDATES_NAME], "internal-dev candidates"
    )
    if len(train_rows) != len(train_pairs) or len(dev_rows) != len(dev_pairs):
        _fail("candidate/data coverage differs")
    empty_ids = tuple(
        row["pair_id"] for row in train_rows if not row.get("candidates")
    )
    if (
        len(empty_ids) != EMPTY_TRAIN_COUNT
        or hashlib.sha256(canonical_json(list(empty_ids)).encode()).hexdigest()
        != EMPTY_TRAIN_IDS_SHA256
        or any(not row.get("candidates") for row in dev_rows)
    ):
        _fail("D-043 empty-pool identity differs")
    records = []
    for index, (pair, row) in enumerate(zip(train_pairs, train_rows)):
        if (
            row.get("pair_id") != pair.pair_id
            or row.get("source_id") != pair.source_id
            or row.get("partition") != "train"
            or not isinstance(row.get("proposals"), list)
            or not isinstance(row.get("candidates"), list)
        ):
            _fail("train candidate identity differs")
        proposals = tuple(
            CandidateProposal(value["text"], value["origin"])
            for value in row["proposals"]
        )
        if proposals:
            record = bind_relation_pair(pair, proposals, index)
        else:
            record = _bind_authorized_empty_train_pair(
                pair,
                (),
                index,
                partition="train",
                policy=EMPTY_POOL_POLICY,
                authorized_pair_ids=frozenset(empty_ids),
            )
        generated = tuple(row["candidates"])
        expected_generated_count = len(generated)
        actual_generated_count = len(record.binding.candidates) - int(
            record.binding.gold_injected
        )
        if actual_generated_count != expected_generated_count:
            _fail("materialized generated candidate count differs")
        for generated_index, value in enumerate(generated):
            binding = record.binding.candidates[generated_index]
            if (
                record.candidate_texts[generated_index] != value.get("text")
                or binding.content_sha256 != value.get("content_sha256")
                or list(binding.origins) != value.get("origins")
            ):
                _fail("materialized generated candidates differ")
        records.append(record)
    return tuple(records), empty_ids


def _protocol_bindings() -> Mapping[str, Mapping[str, Any]]:
    relation_candidates._protocols()
    return {
        "candidate": {
            "path": str(relation_candidates.PROMPT_PATH),
            "sha256": relation_candidates.PROMPT_SHA256,
        },
        "sft": {
            "path": str(relation_candidates.SFT_PROTOCOL_PATH),
            "sha256": relation_candidates.SFT_PROTOCOL_SHA256,
        },
        "evaluation": {
            "path": str(relation_candidates.EVALUATION_PROTOCOL_PATH),
            "sha256": relation_candidates.EVALUATION_PROTOCOL_SHA256,
        },
    }


def _run_input_id(execution_commit: str) -> str:
    return f"kairos-gsm8k-relation-s{SEED}-{execution_commit[:12]}"


def _run_id(execution_commit: str) -> str:
    return f"kairos-gsm8k-relation-s{SEED}-{execution_commit[:12]}"


def _run_input_value(
    execution_commit: str, gate: VerifiedResourceGate
) -> tuple[Mapping[str, Any], tuple[BoundTrainingRecord, ...]]:
    data = development_training_data.verify(relation_candidates.DATA_EXECUTION_COMMIT)
    if data.manifest_sha256 != DATA_MANIFEST_SHA256:
        _fail("development data manifest identity differs")
    records, empty_ids = _bound_records()
    candidate_payloads = _candidate_payloads()
    model_files = relation_candidates._verify_model_files()
    if _ordered_model_hash(model_files) != gate.value["model_ordered_binding_sha256"]:
        _fail("resource gate model binding differs")
    value = {
        "schema_version": RUN_INPUT_SCHEMA,
        "status": RUN_INPUT_STATUS,
        "artifact_id": _run_input_id(execution_commit),
        "execution_commit": execution_commit,
        "method": "kairos",
        "seed": SEED,
        "eligibility": {
            "formal_experiment_eligible": False,
            "paper_metric_eligible": False,
            "result_scope": "DEVELOPMENT / INTERNAL-DEV / NOT PAPER-ELIGIBLE",
            "human_independence_verified": False,
        },
        "audit_and_data": {
            "audit_manifest_sha256": development_training_data.AUDIT_MANIFEST_SHA256,
            "audit_result_sha256": development_training_data.AUDIT_RESULT_SHA256,
            "audit_projection_sha256": development_training_data.AUDIT_PROJECTION_SHA256,
            "provenance_status": "USER_ATTESTED / INDEPENDENCE_UNVERIFIED",
            "data_artifact_id": data.artifact_id,
            "data_manifest_sha256": data.manifest_sha256,
            "train_sha256": data.train_sha256,
            "partition_sha256": data.partition_sha256,
            "train_count": data.train_count,
            "internal_dev_count": data.internal_dev_count,
            "optimizer_partition": "train",
        },
        "candidates": {
            "artifact_id": relation_candidates.ARTIFACT_ID,
            "execution_commit": CANDIDATE_EXECUTION_COMMIT,
            "manifest_sha256": CANDIDATE_MANIFEST_SHA256,
            "config": _binding(candidate_payloads[relation_candidates.CONFIG_NAME]),
            "train_candidates": _binding(
                candidate_payloads[relation_candidates.TRAIN_CANDIDATES_NAME], count=330
            ),
            "train_evidence": _binding(
                candidate_payloads[relation_candidates.TRAIN_EVIDENCE_NAME], count=330
            ),
            "internal_dev_candidates": _binding(
                candidate_payloads[relation_candidates.DEV_CANDIDATES_NAME], count=36
            ),
            "internal_dev_evidence": _binding(
                candidate_payloads[relation_candidates.DEV_EVIDENCE_NAME], count=36
            ),
            "gold_access": "NONE",
        },
        "materialization": {
            "schema_version": "relation-training-materialization-v2",
            "empty_pool_policy": EMPTY_POOL_POLICY,
            "empty_train_count": len(empty_ids),
            "ordered_empty_train_pair_ids_sha256": EMPTY_TRAIN_IDS_SHA256,
            "internal_dev_empty_count": 0,
            "singleton_answer_loss": 0,
            "internal_dev_gold_injection": False,
            "counterfactual_answer_available": False,
        },
        "protocols": _protocol_bindings(),
        "model": {
            "model_id": generation.MODEL_ID,
            "revision": generation.MODEL_REVISION,
            "sha256sums_sha256": MODEL_SHA256SUMS_SHA256,
            "ordered_model_binding_sha256": _ordered_model_hash(model_files),
            "model_file_count": len(model_files),
            "files": {key: model_files[key] for key in sorted(model_files)},
            "chat_template_sha256": relation_candidates.CHAT_TEMPLATE_SHA256,
        },
        "training": _frozen_execution_configuration(),
        "resource_gate": {
            "path": str(gate.path),
            "sha256": gate.sha256,
            "selected_gpu": dict(gate.value["selected_gpu"]),
        },
        "environment": _environment(),
        "runtime_environment": _runtime_environment(),
    }
    return value, records


def _run_input_manifest(
    artifact_id: str, execution_commit: str, input_payload: bytes
) -> Mapping[str, Any]:
    return {
        "schema_version": RUN_INPUT_MANIFEST_SCHEMA,
        "status": RUN_INPUT_STATUS,
        "artifact_id": artifact_id,
        "execution_commit": execution_commit,
        "files": [RUN_INPUT_NAME, MANIFEST_NAME],
        "run_input": _binding(input_payload),
        "paper_metric_eligible": False,
    }


def _publish_run_input(
    execution_commit: str, gate: VerifiedResourceGate
) -> tuple[VerifiedRunInput, tuple[BoundTrainingRecord, ...]]:
    value, records = _run_input_value(execution_commit, gate)
    artifact_id = value["artifact_id"]
    input_payload = _payload(value, "run input")
    manifest_payload = _payload(
        _run_input_manifest(artifact_id, execution_commit, input_payload),
        "run input manifest",
    )
    _private_directory(RUN_INPUT_ROOT.parent, "run-input parent")
    try:
        artifact_io._prepare_root(RUN_INPUT_ROOT)
    except (PredictionArtifactError, OSError) as error:
        raise ProductionTrainingError("run-input root cannot be prepared") from error
    target = RUN_INPUT_ROOT / artifact_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("run-input target already exists")
    artifact_io._git_gate(execution_commit)
    artifact_io._write_exclusive(target / RUN_INPUT_NAME, input_payload)
    artifact_io._fsync_directory(target)
    artifact_io._git_gate(execution_commit)
    artifact_io._write_exclusive(target / MANIFEST_NAME, manifest_payload)
    artifact_io._fsync_directory(target)
    artifact_io._fsync_directory(RUN_INPUT_ROOT)
    return verify_run_input(artifact_id, execution_commit), records


def verify_run_input(
    artifact_id: str, expected_commit: str | None = None
) -> VerifiedRunInput:
    if not _SLUG.fullmatch(artifact_id):
        _fail("run-input artifact ID is invalid")
    target = RUN_INPUT_ROOT / artifact_id
    _private_namespace(target, {RUN_INPUT_NAME, MANIFEST_NAME}, "run-input artifact")
    input_payload = _read(target / RUN_INPUT_NAME, _JSON_LIMIT, RUN_INPUT_NAME)
    manifest_payload = _read(target / MANIFEST_NAME, _JSON_LIMIT, MANIFEST_NAME)
    value = _object(input_payload, "run input")
    manifest = _object(manifest_payload, "run-input manifest")
    execution_commit = value.get("execution_commit")
    if (
        not isinstance(execution_commit, str)
        or not _HEX40.fullmatch(execution_commit)
        or (expected_commit is not None and execution_commit != expected_commit)
        or value.get("artifact_id") != artifact_id
    ):
        _fail("run-input execution identity differs")
    resource = value.get("resource_gate")
    if not isinstance(resource, MappingABC):
        _fail("run-input resource binding is invalid")
    gate = verify_resource_gate(Path(resource.get("path", "")), execution_commit)
    expected, unused_records = _run_input_value(execution_commit, gate)
    if value != expected:
        _fail("run input differs from full provenance replay")
    if manifest != _run_input_manifest(artifact_id, execution_commit, input_payload):
        _fail("run-input manifest differs")
    return VerifiedRunInput(
        artifact_id,
        target,
        execution_commit,
        gate.path,
        hashlib.sha256(input_payload).hexdigest(),
        hashlib.sha256(manifest_payload).hexdigest(),
    )


def _corpus(
    records: Sequence[BoundTrainingRecord],
    execution_commit: str,
    run_input: VerifiedRunInput,
):
    return build_relation_training_corpus(
        records,
        execution_commit,
        run_input.artifact_id,
        run_input.manifest_sha256,
    )


def prepare_training(execution_commit: str, resource_gate_path: Path) -> PreparedTraining:
    _runtime_environment_gate()
    artifact_io._git_gate(execution_commit)
    gate = verify_resource_gate(resource_gate_path, execution_commit)
    run_input, records = _publish_run_input(execution_commit, gate)
    plan = build_training_plan(
        _corpus(records, execution_commit, run_input), SEED, MICRO_BATCH_SIZE
    )
    if (
        len(records) != 330
        or plan.total_optimizer_steps != 31
        or plan.real_slot_count != 990
        or plan.repeat_padding_count != 2
    ):
        _fail("production training plan counts differ")
    plan_artifact = training_plan_artifacts.publish_training_plan(plan)
    replay = training_plan_artifacts.verify_training_plan(plan_artifact.plan_id)
    if replay.plan != plan:
        _fail("published training plan differs")
    return PreparedTraining(run_input, replay)


def _load_tokenizer() -> Any:
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            generation.MODEL_PATH,
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
    except Exception as error:
        raise ProductionTrainingError("fixed local tokenizer load failed") from error
    if not getattr(tokenizer, "is_fast", False):
        _fail("fixed tokenizer is not fast")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def _records_by_id(records: Sequence[BoundTrainingRecord]) -> Mapping[str, BoundTrainingRecord]:
    result = {record.binding.example_id: record for record in records}
    if len(result) != len(records):
        _fail("bound record identities are duplicated")
    return result


class _MaterializedWindow(SequenceABC[MaterializedTrainingBatch]):
    def __init__(self, total: int, values: Mapping[int, MaterializedTrainingBatch]):
        self.total = total
        self.values = dict(values)

    def __len__(self) -> int:
        return self.total

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            return tuple(self[value] for value in range(*index.indices(self.total)))
        normalized = index + self.total if index < 0 else index
        if normalized not in self.values:
            raise IndexError(index)
        return self.values[normalized]


def _to_device(batch: TrainingBatch, device: torch.device) -> TrainingBatch:
    values = {}
    for field in fields(TrainingBatch):
        value = getattr(batch, field.name)
        values[field.name] = value.to(device=device, non_blocking=False) if isinstance(value, Tensor) else value
    return TrainingBatch(**values)


def _materialized_window(
    plan: TrainingPlan,
    progress: TrainingProgress,
    records: Mapping[str, BoundTrainingRecord],
    tokenizer: Any,
    device: torch.device,
) -> _MaterializedWindow:
    start = progress.next_micro_batch_index
    end = start + plan.gradient_accumulation_steps
    values = {}
    for index in range(start, end):
        materialized = materialize_micro_batch(plan, index, records, tokenizer)
        values[index] = MaterializedTrainingBatch(
            materialized.example_ids,
            materialized.candidate_ids,
            _to_device(materialized.batch, device),
        )
    return _MaterializedWindow(len(plan.micro_batches), values)


def inspect_real_materialization(execution_commit: str) -> Mapping[str, Any]:
    _runtime_environment_gate()
    artifact_io._git_gate(execution_commit)
    records, empty_ids = _bound_records()
    placeholder = VerifiedRunInput(
        relation_candidates.ARTIFACT_ID,
        relation_candidates.ARTIFACT_ROOT / relation_candidates.ARTIFACT_ID,
        execution_commit,
        Path("/data0/hk_data/kairos-zx/.tmp/unused-resource-gate.json"),
        "a" * 64,
        CANDIDATE_MANIFEST_SHA256,
    )
    plan = build_training_plan(_corpus(records, execution_commit, placeholder), SEED, 1)
    tokenizer = _load_tokenizer()
    by_id = _records_by_id(records)
    wanted = set(empty_ids)
    indices = {0}
    for batch in plan.micro_batches:
        if wanted.intersection(batch.example_ids):
            indices.add(batch.micro_batch_index)
    shapes = []
    for index in sorted(indices):
        value = materialize_micro_batch(plan, index, by_id, tokenizer)
        shapes.append(
            {
                "micro_batch_index": index,
                "example_id": value.example_ids[0],
                "source_tokens": int(value.batch.input_ids.shape[1]),
                "candidate_count": int(value.batch.candidate_mask.sum()),
                "candidate_tokens": int(value.batch.candidate_input_ids.shape[2]),
            }
        )
    artifact_io._git_gate(execution_commit)
    return {
        "status": "REAL_RECORD_MATERIALIZATION_SMOKE_COMPLETE / NO_ARTIFACT",
        "train_count": len(records),
        "empty_train_count": len(empty_ids),
        "checked_micro_batches": shapes,
        "optimizer_steps": plan.total_optimizer_steps,
    }


def _load_plan_and_records(
    plan_id: str, expected_commit: str
) -> tuple[TrainingPlan, VerifiedRunInput, tuple[BoundTrainingRecord, ...]]:
    plan_artifact = training_plan_artifacts.verify_training_plan(plan_id)
    plan = plan_artifact.plan
    if plan.corpus.execution_commit != expected_commit:
        _fail("training plan execution commit differs")
    run_input = verify_run_input(plan.corpus.source_artifact_id, expected_commit)
    if plan.corpus.source_manifest_sha256 != run_input.manifest_sha256:
        _fail("training plan does not bind the run-input manifest")
    records, unused_empty_ids = _bound_records()
    expected_corpus = _corpus(records, expected_commit, run_input)
    if plan.corpus != expected_corpus:
        _fail("training plan corpus differs from replayed inputs")
    return plan, run_input, records


def _initialize_adapter(
    seed: int, gate: VerifiedResourceGate
) -> tuple[QwenCoreTrainingAdapter, Any, torch.Generator]:
    _runtime_environment_gate(
        selected_gpu_uuid=gate.value["selected_gpu"]["uuid"]
    )
    relation_candidates._gpu_gate(gate.value)
    torch.cuda.reset_peak_memory_stats(0)
    torch.use_deterministic_algorithms(True)
    generator_value = torch.Generator(device="cpu")
    seed_training(seed, generator_value)
    try:
        backbone, tokenizer = generation.load_local_backbone("cuda:0")
    except Exception as error:
        raise ProductionTrainingError("training backbone load failed") from error
    tokenizer.padding_side = "right"
    injected = inject_qwen_lora(backbone, LoraSpec())
    core = KairosModel(KairosConfig(hidden_size=3584)).to(
        device=torch.device("cuda:0"), dtype=torch.bfloat16
    )
    adapter = QwenCoreTrainingAdapter(injected, core)
    return adapter, tokenizer, generator_value


def gpu_smoke(execution_commit: str, resource_gate_path: Path) -> Mapping[str, Any]:
    gate = verify_resource_gate(resource_gate_path, execution_commit)
    _runtime_environment_gate(selected_gpu_uuid=gate.value["selected_gpu"]["uuid"])
    artifact_io._git_gate(execution_commit)
    records, unused_empty_ids = _bound_records()
    placeholder = VerifiedRunInput(
        relation_candidates.ARTIFACT_ID,
        relation_candidates.ARTIFACT_ROOT / relation_candidates.ARTIFACT_ID,
        execution_commit,
        gate.path,
        "a" * 64,
        CANDIDATE_MANIFEST_SHA256,
    )
    plan = build_training_plan(_corpus(records, execution_commit, placeholder), SEED, 1)
    adapter, tokenizer, loader_generator = _initialize_adapter(SEED, gate)
    optimizer = build_optimizer(adapter, plan.execution_config)
    scheduler = build_scheduler(optimizer, plan.execution_config)
    progress = plan.progress(0)
    window = _materialized_window(
        plan, progress, _records_by_id(records), tokenizer, torch.device("cuda:0")
    )
    result = execute_planned_training_steps(
        adapter, window, optimizer, scheduler, plan, progress, 1
    )
    artifact_io._git_gate(execution_commit)
    return {
        "status": "GPU_ONE_STEP_SMOKE_COMPLETE / NO_ARTIFACT",
        "optimizer_steps_completed": result.progress.optimizer_steps_completed,
        "samples_seen": result.progress.samples_seen,
        "loss": result.optimizer_losses[0],
        "gradient_norm": result.gradient_norms[0],
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
        "resource_gate_sha256": gate.sha256,
    }


def _checkpoint_binding(plan: TrainingPlan) -> TrainingArtifactBinding:
    binding = TrainingArtifactBinding(
        model_id=generation.MODEL_ID,
        model_revision=generation.MODEL_REVISION,
        model_sha256sums_sha256=MODEL_SHA256SUMS_SHA256,
        dataset_id=plan.corpus.dataset_id,
        dataset_revision=plan.corpus.dataset_revision,
        split=plan.corpus.official_split,
        data_artifact_id=TRAINING_PLAN_ARTIFACT_ID,
        data_manifest_sha256=plan.manifest_sha256,
        core_type="kairos",
    )
    plan.validate_artifact_binding(binding)
    return binding


def _run_config(
    run_id: str,
    plan_id: str,
    plan_artifact: training_plan_artifacts.VerifiedTrainingPlanArtifact,
    run_input: VerifiedRunInput,
    gate: VerifiedResourceGate,
    resume: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    return {
        "schema_version": RUN_CONFIG_SCHEMA,
        "status": "TRAINING_STARTED_DEVELOPMENT_ONLY",
        "run_id": run_id,
        "experiment_id": _run_id(run_input.execution_commit),
        "started_at_utc": _utc_now(),
        "execution_commit": run_input.execution_commit,
        "method": "kairos",
        "seed": SEED,
        "run_input": {
            "artifact_id": run_input.artifact_id,
            "manifest_sha256": run_input.manifest_sha256,
        },
        "training_plan": {
            "plan_id": plan_id,
            "manifest_sha256": plan_artifact.manifest_sha256,
            "semantic_sha256": plan_artifact.plan_semantic_sha256,
        },
        "resource_gate": {"path": str(gate.path), "sha256": gate.sha256},
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "result_scope": "DEVELOPMENT / INTERNAL-DEV / NOT PAPER-ELIGIBLE",
        "paper_metric_eligible": False,
        "resume": None if resume is None else dict(resume),
    }


def _checkpoint_id(step: int) -> str:
    return f"step-{step:06d}"


def _checkpoint_step(checkpoint_id: str, *, allow_final: bool = True) -> int:
    allowed = CHECKPOINT_STEPS if allow_final else CHECKPOINT_STEPS[:-1]
    for step in allowed:
        if checkpoint_id == _checkpoint_id(step):
            return step
    _fail("checkpoint ID is outside the frozen cadence")


def _trace_receipt_name(step: int) -> str:
    return _checkpoint_id(step) + ".json"


def _publish_trace_receipt(
    target: Path,
    run_id: str,
    checkpoint: VerifiedTrainingCheckpoint,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    step = checkpoint.progress.optimizer_steps_completed
    trace_payload = _trace_payload(rows)
    _verify_trace_prefix(trace_payload, step)
    value = {
        "schema_version": TRACE_PREFIX_SCHEMA,
        "status": "IMMUTABLE_TRACE_PREFIX",
        "run_id": run_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_manifest_sha256": checkpoint.manifest_sha256,
        "optimizer_steps_completed": step,
        "trace_prefix_sha256": hashlib.sha256(trace_payload).hexdigest(),
        "trace_rows": list(rows),
    }
    artifact_io._write_exclusive(
        target / TRACE_PREFIX_DIR_NAME / _trace_receipt_name(step),
        _payload(value, "trace-prefix receipt"),
    )
    artifact_io._fsync_directory(target / TRACE_PREFIX_DIR_NAME)


def _verify_trace_receipt(
    run_id: str, checkpoint: VerifiedTrainingCheckpoint
) -> tuple[tuple[Mapping[str, Any], ...], str]:
    step = checkpoint.progress.optimizer_steps_completed
    root = RUN_ROOT / run_id / TRACE_PREFIX_DIR_NAME
    _private_directory(root, "trace-prefix root")
    payload = _read(
        root / _trace_receipt_name(step), _JSON_LIMIT, "trace-prefix receipt"
    )
    value = _object(payload, "trace-prefix receipt")
    if (
        set(value)
        != {
            "schema_version", "status", "run_id", "checkpoint_id",
            "checkpoint_manifest_sha256", "optimizer_steps_completed",
            "trace_prefix_sha256", "trace_rows",
        }
        or value.get("schema_version") != TRACE_PREFIX_SCHEMA
        or value.get("status") != "IMMUTABLE_TRACE_PREFIX"
        or value.get("run_id") != run_id
        or value.get("checkpoint_id") != checkpoint.checkpoint_id
        or value.get("checkpoint_manifest_sha256") != checkpoint.manifest_sha256
        or value.get("optimizer_steps_completed") != step
        or not isinstance(value.get("trace_rows"), list)
    ):
        _fail("trace-prefix receipt binding differs")
    trace_payload = _trace_payload(value["trace_rows"])
    rows = _verify_trace_prefix(trace_payload, step)
    digest = hashlib.sha256(trace_payload).hexdigest()
    if value.get("trace_prefix_sha256") != digest:
        _fail("trace-prefix SHA256 differs")
    return rows, digest


def _resolve_checkpoint(
    run_id: str,
    step: int,
    execution_commit: str,
    plan_id: str,
    plan: TrainingPlan,
    visited: tuple[str, ...] = (),
) -> LocatedCheckpoint:
    if run_id in visited or len(visited) >= len(CHECKPOINT_STEPS):
        _fail("checkpoint run ancestry is cyclic or too deep")
    unused_payload, config = _run_config_value(run_id)
    if config.get("execution_commit") != execution_commit:
        _fail("checkpoint source execution commit differs")
    if config.get("training_plan", {}).get("plan_id") != plan_id:
        _fail("checkpoint source training plan differs")
    resume = config.get("resume")
    if resume is not None:
        resume_step = _checkpoint_step(resume["checkpoint_id"], allow_final=False)
        if step <= resume_step:
            parent_payload, unused_parent_config = _run_config_value(
                resume["source_run_id"]
            )
            if (
                hashlib.sha256(parent_payload).hexdigest()
                != resume["source_run_config_sha256"]
            ):
                _fail("resume source run-config SHA256 differs")
            located = _resolve_checkpoint(
                resume["source_run_id"],
                step,
                execution_commit,
                plan_id,
                plan,
                visited + (run_id,),
            )
            if step == resume_step and (
                located.checkpoint.manifest_sha256
                != resume["checkpoint_manifest_sha256"]
                or located.trace_prefix_sha256 != resume["trace_prefix_sha256"]
            ):
                _fail("resume ancestry binding differs")
            return located
    checkpoint = verify_training_checkpoint(
        RUN_ROOT / run_id / CHECKPOINT_DIR_NAME,
        _checkpoint_id(step),
        expected_execution_commit=execution_commit,
        expected_config=plan.execution_config,
        expected_artifact_binding=_checkpoint_binding(plan),
    )
    if checkpoint.progress != plan.progress(step):
        _fail("checkpoint progress differs from the training plan")
    rows, digest = _verify_trace_receipt(run_id, checkpoint)
    return LocatedCheckpoint(run_id, checkpoint, rows, digest)


def _checkpoint_ancestry_sha256(
    run_id: str,
    step: int,
    execution_commit: str,
    plan_id: str,
    plan: TrainingPlan,
    visited: tuple[str, ...] = (),
) -> str:
    if run_id in visited or len(visited) >= len(CHECKPOINT_STEPS):
        _fail("checkpoint ancestry is cyclic or too deep")
    config_payload, config = _run_config_value(run_id)
    if (
        config.get("execution_commit") != execution_commit
        or config.get("training_plan", {}).get("plan_id") != plan_id
    ):
        _fail("checkpoint ancestry provenance differs")
    attempt_resource = config.get("resource_gate")
    if not isinstance(attempt_resource, MappingABC):
        _fail("checkpoint ancestry resource binding is invalid")
    verified_attempt_gate = verify_resource_gate(
        Path(attempt_resource.get("path", "")), execution_commit
    )
    if attempt_resource != {
        "path": str(verified_attempt_gate.path),
        "sha256": verified_attempt_gate.sha256,
    }:
        _fail("checkpoint ancestry resource gate differs")
    parent_digest = None
    resume = config.get("resume")
    if resume is not None:
        parent_payload, unused_parent_config = _run_config_value(
            resume["source_run_id"]
        )
        if (
            hashlib.sha256(parent_payload).hexdigest()
            != resume["source_run_config_sha256"]
        ):
            _fail("checkpoint ancestry source config differs")
        parent_step = _checkpoint_step(resume["checkpoint_id"], allow_final=False)
        parent_located = _resolve_checkpoint(
            resume["source_run_id"],
            parent_step,
            execution_commit,
            plan_id,
            plan,
            visited + (run_id,),
        )
        if (
            parent_located.checkpoint.manifest_sha256
            != resume["checkpoint_manifest_sha256"]
            or parent_located.trace_prefix_sha256 != resume["trace_prefix_sha256"]
        ):
            _fail("checkpoint ancestry source receipt differs")
        parent_digest = _checkpoint_ancestry_sha256(
            resume["source_run_id"],
            parent_step,
            execution_commit,
            plan_id,
            plan,
            visited + (run_id,),
        )
        if parent_digest != resume["ancestry_sha256"]:
            _fail("checkpoint parent ancestry SHA256 differs")
    located = _resolve_checkpoint(
        run_id, step, execution_commit, plan_id, plan, visited
    )
    value = {
        "schema_version": "kairos-training-checkpoint-ancestry-v1",
        "run_id": run_id,
        "run_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "training_plan": config["training_plan"],
        "run_input": config["run_input"],
        "attempt_resource_gate": config["resource_gate"],
        "checkpoint_id": _checkpoint_id(step),
        "resolved_artifact_run_id": located.artifact_run_id,
        "checkpoint_manifest_sha256": located.checkpoint.manifest_sha256,
        "trace_prefix_sha256": located.trace_prefix_sha256,
        "parent_ancestry_sha256": parent_digest,
    }
    return sha256_canonical(value)


def train(
    execution_commit: str,
    plan_id: str,
    run_id: str,
    attempt_resource_gate_path: Path,
) -> Mapping[str, Any]:
    if not _SLUG.fullmatch(run_id):
        _fail("training attempt run ID is invalid")
    plan, run_input, records = _load_plan_and_records(plan_id, execution_commit)
    gate = _fresh_attempt_gate(
        attempt_resource_gate_path,
        execution_commit,
        run_input.resource_gate_path,
        run_id,
    )
    _runtime_environment_gate(selected_gpu_uuid=gate.value["selected_gpu"]["uuid"])
    artifact_io._git_gate(execution_commit)
    plan_artifact = training_plan_artifacts.verify_training_plan(plan_id)
    _private_directory(RUN_ROOT.parent, "training-run parent")
    try:
        artifact_io._prepare_root(RUN_ROOT)
    except (PredictionArtifactError, OSError) as error:
        raise ProductionTrainingError("training-run root cannot be prepared") from error
    target = RUN_ROOT / run_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("training run target already exists")
    config_payload = _payload(
        _run_config(run_id, plan_id, plan_artifact, run_input, gate), "run config"
    )
    artifact_io._write_exclusive(target / RUN_CONFIG_NAME, config_payload)
    (target / TRACE_PREFIX_DIR_NAME).mkdir(mode=0o700)
    artifact_io._fsync_directory(target)
    adapter, tokenizer, loader_generator = _initialize_adapter(SEED, gate)
    optimizer = build_optimizer(adapter, plan.execution_config)
    scheduler = build_scheduler(optimizer, plan.execution_config)
    binding = _checkpoint_binding(plan)
    by_id = _records_by_id(records)
    progress = plan.progress(0)
    trace_rows = []
    checkpoints = []
    for step in range(1, plan.total_optimizer_steps + 1):
        window = _materialized_window(
            plan, progress, by_id, tokenizer, torch.device("cuda:0")
        )
        result = execute_planned_training_steps(
            adapter, window, optimizer, scheduler, plan, progress, 1
        )
        progress = result.progress
        trace_rows.append(
            {
                "schema_version": TRACE_SCHEMA,
                "optimizer_step": step,
                "samples_seen": progress.samples_seen,
                "completed_epochs": progress.epoch,
                "loss": result.optimizer_losses[0],
                "gradient_norm": result.gradient_norms[0],
                "learning_rates": [group["lr"] for group in optimizer.param_groups],
            }
        )
        if step in CHECKPOINT_STEPS:
            checkpoint_id = _checkpoint_id(step)
            artifact_io._git_gate(execution_commit)
            verified = save_training_checkpoint(
                target / CHECKPOINT_DIR_NAME,
                checkpoint_id,
                execution_commit,
                plan.execution_config,
                binding,
                adapter,
                optimizer,
                scheduler,
                progress,
                loader_generator,
            )
            artifact_io._git_gate(execution_commit)
            checkpoints.append(verified)
            _publish_trace_receipt(target, run_id, verified, trace_rows)
            artifact_io._git_gate(execution_commit)
    if progress != plan.progress(31) or len(checkpoints) != len(CHECKPOINT_STEPS):
        _fail("training did not reach the frozen final cursor")
    trace_payload = _trace_payload(trace_rows)
    artifact_io._write_exclusive(target / TRACE_NAME, trace_payload)
    artifact_io._fsync_directory(target)
    artifact_io._fsync_directory(RUN_ROOT)
    artifact_io._git_gate(execution_commit)
    return {
        "status": "TRAINING_PAYLOAD_COMPLETE / FINALIZATION_REQUIRED",
        "run_id": run_id,
        "optimizer_steps_completed": progress.optimizer_steps_completed,
        "samples_seen": progress.samples_seen,
        "checkpoint_ids": [value.checkpoint_id for value in checkpoints],
        "trace_sha256": hashlib.sha256(trace_payload).hexdigest(),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
    }


def resume_training(
    execution_commit: str,
    plan_id: str,
    source_run_id: str,
    checkpoint_id: str,
    resume_run_id: str,
    attempt_resource_gate_path: Path,
) -> Mapping[str, Any]:
    """Resume one verified immutable checkpoint into a fresh no-replace run."""

    if (
        not _SLUG.fullmatch(source_run_id)
        or not _SLUG.fullmatch(resume_run_id)
        or source_run_id == resume_run_id
    ):
        _fail("resume run identity is invalid")
    step_value = _checkpoint_step(checkpoint_id, allow_final=False)
    plan, run_input, records = _load_plan_and_records(plan_id, execution_commit)
    gate = _fresh_attempt_gate(
        attempt_resource_gate_path,
        execution_commit,
        run_input.resource_gate_path,
        resume_run_id,
    )
    _runtime_environment_gate(selected_gpu_uuid=gate.value["selected_gpu"]["uuid"])
    artifact_io._git_gate(execution_commit)
    source = RUN_ROOT / source_run_id
    _private_directory(source, "resume source run")
    try:
        source_names = {entry.name for entry in os.scandir(source)}
    except OSError as error:
        raise ProductionTrainingError("resume source cannot be scanned") from error
    if source_names != {
        RUN_CONFIG_NAME,
        CHECKPOINT_DIR_NAME,
        TRACE_PREFIX_DIR_NAME,
    }:
        _fail("resume source is not an immutable interrupted payload")
    source_config_payload, source_config = _run_config_value(source_run_id)
    plan_artifact = training_plan_artifacts.verify_training_plan(plan_id)
    expected_plan = {
        "plan_id": plan_id,
        "manifest_sha256": plan_artifact.manifest_sha256,
        "semantic_sha256": plan_artifact.plan_semantic_sha256,
    }
    expected_input = {
        "artifact_id": run_input.artifact_id,
        "manifest_sha256": run_input.manifest_sha256,
    }
    source_resource = source_config.get("resource_gate")
    if not isinstance(source_resource, MappingABC):
        _fail("resume source resource binding is invalid")
    source_gate = verify_resource_gate(
        Path(source_resource.get("path", "")), execution_commit
    )
    if (
        source_config.get("execution_commit") != execution_commit
        or source_config.get("training_plan") != expected_plan
        or source_config.get("run_input") != expected_input
        or source_resource
        != {"path": str(source_gate.path), "sha256": source_gate.sha256}
    ):
        _fail("resume source provenance differs")
    located = _resolve_checkpoint(
        source_run_id, step_value, execution_commit, plan_id, plan
    )
    ancestry_sha256 = _checkpoint_ancestry_sha256(
        source_run_id, step_value, execution_commit, plan_id, plan
    )
    resume_binding = {
        "source_run_id": source_run_id,
        "checkpoint_id": checkpoint_id,
        "source_run_config_sha256": hashlib.sha256(
            source_config_payload
        ).hexdigest(),
        "checkpoint_manifest_sha256": located.checkpoint.manifest_sha256,
        "trace_prefix_sha256": located.trace_prefix_sha256,
        "ancestry_sha256": ancestry_sha256,
    }
    _private_directory(RUN_ROOT.parent, "training-run parent")
    try:
        artifact_io._prepare_root(RUN_ROOT)
    except (PredictionArtifactError, OSError) as error:
        raise ProductionTrainingError("training-run root cannot be prepared") from error
    target = RUN_ROOT / resume_run_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("resume training target already exists")
    config_payload = _payload(
        _run_config(
            resume_run_id,
            plan_id,
            plan_artifact,
            run_input,
            gate,
            resume_binding,
        ),
        "resume run config",
    )
    artifact_io._write_exclusive(target / RUN_CONFIG_NAME, config_payload)
    (target / TRACE_PREFIX_DIR_NAME).mkdir(mode=0o700)
    artifact_io._fsync_directory(target)
    adapter, tokenizer, loader_generator = _initialize_adapter(SEED, gate)
    optimizer = build_optimizer(adapter, plan.execution_config)
    scheduler = build_scheduler(optimizer, plan.execution_config)
    binding = _checkpoint_binding(plan)
    progress = resume_training_checkpoint(
        located.checkpoint.artifact_path.parent,
        checkpoint_id,
        execution_commit,
        binding,
        plan.execution_config,
        adapter,
        optimizer,
        scheduler,
        loader_generator,
    )
    if progress != plan.progress(step_value):
        _fail("restored progress differs from the explicit checkpoint")
    by_id = _records_by_id(records)
    trace_rows = list(located.trace_rows)
    checkpoints = []
    for step in range(step_value + 1, plan.total_optimizer_steps + 1):
        window = _materialized_window(
            plan, progress, by_id, tokenizer, torch.device("cuda:0")
        )
        result = execute_planned_training_steps(
            adapter, window, optimizer, scheduler, plan, progress, 1
        )
        progress = result.progress
        trace_rows.append(
            {
                "schema_version": TRACE_SCHEMA,
                "optimizer_step": step,
                "samples_seen": progress.samples_seen,
                "completed_epochs": progress.epoch,
                "loss": result.optimizer_losses[0],
                "gradient_norm": result.gradient_norms[0],
                "learning_rates": [group["lr"] for group in optimizer.param_groups],
            }
        )
        if step in CHECKPOINT_STEPS:
            artifact_io._git_gate(execution_commit)
            verified = save_training_checkpoint(
                target / CHECKPOINT_DIR_NAME,
                _checkpoint_id(step),
                execution_commit,
                plan.execution_config,
                binding,
                adapter,
                optimizer,
                scheduler,
                progress,
                loader_generator,
            )
            _publish_trace_receipt(target, resume_run_id, verified, trace_rows)
            artifact_io._git_gate(execution_commit)
            checkpoints.append(verified)
    if progress != plan.progress(31):
        _fail("resumed training did not reach the frozen final cursor")
    trace_payload = _trace_payload(trace_rows)
    _verify_trace(trace_payload)
    artifact_io._write_exclusive(target / TRACE_NAME, trace_payload)
    artifact_io._fsync_directory(target)
    artifact_io._fsync_directory(RUN_ROOT)
    artifact_io._git_gate(execution_commit)
    return {
        "status": "TRAINING_PAYLOAD_COMPLETE / FINALIZATION_REQUIRED",
        "run_id": resume_run_id,
        "resumed_from": resume_binding,
        "optimizer_steps_completed": progress.optimizer_steps_completed,
        "samples_seen": progress.samples_seen,
        "new_checkpoint_ids": [value.checkpoint_id for value in checkpoints],
        "trace_sha256": hashlib.sha256(trace_payload).hexdigest(),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
    }


def _run_config_value(run_id: str) -> tuple[bytes, Mapping[str, Any]]:
    target = RUN_ROOT / run_id
    payload = _read(target / RUN_CONFIG_NAME, _JSON_LIMIT, RUN_CONFIG_NAME)
    value = _object(payload, "run config")
    if (
        set(value) != {
            "schema_version", "status", "run_id", "started_at_utc",
            "experiment_id", "execution_commit", "method", "seed", "run_input",
            "training_plan", "resource_gate", "checkpoint_steps",
            "result_scope", "paper_metric_eligible", "resume",
        }
        or value.get("schema_version") != RUN_CONFIG_SCHEMA
        or value.get("status") != "TRAINING_STARTED_DEVELOPMENT_ONLY"
        or value.get("run_id") != run_id
        or value.get("experiment_id") != _run_id(value.get("execution_commit", ""))
        or value.get("method") != "kairos"
        or value.get("seed") != SEED
        or value.get("checkpoint_steps") != list(CHECKPOINT_STEPS)
        or value.get("result_scope")
        != "DEVELOPMENT / INTERNAL-DEV / NOT PAPER-ELIGIBLE"
        or value.get("paper_metric_eligible") is not False
        or (
            value.get("resume") is not None
            and (
                not isinstance(value["resume"], MappingABC)
                or set(value["resume"])
                != {
                    "source_run_id", "checkpoint_id",
                    "source_run_config_sha256", "checkpoint_manifest_sha256",
                    "trace_prefix_sha256", "ancestry_sha256",
                }
                or not _SLUG.fullmatch(value["resume"].get("source_run_id", ""))
                or value["resume"].get("checkpoint_id")
                not in {_checkpoint_id(step) for step in CHECKPOINT_STEPS[:-1]}
                or not _HEX64.fullmatch(
                    value["resume"].get("source_run_config_sha256", "")
                )
                or not _HEX64.fullmatch(
                    value["resume"].get("checkpoint_manifest_sha256", "")
                )
                or not _HEX64.fullmatch(
                    value["resume"].get("trace_prefix_sha256", "")
                )
                or not _HEX64.fullmatch(
                    value["resume"].get("ancestry_sha256", "")
                )
            )
        )
    ):
        _fail("training run config differs")
    return payload, value


def _verify_trace_prefix(
    payload: bytes, expected_steps: int
) -> tuple[Mapping[str, Any], ...]:
    if expected_steps not in CHECKPOINT_STEPS:
        _fail("trace-prefix checkpoint step is invalid")
    rows = _candidate_rows(payload, "training trace")
    if len(rows) != expected_steps:
        _fail("training trace step count differs")
    for step, row in enumerate(rows, start=1):
        if (
            set(row) != {
                "schema_version", "optimizer_step", "samples_seen",
                "completed_epochs", "loss", "gradient_norm", "learning_rates",
            }
            or row["schema_version"] != TRACE_SCHEMA
            or row["optimizer_step"] != step
            or row["samples_seen"] != step * 32
            or row["completed_epochs"]
            != min(min(step * 32, 990) // 330, 3)
            or not isinstance(row["loss"], (int, float))
            or not math.isfinite(row["loss"])
            or not isinstance(row["gradient_norm"], (int, float))
            or not math.isfinite(row["gradient_norm"])
            or not isinstance(row["learning_rates"], list)
            or len(row["learning_rates"]) != 2
            or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in row["learning_rates"])
        ):
            _fail("training trace row differs")
    return rows


def _verify_trace(payload: bytes) -> tuple[Mapping[str, Any], ...]:
    return _verify_trace_prefix(payload, 31)


def _trace_payload(rows: Sequence[Mapping[str, Any]]) -> bytes:
    payload = b"".join(
        canonical_json(row).encode("utf-8") + b"\n" for row in rows
    )
    if len(payload) > _TRACE_LIMIT:
        _fail("training trace exceeds its byte limit")
    return payload


def _verified_checkpoints(
    run_id: str,
    execution_commit: str,
    plan_id: str,
    plan: TrainingPlan,
) -> tuple[LocatedCheckpoint, ...]:
    result = tuple(
        _resolve_checkpoint(run_id, step, execution_commit, plan_id, plan)
        for step in CHECKPOINT_STEPS
    )
    unused_payload, config = _run_config_value(run_id)
    resume = config.get("resume")
    first_own_step = (
        0 if resume is None else _checkpoint_step(resume["checkpoint_id"], allow_final=False)
    )
    own_steps = {step for step in CHECKPOINT_STEPS if step > first_own_step}
    target = RUN_ROOT / run_id
    _private_directory(target / CHECKPOINT_DIR_NAME, "checkpoint root")
    try:
        names = {entry.name for entry in os.scandir(target / CHECKPOINT_DIR_NAME)}
    except OSError as error:
        raise ProductionTrainingError("checkpoint root cannot be scanned") from error
    if names != {_checkpoint_id(step) for step in own_steps}:
        _fail("checkpoint root namespace differs")
    _private_directory(target / TRACE_PREFIX_DIR_NAME, "trace-prefix root")
    try:
        prefix_names = {
            entry.name for entry in os.scandir(target / TRACE_PREFIX_DIR_NAME)
        }
    except OSError as error:
        raise ProductionTrainingError("trace-prefix root cannot be scanned") from error
    if prefix_names != {_trace_receipt_name(step) for step in own_steps}:
        _fail("trace-prefix root namespace differs")
    return result


def _post_resource(gate: VerifiedResourceGate) -> Mapping[str, Any]:
    gpu = gate.value["selected_gpu"]
    identity = _gpu_identity(gpu["uuid"])
    processes = _gpu_processes(gpu["uuid"])
    if (
        identity["physical_index"] != gpu["physical_index"]
        or identity["pci_bus_id"].casefold() != gpu["pci_bus_id"].casefold()
        or identity["name"] != gpu["name"]
        or identity["total_mib"] != gpu["total_mib"]
        or identity["free_mib"] < MIN_FREE_GPU_MIB
        or processes
    ):
        _fail("selected GPU was not released after training")
    available_memory = _memory_available_bytes()
    filesystem = os.statvfs(ALLOWED_ROOT)
    data0_free = filesystem.f_bavail * filesystem.f_frsize
    if available_memory < 64 * 1024**3 or data0_free < 120 * 1024**3:
        _fail("post-training host resource floor is not satisfied")
    return {
        "schema_version": POST_RESOURCE_SCHEMA,
        "status": "GPU_RELEASE_VERIFIED",
        "observed_at_utc": _utc_now(),
        "resource_gate_sha256": gate.sha256,
        "selected_gpu": identity,
        "compute_process_count": 0,
        "memory_available_bytes": available_memory,
        "data0_free_bytes": data0_free,
    }


def _crosscheck_trace_receipts(
    trace_rows: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[LocatedCheckpoint],
) -> None:
    if len(trace_rows) != 31 or len(checkpoints) != len(CHECKPOINT_STEPS):
        _fail("trace/checkpoint coverage differs")
    for step, located in zip(CHECKPOINT_STEPS, checkpoints):
        expected_rows = tuple(trace_rows[:step])
        expected_payload = _trace_payload(expected_rows)
        if (
            located.checkpoint.progress.optimizer_steps_completed != step
            or located.trace_rows != expected_rows
            or located.trace_prefix_sha256
            != hashlib.sha256(expected_payload).hexdigest()
        ):
            _fail("training trace diverges from checkpoint receipt")


def _run_manifest(
    run_id: str,
    execution_commit: str,
    plan_id: str,
    run_input: VerifiedRunInput,
    config_payload: bytes,
    trace_payload: bytes,
    post_payload: bytes,
    checkpoints: Sequence[LocatedCheckpoint],
    ancestry_sha256: str,
) -> Mapping[str, Any]:
    config_value = _object(config_payload, "run config for manifest")
    return {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "status": RUN_STATUS,
        "run_id": run_id,
        "experiment_id": _run_id(execution_commit),
        "execution_commit": execution_commit,
        "method": "kairos",
        "seed": SEED,
        "result_scope": "DEVELOPMENT / INTERNAL-DEV / NOT PAPER-ELIGIBLE",
        "paper_metric_eligible": False,
        "run_input": {
            "artifact_id": run_input.artifact_id,
            "manifest_sha256": run_input.manifest_sha256,
        },
        "training_plan_id": plan_id,
        "ancestry_sha256": ancestry_sha256,
        "attempt_resource_gate": config_value["resource_gate"],
        "files": {
            RUN_CONFIG_NAME: _binding(config_payload),
            TRACE_NAME: _binding(trace_payload, count=31),
            POST_RESOURCE_NAME: _binding(post_payload),
        },
        "checkpoints": [
            {
                "artifact_run_id": value.artifact_run_id,
                "checkpoint_id": value.checkpoint.checkpoint_id,
                "optimizer_steps_completed": value.checkpoint.progress.optimizer_steps_completed,
                "config_sha256": value.checkpoint.config_sha256,
                "state_sha256": value.checkpoint.state_sha256,
                "manifest_sha256": value.checkpoint.manifest_sha256,
                "trace_prefix_sha256": value.trace_prefix_sha256,
            }
            for value in checkpoints
        ],
        "final_checkpoint_id": _checkpoint_id(31),
        "optimizer_steps_completed": 31,
        "samples_seen": 992,
        "real_slots": 990,
        "repeat_padding_slots": 2,
    }


def finalize(run_id: str) -> VerifiedTrainingRun:
    _runtime_environment_gate()
    if not _SLUG.fullmatch(run_id):
        _fail("training run ID is invalid")
    target = RUN_ROOT / run_id
    _private_namespace(
        target,
        {RUN_CONFIG_NAME, TRACE_NAME, CHECKPOINT_DIR_NAME, TRACE_PREFIX_DIR_NAME},
        "training run payload",
    )
    config_payload, config = _run_config_value(run_id)
    execution_commit = config.get("execution_commit")
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("training execution commit is invalid")
    artifact_io._git_gate(execution_commit)
    plan_value = config.get("training_plan")
    input_value = config.get("run_input")
    resource_value = config.get("resource_gate")
    if not all(isinstance(value, MappingABC) for value in (plan_value, input_value, resource_value)):
        _fail("training config provenance binding is invalid")
    plan_id = plan_value.get("plan_id")
    plan, run_input, unused_records = _load_plan_and_records(plan_id, execution_commit)
    plan_artifact = training_plan_artifacts.verify_training_plan(plan_id)
    if plan_value != {
        "plan_id": plan_id,
        "manifest_sha256": plan_artifact.manifest_sha256,
        "semantic_sha256": plan_artifact.plan_semantic_sha256,
    }:
        _fail("run config training-plan binding differs")
    if input_value != {
        "artifact_id": run_input.artifact_id,
        "manifest_sha256": run_input.manifest_sha256,
    }:
        _fail("run config run-input binding differs")
    gate = verify_resource_gate(Path(resource_value.get("path", "")), execution_commit)
    if resource_value.get("sha256") != gate.sha256:
        _fail("run config resource binding differs")
    checkpoints = _verified_checkpoints(run_id, execution_commit, plan_id, plan)
    trace_payload = _read(target / TRACE_NAME, _TRACE_LIMIT, TRACE_NAME)
    trace_rows = _verify_trace(trace_payload)
    _crosscheck_trace_receipts(trace_rows, checkpoints)
    ancestry_sha256 = _checkpoint_ancestry_sha256(
        run_id, 31, execution_commit, plan_id, plan
    )
    post_payload = _payload(_post_resource(gate), "post-resource")
    artifact_io._write_exclusive(target / POST_RESOURCE_NAME, post_payload)
    artifact_io._fsync_directory(target)
    manifest_payload = _payload(
        _run_manifest(
            run_id,
            execution_commit,
            plan_id,
            run_input,
            config_payload,
            trace_payload,
            post_payload,
            checkpoints,
            ancestry_sha256,
        ),
        "training run manifest",
    )
    artifact_io._git_gate(execution_commit)
    artifact_io._write_exclusive(target / MANIFEST_NAME, manifest_payload)
    artifact_io._fsync_directory(target)
    artifact_io._fsync_directory(RUN_ROOT)
    return verify_run(run_id)


def verify_run(run_id: str) -> VerifiedTrainingRun:
    _runtime_environment_gate()
    if not _SLUG.fullmatch(run_id):
        _fail("training run ID is invalid")
    target = RUN_ROOT / run_id
    _private_namespace(
        target,
        {
            RUN_CONFIG_NAME, TRACE_NAME, POST_RESOURCE_NAME, MANIFEST_NAME,
            CHECKPOINT_DIR_NAME, TRACE_PREFIX_DIR_NAME,
        },
        "training run artifact",
    )
    config_payload, config = _run_config_value(run_id)
    trace_payload = _read(target / TRACE_NAME, _TRACE_LIMIT, TRACE_NAME)
    post_payload = _read(target / POST_RESOURCE_NAME, _JSON_LIMIT, POST_RESOURCE_NAME)
    manifest_payload = _read(target / MANIFEST_NAME, _JSON_LIMIT, MANIFEST_NAME)
    trace_rows = _verify_trace(trace_payload)
    post = _object(post_payload, "post-resource")
    manifest = _object(manifest_payload, "training run manifest")
    execution_commit = config.get("execution_commit")
    plan_id = config["training_plan"]["plan_id"]
    plan, run_input, unused_records = _load_plan_and_records(plan_id, execution_commit)
    gate = verify_resource_gate(Path(config["resource_gate"]["path"]), execution_commit)
    if (
        post.get("schema_version") != POST_RESOURCE_SCHEMA
        or post.get("status") != "GPU_RELEASE_VERIFIED"
        or post.get("resource_gate_sha256") != gate.sha256
        or post.get("compute_process_count") != 0
        or not isinstance(post.get("selected_gpu"), MappingABC)
        or post["selected_gpu"].get("uuid")
        != gate.value["selected_gpu"]["uuid"]
        or post["selected_gpu"].get("pci_bus_id", "").casefold()
        != gate.value["selected_gpu"]["pci_bus_id"].casefold()
        or post["selected_gpu"].get("free_mib", 0) < MIN_FREE_GPU_MIB
        or post.get("memory_available_bytes", 0) < 64 * 1024**3
        or post.get("data0_free_bytes", 0) < 120 * 1024**3
    ):
        _fail("post-resource record differs")
    checkpoints = _verified_checkpoints(run_id, execution_commit, plan_id, plan)
    _crosscheck_trace_receipts(trace_rows, checkpoints)
    ancestry_sha256 = _checkpoint_ancestry_sha256(
        run_id, 31, execution_commit, plan_id, plan
    )
    expected = _run_manifest(
        run_id,
        execution_commit,
        plan_id,
        run_input,
        config_payload,
        trace_payload,
        post_payload,
        checkpoints,
        ancestry_sha256,
    )
    if manifest != expected:
        _fail("training run manifest differs")
    return VerifiedTrainingRun(
        run_id,
        target,
        execution_commit,
        plan_id,
        _checkpoint_id(31),
        hashlib.sha256(manifest_payload).hexdigest(),
        hashlib.sha256(trace_payload).hexdigest(),
    )


def publish_failure(
    failure_id: str,
    execution_commit: str,
    command: str,
    run_id: str,
    error: BaseException,
    attempt_resource_gate_path: Path | None = None,
) -> Mapping[str, Any]:
    """Publish bounded failure evidence outside an immutable run target."""

    if (
        not _SLUG.fullmatch(failure_id)
        or not _HEX40.fullmatch(execution_commit)
        or command not in {"train", "resume"}
        or not _SLUG.fullmatch(run_id)
    ):
        _fail("training failure identity is invalid")
    message = str(error)
    if len(message.encode("utf-8", errors="replace")) > 2048:
        message = message.encode("utf-8", errors="replace")[:2048].decode(
            "utf-8", errors="ignore"
        )
    try:
        artifact_io._git_gate(execution_commit)
        clean_git = True
    except (PredictionArtifactError, OSError, RuntimeError):
        clean_git = False
    attempt_gate = None
    if attempt_resource_gate_path is not None:
        try:
            verified_gate = verify_resource_gate(
                attempt_resource_gate_path, execution_commit
            )
            attempt_gate = {
                "path": str(verified_gate.path),
                "sha256": verified_gate.sha256,
            }
        except (ProductionTrainingError, PredictionArtifactError, OSError, RuntimeError):
            attempt_gate = None
    run_config_sha256 = None
    try:
        run_config_payload = _read(
            RUN_ROOT / run_id / RUN_CONFIG_NAME, _JSON_LIMIT, RUN_CONFIG_NAME
        )
        run_config_sha256 = hashlib.sha256(run_config_payload).hexdigest()
    except (ProductionTrainingError, PredictionArtifactError, OSError):
        run_config_sha256 = None
    value = {
        "schema_version": FAILURE_SCHEMA,
        "status": "TRAINING_FAILED_DEVELOPMENT_ONLY",
        "failure_id": failure_id,
        "observed_at_utc": _utc_now(),
        "execution_commit": execution_commit,
        "command": command,
        "run_id": run_id,
        "error_type": type(error).__name__,
        "error_message": message,
        "clean_git_at_failure_record": clean_git,
        "attempt_resource_gate": attempt_gate,
        "run_config_sha256": run_config_sha256,
        "paper_metric_eligible": False,
    }
    failure_payload = _payload(value, "training failure")
    manifest_value = {
        "schema_version": "kairos-training-failure-manifest-v1",
        "status": "TRAINING_FAILURE_COMPLETE_DEVELOPMENT_ONLY",
        "failure_id": failure_id,
        "files": [FAILURE_NAME, MANIFEST_NAME],
        "failure": _binding(failure_payload),
        "paper_metric_eligible": False,
    }
    _private_directory(FAILURE_ROOT.parent, "training failure parent")
    artifact_io._prepare_root(FAILURE_ROOT)
    target = FAILURE_ROOT / failure_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("training failure target already exists")
    artifact_io._write_exclusive(target / FAILURE_NAME, failure_payload)
    artifact_io._fsync_directory(target)
    artifact_io._write_exclusive(
        target / MANIFEST_NAME, _payload(manifest_value, "training failure manifest")
    )
    artifact_io._fsync_directory(target)
    artifact_io._fsync_directory(FAILURE_ROOT)
    return verify_failure(failure_id)


def verify_failure(failure_id: str) -> Mapping[str, Any]:
    if not _SLUG.fullmatch(failure_id):
        _fail("training failure ID is invalid")
    target = FAILURE_ROOT / failure_id
    _private_namespace(target, {FAILURE_NAME, MANIFEST_NAME}, "training failure")
    failure_payload = _read(target / FAILURE_NAME, _JSON_LIMIT, FAILURE_NAME)
    manifest_payload = _read(target / MANIFEST_NAME, _JSON_LIMIT, MANIFEST_NAME)
    value = _object(failure_payload, "training failure")
    manifest = _object(manifest_payload, "training failure manifest")
    if (
        set(value)
        != {
            "schema_version", "status", "failure_id", "observed_at_utc",
            "execution_commit", "command", "run_id", "error_type",
            "error_message", "clean_git_at_failure_record",
            "attempt_resource_gate", "run_config_sha256", "paper_metric_eligible",
        }
        or value.get("schema_version") != FAILURE_SCHEMA
        or value.get("status") != "TRAINING_FAILED_DEVELOPMENT_ONLY"
        or value.get("failure_id") != failure_id
        or value.get("command") not in {"train", "resume"}
        or not _HEX40.fullmatch(value.get("execution_commit", ""))
        or not _SLUG.fullmatch(value.get("run_id", ""))
        or not isinstance(value.get("error_type"), str)
        or not isinstance(value.get("error_message"), str)
        or len(value["error_message"].encode("utf-8")) > 2048
        or not isinstance(value.get("clean_git_at_failure_record"), bool)
        or (
            value.get("attempt_resource_gate") is not None
            and (
                not isinstance(value["attempt_resource_gate"], MappingABC)
                or set(value["attempt_resource_gate"]) != {"path", "sha256"}
                or not _HEX64.fullmatch(
                    value["attempt_resource_gate"].get("sha256", "")
                )
            )
        )
        or (
            value.get("run_config_sha256") is not None
            and not _HEX64.fullmatch(value["run_config_sha256"])
        )
        or value.get("paper_metric_eligible") is not False
    ):
        _fail("training failure record differs")
    expected_manifest = {
        "schema_version": "kairos-training-failure-manifest-v1",
        "status": "TRAINING_FAILURE_COMPLETE_DEVELOPMENT_ONLY",
        "failure_id": failure_id,
        "files": [FAILURE_NAME, MANIFEST_NAME],
        "failure": _binding(failure_payload),
        "paper_metric_eligible": False,
    }
    if manifest != expected_manifest:
        _fail("training failure manifest differs")
    attempt_binding = value.get("attempt_resource_gate")
    if attempt_binding is not None:
        verified_gate = verify_resource_gate(
            Path(attempt_binding["path"]), value["execution_commit"]
        )
        if attempt_binding != {
            "path": str(verified_gate.path),
            "sha256": verified_gate.sha256,
        }:
            _fail("training failure attempt-gate binding differs")
    config_binding = value.get("run_config_sha256")
    config_path = RUN_ROOT / value["run_id"] / RUN_CONFIG_NAME
    try:
        config_payload = _read(config_path, _JSON_LIMIT, RUN_CONFIG_NAME)
    except (ProductionTrainingError, PredictionArtifactError, OSError):
        if config_binding is not None:
            _fail("training failure run-config is unavailable")
    else:
        if (
            config_binding is None
            or hashlib.sha256(config_payload).hexdigest() != config_binding
        ):
            _fail("training failure run-config binding differs")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("capture-gate")
    gate.add_argument("--execution-commit", required=True)
    gate.add_argument("--gpu-uuid", required=True)
    gate.add_argument("--gate-id", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--execution-commit", required=True)
    smoke = commands.add_parser("gpu-smoke")
    smoke.add_argument("--execution-commit", required=True)
    smoke.add_argument("--resource-gate", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--execution-commit", required=True)
    prepare.add_argument("--resource-gate", type=Path, required=True)
    train_parser = commands.add_parser("train")
    train_parser.add_argument("--execution-commit", required=True)
    train_parser.add_argument("--plan-id", required=True)
    train_parser.add_argument("--run-id", required=True)
    train_parser.add_argument("--attempt-resource-gate", type=Path, required=True)
    train_parser.add_argument("--failure-id", required=True)
    resume_parser = commands.add_parser("resume")
    resume_parser.add_argument("--execution-commit", required=True)
    resume_parser.add_argument("--plan-id", required=True)
    resume_parser.add_argument("--source-run-id", required=True)
    resume_parser.add_argument("--checkpoint-id", required=True)
    resume_parser.add_argument("--resume-run-id", required=True)
    resume_parser.add_argument("--attempt-resource-gate", type=Path, required=True)
    resume_parser.add_argument("--failure-id", required=True)
    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--run-id", required=True)
    verify_input = commands.add_parser("verify-run-input")
    verify_input.add_argument("--artifact-id", required=True)
    verify_input.add_argument("--expected-commit")
    verify_plan = commands.add_parser("verify-plan")
    verify_plan.add_argument("--plan-id", required=True)
    verify_parser = commands.add_parser("verify-run")
    verify_parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        _runtime_environment_gate()
        if arguments.command == "capture-gate":
            value: Any = capture_resource_gate(
                arguments.execution_commit, arguments.gpu_uuid, arguments.gate_id
            )
            result = {
                "status": "PASSED",
                "path": str(value.path),
                "sha256": value.sha256,
            }
        elif arguments.command == "inspect":
            result = inspect_real_materialization(arguments.execution_commit)
        elif arguments.command == "gpu-smoke":
            result = gpu_smoke(arguments.execution_commit, arguments.resource_gate)
        elif arguments.command == "prepare":
            value = prepare_training(arguments.execution_commit, arguments.resource_gate)
            result = {
                "status": "TRAINING_PREPARED_DEVELOPMENT_ONLY",
                "run_input_id": value.run_input.artifact_id,
                "run_input_manifest_sha256": value.run_input.manifest_sha256,
                "plan_id": value.plan_artifact.plan_id,
                "plan_manifest_sha256": value.plan_artifact.manifest_sha256,
                "plan_semantic_sha256": value.plan_artifact.plan_semantic_sha256,
            }
        elif arguments.command == "train":
            result = train(
                arguments.execution_commit,
                arguments.plan_id,
                arguments.run_id,
                arguments.attempt_resource_gate,
            )
        elif arguments.command == "resume":
            result = resume_training(
                arguments.execution_commit,
                arguments.plan_id,
                arguments.source_run_id,
                arguments.checkpoint_id,
                arguments.resume_run_id,
                arguments.attempt_resource_gate,
            )
        elif arguments.command == "finalize":
            value = finalize(arguments.run_id)
            result = {
                "status": RUN_STATUS,
                "run_id": value.run_id,
                "manifest_sha256": value.manifest_sha256,
                "trace_sha256": value.trace_sha256,
                "final_checkpoint_id": value.final_checkpoint_id,
            }
        elif arguments.command == "verify-run-input":
            value = verify_run_input(arguments.artifact_id, arguments.expected_commit)
            result = {
                "status": RUN_INPUT_STATUS,
                "artifact_id": value.artifact_id,
                "manifest_sha256": value.manifest_sha256,
            }
        elif arguments.command == "verify-plan":
            value = training_plan_artifacts.verify_training_plan(arguments.plan_id)
            result = {
                "status": "TRAINING_PLAN_COMPLETE",
                "plan_id": value.plan_id,
                "manifest_sha256": value.manifest_sha256,
                "semantic_sha256": value.plan_semantic_sha256,
            }
        else:
            value = verify_run(arguments.run_id)
            result = {
                "status": RUN_STATUS,
                "run_id": value.run_id,
                "manifest_sha256": value.manifest_sha256,
                "trace_sha256": value.trace_sha256,
                "final_checkpoint_id": value.final_checkpoint_id,
            }
    except (
        ProductionTrainingError,
        PredictionArtifactError,
        ValueError,
        OSError,
        RuntimeError,
    ) as error:
        if arguments.command in {"train", "resume"}:
            run_id = (
                arguments.run_id
                if arguments.command == "train"
                else arguments.resume_run_id
            )
            try:
                publish_failure(
                    arguments.failure_id,
                    arguments.execution_commit,
                    arguments.command,
                    run_id,
                    error,
                    arguments.attempt_resource_gate,
                )
            except Exception as failure_error:
                print(
                    canonical_json(
                        {
                            "status": "FAILURE_RECORD_FAILED",
                            "error": str(failure_error),
                        }
                    ),
                    file=sys.stderr,
                )
        print(canonical_json({"status": "FAILED", "error": str(error)}), file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
