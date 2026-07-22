# Experiment Registry

正式运行采用追加式登记。每个条目必须包含 run ID、状态、方法、数据集/split、数据 revision/SHA256、样本数、模型 revision、Git commit/dirty、配置哈希、seed、GPU、起止时间、退出状态以及预测/指标/checkpoint/日志路径与 SHA256。

当前无模型实验运行。

D-005/D-005-A 的语义与实现历史位于 `decisions.md` 和阶段检查点；完成的 production conversion 作为数据工件单独登记，不伪装成模型实验或论文指标。

## Development-only verification

| ID | Date | Scope | Git state | Result | Artifacts |
|---|---|---|---|---|---|
| `DEV-P01-UNIT-20260722` | 2026-07-22 | deterministic data core unit tests | staged tree later committed as `111bb99` | 27/27 passed after audit fixes | none |
| `DEV-P01-ARCHIVE-20260722` | 2026-07-22 | archive safety and full repository unit tests | staged tree committed as `c57a133` | 49/49 passed after three audit-remediation rounds; final audit approved | none |
| `DEV-P01-ACQUIRE-20260722` | 2026-07-22 | offline GSM8K acquisition finalization/verification helper | committed as `ca759ac` | 62 acquisition tests; 115/115 passed; fifth complete staged audit approved | none |
| `DEV-P01-GSM8K-ADAPTER-20260722` | 2026-07-22 | immutable GSM8K source-ledger/canonical-example adapter | committed as `892b486` | targeted 63/63; full 166/166; third staged audit approved after two remediation rounds | none |
| `DEV-P01-MUSIQUE-PROBE-20260722` | 2026-07-22 | fixed 65,536-byte MuSiQue response-body probe helper; offline synthetic verification only | committed as `cacbcbc` | targeted 92/92; full 258/258; fourth staged audit approved | none |

这些条目不是正式 run，不产生可进入论文的数值；正式模型实验仍为空。

## Acquisition records

| ID | Status | Source revision | Provenance commit | Archive SHA256 | Integrity evidence | Artifacts |
|---|---|---|---|---|---|---|
| `ACQ-GSM8K-20260722` | `COMPLETE` | `3101c7d5072418e28b9008a6636bde82a006892c` | `482af857` | `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a` | offline verify exit 0; SHA256SUMS 15/15; 7,473 train / 1,319 test | `/data0/hk_data/kairos-zx/data/raw/gsm8k/` |

Acquisition records track source provenance and file integrity only. They are not model runs and do not contain paper metrics.

## Processed data artifacts

| ID | Status | Dataset revision | Execution commit | Counts | Artifact binding | Path |
|---|---|---|---|---|---|---|
| `PROC-P01-GSM8K-20260722` | `VERIFIED` | `3101c7d5072418e28b9008a6636bde82a006892c` | `3e34c9c6da06a0364b84ef97492331e59a764a45` | source/example train 7,473; test 1,319; duplicate statistics all 0 | manifest SHA256 `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`; one prepare and one offline verify exit 0; post-audit approved | `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/source-record-v1` |

`VERIFIED` in this table means the immutable processed data artifact passed replay verification. It is not a model metric and cannot by itself support a paper performance claim.
