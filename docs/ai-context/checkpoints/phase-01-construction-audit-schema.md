# Phase 01 Construction Audit Schema v1

- status: `FROZEN_BEFORE_IMPLEMENTATION / PLAN_ONLY`
- branch: `experiment/reproduction-additional-evaluation`
- base_head: `dcf841341f136b3aafcaea8b85e86e029373fde9`
- active_run_ids: none
- artifacts: none
- production_data_read: none

## Purpose and P1 boundary

This checkpoint is the unique detailed source for D-012. P1 adds a typed,
frozen, in-memory audit representation for one unconstructed input
`TemporalExample`, its caller-supplied order and its already computed D-011
`ConstructionResult`. It does not rerun construction, read a dataset, produce
JSONL, define a batch, create a manifest or publish an artifact.

Schema version and construction version are fixed literal strings:

```text
construction-audit-v1
explicit-marker-construction-v0
```

P1 uses only standard-library data structures plus existing Kairos types. It
adds no dependency, CLI, filesystem call, network/model/GPU operation,
registry entry or result entry. Persistence is explicitly deferred to a
separately frozen P2.

## Exact typed record and field order

The implementation type is exactly a non-representing frozen dataclass:

```python
@dataclass(frozen=True, repr=False)
class ConstructionAuditRecord:
    audit_record_id: str
    record_fingerprint_sha256: str
    schema_version: str
    construction_version: str
    input_order: int
    input: TemporalExample
    terminal: ConstructionTerminal
    outcome: ConstructionOutcome
    extraction_result: ExtractionResult
    rewrite_result: CounterfactualRewrite | ExtractionResult | None
    answer_update: AnswerUpdate | None
    template_id: str | None
    prospective_pair_id: str | None
    prospective_counterfactual_record_id: str | None
    original: TemporalExample | None
    counterfactual: TemporalExample | None
```

The top-level mapping has exactly those 16 keys in that field order. The
dataclass stores typed values, never a raw top-level or nested representation
mapping. `to_dict()` emits fresh containers in this order; parsing reconstructs
typed dataclasses, enums and tuples. Canonical JSON sorting, rather than mapping
insertion order, determines serialized bytes.

`input_order` must be an integer but not `bool`, in the inclusive range
`0..9223372036854775807`. It is the zero-based ordinal supplied by the caller
for a future canonical source stream. P1 does not assert cross-record
continuity or uniqueness; those are batch properties reserved for P2.

`input` must be a valid D-011 pre-construction `TemporalExample` with exact
empty tuples for `events` and `relations` and a null pair ID. The maker requires
`result.input_record_id == input.record_id`. The audit record does not add a
parallel source mapping: source ID, dataset, revision, split and source SHA are
carried once by the typed 13-key input.

## Stable audit identity

The maker computes `audit_record_id` only with the existing `make_stable_id`
and this exact namespace and payload:

```python
audit_record_id = make_stable_id(
    "construction-audit",
    {
        "schema_version": "construction-audit-v1",
        "construction_version": "explicit-marker-construction-v0",
        "dataset": input.dataset,
        "revision": input.revision,
        "source_id": input.source_id,
        "input_record_id": input.record_id,
        "source_sha256": input.source_sha256,
    },
)
```

The ID deliberately excludes order, terminal, outcome, extraction/rewrite
content, prospective/final IDs and every diagnostic. Re-running the same
construction version for the same source therefore retains identity while any
result drift changes the independent content fingerprint below.

## Full-record fingerprint

`record_fingerprint_sha256` is lowercase SHA256 hex computed with existing
`sha256_canonical` over a fresh primitive mapping produced by the explicit
audit serializer. That mapping is byte-for-byte equivalent in value to a fresh
`to_dict()` result with only `record_fingerprint_sha256` removed and therefore
contains exactly the other 15 top-level fields: `audit_record_id`, versions,
input order, input, terminal, outcome, full extraction/rewrite/update evidence,
prospective IDs, final records and all diagnostic text/details. The maker and
`from_dict()` must call the same private primitive-payload helper. Passing a
`ConstructionAuditRecord`, any other typed dataclass, enum graph or caller raw
mapping directly to `sha256_canonical` is forbidden.

Both the maker and `from_dict()` recompute the audit ID and fingerprint and
reject either mismatch. A changed free-text diagnostic therefore keeps the
stable audit ID but changes the record fingerprint and canonical bytes.

## Exact nested representation schemas

Every fixed mapping rejects missing or extra keys. Serialization and parsing
are explicit; `dataclasses.asdict` and permissive passthrough are forbidden.
Every JSON array is reconstructed as a tuple in the typed record.

### TemporalExample and common objects

The existing TemporalExample representation has exactly 13 keys:

```text
record_id
source_id
dataset
split
revision
source_sha256
text
question
answers
answer_type
events
relations
counterfactual_pair_id
```

Its nested `split` has exactly `official, internal`. Each event has exactly
`event_id, text, char_span`; each span has exactly `start, end`; and each
relation has exactly
`source_event_id, target_event_id, relation, marker, provenance`.

The `outcome` mapping has exactly:

```text
temporal_filtered
event_extraction_success
reliable_relation_label
valid_counterfactual
final_retained
```

Each extraction has exactly:

```text
text
marker
marker_span
event_a
event_b
relation
```

Each rejection has exactly `reason, message, details`. Each counterfactual
rewrite has exactly
`original_text, rewritten_text, original, rewritten, template_id`. Each answer
update has exactly `status, value, reason`.

### Tagged result unions

`extraction_result` always has exactly `kind, value`:

- `kind="extraction"` requires an extraction mapping as `value`;
- `kind="rejection"` requires a rejection mapping as `value`.

`rewrite_result` is null before the rewrite gate, otherwise it has exactly
`kind, value`:

- `kind="counterfactual_rewrite"` requires a rewrite mapping as `value`;
- `kind="rejection"` requires a rejection mapping as `value` and reconstructs
  a rejected `ExtractionResult`.

`answer_update` is null before the updater gate, otherwise it uses the exact
three-key answer mapping. `original` and `counterfactual` are null on every
non-retained terminal and typed 13-key examples only on `retained`. The three
template/prospective fields retain D-011's all-null/all-present matrix.

## Diagnostic domain, limits and deep freezing

`Rejection.details` is diagnostic, but it is included in canonical bytes and
the full-record fingerprint. The maker and parser must validate and deep-copy
it into a fresh immutable graph: objects become fresh read-only mapping
proxies, arrays become tuples, and no caller-owned mutable mapping or sequence
reference is retained. `to_dict()` returns a new ordinary mapping/list graph
on every call, so mutating emitted data cannot mutate the audit record.

The allowed diagnostic value domain is exactly null, bool, int, finite float,
string, array and string-key object. Non-finite floats, non-string mapping keys
and any other Python type are rejected. Every mapping key must itself be a
canonical JSON string key accepted by `canonical_json`.

Limits are evaluated on the complete details root:

- root depth is 0 and maximum permitted value-node depth is 16;
- node count includes the root plus every object value and every array item;
  object keys are not nodes; maximum count is 4,096;
- `len(canonical_json(details).encode("utf-8"))` must be at most 65,536 bytes.

The node, depth and byte gates run for both maker and parser. They are not
weakened because the input came from an existing `Rejection` object.

## Maker, parser and invariant checks

The public maker candidate is:

```python
make_construction_audit_record(
    *,
    input_order: int,
    input: TemporalExample,
    result: ConstructionResult,
) -> ConstructionAuditRecord
```

It must not call `construct_explicit_counterfactual`, an extractor, a rewriter
or an updater. It must not duplicate the D-011 prospective pair or
counterfactual-record ID formulas. Instead it validates typed fields, compares
the supplied input/result identities and crosslinks, deep-freezes diagnostics,
generates only the new audit ID and fingerprint, and constructs the typed
record.

Crosslink validation includes:

- input record ID equals `result.input_record_id`;
- versions are the fixed literals and audit ID is the exact formula above;
- the stored D-011 fields satisfy the exact terminal/outcome/optional matrix;
- successful rewrite/template/prospective fields agree with each other;
- final original/CF records are both absent or both present only for retained;
- retained original preserves input record/source/dataset/split/revision/SHA,
  text/question/answers/answer type, while its events/relation and shared pair
  ID agree with the result;
- retained CF inherits the required source fields and question/answer type,
  uses the prospective CF record and pair IDs, and agrees with the rewrite and
  known answer update.

The maker may construct a temporary typed `ConstructionResult` from the stored
fields to reuse its invariant checks; that is validation, not rerunning D-011.
`from_dict()` explicitly parses every nested object, deep-freezes details,
reconstructs the typed record, reruns the same crosslink checks, recomputes ID
and fingerprint, and rejects any mismatch. It never accepts an already-typed
audit record in place of a mapping and never stores the caller's raw mapping.

Canonical serialization is exactly
`canonical_json(record.to_dict())`. P1 adds no JSON text parser, newline, file
path or writer. A typed round trip must satisfy
`from_dict(record.to_dict()) == record`, and canonical bytes before and after
the round trip must be identical.

## Privacy and representation cost

The v1 record intentionally stores complete input `text`, `question` and
`answers`. A retained record additionally stores complete decorated original
and counterfactual `TemporalExample` values, so source fields and text may be
repeated. This duplication is deliberate for a self-contained audit contract,
but it makes every record sensitive, data-bearing and potentially large.

`repr=False` only prevents the dataclass-generated representation; it is not
access control, redaction, encryption or permission enforcement. P1 must not
print or log audit values, process real records, add real record contents to
Git, or run on production data. All implementation tests use synthetic
sentinels only. P1 may not silently replace the frozen full representation with
a delta/reference encoding to reduce size.

Before any persistence, P2 must separately freeze dataset-license and
attribution handling, access and permission rules, redaction/logging policy,
and exact per-line, record-count and total-byte bounds in addition to its
publication protocol. The P1 schema alone provides no authorization to retain
or redistribute data-bearing audit records.

## Synthetic test plan

The exact P1 code snapshot candidate is limited to:

- `src/kairos/construction_audit.py`
- `tests/test_construction_audit.py`

Tests use hand-authored inputs and the real D-011 constructor; no extractor,
rewriter or updater return value may be mocked. Required coverage includes:

1. all seven D-011 terminals through maker/to_dict/from_dict;
2. exact 16-key order and every nested exact key set;
3. missing/extra/null/type/enum and bool-as-int rejection;
4. input order boundaries 0 and 2^63-1, plus negative/overflow rejection;
5. both extraction tags and all rewrite null/tag variants;
6. arrays parsed to tuples and emitted as fresh lists/mappings;
7. audit ID exact payload, determinism and sensitivity to each bound source
   field, but insensitivity to order/result/free-text diagnostics;
8. fingerprint sensitivity to every other field including order and diagnostic
   text/details;
9. diagnostic domain, non-string keys, finite float, depth 16/17, node
   4,096/4,097 and UTF-8 byte 65,536/65,537 boundaries;
10. caller mapping/list mutation after maker/from_dict and emitted mapping/list
    mutation after `to_dict()` cannot alter the typed record or canonical bytes;
11. input/result mismatch, invalid D-011 optional matrix and every retained
    pair crosslink mismatch fail closed;
12. unchanged 13-key TemporalExample schema and byte-stable canonical round
    trip;
13. a runtime sentinel test proving both `repr(record)` and `str(record)` omit
    unique synthetic text, question, answer and diagnostic sentinels while
    `to_dict()` still contains each complete sentinel value; separate
    source/import inspection checks only that the module exposes no logging,
    filesystem, subprocess, network, JSONL or manifest API and cannot substitute
    for the runtime redaction test.

Only standard-library synthetic CPU tests are in scope. Future authorized test
execution must use the project-local Python, at most two CPU threads, disabled
GPU/online modes and a unique project-local temporary/cache directory. No
production data, model or persistent artifact may be read or created.

## Deferred P2 persistence boundary

P1 does not modify `schema.py`, `io.py`, `construction.py`, `__init__.py` or
dependencies. In particular, existing `io.write_examples()` accepts only
`TemporalExample` and atomically replaces an existing destination with
`os.replace`; it is not an immutable/no-replace audit publisher and must not be
reused for formal audit output.

Any JSONL writer/verifier requires a new P2 decision and checkpoint covering at
least batch order continuity and uniqueness, line/record/total-byte limits,
source artifact binding, new-target and no-follow path rules, no-replace
publication, fsync/crash semantics, failure preservation, canonical LF lines,
manifest-last completion, file bytes/count/SHA, terminal counts/funnel replay
and exact-directory verification. P1 creates no manifest schema and grants no
production CLI or publication authority.

## Authorization and next gate

This checkpoint authorizes only the four-document schema freeze. The next safe
action is for Agent 1 to submit an exact two-file implementation plan to Agent
2. Until a new explicit approval, do not modify code/tests, run tests, access
data or `/data0`, use network/model/GPU, modify registry/results, create an
artifact, or claim a construction run or paper result.
