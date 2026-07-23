# Phase 01 Explicit-Marker Temporal Construction v0

- status: `COMPLETE / DEVELOPMENT_VERIFICATION_PASSED`
- branch: `experiment/reproduction-additional-evaluation`
- staged_base_head: `62d1b21b39b4ceb05a83500c45181a3c1e1ac5e1`
- implementation_commit: `24ce15d40bd038d61bd6581ed2bc260072468c12`
- active_run_ids: none
- artifacts: none
- production_data_read: none

## Purpose and evidence boundary

This checkpoint is the unique detailed source for D-011. It freezes a minimal,
dependency-independent in-memory composition of the D-003 primitives already
implemented in `kairos.events`, `kairos.counterfactual`, `kairos.ids`,
`kairos.io` and `kairos.schema`. It does not reconstruct any paper subset and
does not claim that a GSM8K record is temporal. The verified GSM8K processed
manifest may establish source/example identity and schema only; neither its
records nor any `/data0` content was read to select this policy.

The approved documentation action modified no source or test, ran no test,
used no network, model, GPU or new dependency, and created no data, run or
experiment artifact. Implementation remains separately gated.

## Exact input contract

The future public construction function accepts exactly one `TemporalExample`.
A non-`TemporalExample` input raises `TypeError`. The input dataclass must
already satisfy its schema and additionally have `events == ()`,
`relations == ()` and `counterfactual_pair_id is None`; violation of any of
these three construction preconditions raises `ValueError`. Preconditions are
programmer errors, not terminal outcomes, and therefore do not create an
envelope or funnel observation.

No dataset name, split or answer type is special-cased. In particular, this v0
does not consume processed GSM8K and does not infer a temporal subset from its
manifest. The input `answers` must contain exactly one value to become a
retained pair; multiple answers are never resolved by selecting an arbitrary
element.

## Ordered construction gates

After the input preconditions pass, the function performs these gates in this
exact order:

1. Call `extract_explicit_relation(original.text)`. This occurs before the
   `text == question` check so that a no-marker input always terminates as
   `no_marker`.
2. If extraction is accepted, require its relation to be reliable. Every
   D-003 explicit relation except `Relation.UNKNOWN` is reliable;
   `Relation.UNKNOWN` is fail-closed and never reaches rewriting.
3. Reject `original.text == original.question` as
   `text_question_alias_unsupported`. The v0 rewrites only `text` and must not
   silently leave an aliased question with changed semantics.
4. Call `rewrite_counterfactual(extraction)`. The question is never rewritten.
5. Once rewriting succeeds, compute the prospective pair and counterfactual
   record IDs below, even if a later answer gate rejects retention.
6. Require `len(original.answers) == 1`; otherwise terminate as
   `multiple_answers_unsupported` without calling the updater.
7. Call `update_answer` with exactly `question=original.question`,
   `original_answer=original.answers[0]`, `answer_type=original.answer_type`
   and the successful rewrite. `UNKNOWN` terminates as
   `answer_update_unknown`; its free-text reason remains diagnostic only.
8. Only `KNOWN` creates both final named records and terminates as `retained`.

The stable terminal enum has exactly these values and never derives identity
from a free-text diagnostic:

```text
no_marker
extraction_rejected
text_question_alias_unsupported
rewrite_rejected
multiple_answers_unsupported
answer_update_unknown
retained
```

`no_marker` is reserved for `RejectionReason.NO_MARKER`. Every other rejected
`ExtractionResult` maps to `extraction_rejected`. A defensive accepted
extraction carrying `Relation.UNKNOWN` also maps to `extraction_rejected`; the
accepted `extraction_result` itself retains that `Relation.UNKNOWN` evidence.
Detailed extraction/rewrite `RejectionReason` values and `AnswerUpdate.reason`
are diagnostics carried only by the exact result fields below and must not
replace or extend the terminal enum.

## Funnel semantics

`ConstructionOutcome` is populated at the terminal boundary as follows:

| Terminal or condition | temporal | extraction | reliable relation | valid rewrite | final retained |
|---|---:|---:|---:|---:|---:|
| `no_marker` | false | false | false | false | false |
| other extraction rejection | true | false | false | false | false |
| defensive accepted `Relation.UNKNOWN` | true | true | false | false | false |
| `text_question_alias_unsupported` | true | true | true | false | false |
| `rewrite_rejected` | true | true | true | false | false |
| `multiple_answers_unsupported` | true | true | true | true | false |
| `answer_update_unknown` | true | true | true | true | false |
| `retained` | true | true | true | true | true |

Here `valid_counterfactual` means a complete invariant-checked marker rewrite,
not a usable answer label. `final_retained` means an atomic complete pair with
a `KNOWN` counterfactual answer. Unknown-answer paths emit neither a final
counterfactual nor a dangling final original.

## Exact prospective identities

After a rewrite succeeds, compute identities using the existing
`make_stable_id` and these literal namespaces and mappings:

```python
pair_id = make_stable_id(
    "counterfactual-pair",
    {
        "version": "explicit-marker-construction-v0",
        "source_id": original.source_id,
        "original_record_id": original.record_id,
        "template_id": rewrite.template_id,
    },
)
counterfactual_record_id = make_stable_id(
    "record",
    {
        "version": "counterfactual-explicit-marker-v0",
        "source_id": original.source_id,
        "original_record_id": original.record_id,
        "counterfactual_pair_id": pair_id,
        "template_id": rewrite.template_id,
        "variant": "counterfactual",
    },
)
```

These are prospective identities on both multiple-answer and unknown-answer
terminals. They do not make an unretained record publishable. Before rewrite
success, `template_id`, prospective pair ID and prospective counterfactual
record ID are all absent.

## In-memory envelope and retained records

The implementation introduces exactly `ConstructionTerminal(str, Enum)` with
the seven values frozen above and exactly this frozen envelope contract; field
order and annotated types are normative:

```python
@dataclass(frozen=True)
class ConstructionResult:
    input_record_id: str
    outcome: ConstructionOutcome
    terminal: ConstructionTerminal
    extraction_result: ExtractionResult
    rewrite_result: CounterfactualRewrite | ExtractionResult | None
    answer_update: AnswerUpdate | None
    template_id: str | None
    prospective_pair_id: str | None
    prospective_counterfactual_record_id: str | None
    original: TemporalExample | None
    counterfactual: TemporalExample | None
```

No additional diagnostic or payload field is permitted in v0. The optional
conditions are exact:

- `extraction_result` is always present. It is rejected on an extraction
  terminal and accepted from the extraction-success gate onward, including the
  defensive `Relation.UNKNOWN` case.
- `rewrite_result` is `None` on extraction failure, unreliable relation and
  alias rejection. A rewrite rejection stores its rejected `ExtractionResult`;
  rewrite success stores its `CounterfactualRewrite` on every later terminal.
- `answer_update` is `None` until the updater is actually called. It stores the
  returned `AnswerUpdate`, whether `UNKNOWN` or `KNOWN`, after that call.
- `template_id` and both prospective IDs are `None` before rewrite success and
  non-`None` from rewrite success onward.
- `original` and `counterfactual` are both non-`None` only for `retained` and
  are otherwise both `None`; partial final pairs are invalid.

The two final roles are represented only by the distinct named `original` and
`counterfactual` fields, never by list position. A successful rewrite and its
prospective IDs remain available on multiple-answer and unknown-answer
terminals. Rejection detail is available through the rejected result object;
an unknown-answer reason is available through `answer_update`; and a defensive
unknown relation is visible in the accepted `extraction_result`. The envelope
is an in-memory audit value only: no JSON schema, JSONL writer, manifest, CLI,
relation-only record or publication format is introduced.

For `retained`, construct both `TemporalExample` values atomically:

- The final original preserves the input `record_id`, `source_id`, `dataset`,
  `revision`, `split`, `source_sha256`, `text`, `question`, `answers` and
  `answer_type`; it adds the original extraction's two events, relation and the
  shared `counterfactual_pair_id`.
- The final counterfactual uses the exact prospective record ID, inherits
  `source_id`, `dataset`, `revision`, `split`, `source_sha256` and
  `answer_type`, sets only `text` to `rewrite.rewritten_text`, preserves
  `question` unchanged, sets `answers` to the singleton known updated value,
  adds the rewritten extraction's two events and relation, and uses the same
  pair ID.
- `source_sha256` is source provenance and is copied unchanged to both records;
  it is not recomputed from rewritten text.

## Implementation and test contract

The approved exact two-file implementation snapshot is
`src/kairos/construction.py` and `tests/test_construction.py`. The module uses
frozen dataclasses/enums, explicit dataclass construction and only Python's
standard library plus existing project modules. It adds no CLI, dependency,
filesystem call or dataset adapter.

Synthetic tests must cover:

1. input type and all three precondition failures;
2. no-marker precedence over `text == question`;
3. every extraction/rewrite terminal and exact funnel prefix;
4. defensive `Relation.UNKNOWN` fail-closed behavior;
5. alias rejection after accepted extraction and before rewriting;
6. multiple-answer rejection after successful rewrite, with updater not called;
7. numeric/free-generation and unsupported question updates remaining unknown;
8. retained extractive and yes/no pairs;
9. exact prospective ID payloads and determinism;
10. absence of prospective IDs before rewrite, and their preservation after a
    successful rewrite followed by answer rejection;
11. original/CF field inheritance, unchanged question and source SHA, exact
    events/relations, shared pair ID and preserved original record ID;
12. no partial final original or counterfactual on any rejected terminal.

Public-path tests must invoke the real extractor, rewriter and updater. They
must not mock or monkeypatch return values to manufacture an otherwise
unreachable public integration branch. Defensive unknown-relation behavior is
tested separately through the pure helper
`is_reliable_relation(extraction: Extraction) -> bool`, using a hand-built
`Extraction` whose relation is `Relation.UNKNOWN`; this is a helper unit test,
not a claimed public-path integration case. The multiple-answer test may prove
that the updater was not called only with a call-observation spy that does not
replace its return value, or by combining `answer_update is None` with static
inspection. It must not mock any path result.

All fixtures must be hand-authored and synthetic. They may not copy, inspect or
parameterize from raw or processed dataset records. Future test execution must
use the project-local Python and project-local cache/temp paths, consume CPU
only, use no GPU/model/network, and create no persistent artifact.

## Implementation verification and post-audit

The implementation was staged from clean parent commit
`62d1b21b39b4ceb05a83500c45181a3c1e1ac5e1` and committed as
`24ce15d40bd038d61bd6581ed2bc260072468c12`. Exact implementation Git blob
identities are:

- `src/kairos/construction.py`:
  `127831adb991caf1569b7dca6c48b0bf57ce25cb`
- `tests/test_construction.py`:
  `f12544f0e03d0f44de3608c8f1bd146a442eda75`

Agent 1 ran the synthetic targeted suite three times against the evolving
approved two-file snapshot: the initial implementation passed 12/12, the
exact empty-tuple precondition correction passed 12/12, and the audit-requested
identity/field-inheritance assertion reinforcement passed 12/12. This records
all three successful runs rather than presenting them as one run; the final
staged blob is covered by the third run.

The independently authorized full repository suite on the final staged
snapshot passed 349/349 in 13.533 seconds with exit 0. An earlier full-suite
launch attempt was rejected by execution preflight before a shell or test
process started; it is not a run and is excluded from test counts. All approved
tests used the project-local Python, CPU thread caps and disabled GPU/online
model access. Every exact temporary run directory was verified and removed;
post-audit found no residual process. No dataset, model, registry output,
prediction, metric, checkpoint or other persistent artifact was created.

Agent 2's pre-commit implementation and post-test audit verdict was
`POST_AUDIT_APPROVED / COMMIT_PENDING`. The exact audited blobs above are now
recorded in the implementation commit without any source/test change.

## Commit disposition and next planning gate

The exact two-implementation plus seven-document snapshot was committed by an
ordinary non-force commit as
`24ce15d40bd038d61bd6581ed2bc260072468c12` with parent
`62d1b21b39b4ceb05a83500c45181a3c1e1ac5e1`, then ordinarily pushed through
the project-only SSH configuration; local and remote branch heads matched.

The next safe action is planning only: draft a P1 construction
audit/persistence schema candidate for Agent 2 review. This completion does not
authorize code or test changes, data or `/data0` access, network, registry or
result changes, persistent construction output, an experiment artifact, a
formal run or any paper claim.
