# Phase 03 TimeQA-Hard Direct Baseline

- status: `COMPLETE / VERIFIED / DETERMINISTIC SINGLE RUN / FORMAT FAILURE`
- run_id: `20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`
- execution_commit: `709f712ff887ed7fa4ac8e7c183158977d1599a5`
- date: 2026-07-23 CST

## Frozen run and resources

The run evaluated all 989 records of fixed revision
`38b05989070c1168b2bef3d5a2656afeeba763dc`, source SHA256
`0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`.
It used `Qwen/Qwen2.5-7B-Instruct` revision
`a09a35458c702b33eeacc393d103063234e8bc28`, Direct greedy, seed 13, batch 1,
`max_new_tokens=128` and the full 32,768-token context without truncation.

Preflight observed 155 GiB free on `/data0`, 220 GiB available RAM and
physical GPU 4 at 11 MiB/0%. The run used only GPU 4 from
`2026-07-23T10:34:03Z` to `2026-07-23T11:05:35Z`, took 1,878.176 seconds and
recorded peak allocated GPU bytes 20,207,448,576. GPU 4 returned to 11 MiB/0%
after exit. Input lengths were 590--24,584 tokens.

## Prediction artifact

Path: `/data0/hk_data/kairos-zx/artifacts/20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 566 | `7ad791b6f907c328de6a0d8b0bcfcd751cf40a866c91281054ac5337dec05a4a` |
| `predictions.jsonl` | 264,974 | `54e3baf8142f4938a1e8547ea65f81983cb63164812cd6868a788c1ea4263f7a` |
| `generation-evidence.jsonl` | 350,636 | `d2ee6c732c7e37e145bd34aee7eed74f835fc01db6e80700453b43082fa17d62` |
| `manifest.json` | 1,439 | `1251a8e18164778d93ee7929b985cf7b4adf3067c9ddadc6c5b3ffbd6bb1dc82` |

The directory is 0700 and each file is 0600/regular/single-link. Fresh
CPU/offline replay verified all 989 records, source order and hashes. Only 3
responses passed the frozen parser; 986 use the fixed incorrect sentinel.
Total generated tokens were 8,998. No raw response or sample content was
printed or committed.

## Metrics artifact and primary result

Path: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`

- aggregation commit/time: `709f712ff887ed7fa4ac8e7c183158977d1599a5`, `2026-07-23T11:06:55Z`
- metrics JSON: 1,207 bytes, SHA256 `0e769343639e8cb785be1ee7e279b73f72b70386e324ba9df86550371f201eeb`
- metrics manifest: 475 bytes, SHA256 `e05b4c019b447d79c2b4696b664ff752137b44ba158a8b9e7b9f6f4045c3d1df`
- strict normalized exact match: `0.0%`
- strict token F1: `0.0%`

A separate fresh process reverified the bound prediction artifact and exactly
recomputed both metrics.

## Aggregate failure analysis

Without printing any raw response, the frozen parser errors aggregate to:

- 966 terminal JSON values that are not strings;
- 18 responses without exactly one terminal final-answer line;
- 2 invalid JSON payloads.

No record used all 128 allowed generated tokens, the maximum was 55, and 920
records used at most 16. The failure is therefore format/type adherence rather
than generation truncation. Because this was observed after the primary run,
the strict parser is not relaxed and the 0.0% result is retained. A future
scalar-coercion recovery may be reported only as an explicitly post-hoc
sensitivity analysis bound to the immutable raw evidence.
