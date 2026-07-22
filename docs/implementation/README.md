# Implementation Specification

本项目根据论文公式进行独立重实现。所有论文未说明的选择必须先登记到 `../ai-context/decisions.md`。

## 数据记录

统一 JSONL 记录包含：来源 ID、dataset/split/revision/SHA256、context/question/answers/answer type、事件字符与 token span、关系两端/标签/marker/provenance、反事实 pair/template/前后关系与答案，以及 explicit/implicit、answer-changing/unchanged、长度和事件数。

关系集合固定为 `precedes`、`follows`、`overlaps`、`contains`、`during`、`unknown`。`unknown` 不进入 relation loss。阶段 1的方向、逆关系、保守 marker、split 和 UpdateAnswer 规则已冻结在 `../ai-context/decisions.md` 的 D-003，并由测试覆盖。

## Kairos 流水线

1. 从输入中提取事件 mention，并对齐 tokenizer span。
2. 对 span hidden states 池化得到事件表示。
3. 投影 start 与 `softplus(duration)`，令 `end=start+duration`。
4. 从区间端点和差值构造 geometry features，预测 pairwise relation。
5. 对有效 pair 的关系分布做 masked graph pooling。
6. 编码共享候选池，通过 graph-aware scorer 选择答案。
7. 以 answer、relation、counterfactual relation 三种损失训练。

匹配 Baseline 必须复用相同数据、候选、解析器和指标，避免实现差异造成不公平比较。

## CLI 与 manifest

计划接口：`prepare-data`、`generate-candidates`、`train`、`evaluate`、`aggregate`、`build-author-report`。每个正式 run 必须写 manifest，包含 Git commit/dirty、配置哈希、数据与模型 revision、seed、资源、起止时间、输出路径和 SHA256。

正式实验只能从 clean commit 启动；dirty-tree smoke test 标为 `development-only`，不能进入论文结果。

## Raw archive safety

`kairos.archive_safety` 为 ZIP/TAR/TAR.GZ 提供标准库全量检查与新目录流式提取。它在标准库物化 archive 前逐条有界解析 ZIP 中心目录，要求中心目录紧邻 EOCD，且 EOCD 数量和字节范围与实际条目精确一致；central/local 的 version-needed、flags、compression、CRC 和大小逐字段交叉核验，data descriptor、ZIP64 与 multi-disk 均保守拒绝。TAR header/PAX/GNU metadata 也在物化前受成员与字节上限约束。模块拒绝 traversal、Windows/反斜杠路径、异常/超长/重复/前缀冲突成员、链接、设备、FIFO、sparse、加密 ZIP 和超预算 archive。源与目标必须为绝对无 symlink 路径；同一源 FD 在检查/提取前后重算 SHA/fstat，目标树使用 root-anchored dirfd 和 `O_NOFOLLOW|O_EXCL`。该模块不使用 `extractall`/`getmembers`，不保留上游 owner/permission，不覆盖已有路径。它只处理已经过 host/下载字节门禁的本地 archive，不负责网络获取或递归扫描嵌套 archive。

## GSM8K acquisition finalization

`kairos.acquisition` 是 D-004-A 的离线 finalization/verification helper 候选实现，不实现网络传输。生产布局、revision、URL、路径、上限和文件名固定在源码中；CLI 仅接受 expected archive SHA256 与 clean Git commit，提供 `validate-stage`、`finalize`、`verify`。它使用 held-fd archive API 对 stage HTTP 观测、独立 archive copy、GSM8K 固定树/JSONL、全文件 SHA256SUMS 和 completion manifest 执行严格校验，并以 fsync 后 formal-tree fingerprint 与固定 guard/final 同 inode pair 绑定 completion。第三和第四次 staged 审计发现的外层生命周期、terminal fingerprint、held/canonical pair cleanup 问题已修复；115/115 开发测试与第五次完整 staged 审计已通过。当前批准仅覆盖实现快照的提交/普通推送；真实获取需单独执行门禁。无锁 verifier 的保证以末次成功复核为线性化点，不声称返回后文件系统持续不变。安全与失败语义的唯一详细来源是 `../ai-context/decisions.md` D-004-A。

## GSM8K source adapter test matrix

D-005 是 source-ledger/canonical-example 语义的唯一来源；本节只保存实现验收矩阵。

- Generic provenance/schema：exact keys/types，NFC POSIX relative path，1-based line number，bool-as-int、absolute/traversal/backslash/NUL/control 拒绝，64-hex file/line SHA，canonical byte stability，ID 对每个输入字段敏感。
- Exact schema：`SourceProvenance`、`Gsm8kSourceRecord`、nested `split` 的 missing/extra/null/enum/type 矩阵；现有 13-key `TemporalExample` 不变，provenance 只出现在 source ledger。
- Raw reader：合成 LF/no-final-LF 行的 byte hash 区分，但 production GSM8K 任一无 LF 行必须拒绝；1 MiB limit+1，strict UTF-8/JSON object/duplicate key/non-finite/exact two strings，blank/empty/extra/missing 拒绝，whole-file hash/byte size/count/revision/path mismatch fail closed。
- GSM8K parser：合成 single delimiter golden reconstruction；zero/multiple delimiter、empty ASCII-trimmed prefix/suffix 拒绝；只 ASCII whitespace trim；逗号、正负号、小数、单位和 Unicode whitespace 不做 normalization。按 D-005-A 另覆盖 NBSP-only/EM-SPACE-only suffix 拒绝，以及 `X` 与 Unicode whitespace 组合接受且逐字符保留。禁止把 raw test 样本复制进 fixture。
- Mapping/linkage：source/record ID 稳定且字段敏感，official train 与 internal train/dev 确定，official test 无 internal split，source ledger 值可重建 decoded raw fields，example `source_id` 一对一引用 source ledger，重复 question 不静默去重。
- Determinism/statistics：四个 JSONL 保持 raw physical line 顺序，source/example 同行 ID 链接，两次合成 fixture conversion 字节一致；train/test 的 question/raw-record duplicate group/record 八个统计按 D-005 口径验证且不触发去重。
- Manifest/CLI：exact top-level/nested schema、fixed values/path/count/byte size/SHA，acquisition commit 与 `--adapter-commit` clean HEAD 角色不混淆，非 40-hex、dirty/mismatched execution preflight 拒绝，禁止 path argument。
- Immutable publication：target/final/temp 已存在、symlink/hardlink/special/extra file 或目录/private-temp 拒绝，O_EXCL/no-replace，四文件及 manifest 每个 create/write/fsync/reopen/link/unlink/root-fsync 阶段故障保留 partial，manifest 未成为唯一完成标志前 verifier 拒绝。
- Verifier/integration：从合成 raw fixture 生成 flat source/example train/test 两类 ledger和 manifest，重算 schema/count/byte size/SHA/ID/source linkage，任一输出篡改、缺失或额外文件/目录拒绝；acquisition completion 在 prepare 前后的替换/篡改、fingerprint/provenance/source binding mismatch 拒绝。
- Formal gate：全套测试只用局部 CPU 与 `/data0` temp/cache；正式 raw 转换只能在包含已审实现的最新 clean checkpoint HEAD 与第二次执行预审后运行一次。
- Fixture/privacy gate：所有 golden/reject/integration 只用人工合成内容，禁止回显、复制或提交真实 raw/test question、answer、raw line 或 per-record hash。

## GSM8K source adapter implementation status

冻结的 D-005/D-005-A 已在 commit `892b486b6bfb522de0aae4a675b651baf7ae1868` 实现。实现使用固定路径、held dirfd/no-follow parent chain、target `mkdirat` no-reuse、O_EXCL private temp、verified fingerprint-bound hardlink publication、manifest-last completion、fresh acquisition gates 与 raw/source/example physical-line lockstep replay。统一 cleanup 保证尝试关闭全部 owned FD/file object，且 cleanup 错误不覆盖活动主异常。

Agent 1与主智能体分别通过 targeted 63/63 和全仓 166/166；Agent 2在两轮阻塞修复后给出 `APPROVED TO COMMIT`。详细审计证据见 `../ai-context/checkpoints/phase-01-gsm8k-adapter.md`。该状态不表示 production processed 已生成，也不授权运行固定 CLI。

## 首批测试

- schema 缺字段和非法 relation 拒绝。
- 稳定 ID、重复处理同哈希、source/CF pair 不跨 split。
- marker 方向、inverse、overlap/contain/during。
- 字符与 token span round trip。
- template 只改变目标关系并拒绝冲突。
- numeric、extractive、yes/no 和 answer-unchanged updater。
- duration 为正且 `end=start+duration`。
- geometry feature 顺序、shape 和符号。
- unknown/padding 不进入 relation loss/graph pool。
- 候选去重、解析、SC tie 和 eval 禁止 gold。
- LLM-Graph malformed JSON。
- checkpoint 保存恢复和逐样本指标重聚合一致。
