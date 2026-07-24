# Phase 03 Training Materialization Checkpoint

## Status

`COMPLETE / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`

- frozen parent: `f84f5cced755fa2f98e378a3417767ee4661cd95`
- contract commit: `db1ea5084efb54cf4e57f2e10f096d469d60e22d`
- implementation commit: `9a58155ed4cb608e5b5dbc7b2a5b804002a2571e`
- formal run IDs: none
- production artifacts: none

This checkpoint implements D-034 only. It did not read the production
relation-supervision JSONL, prompt predictions, reviewer templates, tokenizer
snapshot or 7B weights, did not use a GPU, and does not authorize production
candidate generation, plan publication or training.

## Candidate and corpus binding

`kairos.training_materialization` accepts typed in-memory `RelationOnlyPair`
objects and ordered generated proposals whose origins are limited to Direct,
CoT and Self-Consistency. It deduplicates exact UTF-8 content in first-seen
order, merges origins in D-031 canonical order, binds an already generated gold
candidate when present, and otherwise appends one gold-only final candidate.
Callers cannot claim `gold` provenance.

Each `BoundTrainingRecord` binds `example_id` to the pair ID, all source and
record IDs, the canonical pair SHA256, exact gold hash, candidate text hashes
and target. Corpus construction requires consecutive caller-supplied source
order, official train, one 40-hex revision and explicit source artifact and
manifest identities. It is an in-memory converter, not a production reader or
candidate generator.

## Token and target materialization

Only one D-031 micro-batch is materialized on demand, including explicit repeat
slots. A callable fast tokenizer must use right padding and return CPU integer
IDs, binary attention and valid full-coverage offsets without truncation.
Original and counterfactual queries use one-user chat formatting and shift the
two exact event spans into formatted text before overlap alignment. Candidate
texts use the fixed `<QUERY>/<CANDIDATE>` wrapper and canonical JSON string;
only the JSON answer span is pooled.

The result is an identity-bearing `MaterializedTrainingBatch`. Original and CF
2x2 relation targets include source-to-target and inverse target-to-source
labels with self cells `-100`. The answer target applies only to original
candidate scores. No counterfactual-answer target exists because relation-only
v1 explicitly withholds that answer. D-031 still rechecks example/candidate
IDs, masks and answer targets before any optimizer call.

## Immutable plan publisher

`kairos.training_plan_artifacts` writes only canonical `training-plan.json` and
manifest-last `manifest.json` under a private, allowed `/data0` root. Plan IDs
bind dataset, seed, micro-batch size and semantic plan SHA. Publication requires
clean HEAD equal to the corpus execution commit before plan creation and before
manifest publication, uses no-replace mode-0600 files, mode-0700 directories
and fsync, and preserves a plan-only partial if the second gate fails.

Offline verification requires an exact two-file namespace and private metadata,
parses canonical JSON, fully reconstructs the D-031 corpus/sampler/batches, and
checks semantic hash, file hash/bytes and all manifest facts. The public
production publisher was not called. Tests used new private temporary roots
under `/data0/hk_data/kairos-zx/.tmp` and cleaned them.

## Verification

- focused: 9/9 in 0.360 seconds
- full repository: 560/560 in 17.727 seconds
- full wall time: 21.23 seconds
- maximum RSS: 537,672 KiB
- environment: fixed project Conda, GPU hidden, CPU math threads two

Coverage includes candidate dedup/provenance order, generated versus injected
gold, source-order rejection, original/CF event and inverse relation targets,
variable candidate padding, explicit repeated slots, record/candidate mismatch,
left-padding refusal, plan no-replace, manifest/plan tampering, extra namespace,
private modes, independent replay and second-gate partial-state semantics.

## Remaining boundary

The generated proposal source and its prediction manifests are still absent for
the 370 production pairs. Both human reviewer templates remain blank, so the
audit thresholds cannot be computed. Consequently no production corpus or plan
may be built/published and no Kairos, Pair-MLP or Same-data SFT run may start.
The next safe implementation target is validation and aggregation of future
human audit submissions using synthetic filled fixtures only; AI must not fill,
infer or adjudicate the real reviewer fields.
