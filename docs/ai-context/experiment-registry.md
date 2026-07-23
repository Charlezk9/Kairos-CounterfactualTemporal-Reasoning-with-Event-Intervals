# Experiment Registry

正式运行采用追加式登记。每个条目必须包含 run ID、状态、方法、数据集/split、数据 revision/SHA256、样本数、模型 revision、Git commit/dirty、配置哈希、seed、GPU、起止时间、退出状态以及预测/指标/checkpoint/日志路径与 SHA256。

## Formal model runs

### `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / PAIRED COMPARISON AVAILABLE`
- method: deterministic greedy Direct; batch 8; `max_new_tokens=128`; no sampling
- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`, 1,483 questions / 571 contrast groups
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `eae442b850f0a1aa5cc27275717cf08b6de54bac`, seed 13, physical GPU 4, `2026-07-23T09:47:48Z`--`2026-07-23T09:53:09Z`, exit 0, 322.056 s, peak GPU bytes 15,758,835,712
- parse/token evidence: 1,441 parsed / 42 sentinel parse errors; input tokens 142--323; 29,927 generated tokens total
- replayed metrics: question set EM `15.64396493594066`; question set F1 `16.069849832493126`; cluster exact consistency `1.5761821366024518`; cluster F1>=0.8 consistency `1.5761821366024518` (all percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`
- SHA256: config `ec6ea450f14dea100f0d218cf3b543d12cb8a6c29f7b8a9b2f08b691613f7fb7`; predictions `6cc7298b769a45786f1cc844169f9e8c526ccfb5ace78f6a4d68c320a7003956`; generation evidence `c85c0335051eaadce1ab57781203aabf421bd859aeca4eac620390e670ef8722`; manifest `318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`; aggregation commit `61e96bc58cd13bb4f5dc997ee678b86e81d9044a`; completed `2026-07-23T10:05:44Z`; metrics SHA256 `c508305a934eceac7defacd9c1d288562e6ab4dc3591d34b6c0bc9961a6e659a`; metrics manifest SHA256 `1187e24dba51e8a48bfb0bdbbba4c7596c3231553685ddd06a7ace19f4cceae9`
- verification: fixed-source/order/schema/permission/link/hash replay passed in an independent CPU/offline process; immutable metrics publication reverified the prediction artifact before manifest and a fresh process independently reproduced all metrics. Its registered CoT-vs-Direct paired group-bootstrap comparison is listed below.

### `20260723T100959Z-cot-torque-dev-s13-05e077299faf`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / NEGATIVE RESULT / PAIRED COMPARISON AVAILABLE`
- method: deterministic greedy CoT; batch 8; `max_new_tokens=512`; no sampling
- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`, 1,483 questions / 571 contrast groups
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `21b4eea6d0ba344454c06a56b8e1318fe16ddca5`, seed 13, physical GPU 4, `2026-07-23T10:09:59Z`--`2026-07-23T10:29:33Z`, exit 0, 1,167.092 s, peak GPU bytes 15,833,449,984
- parse/token evidence: 1,452 parsed / 31 sentinel parse errors; input tokens 155--336; 214,717 generated tokens total
- replayed metrics: question set EM `12.60957518543493`; question set F1 `12.777831294351861`; cluster exact consistency `1.2259194395796849`; cluster F1>=0.8 consistency `1.2259194395796849` (all percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T100959Z-cot-torque-dev-s13-05e077299faf`
- SHA256: config `05e077299faf65ee75d6a3be0879ed16c9911b9bf9b5b1f9498482bc2bb71b66`; predictions `900a3872e39e9201ec3686ed7a1e6971f8c7ee93b5576f2b6120af9d2375a563`; generation evidence `9fa093f93025a138b1ecf1340633a7f3c73a4c925f9b6d7ffa5f92a446c9b3c4`; manifest `bbb32677f1903f9e736f25748036dea6d63eea39496139a693123e2d38f41fe5`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T100959Z-cot-torque-dev-s13-05e077299faf`; aggregation commit `21b4eea6d0ba344454c06a56b8e1318fe16ddca5`; completed `2026-07-23T10:30:16Z`; metrics SHA256 `7c14f0d43a56cc87155c362df01a1700c76b4ee1f151ef4188abbb1a0499c6a2`; metrics manifest SHA256 `f8af11f7e1919c1cc5e51a94cce556130a2024529f9304d5becf8c07393ae7a7`
- verification: independent CPU/offline prediction replay and a separate metrics replay both passed. CoT is 3.034 percentage points lower in EM and 3.292 points lower in F1 than Direct; the group-level paired comparison below supports both question-level negative differences after Holm correction. This negative result is retained without prompt retuning.

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

### `20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`

- status: `VERIFIED / DETERMINISTIC SINGLE RUN / NEGATIVE RESULT / PAIRED COMPARISON AVAILABLE`
- method: gold-free CoT+Verifier over fixed Direct index 0 and CoT index 1 candidates; greedy batch 8; `max_new_tokens=32`; normalized equivalent candidates skip generation; strict index parse error falls back to Direct
- upstream candidates: Direct manifest `318136467a25a6b3d70ef6c0a30a24698a125cc338eae3fadb6278324be833b3`; CoT manifest `bbb32677f1903f9e736f25748036dea6d63eea39496139a693123e2d38f41fe5`
- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`, 1,483 questions / 571 contrast groups
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `e09a40fa9e192bb92971be61e795cbfabcb3117d`, seed 13, physical GPU 4, `2026-07-23T14:22:22Z`--`2026-07-23T14:25:16Z`, exit 0, 166.261 s verifier generation, peak GPU bytes 16,113,932,800
- selection/token evidence: 503 equivalent/`NOT_APPLICABLE`; 218 parsed verifier indices; 762 parse-error Direct fallbacks; parsed choices Direct 79 / CoT 139; generated input tokens 193--514; 26,248 generated tokens total
- replayed metrics: question set EM `14.227916385704653`; question set F1 `14.680773635594946`; cluster exact consistency `1.4010507880910683`; cluster F1>=0.8 consistency `1.4010507880910683` (all percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`
- SHA256: config `5edec173ee357d62726f9d3996c6f1197be1aa5dede125d114336e807217445e`; predictions `a099360534dabae5c89362a243b6c726bd2c687ee645c85cccd8289bdf9a89bc`; generation evidence `d5a3c7fdfca4dfa73e64d745ab66c584af3acbcfecad1b3f984c64516b51f8d2`; manifest `7e84484e304b97e4abf45893ec94303ef479c08127a240cf9635ba8ad74dc5c6`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`; aggregation commit `e09a40fa9e192bb92971be61e795cbfabcb3117d`; completed `2026-07-23T14:25:17Z`; metrics SHA256 `a3577a84fa3d0de0099fc68ce144cf108f3095f91ef396a9cb1e6f660286c430`; metrics manifest SHA256 `9e84a5ac4ef77979e4ba699f78ef3579209b4ad3534a451fbaf278941e243e85`
- verification: fresh prediction/metrics replay passed. The registered paired comparison below shows significant negative question-level differences from Direct; the result remains untuned.

### `20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`

- status: `VERIFIED / STOCHASTIC SINGLE RUN / NO SUPPORTED DIFFERENCE / PAIRED COMPARISON AVAILABLE`
- method: 8-sample CoT Self-Consistency; temperature 0.7, top-p 0.9, top-k 0, batch 8, `max_new_tokens=512`; invalid samples excluded; normalized-set plurality with earliest-valid tie-break and all-invalid sentinel
- dataset: TORQUE public dev, revision `ab27019cc6a317fde3c879900499f02acce8b16d`, source SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`, 1,483 questions / 571 contrast groups
- model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`
- execution: clean commit `b2f889b02893d99751ee9aabacdb3038a3456e1e`, seed 13, physical GPU 4, `2026-07-23T15:28:08Z`--`2026-07-23T16:31:05Z`, exit 0, 3,778.678 s, peak GPU bytes 19,608,652,288
- parse/token evidence: 11,864 samples total, 494 invalid samples excluded; 1,482 questions with a valid vote / 1 all-invalid sentinel; input tokens 155--336; 1,714,292 generated tokens total
- replayed metrics: question set EM `15.374241402562374`; question set F1 `15.569469864817137`; cluster exact consistency `1.926444833625219`; cluster F1>=0.8 consistency `1.926444833625219` (all percentages)
- immutable artifact: `/data0/hk_data/kairos-zx/artifacts/20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`
- SHA256: config `f3846fed035d01f128ef46bb925ccba93237d704b6bbcd54285b6ac93cbd9788`; predictions `f7faf46cefbd39cab33a13ae24e36111a38869a4e973b8f0257ff9746324c646`; generation evidence `5bde295df8e89bc210da14a44549d6af54e11772cdd937b7251158b89142da60`; manifest `be449eeb3b2ebf954c3d8510122fb06111659fb28c2a9c86907f1061718e727f`
- metrics artifact: `/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`; aggregation commit `b2f889b02893d99751ee9aabacdb3038a3456e1e`; completed `2026-07-23T16:32:13Z`; metrics SHA256 `22ec0d7628613195f94bec788a5599bdfed7c1891250faf0cfbb7be54f42f27b`; metrics manifest SHA256 `7857e01aff7af1bd70afe316694b5b524839ba562680b230bf792d33688095ec`
- verification: a fresh CPU/offline process recomputed every vote from the eight-sample envelope and another process independently reaggregated metrics. The paired comparison below finds no supported difference from Direct. An earlier batch-1 attempt was interrupted before artifact creation for throughput preflight and is not a formal run.

## Formal statistical comparisons

### `paired-torque-dev-cot-vs-direct-43410b587f33`

- status: `VERIFIED / PAIRED GROUP BOOTSTRAP / NEGATIVE QUESTION-LEVEL RESULT`
- contrast: CoT minus Direct, same Qwen revision and model seed 13; 1,483 questions in 571 `(passage_id, cluster_id)` bootstrap units
- inference: 10,000 resamples, bootstrap seed 20260723, percentile 95% CI, two-sided bootstrap sign p-value with add-one correction, Holm family of four metrics
- results: question EM difference `-3.0343897505057313`, CI `[-4.410820779924873, -1.7088174982911826]`, raw/Holm p `0.00019998000199980003` / `0.0007999200079992001`; question F1 difference `-3.2920185381412654`, CI `[-4.673535185543669, -1.9538072463171003]`, raw/Holm p `0.00019998000199980003` / `0.0007999200079992001`; both cluster differences `-0.3502626970227669`, CI `[-1.2259194395796849, 0.5253940455341506]`, raw/Holm p `0.5629437056294371` / `1.0`
- artifact: `/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-cot-vs-direct-43410b587f33`; aggregation commit/time `db6efe20a6317edac47343d1c713e9f4ec51263b` / `2026-07-23T14:04:00Z`; statistics SHA256 `38646b8241d4c7a9985ca24a616261e393a301d42ff67dfeb7037f7d29b9044c`; manifest SHA256 `d1b08455308b8b3bb721aadde1abfafe626d3ebf93bb1fbc77cb68f5d0efeb7a`
- verification: publication replayed both prediction and metrics artifacts before create and before manifest; a separate fresh CPU/offline process reproduced all 10,000-resample values and both hashes. The result compares prompt baselines only and is not a Kairos effect claim.

### `paired-timeqa-hard-cot-vs-direct-a03673eba45e`

- status: `VERIFIED / PAIRED RECORD BOOTSTRAP / STRICT FORMAT-INTERACTION RESULT`
- contrast: CoT minus Direct, same Qwen revision and model seed 13; 989 record bootstrap units
- inference: 10,000 resamples, bootstrap seed 20260723, percentile 95% CI, two-sided bootstrap sign p-value with add-one correction, Holm family of two metrics
- results: normalized EM and token F1 differences both `0.5055611729019212`, CI `[0.10111223458038422, 1.0111223458038423]`, raw/Holm p `0.015198480151984802` / `0.030396960303969604`
- artifact: `/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-timeqa-hard-cot-vs-direct-a03673eba45e`; aggregation commit/time `db6efe20a6317edac47343d1c713e9f4ec51263b` / `2026-07-23T14:05:00Z`; statistics SHA256 `d1b5c7a908008fedbc0631965583d5d00861952b49347d19114ceceb555dab93`; manifest SHA256 `a44331e9ffa3c0a40e8d7e1e480e89af046a88107a3857f86853f2f98a4e823e`
- verification: separate fresh CPU/offline replay reproduced the values and hashes. The nonzero strict difference is driven by approximately five CoT exact answers against zero Direct exact answers while parse failures are 969/989 and 986/989; it is not evidence of improved temporal reasoning and no post-hoc recovery was used.

### `paired-torque-dev-cot-verifier-vs-direct-0089d1d05c23`

- status: `VERIFIED / PAIRED GROUP BOOTSTRAP / NEGATIVE QUESTION-LEVEL RESULT`
- contrast: CoT+Verifier minus Direct, same Qwen revision and model seed 13; 1,483 questions in 571 `(passage_id, cluster_id)` bootstrap units
- inference: 10,000 resamples, bootstrap seed 20260723, percentile 95% CI, two-sided bootstrap sign p-value with add-one correction, Holm family of four metrics
- results: question EM difference `-1.4160485502360078`, CI `[-2.1002921330920463, -0.789970984459874]`, raw/Holm p `0.00019998000199980003` / `0.0007999200079992001`; question F1 difference `-1.3890761968981806`, CI `[-2.0754880198472283, -0.7576592136002768]`, raw/Holm p `0.00019998000199980003` / `0.0007999200079992001`; both cluster differences `-0.17513134851138346`, CI `[-0.5253940455341506, 0.0]`, raw/Holm p `0.7583241675832417` / `1.0`
- artifact: `/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-cot-verifier-vs-direct-0089d1d05c23`; aggregation commit/time `e09a40fa9e192bb92971be61e795cbfabcb3117d` / `2026-07-23T14:26:00Z`; statistics SHA256 `fd2ae14c89ba876c0e95c4d417896d669dc4336bc4858948c5c86ff567f2cf44`; manifest SHA256 `19f411f6378ccb3e6ab793fa0a5a437737cff1cd3c4dff973e3d84202a7a0b6d`
- verification: a separate fresh CPU/offline process reproduced all values and both hashes. Extra verifier inference did not improve the frozen candidate baseline and no parser/prompt retuning followed.

### `paired-torque-dev-self-consistency-vs-direct-24cdd74c9d32`

- status: `VERIFIED / PAIRED GROUP BOOTSTRAP / NO SUPPORTED DIFFERENCE`
- contrast: Self-Consistency minus Direct, same Qwen revision and model seed 13; 1,483 questions in 571 `(passage_id, cluster_id)` bootstrap units
- inference: 10,000 resamples, bootstrap seed 20260723, percentile 95% CI, two-sided bootstrap sign p-value with add-one correction, Holm family of four metrics
- results: question EM difference `-0.26972353337828636`, CI `[-1.3869648422398804, 0.8849708229847362]`, raw/Holm p `0.6825317468253175` / `1.0`; question F1 difference `-0.5003799676759897`, CI `[-1.631558074345781, 0.686950651460567]`, raw/Holm p `0.395960403959604` / `1.0`; both cluster differences `0.35026269702276713`, CI `[-0.3502626970227671, 1.0507880910683012]`, raw/Holm p `0.44275572442755723` / `1.0`
- artifact: `/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-self-consistency-vs-direct-24cdd74c9d32`; aggregation commit/time `b2f889b02893d99751ee9aabacdb3038a3456e1e` / `2026-07-23T16:32:49Z`; statistics SHA256 `8918c83b7a68e1c82e0c21d0eebac0eb3d3d43b220c439ef0095c54cc940baa8`; manifest SHA256 `d1712be7a616c5b32083037fbf7087536db1f3f053a7a1ef7693e302269f0019`
- verification: a fresh CPU/offline process replayed all 10,000 resamples and reproduced both hashes. No interval excludes zero, so the single-seed result supports neither benefit nor harm relative to Direct.

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
| `DEV-P03-STATISTICAL-ARTIFACTS-20260723` | 2026-07-23 | immutable two-run paired bootstrap, intervals and Holm-adjusted inference | clean commit `db6efe20a6317edac47343d1c713e9f4ec51263b` | focused 6/6; full 471/471 in 14.807s; both production comparisons passed fresh offline replay | production artifacts registered under formal comparisons above |
| `DEV-P03-TORQUE-VERIFIER-20260723` | 2026-07-23 | gold-free CoT+Verifier candidate selection with strict failure fallback | clean commit `e09a40fa9e192bb92971be61e795cbfabcb3117d` | focused 6/6; full 477/477 in 14.508s; production prediction, metrics and paired statistics passed fresh offline replay | production artifacts registered above |
| `DEV-P01-RELATION-ONLY-20260723` | 2026-07-23 | strict in-memory GSM8K original/inverse relation supervision with explicitly unavailable CF answer; synthetic only | clean commit `17137bbf6e666381c148d40b7249032ab1d3a0b6` | focused 8/8 in 0.007s; final full 485/485 in 14.542s; no production source read | none |
| `DEV-P01-RELATION-ARTIFACTS-20260723` | 2026-07-23 | fixed official-train relation-supervision publisher and full source-lockstep verifier | clean commit `5f0b31ed27b9aa582259a61bfc0f4b7dd11cd578`; atime fix `3fbe53fe9aa4faec65b8c948857869dc85574e7f` | artifact focused 8/8; combined 27/27; final full 494/494 in 14.788s | production artifact registered below |
| `DEV-P01-RELATION-HUMAN-AUDIT-20260723` | 2026-07-23 | deterministic train-only stratified 200-pair packet and blank A/B reviewer templates | clean commit `6f56fcb31b07d0c2be095a4aa7d4ea69e2be72cb` | focused 7/7; combined 23/23; full 501/501 in 15.366s | production packet registered below |
| `DEV-P03-TORQUE-SELF-CONSISTENCY-20260723` | 2026-07-23 | fixed 8-sample CoT aggregation, private evidence envelope and offline vote replay | implementation `f6a43f36fc6d48014ca02b7d06dbaf297338b829`; execution commit `b2f889b02893d99751ee9aabacdb3038a3456e1e` | focused 8/8; full 509/509; batch-4/8 smoke passed; production prediction, metrics and paired statistics passed fresh replay | production artifacts registered above |

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
| `PROC-P01-GSM8K-RELATION-ONLY-V1-20260723` | `VERIFIED / TRAIN ONLY / CF ANSWER UNAVAILABLE` | `3101c7d5072418e28b9008a6636bde82a006892c` | `5f0b31ed27b9aa582259a61bfc0f4b7dd11cd578` | train raw/no-marker/extraction-rejected/rewrite-rejected/retained = 7,473/5,628/1,475/0/370; all four identity sets unique 370; no test artifact | JSONL/manifest SHA256 `525e3b09c6a6d03942a6bc3e03ebcd1722c3a68f4f224753dbc641f98465c12a` / `4e22ff135d97c89ded50a54fc1007f25d9646db67ce112e4637d4e8c8b63674a`; fresh full source replay passed; CF answer loss fixed masked | `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/relation-supervision-v1/explicit-marker-relation-only-v1/train` |

`VERIFIED` in this table means the immutable processed data artifact passed replay verification. It is not a model metric and cannot by itself support a paper performance claim.

## Human audit packets

| ID | Status | Source | Sampling | Artifact binding | Path |
|---|---|---|---|---|---|
| `AUDIT-P01-GSM8K-RELATION-ONLY-200-20260723` | `PACKET VERIFIED / HUMAN REVIEW PENDING` | `PROC-P01-GSM8K-RELATION-ONLY-V1-20260723`, 370 train pairs, JSONL/manifest `525e3b09...` / `4e22ff13...` | seed 20260723; after/follows 259→140, before/precedes 111→60; A/B fields all null | items `0f37bc96...`; A `3a2618b9...`; B `390e7cb5...`; instructions `8ee14494...`; manifest `da5d7fb0...`; fresh replay passed | `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/human-audit-v1/explicit-marker-relation-only-v1/train` |

Packet verification proves deterministic sampling and integrity only. Cohen's kappa, adjudicated validity and training permission remain unavailable until two human submissions are completed and hash-locked.
