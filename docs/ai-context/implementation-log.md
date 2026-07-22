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
