# Phase 01 GSM8K Relation-only Train Artifact

- status: `COMPLETE / VERIFIED DATA ARTIFACT / TRAIN ONLY`
- implementation_commit: `5f0b31ed27b9aa582259a61bfc0f4b7dd11cd578`
- stability_fix_commit: `3fbe53fe9aa4faec65b8c948857869dc85574e7f`
- branch: `experiment/reproduction-additional-evaluation`
- artifact_id: `PROC-P01-GSM8K-RELATION-ONLY-V1-20260723`
- production_run: one fixed official-train publication plus fresh offline replay
- active_run_ids: none

## Scope and non-claim

`kairos.relation_supervision_artifacts` publishes exactly one immutable
official-train artifact from the fixed GSM8K processed source. Its production
layout contains no test split and the CLI accepts no split or path argument.
Every verifier call reconstructs all 7,473 source records, regenerates retained
pairs in source order, and compares canonical JSONL and manifest bytes.

This artifact contains original numeric answers and original/inverted relation
labels. It contains no counterfactual answer. The manifest fixes
`counterfactual_answer_available=false` and
`counterfactual_answer_loss_masked=true`. Consequently it is a partial training
artifact, not evidence for counterfactual answer accuracy or the paper's full
updated-answer construction.

## Implementation verification

The persistence layer enforces a fixed source revision/SHA, official train
only, exact terminal coverage, unique identities, canonical source order,
bounded lines/total bytes, mode-0700 target, mode-0600/nlink-1 files,
manifest-last/no-replace publication, exact two-file namespace, clean Git gates
and offline source-lockstep replay. Failures preserve partial targets and never
repair or overwrite them.

- artifact-focused tests: 8/8 passed;
- combined relation/source-persistence tests: 27/27 passed in 0.277 seconds;
- final repository suite: 494/494 passed in 14.788 seconds;
- GPU hidden, CPU threads 2, all cache/temp paths project-local.

The earlier full-suite transient was traced to comparing read-updated atime in
the source hash stability gate. Commit `3fbe53f...` now binds device, inode,
mode, link count, owner, size, mtime and ctime while deliberately excluding
atime; its focused 11/11 and full 486/486 regression passed.

## Production gate and result

Immediately before publication, Git was clean at `5f0b31e...`, the target
observer returned `ABSENT`, `/data0` had 155 GiB free and memory had 229 GiB
available. GPUs 1/2/3/6 contained pre-existing VLLM workers and were not
touched; publication used no GPU and two CPU threads.

| Terminal | Count | Percent of 7,473 |
|---|---:|---:|
| `no_marker` | 5,628 | 75.311% |
| `extraction_rejected` | 1,475 | 19.738% |
| `rewrite_rejected` | 0 | 0.000% |
| `retained` | 370 | 4.951% |

All four identity sets contain 370 unique values. The output has 370 records,
785,369 bytes and maximum physical line size 3,543 bytes.

- JSONL SHA256: `525e3b09c6a6d03942a6bc3e03ebcd1722c3a68f4f224753dbc641f98465c12a`
- manifest SHA256: `4e22ff135d97c89ded50a54fc1007f25d9646db67ce112e4637d4e8c8b63674a`
- target: `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/relation-supervision-v1/explicit-marker-relation-only-v1/train`

A fresh process repeated full source replay and reproduced both hashes. The
target contains only `relation-supervision.jsonl` and its manifest; its parent
contains only `train`, so no relation-only test artifact was created.

## Next gate

Prepare a deterministic, train-only, stratified 200-pair human-audit packet
with blinded independent reviewer forms. No model training may start until two
human reviewers complete event/relation/grammar/non-target checks and the
agreement/validity thresholds in `docs/experiments/README.md` are evaluated.
