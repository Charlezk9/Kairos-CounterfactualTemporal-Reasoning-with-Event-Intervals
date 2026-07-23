# Phase 03 Metrics Artifact Contract

- status: `COMPLETE / DEVELOPMENT_VERIFIED / PRODUCTION_USED`
- implementation_commit: `61e96bc58cd13bb4f5dc997ee678b86e81d9044a`
- date: 2026-07-23 CST

`src/kairos/metrics_artifacts.py` publishes derived transfer metrics without
modifying an immutable prediction run. Each target
`artifacts/derived-metrics/<run-id>` is a new 0700 directory containing only a
0600 canonical `metrics.json` and manifest-last `manifest.json`.

Before the target is created and again before its manifest is published, the
implementation verifies the full prediction artifact, reloads the frozen
dataset source and independently aggregates the fixed metric contract. It
binds the prediction execution commit, config/prediction/evidence/manifest
hashes, aggregation commit/time, parse counts and token-count summary. Offline
verification ignores stored metric authority and recomputes the values.

Verification evidence:

- focused suite: 8/8 passed;
- full repository suite: 465/465 passed in 13.916 seconds;
- GPU hidden and CPU threads fixed to two;
- no production sample content was emitted;
- tests cover no-replace, both Git gates, prediction change between gates,
  rehashed metric tampering, strict aggregation identity, modes, hardlinks and
  extra files.

The contract was production-used for the TORQUE Direct run. Its exact artifact
and replay evidence are recorded in `phase-03-torque-direct-baseline.md` and the
experiment registry.
