# Experiment Registry

正式运行采用追加式登记。每个条目必须包含 run ID、状态、方法、数据集/split、数据 revision/SHA256、样本数、模型 revision、Git commit/dirty、配置哈希、seed、GPU、起止时间、退出状态以及预测/指标/checkpoint/日志路径与 SHA256。

## Formal model runs

### `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / NO COMPARATIVE CI`
- method: deterministic greedy Direct; batch 8; `max_new_tokens=128`; no sampling
- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`, 1,483 questions / 571 contrast groups
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `eae442b850f0a1aa5cc27275717cf08b6de54bac`, seed 13, physical GPU 4, `2026-07-23T09:47:48Z`--`2026-07-23T09:53:09Z`, exit 0, 322.056 s, peak GPU bytes 15,758,835,712
- parse/token evidence: 1,441 parsed / 42 sentinel parse errors; input tokens 142--323; 29,927 generated tokens total
- replayed metrics: question set EM `15.64396493594066`; question set F1 `16.069849832493126`; cluster exact consistency `1.5761821366024518`; cluster F1>=0.8 consistency `1.5761821366024518` (all percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`
- SHA256: config `ec6ea450f14dea100f0d218cf3b543d12cb8a6c29f7b8a9b2f08b691613f7fb7`; predictions `6cc7298b769a45786f1cc844169f9e8c526ccfb5ace78f6a4d68c320a7003956`; generation evidence `c85c0335051eaadce1ab57781203aabf421bd859aeca4eac620390e670ef8722`; manifest `318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`; aggregation commit `61e96bc58cd13bb4f5dc997ee678b86e81d9044a`; completed `2026-07-23T10:05:44Z`; metrics SHA256 `c508305a934eceac7defacd9c1d288562e6ab4dc3591d34b6c0bc9961a6e659a`; metrics manifest SHA256 `1187e24dba51e8a48bfb0bdbbba4c7596c3231553685ddd06a7ace19f4cceae9`
- verification: fixed-source/order/schema/permission/link/hash replay passed in an independent CPU/offline process; immutable metrics publication reverified the prediction artifact before manifest and a fresh process independently reproduced all metrics. This validates the descriptive single-run values, not a cross-method confidence interval or significance claim.

### `20260723T100959Z-cot-torque-dev-s13-05e077299faf`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / NEGATIVE RESULT / NO COMPARATIVE CI`
- method: deterministic greedy CoT; batch 8; `max_new_tokens=512`; no sampling
- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`, 1,483 questions / 571 contrast groups
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `21b4eea6d0ba344454c06a56b8e1318fe16ddca5`, seed 13, physical GPU 4, `2026-07-23T10:09:59Z`--`2026-07-23T10:29:33Z`, exit 0, 1,167.092 s, peak GPU bytes 15,833,449,984
- parse/token evidence: 1,452 parsed / 31 sentinel parse errors; input tokens 155--336; 214,717 generated tokens total
- replayed metrics: question set EM `12.60957518543493`; question set F1 `12.777831294351861`; cluster exact consistency `1.2259194395796849`; cluster F1>=0.8 consistency `1.2259194395796849` (all percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T100959Z-cot-torque-dev-s13-05e077299faf`
- SHA256: config `05e077299faf65ee75d6a3be0879ed16c9911b9bf9b5b1f9498482bc2bb71b66`; predictions `900a3872e39e9201ec3686ed7a1e6971f8c7ee93b5576f2b6120af9d2375a563`; generation evidence `9fa093f93025a138b1ecf1340633a7f3c73a4c925f9b6d7ffa5f92a446c9b3c4`; manifest `bbb32677f1903f9e736f25748036dea6d63eea39496139a693123e2d38f41fe5`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T100959Z-cot-torque-dev-s13-05e077299faf`; aggregation commit `21b4eea6d0ba344454c06a56b8e1318fe16ddca5`; completed `2026-07-23T10:30:16Z`; metrics SHA256 `7c14f0d43a56cc87155c362df01a1700c76b4ee1f151ef4188abbb1a0499c6a2`; metrics manifest SHA256 `f8af11f7e1919c1cc5e51a94cce556130a2024529f9304d5becf8c07393ae7a7`
- verification: independent CPU/offline prediction replay and a separate metrics replay both passed. CoT is 3.034 percentage points lower in EM and 3.292 points lower in F1 than Direct; this negative result is retained without prompt retuning. Significance is not claimed before paired bootstrap.

### `20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / NEGATIVE FORMAT-FAILURE RESULT`
- method: deterministic greedy Direct; batch 1; `max_new_tokens=128`; no sampling; full 32,768 context with no truncation
- dataset: TimeQA-Hard `human_test.hard`, revision `38b05989070c1168b2bef3d5a2656afeeba763dc`, source SHA256 `0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`, 989 records
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `709f712ff887ed7fa4ac8e7c183158977d1599a5`, seed 13, physical GPU 4, `2026-07-23T10:34:03Z`--`2026-07-23T11:05:35Z`, exit 0, 1,878.176 s, peak GPU bytes 20,207,448,576
- parse/token evidence: 3 parsed / 986 sentinel parse errors; input tokens 590--24,584; 8,998 generated tokens total
- replayed metrics: normalized exact match `0.0`; token F1 `0.0` (percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`
- SHA256: config `7ad791b6f907c328de6a0d8b0bcfcd751cf40a866c91281054ac5337dec05a4a`; predictions `54e3baf8142f4938a1e8547ea65f81983cb63164812cd6868a788c1ea4263f7a`; generation evidence `d2ee6c732c7e37e145bd34aee7eed74f835fc01db6e80700453b43082fa17d62`; manifest `1251a8e18164778d93ee7929b985cf7b4adf3067c9ddadc6c5b3ffbd6bb1dc82`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`; aggregation commit `709f712ff887ed7fa4ac8e7c183158977d1599a5`; completed `2026-07-23T11:06:55Z`; metrics SHA256 `0e769343639e8cb785be1ee7e279b73f72b70386e324ba9df86550371f201eeb`; metrics manifest SHA256 `e05b4c019b447d79c2b4696b664ff752137b44ba158a8b9e7b9f6f4045c3d1df`
- verification: fresh prediction and metrics replays passed. Post-run aggregate-only error audit found 966 non-string JSON terminal values, 18 terminal-line violations and 2 invalid JSON responses; no output hit the 128-token limit and 920/989 used at most 16 generated tokens. The frozen strict result remains primary; any later scalar-coercion analysis must be explicitly post hoc and cannot replace it.

### `20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / NEGATIVE FORMAT-FAILURE RESULT`
- method: deterministic greedy CoT; batch 1; `max_new_tokens=512`; no sampling; full 32,768 context with no truncation
- dataset: TimeQA-Hard `human_test.hard`, revision `38b05989070c1168b2bef3d5a2656afeeba763dc`, source SHA256 `0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`, 989 records
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `50c6456cf91123868398ba66c35e4879f06196d4`, seed 13, physical GPU 4, `2026-07-23T11:12:09Z`--`2026-07-23T13:46:45Z`, exit 0, 9,262.608 s, peak GPU bytes 20,210,055,680
- parse/token evidence: 20 parsed / 969 sentinel parse errors; input tokens 603--24,597; 226,010 generated tokens total
- replayed metrics: normalized exact match `0.5055611729019212`; token F1 `0.5055611729019212` (percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`
- SHA256: config `99f5a0a0aa14934c5b63ed18e66a64e66d2acaaeab4924451043754412eee0fc`; predictions `1c738c4ed2eb03b32fd6d7026a3ce74af81bda706c9cb8611033abe242fa69a5`; generation evidence `b8a48c76eab382be665eb87a481f565f9a4c2c9178207b032ea98eb513619813`; manifest `d3f3d7538da5b431f10a1241eb9c41b7efdad61da0198ad91eddaacc5394aa82`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`; aggregation commit `50c6456cf91123868398ba66c35e4879f06196d4`; completed `2026-07-23T13:48:07Z`; metrics SHA256 `da4637f142c09cebd1f125e6987eb5648543f218f57ae5cb6570a4967dd81cc7`; metrics manifest SHA256 `e7646799c75d3fa1f79a2e79fa64a8fbf0d07ab7271390169b1a7efa0ba734df`
- verification: fresh prediction and metrics replays passed. Aggregate-only audit found 907 non-string JSON objects, 59 terminal-line violations and 3 invalid JSON responses; 17 outputs hit 512 tokens. Whitelist-shape audit found no `answer`, `final_answer` or `FINAL_ANSWER` field among the 907 objects, so no post-hoc recovery rule was selected. Strict primary remains unchanged.

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
| `DEV-P03-KAIROS-TENSOR-20260723` | 2026-07-23 | paper-aligned interval geometry/relation graph/candidate scorer plus Pair-MLP same-supervision baseline | clean commit `c178d150bbfc8d4626ea70cd4e91c3a7ead13ec6` | focused 14/14; full 427/427 in 13.087s; synthetic forward/loss/backward passed with GPU hidden | none |
| `DEV-P03-TRANSFER-GENERATION-20260723` | 2026-07-23 | deterministic Direct/CoT prompts, strict terminal JSON parsing, Qwen chat/span binding and resource-bounded greedy generation | prompts `994dfb8f34aaa9ae3fbaaecfc14a4beccdd1a0a0`; generation `f45c9e8c1adeee4f357ab7823ce1dbf287ff5d37`; effective sampling fix `eae442b850f0a1aa5cc27275717cf08b6de54bac` | focused generation 7/7; final full suite 457/457 in 13.355s; one-record GPU development smoke passed; no retained development artifact | none |
| `DEV-P03-METRICS-ARTIFACTS-20260723` | 2026-07-23 | immutable prediction-bound transfer metrics publication and independent reaggregation | clean commit `61e96bc58cd13bb4f5dc997ee678b86e81d9044a` | focused 8/8; full 465/465 in 13.916s; production Direct metrics publish plus fresh offline replay passed | production artifact registered under the formal run above |

这些 development 条目不是正式 run，不产生可进入论文的数值。

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
