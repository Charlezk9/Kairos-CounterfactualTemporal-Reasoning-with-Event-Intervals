# Implementation Decisions

本文件只记录无法从论文材料唯一恢复、且会影响可复现性的决定。任何正式测试结果可见后的修改必须追加新条目，不得静默改写旧决定。

## D-001：论文版本权威

- 状态：FROZEN
- 决定：以 `docs/kairos.pdf` 作为待验证的主要实验规格；`docs/main.tex` 视为较早版本。
- 理由：PDF 含表 1–8、CoT+Verifier、held-out template、第二骨干和完整反事实附录；TeX 缺少这些内容且数值冲突。
- 影响：PDF 数值全部标为 `REPORTED`，在独立运行前不能称为 reproduced。

## D-002：复现口径

- 状态：FROZEN
- 决定：使用 independent reimplementation；不以测试集调参逼近论文数值。
- 理由：作者源码、subset ID、完整 prompt、候选池和训练配置均不可用。

## 待在正式编码前冻结

- 事件抽取和 closest-compatible-pair 的精确定义。
- 字符跨度到 tokenizer span 的对齐规则。
- `overlaps`、`contains`、`during` 的方向、逆关系和对称性。
- hidden-state 层、span pooling、graph pooling 和投影维度。
- backbone frozen/LoRA 的主轨与敏感性轨。
- candidate 数量、prompt、采样和 verifier 规则。
- temporal subset 筛选与 UpdateAnswer 的可靠性判定。

## D-003：阶段 1 数据语义

- 状态：FROZEN
- relation 方向：`relation(a, b)` 始终描述事件 `a` 相对于事件 `b` 的关系。
- inverse：`precedes <-> follows`、`contains <-> during`；`overlaps` 与 `unknown` 自逆。`overlaps` 是对称关系，其他非 unknown 关系均保留方向。
- split：优先保留官方 split。需要从训练集划 internal dev 时，以 UTF-8 canonical source ID 的 SHA256 前 8 bytes 按 big-endian 转整数并 `% 10`；余数 0为 dev，其余为 train。原样本及其全部反事实使用同一 source ID，因此不得跨组。禁止 Python `hash()`。
- 初版事件抽取：只处理文本中唯一且两侧非空的明确 marker；以最近 `.?!;` 边界内、marker 左右的去空白文本作为两个保守 event span，并保留字符偏移。多 marker、空侧、跨度重叠或嵌套、以及无法唯一对齐的文本必须返回结构化拒绝 reason。
- 初版可靠 marker：`before`、`after`、`earlier than`、`later than`、`prior to`。`while`、`when`、`until`、`then` 和隐式关系在 v0 中拒绝，不得把 v0 称为最终事件抽取器。
- counterfactual 改写白名单：只允许 `before <-> after` 与 `earlier than <-> later than`，并要求文本中 marker 唯一、替换后仍唯一且非目标文本逐字符不变。`prior to` 可检测但 v0 不生成反事实。
- UpdateAnswer：只有 task-specific deterministic updater 能证明新答案时才写 `known`。明确 earlier/later event-choice 且原答案精确匹配目标事件时可交换答案；关系型 yes/no 只有问题精确查询被改变关系时才由 truth table 更新。numeric、自由生成、无法唯一匹配或答案与目标关系无关时均标 `unknown`，从反事实 answer supervision 排除；禁止复制原答案充当 CF gold。
- scope：该决定只定义可测试的保守 v0 数据核心；扩展 parser 或隐式关系前必须追加新决定并重新审核。

## D-004：官方数据源与可识别性边界

- 状态：FROZEN BEFORE DOWNLOAD
- 原始四数据集的官方来源：
  - GSM8K：`https://github.com/openai/grade-school-math.git` @ `3101c7d5072418e28b9008a6636bde82a006892c`；使用 `train.jsonl`/`test.jsonl`。
  - MuSiQue：`https://github.com/StonyBrookNLP/musique.git` @ `922ac98f19a201998dbdae6d7f2887a5258dbdeb`；数据使用该 revision README 指向的官方 Google Drive archive `1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h`，不执行上游脚本。
  - StrategyQA：官方 archive `https://storage.googleapis.com/ai2i/strategyqa/data/strategyqa_dataset.zip`（读取时 ETag `f4ae9d9296c06f90d80aee1e4a25d58a`，Last-Modified `2021-01-07`）；代码/非官方 90/10 split 参考 `https://github.com/eladsegal/strategyqa.git` @ `1ba1e97452e189569357876f2854b01357ffbe37`。
  - 2WikiMultihopQA：`https://github.com/Alab-NII/2wikimultihop.git` @ `13800e5be57df1b4040b9b1588c6c811779e69e9`；数据使用该 revision README 指向的修正版 `data_ids_april7.zip`，不静默回退到旧 archive。
- 新增迁移数据集：
  - TORQUE：`https://github.com/qiangning/TORQUE-dataset.git` @ `ab27019cc6a317fde3c879900499f02acce8b16d`，Apache-2.0；使用有 gold 注释的官方 dev，test 注释已由作者移除。
  - TimeQA：`https://github.com/wenhuchen/Time-Sensitive-QA.git` @ `38b05989070c1168b2bef3d5a2656afeeba763dc`，BSD-3-Clause；冻结评测文件为 `dataset/human_test.hard.json`。
- 许可：GSM8K/StrategyQA 官方仓库为 MIT，MuSiQue 为 CC-BY-4.0，2Wiki/TORQUE 为 Apache-2.0，TimeQA 为 BSD-3-Clause；每个 upstream LICENSE 必须随 snapshot 保存并在 manifest 中记录。
- 可识别性：论文没有发布原始四数据集的 temporal subset IDs、完整筛选器或 counterfactual pair IDs。因此下载官方 raw data 不能使表 1–8的精确样本变得可识别；后续只能报告 independent reconstruction，不得用测试结果反向选 subset 追平论文数字。
- 下载协议：所有原始工件只写入 `/data0/hk_data/kairos-zx/data/raw/<dataset>/<revision>/`；先保存 archive/repository snapshot，计算 SHA256，然后解压到同 revision 下的 `extracted/`。禁止执行上游脚本，禁止将 raw data 纳入项目 Git。
- 可达性：MuSiQue Drive 与 2Wiki Dropbox 的 URL/ID 已由固定 commit README 确认，但 2026-07-22 在本机的 HEAD 请求超时，因此 availability 与 archive size 为 `UNVERIFIED`。实际获取失败时不得改用第三方镜像。

## D-004-A：GSM8K 直连快照获取与完成语义

- 状态：FROZEN BEFORE DOWNLOAD
- 运行范围：仅 `openai/grade-school-math` commit `3101c7d5072418e28b9008a6636bde82a006892c` 的 `codeload.github.com` TAR.GZ。该 URL 已是最终直连，本运行不允许 redirect，effective URL 必须与冻结 URL 逐字符一致。这一单源规则优先于 D-004 的通用 `--location` 门禁，不外推到其他源。
- curl：首参数必须为 `--disable`，禁止读取 `.curlrc`，不使用 netrc/config；只使用 `/usr/bin/curl` 7.68 已支持的选项。`--max-filesize 1073741824` 仅为辅助检查，必须同时以 `/usr/bin/prlimit --fsize=1073741824:1073741824` 对 curl 进程实施 1 GiB OS 硬上限，且仅 exit 0 才进入校验。
- 布局：stage 与 revision root 必须以 mode 0700 新建且不得复用。已验证的 stage archive 以 `O_CREAT|O_EXCL|O_NOFOLLOW` 独立复制为 revision root 下的 `source.tar.gz`，flush/fsync/关闭后重算 SHA256；不保留指向正式 archive 的可写 hardlink 别名。解压固定到 `extracted/`。
- 内容验证：固定相对路径为 `extracted/grade-school-math-3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/data/train.jsonl` 和 `.../test.jsonl`，条数分别为 7473/1319。在 `json.loads` 前按原始 bytes 限制每行最多 1,048,576 bytes；拒绝空行、非 object 以及空/非字符串 `question`/`answer`。
- 清单：`SHA256SUMS` 按 UTF-8 相对路径字节序覆盖 revision root 中当时的全部 regular files，只排除 `SHA256SUMS`、`completion-manifest.json`、固定 `completion-manifest.guard` 及本次精确私有临时文件；任何 symlink、特殊文件、缺失或协议外额外文件均使校验失败。
- completion：manifest 必须增加 `formal_tree_fingerprint_sha256`，对 fsync 后的正式树进行 canonical 绑定。指纹排除 revision root 本身、`completion-manifest.json`、固定 `completion-manifest.guard` 和本次精确私有 temp，只包含 `source.tar.gz`、`SHA256SUMS`、`extracted/` 及其嵌套目录/文件；每项按 UTF-8 path 排序，字段为 path、type、dev、ino、mode (`S_IFMT|S_IMODE` 整数)、nlink、size、`mtime_ns`、`ctime_ns` 与 content SHA，目录 SHA 为 null。revision root 跨流程只固定 dev、ino、mode、nlink；mtime/ctime 只在每个无预期发布操作的稳定阶段内比较。
- completion 持久 guard：成功格式永久保留 `completion-manifest.guard` 与 `completion-manifest.json` 两个同 inode hardlink，两者均必须 `st_nlink=2`，guard 不是可清理的 temp。顺序固定为：fsync 正式文件与 bottom-up 目录并稳定重扫→计算正式树指纹并写入排他私有 temp manifest→flush/fsync/关闭与回读全量校验→hardlink no-replace 为固定 guard→unlink 私有 temp 并 fsync root，形成已持久但不可消费的 guard-only 准备态→重验正式树/指纹→hardlink guard no-replace 为 final→fsync root→重验两名同 inode/nlink=2、正式树/指纹与独立 `verify_complete`。若最后 fsync 失败，调用必须报错；崩溃后若 final 未持久则只剩 guard 而被拒绝，若 final 已持久则两者所指 manifest 与正式树在该步骤前已 fsync 且可全量重验。下游必须校验这一两名协议、重算指纹与全清单，不得仅检查 final 存在。
- 生产路径：生产 CLI 在源码中固定 D-004-A 的 stage、revision root、revision 和所有输入/输出文件名，不接受任意路径；仅内部 API 与测试可注入临时根。生产操作从 `/data0/hk_data/kairos-zx` 根 dirfd 逐组件以 `O_DIRECTORY|O_NOFOLLOW` 打开/创建，并在关键操作期间长持有 stage/revision/extracted dirfd；archive inspect/extract 必须接收调用方已打开的 archive fd 和 destination-parent dirfd。禁止以 `resolve`、`os.walk` 或路径字符串重开替代该语义。
- 不变性：archive copy 全程持有源/目标 fd，复制前后重验源 fstat+SHA，目标关闭前后重验 fstat+SHA，且要求源/目标 dev+ino 不同、正式文件 `st_nlink=1`。全树使用 fd-relative no-follow 遍历/打开；每个 regular file 必须 `st_nlink=1`、hash 前后 fstat 不变，并在 completion 前后对比完整 path/type/fingerprint snapshot。拒绝 symlink、特殊文件、未知 hardlink、缺失/额外文件，以及不是任一清单路径祖先的额外空目录。
- 持久性：发布 completion 前必须 fsync 全部正式 regular files，并对目录树 bottom-up fsync，最后 fsync revision root；每个 fd 在 fsync 前后必须与当前稳定阶段 snapshot 的完整 fingerprint 一致。completion 私有 temp 在 root dirfd 下 `O_EXCL|O_NOFOLLOW` 创建；所有 link 前后核对 inode，`os.link` 显式使用同一 src/dst dirfd 与 `follow_symlinks=False`，已有 guard/final 必须 `EEXIST` 失败。内部只得忽略本次持有的精确私有 temp name+inode；任一私有 temp 遗留、guard-only、inode/nlink 不符或 fsync 失败均不得报告完成。
- helper 硬上限：不依赖调用者或 archive validator 的已有检查；自身流式强制 archive `<=1 GiB`、extracted regular bytes `<=2 GiB`、总成员/文件 `<=200000`、metadata 与 `SHA256SUMS` 各 `<=64 MiB`、UTF-8 路径 `<=4096 bytes`、component `<=255 bytes`、JSONL raw line `<=1 MiB`；第 limit+1 项立即失败，copy/hash 使用固定小块。
- 清单文法：路径必须为 NFC POSIX 相对 UTF-8，禁止反斜杠、CR/LF/NUL、Unicode control/format/surrogate 码点、异常 component 和 NFC collision。每行严格为 `64 lowercase hex + two ASCII spaces + relative path + LF`，按规范化路径 UTF-8 bytes 排序，精确解析并拒绝 duplicate/乱序，不允许宽松 split 或 glob 排除。
- HTTP 观测：严格 schema 必须包含且仅包含 curl exit code、HTTP code、fixed/effective URL、MIME 与 size_download；拒绝 bool、NaN、重复或额外字段。curl exit 必须为 0，其他值必须符合固定 URL/MIME 且 size_download 为严格整数并等于 no-follow fd 的 fstat，同时验证 1 GiB cap 和 gzip magic。
- 失败：任一失败保留 stage/partial revision root 作证据，不覆盖、清理、续传或在原目录重试。未通过 completion 全量校验的 revision 不可消费。
