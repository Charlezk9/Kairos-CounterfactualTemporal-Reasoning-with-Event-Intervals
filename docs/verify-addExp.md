# Kairos 补充实验技术与结果报告

> 状态：PHASE 01/03 RUNNING
> 本文件是同伴作者引用补充实验的唯一汇总来源。当前已有可重放数据工件，以及 TORQUE/TimeQA 的 Direct、CoT、CoT+Verifier、TORQUE Self-Consistency、LLM-Graph 与 Rule-Graph 正式结果；Kairos 与匹配监督 Baseline 尚未形成正式结果。

## 1. 文档状态与执行摘要

- 当前阶段：Phase 01 data remediation 与 Phase 03 baseline evaluation 并行；GSM8K source/example conversion、construction v0 replay 和六类 baseline 已完成
- 复现性质：independent reimplementation
- 已完成实验：TORQUE Direct/CoT/CoT+Verifier/Self-Consistency/LLM-Graph/Rule-Graph，TimeQA-Hard Direct/CoT，以及各 candidate 对 Direct 的配对 bootstrap/Holm 校正
- 当前结论：尚不能验证论文 Kairos 核心效果；当前 TORQUE CoT、CoT+Verifier 与 strict LLM-Graph 均低于 Direct，Self-Consistency 与 Direct 无可支持差异，Rule-Graph 与 Direct 四项得分精确相同，TimeQA 结果被严格格式失败主导；GSM8K 保守 v0 为 0 retained，不能直接用于完整 CF-answer 训练

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

D-027 随后在 clean `08d847b...` 上冻结并执行多入口恢复：April 2021 corrected object 的 `www.dropbox.com` SCL 与 `dl.dropboxusercontent.com` content route、官方旧 `data_ids.zip` 和原始 `data.zip` 均在 20--30 秒连接阶段 curl 28，HTTP 000、header/body 0 bytes；固定 unofficial HF mirror `xanhho/2WikiMultihopQA@6ef4eb1...` 又以 OS `Network is unreachable` 失败且未取得 repository metadata。五个无样本内容的 mode-0600 attempt manifests 已保留并登记。当前状态为 `DEFERRED_NETWORK / SOURCE_UNVERIFIED`：这说明服务器当时无法访问冻结源，不说明数据永久不可用，也不允许把未验证镜像用于正式实验。详细证据见 `docs/ai-context/checkpoints/phase-01-2wiki-source-recovery.md`。

TORQUE 的早期 discovery checkpoint 当时仅完成固定 README/LICENSE 与 primary paper metadata，状态为 `METADATA_ONLY / DOCUMENTS_READ`；该历史非结果状态本身不产生实验数值。其后 D-014 用户授权的官方 source 获取、adapter/metric freeze 和正式运行已 supersede 当前执行状态，但不抹去早期边界；test gold 仍不从第三方恢复。详细历史证据见 `docs/ai-context/checkpoints/phase-01-torque-discovery.md`，当前证据见第 9 节。

TORQUE A/B/C snapshot/acquisition 计划随后被判定为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`。该计划未执行，未产生 snapshot/acquisition request、approval、record、stage、archive、数据或实验工件；public dev、clustering/schema、evaluator 与 test-annotation absence 均未作本地验证。该状态不是实验结果，不改变或解决既有指标 `SPEC_CONFLICT`。

TimeQA 的早期 discovery checkpoint 当时只有固定 README/LICENSE 和 official arXiv landing metadata；ar5iv 路由内容未采纳，direct official-PDF 计划也未执行。该历史状态后来被 D-014 用户授权的 fixed-revision source 获取、adapter/metric freeze 和正式运行 supersede，但仍不存在 accepted PDF-body evidence。详细历史边界见 `docs/ai-context/checkpoints/phase-01-timeqa-discovery.md`，当前 source 与结果证据见第 9 节。

TimeQA A/B/C snapshot/acquisition 计划随后被判定为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`。唯一 candidate 和全部 transfer/helper 字段仍为 proposed/unexecuted；不存在 request、approval、record、stage、snapshot、data、code 或 experiment artifact。该 planning blocker 不是 acquisition、数据验证或实验结果。

D-011 显式 marker 构造 v0 已以 commit `24ce15d40bd038d61bd6581ed2bc260072468c12` 完成 development-only 实现与验证。它仅在内存中组合保守 extraction/rewrite/UpdateAnswer：只有可证明的 `KNOWN` 答案才保留完整 original/CF pair，`UNKNOWN` 不产生 dangling record。该开发验证未读取 production data，未定义、生成或统计 GSM8K temporal subset，未运行数据构造，未产生 yield、样本统计、模型指标、论文结果或持久工件，也不是 formal run 或 `VERIFIED` 实验证据。唯一详细证据见 `docs/ai-context/checkpoints/phase-01-temporal-construction-v0.md`。

D-012 construction audit schema v1 已以 commit `633618b6dc81503b7c5794380e8fa524f37c4c4c` 完成 synthetic development verification，parent 为 `2b7e3f03726fd1abf59fa18867593458f38e5b34`，普通 push 后 HEAD、origin 与 upstream 一致。其 source/test blob 为 `1bb1b167f3af5424b8fe199b2c9057c51638957f` 与 `3bfa86de8deb0b15ececad698808583acfe7aa45`；最终 fresh targeted 24/24、0.193s、exit 0，唯一一次 full suite 373/373、13.020s、exit 0，并通过 post-audit。该记录只证明内存 audit schema 的开发检查，不读取 production data，不生成 formal run、artifact、模型指标、论文效果数字或可进入作者结论的 `VERIFIED` effect claim；详细边界见 `docs/ai-context/checkpoints/phase-01-construction-audit-schema.md`。

D-013/P2 与 fixed GSM8K driver 已完成 production integration。有效执行 commit 为 `3944bb56d5c16a11482de39c5f0295936b6ac035`；train/test immutable audit 均经独立 offline source-lockstep replay。当前 adapter 将 GSM8K `text` 与 `question` 设为同一值，冻结 D-011 对所有成功抽取记录触发 `text_question_alias_unsupported`，因此 valid CF 与 retained 均为 0。该结果验证了当前独立实现的数据策略不充分，不能解释为论文方法效果或用来反驳论文中不可识别的作者 subset。

D-022 relation-only supervision v1 已以 commit `17137bbf6e666381c148d40b7249032ab1d3a0b6` 完成 synthetic development verification。它只为可确定重放的显式 marker pair 保存 original relation 与 inverse counterfactual relation，并保留 original numeric answer；counterfactual answer 明确为 `unavailable-relation-only`，序列化 schema 不存在 CF answer 字段。focused 8/8、最终 full 485/485 通过。该实现未读取 production train/test、未发布工件或产生指标；它只能作为 relation-supervision 的部分桥接，不能被写作 CF answer accuracy、update、stability 或 consistency 证据，也不满足论文的 reliable updated-answer 要求。

Kairos tensor core 已在 `c178d15...` 独立实现并通过 14/14 focused、427/427 full 及 synthetic backward：event/answer span mean pooling、`softplus+1e-6` interval、论文顺序的 8-d geometry、五类 relation graph、masked mean graph pool、`[u;g;u*g]` candidate scoring 和三项 loss。Pair-MLP 复用相同 supervision/masks/scorer，仅替换 interval geometry。该状态是 `DEVELOPMENT_VERIFIED TENSOR CORE`，不表示 Qwen/LoRA、端到端训练或模型效果已验证。

`14f7104...` 进一步完成 synthetic-only Qwen-to-core adapter：Kairos/Pair-MLP 共用 original/CF/candidate batch、hidden states、span masks 和三项 loss；只编码 valid candidates，Qwen base decoder 禁用 cache 且不保留所有层 hidden states。LoRA 独立默认固定 rank 16/alpha 32/dropout 0.05，并验证 `q/k/v/o/gate/up/down_proj` 七类 target suffix；当前没有注入 PEFT、加载 7B、持久 checkpoint 或正式训练。focused 7/7、full 522/522 与两个 core 的 synthetic backward 通过。

`7772f7c...` 完成 D-028 synthetic-only 可恢复执行层：严格两组 AdamW、effective-batch accumulation、BF16、scheduler、RNG 和 manifest-last/no-replace checkpoint。Kairos 与 Pair-MLP 的 CPU synthetic uninterrupted 和 interrupted/resumed 路径逐项等价，focused 20/20、full 528/528 通过；同时修复 interval mask 在 autocast 下把 BF16 坐标提升回 FP32 的缺陷，FP32 语义不变。该项不读取 production 数据、不加载 7B、不使用 GPU，也不产生论文指标；该 commit 的 v1 checkpoint 当时尚未绑定 frozen backbone revision 或 production data manifest，不能作为正式训练证据。

`1d80f5d...` 随后将 synthetic checkpoint 升级为 v2，绑定 fixed Qwen model/revision/`SHA256SUMS`、dataset revision/data-manifest SHA256 与 Kairos/Pair-MLP core type；resume 在打开 state 前校验 expected binding。focused 8/8、full 530/530 通过。该 binding 仍不等于实际 production manifest verification，也未实现 PEFT、sampler、7B/GPU 或正式训练，因此不产生新的论文效果数值。

`c68c77a...` 完成项目局部 PEFT 0.14.0 注入：real tiny-Qwen 的 LoRA-only 参数、forward/backward、两组 optimizer、state 与 checkpoint/resume 均验证，full 533/533 通过。clean commit 上 fixed local 7B、synthetic batch 32 的单步 GPU smoke 产生 392 个 LoRA tensors，loss 1.96875，峰值分配 15,920,307,712 bytes并正常释放 GPU。该数值仅为实现诊断，不读取 production 数据、不构成模型效果或论文表格证据；正式训练仍等待人工审计和 deterministic runner。

`8de516d...` 完成 D-031 synthetic-only 训练顺序层：source-order 样本、候选 content hash/来源、gold target/补入状态、三轮 SHA256 顺序、显式 tail repeat、micro-batch 身份与 resume cursor 全部进入可独立重建的 canonical manifest。focused 7/7、full 540/540 通过。该项没有读取 production 样本、生成候选、训练或产生指标；它只消除可重现性工程缺口，不是可回应审稿人的效果证据。

`9a58155...` 完成 D-034 synthetic-only 候选/token 物化与 plan publisher：typed relation pair、exact candidate proposals 与 gold injection形成 D-031 corpus；单个 micro-batch按需生成 original/CF chat event masks、candidate answer masks、双向 relation targets和 original answer target，并以私有 no-replace/manifest-last 工件完整重放 training plan。focused 9/9、full 560/560 通过。该项仍未读取 production pair/prediction/tokenizer/model、未发布正式 plan或训练；它不提供论文效果数值，也不解除两人人工审计门禁。

`832e755...` 完成 D-035 synthetic-only 人工审计结果门禁：对未来已锁定的 Reviewer A、Reviewer B 与 authors adjudication bytes执行 exact 200 行 canonical JSONL、ID/order/schema/Boolean/hash校验，汇总逐字段 agreement、overall-valid 2×2 confusion、Cohen's kappa 与 adjudicated validity，并仅在 κ≥0.80 且 validity≥95% 时通过。focused 5/5、full 565/565 通过。实现没有读取或填写 production 空白模板，也没有生成正式审计结果；因此本项是审计软件准备，不是人工有效性证据或训练许可。

TORQUE Self-Consistency 在 `b2f889b...` 冻结为每题 8 个 CoT samples、temperature 0.7、top-p 0.9、seed 13；invalid sample 不投票，normalized span-set plurality 平票取最早 valid sample，八次全失败才输出 sentinel。focused 8/8、full 509/509 后完成正式运行，私有 evidence 支持逐题离线重算投票。该实现是 prompt baseline，不使用 interval/graph 或训练监督。

TORQUE LLM-Graph 在 `99209b4...` 冻结为 gold-free one-pass structured prompt：倒数第二个 non-empty line 是 strict temporal graph JSON，最后一行是 strict answer array；节点须绑定 passage exact spans，五类边须绑定已有节点，答案须引用 graph event。focused 6/6、full 515/515 后完成正式运行，source-bound verifier 逐条重解析。该严格 primary 不在看过 dev 输出后 repair 或放宽。

TORQUE Rule-Graph 在 `dcc96b7...` 实现为 gold-blind deterministic reranker：固定消费已验证的 Direct、CoT 与八个 raw Self-Consistency candidates，只为单一标准 `before/after` 问题从 passage 的显式 clause 建立 occurrence-level before graph；只有候选集获得正 support 才替换 Direct，否则保守回退。每题 canonical trace 可在无模型、无 GPU 条件下重放。D-033 的 `fdc4f92...` 只为 config 精确绑定该 Direct 上游的 Rule-Graph 开放 paired-statistics 资格，其他跨模型比较继续拒绝。rule focused 9/9、statistics focused 8/8、最终 full 551/551 通过。

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

Train audit/manifest SHA256 为 `a4b38dd3ba6b8b597732744af74b5e16fe464a98f2b8c1f6540fe04361cdb346` / `41edd3255de9e6b3c9f6df4a7d2ca9f05d6dc7ad33a65f2f7d3b044e8a15412f`；test 为 `14393b5e2c8aace358babaaf38e37bd2d4e8fcbcdd52452127b3bf49b9f6a4e4` / `dda773ba105b59eb5d4e27fe8ea4ea0dcc2b661b4c639a2d3cd2ba297f9a129c`。这里的 `VERIFIED DATA ARTIFACT` 不等于实验效果 `VERIFIED`。两人 200 条人工审计与 Cohen's kappa 尚未完成；在该审计达到冻结阈值前不得开始 GSM8K LoRA 训练。

relation-only v1 只对 official train 发布，结果为 7,473 raw → 5,628 no marker / 1,475 extraction rejected / 0 rewrite rejected / 370 retained（4.951%）。370 个 pair/source/original/CF record ID 均唯一；JSONL 为 785,369 bytes，SHA256 `525e3b09c6a6d03942a6bc3e03ebcd1722c3a68f4f224753dbc641f98465c12a`，manifest SHA256 `4e22ff135d97c89ded50a54fc1007f25d9646db67ce112e4637d4e8c8b63674a`，execution commit `5f0b31ed27b9aa582259a61bfc0f4b7dd11cd578`。fresh source-lockstep replay 通过，且没有 test 工件。该工件只支持 original-answer 与 original/inverted-relation supervision；CF answer unavailable/masked，所以这些计数不能进入 CF accuracy/update/consistency 结果。

200 条人工审计准备包已从该 train population 确定性生成：seed 20260723，after/follows 259→140，before/precedes 111→60。items/Reviewer-A/Reviewer-B/instructions/manifest SHA 为 `0f37bc96...` / `3a2618b9...` / `390e7cb5...` / `8ee14494...` / `da5d7fb0...`。两份原始模板的 event/relation/grammar/non-target/overall 字段全部为 null，因此 packet 本身仍只是 `PACKET VERIFIED`，不含判断。后续用户确认 A/B 的开发结果由下述 D-038 独立绑定；两位不同人类的独立完成证据仍未提供。

D-035 的 authors-adjudication evaluator 已开发验证，但没有接收可证明为两位独立人类的 production submission。D-038 后续以不同 schema 对零分歧 A/B 做纯算法 agreement projection，只产生 development gate；它不向 D-035 传入伪造 authors adjudication。正式 human κ、authors-adjudicated validity 与 paper gate 仍 unavailable。

按用户要求，两个隔离智能体另行完成了明确标记的 AI-A/AI-B 预审，供作者检查审阅标准，而非正式人工审计。两者 overall-valid true为115/200与174/200，overall agreement为137/200（68.5%），AI-only diagnostic Cohen's κ=0.2913；event-span validity有61项分歧。该低一致性暴露了 span 判定口径的不稳定性，不能进入论文有效率、不能替代两位人类作者，也不能解锁训练。固定结果与哈希见 `docs/ai-context/ai-reviews/summary.json`。

Claude Code 的第二组独立 AI 预审有6项 overall分歧，用户逐项裁决后得到196/200 valid（98%）与4项 invalid。后续 A/B bytes 已进入 mode-0700/0600 private intake并由 D-038 严格重放：overall observed/expected agreement为1.0/0.9608、条件κ=1.0、validity=0.98、Wilson 95% CI `[0.949713,0.992196]`；projection/result/manifest SHA为 `ae8bc796...` / `df7310e8...` / `c501f376...`。但没有证据证明两名不同人类独立完成 A/B，因此状态严格为 `PASSED_DEVELOPMENT / USER_ATTESTED / INDEPENDENCE_UNVERIFIED / NOT PAPER-ELIGIBLE`，不是正式 human κ 或 authors adjudication。366条 development-only副本的数据/manifest SHA仍为 `4b5fec2b...` / `f24a8e8e...`，CF answer unavailable/masked；下一步从审计链重建并冻结 train330/internal-dev36。

## 7. 已有实验复现结果

待运行。每行同时给出 `REPORTED`、重实现值、95% CI、差异、判定、run ID 和 commit。

## 8. 新增 Baseline 结果

Direct、CoT、CoT+Verifier、Self-Consistency、structured LLM-Graph 与 deterministic Rule-Graph 正式 run 均已完成，并通过 immutable prediction、machine-readable metrics 和配对统计工件的三层离线重放。TORQUE CoT、CoT+Verifier 与 LLM-Graph 均显著低于 Direct；Self-Consistency 的四项 CI 均跨零；Rule-Graph 的四项逐配对差和 CI 均精确为零。所有结果保留且未据此调 prompt/parser/rule。TimeQA strict 的小幅正差异由格式失败主导。Same-data SFT、Pair-MLP 与 Kairos 已获 development-only 审计路径许可，仍待 330/36 partition、共享候选、runner 与实际训练；其内部验证结果不得进入论文。

## 9. TORQUE 与 TimeQA-Hard 结果

TORQUE Direct/CoT/CoT+Verifier/Self-Consistency/LLM-Graph/Rule-Graph 与 TimeQA-Hard Direct/CoT 已完成正式迁移评测。两数据集 fixed official source 已进入本地 staging：

- TORQUE `ab27019c...`：archive SHA256 `7284c675f0cf21ddb1272c31919d4453d2fb53a426e88b46ad6a9a0fd9030cd0`；public dev 145 passages/1,483 answer-bearing QA，dev SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`。test 无 answer，不使用。
- TimeQA `38b05989...`：archive SHA256 `f0df52a31e9d4bb0d5b7577d9e0131740bd017d2aad1e9b4bee7756bfecdfd07`；`human_test.hard.json` 为 989 条 JSONL，SHA256 `0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`。

fixed adapters 与 metric contract 已在 `e89bbfd...` 实现，并由 `8b57ffe...` 修复/冻结 TimeQA 空 gold 行为。focused 13/13、full 401/401；clean production read-only smoke 验证：

- TORQUE：1,483 题、145 passages、571 个 `(passageID, cluster_id)` contrast groups、323 个空 gold set，answer cardinality 0--16。主 consistency 是组内每题 set EM=1；F1>=0.8 口径作为 sensitivity 同时报告。
- TimeQA-Hard：989 unique records、33,679 paragraphs、1,046 targets；target cardinality 1/2/3 为 940/41/8，其中 159 题的唯一 gold 为空字符串，按官方 empty/empty EM/F1 语义保留。

Direct 结果如下。指标均为百分数，parse error 使用固定 sentinel 计错；没有从输出中人工恢复答案。

| Status | Method | Dataset/split | N / groups | Seed | Set EM | Set F1 | Cluster exact | Cluster F1>=0.8 | Parse error / fallback | Run / commit |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `VERIFIED / SINGLE RUN` | Qwen2.5-7B Direct greedy | TORQUE public dev | 1,483 / 571 | 13 | 15.644 | 16.070 | 1.576 | 1.576 | 42/1,483 (2.832%) | `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d` / `eae442b...` |
| `VERIFIED / SINGLE RUN / NEGATIVE` | Qwen2.5-7B CoT greedy | TORQUE public dev | 1,483 / 571 | 13 | 12.610 | 12.778 | 1.226 | 1.226 | 31/1,483 (2.090%) | `20260723T100959Z-cot-torque-dev-s13-05e077299faf` / `21b4eea...` |
| `VERIFIED / SINGLE RUN / NEGATIVE` | Qwen2.5-7B CoT+Verifier | TORQUE public dev | 1,483 / 571 | 13 | 14.228 | 14.681 | 1.401 | 1.401 | 762/980 verifier calls (77.755%) | `20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35` / `e09a40f...` |
| `VERIFIED / SINGLE RUN / NO SUPPORTED DIFFERENCE` | Qwen2.5-7B Self-Consistency (8 CoT samples) | TORQUE public dev | 1,483 / 571 | 13 | 15.374 | 15.569 | 1.926 | 1.926 | 494/11,864 samples; 1/1,483 all-invalid | `20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d` / `b2f889b...` |
| `VERIFIED / SINGLE RUN / NEGATIVE / FORMAT-CONSTRAINED` | Qwen2.5-7B LLM-Graph greedy | TORQUE public dev | 1,483 / 571 | 13 | 1.349 | 1.349 | 0.000 | 0.000 | 816/1,483 (55.024%) | `20260723T165048Z-llm-graph-torque-dev-s13-d52c57809644` / `99209b4...` |
| `VERIFIED / CPU SINGLE RUN / EXACT SCORE TIE` | Deterministic Rule-Graph/Constraint-Rerank | TORQUE public dev | 1,483 / 571 | 13 | 15.644 | 16.070 | 1.576 | 1.576 | 1,465/1,483 conservative fallback | `20260724T064739Z-rule-graph-torque-dev-s13-45fe8931e946` / `dcc96b7...` |

Direct run 固定模型 revision `a09a354...`、数据 SHA `7a8dd84c...`，全量 source-order prediction/raw evidence 与派生 metrics 均通过独立离线 replay。Metrics aggregation commit 为 `61e96bc...`，metrics/manifest SHA 为 `c508305a...` / `1187e24d...`。当前 prompt-only 数值建立了外部迁移下界；配对统计分别支持 CoT、CoT+Verifier 与 Self-Consistency 对 Direct 的冻结比较，在 Kairos 和匹配监督 Baseline 完成前，不能据此声称 interval/graph 方法改进。完整 SHA 与资源证据见 registry 和对应 checkpoint。

CoT run 同样固定模型/数据 revision；prediction/evidence/manifest SHA 为 `900a3872...` / `9fa093f9...` / `bbb32677...`，metrics/manifest SHA 为 `7c14f0d4...` / `f8af11f7...`。相对 Direct，CoT 的 set EM/F1 差为 -3.034/-3.292 个百分点，parse error 反而少 11 条；571-group paired bootstrap 的 95% CI 分别为 `[-4.411,-1.709]` / `[-4.674,-1.954]`，Holm p 均为 0.000800。更高的格式成功率没有转化为更高题级任务指标；两项 cluster 差异均不显著。

CoT+Verifier 只接收上述两个冻结候选，不含 gold；503 条等价候选跳过生成，980 次调用中严格 index 仅解析 218 次，762 次按预注册规则回退 Direct。其 EM/F1 相对 Direct 为 -1.416/-1.389 pp，95% CI `[-2.100,-0.790]` / `[-2.075,-0.758]`，Holm p 均 0.000800；cluster 差异不显著。额外 verifier 推理未带来增益，且结果后未放宽 parser。完整输入 manifest、选择计数与工件哈希见 registry/checkpoint。

Self-Consistency 每题固定 8 个 CoT samples，总生成 1,714,292 tokens；494 个无效 sample 被排除，只有 1 题八次全无效。EM/F1 相对 Direct 为 -0.270/-0.500 pp，95% CI `[-1.387,0.885]` / `[-1.632,0.687]`；cluster 两口径相对 Direct +0.350 pp，CI `[-0.350,1.051]`。四项 Holm p 均为 1.0，因此没有可支持差异。该结果不等于“方法相同”，只表示当前 single-seed 配置没有检出增益或损害。

LLM-Graph 有 667/1,483 条同时通过 strict graph 与 answer contract，但 EM/F1 均仅 1.349，cluster 为 0。相对 Direct 的 EM/F1 为 -14.295/-14.721 pp，95% CI `[-16.155,-12.517]` / `[-16.575,-12.937]`；cluster 差为 -1.576 pp，CI `[-2.627,-0.701]`。主要 parser failure 是 graph line 位置 336 条和 event span 非 passage 原串 293 条，只有 1 条命中生成上限。结果说明严格 one-pass serialization 失败，不应外推为 temporal graph 普遍无效。

Rule-Graph 不生成文本，1,483 条 generation status 全为 `NOT_APPLICABLE`。它选择 Direct 1,475 次、CoT 5 次、SC samples 0/4/7 各 1 次；1,465 题因 cue/语义/anchor/support 门禁保守回退。8 个替换答案均未改变对应题的 EM 或 F1 contribution，因此四项聚合指标与 Direct 精确相同。该结果表明当前 v1 显式规则覆盖和 candidate selection 没有带来增益，不应外推为 constraint reasoning 普遍无效。

TimeQA-Hard strict primary 结果如下：

| Status | Method | Dataset/split | N | Seed | Normalized EM | Token F1 | Parse error | Run / commit |
|---|---|---|---:|---:|---:|---:|---:|---|
| `VERIFIED / SINGLE RUN / FORMAT FAILURE` | Qwen2.5-7B Direct greedy | TimeQA `human_test.hard` | 989 | 13 | 0.000 | 0.000 | 986/989 (99.697%) | `20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907` / `709f712...` |
| `VERIFIED / SINGLE RUN / FORMAT FAILURE` | Qwen2.5-7B CoT greedy | TimeQA `human_test.hard` | 989 | 13 | 0.506 | 0.506 | 969/989 (97.978%) | `20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14` / `50c6456...` |

该 run 使用完整 32,768 context，输入最大 24,584 tokens；没有样本命中 128-token 生成上限。错误聚合为 966 个 terminal JSON value 非 string、18 个 terminal-line violation、2 个 invalid JSON，说明 strict format following 是主要失败点。Primary parser 不在看过结果后放宽；任何 scalar-coercion 恢复值必须另列为 post-hoc sensitivity，不能覆盖这里的 0.0%。

CoT 输入最大 24,597 tokens，20 条通过 strict parser，约 5 条得到 exact match；969 个失败中有 907 个 non-string JSON objects、59 个 terminal-line violation、3 个 invalid JSON，17 条命中 512-token 上限。CoT 比 Direct 高 0.506 pp；989-record paired bootstrap CI 为 `[0.101,1.011]`，Holm p=0.030397。该非零差异只表示冻结 strict parser 下约五条 exact 与零条 exact 的差别，两者仍被 strict-format failure 主导，不能解释为 temporal reasoning 改进。结构审计没有在 907 objects 中找到白名单 `answer/final_answer/FINAL_ANSWER` 字段，因此没有根据 test raw output 定制恢复规则；这避免了 post-hoc parser 选择偏差。

## 10. 统计检验与实验结论

当前完成的是同一模型 revision 的 prompt-baseline 配对推断，以及 D-033 唯一允许的 provenance-bound Rule-Graph 对其 Direct 上游的配对推断；都不是三个训练 seed 的模型方差估计。所有差值为表中 candidate minus Direct；固定 10,000 resamples、bootstrap seed 20260723、percentile 95% CI、add-one 双侧 bootstrap sign p-value，并在每个 dataset/comparison 的全部报告指标内做 Holm 校正。

| Dataset / unit | Metric | Difference (pp) | 95% CI | Raw p | Holm p | Conclusion |
|---|---|---:|---:|---:|---:|---|
| TORQUE / 571 contrast groups | Question set EM | -3.034 | [-4.411, -1.709] | 0.000200 | 0.000800 | CoT lower |
| TORQUE / 571 contrast groups | Question set F1 | -3.292 | [-4.674, -1.954] | 0.000200 | 0.000800 | CoT lower |
| TORQUE / 571 contrast groups | Cluster exact | -0.350 | [-1.226, 0.525] | 0.562944 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Cluster F1>=0.8 | -0.350 | [-1.226, 0.525] | 0.562944 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Verifier question set EM | -1.416 | [-2.100, -0.790] | 0.000200 | 0.000800 | Verifier lower than Direct |
| TORQUE / 571 contrast groups | Verifier question set F1 | -1.389 | [-2.075, -0.758] | 0.000200 | 0.000800 | Verifier lower than Direct |
| TORQUE / 571 contrast groups | Verifier cluster exact | -0.175 | [-0.525, 0.000] | 0.758324 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Verifier cluster F1>=0.8 | -0.175 | [-0.525, 0.000] | 0.758324 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Self-Consistency question set EM | -0.270 | [-1.387, 0.885] | 0.682532 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Self-Consistency question set F1 | -0.500 | [-1.632, 0.687] | 0.395960 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Self-Consistency cluster exact | +0.350 | [-0.350, 1.051] | 0.442756 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | Self-Consistency cluster F1>=0.8 | +0.350 | [-0.350, 1.051] | 0.442756 | 1.000000 | no supported difference |
| TORQUE / 571 contrast groups | LLM-Graph question set EM | -14.295 | [-16.155, -12.517] | 0.000200 | 0.000800 | LLM-Graph lower than Direct |
| TORQUE / 571 contrast groups | LLM-Graph question set F1 | -14.721 | [-16.575, -12.937] | 0.000200 | 0.000800 | LLM-Graph lower than Direct |
| TORQUE / 571 contrast groups | LLM-Graph cluster exact | -1.576 | [-2.627, -0.701] | 0.001200 | 0.002400 | LLM-Graph lower than Direct |
| TORQUE / 571 contrast groups | LLM-Graph cluster F1>=0.8 | -1.576 | [-2.627, -0.701] | 0.001200 | 0.002400 | LLM-Graph lower than Direct |
| TORQUE / 571 contrast groups | Rule-Graph question set EM | 0.000 | [0.000, 0.000] | 1.000000 | 1.000000 | exact score tie |
| TORQUE / 571 contrast groups | Rule-Graph question set F1 | 0.000 | [0.000, 0.000] | 1.000000 | 1.000000 | exact score tie |
| TORQUE / 571 contrast groups | Rule-Graph cluster exact | 0.000 | [0.000, 0.000] | 1.000000 | 1.000000 | exact score tie |
| TORQUE / 571 contrast groups | Rule-Graph cluster F1>=0.8 | 0.000 | [0.000, 0.000] | 1.000000 | 1.000000 | exact score tie |
| TimeQA-Hard / 989 records | Strict normalized EM | +0.506 | [0.101, 1.011] | 0.015198 | 0.030397 | format-interaction only |
| TimeQA-Hard / 989 records | Strict token F1 | +0.506 | [0.101, 1.011] | 0.015198 | 0.030397 | format-interaction only |

TORQUE 结论是保留的负结果：在当前固定 prompt 下，CoT、CoT+Verifier 和 strict LLM-Graph 都显著降低题级 EM/F1，Self-Consistency 与 Direct 的差异没有统计支持，Rule-Graph 则在每个报告指标上精确打平 Direct。Verifier 的 77.8% strict index failure、Self-Consistency 的 494 个无效 samples、LLM-Graph 的 816 个 graph/answer failures 与 Rule-Graph 的 1,465 个保守 fallback 都按冻结规则保留，不能在看过 dev 后通过放宽 parser/rule 消除。LLM-Graph 和 Rule-Graph 分别只约束其 one-pass strict serialization 与 conservative explicit-rule v1。TimeQA 的统计非零不构成能力结论，因为 989 条中约只有 5 条 CoT strict exact，且 Direct/CoT 分别有 986/969 条 parser failure。主要 Kairos-vs-matched-baseline 比较仍需三个训练 seed；在完成前不作论文核心 claim 的显著性判断。

## 11. Interval/Graph 案例与失败分析

Rule-Graph 已提供不含样本原文的聚合失败画像：42.8% 因 question cue count、18.4% 因 unsupported semantics、31.4% 因无 positive-supported candidate、5.0% 因 anchor class ambiguity、1.3% 因 anchor absent（百分比以 1,483 题为分母，四舍五入）。仅 8 题替换 Direct 且全部 score-neutral，显示显式局部规则覆盖不足。Kairos interval 的成功案例、隐式关系、答案未更新、错误翻转与长上下文混淆仍待正式训练和逐例分析。

## 12. 审稿意见与新增证据映射

| Reviewer concern | Planned evidence | Status |
|---|---|---|
| 非标准 temporal 数据集 | TORQUE、TimeQA-Hard | TORQUE 六个正式 baselines、TimeQA 两个 prompt baselines 与 paired inference 均 VERIFIED；TimeQA 为 strict-format failure-dominated result |
| Baseline 弱/监督不公平 | CoT+Verifier、Self-Consistency、Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph | PARTIAL：CoT+Verifier/LLM-Graph VERIFIED negative；Self-Consistency VERIFIED no-supported-difference；Rule-Graph VERIFIED exact-score-tie；matched-supervision methods 仅获 development-only 审计许可，runner/training仍未完成 |
| marker/template artifact | explicit/implicit、held-out、answer-unchanged | PLANNED |
| 数据构造不透明 | 构造漏斗、哈希、人工审计 | PARTIAL：v0 漏斗/哈希 VERIFIED；用户确认的开发审计已重放，但两名独立人类 provenance 仍缺失，不能作为论文人工审计证据 |
| interval 可解释性不足 | interval/graph 可视化与消融 | PLANNED |

## 13. 论文修改建议

只有 `VERIFIED` 结果可以进入本节。实施阶段不自动修改 `main.tex`。

## 14. Run、Commit 与工件追踪

首个正式模型 run 为 Direct `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`，execution/aggregation commit 为 `eae442b...` / `61e96bc...`，prediction/evidence/manifest 与 metrics/manifest SHA 见 registry。第二个为 CoT `20260723T100959Z-cot-torque-dev-s13-05e077299faf`，execution/aggregation commit 均为 `21b4eea...`，metrics/manifest SHA 为 `7c14f0d4...` / `f8af11f7...`。第三个为 TimeQA Direct `20260723T103403Z-direct-timeqa-hard-s13-7ad791b6f907`，execution/aggregation commit 均为 `709f712...`，metrics/manifest SHA 为 `0e769343...` / `e05b4c01...`。第四个为 TimeQA CoT `20260723T111209Z-cot-timeqa-hard-s13-99f5a0a0aa14`，execution/aggregation commit 均为 `50c6456cf91123868398ba66c35e4879f06196d4`；prediction/evidence/manifest SHA 为 `1c738c4e...` / `b8a48c76...` / `d3f3d753...`，metrics/manifest SHA 为 `da4637f1...` / `e7646799...`。第五个为 TORQUE CoT+Verifier `20260723T142222Z-cot-verifier-torque-dev-s13-5edec173ee35`，execution/aggregation commit 均为 `e09a40fa9e192bb92971be61e795cbfabcb3117d`，prediction/evidence/manifest SHA 为 `a0993605...` / `d5a3c7fd...` / `7e84484e...`，metrics/manifest SHA 为 `a3577a84...` / `9e84a5ac...`。第六个为 TORQUE Self-Consistency `20260723T152808Z-self-consistency-torque-dev-s13-f3846fed035d`，execution/aggregation commit 均为 `b2f889b02893d99751ee9aabacdb3038a3456e1e`；prediction/evidence/manifest SHA 为 `f7faf46c...` / `5bde295d...` / `be449eeb...`，metrics/manifest SHA 为 `22ec0d76...` / `7857e01a...`。第七个为 TORQUE LLM-Graph `20260723T165048Z-llm-graph-torque-dev-s13-d52c57809644`，execution/aggregation commit 均为 `99209b4445df3a25fe678e3223cceac2c84e0041`；prediction/evidence/manifest SHA 为 `64a6c2e7...` / `f8a82934...` / `c2573cfb...`，metrics/manifest SHA 为 `6ce16c3a...` / `cbe181d4...`。第八个为 CPU-only TORQUE Rule-Graph `20260724T064739Z-rule-graph-torque-dev-s13-45fe8931e946`，execution/metrics commit 为 `dcc96b74634cc5b339da8e1fe21e5c2bb40c4866`；prediction/evidence/manifest SHA 为 `c46527bf...` / `c2d55bee...` / `ff2eb503...`，metrics/manifest SHA 为 `f4d4d1a4...` / `5ec53db7...`。通用统计实现 commit 为 `db6efe20a6317edac47343d1c713e9f4ec51263b`，Rule-Graph provenance exception/统计 commit 为 `fdc4f92132a4c2a72256297a4abddd05210dd265`；TORQUE CoT comparison SHA 为 `38646b82...` / `d1b08455...`，TimeQA comparison 为 `d1b5c7a9...` / `a44331e9...`，TORQUE verifier comparison 为 `fd2ae14c...` / `19f411f6...`，TORQUE Self-Consistency comparison 为 `8918c83b...` / `d1712be7...`，TORQUE LLM-Graph comparison 为 `234e2d7b...` / `691b3259...`，TORQUE Rule-Graph comparison 为 `ea5a5f80...` / `3e26f09b...`。所有完整值见 registry。数据获取与 processed/construction artifact 的完整追踪也以 registry 为准。

relation-only train data artifact 为 `PROC-P01-GSM8K-RELATION-ONLY-V1-20260723`，execution commit `5f0b31ed27b9aa582259a61bfc0f4b7dd11cd578`，JSONL/manifest SHA 为 `525e3b09...` / `4e22ff13...`；它不是 formal model run 或论文效果数值。

对应审计包为 `AUDIT-P01-GSM8K-RELATION-ONLY-200-20260723`，execution commit `6f56fcb31b07d0c2be095a4aa7d4ea69e2be72cb`，manifest SHA `da5d7fb0...`；这是待人工填写的 packet，不是审计结论。
