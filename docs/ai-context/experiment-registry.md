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
| `DEV-P01-STRATEGYQA-ACQUIRE-20260723` | 2026-07-23 | fixed StrategyQA transfer/stage helper; offline synthetic verification only | committed as `978ba4d` | targeted 79/79; full 337/337; second staged audit approved | none |
| `DEV-P01-TEMPORAL-CONSTRUCTION-20260723` | 2026-07-23 | D-011 in-memory explicit-marker construction; synthetic verification only | committed as `24ce15d` | Agent 1 targeted 12/12 on the final reinforced snapshot; full 349/349 in 13.533s, exit 0; development verification passed | none |
| `DEV-P01-CONSTRUCTION-AUDIT-20260723` | 2026-07-23 | D-012 in-memory typed construction audit; synthetic verification only | commit `633618b6dc81503b7c5794380e8fa524f37c4c4c`, parent `2b7e3f03726fd1abf59fa18867593458f38e5b34`; source/test blobs `1bb1b167f3af5424b8fe199b2c9057c51638957f` / `3bfa86de8deb0b15ececad698808583acfe7aa45` | final fresh targeted 24/24 in 0.193s, exit 0; one full run 373/373 in 13.020s, exit 0; post-audit approved; ordinary push confirmed HEAD=origin=upstream | none |
| `DEV-P01-AUDIT-PERSISTENCE-20260723` | 2026-07-23 | D-013 immutable construction-audit JSONL/manifest publication and offline replay; synthetic verification only | clean commit `63737a3b0da741a5e4ee08ff32c2fd4b8dde7bc5` | focused 8/8; full 381/381 in 13.234s, exit 0; GPU disabled and two CPU threads | none |
| `DEV-P01-GSM8K-CONSTRUCTION-DRIVER-20260723` | 2026-07-23 | fixed D-011 → D-012 → P2 GSM8K driver and acquisition completion integration | driver `c8f5cecfccca1037a12660424ebcbc7a7dc70914`; effective fix `3944bb56d5c16a11482de39c5f0295936b6ac035` | driver focused 5/5 and full 386/386; completion-pair focused 10/10 and clean full 388/388 in 13.057s | none |
| `DEV-P01-TRANSFER-EVAL-20260723` | 2026-07-23 | fixed read-only TORQUE dev and TimeQA-Hard adapters plus frozen metrics | implementation `e89bbfd5c13792e51f69ceb21b4525efcc30736b`; effective empty-gold fix `8b57ffeb007dfb6e51d218c85f53011cce364f6e` | focused 13/13; full 401/401 in 13.033s; clean production read-only smoke verified 1,483 TORQUE QA/571 local contrast groups and 989 TimeQA-Hard records; no predictions or model metrics | none |
| `DEV-P01-PREDICTION-ARTIFACTS-20260723` | 2026-07-23 | immutable model-agnostic prediction JSONL/manifest publication and offline source replay | clean commit `f12efa05459daa982b4a5583abf22d48e38b9a1a` | focused 12/12; full 413/413 in 13.163s; real isolated clean-Git gate passed; production publish not called | none |

这些条目不是正式 run，不产生可进入论文的数值；正式模型实验仍为空。

## Acquisition records

| ID | Status | Source revision | Provenance commit | Archive SHA256 | Integrity evidence | Artifacts |
|---|---|---|---|---|---|---|
| `ACQ-GSM8K-20260722` | `COMPLETE` | `3101c7d5072418e28b9008a6636bde82a006892c` | `482af857` | `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a` | offline verify exit 0; SHA256SUMS 15/15; 7,473 train / 1,319 test | `/data0/hk_data/kairos-zx/data/raw/gsm8k/` |
| `ACQ-STRATEGYQA-20260723` | `STAGED_ARCHIVE_POLICY_BLOCKED` | `official-20210107` | `7eca38e` | `4911d85eb6721a93bed7645419df77e721808b32b9785dee14ad80e6249e0a90` | HTTP 200 and byte/SHA binding passed; official ZIP uses forbidden data descriptors; not extracted; manifest SHA `464a14091f047ccdd95d6036464176baa101f8cfc3c468ddac2a0d5964f47c0e` | `/data0/hk_data/kairos-zx/data/raw/strategyqa/official-20210107` |
| `ACQ-TORQUE-20260723` | `EXTRACTED_SCHEMA_OBSERVED` | `ab27019cc6a317fde3c879900499f02acce8b16d` | `7eca38e` | `7284c675f0cf21ddb1272c31919d4453d2fb53a426e88b46ad6a9a0fd9030cd0` | archive safety passed 28 members/22,163,721 bytes; dev 145 passages/1,483 QA; manifest SHA `e01f87df92daf0378ac126b83c3d596a01a04f281dc35567b305d720f70386e3` | `/data0/hk_data/kairos-zx/data/raw/torque/ab27019cc6a317fde3c879900499f02acce8b16d` |
| `ACQ-TIMEQA-20260723` | `EXTRACTED_SCHEMA_OBSERVED` | `38b05989070c1168b2bef3d5a2656afeeba763dc` | `7eca38e` | `f0df52a31e9d4bb0d5b7577d9e0131740bd017d2aad1e9b4bee7756bfecdfd07` | archive safety passed 40 members/454,095,594 bytes; hard JSONL 989 records; manifest SHA `8212a7826b0fadf6b0454f79c52bc6b3440d487af860c53456891efbec2e50a3` | `/data0/hk_data/kairos-zx/data/raw/timeqa/38b05989070c1168b2bef3d5a2656afeeba763dc` |
| `ACQ-2WIKI-20260723` | `TRANSFER_FAILED / NO_HTTP_RESPONSE` | `13800e5be57df1b4040b9b1588c6c811779e69e9` | `7eca38e` | none | corrected literal URL curl 28 at connect timeout; zero header bytes; no retry/fallback/mirror; manifest SHA `2013e6e465901c59c32719293e123e43ba4bfbaf0ac68bb003fe87248fd210db` | `/data0/hk_data/kairos-zx/data/raw/2wiki/13800e5be57df1b4040b9b1588c6c811779e69e9` |

Acquisition records track source provenance and file integrity only. They are not model runs and do not contain paper metrics.

## Acquisition policy blocks

| ID | Status | Source revision | Reason | Evidence | Artifacts |
|---|---|---|---|---|---|
| `POLICY-MUSIQUE-20260722` | `BLOCKED_POLICY` | `922ac98f19a201998dbdae6d7f2887a5258dbdeb` | `TRUSTED_ANCESTOR_CONFLICT` | fixed path contains 0775 ancestors rejected before stage/network; Agent 2 approved classification | none |

This table records local execution-policy state only. It must not be interpreted
as a source availability result, HTTP observation or paper experiment.

## Source planning gates

| ID | Status | Source label | Approved scope | Artifacts |
|---|---|---|---|---|
| `PLAN-STRATEGYQA-20260722` | `SOURCE_PLAN_APPROVED` | `official-20210107` | documentation plus exact transfer/stage-validator implementation plan; no code/network/data | none |
| `GATE-STRATEGYQA-REDIRECT-20260723` | `BLOCKED_TOOLING / NO_NATIVE_EXEC_ENV` | `official-20210107` | documentation-only gate; retained preparations are invalid/not executed and a native replacement-env process API plus fresh audited identity are required | none |
| `DISCOVERY-2WIKI-20260723` | `METADATA_ONLY / HEAD_NOT_ATTEMPTED` | `13800e5be57df1b4040b9b1588c6c811779e69e9` | fixed metadata only; no new 2026-07-23 request and corrected exact HEAD not run; historical 2026-07-22 HEAD timeout remains non-availability evidence; no body, data, acquisition or formal run | none |
| `PLAN-2WIKI-HEAD-20260723` | `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV` | `13800e5be57df1b4040b9b1588c6c811779e69e9` | planning-only exact corrected-URL HEAD disposition; unavailable native replacement-env launch; no execution, response, approval, record, data or formal run | none |
| `DISCOVERY-TORQUE-20260723` | `METADATA_ONLY / DOCUMENTS_READ` | `ab27019cc6a317fde3c879900499f02acce8b16d` | fixed README/LICENSE and primary-paper metadata only; no tree, data, evaluator, snapshot, acquisition or formal run | none |
| `PLAN-TORQUE-SNAPSHOT-20260723` | `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV` | `ab27019cc6a317fde3c879900499f02acce8b16d` | planning-only A/B/C snapshot disposition; no snapshot/acquisition request, approval, record, stage, archive, data, artifact or formal run | none |
| `DISCOVERY-TIMEQA-20260723` | `METADATA_ONLY / ROUTE_REJECTED` | `38b05989070c1168b2bef3d5a2656afeeba763dc` | fixed README/LICENSE plus arXiv landing metadata; ar5iv route rejected; no data, snapshot, acquisition or formal run | none |
| `PLAN-TIMEQA-PDF-20260723` | `BLOCKED_TOOLING / NO_PRE_FETCH_REDIRECT_AND_BYTE_GATES` | `arXiv:2108.06314` | planning-only direct official-PDF disposition; not executed and no accepted PDF-body evidence, approval, record, data or formal run | none |
| `PLAN-TIMEQA-SNAPSHOT-20260723` | `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV` | `38b05989070c1168b2bef3d5a2656afeeba763dc` | planning-only A/B/C snapshot disposition; sole candidate unverified/unexecuted; no request, approval, record, stage, snapshot, data, code, artifact or formal run | none |

Planning-gate entries are not acquisition records or model runs. In particular,
the StrategyQA gate has no active run ID and registers no formal run.
They are retained as historical dispositions. The later user-authorized manual
source actions are recorded in the acquisition table above and in D-014; those
records supersede the old `NO_NATIVE_EXEC_ENV` planning state without erasing it.

## Processed data artifacts

| ID | Status | Dataset revision | Execution commit | Counts | Artifact binding | Path |
|---|---|---|---|---|---|---|
| `PROC-P01-GSM8K-20260722` | `VERIFIED` | `3101c7d5072418e28b9008a6636bde82a006892c` | `3e34c9c6da06a0364b84ef97492331e59a764a45` | source/example train 7,473; test 1,319; duplicate statistics all 0 | manifest SHA256 `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`; one prepare and one offline verify exit 0; post-audit approved | `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/source-record-v1` |
| `PROC-P01-GSM8K-CONSTRUCTION-V0-20260723` | `VERIFIED / ZERO_RETAINED` | `3101c7d5072418e28b9008a6636bde82a006892c` | `3944bb56d5c16a11482de39c5f0295936b6ac035` | train raw/temporal/extracted/valid-CF/retained = 7,473/1,845/370/0/0; test = 1,319/361/79/0/0 | train audit/manifest SHA256 `a4b38dd3ba6b8b597732744af74b5e16fe464a98f2b8c1f6540fe04361cdb346` / `41edd3255de9e6b3c9f6df4a7d2ca9f05d6dc7ad33a65f2f7d3b044e8a15412f`; test `14393b5e2c8aace358babaaf38e37bd2d4e8fcbcdd52452127b3bf49b9f6a4e4` / `dda773ba105b59eb5d4e27fe8ea4ea0dcc2b661b4c639a2d3cd2ba297f9a129c`; independent offline replay passed | `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/construction-audit-v1/explicit-marker-construction-v0` |

`VERIFIED` in this table means the immutable processed data artifact passed replay verification. It is not a model metric and cannot by itself support a paper performance claim.
