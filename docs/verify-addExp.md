# Kairos 补充实验技术与结果报告

> 状态：PHASE 01 RUNNING
> 本文件是同伴作者引用补充实验的唯一汇总来源。当前已有 source conversion 与 construction v0 两个 `VERIFIED` 数据工件，但所有论文效果数字仍仅为 `REPORTED`，尚无本项目 `VERIFIED` 模型实验结果。

## 1. 文档状态与执行摘要

- 当前阶段：Phase 01，data pipeline；GSM8K source/example conversion 与 construction v0 production replay 已完成
- 复现性质：independent reimplementation
- 已完成实验：无
- 当前结论：尚不能验证论文效果数值；已验证当前保守 v0 在 GSM8K 上为 0 retained，不能直接用于模型训练

## 2. 复现范围、版本与 Git commit

restart-safe bootstrap commit 为 `989634284e58b733e0bca2520fd0e7caad930e4c`。以 `kairos.pdf` 为主要待验证规格，`main.tex` 为较早且数值冲突的版本。

## 3. PDF、TeX 与重实现差异

详细差异见 `docs/ai-context/discrepancies.md`。PDF 的 Overall Kairos Standard/CF/Average 为 0.610/0.604/0.607；TeX 为 0.272/0.251/0.262。两组数值当前均未由代码和数据支持。

## 4. 技术实现路径

阶段 1已实现第一个开发检查点：严格 JSONL schema、relation inverse、稳定 ID 与 split、唯一显式 marker 抽取、白名单反事实改写、保守 `UpdateAnswer` 和构造漏斗。该版本只支持 D-003 声明的高精度 v0 语义，不是通用事件抽取器。包含嵌套 schema、非字符串 canonical key 拒绝和无关 relation 更新拒绝的 27 项开发单元测试通过；未开始真实数据构造，因此未产生 `VERIFIED` 实验结果。

数据获取前置实现已增加不使用 `extractall`/`getmembers` 的 ZIP/TAR/TAR.GZ 前置元数据门禁、全量检查与 dirfd 流式提取。三轮审计发现的无界元数据、原地改写、symlink/竞态、伪造 EOCD count、ZIP64、central-to-EOCD gap 与 central/local header 不一致均已增加前置门禁和回归测试。仓库全套 49 项开发测试与完整 staged 复审已通过；真实数据获取尚未完成，因此不产生 `VERIFIED` 实验证据。

archive validator 已在智能体 2独立重放篡改反例后通过最终安全审计，并以 commit `c57a133cf7c05f049ca16f8e43d29302480ec411` 推送。该证据仅验证数据获取前置组件，不是论文实验运行；真实数据下载仍需单独资源与路径审批。

GSM8K 首次实际获取预审为 `BLOCKED`，未创建 raw 目录。阻塞项涉及传输硬上限、curl 局部配置隔离、archive 别名完整性、completion 崩溃一致性和 JSONL 内存上限；修复规格已冻结到 D-004-A，在代码与执行复审前仍不获取数据。

acquisition helper 的首次实施预审同样为 `BLOCKED`：完成语义还必须抵抗路径替换、未知 hardlink、hash 期间变更和掉电后数据未持久化，并在 helper 内重复实施全部字节、成员、路径与清单上限。扩展规格已追加到 D-004-A，未下载、未产生数据统计。

扩展 D-004-A 后，acquisition helper 的修订实施计划获得代码实施批准。固定布局的离线 stage/finalize/verify 模块和 33 项针对 HTTP schema、TOCTOU、hardlink/symlink、预算、清单篡改与 completion 发布的测试已实现；仓库全套 82 项测试通过。当前仍待 staged 安全复审，未下载且无 `VERIFIED` 论文数值。

首次 staged 安全复审结论为 `BLOCKED`：82 项测试未覆盖 revision 路径重解析、同内容 inode 替换、大规模空目录检查和 completion 已发布后的 fsync/snapshot 失败。该 helper 当前不可提交、不可用于获取或论文证据。

扩展修复已将 archive inspect/extract 改为 held-fd API，绑定 formal archive 重开前后 inode，线性化空目录检查，并以 fsync 后 formal-tree fingerprint 和永久 guard/final pair 表示完成。包含 44 项 acquisition 测试的仓库全套 97/97 通过；完整 staged 复审仍待进行，未下载且无 `VERIFIED` 论文数值。

第二次 staged 复审仍为 `BLOCKED`：97 项测试未阻止 completion pair 在读取后被整体替换、整条 revision parent chain 移位、formal root 的协议外文件，并且 guard 名称/发布顺序与冻结协议不一致。该 helper 仍不可提交或用于论文证据。

第二轮修复已长持并重绑 completion pair，从 absolute project root 重建整条 revision chain，限制 formal root 为三项固定集合，并以 guard-only 先 fsync、guard 再 link final 的顺序发布。新增六项回归后仓库全套 103/103 通过；第三次 staged 复审仍待进行，未下载且无 `VERIFIED` 论文数值。

第三次 staged 复审结论仍为 `BLOCKED`：内层验证结束到最外层返回之间仍可替换 completion pair 或新增 root entry，pair fd 关闭故障也可泄漏另一 fd/掩盖原异常。该 helper 仍不可提交或用于论文证据。

第三次审计修复已将 held completion pair 生命周期扩展到末次树扫描、canonical pair 重绑、完整 root/parent/revision fingerprint 校验和返回线性化点，并实现不掩盖活动异常的双 fd best-effort close。新增晚期 pair/路径/普通文件/目录攻击与 close-failure 回归后，57 项 acquisition 测试及仓库全套 110/110 开发测试通过。这仍只是待第四次 staged 安全审计的开发证据；未下载数据，不产生 `VERIFIED` 论文数值。

第四次 staged 审计仍为 `BLOCKED`：held pair 修复正确，但 canonical guard/final 每次重开的临时 fd 在 close 故障时仍可泄漏另一 fd，并以 cleanup 错误覆盖既有 validation/open 异常。因此 helper 尚不可提交、不可用于数据获取或论文证据。

canonical 临时 fd 已改用与 held pair 一致的固定快照 best-effort cleanup，并新增 final/guard/both close、active validation 和 partial-open 故障矩阵。62 项 acquisition 测试与仓库全套 115/115 通过；第五次 staged 审计前仍只是开发证据，未下载数据，不产生 `VERIFIED` 论文数值。

第五次完整 staged 审计独立重放上述故障矩阵和前四轮攻击路径后给出 `APPROVED TO COMMIT`。该批准仅证明获取 helper 快照可提交/普通推送，不是数据下载、论文实验或 `VERIFIED` 数值的批准。

审计通过的 helper 已以 commit `ca759ac26bfc0bd64ee25a9732c20d8ea335a362` 普通推送至工作分支。截至该提交仍无 raw 数据、实验 run 或论文指标。

GSM8K 官方 commit `3101c7d5072418e28b9008a6636bde82a006892c` 已在 provenance commit `482af857249b03d89c986dce96c9d38fc11cfd70` 上按固定 codeload URL 获取。Archive 为 4,447,003 bytes，SHA256 `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a`，18 个成员、声明展开 14,356,149 bytes；train/test 分别 7,473/1,319 条。主智能体与边界智能体的 offline verify 均通过，`SHA256SUMS` 15/15 严格验证，completion pair 同 inode 且 `nlink=2`。这只是 `ACQ-GSM8K-20260722` 数据获取/完整性证据，不是模型实验、论文指标或 `VERIFIED` 结果。

D-005 只读 discovery 进一步确认 train/test 的 exact `{answer, question}` string schema 与 whole-file SHA256；parser 语义只由 train 冻结，test 未回显值也未用于选择规则。实施计划审计发现 ASCII-only trim 与 generic answer Unicode-whitespace invariant 在 NBSP-only/EM-SPACE-only suffix 上冲突，最小 D-005-A 已经边界审计冻结：Unicode `strip()` 只作非空接受判定，发布值仍是逐字符保留的 ASCII-trim target。在该语义冻结检查点，尚未实现 adapter、运行测试、读取 raw 或创建 processed 工件，因此该检查点不产生实验结果。

immutable GSM8K source adapter 已以 commit `892b486b6bfb522de0aae4a675b651baf7ae1868` 实现：source ledger 保存 decoded raw 与 compact provenance，canonical example 以 `source_id` 引用并保存 ASCII-trim target；四 JSONL 与 manifest 使用 no-replace、fingerprint-bound、manifest-last 发布，verifier 从 raw physical line 锁步重构全部预期值。两轮安全阻塞先后修复了 FD/异常生命周期、terminal namespace 窗口和伪故障覆盖；最终 targeted 63/63、full 166/166 并经智能体 2独立复核。在该 adapter implementation checkpoint 尚未运行 production conversion、创建 processed 工件或产生论文指标。

随后从 clean checkpoint commit `3e34c9c6da06a0364b84ef97492331e59a764a45` 完成唯一一次 production prepare 和唯一一次 offline verify，二者均 exit 0 且 canonical manifest 一致。工件 `PROC-P01-GSM8K-20260722` 已通过智能体 2事后边界审计；它验证数据转换可追溯性，不是论文模型实验。

MuSiQue 固定官方 Drive view URL 的 65,536-byte response-body probe helper 已以 commit `cacbcbcc504ebfcb77c1e6329edc69f05de9a7e2` 实现。真实 prlimit/procfd、whole-PGID cleanup、严格字节三方一致、零跳转、三态离线验证和 publication fatal fail-close 均有合成回归；最终 targeted 92/92、full 258/258 并通过四轮边界审计。这只是尚未执行的获取前置组件：未产生 MuSiQue 数据、样本统计、实验 run 或论文指标。当前 0775 trusted-ancestor 门禁会在联网前主动阻止 production execute，后续不得通过放宽策略绕过。

执行策略复核已将 MuSiQue 获取工作项标为 `BLOCKED_POLICY / TRUSTED_ANCESTOR_CONFLICT`：固定路径的 0775 祖先在 stage 创建和网络前即被拒绝。该状态不是 ProbeStatus、HTTP 失败或 Drive 不可达证据；production probe 从未运行，MuSiQue 的 archive 与实验状态仍未验证。

StrategyQA 已完成获取前 source-plan 冻结：`official-20210107` 仅是项目标签，未来对象必须由固定 GCS URL、strong ETag、UTC date 与首次 GET 后 SHA/bytes 联合识别。实际 ZIP、schema、split、license 与指标均未获取或验证；该 source-plan 检查点当时的批准范围只到精确 implementation plan，因而它本身不产生实验或数据证据。

StrategyQA 固定 transfer/stage helper 已以 commit `978ba4dea0792061340d0ec97241caa1efd6d6f2` 实现；两轮安全审计后 targeted 79/79、full 337/337 合成测试通过。该结果只是 development verification，`RUNTIME_REDIRECT_SEMANTICS_VERIFIED=False` 仍在任何网络、文件或子进程操作前阻断 production fetch。因此本项未产生 StrategyQA archive、样本统计、run ID 或论文指标，不得作为效果 claim。

StrategyQA runtime redirect 门禁现为 `BLOCKED_TOOLING / NO_NATIVE_EXEC_ENV`：现有调用工具不能为最外层动态进程原生提供完全替换式环境，因此所有准备记录均未执行且不可复用。未创建新的运行身份、approval 或 V3，也没有网络、数据或实验工件；该状态不是实验结果，不改变任何论文结论。恢复条件与审计证据见 `docs/ai-context/checkpoints/phase-01-strategyqa-runtime-redirect.md`。

2Wiki 当前仅完成官方 corrected source 与主论文 metadata 的文档冻结，状态为 `METADATA_ONLY / HEAD_NOT_ATTEMPTED`。本次 2026-07-23 discovery 未发起新的 Dropbox 请求，corrected literal exact HEAD 尚未执行；2026-07-22 历史限时 HEAD 超时且没有可用于证明 availability、size、MIME、redirect 或 archive content 的响应。未读取 archive 或观察本地 split/schema，论文描述也未被当作本地数据或实验结果；详细边界见 `docs/ai-context/checkpoints/phase-01-2wiki-discovery.md`。

2Wiki exact HEAD 计划随后被独立判定为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`，未执行且没有新的 HEAD 响应、approval、record、数据或实验工件。该非结果状态不验证 availability、redirect、MIME、size 或任何 archive property，也不支持论文 claim。

TORQUE 当前仅完成固定 README/LICENSE 与 primary paper 的 metadata discovery，状态为 `METADATA_ONLY / DOCUMENTS_READ`。README/paper 描述没有被当作本地 tree、数据、schema、evaluator 或实验观察；指标定义冲突仍未选择，test gold 不会从第三方恢复。该非结果状态不产生任何可写入论文的实验数值，详细边界见 `docs/ai-context/checkpoints/phase-01-torque-discovery.md`。

TORQUE A/B/C snapshot/acquisition 计划随后被判定为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`。该计划未执行，未产生 snapshot/acquisition request、approval、record、stage、archive、数据或实验工件；public dev、clustering/schema、evaluator 与 test-annotation absence 均未作本地验证。该状态不是实验结果，不改变或解决既有指标 `SPEC_CONFLICT`。

TimeQA 当前只有固定 README/LICENSE 和 official arXiv landing 的 metadata evidence。ar5iv HTML 路由仅作为越界失败记录且未采纳内容，direct official-PDF 计划为 `BLOCKED_TOOLING / NO_PRE_FETCH_REDIRECT_AND_BYTE_GATES` 且未执行；不存在 accepted PDF-body evidence、来自 `PROJECT_PLANNED` hard evaluation file 的任何 bytes、schema、split、PDF-body 指标或实验结果。该状态不能支持任何新增论文 claim，详细边界见 `docs/ai-context/checkpoints/phase-01-timeqa-discovery.md`。

TimeQA A/B/C snapshot/acquisition 计划随后被判定为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`。唯一 candidate 和全部 transfer/helper 字段仍为 proposed/unexecuted；不存在 request、approval、record、stage、snapshot、data、code 或 experiment artifact。该 planning blocker 不是 acquisition、数据验证或实验结果。

D-011 显式 marker 构造 v0 已以 commit `24ce15d40bd038d61bd6581ed2bc260072468c12` 完成 development-only 实现与验证。它仅在内存中组合保守 extraction/rewrite/UpdateAnswer：只有可证明的 `KNOWN` 答案才保留完整 original/CF pair，`UNKNOWN` 不产生 dangling record。该开发验证未读取 production data，未定义、生成或统计 GSM8K temporal subset，未运行数据构造，未产生 yield、样本统计、模型指标、论文结果或持久工件，也不是 formal run 或 `VERIFIED` 实验证据。唯一详细证据见 `docs/ai-context/checkpoints/phase-01-temporal-construction-v0.md`。

D-012 construction audit schema v1 已以 commit `633618b6dc81503b7c5794380e8fa524f37c4c4c` 完成 synthetic development verification，parent 为 `2b7e3f03726fd1abf59fa18867593458f38e5b34`，普通 push 后 HEAD、origin 与 upstream 一致。其 source/test blob 为 `1bb1b167f3af5424b8fe199b2c9057c51638957f` 与 `3bfa86de8deb0b15ececad698808583acfe7aa45`；最终 fresh targeted 24/24、0.193s、exit 0，唯一一次 full suite 373/373、13.020s、exit 0，并通过 post-audit。该记录只证明内存 audit schema 的开发检查，不读取 production data，不生成 formal run、artifact、模型指标、论文效果数字或可进入作者结论的 `VERIFIED` effect claim；详细边界见 `docs/ai-context/checkpoints/phase-01-construction-audit-schema.md`。

D-013/P2 与 fixed GSM8K driver 已完成 production integration。有效执行 commit 为 `3944bb56d5c16a11482de39c5f0295936b6ac035`；train/test immutable audit 均经独立 offline source-lockstep replay。当前 adapter 将 GSM8K `text` 与 `question` 设为同一值，冻结 D-011 对所有成功抽取记录触发 `text_question_alias_unsupported`，因此 valid CF 与 retained 均为 0。该结果验证了当前独立实现的数据策略不充分，不能解释为论文方法效果或用来反驳论文中不可识别的作者 subset。

Kairos tensor core 已在 `c178d15...` 独立实现并通过 14/14 focused、427/427 full 及 synthetic backward：event/answer span mean pooling、`softplus+1e-6` interval、论文顺序的 8-d geometry、五类 relation graph、masked mean graph pool、`[u;g;u*g]` candidate scoring 和三项 loss。Pair-MLP 复用相同 supervision/masks/scorer，仅替换 interval geometry。该状态是 `DEVELOPMENT_VERIFIED TENSOR CORE`，不表示 Qwen/LoRA、端到端训练或模型效果已验证。

## 5. 实验设计与超参数

冻结设计见 `docs/experiments/README.md`。任何偏离必须记录决定、时间和影响。

## 6. 数据构造统计与人工审计

GSM8K 固定 upstream revision `3101c7d5072418e28b9008a6636bde82a006892c` 的 source/example 转换已验证：

| Status | Artifact ID | Split | Source records | Canonical examples | Duplicate question/raw-record groups | Execution commit |
|---|---|---:|---:|---:|---:|---|
| `VERIFIED DATA ARTIFACT` | `PROC-P01-GSM8K-20260722` | train | 7,473 | 7,473 | 0 / 0 | `3e34c9c6da06a0364b84ef97492331e59a764a45` |
| `VERIFIED DATA ARTIFACT` | `PROC-P01-GSM8K-20260722` | test | 1,319 | 1,319 | 0 / 0 | `3e34c9c6da06a0364b84ef97492331e59a764a45` |

processed manifest SHA256 为 `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`；四个 ledger 的逐文件 SHA256 与 bytes 位于 `docs/ai-context/checkpoints/phase-01-gsm8k-conversion.md`。

Construction v0 的已验证漏斗为：

| Status | Artifact ID | Split | Raw | Temporal filtered | Extraction/reliable | Valid CF | Retained | Execution commit |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `VERIFIED DATA ARTIFACT / ZERO_RETAINED` | `PROC-P01-GSM8K-CONSTRUCTION-V0-20260723` | train | 7,473 | 1,845 (24.69%) | 370 (4.95%) | 0 | 0 | `3944bb56d5c16a11482de39c5f0295936b6ac035` |
| `VERIFIED DATA ARTIFACT / ZERO_RETAINED` | `PROC-P01-GSM8K-CONSTRUCTION-V0-20260723` | test | 1,319 | 361 (27.37%) | 79 (5.99%) | 0 | 0 | `3944bb56d5c16a11482de39c5f0295936b6ac035` |

Train audit/manifest SHA256 为 `a4b38dd3ba6b8b597732744af74b5e16fe464a98f2b8c1f6540fe04361cdb346` / `41edd3255de9e6b3c9f6df4a7d2ca9f05d6dc7ad33a65f2f7d3b044e8a15412f`；test 为 `14393b5e2c8aace358babaaf38e37bd2d4e8fcbcdd52452127b3bf49b9f6a4e4` / `dda773ba105b59eb5d4e27fe8ea4ea0dcc2b661b4c639a2d3cd2ba297f9a129c`。这里的 `VERIFIED DATA ARTIFACT` 不等于实验效果 `VERIFIED`。两人 200 条人工审计与 Cohen's kappa 尚未完成；在冻结 construction v1 前不得开始 GSM8K LoRA 训练。

## 7. 已有实验复现结果

待运行。每行同时给出 `REPORTED`、重实现值、95% CI、差异、判定、run ID 和 commit。

## 8. 新增 Baseline 结果

首个 prompt-only Direct 正式 run 已完成，并通过 immutable prediction 与 machine-readable metrics 的两层离线重放，状态为 `VERIFIED / DETERMINISTIC SINGLE RUN / NO COMPARATIVE CI`。Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph/Constraint-Rerank 仍待运行。

## 9. TORQUE 与 TimeQA-Hard 结果

TORQUE Direct 已完成首次正式迁移评测；TimeQA-Hard 尚未运行模型评测。两数据集 fixed official source 已进入本地 staging：

- TORQUE `ab27019c...`：archive SHA256 `7284c675f0cf21ddb1272c31919d4453d2fb53a426e88b46ad6a9a0fd9030cd0`；public dev 145 passages/1,483 answer-bearing QA，dev SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`。test 无 answer，不使用。
- TimeQA `38b05989...`：archive SHA256 `f0df52a31e9d4bb0d5b7577d9e0131740bd017d2aad1e9b4bee7756bfecdfd07`；`human_test.hard.json` 为 989 条 JSONL，SHA256 `0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`。

fixed adapters 与 metric contract 已在 `e89bbfd...` 实现，并由 `8b57ffe...` 修复/冻结 TimeQA 空 gold 行为。focused 13/13、full 401/401；clean production read-only smoke 验证：

- TORQUE：1,483 题、145 passages、571 个 `(passageID, cluster_id)` contrast groups、323 个空 gold set，answer cardinality 0--16。主 consistency 是组内每题 set EM=1；F1>=0.8 口径作为 sensitivity 同时报告。
- TimeQA-Hard：989 unique records、33,679 paragraphs、1,046 targets；target cardinality 1/2/3 为 940/41/8，其中 159 题的唯一 gold 为空字符串，按官方 empty/empty EM/F1 语义保留。

Direct 结果如下。指标均为百分数，parse error 使用固定 sentinel 计错；没有从输出中人工恢复答案。

| Status | Method | Dataset/split | N / groups | Seed | Set EM | Set F1 | Cluster exact | Cluster F1>=0.8 | Parse error | Run / commit |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `VERIFIED / SINGLE RUN` | Qwen2.5-7B Direct greedy | TORQUE public dev | 1,483 / 571 | 13 | 15.644 | 16.070 | 1.576 | 1.576 | 42/1,483 (2.832%) | `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d` / `eae442b...` |

该 run 固定模型 revision `a09a354...`、数据 SHA `7a8dd84c...`，全量 source-order prediction/raw evidence 与派生 metrics 均通过独立离线 replay。Metrics aggregation commit 为 `61e96bc...`，metrics/manifest SHA 为 `c508305a...` / `1187e24d...`。当前数值只建立了 prompt-only 下界；在 CoT、Kairos 和匹配监督 Baseline 完成及 paired bootstrap 前，不能据此声称 interval/graph 方法改进或显著差异。完整 SHA 与资源证据见 registry 和 `phase-03-torque-direct-baseline.md`。

## 10. 统计检验与实验结论

待三个 seed 和 paired bootstrap 完成后填写。负结果和无显著差异必须保留。

## 11. Interval/Graph 案例与失败分析

待填写成功案例与事件抽取、隐式关系、答案未更新、错误翻转、长上下文混淆等失败类型。

## 12. 审稿意见与新增证据映射

| Reviewer concern | Planned evidence | Status |
|---|---|---|
| 非标准 temporal 数据集 | TORQUE、TimeQA-Hard | TORQUE Direct VERIFIED single run；TimeQA model evaluation PLANNED |
| Baseline 弱/监督不公平 | Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph | PLANNED |
| marker/template artifact | explicit/implicit、held-out、answer-unchanged | PLANNED |
| 数据构造不透明 | 构造漏斗、哈希、人工审计 | PARTIAL：v0 漏斗/哈希 VERIFIED；人工审计待完成 |
| interval 可解释性不足 | interval/graph 可视化与消融 | PLANNED |

## 13. 论文修改建议

只有 `VERIFIED` 结果可以进入本节。实施阶段不自动修改 `main.tex`。

## 14. Run、Commit 与工件追踪

首个正式模型 run 为 `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`，execution commit `eae442b850f0a1aa5cc27275717cf08b6de54bac`；config/prediction/evidence/manifest SHA 分别为 `ec6ea450...`、`6cc7298b...`、`c85c0335...`、`31813646...`。其 metrics aggregation commit 为 `61e96bc58cd13bb4f5dc997ee678b86e81d9044a`，metrics/manifest SHA 分别为 `c508305a...` / `1187e24d...`；完整值见 registry。数据获取记录 `ACQ-GSM8K-20260722` 对应 provenance `482af857249b03d89c986dce96c9d38fc11cfd70` 和 archive SHA256 `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a`；processed artifact `PROC-P01-GSM8K-20260722` 对应 execution commit `3e34c9c6da06a0364b84ef97492331e59a764a45` 和 manifest SHA256 `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`。Construction artifact `PROC-P01-GSM8K-CONSTRUCTION-V0-20260723` 对应 `3944bb56d5c16a11482de39c5f0295936b6ac035`，split 哈希见第 6 节。新增 source records 为 `ACQ-STRATEGYQA-20260723`、`ACQ-TORQUE-20260723`、`ACQ-TIMEQA-20260723` 与 `ACQ-2WIKI-20260723`，状态和 manifest SHA 见 registry。Bootstrap commit 为 `989634284e58b733e0bca2520fd0e7caad930e4c`；后续所有表格必须引用 registry 中的 run ID 和 SHA256。
