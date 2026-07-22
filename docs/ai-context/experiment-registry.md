# Experiment Registry

正式运行采用追加式登记。每个条目必须包含 run ID、状态、方法、数据集/split、数据 revision/SHA256、样本数、模型 revision、Git commit/dirty、配置哈希、seed、GPU、起止时间、退出状态以及预测/指标/checkpoint/日志路径与 SHA256。

当前无实验运行。

D-005-A 最小语义修订已经文档复审冻结；未创建 development/formal run 或 processed 工件。其唯一语义记录位于 `decisions.md` 和阶段检查点，因此不伪造 run ID。

## Development-only verification

| ID | Date | Scope | Git state | Result | Artifacts |
|---|---|---|---|---|---|
| `DEV-P01-UNIT-20260722` | 2026-07-22 | deterministic data core unit tests | staged tree later committed as `111bb99` | 27/27 passed after audit fixes | none |
| `DEV-P01-ARCHIVE-20260722` | 2026-07-22 | archive safety and full repository unit tests | staged tree committed as `c57a133` | 49/49 passed after three audit-remediation rounds; final audit approved | none |
| `DEV-P01-ACQUIRE-20260722` | 2026-07-22 | offline GSM8K acquisition finalization/verification helper | committed as `ca759ac` | 62 acquisition tests; 115/115 passed; fifth complete staged audit approved | none |

该条目不是正式 run，不产生可进入论文的数值；正式实验仍为空。

## Acquisition records

| ID | Status | Source revision | Provenance commit | Archive SHA256 | Integrity evidence | Artifacts |
|---|---|---|---|---|---|---|
| `ACQ-GSM8K-20260722` | `COMPLETE` | `3101c7d5072418e28b9008a6636bde82a006892c` | `482af857` | `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a` | offline verify exit 0; SHA256SUMS 15/15; 7,473 train / 1,319 test | `/data0/hk_data/kairos-zx/data/raw/gsm8k/` |

Acquisition records track source provenance and file integrity only. They are not model runs and do not contain paper metrics.
