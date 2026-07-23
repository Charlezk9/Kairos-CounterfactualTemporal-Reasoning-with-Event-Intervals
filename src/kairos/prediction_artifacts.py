"""Immutable, model-agnostic prediction artifacts for formal evaluation."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable, Mapping, Sequence

from .ids import canonical_json
from .transfer_eval import load_timeqa_hard, load_torque_dev


_PROJECT_ROOT = Path("/home/yangbin/zx-tmp/kairos")
_ARTIFACT_ROOT = Path("/data0/hk_data/kairos-zx/artifacts")
_MANIFEST_SCHEMA = "prediction-run-manifest-v1"
_RECORD_SCHEMA = "prediction-record-v1"
_STATUS = "PREDICTIONS_COMPLETE"
_CONFIG_NAME = "config.json"
_PREDICTIONS_NAME = "predictions.jsonl"
_MANIFEST_NAME = "manifest.json"
_FINAL_NAMES = frozenset({_CONFIG_NAME, _PREDICTIONS_NAME, _MANIFEST_NAME})
_CONFIG_LIMIT = 1_048_576
_PREDICTION_LINE_LIMIT = 262_144
_PREDICTIONS_LIMIT = 128 * 1024 * 1024
_MANIFEST_LIMIT = 262_144
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_RUN_ID = re.compile(
    r"^[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,39}-"
    r"(?:torque-dev|timeqa-hard)-s[0-9]{1,10}-[0-9a-f]{12}$"
)


class PredictionArtifactError(ValueError):
    """A prediction artifact invariant failed."""


@dataclass(frozen=True)
class _DatasetBinding:
    name: str
    split: str
    revision: str
    source_sha256: str
    record_count: int
    adapter_schema_version: str
    metric_contract_version: str
    prediction_value_schema: str
    loader: Callable[[], Sequence[Any]]


_BINDINGS = {
    "torque-dev": _DatasetBinding(
        name="torque-dev",
        split="public-dev",
        revision="ab27019cc6a317fde3c879900499f02acce8b16d",
        source_sha256=(
            "7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434"
        ),
        record_count=1483,
        adapter_schema_version="torque-dev-adapter-v1",
        metric_contract_version="torque-set-metrics-v1",
        prediction_value_schema="string-array",
        loader=load_torque_dev,
    ),
    "timeqa-hard": _DatasetBinding(
        name="timeqa-hard",
        split="human_test.hard",
        revision="38b05989070c1168b2bef3d5a2656afeeba763dc",
        source_sha256=(
            "0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188"
        ),
        record_count=989,
        adapter_schema_version="timeqa-hard-adapter-v1",
        metric_contract_version="timeqa-official-string-metrics-v1",
        prediction_value_schema="string",
        loader=load_timeqa_hard,
    ),
}


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PredictionArtifactError(f"{name} must be a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise PredictionArtifactError(f"{name} is not valid Unicode") from error
    if not allow_empty and not value.strip():
        raise PredictionArtifactError(f"{name} must be non-empty")
    return value


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PredictionArtifactError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise PredictionArtifactError(f"{name} is outside its allowed range")
    return value


def _exact_mapping(
    value: Any, expected: set[str], name: str
) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC):
        raise PredictionArtifactError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise PredictionArtifactError(f"{name} keys must be strings")
    missing = expected.difference(value)
    extra = set(value).difference(expected)
    if missing or extra:
        raise PredictionArtifactError(
            f"invalid {name} keys; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        raise PredictionArtifactError(f"{name} must be a non-string sequence")
    return value


def _config_bytes(config: Mapping[str, Any]) -> bytes:
    if not isinstance(config, MappingABC):
        raise PredictionArtifactError("configuration must be a mapping")
    try:
        content = canonical_json(config).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise PredictionArtifactError(
            "configuration is not canonical-JSON compatible"
        ) from error
    if len(content) > _CONFIG_LIMIT:
        raise PredictionArtifactError("configuration exceeds its byte limit")
    return content


def _parse_utc(value: Any, name: str) -> datetime:
    text = _text(value, name)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", text):
        raise PredictionArtifactError(f"{name} must be second-resolution UTC")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise PredictionArtifactError(f"{name} is not a valid UTC timestamp") from error
    return parsed


def make_run_id(
    started_at: str,
    method_name: str,
    dataset: str,
    seed: int,
    config: Mapping[str, Any],
) -> str:
    """Create the only accepted run ID from literal run inputs."""

    started = _parse_utc(started_at, "started_at")
    method_name = _text(method_name, "method name")
    if not _SLUG.fullmatch(method_name):
        raise PredictionArtifactError("method name must be a lowercase slug")
    if dataset not in _BINDINGS:
        raise PredictionArtifactError("dataset is not a frozen evaluation binding")
    seed = _integer(seed, "seed", 0, 2_147_483_647)
    digest = hashlib.sha256(_config_bytes(config)).hexdigest()[:12]
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{method_name}-{dataset}-s{seed}-{digest}"


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    dataset: str
    method_name: str
    model_id: str
    model_revision: str
    execution_commit: str
    seed: int
    started_at: str
    completed_at: str
    config: Mapping[str, Any]
    gpu_ids: tuple[int, ...]
    cpu_threads: int
    memory_gib: int
    dataloader_workers: int

    def __post_init__(self) -> None:
        if self.dataset not in _BINDINGS:
            raise PredictionArtifactError("dataset is not a frozen evaluation binding")
        _text(self.method_name, "method name")
        if not _SLUG.fullmatch(self.method_name):
            raise PredictionArtifactError("method name must be a lowercase slug")
        _text(self.model_id, "model ID")
        _text(self.model_revision, "model revision")
        if not isinstance(self.execution_commit, str) or not _HEX40.fullmatch(
            self.execution_commit
        ):
            raise PredictionArtifactError("execution commit must be 40 lowercase hex")
        _integer(self.seed, "seed", 0, 2_147_483_647)
        started = _parse_utc(self.started_at, "started_at")
        completed = _parse_utc(self.completed_at, "completed_at")
        if completed < started:
            raise PredictionArtifactError("completed_at precedes started_at")
        _config_bytes(self.config)
        if not isinstance(self.gpu_ids, tuple):
            raise PredictionArtifactError("gpu_ids must be a tuple")
        for gpu_id in self.gpu_ids:
            _integer(gpu_id, "GPU ID", 0, 63)
        if len(self.gpu_ids) > 4 or len(set(self.gpu_ids)) != len(self.gpu_ids):
            raise PredictionArtifactError("gpu_ids violate uniqueness or count limits")
        _integer(self.cpu_threads, "cpu_threads", 1, 16)
        _integer(self.memory_gib, "memory_gib", 1, 64)
        _integer(self.dataloader_workers, "dataloader_workers", 0, 8)
        expected = make_run_id(
            self.started_at,
            self.method_name,
            self.dataset,
            self.seed,
            self.config,
        )
        if self.run_id != expected or not _RUN_ID.fullmatch(self.run_id):
            raise PredictionArtifactError("run ID differs from its literal inputs")


@dataclass(frozen=True)
class PredictionRecord:
    record_id: str
    prediction: Any


@dataclass(frozen=True)
class VerifiedPredictionArtifact:
    spec: RunSpec
    records: tuple[PredictionRecord, ...]
    config_sha256: str
    predictions_sha256: str
    manifest_sha256: str
    artifact_path: Path


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
        raise PredictionArtifactError(f"{name} contains a non-finite number")

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PredictionArtifactError(f"{name} is not strict UTF-8 JSON") from error
    if duplicates:
        raise PredictionArtifactError(f"{name} contains duplicate JSON keys")
    return value


def _canonical_object(payload: bytes, name: str) -> Mapping[str, Any]:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise PredictionArtifactError(f"{name} is not one LF-terminated object")
    value = _strict_json(payload[:-1], name)
    if not isinstance(value, MappingABC):
        raise PredictionArtifactError(f"{name} must be an object")
    if canonical_json(value).encode("utf-8") + b"\n" != payload:
        raise PredictionArtifactError(f"{name} is not canonical JSON")
    return value


def _record_ids(binding: _DatasetBinding) -> tuple[str, ...]:
    examples = binding.loader()
    result: list[str] = []
    for example in examples:
        record_id = _text(getattr(example, "record_id", None), "source record ID")
        result.append(record_id)
    if len(result) != binding.record_count:
        raise PredictionArtifactError("source record count differs from its binding")
    if len(set(result)) != len(result):
        raise PredictionArtifactError("source record IDs are duplicated")
    return tuple(result)


def _prediction_value(binding: _DatasetBinding, value: Any) -> Any:
    if binding.prediction_value_schema == "string":
        return _text(value, "prediction", allow_empty=True)
    values = tuple(_text(item, "prediction item") for item in _sequence(value, "prediction"))
    return list(values)


def _prediction_bytes(
    binding: _DatasetBinding,
    run_id: str,
    record_ids: Sequence[str],
    predictions: Mapping[str, Any],
) -> bytes:
    if not isinstance(predictions, MappingABC):
        raise PredictionArtifactError("predictions must be a mapping")
    if any(not isinstance(key, str) for key in predictions):
        raise PredictionArtifactError("prediction keys must be strings")
    missing = set(record_ids).difference(predictions)
    extra = set(predictions).difference(record_ids)
    if missing or extra:
        raise PredictionArtifactError(
            f"prediction key mismatch; missing={len(missing)}, extra={len(extra)}"
        )
    lines: list[bytes] = []
    total = 0
    for record_id in record_ids:
        value = {
            "schema_version": _RECORD_SCHEMA,
            "run_id": run_id,
            "dataset": binding.name,
            "record_id": record_id,
            "prediction": _prediction_value(binding, predictions[record_id]),
        }
        line = canonical_json(value).encode("utf-8") + b"\n"
        if len(line) > _PREDICTION_LINE_LIMIT:
            raise PredictionArtifactError("prediction line exceeds its byte limit")
        total += len(line)
        if total > _PREDICTIONS_LIMIT:
            raise PredictionArtifactError("predictions exceed their byte limit")
        lines.append(line)
    return b"".join(lines)


def _manifest(
    binding: _DatasetBinding,
    spec: RunSpec,
    config: bytes,
    predictions: bytes,
    record_count: int,
) -> Mapping[str, Any]:
    return {
        "schema_version": _MANIFEST_SCHEMA,
        "status": _STATUS,
        "run_id": spec.run_id,
        "dataset": {
            "name": binding.name,
            "split": binding.split,
            "revision": binding.revision,
            "source_sha256": binding.source_sha256,
            "record_count": record_count,
            "adapter_schema_version": binding.adapter_schema_version,
            "metric_contract_version": binding.metric_contract_version,
            "prediction_value_schema": binding.prediction_value_schema,
        },
        "method": {
            "name": spec.method_name,
            "model_id": spec.model_id,
            "model_revision": spec.model_revision,
        },
        "execution": {
            "git_commit": spec.execution_commit,
            "dirty": False,
            "seed": spec.seed,
            "started_at": spec.started_at,
            "completed_at": spec.completed_at,
        },
        "resources": {
            "gpu_ids": list(spec.gpu_ids),
            "cpu_threads": spec.cpu_threads,
            "memory_gib": spec.memory_gib,
            "dataloader_workers": spec.dataloader_workers,
        },
        "configuration": {
            "path": _CONFIG_NAME,
            "sha256": hashlib.sha256(config).hexdigest(),
            "byte_size": len(config),
        },
        "predictions": {
            "path": _PREDICTIONS_NAME,
            "sha256": hashlib.sha256(predictions).hexdigest(),
            "byte_size": len(predictions),
            "record_count": record_count,
            "record_schema_version": _RECORD_SCHEMA,
        },
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(os.fspath(path), flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise OSError("artifact write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        os.fspath(path),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_artifact_file(path: Path, limit: int, name: str) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise PredictionArtifactError(f"cannot open artifact {name}") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
        ):
            raise PredictionArtifactError(f"artifact {name} metadata is invalid")
        if before.st_size > limit:
            raise PredictionArtifactError(f"artifact {name} exceeds its byte limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1_048_576, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise PredictionArtifactError(f"artifact {name} exceeds its byte limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise PredictionArtifactError(f"artifact {name} changed while reading")
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _git_gate(expected_commit: str) -> None:
    environment = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }

    def run(arguments: Sequence[str]) -> str:
        result = subprocess.run(
            ["/usr/bin/git", "-c", "core.fsmonitor=false", *arguments],
            cwd=_PROJECT_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        if result.returncode != 0 or len(result.stdout) > 1_048_576:
            raise PredictionArtifactError("clean Git gate failed")
        try:
            return result.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise PredictionArtifactError("Git gate output is not UTF-8") from error

    if run(("rev-parse", "HEAD")) != expected_commit + "\n":
        raise PredictionArtifactError("execution commit differs from clean HEAD")
    if run(("status", "--porcelain", "--untracked-files=all")):
        raise PredictionArtifactError("formal prediction publication requires a clean tree")


def _prepare_root(root: Path) -> None:
    try:
        status = root.lstat()
    except FileNotFoundError:
        root.mkdir(mode=0o700)
        _fsync_directory(root.parent)
        status = root.lstat()
    if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
        raise PredictionArtifactError("artifact root must be a private directory")


def _publish(
    root: Path,
    binding: _DatasetBinding,
    spec: RunSpec,
    predictions: Mapping[str, Any],
    git_gate: Callable[[str], None],
) -> VerifiedPredictionArtifact:
    if spec.dataset != binding.name:
        raise PredictionArtifactError("run spec dataset differs from its binding")
    config = _config_bytes(spec.config)
    record_ids = _record_ids(binding)
    prediction_payload = _prediction_bytes(
        binding, spec.run_id, record_ids, predictions
    )
    manifest = _manifest(
        binding, spec, config, prediction_payload, len(record_ids)
    )
    manifest_payload = canonical_json(manifest).encode("utf-8") + b"\n"
    if len(manifest_payload) > _MANIFEST_LIMIT:
        raise PredictionArtifactError("manifest exceeds its byte limit")
    git_gate(spec.execution_commit)
    _prepare_root(root)
    target = root / spec.run_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as error:
        raise PredictionArtifactError("run artifact already exists") from error
    _write_exclusive(target / _CONFIG_NAME, config)
    _write_exclusive(target / _PREDICTIONS_NAME, prediction_payload)
    _fsync_directory(target)
    git_gate(spec.execution_commit)
    _write_exclusive(target / _MANIFEST_NAME, manifest_payload)
    _fsync_directory(target)
    _fsync_directory(root)
    return _verify(root, binding, spec.run_id)


def publish_predictions(
    spec: RunSpec, predictions: Mapping[str, Any]
) -> VerifiedPredictionArtifact:
    """Publish one complete prediction run to the fixed artifact root."""

    return _publish(
        _ARTIFACT_ROOT, _BINDINGS[spec.dataset], spec, predictions, _git_gate
    )


def _parse_manifest(
    value: Mapping[str, Any], binding: _DatasetBinding, config: Mapping[str, Any]
) -> RunSpec:
    value = _exact_mapping(
        value,
        {
            "schema_version", "status", "run_id", "dataset", "method",
            "execution", "resources", "configuration", "predictions",
        },
        "prediction manifest",
    )
    if value["schema_version"] != _MANIFEST_SCHEMA or value["status"] != _STATUS:
        raise PredictionArtifactError("prediction manifest fixed literals differ")
    dataset = _exact_mapping(
        value["dataset"],
        {
            "name", "split", "revision", "source_sha256", "record_count",
            "adapter_schema_version", "metric_contract_version",
            "prediction_value_schema",
        },
        "manifest dataset",
    )
    expected_dataset = {
        "name": binding.name,
        "split": binding.split,
        "revision": binding.revision,
        "source_sha256": binding.source_sha256,
        "record_count": binding.record_count,
        "adapter_schema_version": binding.adapter_schema_version,
        "metric_contract_version": binding.metric_contract_version,
        "prediction_value_schema": binding.prediction_value_schema,
    }
    if dict(dataset) != expected_dataset:
        raise PredictionArtifactError("manifest dataset binding differs")
    method = _exact_mapping(
        value["method"], {"name", "model_id", "model_revision"}, "manifest method"
    )
    execution = _exact_mapping(
        value["execution"],
        {"git_commit", "dirty", "seed", "started_at", "completed_at"},
        "manifest execution",
    )
    if execution["dirty"] is not False:
        raise PredictionArtifactError("manifest dirty flag must be false")
    resources = _exact_mapping(
        value["resources"],
        {"gpu_ids", "cpu_threads", "memory_gib", "dataloader_workers"},
        "manifest resources",
    )
    gpu_ids = tuple(_sequence(resources["gpu_ids"], "manifest GPU IDs"))
    return RunSpec(
        run_id=value["run_id"],
        dataset=dataset["name"],
        method_name=method["name"],
        model_id=method["model_id"],
        model_revision=method["model_revision"],
        execution_commit=execution["git_commit"],
        seed=execution["seed"],
        started_at=execution["started_at"],
        completed_at=execution["completed_at"],
        config=config,
        gpu_ids=gpu_ids,
        cpu_threads=resources["cpu_threads"],
        memory_gib=resources["memory_gib"],
        dataloader_workers=resources["dataloader_workers"],
    )


def _parse_prediction_records(
    payload: bytes,
    binding: _DatasetBinding,
    run_id: str,
    expected_ids: Sequence[str],
) -> tuple[PredictionRecord, ...]:
    if not payload or not payload.endswith(b"\n"):
        raise PredictionArtifactError("predictions must be non-empty LF JSONL")
    records: list[PredictionRecord] = []
    for line_number, raw in enumerate(payload.splitlines(keepends=True), start=1):
        if not raw.endswith(b"\n") or raw.endswith(b"\r\n"):
            raise PredictionArtifactError("prediction line is not LF-delimited")
        if len(raw) > _PREDICTION_LINE_LIMIT:
            raise PredictionArtifactError("prediction line exceeds its byte limit")
        value = _exact_mapping(
            _strict_json(raw[:-1], f"prediction line {line_number}"),
            {"schema_version", "run_id", "dataset", "record_id", "prediction"},
            "prediction record",
        )
        if canonical_json(value).encode("utf-8") + b"\n" != raw:
            raise PredictionArtifactError("prediction record is not canonical JSON")
        if value["schema_version"] != _RECORD_SCHEMA:
            raise PredictionArtifactError("prediction record schema differs")
        if value["run_id"] != run_id or value["dataset"] != binding.name:
            raise PredictionArtifactError("prediction record binding differs")
        prediction = _prediction_value(binding, value["prediction"])
        records.append(PredictionRecord(value["record_id"], prediction))
    if tuple(record.record_id for record in records) != tuple(expected_ids):
        raise PredictionArtifactError("prediction record order or coverage differs")
    return tuple(records)


def _verify(
    root: Path, binding: _DatasetBinding, run_id: str
) -> VerifiedPredictionArtifact:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise PredictionArtifactError("run ID syntax is invalid")
    target = root / run_id
    try:
        target_status = target.lstat()
    except OSError as error:
        raise PredictionArtifactError("run artifact directory is unavailable") from error
    if (
        not stat.S_ISDIR(target_status.st_mode)
        or stat.S_IMODE(target_status.st_mode) != 0o700
    ):
        raise PredictionArtifactError("run artifact directory metadata is invalid")
    try:
        names = {entry.name for entry in os.scandir(target)}
    except OSError as error:
        raise PredictionArtifactError("cannot scan run artifact directory") from error
    if names != _FINAL_NAMES:
        raise PredictionArtifactError("run artifact file set is incomplete or extra")
    config_payload = _read_artifact_file(target / _CONFIG_NAME, _CONFIG_LIMIT, _CONFIG_NAME)
    predictions_payload = _read_artifact_file(
        target / _PREDICTIONS_NAME, _PREDICTIONS_LIMIT, _PREDICTIONS_NAME
    )
    manifest_payload = _read_artifact_file(
        target / _MANIFEST_NAME, _MANIFEST_LIMIT, _MANIFEST_NAME
    )
    config = _canonical_object(config_payload, "configuration")
    manifest = _canonical_object(manifest_payload, "prediction manifest")
    manifest_shell = _exact_mapping(
        manifest,
        {
            "schema_version", "status", "run_id", "dataset", "method",
            "execution", "resources", "configuration", "predictions",
        },
        "prediction manifest",
    )
    configuration = manifest_shell["configuration"]
    prediction_facts = manifest_shell["predictions"]
    configuration = _exact_mapping(
        configuration, {"path", "sha256", "byte_size"}, "manifest configuration"
    )
    prediction_facts = _exact_mapping(
        prediction_facts,
        {"path", "sha256", "byte_size", "record_count", "record_schema_version"},
        "manifest predictions",
    )
    if configuration != {
        "path": _CONFIG_NAME,
        "sha256": hashlib.sha256(config_payload).hexdigest(),
        "byte_size": len(config_payload),
    }:
        raise PredictionArtifactError("configuration manifest facts differ")
    if prediction_facts != {
        "path": _PREDICTIONS_NAME,
        "sha256": hashlib.sha256(predictions_payload).hexdigest(),
        "byte_size": len(predictions_payload),
        "record_count": binding.record_count,
        "record_schema_version": _RECORD_SCHEMA,
    }:
        raise PredictionArtifactError("prediction manifest facts differ")
    spec = _parse_manifest(manifest_shell, binding, config)
    if spec.run_id != run_id:
        raise PredictionArtifactError("directory run ID differs from manifest")
    expected_ids = _record_ids(binding)
    records = _parse_prediction_records(
        predictions_payload, binding, run_id, expected_ids
    )
    return VerifiedPredictionArtifact(
        spec=spec,
        records=records,
        config_sha256=hashlib.sha256(config_payload).hexdigest(),
        predictions_sha256=hashlib.sha256(predictions_payload).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_path=target,
    )


def verify_predictions(run_id: str) -> VerifiedPredictionArtifact:
    """Offline-verify one fixed-root prediction artifact by its run ID."""

    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise PredictionArtifactError("run ID syntax is invalid")
    if "-torque-dev-" in run_id:
        binding = _BINDINGS["torque-dev"]
    elif "-timeqa-hard-" in run_id:
        binding = _BINDINGS["timeqa-hard"]
    else:
        raise PredictionArtifactError("run ID dataset is not frozen")
    return _verify(_ARTIFACT_ROOT, binding, run_id)
