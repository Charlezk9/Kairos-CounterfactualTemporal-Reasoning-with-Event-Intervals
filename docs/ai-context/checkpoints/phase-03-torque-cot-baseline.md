# Phase 03 TORQUE CoT Baseline

- status: `COMPLETE / VERIFIED / DETERMINISTIC SINGLE RUN / NEGATIVE RESULT`
- run_id: `20260723T100959Z-cot-torque-dev-s13-05e077299faf`
- execution_commit: `21b4eea6d0ba344454c06a56b8e1318fe16ddca5`
- date: 2026-07-23 CST

## Frozen run

The run used TORQUE public dev revision
`ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256
`7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`,
and all 1,483 questions / 571 groups in source order. The model was fixed
`Qwen/Qwen2.5-7B-Instruct` revision
`a09a35458c702b33eeacc393d103063234e8bc28`. Configuration was CoT greedy,
seed 13, batch 8 and `max_new_tokens=512`.

Mandatory resource preflight observed 156 GiB free on `/data0`, approximately
219 GiB available RAM, and physical GPU 4 at 11 MiB/0%. Execution ran only on
GPU 4 from `2026-07-23T10:09:59Z` to `2026-07-23T10:29:33Z`, took 1,167.092
seconds and peaked at 15,833,449,984 GPU bytes. After exit GPU 4 returned to
11 MiB/0%, and the repository remained clean.

The result contains 1,452 parsed outputs and 31 strict-parser failures, with
input lengths 155--336 tokens and 214,717 generated tokens total. Parse errors
use the fixed incorrect sentinel. No sample prompt, output, prediction or gold
was printed or committed.

## Prediction artifact

Path: `/data0/hk_data/kairos-zx/artifacts/20260723T100959Z-cot-torque-dev-s13-05e077299faf`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 557 | `05e077299faf65ee75d6a3be0879ed16c9911b9bf9b5b1f9498482bc2bb71b66` |
| `predictions.jsonl` | 422,474 | `900a3872e39e9201ec3686ed7a1e6971f8c7ee93b5576f2b6120af9d2375a563` |
| `generation-evidence.jsonl` | 1,502,501 | `9fa093f93025a138b1ecf1340633a7f3c73a4c925f9b6d7ffa5f92a446c9b3c4` |
| `manifest.json` | 1,423 | `bbb32677f1903f9e736f25748036dea6d63eea39496139a693123e2d38f41fe5` |

All files are 0600/regular/single-link under a 0700 directory. A fresh
CPU/offline process replayed source identity/order, coverage, schemas,
permissions and hashes before aggregation.

## Metrics artifact and result

Path: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T100959Z-cot-torque-dev-s13-05e077299faf`

- aggregation commit/time: `21b4eea6d0ba344454c06a56b8e1318fe16ddca5`, `2026-07-23T10:30:16Z`
- metrics JSON: 1,358 bytes, SHA256 `7c14f0d43a56cc87155c362df01a1700c76b4ee1f151ef4188abbb1a0499c6a2`
- metrics manifest: 471 bytes, SHA256 `f8af11f7e1919c1cc5e51a94cce556130a2024529f9304d5becf8c07393ae7a7`

| Metric | Percent |
|---|---:|
| question set exact match | 12.60957518543493 |
| question set F1 | 12.777831294351861 |
| cluster exact consistency | 1.2259194395796849 |
| cluster F1>=0.8 consistency | 1.2259194395796849 |

A separate fresh process reverified the prediction manifest bound by the
metrics manifest and exactly recomputed every value.

## Negative-result interpretation

Against the verified Direct run on the exact same records/model/seed, CoT is
3.034 percentage points lower in set EM and 3.292 points lower in set F1. Its
strict parse-error count is lower by 11, so formatting success alone does not
explain task performance. The prompt and generation budget are not retuned
after observing this result. These are deterministic descriptive differences;
paired bootstrap and a formal comparative conclusion remain pending.
