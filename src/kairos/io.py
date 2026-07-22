"""Canonical JSONL I/O for strict temporal examples."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Iterable, List

from .ids import canonical_json
from .schema import TemporalExample


@dataclass(frozen=True)
class ConstructionOutcome:
    """Whether one raw example passed each ordered construction stage."""

    temporal_filtered: bool = False
    event_extraction_success: bool = False
    reliable_relation_label: bool = False
    valid_counterfactual: bool = False
    final_retained: bool = False

    def __post_init__(self) -> None:
        values = (
            self.temporal_filtered,
            self.event_extraction_success,
            self.reliable_relation_label,
            self.valid_counterfactual,
            self.final_retained,
        )
        if any(not isinstance(value, bool) for value in values):
            raise TypeError("construction outcomes must be booleans")
        if any(current and not previous for previous, current in zip(values, values[1:])):
            raise ValueError("construction outcome stages must form a retained prefix")


@dataclass(frozen=True)
class ConstructionFunnel:
    raw: int
    temporal_filtered: int
    event_extraction_success: int
    reliable_relation_labels: int
    valid_counterfactuals: int
    final_retained: int

    def __post_init__(self) -> None:
        counts = (
            self.raw,
            self.temporal_filtered,
            self.event_extraction_success,
            self.reliable_relation_labels,
            self.valid_counterfactuals,
            self.final_retained,
        )
        if any(isinstance(count, bool) or not isinstance(count, int) for count in counts):
            raise TypeError("funnel counts must be integers")
        if any(count < 0 for count in counts):
            raise ValueError("funnel counts must be non-negative")
        if any(later > earlier for earlier, later in zip(counts, counts[1:])):
            raise ValueError("funnel counts must be monotonically non-increasing")


def compute_funnel(outcomes: Iterable[ConstructionOutcome]) -> ConstructionFunnel:
    raw = temporal = events = relations = counterfactuals = retained = 0
    for outcome in outcomes:
        if not isinstance(outcome, ConstructionOutcome):
            raise TypeError("compute_funnel accepts only ConstructionOutcome values")
        raw += 1
        temporal += int(outcome.temporal_filtered)
        events += int(outcome.event_extraction_success)
        relations += int(outcome.reliable_relation_label)
        counterfactuals += int(outcome.valid_counterfactual)
        retained += int(outcome.final_retained)
    return ConstructionFunnel(raw, temporal, events, relations, counterfactuals, retained)


def write_examples(path: str | Path, examples: Iterable[TemporalExample]) -> None:
    """Atomically replace ``path`` with canonical, newline-terminated JSONL."""

    output = Path(path)
    if not output.parent.is_dir():
        raise FileNotFoundError(f"parent directory does not exist: {output.parent}")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        try:
            for example in examples:
                if not isinstance(example, TemporalExample):
                    raise TypeError("write_examples accepts only TemporalExample values")
                handle.write(canonical_json(example))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, output)


def read_examples(path: str | Path) -> List[TemporalExample]:
    examples: List[TemporalExample] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"blank JSONL line at {line_number}")
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("record is not a JSON object")
                examples.append(TemporalExample.from_dict(value))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid JSONL record at line {line_number}: {error}") from error
    return examples
