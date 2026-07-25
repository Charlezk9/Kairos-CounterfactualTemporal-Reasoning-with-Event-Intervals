# Implementation Log

## 2026-07-22 — Phase 00 started

- 只读确认项目仅有三份论文材料和空的 `src/`。
- 智能体 1完成实现入口与首批测试检查，未写入文件、下载或调用 GPU。
- 智能体 2批准阶段 0，要求先创建项目文档、后精简父级 AGENTS，并严格校验 GitHub Ed25519 host key。
- 已按单一职责创建项目 README、CURRENT、检查点、registry 和作者报告骨架，并最后精简父级 `AGENTS.md`；父级文件 SHA256 为 `2cad310e7cd803b2fdbc1ba593f5e9726b983a533ddcb553a3de72458ec001d4`。
- 已初始化 repository-local Git 配置；项目专用 SSH 返回 `Hi Charlezk9!`，GitHub host key 指纹严格匹配，remote 再次确认无 refs。
- 尚未下载数据，尚未运行实验。

## 2026-07-22 — Phase 00 completed

- 智能体 2对 21 个 staged 文件完成两轮审核；修正 hook 的 index-blob 大小检查、NUL 路径、`.bin`/HF token 防护和 SSH `UpdateHostKeys=no` 后给出 `APPROVED`。
- 创建并推送 bootstrap commit `989634284e58b733e0bca2520fd0e7caad930e4c` 到 `origin/main`。
- 创建工作分支 `experiment/reproduction-additional-evaluation`。

## 2026-07-22 — Phase 01 data core started

- 在 D-003 冻结 relation 方向、inverse、稳定 split、保守 marker、反事实改写和 `UpdateAnswer` 语义。
- 智能体 2审核实施边界：本子阶段只用 Python 标准库，不下载、不联网、不调用 GPU。
- 智能体 1在 `src/kairos/` 和 `tests/` 实现确定性数据核心；主智能体使用局部 Conda Python 独立复跑，包含严格嵌套 schema 拒绝的 24 项单元测试全部通过。
- 真实数据源、构造漏斗和 200 条人工审计尚未开始；不将本次开发测试记为正式实验。
- 智能体 2首次 staged-diff 事后审计阻止提交：发现无关 relation 查询可被误标 `known`，以及 canonical JSON 对非字符串 key 存在覆盖风险。修复、回归测试与复审完成前不提交。
- 两项缺陷修复后 27/27 测试通过；第二次审计又纠正了 checkpoint 的 `CONDARC` 路径和过期 `next_safe_action`。最终审计为 `APPROVED TO COMMIT`。
- 提交并普通推送 `111bb992f4371385dd9513f3a9d7ec161d16c313` (`feat(data): add deterministic temporal data core`)；本地与远端分支 SHA 一致，专用 GitHub Ed25519 `known_hosts` 仍为单行。
- 提交并推送提交后恢复状态 `bcc18139ebbe901a797c59d5120637cb3d644d8e`。
- 只读核对六个官方数据源、HEAD revision、许可与公开 split；发现论文未发布原始四数据集的 temporal subset IDs，已在 D-004 冻结 independent reconstruction 的可识别性边界。
- 未下载数据；已起草 0-GPU、8-GiB 硬限、顺序下载和 archive traversal 检查的获取门禁，等待智能体 2审核。
- 智能体 2核对数据源事实后首次阻止下载：原门禁未覆盖 archive 特殊 entry、展开字节、Windows 路径和裸 `curl` 解析到根目录外 Anaconda 的风险。已将标准库 validator、`/usr/bin/curl`、`.part`、host allowlist、archive bomb 限制与新空目录门禁写入检查点，等待复审。
- 数据源与采集门禁以 `b6491ec501ad18115bf5d3588cb250e01891d1e2` 提交并普通推送；该批准不包含下载。
- 智能体 1实现标准库 archive validator 及恶意 TAR/ZIP 回归测试；主智能体使用局部 Python 独立复跑 36/36 测试通过。尚未下载真实数据，等待 staged-diff 安全审计。
- 智能体 2首次 validator staged audit 为 `BLOCKED`：发现 ZIP/TAR 元数据在上限前无界物化、首次 SHA 后原地改写可混合新旧证据、以及源/目标父路径 symlink 与竞态逃逸。
- 智能体 1改为 ZIP EOCD 前置门禁、TAR 有界 header/metadata 扫描、检查/提取前后 SHA+fstat 复核和 root-anchored dirfd/O_NOFOLLOW 操作；主智能体独立复跑 45/45 测试通过，等待复审。
- 智能体 2第二次 validator staged audit 仍为 `BLOCKED`：EOCD 声明的条目数仍可被伪造以绕过实际中心目录数量门禁，且 local ZIP64 extra 未完整拒绝。
- 智能体 1新增逐条有界中心目录解析、EOCD 数量/字节范围精确匹配、central/local header 交叉核验以及 ZIP64/multi-disk 拒绝；主智能体独立复跑 47/47 测试通过，等待最终复审。
- 智能体 2第三次 validator staged audit 确认 forged-count 与 local ZIP64 已修复，但仍以可复现反例阻止提交：central directory 与 EOCD 之间可插入未计量 gap，local flags/compression/CRC/sizes 可与 central 不一致而通过前置门禁。
- 上述两个缺陷已交由智能体 1修复；修复及新的 pre-ZipFile 回归测试获得智能体 2批准前，不提交且不下载。
- 智能体 1已要求 central directory 紧邻 EOCD，逐字段比较 central/local version-needed、flags、compression、CRC 和大小，并保守拒绝 data descriptor；EOCD gap 和各字段不一致均有 pre-ZipFile 回归。主智能体将独立复跑 49 项测试后请求完整 staged 复审。
- 智能体 2独立重放 central-to-EOCD gap、central-only/local-only encryption/bit3 和其他 header 字段篡改，全部在 `ZipFile` 构造前被拒绝；49/49、hook/diff、secret/大文件/危险命令与 Git/SSH 检查通过，给出 `APPROVED TO COMMIT`。
- 已创建并普通 non-force 推送 `c57a133cf7c05f049ca16f8e43d29302480ec411` (`feat(data): add bounded archive validation`)；本地/远程 SHA 一致，GitHub Ed25519 `known_hosts` 仍为单行且指纹为 `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`。该批准不包含真实数据下载。
- 提交后恢复状态以 `8b5c64e653de0aaa87cf0dd43122d446ae395169` 普通推送；工作树 clean。GSM8K 固定快照 HEAD 预检为 200/`application/x-gzip`，effective host 为 `codeload.github.com`，/data0 当时可用 227100254208 bytes，raw root 与目标不存在。
- 智能体 1提交 GSM8K 单源执行单；主智能体在提交审计前删除 curl 7.68 不支持的 `--retry-all-errors`/`--no-clobber` 并修正为 revision-root + `extracted/` 布局。
- 智能体 2仍以 `BLOCKED` 阻止实际下载：`--max-filesize` 不是未知 HTTP 长度的传输硬上限，curl 默认可读 `.curlrc`，无跳转策略与检查点冲突，hardlink stage alias 可破坏正式归档，completion 存在不能证明完整，JSONL 缺单行上限。已在 D-004-A 冻结修复语义，仍未创建 raw 数据。
- D-004-A 以 `efb0cfd3add3b3b1bec6209ad5ab6066ec88aba0` 提交并普通推送，本地/远程 SHA 一致。智能体 1随后提交无网络 acquisition helper API/CLI 与 45–60 项故障测试计划。
- 智能体 2对 helper 实施预审为 `BLOCKED`：任意生产路径、path-based reopen、未完整的 copy/tree fingerprint、未拒绝 hardlink、completion 前未 fsync 全树、helper 未独立执行全部硬上限，以及清单路径文法未充分冻结。补充规格已追加到 D-004-A，代码尚未实施。
- D-004-A 增补以 `f3003a290d01f1ce72e77cb973c3aa9aefc3776a` 提交并普通推送。智能体 2复审后给出 `APPROVED TO IMPLEMENT`，范围仅两个 src/test 文件、标准库、无网络/GPU/raw 写入。
- 智能体 1实现固定生产布局的 acquisition helper 与 33 项测试；主智能体使用项目局部 Python 独立复跑 82/82 通过，CLI 只暴露 `validate-stage`/`finalize`/`verify`，raw root 仍不存在。等待 staged 事后安全审计。
- 智能体 2对 9-file staged snapshot 的事后审计为 `BLOCKED`：`safe_extract`/`inspect_archive` 仍通过绝对路径重开 revision，formal archive 关闭后重开未核对原目标 inode，空目录检查最坏 O(D×F)，completion 发布后才比较 snapshot 可留下未绑定 fsync 状态的 final。现有测试未覆盖这些反例，不提交、不下载。
- 智能体 2对四文件扩展修复计划首次阻止了 root fingerprint 自污染和删除 guard 后无法保证失效的顺序；D-004-A 改为排除 revision root 的 formal-tree fingerprint 与永久 fixed guard/final 同 inode、`nlink=2` 成功格式后，获得 `APPROVED TO IMPLEMENT`。
- 智能体 1新增 fd-native archive inspect/extract，修复 held revision/copy inode/O(D×F)/fsync publication 问题，并增加 canonical revision replacement、same-content inode swap、file/dir/root fsync、sparse limit+1、guard/fingerprint 回归。主智能体独立复跑 97/97 通过，raw root 仍不存在，等待完整 staged 复审。
- 智能体 2第二次 staged audit 仍为 `BLOCKED`：读取 completion pair 后替换两个 canonical names 仍可返回旧 manifest，整个 revision parent 重命名后 leaf-only 核对仍可成功，formal root 的协议外 regular file 可进入清单并通过，且实现使用 `.completion-manifest.guard` 和 temp 直接同时 link guard/final，未形成 D-004-A 规定的已 fsync guard-only 准备态。当前不提交、不下载。
- 智能体 2批准仅修改 acquisition 源/测试的第二轮修复；智能体 1新增显式 completion-pair context 与五态 protocol scan，对 pair 做首次/末次/返回前重绑，从 absolute project root 重建并比较全 revision chain，严核 formal root 三项集合，并实现 `completion-manifest.guard` guard-only fsync 后再 link final 的顺序。
- 新增 pair swap、intermediate parent/project-root replacement、protocol-extra file/directory 和 publication-event 回归；主智能体独立复跑 103/103 通过，raw root 仍不存在，等待第三次 staged 复审。
- 智能体 2第三次 staged audit 仍为 `BLOCKED`：`_verify_complete_fd` 结束后 pair fd 已关闭，外层做 revision binding 时替换 canonical pair 仍可返回旧 `COMPLETE`；最终 revision identity 比较漏掉 nlink，返回前新增目录可通过；`_CompletionPair.close()` 在首个 close 失败时不尝试另一 fd 且可掩盖活动异常。现有 103 项测试不足以放行。
- 智能体 2预审批准仅修改 `src/kairos/acquisition.py` 和 `tests/test_acquisition.py`；finalize 现在 completion 发布完成后捕获稳定阶段 binding，统一 bound verifier 长持 pair 到末次树扫描、canonical pair 重绑、完整 root/parent/revision fingerprint 链校验和返回线性化点。
- pair close 会预先清空对象状态并 best-effort 尝试两个 fd；独立 close 错误阻止成功返回，活动主异常不被 cleanup 错误覆盖。late pair/root/parent/leaf、late extra directory/regular file 和 close-failure 回归均通过。
- 智能体 1与主智能体分别使用项目局部 CPU 环境通过 110/110 完整测试；等待第四次 staged 审计，真实下载仍未批准。
- 智能体 2第四次 staged audit 仍为 `BLOCKED`：held `_CompletionPair.close()` 矩阵已通过，但 `_assert_completion_pair_binding` 中重开的 canonical final/guard 临时 fd 仍用串行 finally 关闭；final close 失败会跳过 guard close，且可覆盖既有 validation/open 异常。需补 canonical close 矩阵后再审。
- 智能体 2预审批准 canonical cleanup 聚焦修复；共享 `_close_fds_best_effort` 在调用者清空所有权后按 final→guard 尝试全部 fd，正常路径上拋首个 cleanup 错误，异常展开路径保留原 validation/open 异常。
- canonical final/guard/both close、active validation+双 close、partial final-open+guard cleanup 回归已增加；智能体 1和主智能体分别使用项目局部 CPU 环境通过 115/115 完整测试，等待第五次 staged 审计。
- 智能体 2第五次完整 staged audit 独立通过 115/115、62/62 acquisition 和 26/26 archive safety，重放全部 terminal namespace/pair/chain 及 held/canonical cleanup 攻击并给出 `APPROVED TO COMMIT`。批准仅覆盖当前 12-file snapshot 的提交/普通推送，不批准真实下载。
- 已创建并普通 non-force 推送 `ca759ac26bfc0bd64ee25a9732c20d8ea335a362` (`feat(data): add audited GSM8K acquisition finalizer`)；本地/远程 SHA 一致，项目专用 GitHub Ed25519 host key 仍为单行且指纹正确。真实下载等待单独执行预审。
- 提交后状态以 `482af857249b03d89c986dce96c9d38fc11cfd70` 普通推送；智能体 2另行批准仅固定 GSM8K codeload 对象的一次前台获取。
- curl exit 0，HTTP 200，effective URL 精确一致，MIME 为 `application/x-gzip`；4,447,003-byte archive SHA256 为 `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a`。
- `validate-stage`、`finalize`、主智能体 `verify` 和智能体 2独立 offline verify 全部 exit 0；SHA256SUMS 15/15，train/test 为 7,473/1,319。无残留进程、后台任务或 GPU 使用。
- 智能体 2批准只读 D-005 discovery；智能体 1以无 raw 回显的聚合方式确认 train/test exact schema、whole-file SHA、LF/UTF-8/JSON 结构和 train delimiter 可逆性。
- 现有 `TemporalExample` 不足以同时表达完整 raw answer 和提取 target；智能体 2批准起草二阶段 D-005：source-specific ledger 保存 decoded raw，generic compact provenance 定位，`TemporalExample` 只保存任务语义。实现和 processed 写入仍未批准。
- D-005 补齐 exact nested schema、fixed binding、literal ID payload、五文件 manifest、immutable publication 和 synthetic-only 测试矩阵后，智能体 2二轮只读审计给出 `APPROVED TO FREEZE/PLAN IMPLEMENTATION`。本门禁只批准文档冻结提交与智能体 1下一步实施计划，仍不批准编码、测试执行或 processed 写入。
- 智能体 1的四文件实施计划主动发现 ASCII-trim 与 generic Unicode-whitespace invariant 的极端冲突。智能体 2因不得在代码中暗选行为而给出 `BLOCKED`；D-005-A 只增加不输出 Unicode-strip 结果的兼容性接受判定，待文档复审。
- 智能体 2复审确认 D-005-A 仅替代 target acceptance 极端边界，不改 generic schema 或其他冻结语义，因而给出 `APPROVED TO FREEZE/REPLAN IMPLEMENTATION`。下一步仍只是修订实施计划。
- 四文件 adapter 实施在首次 staged audit 被阻止：direct close 会泄漏/掩盖异常，terminal canonical target 仍有可替换窗口，故障矩阵也不完整。智能体 1统一 owned-resource cleanup、收紧终态线性化并增加竞态回归。
- 第二次 staged audit 确认实现缺陷已修复，但阻止了未落在真实边界的 close/content 伪覆盖。后续改为真实 temp 篡改、已验 fingerprint 绑定 publication 和 artifact-aware 真实 close cleanup，并固化 canonical FD 已打开后的 target replacement 攻击。
- 智能体 1与主智能体独立通过 targeted 63/63 与 full 166/166；智能体 2第三次 staged audit 给出 `APPROVED TO COMMIT`。批准仅覆盖四文件实现快照和普通推送。
- 已创建并普通推送 `892b486b6bfb522de0aae4a675b651baf7ae1868` (`feat(data): add immutable GSM8K source adapter`)；本地/远程一致，未运行 production conversion。
- adapter checkpoint 文档以 `3e34c9c6da06a0364b84ef97492331e59a764a45` 普通推送；智能体 1随后提交一次性 production conversion 执行单，智能体 2给出仅覆盖一次 prepare、成功后一次 verify 与非内容验收的 `APPROVED TO EXECUTE`。
- clean HEAD、upstream 0/0、target absent、181 GiB `/data0` 余量、0 GPU 与 2 CPU 线程门禁通过。固定 `prepare --adapter-commit 3e34c9c...` 与独立无参 `verify` 各执行一次且均 exit 0。
- `PROC-P01-GSM8K-20260722` 生成四个 ledger 与 manifest；train/test 均保持 7,473/1,319 一一对应，八个 duplicate statistics 均为 0。智能体 2完成 namespace/权限/Git/进程事后审计并给出 `POST-AUDIT APPROVED`。
- 智能体 1提交 MuSiQue 单源 discovery 计划；智能体 2分别批准仓库内论文只读核对和仅官方 GitHub/ACL/Drive HEAD 的 metadata discovery，明确禁止数据 body、Range、clone、写文件和第三方镜像。
- 官方 metadata 确认 fixed commit `922ac98f...`、CC BY 4.0、Drive object ID、MuSiQue-Ans/Full train/dev/test、dev-as-validation、官方 answer/support F1、24,814 条 split 规模和 seed single-hop leakage 门禁。Kairos 的 418 条 temporal subset 仍不可识别。
- 固定 Drive view URL 的唯一 no-follow/no-body HEAD 在连接阶段 curl error 28；未收到 HTTP response。可达性、size/MIME/hash/tree/schema 均保持 `UNVERIFIED`，未下载或创建 MuSiQue 工件。
- 智能体 1随后实现固定 65,536-byte MuSiQue response-body probe helper；四轮 staged 边界审计依次补齐真实 prlimit/procfd、whole-PGID、selector/pipe、双 fsync、三态和 publication fatal fail-close 语义。智能体 1最终 targeted 92/92、full 258/258，主智能体独立 full 258/258；智能体 2给出 `APPROVED TO COMMIT`。
- 精确两文件实现提交为 `cacbcbcc504ebfcb77c1e6329edc69f05de9a7e2`。本工作未执行 production、真实 curl/Git preflight、网络或 MuSiQue 数据访问；当前 0775 trusted-ancestor 门禁会在联网前 fail closed，等待独立执行策略审查。
- 智能体 1与智能体 2只读复核 fixed root、调用链和 `namei` mode 后确认：不 chmod、不改代码/信任策略且不扩大允许根时不存在合规执行路径。MuSiQue acquisition 记为 `BLOCKED_POLICY / TRUSTED_ANCESTOR_CONFLICT`，不是 ProbeStatus 或远端不可达证据；未创建 stage、未发请求。
- 智能体 2批准下一步仅编写 StrategyQA 官方 GCS source 获取策略计划；HEAD/GET、下载、production、raw/processed 写入和代码修改仍未批准。
- StrategyQA 计划将 `official-20210107` 明确为 project label，以 fixed GCS URL、strong ETag token、UTC date 和首次 GET 后 SHA/bytes 联合绑定；ZIP、成员、schema、MIME 和 license 保持未验证。ZIP 缺 license 时只能 `STAGED_LICENSE_BLOCKED`。
- 智能体 2给出 `APPROVED TO DOCUMENT / PLAN IMPLEMENTATION`，但 held-dirfd 模型仅是 StrategyQA 候选；下一份实施计划必须解决 0775 初始根假设、全 PGID 和三个小流独立上限。未批准代码、测试、Git preflight、网络或数据写入。
- StrategyQA 固定 transfer/stage helper 经两轮 staged 事后审计。首轮在 75/75 targeted 和 333/333 full 通过后仍因 FD close retry、unknown marker 绑定前读取和 manifest pair 越过 commit point 而 `BLOCKED`。
- 智能体 1修复所有权转移、marker inode 早拒绝和 pair pre-commit teardown；智能体 1与主智能体分别通过 targeted 79/79 和 full 337/337，无 production 路径、测试临时目录或残留进程。
- 智能体 2对精确两文件 staged snapshot 给出 `APPROVED TO COMMIT`；已提交 `978ba4dea0792061340d0ec97241caa1efd6d6f2` (`feat(data): add bounded StrategyQA acquisition stage`)。`RUNTIME_REDIRECT_SEMANTICS_VERIFIED=False` 保持，未执行 HEAD/GET、网络、production、数据写入或真实 Git/NSS/ACL。

## 2026-07-23 — D-011 explicit-marker construction v0

- 两文件 staged 实现仅组合已冻结的 extraction、rewrite 与 UpdateAnswer；完整 `KNOWN` original/CF pair 原子保留，`UNKNOWN` 仅留内存诊断且不产生 dangling record。
- 合成 targeted 和全仓测试通过，智能体 2事后审计状态为 `POST_AUDIT_APPROVED / COMMIT_PENDING`。实现、blob、测试、临时目录和非实验边界的唯一详细证据见 `checkpoints/phase-01-temporal-construction-v0.md`。
- 本次未读取 production data，未写持久构造记录，未建立正式 run、模型指标或论文结果。
- 精确 2 code + 7 docs 共9路径快照已以普通 non-force commit `24ce15d40bd038d61bd6581ed2bc260072468c12` 提交，parent 为 `62d1b21b39b4ceb05a83500c45181a3c1e1ac5e1`；项目专用 SSH 普通推送后 local/remote branch head 一致。
- 该提交的状态是 `COMPLETE / DEVELOPMENT_VERIFICATION_PASSED`，仍非数据构造运行、模型实验、formal run 或论文证据。

## 2026-07-23 — D-012 construction audit schema v1

- 在 base HEAD `2b7e3f03726fd1abf59fa18867593458f38e5b34` 上实现只存内存的 frozen typed audit record；source/test blob 分别为 `1bb1b167f3af5424b8fe199b2c9057c51638957f` 与 `3bfa86de8deb0b15ececad698808583acfe7aa45`。
- 两轮 staged 复审修复集中于显式 primitive scalar parsing、无载荷异常、D-011 optional/crosslink/role 矩阵和完整 synthetic regression；未扩展到 persistence、JSONL、manifest 或 CLI。
- 最终 fresh targeted 为 24/24、0.193s、exit 0；唯一一次 full suite 为 373/373、13.020s、exit 0，full temp `/data0/hk_data/kairos-zx/.tmp/d012-full.r2tb5NGaAd` 已清理。智能体 2事后裁决为 `POST_AUDIT_APPROVED`。
- 精确九路径实现快照已以普通 commit `633618b6dc81503b7c5794380e8fa524f37c4c4c` 提交，parent 为 `2b7e3f03726fd1abf59fa18867593458f38e5b34`；普通 push 后 local HEAD、origin 与 upstream 一致。
- 当前状态为 `COMPLETE / DEVELOPMENT_VERIFICATION_PASSED`。下一步仅由智能体 1起草 P2 persistence/publication 的 documentation-only 计划供智能体 2审核；本项没有 formal run、production data read、network、model/GPU、artifact、paper metric 或 `VERIFIED` 实验 effect claim。

## 2026-07-23 — D-013 construction audit persistence v1

- 按最新项目指令切换为单智能体直接推进，安全路径、资源、clean-commit 和 pre-commit 门禁不变。
- 新增固定 GSM8K source binding 的 immutable JSONL/manifest publisher、offline verifier 和 observer；实现 commit 为 `63737a3b0da741a5e4ee08ff32c2fd4b8dde7bc5`，已普通推送。
- focused 8/8 与 clean-commit full 381/381（13.234s）通过；GPU 禁用、CPU 线程 2、cache/temp 均位于 `/data0/hk_data/kairos-zx`。
- 本里程碑没有创建 production audit、run ID 或论文数值。下一步实现 fixed production driver，再从 clean commit 运行 train/test 构造并登记实际 funnel。

## 2026-07-23 — GSM8K construction v0 production

- fixed driver commit `c8f5cecf...` 的首次 train 调用在 target 创建前发现 completion hardlink binding 不匹配并 fail closed，target 保持 absent。根因是 P2 合成 fixture 未模拟 acquisition 的 guard/final 同 inode nlink=2 协议，同时 completion digest 常量少一位。
- `3944bb56...` 严格绑定双链接 completion pair、修正 64-hex digest 并加入回归；focused 10/10、clean full 388/388，production source gate 通过。
- 从 clean `3944bb56...` 各执行一次 train/test，随后独立 offline replay 均为 `STRUCTURALLY_VERIFIED`。train 7,473 → temporal 1,845 → extracted/reliable 370 → valid CF/retained 0；test 1,319 → 361 → 79 → 0。
- 工件 ID 为 `PROC-P01-GSM8K-CONSTRUCTION-V0-20260723`。零 retained 是冻结 alias-safety/numeric-update 约束的负数据结果，不是模型指标；不得在查看 test funnel 后静默调整 v0。

## 2026-07-23 — Manual official-source acquisition

- clean `7eca38e...` 上资源门禁通过后并行下载 StrategyQA official GCS ZIP、TORQUE fixed-commit TAR.GZ 和 TimeQA fixed-commit TAR.GZ；均 HTTP 200，archive bytes/SHA/magic 固定，未执行上游代码。
- TORQUE 28 members/22,163,721 bytes 与 TimeQA 40 members/454,095,594 bytes 通过 held-FD safety inspection/extraction。只读 schema 聚合确认 TORQUE dev 145 passages/1,483 answer-bearing QA、test 无 answer；TimeQA hard 为 989 条 exact-key JSONL。
- StrategyQA archive 使用通用策略禁止的 ZIP data descriptor，因此保留 staged archive、不解压、不放宽 guard。2Wiki corrected literal URL 一次 GET 在连接阶段 curl 28、无 response，未重试或回退。
- 四个 raw revision 均写入 canonical 0600 acquisition manifest；本阶段不产生模型 run 或论文效果指标。

## 2026-07-23 — TORQUE/TimeQA transfer-evaluation contract

- `e89bbfd...` 新增固定 revision/SHA 的只读适配器、TORQUE span-set 指标、两种 contrast consistency 口径，以及 TimeQA 官方 normalizer/EM/F1 的语义复刻；合成测试与完整回归分别为 12/12、400/400。
- 首次 clean production smoke 在任何结果返回前 fail closed，揭示 TimeQA-Hard 有合法空字符串 gold。聚合只读确认共 159 条，随后将“target 列表非空但 target 可空”加入合成契约。
- 修复提交 `8b57ffe...` 的 focused 13/13、full 401/401 通过。clean production read-only smoke 验证 TORQUE 1,483 QA/571 local groups 与 TimeQA-Hard 989 unique records；未创建预测、metric artifact、run ID 或 GPU 任务。
- TORQUE 主 consistency 固定为组内每题 set EM=1；F1>=0.8 作为显式 sensitivity 同时输出。详细证据唯一来源为 `checkpoints/phase-01-transfer-eval-contract.md`。

## 2026-07-23 — Prediction artifact contract

- `f12efa0...` 实现 model-agnostic run spec、stable run ID、canonical config/prediction JSONL、manifest-last/no-replace 发布、两次 clean Git gate 和 fixed-source offline replay。
- focused 12/12、full 413/413（13.163s）通过；提交后的真实隔离 Git gate 在 exact HEAD 上通过。测试覆盖 coverage/type、篡改、rehashed reorder、权限、hardlink/symlink 和 partial publication。
- 未调用 production publisher、未创建 `/data0/.../artifacts`、未登记 formal run 或模型指标。详细合同唯一来源为 `checkpoints/phase-01-prediction-artifacts.md`。

## 2026-07-23 — Kairos tensor core and Pair-MLP

- `c178d15...` 实现 event/answer span mean pool、positive interval、论文 8 维 geometry、五类 relation graph、masked graph pool、graph-aware candidate scorer、三项 loss，以及无 interval 的 Pair-MLP same-supervision baseline。
- focused 14/14、full 427/427（13.087s）通过，包含 full forward/loss/backward；GPU 隐藏、CPU 2 线程，未加载 Qwen 或 production data。
- 该提交只覆盖可训练 tensor core。backbone/token alignment/prompt/candidate/evaluation runner 仍待实现，工程默认和非结果边界见 `checkpoints/phase-03-kairos-tensor-core.md`。

## 2026-07-23 — Transfer prompts, greedy generation and first formal baseline

- `994dfb8...` 固定 Direct/CoT prompt、terminal `FINAL_ANSWER` JSON parser、candidate dedup，以及 Qwen chat-template literal-content 和字符到 token offset 对齐。
- `f45c9e8...` 增加固定本地 Qwen revision 的 resource-bounded greedy generation，并将 raw response、parse status、input/output token counts 写入 prediction artifact v2；`eae442b...` 显式清除 greedy 模式下的 inactive sampling controls。最终 focused generation 7/7、full 457/457（13.355s）。
- 无权重 token preflight 确认 TORQUE Direct/CoT 最大 323/336 input tokens；TimeQA Direct/CoT 最大 24,584/24,597，均在 32,768 context 内。TimeQA 有 253 条超过 8,192、79 条超过 16,384，后续不得使用较短默认 context 静默截断。
- clean `eae442b...` 上完成首个正式运行 `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`。TORQUE public dev 1,483 题全部发布，1,441 parsed、42 parse errors；独立 CPU/offline replay 通过并得到 set EM/F1 15.644/16.070、两种 cluster consistency 均 1.576（百分数）。
- prediction/raw-evidence 工件和所有 SHA 已登记。在该检查点 machine-readable metrics artifact 尚未发布，因此结果暂记为 `PRELIMINARY / PREDICTIONS VERIFIED`；下一节记录其后续升级。

## 2026-07-23 — Immutable metrics artifacts and Direct promotion

- `61e96bc...` 实现 prediction-bound `metrics.json`/manifest-last publication：发布前后均重放完整 prediction/source，绑定 aggregation commit/time 和四个 prediction SHA，独立 verifier 重新聚合而不是信任已存数值。
- focused 8/8、full 465/465（13.916s）通过；测试覆盖 no-replace、双 Git gate、中途 prediction 变化、rehashed metric 篡改、权限、hardlink 和额外文件。
- 首次 production 调用因手工输入的 expected commit SHA 错误在首次 Git gate 处 fail closed，目标目录未创建；使用实际 clean HEAD `61e96bc58cd13bb4f5dc997ee678b86e81d9044a` 重试后发布成功。
- Direct metrics SHA `c508305a...`、manifest SHA `1187e24d...`；fresh CPU/offline replay 完全一致。结果升级为 `VERIFIED / DETERMINISTIC SINGLE RUN / NO COMPARATIVE CI`。

## 2026-07-23 — TORQUE CoT formal baseline

- clean `21b4eea...` 上通过资源门禁后，仅使用 physical GPU 4 运行 TORQUE public dev 全量 CoT greedy（seed 13、batch 8、`max_new_tokens=512`）。1,483 条用时 1,167.092s，峰值 GPU bytes 15,833,449,984；结束后 GPU 4 回到 11 MiB/0%。
- 全量 prediction artifact 发布成功：1,452 parsed、31 parse errors、输入 155--336 tokens、总生成 214,717 tokens。fresh CPU/offline prediction replay 通过。
- prediction-bound metrics 发布并由另一 fresh 进程重放：set EM/F1 12.610/12.778，两个 cluster consistency 均 1.226（百分数）。完整 SHA 见 registry/checkpoint。
- CoT 相对 Direct 的描述差为 EM -3.034 pp、F1 -3.292 pp；这是保留的负结果，不修改 prompt 或生成预算。paired bootstrap 未完成前不作显著性判断。

## 2026-07-23 — TimeQA-Hard Direct formal baseline

- clean `709f712...` 资源门禁后，仅用 physical GPU 4 对 989 条 `human_test.hard` 运行 Direct greedy（seed 13、batch 1、`max_new_tokens=128`）；完整 32,768 context、不截断，输入 590--24,584 tokens。用时 1,878.176s，峰值 GPU bytes 20,207,448,576，结束后 GPU 释放。
- prediction artifact 全量发布并通过 fresh CPU/offline replay：3 parsed、986 parse errors、总生成 8,998 tokens。metrics artifact 随后发布并由另一进程重放，strict normalized EM/token F1 均为 0.0%。
- 只聚合错误类型、不打印响应的审计发现：966 个 terminal JSON value 非 string，18 个违反 terminal-line 约束，2 个 invalid JSON；0 条命中 128-token 上限，920 条生成不超过 16 tokens。失败主要是冻结格式不遵循，不是 max-token 截断。
- 主结果不放宽 parser、不重跑覆盖。未来 scalar-coercion 只能作为明确的 post-hoc sensitivity，不能替换 strict primary；完整身份和 SHA 见 registry/checkpoint。

## 2026-07-23 — TimeQA-Hard CoT formal baseline

- clean `50c6456...` 资源门禁后，仅用 physical GPU 4 运行 989 条 CoT greedy（seed 13、batch 1、`max_new_tokens=512`、完整 context、不截断）。用时 9,262.608s，峰值 GPU bytes 20,210,055,680，结束后 GPU 释放。
- prediction artifact 全量发布并经 fresh replay：20 parsed、969 parse errors、输入 603--24,597 tokens、总生成 226,010 tokens。metrics 双重 replay 得 strict EM/token F1 均 0.505561%。
- 聚合错误为 907 non-string JSON objects、59 terminal-line violations、3 invalid JSON；17 条命中 512-token 上限。无值/样本输出的 whitelist audit 发现 907 objects 均无 `answer/final_answer/FINAL_ANSWER` 字段。
- 因此不从 test raw outputs 设计 object-unwrapping parser，post-hoc sensitivity 暂缓。CoT 只比 Direct 高 0.506 pp，且两者都属于 strict-format failure；不作显著性或时间推理能力结论。

## 2026-07-23 — Paired bootstrap and Holm inference

- `db6efe2...` 实现两侧 prediction/metrics-bound 的 immutable statistical artifact；SplitMix64、10,000 resamples、percentile 95% CI、add-one 双侧 bootstrap sign p-value 与 dataset 内 Holm 校正全部固定。focused 6/6、full 471/471（14.807s）通过。
- TORQUE 以 571 个 contrast groups 重采样。CoT-Direct 的 question EM/F1 为 -3.034/-3.292 pp，95% CI 分别 `[-4.411,-1.709]` / `[-4.674,-1.954]`，Holm p 均 0.000800；两项 cluster 差异 -0.350 pp，CI 跨零且 Holm p=1。
- TimeQA 以 989 records 重采样。strict EM/F1 差均 +0.506 pp，CI `[0.101,1.011]`、Holm p=0.030397；该差异只代表约五条 strict exact 和严重格式失败下的 parser interaction，不支持推理能力 claim。
- 两个 manifest-last 工件均通过另一 fresh CPU/offline process 重算，SHA 与首次发布一致；完整身份、数值和限制见 `checkpoints/phase-03-paired-bootstrap.md` 与 registry。

## 2026-07-23 — TORQUE CoT+Verifier formal baseline

- `e09a40f...` 实现 gold-free Direct/CoT candidate verifier、严格 terminal JSON index、候选等价 skip 和 parse-error Direct fallback；focused 6/6、full 477/477（14.508s）通过。
- clean commit 上 preflight 确认 503/1,483 等价无需调用，余下 980 条为 193--514 input tokens。仅用 physical GPU 4 前台运行 166.261s，峰值 16,113,932,800 bytes，结束后 GPU 释放。
- 218 个 index parsed、762 个回退；正式 EM/F1 14.228/14.681，cluster 两口径均 1.401。prediction/metrics fresh offline replay 通过。
- 对 Direct 的 group bootstrap 显示 EM/F1 -1.416/-1.389 pp，CI 均低于零、Holm p=0.000800；cluster 差异不显著。负结果和严格格式限制均保留，完整证据见对应 checkpoint/registry。

## 2026-07-23 — GSM8K relation-only supervision v1

- construction v0 的 zero-retained 根因是 numeric CF answer 全部不可证明，因此没有复制 original answer 或伪造 CF gold；D-022 冻结为部分 relation-supervision bridge。
- `17137bb...` 新增 exact in-memory pair schema、稳定身份、deterministic extraction/rewrite replay 与显式 `unavailable-relation-only` CF answer 状态；schema 不含 counterfactual answer 字段。
- synthetic focused 8/8、最终 full 485/485（14.542s）通过。此前一次 full run 的旧 persistence fingerprint 测试出现瞬时失败，isolated replay 与最终 fresh full 均通过，已在 checkpoint 留痕。
- 未读取 production train/test，未发布 JSONL/manifest、未训练或产生指标。下一步先实现 train-only immutable publisher/offline verifier。

## 2026-07-23 — GSM8K relation-only official-train artifact

- 旧 source stability gate 将 read-updated atime 误判为内容变化；`3fbe53f...` 改为绑定 identity/content metadata 并排除 atime，focused 11/11、full 486/486 通过。
- `5f0b31e...` 新增 fixed train-only immutable publisher/verifier；artifact-focused 8/8、combined 27/27、full 494/494 通过。CLI/production layout 无 test split 或路径参数。
- 资源门禁为 `/data0` 155 GiB free、memory 229 GiB available；未触碰 GPUs 1/2/3/6 的既有 VLLM，GPU 显式禁用、CPU 2 线程。
- clean commit 上一次发布与 fresh offline replay均通过：7,473 → no marker 5,628 / extraction rejected 1,475 / rewrite rejected 0 / retained 370。JSONL/manifest SHA 为 `525e3b09...` / `4e22ff13...`。
- 工件只含 original answer 和 original/inverted relations，CF answer unavailable/masked；没有 test 工件、训练或模型指标。下一步准备 200-pair 两人盲审包。

## 2026-07-23 — Relation-only 200-pair human-audit packet

- `6f56fcb...` 实现 train-only Hamilton proportional stratification、seed-bound SHA256 selection/presentation、两份全 null reviewer templates、instructions 和 immutable full replay；focused 7/7、combined 23/23、full 501/501 通过。
- clean commit、155 GiB `/data0` free、229 GiB memory available、GPU disabled 下发布 200/370 条：after/follows 259→140，before/precedes 111→60。
- fresh replay 复现 items/reviewer-A/reviewer-B/instructions/manifest SHA；模板没有人工判断，包状态为 `HUMAN REVIEW PENDING`，不能计算 kappa/validity或解锁训练。

## 2026-07-23 — TORQUE Self-Consistency formal baseline

- `f6a43f3...` 实现固定 8-sample CoT sampling、strict sample aggregation、确定性 plurality/tie-break、全无效 sentinel 和 raw-envelope vote replay；最终 batch-8 execution commit 为 `b2f889b...`。focused 8/8、full 509/509 通过。
- 初始 batch-1 尝试因明显低 GPU 利用率在 artifact 创建前主动中断并释放 GPU，状态为 `INTERRUPTED_PREFLIGHT / NO ARTIFACT`；batch-4/8 smoke 均不保留工件。正式运行从 clean commit 用 physical GPU 4 前台执行 3,778.678s，发布 1,483 条、11,864 samples、1,714,292 generated tokens。
- 494 个 sample parse failures 被排除；1,482 题仍有 valid vote，仅 1 题八次全失败。prediction 与 metrics 经独立 CPU/offline replay，EM/F1 15.374/15.569，cluster 两口径 1.926。
- 对 Direct 的 571-group bootstrap 显示 EM/F1 -0.270/-0.500 pp、cluster +0.350 pp，四项 CI 均跨零且 Holm p=1.0。保留为无可支持增益的 single-seed negative result；完整工件、SHA 与资源证据见对应 checkpoint/registry。

## 2026-07-24 — TORQUE LLM-Graph formal baseline

- `6c30c83...` 实现 gold-free strict graph JSON prompt/parser、五类关系、answer-event binding、greedy runner 与 source-bound replay；cleanup 误删 runtime `Tensor` import 后，第一次 GPU smoke 在 shape check fail closed、无 artifact。`99209b4...` 修复后 focused 6/6、full 515/515 通过。
- token preflight 为 271--452 input tokens。固定 8-record smoke 虽 8/8 parse failure，但不据 dev 观察放宽已提交 schema。clean `99209b4...` 上 physical GPU 4 前台运行 1,927.260s，发布 1,483 条，峰值 16,012,927,488 bytes，结束后 GPU 释放。
- 667 parsed、816 parse errors、348,766 generated tokens；仅 1 条触及 768-token 上限。prediction/metrics fresh replay 得 EM/F1 1.349、cluster 0。无值错误聚合显示 graph line 位置 336、non-exact event span 293 为主因。
- 对 Direct 的 571-group bootstrap 四项 CI 均低于零；该显著负结果只约束严格 one-pass serialization 实现，不反驳 graph 方法或构成 Kairos claim。完整证据见对应 checkpoint/registry。

## 2026-07-24 — Qwen-to-core synthetic training adapter

- `14f7104...` 新增 strict original/counterfactual/candidate training batch，把 Qwen-compatible last hidden state、event/candidate span masks 接到既有 Kairos 与 Pair-MLP，并共用 answer/relation/CF-relation loss。
- 仅 valid candidates 进入 backbone；Qwen base decoder 固定 `use_cache=False`、不保留全层 hidden states。LoRA rank/alpha/dropout 与七类 attention/MLP projection targets 被只读冻结/验证，未注入 PEFT 或加载权重。
- focused 7/7、full 522/522（14.955s）通过，覆盖两个 core 的 full forward/loss/backward、padding/target/CF group、hidden contract、LoRA coverage 与 trainable-state strict round-trip。
- 本项只用 CPU synthetic tensors，不读取 production data/model，不运行训练或产生指标；持久 checkpoint、optimizer/RNG/resume/runner 仍待实现，人工审计门禁不变。

## 2026-07-24 — Reviewer remediation freeze and 2Wiki source recovery

- `7287cfb...` 将剩余 reviewer-response 计划写入可恢复 checkpoint；`08d847b...` 以 D-027 冻结证据优先级、2Wiki 来源顺序、relation-only claim 与 TimeQA follow-up 边界。
- clean `08d847b...` 上每次请求前通过资源门禁；`/data0` 约 145 GiB free。四个官方 Dropbox 对象/route 均在 20--30 秒连接阶段 curl 28、HTTP 000、0 header/body bytes。
- 固定 unofficial HF mirror `xanhho/2WikiMultihopQA@6ef4eb1...` 随后报 OS `Network is unreachable`，没有 repository metadata 或数据文件。五个私有 stage 只保存空 header 与 mode-0600 无样本 attempt manifest，未发布 formal raw、未删除旧失败工件。
- 2Wiki 状态升级为 `DEFERRED_NETWORK / SOURCE_UNVERIFIED`，不是永久不可用结论。TORQUE reviewer-response 关键路径继续，下一步为无 network/model/GPU/production data 的 synthetic resumable trainer。

## 2026-07-24 — Resumable synthetic training execution

- `9cb192e...` 以 D-028 冻结两组 AdamW、effective batch 32、BF16、scheduler、RNG、optimizer-boundary progress 与 manifest-last/no-replace checkpoint 合同；明确不授权 production 数据、7B、PEFT、GPU 或正式训练。
- `7772f7c...` 实现 `kairos.training_execution`。Kairos 与 Pair-MLP 均通过 CPU BF16 uninterrupted 与 one-step interrupted/save/fresh-object restore/resume 的逐项等价验证。
- 首轮等价测试发现 interval mask 在 autocast 下把已量化 BF16 坐标提升回 FP32；mask 改为投影坐标 dtype 后保持精确端点恒等式，FP32 行为不变。
- focused 20/20（1.830s）、full 528/528（18.175s）通过；GPU 隐藏、CPU 两线程，测试 checkpoint 已清理，没有 production 数据/模型读取、正式工件或指标。
- 当前执行层只消费调用方已物化的 deterministic batches；未实现 sampler/data/candidate/CLI/PEFT/7B/GPU，且 checkpoint 未绑定 frozen backbone revision 或 production data manifest，因此不得用于正式训练。

## 2026-07-24 — Checkpoint artifact identity binding

- 局部 Conda 环境只读检查为 `peft_spec=none` / `peft_version=none`，package cache 无 PEFT；遵守依赖扩充需另行授权的既有约束，没有安装包、加载模型或使用 GPU。
- `ee66675...` 以 D-029 冻结 fixed Qwen revision/`SHA256SUMS`、data revision/manifest 和 Kairos/Pair-MLP core-type binding；`1d80f5d...` 将 config/state/manifest 原子升级为 v2 并实现该身份对象。
- 保存前从 live adapter 推导 core；resume 在打开 `state.pt` 前校验 live core 与 expected commit/config/binding，mismatch 不改变 model/optimizer/scheduler/dataloader RNG。
- focused 8/8（1.735s）、最终 full 530/530（17.316s）通过；GPU 隐藏、CPU 两线程、最大 RSS 499,964 KiB，测试工件清理。环境没有 pytest，故使用仓库既有标准库 unittest，不为测试扩充依赖。
- binding 只记录调用方给定的 immutable identity；production runner 仍需独立验证实际模型和 data manifest。sampler/batch/candidate/CLI/PEFT/7B/GPU/formal run 仍不存在。

## 2026-07-24 — Project-local PEFT injection and GPU smoke

- 用户授权后，`c37d86a...` 以 D-030 冻结 PEFT 0.14.0、wheel-only/no-deps 安装和注入合同。官方 wheel 为 374,831 bytes、SHA `2f04f3a...`；仅安装到项目环境，核心依赖版本未变，manifest SHA `0b76d845...`，`pip check` 通过。
- `c68c77a...` 实现 lazy exact-version import、七类 Qwen targets 注入、LoRA-only trainable/配置检查、cache/gradient-checkpointing 门禁及 PEFT wrapper decoder routing。real tiny-Qwen forward/backward、optimizer、state 和 checkpoint/resume 均通过。
- focused 9/9 + 9/9、full 533/533（16.746s）通过。首次 GPU smoke 在 model load 前因 CUDA memory-stat initialization 次序失败，无模型/工件；资源复核后不改变代码重试。
- clean `c68c77a...` 上 physical GPU 4 用 fixed local 7B 和 synthetic batch 32 完成 one-step：392 LoRA tensors、loss 1.96875、gradient norm 203.842285、peak allocated/reserved 15,920,307,712 / 15,934,160,896 bytes；进程退出 0，GPU 回到 11 MiB。
- 本项不读取 production 数据、不保存 checkpoint/预测/指标，不是 formal run 或论文结果。正式训练仍受人工审计和 sampler/manifest/runner 缺失阻塞。

## 2026-07-24 — Deterministic training manifest and resume cursor

- `d592e5c...` 冻结 D-031：候选/gold 身份、source-order corpus、三轮 SHA256 rank、effective-batch 32 尾部策略和 exact cursor 必须进入同一 canonical manifest；所有真实样本每轮恰好一次，末尾不足仅允许 0--31 个显式 repeat slots。
- `8de516d...` 实现 `kairos.training_plan`。manifest 绑定 source artifact/revision/commit、去重候选 content SHA/origins、gold target/injection、epoch slots、micro-batch/optimizer-step 与 checkpoint data SHA。from-dict 只能通过最小输入重建后 exact equality。
- planned execution 在 optimizer 调用前验证本 window 的 example/candidate IDs、candidate mask 和 answer targets；只物化当前 window，避免预先携带全部三轮 tensors。cursor 精确记录 consumed real/repeat slots、completed epochs 和 next example，只接受 optimizer boundary。
- 首轮 focused 在 test collection 因调用了不存在的执行器别名失败，未运行测试逻辑或模型；改用现有 `run_optimizer_steps` 后 focused 7/7（0.904s）、full 540/540（17.853s）通过，最大 RSS 537,360 KiB。GPU 隐藏，未读取 production 数据/模型，无工件或指标。
- 该实现消除 sampler/manifest/cursor 工程缺口，但候选生成/物化与 formal runner 仍未实现；两人 relation audit 未完成，正式 Kairos/Pair-MLP 训练仍禁止。

## 2026-07-24 — TORQUE Rule-Graph formal baseline

- `13dbbd9...` 冻结 D-032 gold-blind candidate/rule/trace/fallback 合同；`dcc96b7...` 实现 fixed Direct/CoT/8 raw-SC replay、保守 explicit-before graph、候选集打分和完整离线验证。focused 9/9、full 549/549 通过。
- clean `dcc96b7...` 上以 CPU 两线程、GPU 隐藏前台发布 1,483 条。1,475 条选择 Direct，5 条 CoT，SC samples 0/4/7 各 1 条；1,465 条有保守 fallback。prediction/metrics fresh replay 通过，EM/F1 15.644/16.070、cluster 两项 1.576，与 Direct 精确相同。
- 通用统计门禁先在工件创建前拒绝不同 model revision。`9a05fd2...` 以 D-033 冻结仅限 provenance-bound Rule-Graph 的窄例外，`fdc4f92...` 实现；focused statistics 8/8、full 551/551 通过，无关跨模型及错误上游 manifest 仍 fail closed。
- 正式 571-group/10,000-resample comparison 经全新进程重放：四项差值与 95% CI 均为 0、Holm p=1。8 条改写的逐题 metric contribution 都未变化；这是保留的无提升结果，不是 Kairos effect 或 constraint reasoning 的一般结论。

## 2026-07-24 — Synthetic relation training materialization

- `db1ea50...` 以 D-034 冻结 relation-only 候选去重/gold 注入、source identity、chat/event/candidate token alignment、双向 relation target、单 micro-batch 物化和 immutable training-plan publication 合同；明确 CF answer target unavailable，production audit gate不变。
- `9a58155...` 实现 `kairos.training_materialization`：typed pair与候选 proposal形成 D-031 corpus binding，fake fast tokenizer只按需物化一个含 repeat slots 的 CPU `TrainingBatch`，original/CF 两组 event/relations 与 original answer target严格对齐。
- 同提交实现 `kairos.training_plan_artifacts`：allowed `/data0` 私有 root、clean Git双门禁、plan/manifest no-replace+fsync、完整 deterministic reconstruction、hash/bytes/namespace/mode/tamper replay。第二门禁失败保留 plan-only partial，不伪装完成。
- focused 9/9、full 560/560（17.727s）通过，最大 RSS 537,672 KiB，GPU 隐藏、CPU 两线程；测试临时 plan全部清理。没有 production record/candidate/tokenizer/model读取，没有正式 plan、训练或论文指标。

## 2026-07-24 — Synthetic human-audit result gate

- `fbf7de2...` 以 D-035 冻结 completed A/B submissions、authors adjudication、hash binding、overall-valid Cohen's kappa与 adjudicated-validity 门禁；AI 不得读取、填写或裁决 production 模板。
- `832e755...` 实现 `kairos.relation_audit_results`：exact 200 行 canonical JSONL、slot/ID/order/schema/Boolean/overall 校验、agreement-preserving adjudication、2×2 confusion、逐字段 agreement、κ unavailable处理与包含等号的 0.80/0.95 阈值。
- 提交前自审发现 frozen result 的嵌套 mapping 仍可变，改为深层只读并增加回归断言；hash 与 canonical output 因而不能被返回后的调用方修改。
- focused 5/5、最终 full 565/565（17.876s）通过，GPU 隐藏、CPU 两线程。测试只有 synthetic filled bytes；production packet/templates 未读取，正式 κ/validity/result artifact/训练许可均不存在。

## 2026-07-24 — Two independent AI pre-reviews

- 用户要求两个智能体分别独立填写并由用户检查准确率；`023490e...` 先冻结 D-036，将输出隔离为 `AI-A/AI-B`，禁止冒充 human Reviewer、进入 D-035 或解锁训练。
- 两个智能体只读同一 200-item immutable packet，分别只写独立 JSONL并报告未读取对方或 production templates。主智能体在两者完成后才读取，机械验证 exact 200 行、source order/ID、canonical schema、Boolean与overall AND。
- AI-A/AI-B SHA为 `efaf43bb...` / `a579fd69...`；overall true 115/174。逐字段 agreement：event spans 139、original relation 197、CF relation 196、grammar 185、non-target 200、overall 137。
- AI-only diagnostic observed/expected agreement为0.685/0.5555，κ=0.2913386；event-span 61项分歧为主。负面一致性结果原样保留，等待用户核查，不作自动 adjudication或人类门禁结论。

## 2026-07-25 — User-resolved development training copy

- 拉取 `3dbc80e...` 的 Claude Code双智能体预审；两者只有6项 overall分歧。用户逐项裁决：lines 2/6 grammar false，81/99 CF relation false，119/198 CF relation true；resolution SHA `77087c1e...`，已在 `4dba42a...` 推送。
- 用户声明本地人工审计与最终196 valid/4 invalid标签完全一致，因此条件 human κ=1.0、validity=98%。允许目录搜索未发现 raw formal-A/B文件，`src/ab-reviewer-web/results/`只有README；正式 artifact状态仍 pending。
- 按用户授权从370条 verified relation-only source按原顺序复制并排除4个已知无效 pair，得到366条 development-only训练数据。数据/manifest SHA为 `4b5fec2b...` / `f24a8e8e...`；namespace/mode/canonical/hash/source-order/filter/count和状态均重放通过。
- 工件明确 `d035_training_gate_passed=false`、formal/paper eligible=false、CF answer unavailable/masked；可用于探索性训练，但指标必须 PRELIMINARY。

## 2026-07-25 — User-attested development audit publication

- 独立严格审计经四轮复核批准 `USER_ATTESTED / DEVELOPMENT ONLY / INTERNAL-DEV / NOT PAPER-ELIGIBLE` 计划；两名独立人类 provenance 缺失时不允许正式 human-audit 或论文指标表述。
- raw A/B 与 sidecar 已复制到 mode-0700/0600 private intake并逐文件重放；随后用普通提交从 branch tip 删除，既有 remote history不重写。intake metadata SHA为 `a518d507...`。
- clean `06eff003...` 实现 D-038 additive agreement projection与 immutable publisher；任一 overall分歧硬失败，不向 D-035 伪装 authors adjudication。focused 9/9、full 569/569（18.773s）通过，GPU隐藏、CPU两线程。
- 单次发布与新鲜进程重放通过：196/200 valid，observed/expected 1.0/0.9608，conditional κ=1.0，validity=0.98，Wilson 95% `[0.949713,0.992196]`；projection/result/manifest SHA为 `ae8bc796...` / `df7310e8...` / `c501f376...`。
- 结果固定 `human_independence_verified=false`、`paper_metric_eligible=false`。下一步只构造 train330/internal-dev36 开发分区，不产生论文结论。

## 2026-07-25 — Audit-bound 330/36 development partition

- `3c026858...` 实现从370条 relation source、audit items与 D-038 projection全链重放的 v2 publisher；4个排除 pair只能由 audit ID join推导，不接受手写 exclusion list。
- pure partition tests 3/3、full 572/572（18.842s）通过。production derive得到366条、train330/internal-dev36；完整数据 SHA `4b5fec2b...` 与旧副本相同。
- clean commit 单次发布后新鲜进程重放通过；train/dev/partition/manifest SHA为 `073b4c65...` / `63041d7e...` / `cfc1894e...` / `0631e02c...`，全部0700/0600且nlink=1。
- internal-dev禁止 optimizer/gold injection/selection/tuning，所有结果仍 `NOT PAPER-ELIGIBLE`；CF answer继续 unavailable。

## 2026-07-25 — Frozen GSM8K relation candidate pool

- D-042 在 clean `67f995d...` 上通过 focused 6/6 与 full 578/578；第二次8条 mechanics smoke完成15,296 tokens、25 parse errors且不发布工件。
- production 前台任务使用 physical GPU 5/full UUID，完成 train330/internal-dev36 的 Direct、CoT与8个SC位置：726,637 generated tokens、1,334/3,660 typed parse errors。结束后 GPU 回到11 MiB，Git仍与origin同步 clean。
- manifest-last工件经新鲜 GPU-hidden进程完整重放；train/dev candidate SHA为 `e5955a6a...` / `101fd821...`，manifest为 `bdf45755...`，权限0700/0600、nlink=1。
- train有3个空生成池，internal-dev为0；没有修改 immutable gold-blind工件。独立 runner审计因此阻塞训练，D-043先冻结显式 train-only gold-singleton策略并等待复审。
