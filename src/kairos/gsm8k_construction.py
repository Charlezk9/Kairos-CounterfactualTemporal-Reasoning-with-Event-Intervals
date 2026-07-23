"""Fixed GSM8K driver for D-011/D-012/P2 construction-audit publication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping, Sequence

from .construction import construct_explicit_counterfactual
from .construction_audit import (
    ConstructionAuditRecord,
    make_construction_audit_record,
)
from .construction_audit_persistence import (
    ConstructionAuditPersistenceError,
    REVISION,
    publish,
    verify,
)
from .ids import canonical_json
from .schema import TemporalExample


_DATA_ROOT = Path("/data0/hk_data/kairos-zx")
_SOURCE_PATHS = {
    "train": _DATA_ROOT
    / "data"
    / "processed"
    / "gsm8k"
    / REVISION
    / "source-record-v1"
    / "examples-train.jsonl",
    "test": _DATA_ROOT
    / "data"
    / "processed"
    / "gsm8k"
    / REVISION
    / "source-record-v1"
    / "examples-test.jsonl",
}
_SOURCE_LINE_LIMIT = 2_162_688


class Gsm8kConstructionError(ValueError):
    """The fixed construction driver rejected its source stream."""


def _fail() -> None:
    raise Gsm8kConstructionError("GSM8K construction input is invalid") from None


def _strict_object(payload: bytes) -> Mapping[str, Any]:
    duplicates: list[str] = []

    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    def constant(_: str) -> Any:
        _fail()

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail()
    if duplicates or not isinstance(value, Mapping):
        _fail()
    return value


def _record_stream(path: Path) -> Iterator[ConstructionAuditRecord]:
    try:
        handle = path.open("rb")
    except (FileNotFoundError, PermissionError, OSError):
        _fail()
    with handle:
        input_order = 0
        while True:
            line = handle.readline(_SOURCE_LINE_LIMIT + 2)
            if not line:
                break
            if len(line) > _SOURCE_LINE_LIMIT + 1 or not line.endswith(b"\n"):
                _fail()
            value = _strict_object(line[:-1])
            if canonical_json(value).encode("utf-8") + b"\n" != line:
                _fail()
            try:
                example = TemporalExample.from_dict(value)
                result = construct_explicit_counterfactual(example)
                record = make_construction_audit_record(
                    input_order=input_order,
                    input=example,
                    result=result,
                )
            except (TypeError, ValueError):
                _fail()
            yield record
            input_order += 1


def prepare(*, official_split: str, execution_commit: str) -> Mapping[str, Any]:
    """Construct and publish exactly one fixed GSM8K official split."""

    if not isinstance(official_split, str) or official_split not in _SOURCE_PATHS:
        raise Gsm8kConstructionError("official split must be train or test") from None
    return publish(
        _record_stream(_SOURCE_PATHS[official_split]),
        official_split=official_split,
        execution_commit=execution_commit,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kairos.gsm8k_construction")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--split", required=True, choices=("train", "test"))
    prepare_parser.add_argument("--execution-commit", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--split", required=True, choices=("train", "test"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            result = prepare(
                official_split=arguments.split,
                execution_commit=arguments.execution_commit,
            )
        else:
            result = verify(official_split=arguments.split)
    except (
        Gsm8kConstructionError,
        ConstructionAuditPersistenceError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ):
        print("GSM8K construction failed", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "Gsm8kConstructionError",
    "main",
    "prepare",
)
