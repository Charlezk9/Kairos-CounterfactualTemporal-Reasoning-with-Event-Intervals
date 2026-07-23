# Phase 03 TORQUE CoT+Verifier Baseline

- status: `COMPLETE / VERIFIED / NEGATIVE RESULT`
- run_id: `20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`
- execution_commit: `e09a40fa9e192bb92971be61e795cbfabcb3117d`
- date: 2026-07-23 CST

## Frozen method and inputs

The verifier receives only each TORQUE passage, question, the frozen Direct
candidate as index 0 and frozen CoT candidate as index 1. Gold annotations are
not serialized into the prompt. It reasons greedily and must end with the
strict JSON integer line `FINAL_ANSWER: 0` or `FINAL_ANSWER: 1`.

Direct and CoT inputs are bound by run and manifest SHA:

- Direct `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`, manifest
  `318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3`;
- CoT `20260723T100959Z-cot-torque-dev-s13-05e077299faf`, manifest
  `bbb32677f1903f9e736f25748036dea6d63eea39496139a693123e2d38f41fe5`.

Equivalent normalized candidate sets deterministically use Direct without a
model call. A malformed verifier index also falls back to Direct. These rules,
candidate order and both input hashes are in the immutable run config. The
implementation commit passed 6/6 focused tests and 477/477 full tests in
14.508 seconds before production.

## Resources and execution

Preflight found 503 equivalent records and 980 requiring generation; generated
prompt lengths were 193--514 tokens. `/data0` had 155 GiB free and system RAM
had 229 GiB available. Physical GPU 4 was idle at 11 MiB/0%.

Only physical GPU 4 ran from `2026-07-23T14:22:22Z` to
`2026-07-23T14:25:16Z`. Verifier generation took 166.261 seconds and peak GPU
allocation was 16,113,932,800 bytes. GPU 4 returned to 11 MiB/0% after exit.
Configuration was greedy, seed 13, batch 8, and `max_new_tokens=32`.

Of 1,483 records, 503 were equivalent/`NOT_APPLICABLE`; among 980 model calls,
218 indices parsed and 762 failed strict parsing and used the frozen Direct
fallback. The parsed selections chose Direct 79 times and CoT 139 times. Total
generated tokens were 26,248. No response or sample value was printed or
committed.

## Prediction and metric artifacts

Prediction path:
`/data0/hk_data/kairos-zx/artifacts/20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 912 | `5edec173ee357d62726f9d3996c6f1197be1aa5dede125d114336e807217445e` |
| `predictions.jsonl` | 415,093 | `a099360534dabae5c89362a243b6c726bd2c687ee645c85cccd8289bdf9a89bc` |
| `generation-evidence.jsonl` | 616,395 | `d5a3c7fdfca4dfa73e64d745ab66c584af3acbcfecad1b3f984c64516b51f8d2` |
| `manifest.json` | 1,440 | `7e84484e304b97e4abf45893ec94303ef479c08127a240cf9635ba8ad74dc5c6` |

Metrics path:
`/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`

- aggregation commit/time: `e09a40fa9e192bb92971be61e795cbfabcb3117d`,
  `2026-07-23T14:25:17Z`
- question set EM: `14.227916385704653%`
- question set F1: `14.680773635594946%`
- cluster exact and F1>=0.8 consistency: `1.4010507880910683%`
- metrics SHA256:
  `a3577a84fa3d0de0099fc68ce144cf108f3095f91ef396a9cb1e6f660286c430`
- metrics manifest SHA256:
  `9e84a5ac4ef77979e4ba699f78ef3579209b4ad3534a451fbaf278941e243e85`

A separate fresh CPU/offline process verified source order, input bindings,
permissions, hashes, prediction evidence and exact metric reaggregation.

## Paired inference and conclusion

Comparison ID:
`paired-torque-dev-cot-verifier-vs-direct-0089d1d05c23`

| Metric (%) | Direct | CoT+Verifier | Difference | 95% CI | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| Question set EM | 15.643965 | 14.227916 | -1.416049 | [-2.100292, -0.789971] | 0.000200 | 0.000800 |
| Question set F1 | 16.069850 | 14.680774 | -1.389076 | [-2.075488, -0.757659] | 0.000200 | 0.000800 |
| Cluster exact | 1.576182 | 1.401051 | -0.175131 | [-0.525394, 0.000000] | 0.758324 | 1.000000 |
| Cluster F1>=0.8 | 1.576182 | 1.401051 | -0.175131 | [-0.525394, 0.000000] | 0.758324 | 1.000000 |

Statistics path:
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-cot-verifier-vs-direct-0089d1d05c23`

- aggregation commit/time: `e09a40fa9e192bb92971be61e795cbfabcb3117d`,
  `2026-07-23T14:26:00Z`
- statistics SHA256:
  `fd2ae14c89ba876c0e95c4d417896d669dc4336bc4858948c5c86ff567f2cf44`
- manifest SHA256:
  `19f411f6378ccb3e6ab793fa0a5a437737cff1cd3c4dff973e3d84202a7a0b6d`

A fresh process independently replayed all 10,000 group resamples. The
verifier is significantly below Direct on both question metrics and does not
improve cluster consistency. The high strict-index failure rate is a method
limitation, not grounds to tune the parser after seeing dev results. This is a
retained negative Baseline and makes no claim about trained Kairos.
