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
