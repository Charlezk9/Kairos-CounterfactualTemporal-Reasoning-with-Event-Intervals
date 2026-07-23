# Phase 01 GSM8K Relation-only Supervision v1

- status: `COMPLETE / DEVELOPMENT_VERIFICATION_PASSED`
- implementation_commit: `17137bbf6e666381c148d40b7249032ab1d3a0b6`
- parent_commit: `65989c2df27da3964e680891512f0659200b96da`
- branch: `experiment/reproduction-additional-evaluation`
- production_run: none
- active_run_ids: none

## Scope

`kairos.relation_supervision` defines an in-memory, fail-closed GSM8K
relation-supervision pair for the narrow case where the existing explicit-marker
extractor and counterfactual rewrite can deterministically prove an original
relation and its inverse. It preserves the original numeric answer only for the
original query. The counterfactual answer status is exactly
`unavailable-relation-only`; the schema has no counterfactual-answer field.

This is an independent-reimplementation bridge around construction v0's
verified zero-retained result. It is not a reconstruction of the paper's
unreleased temporal subset or answer updater, and it does not satisfy the
paper's reliable updated-answer requirement.

## Frozen contract

- Input must be an unannotated, numeric GSM8K `TemporalExample` with
  `text == question`, one original answer and no existing pair.
- Accepted pairs contain exactly two source-aligned event spans in each query,
  a known original relation and its deterministic inverse.
- Pair and counterfactual record identities bind construction version, source,
  original record and rewrite template.
- Deserialization rejects missing/extra keys, nested schema drift, invalid
  hashes/enums, stale identities, span drift and non-inverse relations, then
  replays extraction and rewrite from the original query.
- Rejected inputs terminate as `no_marker`, `extraction_rejected` or
  `rewrite_rejected`; rejected cases never emit a partial pair.
- The public schema deliberately cannot represent a counterfactual answer.

## Verification evidence

Only synthetic in-memory fixtures were used. No production train/test source,
model, GPU, JSONL target or experiment artifact was read or created.

- focused suite: 8/8 passed in 0.007 seconds;
- final full repository suite: 485/485 passed in 14.542 seconds;
- GPU hidden, CPU thread limits 2, caches/temp bound to the project-local
  `/data0/hk_data/kairos-zx` tree.

An earlier full-suite attempt passed 484 tests but the pre-existing construction
audit persistence test reported `bound input changed while reading`. Its
immediate isolated replay passed, the new focused suite passed again, and the
final fresh full suite above passed. The transient is retained here rather than
silently omitted; no relation-supervision assertion failed.

## Reporting and use boundary

This checkpoint is development verification only. It supplies neither a data
count nor a model result and cannot support counterfactual answer accuracy,
update, stability or consistency claims. Training must mask the counterfactual
answer loss for these pairs; only original-answer, original-relation and
counterfactual-relation supervision are in scope.

## Next gate

Implement a fixed train-only immutable JSONL/manifest publisher and independent
source-lockstep offline verifier. Freeze and test that persistence contract from
synthetic data at a clean commit before reading the production train funnel.
Do not read or publish the official test split, overwrite construction v0, or
start training until the train artifact and its limitations are recorded.
