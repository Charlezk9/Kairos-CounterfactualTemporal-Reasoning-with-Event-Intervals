# Phase 03 TORQUE Self-Consistency Baseline

- status: `COMPLETE / VERIFIED / NO SUPPORTED DIFFERENCE FROM DIRECT`
- run_id: `20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`
- execution_commit: `b2f889b02893d99751ee9aabacdb3038a3456e1e`
- date: 2026-07-23 CST

## Frozen method

For each TORQUE public-dev question, the baseline draws eight independent CoT
samples from the fixed local Qwen2.5-7B-Instruct revision. Sampling is frozen at
temperature 0.7, top-p 0.9, top-k 0, `max_new_tokens=512`, and model seed 13.
The prompt contains no gold answer. Each sample must satisfy the existing strict
terminal JSON string-array contract.

Invalid samples are excluded from voting. Valid normalized span sets are grouped
by exact set equality; the plurality set wins, and a tie selects the earliest
valid sample. If all eight samples are invalid, the fixed sentinel prediction is
used. The raw eight-sample envelope, per-sample token counts and aggregate parse
status are retained only in the private evidence artifact. Offline verification
recomputes every vote from that envelope; no sample or model response is printed
or committed.

Implementation commits were `f6a43f36fc6d48014ca02b7d06dbaf297338b829`
for the frozen voting/evidence contract, `94fd0d7...` for batch-4 support and
`b2f889b...` for the final batch-8 execution setting. Focused tests finished at
8/8 and the full repository suite at 509/509 before the formal run.

## Preflight and resources

Token preflight covered all 1,483 records: input lengths were 155--336 tokens,
below the 32,768-token model context after reserving eight 512-token generations.
A four-record batch-4 GPU smoke generated 4,425 tokens in 19.55 seconds including
model load and peaked at 16,461,417,472 bytes. An eight-record batch-8 smoke
generated 8,264 tokens in 22.98 seconds including load and peaked at
17,652,922,368 bytes. Neither smoke retained an artifact.

The first intended formal attempt used batch 1 and was deliberately interrupted
before publication when the preflight showed avoidable under-utilization. It is
`INTERRUPTED_PREFLIGHT / NO ARTIFACT`, not a failed or partial formal run. No run
directory was created and GPU 4 was released before the batch changes were
committed and retested.

The final resource gate found 155 GiB free on `/data0` and 229 GiB system memory
available. Existing VLLM allocations on physical GPUs 1, 2, 3 and 6 were not
touched. The formal run used physical GPU 4, two CPU threads and a declared
32 GiB memory bound. GPU 4 remained near 20.1/24.6 GB and 67--68 C during the
run, and returned to 11 MiB/0% after exit.

## Formal execution

The clean execution commit ran from `2026-07-23T15:28:08Z` to
`2026-07-23T16:31:05Z`, exit 0. Generation took 3,778.678 seconds and peak GPU
allocation was 19,608,652,288 bytes. All 1,483 source-order questions were
published. Inputs were 155--336 tokens and all eight samples together generated
1,714,292 tokens.

Across 11,864 individual samples, 494 failed the strict parser (4.164%). At the
question level, 1,482 records had at least one valid sample and one record had all
eight invalid. Thus the prediction artifact has 1,482 `PARSED` records and one
`PARSE_ERROR` sentinel. Sample-level parser failures are not silently converted
to votes.

## Prediction and metric artifacts

Prediction path:
`/data0/hk_data/kairos-zx/artifacts/20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 764 | `f3846fed035d01f128ef46bb925ccba93237d704b6bbcd54285b6ac93cbd9788` |
| `predictions.jsonl` | 429,505 | `f7faf46cefbd39cab33a13ae24e36111a38869a4e973b8f0257ff9746324c646` |
| `generation-evidence.jsonl` | 10,340,467 | `5bde295df8e89bc210da14a44549d6af54e11772cdd937b7251158b89142da60` |
| `manifest.json` | 1,450 | `be449eeb3b2ebf954c3d8510122fb06111659fb28c2a9c86907f1061718e727f` |

Metrics path:
`/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`

- aggregation commit/time: `b2f889b02893d99751ee9aabacdb3038a3456e1e`,
  `2026-07-23T16:32:13Z`
- question set EM: `15.374241402562374%`
- question set F1: `15.569469864817137%`
- cluster exact and F1>=0.8 consistency: `1.926444833625219%`
- metrics SHA256:
  `22ec0d7628613195f94bec788a5599bdfed7c1891250faf0cfbb7be54f42f27b`
- metrics manifest SHA256:
  `7857e01aff7af1bd70afe316694b5b524839ba562680b230bf792d33688095ec`

The publisher rejected one first call at its format gate because `completed_at`
contained microseconds; it wrote no formal metrics file. A second call used the
required second-resolution UTC value. Independent CPU/offline processes then
replayed all votes, source bindings, prediction hashes and metric aggregation.

## Paired inference and conclusion

Comparison ID:
`paired-torque-dev-self-consistency-vs-direct-24cdd74c9d32`

| Metric (%) | Direct | Self-Consistency | Difference | 95% CI | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| Question set EM | 15.643965 | 15.374241 | -0.269724 | [-1.386965, 0.884971] | 0.682532 | 1.000000 |
| Question set F1 | 16.069850 | 15.569470 | -0.500380 | [-1.631558, 0.686951] | 0.395960 | 1.000000 |
| Cluster exact | 1.576182 | 1.926445 | +0.350263 | [-0.350263, 1.050788] | 0.442756 | 1.000000 |
| Cluster F1>=0.8 | 1.576182 | 1.926445 | +0.350263 | [-0.350263, 1.050788] | 0.442756 | 1.000000 |

Statistics path:
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-self-consistency-vs-direct-24cdd74c9d32`

- aggregation commit/time: `b2f889b02893d99751ee9aabacdb3038a3456e1e`,
  `2026-07-23T16:32:49Z`
- bootstrap: 571 contrast groups, 10,000 resamples, seed 20260723
- statistics SHA256:
  `8918c83b7a68e1c82e0c21d0eebac0eb3d3d43b220c439ef0095c54cc940baa8`
- manifest SHA256:
  `d1712be7a616c5b32083037fbf7087536db1f3f053a7a1ef7693e302269f0019`

A fresh process independently replayed the full comparison. All four confidence
intervals cross zero and all Holm-adjusted p-values are 1.0. Under this frozen
single-seed setup, eight-sample Self-Consistency has no supported difference from
Direct: it does not improve question EM/F1, while the sparse cluster increase is
also inconclusive. This retained negative result is a prompt-baseline finding,
not a Kairos effect claim and not a three-training-seed estimate.
