"""Immutable, prediction-bound metric artifacts for transfer evaluation."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from .ids import canonical_json
from . import prediction_artifacts as prediction_contract
from .prediction_artifacts import VerifiedPredictionArtifact
from .transfer_eval import (
    evaluate_timeqa,
    evaluate_torque,
    load_timeqa_hard,
    load_torque_dev,
)


_METRICS_ROOT = Path("/data0/hk_data/kairos-zx/artifacts/derived-metrics")
_METRICS_SCHEMA = "transfer-metrics-v1"
_MANIFEST_SCHEMA = "metrics-artifact-manifest-v1"
_STATUS = "METRICS_COMPLETE"
_METRICS_NAME = "metrics.json"
_MANIFEST_NAME = "manifest.json"
_FINAL_NAMES = frozenset({_METRICS_NAME, _MANIFEST_NAME})
_FILE_LIMIT = 1_048_576
_HEX40 = re.compile(r"^[0-9a-f]{40}$")

_METRIC_KEYS = {
    "torque-dev": {
        "schema_version",
        "adapter_schema_version",
        "question_count",
        "cluster_count",
        "question_exact_match",
        "question_set_f1",
        "cluster_exact_consistency",
        "cluster_f1_80_consistency",
    },
    "timeqa-hard": {
        "schema_version",
        "adapter_schema_version",
        "total",
        "exact_match",
        "token_f1",
    },
}
_METRIC_SCHEMAS = {
    "torque-dev": "torque-set-metrics-v1",
    "timeqa-hard": "timeqa-official-string-metrics-v1",
}


class MetricsArtifactError(ValueError):
    """A derived metrics artifact invariant failed."""


@dataclass(frozen=True)
class VerifiedMetricsArtifact:
    run_id: str
    aggregation_commit: str
    completed_at: str
    metrics: Mapping[str, Any]
    generation_summary: Mapping[str, Any]
    prediction_manifest_sha256: str
    metrics_sha256: str
    manifest_sha256: str
    artifact_path: Path


def _dataset_components(
    dataset: str,
) -> tuple[Callable[[], Sequence[Any]], Callable[[Sequence[Any], Mapping[str, Any]], Mapping[str, Any]]]:
    if dataset == "torque-dev":
        return load_torque_dev, evaluate_torque
    if dataset == "timeqa-hard":
        return load_timeqa_hard, evaluate_timeqa
    raise MetricsArtifactError("prediction dataset has no frozen metric publisher")


def _validate_aggregation_identity(
    prediction: VerifiedPredictionArtifact,
    aggregation_commit: str,
    completed_at: str,
) -> None:
    if not isinstance(aggregation_commit, str) or not _HEX40.fullmatch(
        aggregation_commit
    ):
        raise MetricsArtifactError("aggregation commit must be 40 lowercase hex")
    aggregation_time = prediction_contract._parse_utc(
        completed_at, "metrics completed_at"
    )
    run_time = prediction_contract._parse_utc(
        prediction.spec.completed_at, "prediction completed_at"
    )
    if aggregation_time < run_time:
        raise MetricsArtifactError("metrics completed_at precedes prediction completion")


def _validated_metrics(dataset: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, MappingABC):
        raise MetricsArtifactError("evaluator result must be a mapping")
    expected_keys = _METRIC_KEYS.get(dataset)
    if expected_keys is None or set(value) != expected_keys:
        raise MetricsArtifactError("evaluator result keys differ from the frozen contract")
    if value.get("schema_version") != _METRIC_SCHEMAS[dataset]:
        raise MetricsArtifactError("evaluator metric schema differs from the frozen contract")
    try:
        canonical_json(value)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise MetricsArtifactError("evaluator result is not canonical-JSON compatible") from error
    return dict(value)


def _generation_summary(
    prediction: VerifiedPredictionArtifact,
) -> Mapping[str, Any]:
    if not prediction.evidence:
        raise MetricsArtifactError("prediction evidence must be non-empty")
    statuses = {"PARSED": 0, "PARSE_ERROR": 0, "NOT_APPLICABLE": 0}
    input_counts: list[int] = []
    generated_total = 0
    for item in prediction.evidence:
        if item.parse_status not in statuses:
            raise MetricsArtifactError("prediction evidence parse status is invalid")
        statuses[item.parse_status] += 1
        input_counts.append(item.input_token_count)
        generated_total += item.generated_token_count
    return {
        "record_count": len(prediction.evidence),
        "parse_status_counts": statuses,
        "input_token_count_min": min(input_counts),
        "input_token_count_max": max(input_counts),
        "generated_token_count_total": generated_total,
    }


def _metrics_value(
    prediction: VerifiedPredictionArtifact,
    aggregation_commit: str,
    completed_at: str,
    loader: Callable[[], Sequence[Any]],
    evaluator: Callable[[Sequence[Any], Mapping[str, Any]], Mapping[str, Any]],
) -> Mapping[str, Any]:
    _validate_aggregation_identity(prediction, aggregation_commit, completed_at)
    examples = loader()
    predictions = {record.record_id: record.prediction for record in prediction.records}
    metrics = _validated_metrics(
        prediction.spec.dataset, evaluator(examples, predictions)
    )
    return {
        "schema_version": _METRICS_SCHEMA,
        "status": _STATUS,
        "run_id": prediction.spec.run_id,
        "dataset": prediction.spec.dataset,
        "method": {
            "name": prediction.spec.method_name,
            "model_id": prediction.spec.model_id,
            "model_revision": prediction.spec.model_revision,
            "seed": prediction.spec.seed,
        },
        "prediction_artifact": {
            "execution_commit": prediction.spec.execution_commit,
            "config_sha256": prediction.config_sha256,
            "predictions_sha256": prediction.predictions_sha256,
            "generation_evidence_sha256": prediction.evidence_sha256,
            "manifest_sha256": prediction.manifest_sha256,
        },
        "aggregation": {
            "git_commit": aggregation_commit,
            "completed_at": completed_at,
        },
        "generation_summary": _generation_summary(prediction),
        "metrics": metrics,
    }


def _payload(value: Mapping[str, Any], name: str) -> bytes:
    try:
        payload = canonical_json(value).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise MetricsArtifactError(f"{name} is not canonical-JSON compatible") from error
    if len(payload) > _FILE_LIMIT:
        raise MetricsArtifactError(f"{name} exceeds its byte limit")
    return payload


def _prediction_identity(
    value: VerifiedPredictionArtifact,
) -> tuple[Any, ...]:
    return (
        value.spec,
        value.config_sha256,
        value.predictions_sha256,
        value.evidence_sha256,
        value.manifest_sha256,
    )


def _manifest_value(
    metrics_value: Mapping[str, Any], metrics_payload: bytes
) -> Mapping[str, Any]:
    prediction = metrics_value["prediction_artifact"]
    aggregation = metrics_value["aggregation"]
    return {
        "schema_version": _MANIFEST_SCHEMA,
        "status": _STATUS,
        "run_id": metrics_value["run_id"],
        "aggregation": aggregation,
        "prediction_manifest_sha256": prediction["manifest_sha256"],
        "metrics": {
            "path": _METRICS_NAME,
            "sha256": hashlib.sha256(metrics_payload).hexdigest(),
            "byte_size": len(metrics_payload),
        },
    }


def _require_private_directory(path: Path, name: str) -> None:
    try:
        status = path.lstat()
    except OSError as error:
        raise MetricsArtifactError(f"{name} is unavailable") from error
    if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
        raise MetricsArtifactError(f"{name} metadata is invalid")


def _publish(
    root: Path,
    run_id: str,
    aggregation_commit: str,
    completed_at: str,
    prediction_verifier: Callable[[str], VerifiedPredictionArtifact],
    loader: Callable[[], Sequence[Any]],
    evaluator: Callable[[Sequence[Any], Mapping[str, Any]], Mapping[str, Any]],
    git_gate: Callable[[str], None],
) -> VerifiedMetricsArtifact:
    first_prediction = prediction_verifier(run_id)
    if first_prediction.spec.run_id != run_id:
        raise MetricsArtifactError("prediction verifier returned a different run")
    metrics_value = _metrics_value(
        first_prediction, aggregation_commit, completed_at, loader, evaluator
    )
    metrics_payload = _payload(metrics_value, "metrics")
    manifest_value = _manifest_value(metrics_value, metrics_payload)
    manifest_payload = _payload(manifest_value, "metrics manifest")

    git_gate(aggregation_commit)
    prediction_contract._prepare_root(root)
    target = root / run_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as error:
        raise MetricsArtifactError("metrics artifact already exists") from error
    prediction_contract._write_exclusive(target / _METRICS_NAME, metrics_payload)
    prediction_contract._fsync_directory(target)

    second_prediction = prediction_verifier(run_id)
    second_value = _metrics_value(
        second_prediction, aggregation_commit, completed_at, loader, evaluator
    )
    if (
        _prediction_identity(second_prediction) != _prediction_identity(first_prediction)
        or second_value != metrics_value
    ):
        raise MetricsArtifactError("prediction or aggregation changed before publication")
    git_gate(aggregation_commit)
    prediction_contract._write_exclusive(target / _MANIFEST_NAME, manifest_payload)
    prediction_contract._fsync_directory(target)
    prediction_contract._fsync_directory(root)
    return _verify(root, run_id, prediction_verifier, loader, evaluator)


def publish_metrics(
    run_id: str, aggregation_commit: str, completed_at: str
) -> VerifiedMetricsArtifact:
    """Aggregate and immutably publish metrics for one verified prediction run."""

    prediction = prediction_contract.verify_predictions(run_id)
    loader, evaluator = _dataset_components(prediction.spec.dataset)
    return _publish(
        _METRICS_ROOT,
        run_id,
        aggregation_commit,
        completed_at,
        prediction_contract.verify_predictions,
        loader,
        evaluator,
        prediction_contract._git_gate,
    )


def _verify(
    root: Path,
    run_id: str,
    prediction_verifier: Callable[[str], VerifiedPredictionArtifact],
    loader: Callable[[], Sequence[Any]],
    evaluator: Callable[[Sequence[Any], Mapping[str, Any]], Mapping[str, Any]],
) -> VerifiedMetricsArtifact:
    prediction = prediction_verifier(run_id)
    if prediction.spec.run_id != run_id:
        raise MetricsArtifactError("prediction verifier returned a different run")
    _require_private_directory(root, "metrics root")
    target = root / run_id
    _require_private_directory(target, "metrics artifact directory")
    try:
        names = {entry.name for entry in os.scandir(target)}
    except OSError as error:
        raise MetricsArtifactError("cannot scan metrics artifact directory") from error
    if names != _FINAL_NAMES:
        raise MetricsArtifactError("metrics artifact file set is incomplete or extra")

    metrics_payload = prediction_contract._read_artifact_file(
        target / _METRICS_NAME, _FILE_LIMIT, _METRICS_NAME
    )
    manifest_payload = prediction_contract._read_artifact_file(
        target / _MANIFEST_NAME, _FILE_LIMIT, _MANIFEST_NAME
    )
    metrics_value = prediction_contract._canonical_object(
        metrics_payload, "metrics"
    )
    manifest = prediction_contract._canonical_object(
        manifest_payload, "metrics manifest"
    )
    metrics_value = prediction_contract._exact_mapping(
        metrics_value,
        {
            "schema_version", "status", "run_id", "dataset", "method",
            "prediction_artifact", "aggregation", "generation_summary", "metrics",
        },
        "metrics",
    )
    manifest = prediction_contract._exact_mapping(
        manifest,
        {
            "schema_version", "status", "run_id", "aggregation",
            "prediction_manifest_sha256", "metrics",
        },
        "metrics manifest",
    )
    if (
        metrics_value["schema_version"] != _METRICS_SCHEMA
        or metrics_value["status"] != _STATUS
        or metrics_value["run_id"] != run_id
        or metrics_value["dataset"] != prediction.spec.dataset
    ):
        raise MetricsArtifactError("metrics fixed bindings differ")
    if (
        manifest["schema_version"] != _MANIFEST_SCHEMA
        or manifest["status"] != _STATUS
        or manifest["run_id"] != run_id
    ):
        raise MetricsArtifactError("metrics manifest fixed bindings differ")
    aggregation = prediction_contract._exact_mapping(
        metrics_value["aggregation"],
        {"git_commit", "completed_at"},
        "metrics aggregation",
    )
    manifest_aggregation = prediction_contract._exact_mapping(
        manifest["aggregation"],
        {"git_commit", "completed_at"},
        "manifest aggregation",
    )
    if dict(manifest_aggregation) != dict(aggregation):
        raise MetricsArtifactError("manifest aggregation binding differs")
    expected_value = _metrics_value(
        prediction,
        aggregation["git_commit"],
        aggregation["completed_at"],
        loader,
        evaluator,
    )
    if dict(metrics_value) != expected_value:
        raise MetricsArtifactError("metrics differ from independent recomputation")
    expected_manifest = _manifest_value(expected_value, metrics_payload)
    if dict(manifest) != expected_manifest:
        raise MetricsArtifactError("metrics manifest facts differ")
    return VerifiedMetricsArtifact(
        run_id=run_id,
        aggregation_commit=aggregation["git_commit"],
        completed_at=aggregation["completed_at"],
        metrics=metrics_value["metrics"],
        generation_summary=metrics_value["generation_summary"],
        prediction_manifest_sha256=prediction.manifest_sha256,
        metrics_sha256=hashlib.sha256(metrics_payload).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_path=target,
    )


def verify_metrics(run_id: str) -> VerifiedMetricsArtifact:
    """Offline-verify predictions, source aggregation and one metrics artifact."""

    prediction = prediction_contract.verify_predictions(run_id)
    loader, evaluator = _dataset_components(prediction.spec.dataset)
    return _verify(
        _METRICS_ROOT,
        run_id,
        prediction_contract.verify_predictions,
        loader,
        evaluator,
    )
