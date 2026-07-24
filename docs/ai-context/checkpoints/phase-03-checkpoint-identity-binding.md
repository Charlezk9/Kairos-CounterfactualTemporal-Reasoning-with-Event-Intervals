# Phase 03 Checkpoint Artifact Identity Binding

- status: `COMPLETE / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`
- implementation_commit: `1d80f5d4196a5a89cb1b465f162c5822c07534cb`
- frozen_contract_commit: `ee6667550f2e6f0b6f48ba8511a34d7a2b55fae1`
- date: 2026-07-24 CST
- PEFT/model load/production data/GPU/formal run: none

## Implemented binding

`kairos.training_execution.TrainingArtifactBinding` now binds every v2
checkpoint to:

- model ID `Qwen/Qwen2.5-7B-Instruct`;
- model revision `a09a35458c702b33eeacc393d103063234e8bc28`;
- local model `SHA256SUMS` file SHA256
  `3ee6c9510b7e50bfcd46d6df33cafa3e2019f13a6a09bf1d2f9e80cdfe1164e8`;
- bounded dataset ID, 40-hex dataset revision, split and data artifact ID;
- lowercase 64-hex immutable data-manifest SHA256;
- exact core type `kairos` or `pair-mlp`.

Config, state and manifest schemas were atomically advanced to v2 because no
formal v1 training checkpoint exists. Canonical config and manifest each carry
the same complete binding, and the verified result exposes its parsed value.
The state remains a restricted tensor/scalar/RNG/progress object and contains
no paths or arbitrary user objects.

Save derives the live core type before creating the checkpoint root. Resume
validates the live core and expected execution commit/config/artifact binding
before opening `state.pt`; only then does it perform the existing hash,
restricted-load and rollback-protected state restore. A binding mismatch thus
cannot mutate model, optimizer, scheduler or dataloader RNG state.

## Verification

- focused training-execution tests: 8/8 passed in 1.735 seconds;
- final full repository suite: 530/530 passed in 17.316 seconds (19.43 seconds
  wall time, 499,964 KiB maximum RSS);
- both Kairos and Pair-MLP retain exact CPU BF16 uninterrupted versus
  interrupted/resumed equivalence;
- tests cover binding round-trip, config tamper, expected data-manifest
  mismatch, live core mismatch before publication, state-read exclusion on
  expected mismatch, private namespace, no-replace and state hash tamper;
- `CUDA_VISIBLE_DEVICES` was empty and CPU math threads were fixed to two;
- all checkpoint fixtures were removed by test teardown.

The local environment has no `pytest`, so verification used the standard
library `unittest` runner already used by the repository. No dependency was
installed to change that.

## Remaining boundary

The binding records caller-supplied immutable identities; it does not itself
open or certify a production data manifest or rehash the complete 7B snapshot.
A future production runner must independently verify those artifacts before
constructing this binding. Deterministic production sampling, materialized
batches/candidates, CLI and formal run publication remain absent.

PEFT is absent from the fixed local environment and cache. The prior
environment contract requires separate user authorization before adding a
dependency, so no PEFT injection, 7B load or GPU smoke was attempted. D-023
also remains unchanged: production GSM8K training is blocked until two real
human submissions satisfy the frozen agreement and validity thresholds.
