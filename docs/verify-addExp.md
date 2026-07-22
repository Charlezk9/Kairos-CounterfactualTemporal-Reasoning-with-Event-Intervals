# Kairos 补充实验技术与结果报告

> 状态：PLANNED
> 本文件是同伴作者引用补充实验的唯一汇总来源。当前已有一个 `VERIFIED` 数据准备工件，但所有论文效果数字仍仅为 `REPORTED`，尚无本项目 `VERIFIED` 模型实验结果。

## 1. 文档状态与执行摘要

- 当前阶段：Phase 01，data pipeline；GSM8K source/example production conversion 已完成
- 复现性质：independent reimplementation
- 已完成实验：无
- 当前结论：尚不能验证论文数值或新增 claim

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

## 5. 实验设计与超参数

冻结设计见 `docs/experiments/README.md`。任何偏离必须记录决定、时间和影响。

## 6. 数据构造统计与人工审计

GSM8K 固定 upstream revision `3101c7d5072418e28b9008a6636bde82a006892c` 的 source/example 转换已验证：

| Status | Artifact ID | Split | Source records | Canonical examples | Duplicate question/raw-record groups | Execution commit |
|---|---|---:|---:|---:|---:|---|
| `VERIFIED DATA ARTIFACT` | `PROC-P01-GSM8K-20260722` | train | 7,473 | 7,473 | 0 / 0 | `3e34c9c6da06a0364b84ef97492331e59a764a45` |
| `VERIFIED DATA ARTIFACT` | `PROC-P01-GSM8K-20260722` | test | 1,319 | 1,319 | 0 / 0 | `3e34c9c6da06a0364b84ef97492331e59a764a45` |

processed manifest SHA256 为 `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`；四个 ledger 的逐文件 SHA256 与 bytes 位于 `docs/ai-context/checkpoints/phase-01-gsm8k-conversion.md`。这里的 `VERIFIED DATA ARTIFACT` 不等于实验效果 `VERIFIED`。事件抽取、关系可靠性、反事实有效率、人工审计和 Cohen's kappa 尚未运行。

## 7. 已有实验复现结果

待运行。每行同时给出 `REPORTED`、重实现值、95% CI、差异、判定、run ID 和 commit。

## 8. 新增 Baseline 结果

待运行：Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph/Constraint-Rerank。

## 9. TORQUE 与 TimeQA-Hard 结果

待运行。两数据集仅用于冻结后的迁移评测。

## 10. 统计检验与实验结论

待三个 seed 和 paired bootstrap 完成后填写。负结果和无显著差异必须保留。

## 11. Interval/Graph 案例与失败分析

待填写成功案例与事件抽取、隐式关系、答案未更新、错误翻转、长上下文混淆等失败类型。

## 12. 审稿意见与新增证据映射

| Reviewer concern | Planned evidence | Status |
|---|---|---|
| 非标准 temporal 数据集 | TORQUE、TimeQA-Hard | PLANNED |
| Baseline 弱/监督不公平 | Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph | PLANNED |
| marker/template artifact | explicit/implicit、held-out、answer-unchanged | PLANNED |
| 数据构造不透明 | 构造漏斗、哈希、人工审计 | PLANNED |
| interval 可解释性不足 | interval/graph 可视化与消融 | PLANNED |

## 13. 论文修改建议

只有 `VERIFIED` 结果可以进入本节。实施阶段不自动修改 `main.tex`。

## 14. Run、Commit 与工件追踪

当前无正式模型 run。数据获取记录 `ACQ-GSM8K-20260722` 对应 provenance `482af857249b03d89c986dce96c9d38fc11cfd70` 和 archive SHA256 `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a`；processed artifact `PROC-P01-GSM8K-20260722` 对应 execution commit `3e34c9c6da06a0364b84ef97492331e59a764a45` 和 manifest SHA256 `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`。Bootstrap commit 为 `989634284e58b733e0bca2520fd0e7caad930e4c`；后续所有表格必须引用 registry 中的 run ID 和 SHA256。
