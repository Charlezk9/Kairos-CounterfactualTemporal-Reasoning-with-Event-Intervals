# Phase 03 TimeQA-Hard CoT Baseline

- status: `COMPLETE / VERIFIED / DETERMINISTIC SINGLE RUN / FORMAT FAILURE`
- run_id: `20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`
- execution_commit: `50c6456cf91123868398ba66c35e4879f06196d4`
- date: 2026-07-23 CST

## Frozen run and resources

The run used all 989 `human_test.hard` records from revision
`38b05989070c1168b2bef3d5a2656afeeba763dc`, source SHA256
`0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`,
and fixed Qwen revision `a09a35458c702b33eeacc393d103063234e8bc28`.
Configuration was CoT greedy, seed 13, batch 1, `max_new_tokens=512`, full
32,768 context and no truncation.

Preflight observed 155 GiB free on `/data0`, 219 GiB available RAM and GPU 4
at 11 MiB/0%. Only physical GPU 4 ran from `2026-07-23T11:12:09Z` to
`2026-07-23T13:46:45Z`. Elapsed time was 9,262.608 seconds and peak allocated
GPU bytes were 20,210,055,680. GPU 4 returned to 11 MiB/0% after exit.

## Prediction artifact

Path: `/data0/hk_data/kairos-zx/artifacts/20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 563 | `99f5a0a0aa14934c5b63ed18e66a64e66d2acaaeab4924451043754412eee0fc` |
| `predictions.jsonl` | 261,534 | `1c738c4ed2eb03b32fd6d7026a3ce74af81bda706c9cb8611033abe242fa69a5` |
| `generation-evidence.jsonl` | 1,188,159 | `b8a48c76eab382be665eb87a481f565f9a4c2c9178207b032ea98eb513619813` |
| `manifest.json` | 1,434 | `d3f3d7538da5b431f10a1241eb9c41b7efdad61da0198ad91eddaacc5394aa82` |

Fresh CPU/offline replay verified all files, hashes, source order and 989-record
coverage. There are 20 parsed and 969 sentinel predictions, input lengths
603--24,597 tokens, and 226,010 generated tokens total. No raw output or sample
content was printed or committed.

## Metrics artifact and primary result

Path: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`

- aggregation commit/time: `50c6456cf91123868398ba66c35e4879f06196d4`, `2026-07-23T13:48:07Z`
- metrics JSON: 1,234 bytes, SHA256 `da4637f142c09cebd1f125e6987eb5648543f218f57ae5cb6570a4967dd81cc7`
- metrics manifest: 472 bytes, SHA256 `e7646799c75d3fa1f79a2e79fa64a8fbf0d07ab7271390169b1a7efa0ba734df`
- strict normalized exact match: `0.5055611729019212%`
- strict token F1: `0.5055611729019212%`

A separate fresh process reverified the prediction artifact and exactly
recomputed the metrics. The percentage corresponds to approximately five exact
answers; F1 has no additional partial-credit gain.

## Aggregate failure analysis and decision

Without printing values or unknown keys, parser errors aggregate to 907
non-string terminal JSON objects, 59 terminal-line violations and 3 invalid
JSON payloads. Seventeen outputs hit 512 generated tokens; only three used at
most 64. Truncation can affect a minority, but the dominant failure is still
the wrong terminal JSON type.

A whitelist structure audit found none of the 907 objects contained an
`answer`, `final_answer` or `FINAL_ANSWER` field. Defining first-value,
recursive or key-specific extraction after seeing test outputs would introduce
uncontrolled researcher degrees of freedom. D-019 therefore keeps the strict
0.506% primary result and defers post-hoc recovery. CoT's +0.506 percentage
point difference over Direct is descriptive only until paired inference.
