# Phase 03 TORQUE Direct Baseline

- status: `COMPLETE / VERIFIED / DETERMINISTIC SINGLE RUN / NO COMPARATIVE CI`
- run_id: `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`
- execution_commit: `eae442b850f0a1aa5cc27275717cf08b6de54bac`
- date: 2026-07-23 CST

## Frozen identities

- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`
- source SHA256: `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`
- coverage: 1,483 questions in source order; 571 `(passageID, cluster_id)` groups
- model: `Qwen/Qwen2.5-7B-Instruct`
- model revision: `a09a35458c702b33eeacc393d103063234e8bc28`
- method: Direct, greedy, batch 8, `max_new_tokens=128`, seed 13
- execution: `2026-07-23T09:47:48Z`--`2026-07-23T09:53:09Z`, 322.056 seconds, exit 0

## Resource and execution evidence

The mandatory preflight passed immediately before execution: physical GPU 4
was unused apart from 11 MiB display allocation, `/data0` had 156 GiB free and
host available memory was approximately 220 GiB. The run used only physical
GPU 4, declared four CPU threads, and peaked at 15,758,835,712 GPU bytes. GPU 4
returned to its pre-run idle state and the repository remained clean at the
exact execution commit after publication.

The full run produced 1,441 parsed responses and 42 strict-parser failures.
Failures were retained as raw generation evidence and converted to the frozen
sentinel; they count as incorrect. Input lengths ranged from 142 to 323 tokens,
and total generated tokens were 29,927. No sample prompt, gold, prediction or
raw response was printed or committed.

## Immutable artifact

Path:
`/data0/hk_data/kairos-zx/artifacts/20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`

The directory is mode 0700. All four exact files are mode 0600, regular and
single-link:

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 570 | `ec6ea450f14dea100f0d218cf3b543d12cb8a6c29f7b8a9b2f08b691613f7fb7` |
| `predictions.jsonl` | 398,816 | `6cc7298b769a45786f1cc844169f9e8c526ccfb5ace78f6a4d68c320a7003956` |
| `generation-evidence.jsonl` | 592,280 | `c85c0335051eaadce1ab57781203aabf421bd859aeca4eac620390e670ef8722` |
| `manifest.json` | 1,428 | `318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3` |

An independent CPU/offline verifier replayed the fixed adapter, source order,
coverage, schemas, permissions, links, canonical bytes and every hash. A second
aggregation from the verified prediction rows exactly reproduced:

| Metric | Percent |
|---|---:|
| question set exact match | 15.64396493594066 |
| question set F1 | 16.069849832493126 |
| cluster exact consistency | 1.5761821366024518 |
| cluster F1>=0.8 consistency | 1.5761821366024518 |

## Immutable metrics artifact

Implementation commit `61e96bc58cd13bb4f5dc997ee678b86e81d9044a`
published the independently reaggregated result at:

`/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`

The exact two files are mode 0600/single-link under 0700 directories. Metrics
completed at `2026-07-23T10:05:44Z`; `metrics.json` is 1,363 bytes with SHA256
`c508305a934eceac7defacd9c1d288562e6ab4dc3591d34b6c0bc9961a6e659a`, and
the 474-byte manifest SHA256 is
`1187e24dba51e8a48bfb0bdbbba4c7596c3231553685ddd06a7ace19f4cceae9`.
The manifest binds prediction manifest SHA
`318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3`.

The first production publish call supplied a mistyped expected commit and was
rejected by the initial clean-HEAD gate before creating the metrics root or
target. The successful retry used the exact HEAD above. A fresh CPU/offline
process then reverified both the prediction and metrics artifacts and exactly
reproduced the table.

## Interpretation

This is the independent reimplementation's prompt-only lower bound, not a
reproduction of an author-provided prompt. Its low cluster consistency means
the Direct output rarely answers every member of a contrast group correctly;
it does not yet support a comparison or an interval/graph improvement claim.

Prediction integrity, aggregation and machine-readable publication are
verified, so the descriptive values are `VERIFIED`. This remains one
deterministic seed/run; comparative confidence intervals and significance are
not available until another method produces paired predictions.
