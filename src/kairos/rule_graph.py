"""Gold-blind explicit-before/after constraint reranking for TORQUE."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

from .generation import MODEL_ID, MODEL_REVISION
from .ids import canonical_json
from .prediction_artifacts import (
    GenerationEvidence,
    PredictionArtifactError,
    RunSpec,
    VerifiedPredictionArtifact,
    make_run_id,
    publish_predictions,
    verify_predictions,
)
from .prompting import PromptError, parse_torque_response
from .self_consistency import (
    SelfConsistencyError,
    _parse_envelope,
    verify_self_consistency_predictions,
)
from .transfer_eval import TorqueExample, load_torque_dev, normalize_torque_span


METHOD_NAME = "rule-graph"
RULE_MODEL_ID = "deterministic-rule-graph"
RULE_MODEL_REVISION = "explicit-before-after-constraint-v1"
CONFIG_SCHEMA_VERSION = "torque-rule-graph-config-v1"
TRACE_SCHEMA_VERSION = "torque-rule-graph-trace-v1"
DIRECT_RUN_ID = "20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d"
DIRECT_MANIFEST_SHA256 = (
    "318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3"
)
COT_RUN_ID = "20260723T100959Z-cot-torque-dev-s13-05e077299faf"
COT_MANIFEST_SHA256 = (
    "bbb32677f1903f9e736f25748036dea6d63eea39496139a693123e2d38f41fe5"
)
SELF_CONSISTENCY_RUN_ID = (
    "20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d"
)
SELF_CONSISTENCY_MANIFEST_SHA256 = (
    "be449eeb3b2ebf954c3d8510122fb06111659fb28c2a9c86907f1061718e727f"
)
_CANDIDATE_SOURCES = ("direct", "cot") + tuple(
    f"self-consistency-{index}" for index in range(8)
)
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
_CUE = re.compile(r"\b(before|after)\b", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?;]+(?:[.!?;]|$)")
_NEGATION = re.compile(r"\b(?:not|never)\b|n't\b", re.IGNORECASE)
_UNSUPPORTED = re.compile(
    r"\b(?:start|starts|started|starting|begin|begins|began|begun|beginning|"
    r"end|ends|ended|ending|finish|finishes|finished|finishing|during|while|"
    r"simultaneous|already|future|might|may|could|should|would|if|want|wants|"
    r"wanted|intend|intends|intended|usually|often|expect|expects|expected)\b|"
    r"\bsame\s+time\b|\bused\s+to\b|\b(?:not|never)\b|n't\b",
    re.IGNORECASE,
)
_CONTENT_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "did",
        "do",
        "does",
        "was",
        "were",
        "is",
        "are",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "will",
        "happen",
        "happened",
        "event",
        "events",
        "thing",
        "things",
    }
)


class RuleGraphError(ValueError):
    """A fixed input, rule graph, trace, publication, or replay invariant failed."""


def _fail(message: str) -> None:
    raise RuleGraphError(message) from None


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, SequenceABC
    ):
        _fail(f"{name} must be a non-string sequence")
    return value


@dataclass(frozen=True)
class RuleGraphConfig:
    direct_run_id: str = DIRECT_RUN_ID
    direct_manifest_sha256: str = DIRECT_MANIFEST_SHA256
    cot_run_id: str = COT_RUN_ID
    cot_manifest_sha256: str = COT_MANIFEST_SHA256
    self_consistency_run_id: str = SELF_CONSISTENCY_RUN_ID
    self_consistency_manifest_sha256: str = SELF_CONSISTENCY_MANIFEST_SHA256

    def __post_init__(self) -> None:
        if (
            self.direct_run_id != DIRECT_RUN_ID
            or self.direct_manifest_sha256 != DIRECT_MANIFEST_SHA256
            or self.cot_run_id != COT_RUN_ID
            or self.cot_manifest_sha256 != COT_MANIFEST_SHA256
            or self.self_consistency_run_id != SELF_CONSISTENCY_RUN_ID
            or self.self_consistency_manifest_sha256
            != SELF_CONSISTENCY_MANIFEST_SHA256
        ):
            _fail("Rule-Graph upstream binding differs from D-032")

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "dataset": "torque-dev",
            "method": METHOD_NAME,
            "model_id": RULE_MODEL_ID,
            "model_revision": RULE_MODEL_REVISION,
            "seed": 13,
            "candidate_order": list(_CANDIDATE_SOURCES),
            "upstream": {
                "direct": {
                    "run_id": self.direct_run_id,
                    "manifest_sha256": self.direct_manifest_sha256,
                },
                "cot": {
                    "run_id": self.cot_run_id,
                    "manifest_sha256": self.cot_manifest_sha256,
                },
                "self_consistency": {
                    "run_id": self.self_consistency_run_id,
                    "manifest_sha256": self.self_consistency_manifest_sha256,
                    "source": "eight-raw-samples-not-plurality",
                },
            },
            "question_contract": "single-standard-before-after-v1",
            "anchor_contract": "longest-casefold-exact-word-ngram-v1",
            "graph_contract": "explicit-clause-before-transitive-closure-v1",
            "score": [
                "negative-contradiction-count",
                "support-count",
                "negative-unknown-count",
                "negative-candidate-index",
            ],
            "selection": "positive-support-best-set-else-direct-v1",
            "gold_access": False,
            "generation": "none",
            "trace_schema_version": TRACE_SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class _Word:
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class _Occurrence:
    node_id: int
    surface: str
    start: int
    end: int
    anchor: bool


@dataclass(frozen=True)
class _Query:
    cue: str
    anchor_surface: str
    anchor_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class RuleGraphExampleResult:
    prediction: list[str]
    trace: Mapping[str, Any]
    selected_source: str
    fallback_reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.prediction, list) or any(
            not isinstance(item, str) for item in self.prediction
        ):
            _fail("Rule-Graph prediction is invalid")
        if not isinstance(self.trace, MappingABC):
            _fail("Rule-Graph trace is invalid")
        encoded = canonical_json(self.trace).encode("utf-8")
        if not encoded or len(encoded) > 65_536:
            _fail("Rule-Graph trace exceeds its evidence limit")
        if self.selected_source not in _CANDIDATE_SOURCES:
            _fail("Rule-Graph selected source is invalid")
        if self.fallback_reason is not None and not isinstance(
            self.fallback_reason, str
        ):
            _fail("Rule-Graph fallback reason is invalid")


@dataclass(frozen=True)
class RuleGraphInputs:
    examples: tuple[TorqueExample, ...]
    candidates: Mapping[str, tuple[tuple[str, ...] | None, ...]]

    def __post_init__(self) -> None:
        if not self.examples or any(
            not isinstance(example, TorqueExample) for example in self.examples
        ):
            _fail("Rule-Graph examples are invalid")
        expected = tuple(example.record_id for example in self.examples)
        if len(set(expected)) != len(expected):
            _fail("Rule-Graph example IDs are duplicated")
        if not isinstance(self.candidates, MappingABC) or set(self.candidates) != set(
            expected
        ):
            _fail("Rule-Graph candidate coverage differs")
        for record_id in expected:
            values = self.candidates[record_id]
            if not isinstance(values, tuple) or len(values) != len(
                _CANDIDATE_SOURCES
            ):
                _fail("Rule-Graph candidate count differs")
            if values[0] is None or values[1] is None:
                _fail("Direct and CoT candidate sets must be present")
            for value in values:
                if value is not None and (
                    not isinstance(value, tuple)
                    or any(not isinstance(item, str) for item in value)
                ):
                    _fail("Rule-Graph candidate set is invalid")


@dataclass(frozen=True)
class RuleGraphRunResult:
    predictions: Mapping[str, list[str]]
    evidence: Mapping[str, GenerationEvidence]
    selected_source_counts: Mapping[str, int]
    fallback_counts: Mapping[str, int]


def _words(text: str) -> tuple[_Word, ...]:
    return tuple(
        _Word(match.group(0).casefold(), match.start(), match.end())
        for match in _WORD.finditer(text)
    )


def _reference_text(question: str, cue_match: re.Match[str]) -> str:
    prefix = question[: cue_match.start()]
    suffix = question[cue_match.end() :]
    if not _WORD.search(prefix):
        comma = suffix.find(",")
        if comma < 0:
            return ""
        return suffix[:comma]
    return suffix.rsplit("?", 1)[0]


def _query(example: TorqueExample) -> tuple[_Query | None, str | None]:
    question = example.question
    cues = tuple(_CUE.finditer(question))
    if len(cues) != 1:
        return None, "question-cue-count"
    if _UNSUPPORTED.search(question):
        return None, "unsupported-question-semantics"
    reference = _reference_text(question, cues[0])
    reference_words = _words(reference)
    passage_words = _words(example.passage)
    if not reference_words or not passage_words:
        return None, "anchor-text-empty"
    matches_by_length: dict[int, list[tuple[tuple[str, ...], int, int]]] = defaultdict(list)
    for size in range(len(reference_words), 0, -1):
        for start in range(len(reference_words) - size + 1):
            phrase = tuple(word.value for word in reference_words[start : start + size])
            if not any(value not in _CONTENT_STOP and len(value) >= 3 for value in phrase):
                continue
            for passage_start in range(len(passage_words) - size + 1):
                passage_phrase = tuple(
                    word.value
                    for word in passage_words[passage_start : passage_start + size]
                )
                if passage_phrase == phrase:
                    matches_by_length[size].append(
                        (
                            phrase,
                            passage_words[passage_start].start,
                            passage_words[passage_start + size - 1].end,
                        )
                    )
        if matches_by_length[size]:
            values = matches_by_length[size]
            phrase_classes = {item[0] for item in values}
            if len(phrase_classes) != 1:
                return None, "anchor-longest-class-ambiguous"
            spans = tuple(sorted({(item[1], item[2]) for item in values}))
            first_start, first_end = spans[0]
            return (
                _Query(
                    cue=cues[0].group(1).casefold(),
                    anchor_surface=example.passage[first_start:first_end],
                    anchor_spans=spans,
                ),
                None,
            )
    return None, "anchor-not-found"


def _literal_occurrences(text: str, surface: str) -> tuple[tuple[int, int], ...]:
    if not surface:
        return ()
    result = []
    start = 0
    while True:
        found = text.find(surface, start)
        if found < 0:
            break
        result.append((found, found + len(surface)))
        start = found + max(1, len(surface))
    return tuple(result)


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and (text[start].isspace() or text[start] in ",:()[]{}\"'"):
        start += 1
    while end > start and (
        text[end - 1].isspace() or text[end - 1] in ",:()[]{}\"'.!?;"
    ):
        end -= 1
    if start >= end or not _WORD.search(text[start:end]):
        return None
    return start, end


def _clause_relations(text: str) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
    relations: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for sentence_match in _SENTENCE.finditer(text):
        raw = sentence_match.group(0)
        cues = tuple(_CUE.finditer(raw))
        if len(cues) != 1 or _NEGATION.search(raw):
            continue
        cue = cues[0]
        before_text = raw[: cue.start()]
        after_text = raw[cue.end() :]
        has_prefix = bool(_WORD.search(before_text))
        if has_prefix:
            if "," in before_text or "," in after_text:
                continue
            left = _trim_span(
                text,
                sentence_match.start(),
                sentence_match.start() + cue.start(),
            )
            right = _trim_span(
                text,
                sentence_match.start() + cue.end(),
                sentence_match.end(),
            )
            if left is None or right is None:
                continue
            relation = (left, right) if cue.group(1).casefold() == "before" else (right, left)
        else:
            comma = after_text.find(",")
            if comma < 0 or "," in after_text[comma + 1 :]:
                continue
            subordinate = _trim_span(
                text,
                sentence_match.start() + cue.end(),
                sentence_match.start() + cue.end() + comma,
            )
            main = _trim_span(
                text,
                sentence_match.start() + cue.end() + comma + 1,
                sentence_match.end(),
            )
            if subordinate is None or main is None:
                continue
            relation = (
                (main, subordinate)
                if cue.group(1).casefold() == "before"
                else (subordinate, main)
            )
        relations.append(relation)
    return tuple(relations)


def _inside(occurrence: _Occurrence, span: tuple[int, int]) -> bool:
    return span[0] <= occurrence.start and occurrence.end <= span[1]


def _overlap(first: _Occurrence, second: _Occurrence) -> bool:
    return first.start < second.end and second.start < first.end


def _graph(
    example: TorqueExample,
    query: _Query,
    candidate_sets: Sequence[tuple[str, ...] | None],
) -> tuple[
    tuple[_Occurrence, ...],
    frozenset[tuple[int, int]],
    int,
]:
    surfaces: list[str] = []
    normalized: set[str] = set()
    for candidate in candidate_sets:
        if candidate is None:
            continue
        for surface in candidate:
            key = normalize_torque_span(surface)
            if key not in normalized:
                normalized.add(key)
                surfaces.append(surface)
    occurrences: list[_Occurrence] = []
    for start, end in query.anchor_spans:
        occurrences.append(
            _Occurrence(len(occurrences), query.anchor_surface, start, end, True)
        )
    for surface in surfaces:
        for start, end in _literal_occurrences(example.passage, surface):
            occurrences.append(
                _Occurrence(len(occurrences), surface, start, end, False)
            )
    edges: set[tuple[int, int]] = set()
    relations = _clause_relations(example.passage)
    for earlier_span, later_span in relations:
        earlier = [item for item in occurrences if _inside(item, earlier_span)]
        later = [item for item in occurrences if _inside(item, later_span)]
        for first in earlier:
            for second in later:
                if first.node_id != second.node_id and not _overlap(first, second):
                    edges.add((first.node_id, second.node_id))
    adjacency: dict[int, set[int]] = defaultdict(set)
    for first, second in edges:
        adjacency[first].add(second)
    closure: set[tuple[int, int]] = set(edges)
    for source in range(len(occurrences)):
        pending = list(adjacency[source])
        reached = set(pending)
        while pending:
            current = pending.pop()
            for target in adjacency[current]:
                if target not in reached:
                    reached.add(target)
                    pending.append(target)
        closure.update((source, target) for target in reached if source != target)
    return tuple(occurrences), frozenset(closure), len(edges)


def _deduplicate(candidate: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for surface in candidate:
        if not isinstance(surface, str) or not surface.strip():
            _fail("candidate span must be a non-empty string")
        key = normalize_torque_span(surface)
        if key not in seen:
            seen.add(key)
            values.append(surface)
    return values


def _unevaluated_candidate_traces(
    candidate_sets: Sequence[tuple[str, ...] | None],
) -> list[Mapping[str, Any]]:
    traces = []
    for index, (source, candidate) in enumerate(
        zip(_CANDIDATE_SOURCES, candidate_sets)
    ):
        available = candidate is not None
        spans = None if candidate is None else _deduplicate(candidate)
        traces.append(
            {
                "candidate_index": index,
                "source": source,
                "available": available,
                "spans": spans,
                "span_statuses": (
                    None if spans is None else ["not-evaluated"] * len(spans)
                ),
                "support_count": 0,
                "contradiction_count": 0,
                "unknown_count": 0,
                "score": None,
            }
        )
    return traces


def _candidate_trace(
    example: TorqueExample,
    query: _Query,
    occurrences: Sequence[_Occurrence],
    closure: frozenset[tuple[int, int]],
    source: str,
    candidate: tuple[str, ...] | None,
    index: int,
) -> Mapping[str, Any]:
    if candidate is None:
        return {
            "candidate_index": index,
            "source": source,
            "available": False,
            "spans": None,
            "span_statuses": None,
            "support_count": 0,
            "contradiction_count": 0,
            "unknown_count": 0,
            "score": None,
        }
    spans = _deduplicate(candidate)
    anchors = [item for item in occurrences if item.anchor]
    statuses: list[str] = []
    for surface in spans:
        nodes = [
            item
            for item in occurrences
            if not item.anchor and item.surface == surface
        ]
        desired = False
        inverse = False
        for node in nodes:
            for anchor in anchors:
                if _overlap(node, anchor):
                    continue
                if query.cue == "before":
                    desired = desired or (node.node_id, anchor.node_id) in closure
                    inverse = inverse or (anchor.node_id, node.node_id) in closure
                else:
                    desired = desired or (anchor.node_id, node.node_id) in closure
                    inverse = inverse or (node.node_id, anchor.node_id) in closure
        if desired and not inverse:
            statuses.append("support")
        elif inverse and not desired:
            statuses.append("contradiction")
        else:
            statuses.append("unknown")
    counts = Counter(statuses)
    support = counts["support"]
    contradiction = counts["contradiction"]
    unknown = counts["unknown"]
    score = [-contradiction, support, -unknown, -index]
    return {
        "candidate_index": index,
        "source": source,
        "available": True,
        "spans": spans,
        "span_statuses": statuses,
        "support_count": support,
        "contradiction_count": contradiction,
        "unknown_count": unknown,
        "score": score,
    }


def rerank_example(
    example: TorqueExample,
    candidate_sets: Sequence[tuple[str, ...] | None],
) -> RuleGraphExampleResult:
    """Select one frozen upstream answer set using explicit temporal constraints."""

    if not isinstance(example, TorqueExample):
        _fail("Rule-Graph example must be a TORQUE example")
    values = tuple(_sequence(candidate_sets, "candidate sets"))
    if len(values) != len(_CANDIDATE_SOURCES) or values[0] is None:
        _fail("Rule-Graph requires ten fixed candidate positions and Direct")
    for value in values:
        if value is not None and (
            not isinstance(value, tuple)
            or any(not isinstance(item, str) for item in value)
        ):
            _fail("Rule-Graph candidate set is invalid")
    direct = list(values[0])
    query, reason = _query(example)
    if query is None:
        trace = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "record_id": example.record_id,
            "query_status": "UNSUPPORTED",
            "fallback_reason": reason,
            "cue": None,
            "anchor_surface": None,
            "anchor_occurrence_count": 0,
            "direct_edge_count": 0,
            "closure_edge_count": 0,
            "candidates": _unevaluated_candidate_traces(values),
            "selected_candidate_index": 0,
            "selected_source": "direct",
        }
        return RuleGraphExampleResult(direct, trace, "direct", reason)
    occurrences, closure, direct_edges = _graph(example, query, values)
    traces = tuple(
        _candidate_trace(
            example,
            query,
            occurrences,
            closure,
            source,
            candidate,
            index,
        )
        for index, (source, candidate) in enumerate(zip(_CANDIDATE_SOURCES, values))
    )
    available = [trace for trace in traces if trace["available"]]
    best = max(available, key=lambda trace: tuple(trace["score"]))
    if best["support_count"] > 0:
        selected_index = best["candidate_index"]
        fallback = None
    else:
        selected_index = 0
        fallback = "no-positive-supported-candidate"
    selected = traces[selected_index]
    prediction = list(values[selected_index])
    trace = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "record_id": example.record_id,
        "query_status": "SUPPORTED_STANDARD",
        "fallback_reason": fallback,
        "cue": query.cue,
        "anchor_surface": query.anchor_surface,
        "anchor_occurrence_count": len(query.anchor_spans),
        "direct_edge_count": direct_edges,
        "closure_edge_count": len(closure),
        "candidates": list(traces),
        "selected_candidate_index": selected_index,
        "selected_source": selected["source"],
    }
    return RuleGraphExampleResult(
        prediction, trace, selected["source"], fallback
    )


def run_rule_graph(inputs: RuleGraphInputs) -> RuleGraphRunResult:
    if not isinstance(inputs, RuleGraphInputs):
        _fail("Rule-Graph inputs are invalid")
    predictions: dict[str, list[str]] = {}
    evidence: dict[str, GenerationEvidence] = {}
    selected = Counter()
    fallback = Counter()
    for example in inputs.examples:
        result = rerank_example(example, inputs.candidates[example.record_id])
        predictions[example.record_id] = result.prediction
        evidence[example.record_id] = GenerationEvidence(
            raw_response=canonical_json(result.trace),
            parse_status="NOT_APPLICABLE",
            input_token_count=0,
            generated_token_count=0,
        )
        selected[result.selected_source] += 1
        if result.fallback_reason is not None:
            fallback[result.fallback_reason] += 1
    return RuleGraphRunResult(
        predictions=predictions,
        evidence=evidence,
        selected_source_counts=dict(sorted(selected.items())),
        fallback_counts=dict(sorted(fallback.items())),
    )


def _validate_upstream(
    artifact: VerifiedPredictionArtifact,
    run_id: str,
    manifest_sha256: str,
    method: str,
) -> None:
    if (
        artifact.spec.run_id != run_id
        or artifact.manifest_sha256 != manifest_sha256
        or artifact.spec.dataset != "torque-dev"
        or artifact.spec.method_name != method
        or artifact.spec.model_id != MODEL_ID
        or artifact.spec.model_revision != MODEL_REVISION
        or artifact.spec.seed != 13
    ):
        _fail("Rule-Graph upstream artifact differs from D-032")


def load_fixed_inputs() -> RuleGraphInputs:
    """Verify all fixed upstream artifacts and replay ten gold-blind candidates."""

    try:
        direct = verify_predictions(DIRECT_RUN_ID)
        cot = verify_predictions(COT_RUN_ID)
        self_consistency = verify_self_consistency_predictions(
            SELF_CONSISTENCY_RUN_ID
        ).artifact
    except (PredictionArtifactError, SelfConsistencyError) as error:
        raise RuleGraphError("Rule-Graph upstream verification failed") from error
    _validate_upstream(
        direct, DIRECT_RUN_ID, DIRECT_MANIFEST_SHA256, "direct"
    )
    _validate_upstream(cot, COT_RUN_ID, COT_MANIFEST_SHA256, "cot")
    _validate_upstream(
        self_consistency,
        SELF_CONSISTENCY_RUN_ID,
        SELF_CONSISTENCY_MANIFEST_SHA256,
        "self-consistency",
    )
    examples = tuple(load_torque_dev())
    ids = tuple(example.record_id for example in examples)
    for artifact in (direct, cot, self_consistency):
        if tuple(record.record_id for record in artifact.records) != ids:
            _fail("Rule-Graph upstream source order differs")
    candidates: dict[str, tuple[tuple[str, ...] | None, ...]] = {}
    for index, example in enumerate(examples):
        direct_value = tuple(direct.records[index].prediction)
        cot_value = tuple(cot.records[index].prediction)
        try:
            responses, unused_input, unused_counts = _parse_envelope(
                self_consistency.evidence[index].raw_response
            )
        except SelfConsistencyError as error:
            raise RuleGraphError("Self-Consistency envelope replay failed") from error
        samples: list[tuple[str, ...] | None] = []
        for response in responses:
            try:
                samples.append(tuple(parse_torque_response(response)))
            except PromptError:
                samples.append(None)
        candidates[example.record_id] = (direct_value, cot_value, *samples)
    return RuleGraphInputs(examples, candidates)


def make_run_spec(
    execution_commit: str,
    started_at: str,
    completed_at: str,
) -> RunSpec:
    config = RuleGraphConfig().to_dict()
    run_id = make_run_id(started_at, METHOD_NAME, "torque-dev", 13, config)
    return RunSpec(
        run_id=run_id,
        dataset="torque-dev",
        method_name=METHOD_NAME,
        model_id=RULE_MODEL_ID,
        model_revision=RULE_MODEL_REVISION,
        execution_commit=execution_commit,
        seed=13,
        started_at=started_at,
        completed_at=completed_at,
        config=config,
        gpu_ids=(),
        cpu_threads=2,
        memory_gib=8,
        dataloader_workers=0,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish_rule_graph(
    execution_commit: str,
    started_at: str,
    completed_at: str,
    result: RuleGraphRunResult,
) -> VerifiedPredictionArtifact:
    if not isinstance(result, RuleGraphRunResult):
        _fail("Rule-Graph result is invalid")
    try:
        return publish_predictions(
            make_run_spec(execution_commit, started_at, completed_at),
            result.predictions,
            result.evidence,
        )
    except PredictionArtifactError as error:
        raise RuleGraphError("Rule-Graph prediction publication failed") from error


def verify_rule_graph(run_id: str) -> tuple[VerifiedPredictionArtifact, RuleGraphRunResult]:
    """Offline-replay the fixed inputs, every rule trace, and every prediction."""

    try:
        artifact = verify_predictions(run_id)
    except PredictionArtifactError as error:
        raise RuleGraphError("Rule-Graph prediction verification failed") from error
    if (
        artifact.spec.method_name != METHOD_NAME
        or artifact.spec.model_id != RULE_MODEL_ID
        or artifact.spec.model_revision != RULE_MODEL_REVISION
        or artifact.spec.seed != 13
        or artifact.spec.gpu_ids
        or artifact.spec.config != RuleGraphConfig().to_dict()
    ):
        _fail("Rule-Graph run spec differs from D-032")
    replay = run_rule_graph(load_fixed_inputs())
    expected_ids = tuple(replay.predictions)
    if tuple(record.record_id for record in artifact.records) != expected_ids:
        _fail("Rule-Graph output source order differs")
    for record, evidence in zip(artifact.records, artifact.evidence):
        expected_evidence = replay.evidence[record.record_id]
        if (
            record.prediction != replay.predictions[record.record_id]
            or evidence != expected_evidence
        ):
            _fail("Rule-Graph prediction or trace differs from replay")
    return artifact, replay


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "METHOD_NAME",
    "RULE_MODEL_ID",
    "RULE_MODEL_REVISION",
    "RuleGraphConfig",
    "RuleGraphError",
    "RuleGraphExampleResult",
    "RuleGraphInputs",
    "RuleGraphRunResult",
    "load_fixed_inputs",
    "make_run_spec",
    "publish_rule_graph",
    "rerank_example",
    "run_rule_graph",
    "utc_now",
    "verify_rule_graph",
]
