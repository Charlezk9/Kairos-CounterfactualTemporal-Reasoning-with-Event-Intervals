"""Immutable publication and replay of deterministic training plans."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from .ids import canonical_json
from . import prediction_artifacts as artifact_io
from .prediction_artifacts import PredictionArtifactError
from .training_plan import TrainingPlan, TrainingPlanError, training_plan_from_dict


ARTIFACT_ROOT = Path("/data0/hk_data/kairos-zx/artifacts/training-plans")
MANIFEST_SCHEMA_VERSION = "training-plan-artifact-manifest-v1"
STATUS = "TRAINING_PLAN_COMPLETE"
PLAN_NAME = "training-plan.json"
MANIFEST_NAME = "manifest.json"
_PLAN_LIMIT = 32 * 1024 * 1024
_MANIFEST_LIMIT = 1 * 1024 * 1024
_PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,190}[a-z0-9]$")


class TrainingPlanArtifactError(ValueError):
    """A training-plan publication or replay invariant failed."""


def _fail(message: str) -> None:
    raise TrainingPlanArtifactError(message) from None


@dataclass(frozen=True)
class VerifiedTrainingPlanArtifact:
    plan_id: str
    plan: TrainingPlan
    plan_semantic_sha256: str
    plan_file_sha256: str
    manifest_sha256: str
    artifact_path: Path


def make_plan_id(plan: TrainingPlan) -> str:
    if not isinstance(plan, TrainingPlan):
        _fail("training plan is invalid")
    dataset_slug = plan.corpus.dataset_id.replace("_", "-")
    value = (
        f"training-plan-{dataset_slug}-s{plan.seed}-"
        f"mb{plan.micro_batch_size}-{plan.manifest_sha256[:12]}"
    )
    if not _PLAN_ID.fullmatch(value):
        _fail("training plan ID is invalid")
    return value


def _payload(value: Mapping[str, Any], name: str, limit: int) -> bytes:
    try:
        payload = canonical_json(value).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise TrainingPlanArtifactError(
            f"{name} is not canonical-JSON compatible"
        ) from error
    if len(payload) > limit:
        _fail(f"{name} exceeds its byte limit")
    return payload


def _manifest_value(
    plan: TrainingPlan, plan_id: str, plan_payload: bytes
) -> Mapping[str, Any]:
    summary = plan.to_dict()["summary"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": STATUS,
        "plan_id": plan_id,
        "execution_commit": plan.corpus.execution_commit,
        "dataset": {
            "dataset_id": plan.corpus.dataset_id,
            "revision": plan.corpus.dataset_revision,
            "split": plan.corpus.official_split,
            "source_artifact_id": plan.corpus.source_artifact_id,
            "source_manifest_sha256": plan.corpus.source_manifest_sha256,
        },
        "sampler": {
            "seed": plan.seed,
            "micro_batch_size": plan.micro_batch_size,
            "optimizer_step_count": summary["optimizer_step_count"],
            "real_slot_count": summary["real_slot_count"],
            "repeat_padding_count": summary["repeat_padding_count"],
        },
        "plan": {
            "path": PLAN_NAME,
            "byte_size": len(plan_payload),
            "file_sha256": hashlib.sha256(plan_payload).hexdigest(),
            "semantic_sha256": plan.manifest_sha256,
        },
    }


def _require_private_directory(path: Path, name: str) -> None:
    try:
        info = path.lstat()
    except OSError:
        _fail(f"{name} is unavailable")
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        _fail(f"{name} metadata is invalid")


def _prepare_root(root: Path) -> None:
    allowed = Path("/data0/hk_data/kairos-zx")
    if not isinstance(root, Path) or not root.is_absolute() or not root.is_relative_to(allowed):
        _fail("training plan root is outside the allowed data path")
    _require_private_directory(root.parent, "training plan root parent")
    try:
        artifact_io._prepare_root(root)
    except (PredictionArtifactError, OSError) as error:
        raise TrainingPlanArtifactError("training plan root cannot be prepared") from error


def _canonical_object(payload: bytes, name: str) -> Mapping[str, Any]:
    try:
        return artifact_io._canonical_object(payload, name)
    except PredictionArtifactError as error:
        raise TrainingPlanArtifactError(f"{name} is invalid") from error


def _read(path: Path, limit: int, name: str) -> bytes:
    try:
        return artifact_io._read_artifact_file(path, limit, name)
    except PredictionArtifactError as error:
        raise TrainingPlanArtifactError(f"{name} file is invalid") from error


def _verify(root: Path, plan_id: str) -> VerifiedTrainingPlanArtifact:
    if not isinstance(plan_id, str) or not _PLAN_ID.fullmatch(plan_id):
        _fail("training plan ID is invalid")
    _require_private_directory(root, "training plan root")
    target = root / plan_id
    _require_private_directory(target, "training plan artifact directory")
    try:
        names = {entry.name for entry in os.scandir(target)}
    except OSError:
        _fail("training plan artifact directory cannot be scanned")
    if names != {PLAN_NAME, MANIFEST_NAME}:
        _fail("training plan artifact namespace differs")
    plan_payload = _read(target / PLAN_NAME, _PLAN_LIMIT, PLAN_NAME)
    manifest_payload = _read(target / MANIFEST_NAME, _MANIFEST_LIMIT, MANIFEST_NAME)
    plan_value = _canonical_object(plan_payload, "training plan")
    manifest = _canonical_object(manifest_payload, "training plan manifest")
    try:
        plan = training_plan_from_dict(plan_value)
    except TrainingPlanError as error:
        raise TrainingPlanArtifactError(
            "training plan deterministic reconstruction failed"
        ) from error
    if make_plan_id(plan) != plan_id:
        _fail("training plan ID differs from its content")
    expected_manifest = _manifest_value(plan, plan_id, plan_payload)
    if manifest != expected_manifest:
        _fail("training plan manifest facts differ")
    return VerifiedTrainingPlanArtifact(
        plan_id=plan_id,
        plan=plan,
        plan_semantic_sha256=plan.manifest_sha256,
        plan_file_sha256=hashlib.sha256(plan_payload).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(),
        artifact_path=target,
    )


def _publish(
    root: Path,
    plan: TrainingPlan,
    git_gate: Callable[[str], None],
) -> VerifiedTrainingPlanArtifact:
    if not isinstance(plan, TrainingPlan):
        _fail("training plan is invalid")
    plan_id = make_plan_id(plan)
    plan_payload = _payload(plan.to_dict(), "training plan", _PLAN_LIMIT)
    manifest_payload = _payload(
        _manifest_value(plan, plan_id, plan_payload),
        "training plan manifest",
        _MANIFEST_LIMIT,
    )
    try:
        git_gate(plan.corpus.execution_commit)
        _prepare_root(root)
    except (PredictionArtifactError, OSError) as error:
        raise TrainingPlanArtifactError("training plan publication gate failed") from error
    target = root / plan_id
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("training plan artifact already exists")
    except OSError as error:
        raise TrainingPlanArtifactError(
            "training plan artifact directory cannot be created"
        ) from error
    try:
        artifact_io._write_exclusive(target / PLAN_NAME, plan_payload)
        artifact_io._fsync_directory(target)
        git_gate(plan.corpus.execution_commit)
        artifact_io._write_exclusive(target / MANIFEST_NAME, manifest_payload)
        artifact_io._fsync_directory(target)
        artifact_io._fsync_directory(root)
    except (PredictionArtifactError, OSError) as error:
        raise TrainingPlanArtifactError(
            "training plan publication failed; partial state is retained"
        ) from error
    return _verify(root, plan_id)


def publish_training_plan(plan: TrainingPlan) -> VerifiedTrainingPlanArtifact:
    """Publish one clean-commit training plan without reading training records."""

    return _publish(ARTIFACT_ROOT, plan, artifact_io._git_gate)


def verify_training_plan(plan_id: str) -> VerifiedTrainingPlanArtifact:
    """Replay one immutable plan from its minimal corpus and sampler inputs."""

    return _verify(ARTIFACT_ROOT, plan_id)


__all__ = [
    "ARTIFACT_ROOT",
    "MANIFEST_SCHEMA_VERSION",
    "VerifiedTrainingPlanArtifact",
    "TrainingPlanArtifactError",
    "make_plan_id",
    "publish_training_plan",
    "verify_training_plan",
]
