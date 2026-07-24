"""Frozen gold-blind Qwen candidate generation for GSM8K relation-only data."""

from __future__ import annotations

import argparse
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from .ids import canonical_json
from . import prediction_artifacts as artifact_io
from .prediction_artifacts import PredictionArtifactError
from . import development_training_data
from . import generation
from .relation_supervision import RelationOnlyPair, RelationSupervisionError


ALLOWED_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
MODEL_PATH = Path(generation.MODEL_PATH)
MODEL_SHA256SUMS_SHA256 = (
    "3ee6c9510b7e50bfcd46d6df33cafa3e2019f13a6a09bf1d2f9e80cdfe1164e8"
)
DATA_EXECUTION_COMMIT = "3c02685845f54475b7bca834200aa584b02e4a6c"
DATA_MANIFEST_SHA256 = (
    "0631e02c6ff0e61cfba616fc262198cf7578170f80733b7debcca5a770acf4d4"
)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "docs/ai-context/candidate-prompt-v1.json"
SFT_PROTOCOL_PATH = Path(__file__).resolve().parents[2] / "docs/ai-context/sft-protocol-v1.json"
EVALUATION_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[2] / "docs/ai-context/evaluation-protocol-v1.json"
)
PROMPT_SHA256 = "8632dfbd3f8f2b90c9a897bdb15b232b92705d79c8d8dcfd3f7ea94886f67349"
SFT_PROTOCOL_SHA256 = "86c1de0b6c47e9e9275771866bc42b6b39b56c0f3b1430a9cfc1fd35225f0d43"
EVALUATION_PROTOCOL_SHA256 = (
    "b15074103a7940777dd6e39e0aa2f9831ca9fc344affddc102a8a0c3fc88aee1"
)
CHAT_TEMPLATE_SHA256 = (
    "cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f"
)
POOL_SEED = 20260725
ARTIFACT_ROOT = ALLOWED_DATA_ROOT / "artifacts/relation-candidates"
ARTIFACT_ID = "gsm8k-relation-qwen25-7b-pool-v1"
CONFIG_NAME = "config.json"
TRAIN_CANDIDATES_NAME = "train-candidates.jsonl"
TRAIN_EVIDENCE_NAME = "train-evidence.jsonl"
DEV_CANDIDATES_NAME = "internal-dev-candidates.jsonl"
DEV_EVIDENCE_NAME = "internal-dev-evidence.jsonl"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = "gsm8k-relation-candidate-manifest-v1"
CANDIDATE_SCHEMA_VERSION = "gsm8k-relation-candidate-record-v1"
EVIDENCE_SCHEMA_VERSION = "gsm8k-relation-candidate-evidence-v1"
STATUS = "COMPLETE_DEVELOPMENT_ONLY"
MAX_INPUT_TOKENS = 4096
DIRECT_MAX_NEW_TOKENS = 128
COT_MAX_NEW_TOKENS = 512
SAMPLE_COUNT = 8
TEMPERATURE = 0.7
TOP_P = 0.9
TOP_K = 0
PAD_TOKEN_ID = 151643
EOS_TOKEN_IDS = (151645, 151643)
MIN_FREE_GPU_MIB = 22 * 1024
_RESPONSE_LIMIT = 64 * 1024
_ARTIFACT_LIMIT = 512 * 1024 * 1024
_CONFIG_LIMIT = 4 * 1024 * 1024
_LINE_LIMIT = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_NAMES = {
    CONFIG_NAME,
    TRAIN_CANDIDATES_NAME,
    TRAIN_EVIDENCE_NAME,
    DEV_CANDIDATES_NAME,
    DEV_EVIDENCE_NAME,
    MANIFEST_NAME,
}


class RelationCandidateError(ValueError):
    """A protocol, generation, resource, publication, or replay invariant failed."""


def _fail(message: str) -> None:
    raise RelationCandidateError(message) from None


@dataclass(frozen=True)
class Position:
    method: str
    sample_position: int | None
    max_new_tokens: int
    do_sample: bool

    @property
    def origin(self) -> str:
        return "self-consistency" if self.method == "self-consistency" else self.method


POSITIONS = (
    Position("direct", None, DIRECT_MAX_NEW_TOKENS, False),
    Position("cot", None, COT_MAX_NEW_TOKENS, False),
    *(Position("self-consistency", index, COT_MAX_NEW_TOKENS, True) for index in range(SAMPLE_COUNT)),
)


@dataclass(frozen=True)
class PoolRecord:
    pair_id: str
    source_id: str
    partition: str
    proposals: tuple[Mapping[str, Any], ...]
    candidates: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "pair_id": self.pair_id,
            "source_id": self.source_id,
            "partition": self.partition,
            "gold_access": "NONE",
            "proposals": [dict(value) for value in self.proposals],
            "candidates": [dict(value) for value in self.candidates],
        }


@dataclass(frozen=True)
class CandidateGenerationResult:
    train_candidates: bytes
    train_evidence: bytes
    dev_candidates: bytes
    dev_evidence: bytes
    train_count: int
    dev_count: int
    parse_error_count: int
    generated_token_count: int


@dataclass(frozen=True)
class VerifiedCandidateArtifact:
    artifact_path: Path
    train_count: int
    internal_dev_count: int
    manifest_sha256: str
    train_candidates_sha256: str
    internal_dev_candidates_sha256: str


def _file_bytes(path: Path, expected_sha256: str, name: str) -> bytes:
    try:
        info = path.lstat()
        payload = path.read_bytes()
    except OSError as error:
        raise RelationCandidateError(f"{name} is unavailable") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        _fail(f"{name} identity differs")
    return payload


def _protocols() -> Mapping[str, Mapping[str, Any]]:
    result = {}
    for key, path, expected in (
        ("candidate", PROMPT_PATH, PROMPT_SHA256),
        ("sft", SFT_PROTOCOL_PATH, SFT_PROTOCOL_SHA256),
        ("evaluation", EVALUATION_PROTOCOL_PATH, EVALUATION_PROTOCOL_SHA256),
    ):
        payload = _file_bytes(path, expected, f"{key} protocol")
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RelationCandidateError(f"{key} protocol JSON is invalid") from error
        if not isinstance(value, MappingABC):
            _fail(f"{key} protocol is not an object")
        result[key] = value
    return result


def _verify_model_files() -> Mapping[str, str]:
    sums_payload = _file_bytes(
        MODEL_PATH / "SHA256SUMS", MODEL_SHA256SUMS_SHA256, "model SHA256SUMS"
    )
    try:
        lines = sums_payload.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as error:
        raise RelationCandidateError("model SHA256SUMS is not UTF-8") from error
    result = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            _fail("model SHA256SUMS grammar differs")
        digest, relative = line[:64], line[66:]
        if not _HEX64.fullmatch(digest) or not relative or relative in result:
            _fail("model SHA256SUMS entry differs")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            _fail("model SHA256SUMS path is unsafe")
        path = MODEL_PATH / relative_path
        try:
            info = path.lstat()
        except OSError:
            _fail("model file is unavailable")
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
            _fail("model file metadata differs")
        hasher = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError as error:
            raise RelationCandidateError("model file cannot be hashed") from error
        if hasher.hexdigest() != digest:
            _fail("model file SHA256 differs")
        result[relative] = digest
    if len(result) != 14:
        _fail("model SHA256SUMS entry count differs")
    try:
        names = {entry.name for entry in os.scandir(MODEL_PATH)}
    except OSError as error:
        raise RelationCandidateError("model namespace cannot be scanned") from error
    if names != set(result).union({"SHA256SUMS"}):
        _fail("model namespace differs from SHA256SUMS")
    result["SHA256SUMS"] = MODEL_SHA256SUMS_SHA256
    tokenizer_config = _file_bytes(
        MODEL_PATH / "tokenizer_config.json",
        result.get("tokenizer_config.json", ""),
        "model tokenizer config",
    )
    try:
        tokenizer_value = json.loads(tokenizer_config.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RelationCandidateError("model tokenizer config is invalid") from error
    chat_template = tokenizer_value.get("chat_template")
    if (
        not isinstance(chat_template, str)
        or hashlib.sha256(chat_template.encode("utf-8")).hexdigest()
        != CHAT_TEMPLATE_SHA256
    ):
        _fail("model chat template identity differs")
    return result


def _seed(source_id: str, sample_position: int) -> int:
    if not isinstance(source_id, str) or not source_id or not 0 <= sample_position < 8:
        _fail("candidate seed identity is invalid")
    payload = (
        b"kairos-candidate-v1\0"
        + str(POOL_SEED).encode("ascii")
        + b"\0"
        + source_id.encode("utf-8", errors="strict")
        + b"\0"
        + str(sample_position).encode("ascii")
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _parse_response(method: str, response: str) -> str:
    if not isinstance(response, str):
        _fail("candidate response is not a string")
    try:
        encoded = response.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("candidate response is not valid Unicode")
    if not encoded or len(encoded) > _RESPONSE_LIMIT:
        _fail("candidate response is empty or exceeds 64 KiB")
    if method == "direct":
        payload = response.strip(" \t\r\n")
    elif method in {"cot", "self-consistency"}:
        lines = response.splitlines()
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines or not lines[-1].startswith("FINAL_ANSWER: "):
            _fail("candidate CoT terminal line differs")
        payload = lines[-1][len("FINAL_ANSWER: ") :]
    else:
        _fail("candidate method is invalid")

    def reject_constant(unused: str) -> Any:
        _fail("candidate JSON contains a non-finite value")

    try:
        value = json.loads(payload, parse_constant=reject_constant)
    except json.JSONDecodeError as error:
        raise RelationCandidateError("candidate answer is not strict JSON") from error
    if not isinstance(value, str) or not value:
        _fail("candidate answer must be a non-empty JSON string")
    try:
        value_bytes = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("candidate answer is not valid Unicode")
    if len(value_bytes) > 4096:
        _fail("candidate answer exceeds its byte limit")
    return value


def _pool(pair_id: str, source_id: str, partition: str, evidence: Sequence[Mapping[str, Any]]) -> PoolRecord:
    if len(evidence) != len(POSITIONS):
        _fail("candidate evidence coverage differs")
    proposals = []
    candidates: list[dict[str, Any]] = []
    by_text: dict[str, int] = {}
    for position, row in zip(POSITIONS, evidence):
        if row["parse_status"] != "PARSED":
            continue
        answer = row["parsed_answer"]
        proposal = {
            "text": answer,
            "origin": position.origin,
            "position": position.sample_position,
            "content_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        }
        proposals.append(proposal)
        if answer not in by_text:
            by_text[answer] = len(candidates)
            candidates.append(
                {
                    "text": answer,
                    "content_sha256": proposal["content_sha256"],
                    "origins": [position.origin],
                }
            )
        elif position.origin not in candidates[by_text[answer]]["origins"]:
            candidates[by_text[answer]]["origins"].append(position.origin)
    return PoolRecord(pair_id, source_id, partition, tuple(proposals), tuple(candidates))


def _data_records() -> tuple[tuple[RelationOnlyPair, ...], tuple[RelationOnlyPair, ...]]:
    verified = development_training_data.verify(DATA_EXECUTION_COMMIT)
    if verified.manifest_sha256 != DATA_MANIFEST_SHA256:
        _fail("development data manifest differs")

    def load(name: str, expected_count: int) -> tuple[RelationOnlyPair, ...]:
        try:
            payload = artifact_io._read_artifact_file(
                verified.artifact_path / name, 32 * 1024 * 1024, name
            )
        except PredictionArtifactError as error:
            raise RelationCandidateError("development partition file is invalid") from error
        rows = []
        for raw in payload.splitlines(keepends=True):
            if not raw.endswith(b"\n"):
                _fail("development partition line framing differs")
            try:
                value = artifact_io._strict_json(raw[:-1], name)
                pair = RelationOnlyPair.from_dict(value)
            except (PredictionArtifactError, RelationSupervisionError) as error:
                raise RelationCandidateError("development partition replay failed") from error
            if canonical_json(pair.to_dict()).encode("utf-8") + b"\n" != raw:
                _fail("development partition row differs from pair replay")
            rows.append(pair)
        if len(rows) != expected_count:
            _fail("development partition count differs")
        return tuple(rows)

    return load(development_training_data.TRAIN_NAME, 330), load(
        development_training_data.DEV_NAME, 36
    )


def _chat_prompt(tokenizer: Any, protocol: Mapping[str, Any], query: str, position: Position) -> str:
    template_key = "direct_user_template" if position.method == "direct" else "cot_user_template"
    template = protocol.get(template_key)
    system = protocol.get("system")
    if not isinstance(template, str) or template.count("{query}") != 1 or not isinstance(system, str):
        _fail("candidate prompt protocol differs")
    user = template.replace("{query}", query)
    try:
        rendered = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception as error:
        raise RelationCandidateError("candidate chat rendering failed") from error
    if not isinstance(rendered, str) or not rendered:
        _fail("candidate rendered prompt is invalid")
    return rendered


def _tokenize(tokenizer: Any, prompt: str) -> Mapping[str, Tensor]:
    try:
        encoded = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=False,
            add_special_tokens=False,
        )
    except Exception as error:
        raise RelationCandidateError("candidate tokenization failed") from error
    if not isinstance(encoded, MappingABC):
        _fail("candidate tokenizer output is invalid")
    input_ids = encoded.get("input_ids")
    attention = encoded.get("attention_mask")
    if (
        not isinstance(input_ids, Tensor)
        or input_ids.shape[0] != 1
        or input_ids.ndim != 2
        or not isinstance(attention, Tensor)
        or attention.shape != input_ids.shape
    ):
        _fail("candidate token tensors are invalid")
    count = int(attention.sum().item())
    if not 1 <= count <= MAX_INPUT_TOKENS or input_ids.shape[1] != count:
        _fail("candidate input exceeds its frozen token budget")
    return {"input_ids": input_ids.long(), "attention_mask": attention.long()}


def _generated_count(tokens: Tensor) -> int:
    count = 0
    for item in tokens.tolist():
        count += 1
        if int(item) in EOS_TOKEN_IDS:
            break
    return count


def _one_generation(
    model: Any,
    tokenizer: Any,
    protocol: Mapping[str, Any],
    pair: RelationOnlyPair,
    position: Position,
) -> Mapping[str, Any]:
    prompt = _chat_prompt(tokenizer, protocol, pair.original_query, position)
    encoded = _tokenize(tokenizer, prompt)
    seed = None
    if position.do_sample:
        assert position.sample_position is not None
        seed = _seed(pair.source_id, position.sample_position)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    device_inputs = {key: value.to("cuda:0") for key, value in encoded.items()}
    arguments = {
        "max_new_tokens": position.max_new_tokens,
        "do_sample": position.do_sample,
        "use_cache": True,
        "pad_token_id": PAD_TOKEN_ID,
        "eos_token_id": list(EOS_TOKEN_IDS),
    }
    if position.do_sample:
        arguments.update(temperature=TEMPERATURE, top_p=TOP_P, top_k=TOP_K)
    else:
        arguments.update(temperature=None, top_p=None, top_k=None)
    try:
        with torch.inference_mode():
            output = model.generate(**device_inputs, **arguments)
    except Exception as error:
        raise RelationCandidateError("candidate model generation failed") from error
    width = encoded["input_ids"].shape[1]
    if (
        not isinstance(output, Tensor)
        or output.ndim != 2
        or output.shape[0] != 1
        or not width <= output.shape[1] <= width + position.max_new_tokens
    ):
        _fail("candidate generation tensor shape differs")
    tokens = output[0, width:].detach().cpu()
    try:
        response = tokenizer.decode(
            tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
    except Exception as error:
        raise RelationCandidateError("candidate decode failed") from error
    try:
        parsed = _parse_response(position.method, response)
        parse_status = "PARSED"
        parse_error = None
    except RelationCandidateError as error:
        parsed = None
        parse_status = "PARSE_ERROR"
        parse_error = str(error)
    return {
        "method": position.method,
        "sample_position": position.sample_position,
        "generation_seed": seed,
        "max_new_tokens": position.max_new_tokens,
        "raw_response": response,
        "parse_status": parse_status,
        "parse_error": parse_error,
        "parsed_answer": parsed,
        "input_token_count": int(encoded["attention_mask"].sum().item()),
        "generated_token_count": _generated_count(tokens),
    }


def _generate_partition(
    model: Any,
    tokenizer: Any,
    protocol: Mapping[str, Any],
    pairs: Sequence[RelationOnlyPair],
    partition: str,
) -> tuple[bytes, bytes, int, int]:
    candidate_lines = []
    evidence_lines = []
    parse_errors = 0
    generated_tokens = 0
    for pair in pairs:
        rows = tuple(_one_generation(model, tokenizer, protocol, pair, position) for position in POSITIONS)
        parse_errors += sum(row["parse_status"] != "PARSED" for row in rows)
        generated_tokens += sum(row["generated_token_count"] for row in rows)
        pool = _pool(pair.pair_id, pair.source_id, partition, rows)
        candidate_lines.append(canonical_json(pool.to_dict()).encode("utf-8") + b"\n")
        evidence_lines.append(
            canonical_json(
                {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "pair_id": pair.pair_id,
                    "source_id": pair.source_id,
                    "partition": partition,
                    "positions": list(rows),
                }
            ).encode("utf-8")
            + b"\n"
        )
    candidates = b"".join(candidate_lines)
    evidence = b"".join(evidence_lines)
    if len(candidates) > _ARTIFACT_LIMIT or len(evidence) > _ARTIFACT_LIMIT:
        _fail("candidate partition exceeds its byte ceiling")
    return candidates, evidence, parse_errors, generated_tokens


def _resource_gate(path: Path, execution_commit: str) -> tuple[Mapping[str, Any], str]:
    if not path.is_absolute() or not path.is_relative_to(ALLOWED_DATA_ROOT):
        _fail("resource gate path is outside the allowed data root")
    try:
        payload = artifact_io._read_artifact_file(path, _CONFIG_LIMIT, "resource gate")
        value = artifact_io._canonical_object(payload, "resource gate")
    except PredictionArtifactError as error:
        raise RelationCandidateError("resource gate artifact is invalid") from error
    gpu = value.get("selected_gpu")
    if (
        value.get("schema_version") != "kairos-model-resource-gate-v1"
        or value.get("status") != "PASSED"
        or value.get("execution_commit") != execution_commit
        or value.get("model_files_verified") is not True
        or not isinstance(gpu, MappingABC)
        or not isinstance(gpu.get("uuid"), str)
        or not isinstance(gpu.get("pci_bus_id"), str)
        or not isinstance(gpu.get("name"), str)
        or type(gpu.get("physical_index")) is not int
        or type(gpu.get("total_mib")) is not int
        or type(gpu.get("torch_total_bytes")) is not int
        or type(gpu.get("free_mib")) is not int
        or type(gpu.get("free_bytes")) is not int
        or gpu["free_bytes"] != gpu["free_mib"] * 1024**2
        or not 0 <= gpu["physical_index"] < 64
        or not 0 < gpu["free_mib"] <= gpu["total_mib"]
        or not 20 * 1024**3 <= gpu["torch_total_bytes"] <= 26 * 1024**3
        or gpu["free_mib"] < MIN_FREE_GPU_MIB
        or gpu.get("compute_process_count") != 0
        or type(value.get("data0_free_bytes")) is not int
        or value["data0_free_bytes"] < 120 * 1024**3
        or type(value.get("memory_available_bytes")) is not int
        or value["memory_available_bytes"] < 64 * 1024**3
        or type(value.get("project_bytes_before")) is not int
        or type(value.get("projected_new_bytes")) is not int
        or type(value.get("projected_project_bytes_after")) is not int
        or value["projected_new_bytes"] > 2 * 1024**3
        or value["projected_project_bytes_after"]
        != value["project_bytes_before"] + value["projected_new_bytes"]
        or value["projected_project_bytes_after"] > 80 * 1024**3
        or value.get("gpu_count") != 1
        or value.get("cpu_thread_limit") != 8
        or value.get("dataloader_workers") != 2
    ):
        _fail("resource gate does not satisfy the frozen candidate boundary")
    return value, hashlib.sha256(payload).hexdigest()


def _nvidia_query(arguments: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/nvidia-smi", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RelationCandidateError("nvidia-smi query failed") from error
    if result.returncode != 0 or len(result.stdout) > 1024 * 1024:
        _fail("nvidia-smi query failed")
    try:
        return result.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RelationCandidateError("nvidia-smi output is not UTF-8") from error


def _gpu_gate(gate: Mapping[str, Any]) -> None:
    gpu = gate["selected_gpu"]
    if os.environ.get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID" or os.environ.get(
        "CUDA_VISIBLE_DEVICES"
    ) != gpu["uuid"]:
        _fail("CUDA UUID environment differs from resource gate")
    def live_identity() -> tuple[int, str, str, str, int, int]:
        fields = _nvidia_query(
            (
                f"--id={gpu['uuid']}",
                "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            )
        ).strip().split(", ")
        try:
            value = (
                int(fields[0]),
                fields[1],
                fields[2],
                fields[3],
                int(fields[4]),
                int(fields[5]),
            )
        except (IndexError, ValueError):
            _fail("selected GPU live identity is malformed")
        if (
            len(fields) != 6
            or value[0] != gpu["physical_index"]
            or value[1] != gpu["uuid"]
            or value[2].casefold() != gpu["pci_bus_id"].casefold()
            or value[3] != gpu["name"]
            or value[4] != gpu["total_mib"]
            or value[5] < MIN_FREE_GPU_MIB
        ):
            _fail("selected GPU live identity or free memory differs")
        return value

    def process_ids() -> set[int]:
        output = _nvidia_query(
            (
                "--query-compute-apps=gpu_uuid,pid",
                "--format=csv,noheader,nounits",
            )
        )
        result = set()
        for line in output.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if fields and fields[0] == gpu["uuid"]:
                try:
                    result.add(int(fields[1]))
                except (IndexError, ValueError):
                    _fail("selected GPU process identity is malformed")
        return result

    live_identity()
    if process_ids():
        _fail("selected GPU acquired a compute process before CUDA initialization")
    if torch.cuda.device_count() != 1:
        _fail("CUDA does not expose exactly one selected GPU")
    properties = torch.cuda.get_device_properties(0)
    if (
        properties.name != gpu["name"]
        or properties.total_memory != gpu["torch_total_bytes"]
    ):
        _fail("Torch visible GPU capacity differs from resource gate")
    live_identity()
    unexpected_processes = process_ids().difference({os.getpid()})
    if unexpected_processes:
        _fail("another compute process appeared on the selected GPU")


def _config(
    execution_commit: str,
    gate_path: Path,
    gate_sha256: str,
    model_files: Mapping[str, str],
) -> Mapping[str, Any]:
    return {
        "schema_version": "gsm8k-relation-candidate-config-v1",
        "execution_commit": execution_commit,
        "model_id": generation.MODEL_ID,
        "model_revision": generation.MODEL_REVISION,
        "model_sha256sums_sha256": MODEL_SHA256SUMS_SHA256,
        "model_file_count": len(model_files),
        "model_files": dict(model_files),
        "chat_template_sha256": CHAT_TEMPLATE_SHA256,
        "resource_gate_path": str(gate_path),
        "resource_gate_sha256": gate_sha256,
        "data_manifest_sha256": DATA_MANIFEST_SHA256,
        "prompt_sha256": PROMPT_SHA256,
        "sft_protocol_sha256": SFT_PROTOCOL_SHA256,
        "evaluation_protocol_sha256": EVALUATION_PROTOCOL_SHA256,
        "pool_seed": POOL_SEED,
        "positions": [
            {
                "method": value.method,
                "sample_position": value.sample_position,
                "max_new_tokens": value.max_new_tokens,
                "do_sample": value.do_sample,
            }
            for value in POSITIONS
        ],
        "sampling": {"temperature": TEMPERATURE, "top_p": TOP_P, "top_k": TOP_K},
        "max_input_tokens": MAX_INPUT_TOKENS,
        "batch_size": 1,
        "dtype": "bfloat16",
        "attention_implementation": "sdpa",
        "eos_token_ids": list(EOS_TOKEN_IDS),
        "pad_token_id": PAD_TOKEN_ID,
        "gold_access": "NONE",
    }


def _payload(value: Mapping[str, Any], name: str) -> bytes:
    payload = canonical_json(value).encode("utf-8") + b"\n"
    if len(payload) > _CONFIG_LIMIT:
        _fail(f"{name} exceeds its byte limit")
    return payload


def _binding(payload: bytes, count: int | None = None) -> Mapping[str, Any]:
    value: dict[str, Any] = {
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if count is not None:
        value["record_count"] = count
    return value


def _manifest(
    execution_commit: str,
    config: bytes,
    result: CandidateGenerationResult,
) -> Mapping[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": STATUS,
        "artifact_id": ARTIFACT_ID,
        "execution_commit": execution_commit,
        "paper_metric_eligible": False,
        "gold_access": "NONE",
        "configuration": _binding(config),
        "outputs": {
            TRAIN_CANDIDATES_NAME: _binding(result.train_candidates, result.train_count),
            TRAIN_EVIDENCE_NAME: _binding(result.train_evidence, result.train_count),
            DEV_CANDIDATES_NAME: _binding(result.dev_candidates, result.dev_count),
            DEV_EVIDENCE_NAME: _binding(result.dev_evidence, result.dev_count),
        },
        "summary": {
            "parse_error_count": result.parse_error_count,
            "generated_token_count": result.generated_token_count,
        },
    }


def _replay_partition(
    candidates: bytes,
    evidence: bytes,
    pairs: Sequence[RelationOnlyPair],
    partition: str,
) -> tuple[int, int]:
    candidate_lines = candidates.splitlines(keepends=True)
    evidence_lines = evidence.splitlines(keepends=True)
    if len(candidate_lines) != len(pairs) or len(evidence_lines) != len(pairs):
        _fail("candidate artifact coverage differs")
    parse_errors = 0
    generated_tokens = 0
    for pair, candidate_raw, evidence_raw in zip(pairs, candidate_lines, evidence_lines):
        if not candidate_raw.endswith(b"\n") or not evidence_raw.endswith(b"\n"):
            _fail("candidate artifact line framing differs")
        try:
            candidate = artifact_io._strict_json(candidate_raw[:-1], "candidate record")
            evidence_value = artifact_io._strict_json(evidence_raw[:-1], "evidence record")
        except PredictionArtifactError as error:
            raise RelationCandidateError("candidate artifact JSON is invalid") from error
        if (
            canonical_json(candidate).encode("utf-8") + b"\n" != candidate_raw
            or canonical_json(evidence_value).encode("utf-8") + b"\n" != evidence_raw
            or evidence_value.get("schema_version") != EVIDENCE_SCHEMA_VERSION
            or evidence_value.get("pair_id") != pair.pair_id
            or evidence_value.get("source_id") != pair.source_id
            or evidence_value.get("partition") != partition
            or not isinstance(evidence_value.get("positions"), list)
            or len(evidence_value["positions"]) != len(POSITIONS)
        ):
            _fail("candidate artifact identity differs")
        rows = evidence_value["positions"]
        for position, row in zip(POSITIONS, rows):
            if not isinstance(row, MappingABC) or set(row) != {
                "method",
                "sample_position",
                "generation_seed",
                "max_new_tokens",
                "raw_response",
                "parse_status",
                "parse_error",
                "parsed_answer",
                "input_token_count",
                "generated_token_count",
            }:
                _fail("candidate evidence row schema differs")
            if (
                row.get("method") != position.method
                or row.get("sample_position") != position.sample_position
                or row.get("max_new_tokens") != position.max_new_tokens
                or row.get("generation_seed")
                != (_seed(pair.source_id, position.sample_position) if position.do_sample else None)
                or not isinstance(row.get("raw_response"), str)
                or type(row.get("input_token_count")) is not int
                or not 1 <= row["input_token_count"] <= MAX_INPUT_TOKENS
                or type(row.get("generated_token_count")) is not int
                or not 0 <= row["generated_token_count"] <= position.max_new_tokens
            ):
                _fail("candidate evidence position differs")
            try:
                parsed = _parse_response(position.method, row["raw_response"])
                expected_status = "PARSED"
                expected_error = None
            except RelationCandidateError as error:
                parsed = None
                expected_status = "PARSE_ERROR"
                expected_error = str(error)
            if (
                row.get("parse_status") != expected_status
                or row.get("parse_error") != expected_error
                or row.get("parsed_answer") != parsed
            ):
                _fail("candidate evidence parser replay differs")
            parse_errors += expected_status != "PARSED"
            generated_tokens += row["generated_token_count"]
        expected = _pool(pair.pair_id, pair.source_id, partition, rows).to_dict()
        if candidate != expected:
            _fail("candidate pool differs from raw evidence replay")
    return parse_errors, generated_tokens


def _verify(expected_commit: str | None = None) -> VerifiedCandidateArtifact:
    train, dev = _data_records()
    target = ARTIFACT_ROOT / ARTIFACT_ID
    development_training_data.audit_artifacts._private_directory(ARTIFACT_ROOT, "candidate root")
    development_training_data.audit_artifacts._namespace(target, _OUTPUT_NAMES, "candidate artifact")
    files = {
        name: artifact_io._read_artifact_file(
            target / name,
            _ARTIFACT_LIMIT if name.endswith(".jsonl") else _CONFIG_LIMIT,
            name,
        )
        for name in _OUTPUT_NAMES
    }
    config = artifact_io._canonical_object(files[CONFIG_NAME], "candidate config")
    manifest = artifact_io._canonical_object(files[MANIFEST_NAME], "candidate manifest")
    execution_commit = config.get("execution_commit")
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("candidate execution commit is invalid")
    if expected_commit is not None and execution_commit != expected_commit:
        _fail("candidate execution commit differs")
    if manifest.get("execution_commit") != execution_commit:
        _fail("candidate manifest commit differs")
    gate_path_raw = config.get("resource_gate_path")
    gate_sha256 = config.get("resource_gate_sha256")
    if (
        not isinstance(gate_path_raw, str)
        or not isinstance(gate_sha256, str)
        or not _HEX64.fullmatch(gate_sha256)
    ):
        _fail("candidate resource gate binding differs")
    gate_path = Path(gate_path_raw)
    _, replayed_gate_sha256 = _resource_gate(gate_path, execution_commit)
    if replayed_gate_sha256 != gate_sha256:
        _fail("candidate resource gate SHA256 differs")
    model_files = _verify_model_files()
    expected_config = _config(
        execution_commit, gate_path, gate_sha256, model_files
    )
    if config != expected_config:
        _fail("candidate configuration differs")
    train_errors, train_tokens = _replay_partition(
        files[TRAIN_CANDIDATES_NAME], files[TRAIN_EVIDENCE_NAME], train, "train"
    )
    dev_errors, dev_tokens = _replay_partition(
        files[DEV_CANDIDATES_NAME], files[DEV_EVIDENCE_NAME], dev, "internal-dev"
    )
    summary = manifest.get("summary")
    if (
        not isinstance(summary, MappingABC)
        or type(summary.get("parse_error_count")) is not int
        or not 0 <= summary["parse_error_count"] <= (len(train) + len(dev)) * len(POSITIONS)
        or type(summary.get("generated_token_count")) is not int
        or summary["generated_token_count"] < 0
        or summary["parse_error_count"] != train_errors + dev_errors
        or summary["generated_token_count"] != train_tokens + dev_tokens
    ):
        _fail("candidate manifest summary differs")
    result = CandidateGenerationResult(
        files[TRAIN_CANDIDATES_NAME],
        files[TRAIN_EVIDENCE_NAME],
        files[DEV_CANDIDATES_NAME],
        files[DEV_EVIDENCE_NAME],
        len(train),
        len(dev),
        summary["parse_error_count"],
        summary["generated_token_count"],
    )
    if manifest != _manifest(execution_commit, files[CONFIG_NAME], result):
        _fail("candidate manifest differs")
    return VerifiedCandidateArtifact(
        target,
        len(train),
        len(dev),
        hashlib.sha256(files[MANIFEST_NAME]).hexdigest(),
        hashlib.sha256(files[TRAIN_CANDIDATES_NAME]).hexdigest(),
        hashlib.sha256(files[DEV_CANDIDATES_NAME]).hexdigest(),
    )


def generate(
    execution_commit: str,
    resource_gate_path: Path,
    smoke_limit: int | None = None,
) -> Mapping[str, Any]:
    if not isinstance(execution_commit, str) or not _HEX40.fullmatch(execution_commit):
        _fail("execution commit is invalid")
    artifact_io._git_gate(execution_commit)
    protocols = _protocols()
    train, dev = _data_records()
    gate, gate_sha = _resource_gate(resource_gate_path, execution_commit)
    model_files = _verify_model_files()
    _gpu_gate(gate)
    torch.use_deterministic_algorithms(True)
    try:
        model, tokenizer = generation.load_local_backbone("cuda:0")
    except generation.GenerationError as error:
        raise RelationCandidateError("candidate backbone load failed") from error
    if tokenizer.pad_token_id != PAD_TOKEN_ID or tokenizer.eos_token_id != EOS_TOKEN_IDS[0]:
        _fail("candidate tokenizer special token identity differs")
    protocol = protocols["candidate"]
    if smoke_limit is not None:
        if not 1 <= smoke_limit <= 8:
            _fail("candidate smoke limit is invalid")
        selected = train[:smoke_limit]
        candidates, evidence, errors, tokens = _generate_partition(
            model, tokenizer, protocol, selected, "smoke"
        )
        return {
            "status": "SMOKE_COMPLETE / NO_ARTIFACT",
            "record_count": len(selected),
            "candidate_sha256": hashlib.sha256(candidates).hexdigest(),
            "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
            "parse_error_count": errors,
            "generated_token_count": tokens,
        }
    train_candidates, train_evidence, train_errors, train_tokens = _generate_partition(
        model, tokenizer, protocol, train, "train"
    )
    dev_candidates, dev_evidence, dev_errors, dev_tokens = _generate_partition(
        model, tokenizer, protocol, dev, "internal-dev"
    )
    result = CandidateGenerationResult(
        train_candidates,
        train_evidence,
        dev_candidates,
        dev_evidence,
        len(train),
        len(dev),
        train_errors + dev_errors,
        train_tokens + dev_tokens,
    )
    config_payload = _payload(
        _config(execution_commit, resource_gate_path, gate_sha, model_files),
        "candidate config",
    )
    manifest_payload = _payload(_manifest(execution_commit, config_payload, result), "candidate manifest")
    development_training_data.audit_artifacts._private_directory(
        ARTIFACT_ROOT.parent, "candidate root parent"
    )
    artifact_io._prepare_root(ARTIFACT_ROOT)
    target = ARTIFACT_ROOT / ARTIFACT_ID
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        _fail("candidate artifact already exists")
    try:
        for name, payload in (
            (CONFIG_NAME, config_payload),
            (TRAIN_CANDIDATES_NAME, train_candidates),
            (TRAIN_EVIDENCE_NAME, train_evidence),
            (DEV_CANDIDATES_NAME, dev_candidates),
            (DEV_EVIDENCE_NAME, dev_evidence),
        ):
            artifact_io._write_exclusive(target / name, payload)
        artifact_io._fsync_directory(target)
        artifact_io._git_gate(execution_commit)
        artifact_io._write_exclusive(target / MANIFEST_NAME, manifest_payload)
        artifact_io._fsync_directory(target)
        artifact_io._fsync_directory(ARTIFACT_ROOT)
    except (PredictionArtifactError, OSError) as error:
        raise RelationCandidateError("candidate publication failed; partial state retained") from error
    verified = _verify(execution_commit)
    return {
        "status": STATUS,
        "artifact_path": str(verified.artifact_path),
        "manifest_sha256": verified.manifest_sha256,
        "train_candidates_sha256": verified.train_candidates_sha256,
        "internal_dev_candidates_sha256": verified.internal_dev_candidates_sha256,
        "parse_error_count": result.parse_error_count,
        "generated_token_count": result.generated_token_count,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("smoke", "generate"):
        command = commands.add_parser(name)
        command.add_argument("--execution-commit", required=True)
        command.add_argument("--resource-gate", type=Path, required=True)
        if name == "smoke":
            command.add_argument("--limit", type=int, default=8)
    verifier = commands.add_parser("verify")
    verifier.add_argument("--expected-commit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "verify":
            value: Any = _verify(arguments.expected_commit)
            result = {
                "status": STATUS,
                "artifact_path": str(value.artifact_path),
                "manifest_sha256": value.manifest_sha256,
                "train_candidates_sha256": value.train_candidates_sha256,
                "internal_dev_candidates_sha256": value.internal_dev_candidates_sha256,
            }
        else:
            result = generate(
                arguments.execution_commit,
                arguments.resource_gate,
                arguments.limit if arguments.command == "smoke" else None,
            )
    except (RelationCandidateError, PredictionArtifactError) as error:
        print(f"relation candidates failed: {error}", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
