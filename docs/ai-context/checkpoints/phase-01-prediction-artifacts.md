# Phase 01 Prediction Artifact Contract

- status: `COMPLETE / DEVELOPMENT_VERIFIED`
- implementation_commit: `f12efa05459daa982b4a5583abf22d48e38b9a1a`
- date: 2026-07-23 CST
- formal_runs: none
- production_artifact_root_created: no

## Contract

`src/kairos/prediction_artifacts.py` defines the model-agnostic boundary between
generation and evaluation. A run is bound to one fixed TORQUE dev or TimeQA-Hard
source, complete official record-ID order, method/model revision, canonical
configuration hash, clean execution commit, seed, UTC start/end and bounded
resource declaration.

The stable run ID is
`<UTC>-<method>-<dataset>-s<seed>-<12-char-config-hash>`. A new mode-0700 run
directory contains only mode-0600 `config.json`, `predictions.jsonl` and
manifest-last `manifest.json`. Publication is exclusive/no-replace; a failure
before the manifest preserves an incomplete directory that cannot verify or be
reused. Git clean/HEAD gates run before directory creation and again before the
manifest.

TORQUE prediction values are string arrays and may be empty; TimeQA values are
strings and may be empty. Both require exact record-ID coverage and source order.
The offline verifier replays the fixed source adapter, hashes every file, checks
canonical JSON, exact nested manifest schemas, permissions/link count and every
record binding. It neither computes metrics nor executes a model.

## Verification

- focused synthetic suite: 12/12 passed
- full repository suite: 413/413 passed in 13.163 seconds
- real isolated clean-Git gate passed at exact commit `f12efa0...`
- tests cover missing/extra IDs, wrong prediction types, second-gate failure,
  no-replace, config/prediction/manifest tamper, rehashed record reordering,
  duplicate/noncanonical JSON, wrong record binding, extra/missing files,
  wrong mode, hardlink and symlink
- tests used only `/data0/hk_data/kairos-zx/.tmp`; GPU was hidden and CPU threads
  were fixed to 2

No production publish function was called, `/data0/hk_data/kairos-zx/artifacts`
was not created, and no run ID, prediction or metric was registered.

## Next gate

Implement the Kairos tensor architecture and minimum baseline interfaces using
only synthetic tensors/text. Do not publish formal predictions until the model
implementation, output parsing and evaluation runner pass their own clean-commit
tests and the resource gate is repeated.
