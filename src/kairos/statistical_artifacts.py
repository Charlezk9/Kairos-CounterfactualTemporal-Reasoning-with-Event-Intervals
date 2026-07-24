"""Immutable paired-bootstrap artifacts for transfer baseline contrasts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from .ids import canonical_json
from . import metrics_artifacts as metrics_contract
from .metrics_artifacts import VerifiedMetricsArtifact
from . import prediction_artifacts as prediction_contract
from .prediction_artifacts import VerifiedPredictionArtifact
from .transfer_eval import (
    TimeQaExample,
    TorqueExample,
    evaluate_timeqa,
    evaluate_torque,
    load_timeqa_hard,
    load_torque_dev,
    normalize_torque_span,
    timeqa_exact,
    timeqa_f1,
)


_STATISTICS_ROOT = Path(
    "/data0/hk_data/kairos-zx/artifacts/derived-statistics"
)
_STATISTICS_SCHEMA = "paired-bootstrap-comparison-v1"
_MANIFEST_SCHEMA = "statistics-artifact-manifest-v1"
_STATUS = "STATISTICS_COMPLETE"
_STATISTICS_NAME = "statistics.json"
_MANIFEST_NAME = "manifest.json"
_FINAL_NAMES = frozenset({_STATISTICS_NAME, _MANIFEST_NAME})
_FILE_LIMIT = 2 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_COMPARISON_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,158}[a-z0-9]$")
_RESAMPLES = 10_000
_CONFIDENCE_LEVEL = 0.95
_MASK64 = (1 << 64) - 1

_METRIC_KEYS = {
    "torque-dev": (
        "question_exact_match",
        "question_set_f1",
        "cluster_exact_consistency",
        "cluster_f1_80_consistency",
    ),
    "timeqa-hard": ("exact_match", "token_f1"),
}
_BOOTSTRAP_UNITS = {
    "torque-dev": "passage_id-and-cluster_id",
    "timeqa-hard": "record",
}
_RULE_GRAPH_METHOD = "rule-graph"
_RULE_GRAPH_MODEL_ID = "deterministic-rule-graph"
_RULE_GRAPH_MODEL_REVISION = "explicit-before-after-constraint-v1"
_RULE_GRAPH_CONFIG_SCHEMA = "torque-rule-graph-config-v1"


class StatisticalArtifactError(ValueError):
    """A paired statistical artifact invariant failed."""


@dataclass(frozen=True)
class VerifiedStatisticalArtifact:
    comparison_id: str
    dataset: str
    reference_run_id: str
    candidate_run_id: str
    aggregation_commit: str
    completed_at: str
    bootstrap_seed: int
    resamples: int
    results: Mapping[str, Any]
    statistics_sha256: str
    manifest_sha256: str
    artifact_path: Path


@dataclass(frozen=True)
class _RunInput:
    prediction: VerifiedPredictionArtifact
    metrics: VerifiedMetricsArtifact


class _SplitMix64:
    """Small explicitly specified PRNG used only for bootstrap indices."""

    def __init__(self, seed: int) -> None:
        self.state = seed & _MASK64

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & _MASK64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
        return (value ^ (value >> 31)) & _MASK64

    def randbelow(self, stop: int) -> int:
        if isinstance(stop, bool) or not isinstance(stop, int) or stop <= 0:
            raise StatisticalArtifactError("bootstrap sampling bound is invalid")
        limit = (1 << 64) - ((1 << 64) % stop)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % stop


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatisticalArtifactError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise StatisticalArtifactError(f"{name} is outside its allowed range")
    return value


def _comparison_id_text(value: Any) -> str:
    if not isinstance(value, str) or not _COMPARISON_ID.fullmatch(value):
        raise StatisticalArtifactError("comparison ID is invalid")
    return value


def _dataset_loader(dataset: str) -> Callable[[], Sequence[Any]]:
    if dataset == "torque-dev":
        return load_torque_dev
    if dataset == "timeqa-hard":
        return load_timeqa_hard
    raise StatisticalArtifactError("dataset has no frozen bootstrap contract")


def _load_input(
    run_id: str,
    prediction_verifier: Callable[[str], VerifiedPredictionArtifact],
    metrics_verifier: Callable[[str], VerifiedMetricsArtifact],
) -> _RunInput:
    prediction = prediction_verifier(run_id)
    metrics = metrics_verifier(run_id)
    if prediction.spec.run_id != run_id or metrics.run_id != run_id:
        raise StatisticalArtifactError("input verifier returned a different run")
    if metrics.prediction_manifest_sha256 != prediction.manifest_sha256:
        raise StatisticalArtifactError("metrics-to-prediction binding differs")
    return _RunInput(prediction=prediction, metrics=metrics)


def _input_identity(value: _RunInput) -> tuple[Any, ...]:
    return (
        value.prediction.spec,
        value.prediction.config_sha256,
        value.prediction.predictions_sha256,
        value.prediction.evidence_sha256,
        value.prediction.manifest_sha256,
        value.metrics.aggregation_commit,
        value.metrics.completed_at,
        value.metrics.metrics_sha256,
        value.metrics.manifest_sha256,
    )


def _validate_pair(reference: _RunInput, candidate: _RunInput) -> str:
    if reference.prediction.spec.run_id == candidate.prediction.spec.run_id:
        raise StatisticalArtifactError("reference and candidate runs must differ")
    dataset = reference.prediction.spec.dataset
    if candidate.prediction.spec.dataset != dataset or dataset not in _METRIC_KEYS:
        raise StatisticalArtifactError("paired runs must use one supported dataset")
    if reference.prediction.spec.seed != candidate.prediction.spec.seed:
        raise StatisticalArtifactError("paired runs must use the same model seed")
    same_model_revision = (
        reference.prediction.spec.model_id == candidate.prediction.spec.model_id
        and reference.prediction.spec.model_revision
        == candidate.prediction.spec.model_revision
    )
    if not same_model_revision and not _is_bound_rule_graph_pair(reference, candidate):
        raise StatisticalArtifactError("paired runs must use the same model revision")
    return dataset


def _is_bound_rule_graph_pair(
    reference: _RunInput, candidate: _RunInput
) -> bool:
    """Accept only D-033's Rule-Graph-to-its-Direct-upstream contrast."""

    reference_spec = reference.prediction.spec
    candidate_spec = candidate.prediction.spec
    if (
        reference_spec.method_name != "direct"
        or candidate_spec.method_name != _RULE_GRAPH_METHOD
        or candidate_spec.model_id != _RULE_GRAPH_MODEL_ID
        or candidate_spec.model_revision != _RULE_GRAPH_MODEL_REVISION
    ):
        return False
    config = candidate_spec.config
    if not isinstance(config, MappingABC) or any(
        (
            config.get("schema_version") != _RULE_GRAPH_CONFIG_SCHEMA,
            config.get("dataset") != "torque-dev",
            config.get("method") != _RULE_GRAPH_METHOD,
            config.get("model_id") != _RULE_GRAPH_MODEL_ID,
            config.get("model_revision") != _RULE_GRAPH_MODEL_REVISION,
            config.get("seed") != candidate_spec.seed,
            config.get("generation") != "none",
            config.get("gold_access") is not False,
        )
    ):
        return False
    upstream = config.get("upstream")
    if not isinstance(upstream, MappingABC):
        return False
    direct = upstream.get("direct")
    return bool(
        isinstance(direct, MappingABC)
        and direct.get("run_id") == reference_spec.run_id
        and direct.get("manifest_sha256") == reference.prediction.manifest_sha256
    )


def _make_comparison_id(
    reference: _RunInput,
    candidate: _RunInput,
    bootstrap_seed: int,
    resamples: int,
) -> str:
    dataset = _validate_pair(reference, candidate)
    identity = {
        "schema_version": _STATISTICS_SCHEMA,
        "dataset": dataset,
        "reference_run_id": reference.prediction.spec.run_id,
        "candidate_run_id": candidate.prediction.spec.run_id,
        "bootstrap_seed": bootstrap_seed,
        "resamples": resamples,
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:12]
    value = (
        f"paired-{dataset}-{candidate.prediction.spec.method_name}-vs-"
        f"{reference.prediction.spec.method_name}-{digest}"
    )
    return _comparison_id_text(value)


def _predictions(value: VerifiedPredictionArtifact) -> Mapping[str, Any]:
    result = {item.record_id: item.prediction for item in value.records}
    if len(result) != len(value.records):
        raise StatisticalArtifactError("prediction records contain duplicate IDs")
    return result


def _validate_source_order(
    examples: Sequence[Any], reference: _RunInput, candidate: _RunInput
) -> None:
    expected = tuple(example.record_id for example in examples)
    reference_ids = tuple(item.record_id for item in reference.prediction.records)
    candidate_ids = tuple(item.record_id for item in candidate.prediction.records)
    if not expected or reference_ids != expected or candidate_ids != expected:
        raise StatisticalArtifactError("paired prediction source order differs")


def _torque_scores(example: TorqueExample, prediction: Any) -> tuple[float, float]:
    if not isinstance(prediction, list) or any(
        not isinstance(item, str) or not item.strip() for item in prediction
    ):
        raise StatisticalArtifactError("TORQUE paired prediction is invalid")
    predicted = {normalize_torque_span(item) for item in prediction}
    if "" in predicted:
        raise StatisticalArtifactError("TORQUE paired prediction contains an empty span")
    gold = {normalize_torque_span(item) for item in example.gold_spans}
    exact = float(predicted == gold)
    if not predicted and not gold:
        f1 = 1.0
    elif not predicted or not gold:
        f1 = 0.0
    else:
        f1 = 2.0 * len(predicted.intersection(gold)) / (len(predicted) + len(gold))
    return exact, f1


def _torque_units(
    examples: Sequence[Any],
    reference_predictions: Mapping[str, Any],
    candidate_predictions: Mapping[str, Any],
) -> tuple[tuple[float, float, int, float, float], ...]:
    groups: dict[tuple[str, str], list[tuple[float, float, float, float]]] = defaultdict(list)
    for example in examples:
        if not isinstance(example, TorqueExample):
            raise StatisticalArtifactError("TORQUE source contains an invalid item")
        reference = _torque_scores(example, reference_predictions[example.record_id])
        candidate = _torque_scores(example, candidate_predictions[example.record_id])
        groups[(example.passage_id, example.cluster_id)].append(
            (reference[0], reference[1], candidate[0], candidate[1])
        )
    if not groups:
        raise StatisticalArtifactError("TORQUE bootstrap groups are empty")
    units = []
    for values in groups.values():
        units.append(
            (
                sum(item[2] - item[0] for item in values),
                sum(item[3] - item[1] for item in values),
                len(values),
                float(all(item[2] == 1.0 for item in values))
                - float(all(item[0] == 1.0 for item in values)),
                float(all(item[3] >= 0.8 for item in values))
                - float(all(item[1] >= 0.8 for item in values)),
            )
        )
    return tuple(units)


def _timeqa_units(
    examples: Sequence[Any],
    reference_predictions: Mapping[str, Any],
    candidate_predictions: Mapping[str, Any],
) -> tuple[tuple[float, float], ...]:
    units = []
    for example in examples:
        if not isinstance(example, TimeQaExample):
            raise StatisticalArtifactError("TimeQA source contains an invalid item")
        reference = reference_predictions[example.record_id]
        candidate = candidate_predictions[example.record_id]
        if not isinstance(reference, str) or not isinstance(candidate, str):
            raise StatisticalArtifactError("TimeQA paired prediction is invalid")
        reference_exact = max(timeqa_exact(target, reference) for target in example.targets)
        candidate_exact = max(timeqa_exact(target, candidate) for target in example.targets)
        reference_f1 = max(timeqa_f1(target, reference) for target in example.targets)
        candidate_f1 = max(timeqa_f1(target, candidate) for target in example.targets)
        units.append((candidate_exact - reference_exact, candidate_f1 - reference_f1))
    if not units:
        raise StatisticalArtifactError("TimeQA bootstrap records are empty")
    return tuple(units)


def _bootstrap_differences(
    dataset: str,
    examples: Sequence[Any],
    reference_predictions: Mapping[str, Any],
    candidate_predictions: Mapping[str, Any],
    seed: int,
    resamples: int,
) -> tuple[tuple[float, ...], ...]:
    generator = _SplitMix64(seed)
    metric_count = len(_METRIC_KEYS[dataset])
    distributions: list[list[float]] = [[] for unused in range(metric_count)]
    if dataset == "torque-dev":
        units = _torque_units(examples, reference_predictions, candidate_predictions)
        group_count = len(units)
        for unused in range(resamples):
            exact_sum = f1_sum = cluster_exact_sum = cluster_f1_sum = 0.0
            question_count = 0
            for unused_group in range(group_count):
                unit = units[generator.randbelow(group_count)]
                exact_sum += unit[0]
                f1_sum += unit[1]
                question_count += unit[2]
                cluster_exact_sum += unit[3]
                cluster_f1_sum += unit[4]
            distributions[0].append(100.0 * exact_sum / question_count)
            distributions[1].append(100.0 * f1_sum / question_count)
            distributions[2].append(100.0 * cluster_exact_sum / group_count)
            distributions[3].append(100.0 * cluster_f1_sum / group_count)
    elif dataset == "timeqa-hard":
        units = _timeqa_units(examples, reference_predictions, candidate_predictions)
        record_count = len(units)
        for unused in range(resamples):
            exact_sum = f1_sum = 0.0
            for unused_record in range(record_count):
                unit = units[generator.randbelow(record_count)]
                exact_sum += unit[0]
                f1_sum += unit[1]
            distributions[0].append(100.0 * exact_sum / record_count)
            distributions[1].append(100.0 * f1_sum / record_count)
    else:
        raise StatisticalArtifactError("dataset has no bootstrap implementation")
    return tuple(tuple(values) for values in distributions)


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise StatisticalArtifactError("percentile input is invalid")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap_p_value(values: Sequence[float]) -> float:
    nonpositive = sum(value <= 0.0 for value in values)
    nonnegative = sum(value >= 0.0 for value in values)
    denominator = len(values) + 1
    return min(
        1.0,
        2.0 * min((nonpositive + 1) / denominator, (nonnegative + 1) / denominator),
    )


def _holm_adjust(raw: Mapping[str, float]) -> Mapping[str, float]:
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * value))
        adjusted[name] = running
    return adjusted


def _validate_metric_replay(
    dataset: str,
    examples: Sequence[Any],
    value: _RunInput,
    predictions: Mapping[str, Any],
) -> None:
    if dataset == "torque-dev":
        replay = evaluate_torque(examples, predictions)
    else:
        replay = evaluate_timeqa(examples, predictions)
    if dict(value.metrics.metrics) != dict(replay):
        raise StatisticalArtifactError("input metrics differ from source replay")


def _method_value(value: _RunInput) -> Mapping[str, Any]:
    prediction = value.prediction
    metrics = value.metrics
    return {
        "run_id": prediction.spec.run_id,
        "name": prediction.spec.method_name,
        "model_id": prediction.spec.model_id,
        "model_revision": prediction.spec.model_revision,
        "seed": prediction.spec.seed,
        "prediction_artifact": {
            "config_sha256": prediction.config_sha256,
            "predictions_sha256": prediction.predictions_sha256,
            "generation_evidence_sha256": prediction.evidence_sha256,
            "manifest_sha256": prediction.manifest_sha256,
        },
        "metrics_artifact": {
            "aggregation_commit": metrics.aggregation_commit,
            "completed_at": metrics.completed_at,
            "metrics_sha256": metrics.metrics_sha256,
            "manifest_sha256": metrics.manifest_sha256,
        },
    }


def _statistics_value(
    reference: _RunInput,
    candidate: _RunInput,
    bootstrap_seed: int,
    resamples: int,
    aggregation_commit: str,
    completed_at: str,
    loader: Callable[[], Sequence[Any]],
) -> Mapping[str, Any]:
    dataset = _validate_pair(reference, candidate)
    _integer(bootstrap_seed, "bootstrap seed", 0, (1 << 63) - 1)
    if resamples != _RESAMPLES:
        raise StatisticalArtifactError("formal bootstrap requires exactly 10000 resamples")
    if not isinstance(aggregation_commit, str) or not _HEX40.fullmatch(aggregation_commit):
        raise StatisticalArtifactError("aggregation commit must be 40 lowercase hex")
    aggregation_time = prediction_contract._parse_utc(
        completed_at, "statistics completed_at"
    )
    for value in (reference.metrics.completed_at, candidate.metrics.completed_at):
        if aggregation_time < prediction_contract._parse_utc(
            value, "input metrics completed_at"
        ):
            raise StatisticalArtifactError("statistics completed_at precedes input metrics")

    examples = loader()
    _validate_source_order(examples, reference, candidate)
    reference_predictions = _predictions(reference.prediction)
    candidate_predictions = _predictions(candidate.prediction)
    _validate_metric_replay(dataset, examples, reference, reference_predictions)
    _validate_metric_replay(dataset, examples, candidate, candidate_predictions)
    distributions = _bootstrap_differences(
        dataset,
        examples,
        reference_predictions,
        candidate_predictions,
        bootstrap_seed,
        resamples,
    )
    raw_p = {
        name: _bootstrap_p_value(distribution)
        for name, distribution in zip(_METRIC_KEYS[dataset], distributions)
    }
    adjusted = _holm_adjust(raw_p)
    results = {}
    for name, distribution in zip(_METRIC_KEYS[dataset], distributions):
        reference_score = reference.metrics.metrics[name]
        candidate_score = candidate.metrics.metrics[name]
        if isinstance(reference_score, bool) or not isinstance(reference_score, (int, float)):
            raise StatisticalArtifactError("reference metric is not numeric")
        if isinstance(candidate_score, bool) or not isinstance(candidate_score, (int, float)):
            raise StatisticalArtifactError("candidate metric is not numeric")
        results[name] = {
            "reference": reference_score,
            "candidate": candidate_score,
            "difference_candidate_minus_reference": candidate_score - reference_score,
            "confidence_interval_95": {
                "lower": _percentile(distribution, 0.025),
                "upper": _percentile(distribution, 0.975),
            },
            "p_value_raw": raw_p[name],
            "p_value_holm": adjusted[name],
        }
    comparison_id = _make_comparison_id(
        reference, candidate, bootstrap_seed, resamples
    )
    return {
        "schema_version": _STATISTICS_SCHEMA,
        "status": _STATUS,
        "comparison_id": comparison_id,
        "dataset": dataset,
        "contrast": {
            "direction": "candidate-minus-reference",
            "reference_run_id": reference.prediction.spec.run_id,
            "candidate_run_id": candidate.prediction.spec.run_id,
        },
        "methods": {
            "reference": _method_value(reference),
            "candidate": _method_value(candidate),
        },
        "bootstrap": {
            "schema_version": "paired-bootstrap-splitmix64-v1",
            "seed": bootstrap_seed,
            "resamples": resamples,
            "unit": _BOOTSTRAP_UNITS[dataset],
            "confidence_level": _CONFIDENCE_LEVEL,
            "interval": "percentile-linear-interpolation",
            "p_value": "two-sided-bootstrap-sign-add-one",
        },
        "multiplicity": {
            "method": "holm",
            "family": "all-reported-metrics-within-dataset-comparison",
            "hypothesis_count": len(_METRIC_KEYS[dataset]),
        },
        "aggregation": {
            "git_commit": aggregation_commit,
            "completed_at": completed_at,
        },
        "results": results,
    }


def _payload(value: Mapping[str, Any], name: str) -> bytes:
    try:
        payload = canonical_json(value).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise StatisticalArtifactError(f"{name} is not canonical-JSON compatible") from error
    if len(payload) > _FILE_LIMIT:
        raise StatisticalArtifactError(f"{name} exceeds its byte limit")
    return payload


def _manifest_value(
    statistics: Mapping[str, Any], statistics_payload: bytes
) -> Mapping[str, Any]:
    methods = statistics["methods"]
    return {
        "schema_version": _MANIFEST_SCHEMA,
        "status": _STATUS,
        "comparison_id": statistics["comparison_id"],
        "aggregation": statistics["aggregation"],
        "input_manifests": {
            "reference_prediction": methods["reference"]["prediction_artifact"]["manifest_sha256"],
            "reference_metrics": methods["reference"]["metrics_artifact"]["manifest_sha256"],
            "candidate_prediction": methods["candidate"]["prediction_artifact"]["manifest_sha256"],
            "candidate_metrics": methods["candidate"]["metrics_artifact"]["manifest_sha256"],
        },
        "statistics": {
            "path": _STATISTICS_NAME,
            "sha256": hashlib.sha256(statistics_payload).hexdigest(),
            "byte_size": len(statistics_payload),
        },
    }


def _require_private_directory(path: Path, name: str) -> None:
    try:
        status = path.lstat()
    except OSError as error:
        raise StatisticalArtifactError(f"{name} is unavailable") from error
    if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
        raise StatisticalArtifactError(f"{name} metadata is invalid")


def _publish(
    root: Path,
    reference_run_id: str,
    candidate_run_id: str,
    bootstrap_seed: int,
    resamples: int,
    aggregation_commit: str,
    completed_at: str,
    prediction_verifier: Callable[[str], VerifiedPredictionArtifact],
    metrics_verifier: Callable[[str], VerifiedMetricsArtifact],
    loader: Callable[[], Sequence[Any]],
    git_gate: Callable[[str], None],
) -> VerifiedStatisticalArtifact:
    first_reference = _load_input(reference_run_id, prediction_verifier, metrics_verifier)
    first_candidate = _load_input(candidate_run_id, prediction_verifier, metrics_verifier)
    statistics = _statistics_value(
        first_reference,
        first_candidate,
        bootstrap_seed,
        resamples,
        aggregation_commit,
        completed_at,
        loader,
    )
    statistics_payload = _payload(statistics, "statistics")
    manifest = _manifest_value(statistics, statistics_payload)
    manifest_payload = _payload(manifest, "statistics manifest")

    git_gate(aggregation_commit)
    prediction_contract._prepare_root(root)
    target = root / statistics["comparison_id"]
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as error:
        raise StatisticalArtifactError("statistics artifact already exists") from error
    prediction_contract._write_exclusive(target / _STATISTICS_NAME, statistics_payload)
    prediction_contract._fsync_directory(target)

    second_reference = _load_input(reference_run_id, prediction_verifier, metrics_verifier)
    second_candidate = _load_input(candidate_run_id, prediction_verifier, metrics_verifier)
    second_value = _statistics_value(
        second_reference,
        second_candidate,
        bootstrap_seed,
        resamples,
        aggregation_commit,
        completed_at,
        loader,
    )
    if (
        _input_identity(first_reference) != _input_identity(second_reference)
        or _input_identity(first_candidate) != _input_identity(second_candidate)
        or second_value != statistics
    ):
        raise StatisticalArtifactError("inputs or statistics changed before publication")
    git_gate(aggregation_commit)
    prediction_contract._write_exclusive(target / _MANIFEST_NAME, manifest_payload)
    prediction_contract._fsync_directory(target)
    prediction_contract._fsync_directory(root)
    return _verify(
        root,
        statistics["comparison_id"],
        prediction_verifier,
        metrics_verifier,
        loader,
    )


def publish_statistics(
    reference_run_id: str,
    candidate_run_id: str,
    bootstrap_seed: int,
    aggregation_commit: str,
    completed_at: str,
) -> VerifiedStatisticalArtifact:
    """Publish one fixed 10,000-resample paired baseline contrast."""

    reference = prediction_contract.verify_predictions(reference_run_id)
    candidate = prediction_contract.verify_predictions(candidate_run_id)
    if reference.spec.dataset != candidate.spec.dataset:
        raise StatisticalArtifactError("paired runs use different datasets")
    return _publish(
        _STATISTICS_ROOT,
        reference_run_id,
        candidate_run_id,
        bootstrap_seed,
        _RESAMPLES,
        aggregation_commit,
        completed_at,
        prediction_contract.verify_predictions,
        metrics_contract.verify_metrics,
        _dataset_loader(reference.spec.dataset),
        prediction_contract._git_gate,
    )


def _verify(
    root: Path,
    comparison_id: str,
    prediction_verifier: Callable[[str], VerifiedPredictionArtifact],
    metrics_verifier: Callable[[str], VerifiedMetricsArtifact],
    loader: Callable[[], Sequence[Any]] | None = None,
) -> VerifiedStatisticalArtifact:
    comparison_id = _comparison_id_text(comparison_id)
    _require_private_directory(root, "statistics root")
    target = root / comparison_id
    _require_private_directory(target, "statistics artifact directory")
    try:
        names = {entry.name for entry in os.scandir(target)}
    except OSError as error:
        raise StatisticalArtifactError("cannot scan statistics artifact directory") from error
    if names != _FINAL_NAMES:
        raise StatisticalArtifactError("statistics artifact file set is incomplete or extra")
    statistics_payload = prediction_contract._read_artifact_file(
        target / _STATISTICS_NAME, _FILE_LIMIT, _STATISTICS_NAME
    )
    manifest_payload = prediction_contract._read_artifact_file(
        target / _MANIFEST_NAME, _FILE_LIMIT, _MANIFEST_NAME
    )
    statistics = prediction_contract._canonical_object(statistics_payload, "statistics")
    manifest = prediction_contract._canonical_object(manifest_payload, "statistics manifest")
    statistics = prediction_contract._exact_mapping(
        statistics,
        {
            "schema_version", "status", "comparison_id", "dataset", "contrast",
            "methods", "bootstrap", "multiplicity", "aggregation", "results",
        },
        "statistics",
    )
    manifest = prediction_contract._exact_mapping(
        manifest,
        {
            "schema_version", "status", "comparison_id", "aggregation",
            "input_manifests", "statistics",
        },
        "statistics manifest",
    )
    if (
        statistics["schema_version"] != _STATISTICS_SCHEMA
        or statistics["status"] != _STATUS
        or statistics["comparison_id"] != comparison_id
    ):
        raise StatisticalArtifactError("statistics fixed bindings differ")
    if (
        manifest["schema_version"] != _MANIFEST_SCHEMA
        or manifest["status"] != _STATUS
        or manifest["comparison_id"] != comparison_id
    ):
        raise StatisticalArtifactError("statistics manifest fixed bindings differ")
    contrast = prediction_contract._exact_mapping(
        statistics["contrast"],
        {"direction", "reference_run_id", "candidate_run_id"},
        "statistics contrast",
    )
    bootstrap = prediction_contract._exact_mapping(
        statistics["bootstrap"],
        {
            "schema_version", "seed", "resamples", "unit", "confidence_level",
            "interval", "p_value",
        },
        "statistics bootstrap",
    )
    aggregation = prediction_contract._exact_mapping(
        statistics["aggregation"], {"git_commit", "completed_at"}, "statistics aggregation"
    )
    reference = _load_input(contrast["reference_run_id"], prediction_verifier, metrics_verifier)
    candidate = _load_input(contrast["candidate_run_id"], prediction_verifier, metrics_verifier)
    dataset = _validate_pair(reference, candidate)
    if statistics["dataset"] != dataset:
        raise StatisticalArtifactError("statistics dataset binding differs")
    expected = _statistics_value(
        reference,
        candidate,
        bootstrap["seed"],
        bootstrap["resamples"],
        aggregation["git_commit"],
        aggregation["completed_at"],
        loader or _dataset_loader(dataset),
    )
    if dict(statistics) != expected:
        raise StatisticalArtifactError("statistics differ from independent recomputation")
    expected_manifest = _manifest_value(expected, statistics_payload)
    if dict(manifest) != expected_manifest:
        raise StatisticalArtifactError("statistics manifest facts differ")
    return VerifiedStatisticalArtifact(
        comparison_id=comparison_id,
        dataset=dataset,
        reference_run_id=contrast["reference_run_id"],
        candidate_run_id=contrast["candidate_run_id"],
        aggregation_commit=aggregation["git_commit"],
        completed_at=aggregation["completed_at"],
        bootstrap_seed=bootstrap["seed"],
        resamples=bootstrap["resamples"],
        results=statistics["results"],
        statistics_sha256=hashlib.sha256(statistics_payload).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_path=target,
    )


def verify_statistics(comparison_id: str) -> VerifiedStatisticalArtifact:
    """Offline-verify inputs and independently replay one statistical artifact."""

    return _verify(
        _STATISTICS_ROOT,
        comparison_id,
        prediction_contract.verify_predictions,
        metrics_contract.verify_metrics,
    )
