# Phase 03 First Development Training

## Status

`COMPLETE / FRESH REPLAY VERIFIED / DEVELOPMENT ONLY / NOT PAPER-ELIGIBLE`

This checkpoint records the first complete, replayable Kairos relation-only
training run. It is not a paper result: the input audit lacks provenance for
two independently working human reviewers, and relation-only v1 has no
counterfactual answer target.

## Frozen identities

- execution commit: `416dbd77314494c3bbd525bb4a8d0e25f5450583`
- run ID: `kairos-s13-416dbd7-attempt-01`
- experiment ID: `kairos-gsm8k-relation-s13-416dbd773144`
- seed: `13`
- run-input ID / manifest SHA256:
  `kairos-gsm8k-relation-s13-416dbd773144` /
  `b9dd459af4be9ee9b39447b4230888a49f9bfc503f5cadc81e48cea282df1606`
- plan ID / manifest / semantic SHA256:
  `training-plan-gsm8k-relation-only-v1-s13-mb1-2d14989edf6f` /
  `ad02839c99e885a66cdcc2945f2782dc2b743d4f142fb0728bb02a7239461643` /
  `2d14989edf6f47c569bc86bf782985503e60621520518ec76f90c0218c4f5b25`
- attempt resource-gate SHA256:
  `6e54101bdb2a1eaf6ad02972ce4b8e56a38b3bcda2bec00015156ca1b1477a23`
- model: `Qwen/Qwen2.5-7B-Instruct`, revision
  `a09a35458c702b33eeacc393d103063234e8bc28`
- selected device: physical GPU 5, UUID
  `GPU-1389a4f1-ca5a-d380-1de3-ebb3f55c9b29`, PCI
  `00000000:89:00.0`, NVIDIA GeForce RTX 3090

## Execution and diagnostics

- clean synchronized commit inspection and real-record materialization passed:
  330 train records, three fixed D-043 empty-pool records, 31 optimizer steps.
- one-step GPU smoke completed without artifact before plan publication.
- the attempt began at `2026-07-25T07:39:57Z` and finalization observed the
  released GPU at `2026-07-25T08:12:11Z`.
- micro-batch 1, gradient accumulation 32, 31 optimizer steps, 992 sample
  exposures = 990 real slots plus 2 deterministic repeat-padding slots.
- trace step 1 loss / gradient norm: `5.6595306396484375` /
  `48.517330169677734`.
- trace step 31 loss / gradient norm: `3.031139776110649` /
  `13.773099899291992`.
- the train command reported peak allocated / reserved CUDA bytes of
  `16983472128` / `17339252736`; these are operational diagnostics, not model
  performance metrics.
- D-043 was exercised only for the exact three train empty-pool identities.
  Internal-dev was not read for optimization or evaluation.

## Immutable outputs

Artifact root:
`/data0/hk_data/kairos-zx/artifacts/training-runs/kairos-s13-416dbd7-attempt-01`

- checkpoints: `step-000005`, `step-000010`, `step-000015`, `step-000020`,
  `step-000025`, `step-000030`, `step-000031`
- final checkpoint state SHA256:
  `d2e6fe9f435ff98cf3c5d954cca9d1927d1a4dfd03703e51fbfc6242859a0169`
- trace SHA256:
  `261a8d5a1e9a5be5df455268995e6446e6c7897a55076056709c7b07dc7104cc`
- run-config SHA256:
  `aa0a29c8b1a423abe7bad50826d28e00186d587f0a5c7c50be600cc5a4a4fbe4`
- final manifest SHA256:
  `f9314e4a3ea6afa9147146364560c21b57d3c0c258a3c1655429f9673fbbf1ce`
- recursive ancestry SHA256:
  `50118414502905754b9abb9ab74dc1d3a10481ba8fe890208061da7df2920655`
- artifact size: approximately 3.2 GiB; all files were verified as mode 0600
  with link count 1.

## Independent verification

Training returned
`TRAINING_PAYLOAD_COMPLETE / FINALIZATION_REQUIRED` with 31/31 steps and then
exited normally. A separate finalizer verified all seven checkpoint receipts,
full-trace prefixes, recursive ancestry and GPU release before publishing the
manifest last. A third fresh process ran `verify-run` and independently
returned `TRAINING_RUN_COMPLETE_DEVELOPMENT_ONLY` with the same final
checkpoint, manifest SHA256 and trace SHA256. Direct `sha256sum` checks of the
gate, run-input manifest, plan manifest, run-config, trace, final checkpoint
state and run manifest matched their registered values.

A separate strict read-only completion auditor cross-checked the manifests,
31-row trace, all seven checkpoint receipts and exact trace prefixes, recursive
ancestry, file type/mode/link constraints, post-resource evidence and every
eligibility statement in the repository documents. It returned `APPROVED`
with no P0/P1; the only P2 was to commit and normally push this documentation.

Post-finalization evidence recorded zero compute processes on the selected GPU,
24,243 MiB free, 220,474,875,904 available host bytes and 177,935,544,320 free
bytes on `/data0`. A later unrelated process from another user appeared on GPU
5; it was not inspected beyond process metadata and was not modified or ended.

## Interpretation boundary

The loss trace only proves that the frozen development optimization ran and
produced a replayable checkpoint chain. No internal-dev, TORQUE, TimeQA or
official-test metric has been computed from this checkpoint. It therefore does
not establish the paper's accuracy, counterfactual-answer or reviewer-response
claims. Evaluation requires a separately frozen plan and must retain the same
development-only eligibility label.
