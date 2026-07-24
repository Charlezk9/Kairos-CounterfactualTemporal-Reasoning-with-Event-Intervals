# Phase 03 TORQUE Rule-Graph Baseline

- status: `COMPLETE / VERIFIED / EXACT SCORE TIE`
- run_id: `20260724T064739Z-rule-graph-torque-dev-s13-45fe8931e946`
- execution_commit: `dcc96b74634cc5b339da8e1fe21e5c2bb40c4866`
- statistics_commit: `fdc4f92132a4c2a72256297a4abddd05210dd265`
- date: 2026-07-24 CST

## Frozen gold-blind method

D-032 binds ten candidate positions: Direct, CoT and the eight raw
Self-Consistency samples. It never reads gold, never calls a model and never
constructs an answer from a union. Only one-cue standard `before/after`
questions are eligible. The parser derives exact-occurrence nodes and directed
before edges from conservative explicit clauses, computes transitive closure,
then scores each existing answer set by contradictions, supports, unknowns and
fixed candidate order. A candidate is selected only with positive support;
otherwise the exact Direct prediction is retained.

The implementation is `kairos.rule_graph`. Contract commit
`13dbbd9c258ffc75ca2659ef74dd02e5d0e6c960` preceded implementation commit
`dcc96b74634cc5b339da8e1fe21e5c2bb40c4866`. Focused tests passed 9/9 and the
then-full repository passed 549/549 in 17.638 seconds with GPU hidden. Tests
cover positive and inverse paths, transitivity, occurrence separation,
unsupported semantics, anchor ambiguity, candidate scoring, immutable
publication and complete upstream/trace replay.

## Formal CPU run and coverage

The clean production run used two CPU threads, declared 8 GiB memory, no GPU
and no dataloader worker. It ran from `2026-07-24T06:47:39Z` to
`2026-07-24T06:47:59Z`; rule execution and publication took 6.50 seconds with a
418,940 KiB observed maximum RSS. `/data0` had 144 GiB free and system memory
had 225 GiB available. Existing VLLM processes were not touched.

| Selected source | Count |
|---|---:|
| Direct | 1,475 |
| CoT | 5 |
| Self-Consistency sample 0 | 1 |
| Self-Consistency sample 4 | 1 |
| Self-Consistency sample 7 | 1 |

Eight predictions therefore differ from Direct. Conservative fallback reasons
sum to 1,465: question cue count 634, no positive supported candidate 465,
unsupported semantics 273, longest anchor-class ambiguity 74 and anchor not
found 19. The remaining supported cases can still select Direct by score.

## Immutable artifacts

Prediction path:
`/data0/hk_data/kairos-zx/artifacts/20260724T064739Z-rule-graph-torque-dev-s13-45fe8931e946`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 1,378 | `45fe8931e9462df5a6893c449c0489ff5d919c63bd2c04e2212ec8225ef8ef4f` |
| `predictions.jsonl` | 404,552 | `c46527bf093d59ca785ceda3deebcc7430db9407b36246bd0d7bd0e14aeede2c` |
| `generation-evidence.jsonl` | 4,853,033 | `c2d55beedd33881b9001b8a43fd99a5495b08ca0162751cb0cb718351bd1a88e` |
| `manifest.json` | 1,431 | `ff2eb5038675cc6cc135c834e948f0b6d48d3ca24979194fbcaedafbe4a34830` |

All 1,483 evidence records have `NOT_APPLICABLE` generation status and zero
tokens; they contain bounded canonical rule traces, not model output.

Metrics path:
`/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260724T064739Z-rule-graph-torque-dev-s13-45fe8931e946`

- aggregation commit/time: `dcc96b74634cc5b339da8e1fe21e5c2bb40c4866`,
  `2026-07-24T06:48:37Z`
- question set EM/F1: `15.64396493594066%` / `16.069849832493126%`
- cluster exact/F1>=0.8 consistency: `1.5761821366024518%` / `1.5761821366024518%`
- metrics/manifest SHA256: `f4d4d1a4023a10a04c113c98c86a9df8f090207ee03684085a0e2712bb3700b3` /
  `5ec53db717b48a8a1d7b3c2242e76fcbcacb67505994d043523ab71327ec2a70`

## Paired inference and conclusion

The generic statistics publisher initially rejected the cross-model identity
before creating any artifact. D-033 then froze a narrow exception that accepts
only a `rule-graph` candidate whose config binds the exact reference Direct run
and manifest. Commit `fdc4f92132a4c2a72256297a4abddd05210dd265`
implemented it; focused statistical tests passed 8/8 and the full suite passed
551/551. Unrelated cross-model and wrong-provenance comparisons remain rejected.

Comparison ID: `paired-torque-dev-rule-graph-vs-direct-cebd6cfa4ed5`

| Metric (%) | Direct | Rule-Graph | Difference | 95% CI | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| Question set EM | 15.643965 | 15.643965 | 0.000000 | [0.000000, 0.000000] | 1.000000 | 1.000000 |
| Question set F1 | 16.069850 | 16.069850 | 0.000000 | [0.000000, 0.000000] | 1.000000 | 1.000000 |
| Cluster exact | 1.576182 | 1.576182 | 0.000000 | [0.000000, 0.000000] | 1.000000 | 1.000000 |
| Cluster F1>=0.8 | 1.576182 | 1.576182 | 0.000000 | [0.000000, 0.000000] | 1.000000 | 1.000000 |

Statistics path:
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-rule-graph-vs-direct-cebd6cfa4ed5`

- aggregation commit/time: `fdc4f92132a4c2a72256297a4abddd05210dd265`,
  `2026-07-24T06:56:21Z`
- bootstrap: 571 contrast groups, 10,000 resamples, seed 20260723
- statistics/manifest SHA256: `ea5a5f8013b6aad3231ecfd51adafda863b6c281c62c9b7013e73a69c0cfcee4` /
  `3e26f09b111be9f5db702891e3d2c30a8f746d984b3063d8fd61a3de5be7296c`

A fresh process reverified all three upstream artifacts and raw SC envelopes,
recomputed every rule trace and prediction, replayed metrics, and reproduced all
10,000 bootstrap values and hashes. The eight changed predictions have exactly
zero per-record metric delta, explaining the degenerate zero intervals. This is
a verified no-improvement result for the deliberately conservative v1 rule
coverage; it neither supports a Kairos effect nor rejects constraint reasoning
in general.
