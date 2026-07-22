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

## D-005：GSM8K source ledger 与 canonical example 边界

- 状态：FROZEN BEFORE IMPLEMENTATION
- 范围：本决定只定义已获取 GSM8K raw JSONL 到 source ledger 和原始 `TemporalExample` 的确定性映射。不定义 temporal filtering、event extraction、counterfactual、candidate、training、evaluation normalizer 或 TORQUE/TimeQA schema。
- 两阶段结构：每个 raw 行恰好写一个 source-specific `Gsm8kSourceRecord`，保存 decoded `question`/`answer` 值；`TemporalExample` 仅以 `source_id` 引用 source record 并保存任务语义。`SourceProvenance` 只属于 source ledger，现有 `TemporalExample` 的 13 个 exact top-level keys 与 nested schema 在 v1 不变。
- generic provenance exact schema：`SourceProvenance` 只含 `relative_path: str`、`line_number: int`、`source_file_sha256: str`。`line_number` 不得为 bool 且 `>=1`；SHA 为 64 位 lowercase hex。Path 以 raw revision root 为基准，必须为 NFC POSIX 相对 UTF-8（总计 `<=4096` bytes，component `<=255` bytes），拒绝绝对路径、空/`.`/`..` component、反斜杠、CR/LF/NUL、Unicode control/format/surrogate 码点和任意 extra key/payload。
- 固定 source paths：train 为 `extracted/grade-school-math-3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/data/train.jsonl`，test 为 `extracted/grade-school-math-3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/data/test.jsonl`。Whole-file SHA/count/byte size 分别为 train `17f347dc51477c50d4efb83959dbb7c56297aba886e5544ee2aaed3024813465` / 7,473 / 4,166,206，test `3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14` / 1,319 / 749,738。
- 记录哈希：现有 `TemporalExample.source_sha256` 与 `Gsm8kSourceRecord.source_sha256` 统一表示 binary `readline()` 返回的完整 raw line bytes SHA256。实际 LF 存在时必须进入哈希；无 LF 的最后一行按实际 bytes 哈希。Whole-file SHA256 覆盖文件全部 bytes。GSM8K 本 revision 额外要求每个 production 行都以 LF 终止。
- source ID exact call：`make_stable_id("source", {"dataset":"gsm8k","revision":REVISION,"official_split":official_split,"relative_path":relative_path,"line_number":line_number,"source_sha256":source_sha256})`，其中所有 key 为 literal string，`official_split` 只为 `"train"`/`"test"`，`line_number` 为非 bool 正整数，其余值为上述固定/验证 string。Record ID exact call：`make_stable_id("record", {"source_id":source_id,"variant":"original"})`。
- source ledger exact schema：只含 `source_id: str`、`dataset: "gsm8k"`、`revision: REVISION`、`split: {"official": "train"|"test", "internal": "train"|"dev"|null}`、`source_sha256: str`、`provenance: SourceProvenance`、`question: str`、`answer: str`。所有 mapping 拒绝 missing/extra/duplicate key；字符串必须非空且 question/answer `strip()` 后非空；不容许 bool 充当 int。Official train 的 internal 由 `assign_split(source_id,"train")` 决定，official test 的 internal 必须为 null。Decoded `question`/`answer` 原值不 trim/改写；ledger 承诺值可逆，不声称恢复 raw JSON escape/whitespace/key order，raw bytes 由 line/file SHA 绑定。
- raw/parser contract：每个 raw JSON 只允许 exact `{question, answer}` 两个非空 string；严格 UTF-8、duplicate-key/non-finite 拒绝、raw line `<=1,048,576` bytes。Parser 规则只由 train 冻结，test 只在冻结后做无回显 conformance。Decoded answer 必须恰有一个 ASCII `####`，并可按 exact prefix/separator/suffix 重构；prefix/suffix 以 ASCII `SPACE/TAB/LF/CR/VT/FF` 集合 trim 后非空。Final suffix 不做数值、逗号、单位、符号、Unicode whitespace、大小写或其他 normalization。
- example exact mapping：`record_id` 使用上述 exact call，`source_id=ledger.source_id`，`dataset="gsm8k"`，`split=ledger.split`，`revision=REVISION`，`source_sha256=ledger.source_sha256`，`text=ledger.question`，`question=ledger.question`，`answers=(ascii_trimmed_suffix,)` 且恰一个元素，`answer_type=NUMERIC`，`events=()`，`relations=()`，`counterfactual_pair_id=None`。Source/example 文件都严格按 raw physical line 升序写入，同 split 同行 `source_id` 必须一对一，不另行排序或去重。
- 固定 flat output：target 为 `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/source-record-v1`，完成时只含五个 0600 regular/nlink=1 文件：`source-train.jsonl`、`source-test.jsonl`、`examples-train.jsonl`、`examples-test.jsonl`、`processed-manifest.json`。JSONL 每行使用 `canonical_json` 且以 LF 终止；manifest 是单个 canonical JSON object 加 LF。
- manifest exact top level：只含 `status: "COMPLETE"`、`schema_version: "kairos-gsm8k-processed-v1"`、`dataset: "gsm8k"`、`revision: REVISION`、`acquisition`、`adapter`、`sources`、`outputs`、`duplicates`。所有整数非 bool 且非负，所有 SHA/commit 为 lowercase 64/40 hex，所有 nested mapping exact 拒绝 missing/extra。
- manifest `acquisition` exact keys：`provenance_commit` 固定从已验 completion 读取且等于 `482af857249b03d89c986dce96c9d38fc11cfd70`，`completion_manifest_path` 固定为相对项目数据根的 `data/raw/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/completion-manifest.json`，`completion_manifest_sha256` 为 `d8861250e197bf04e1f24fee4dbb7bfe07194f485095f77cdcc8669412e35047`，`sha256sums_sha256` 为 `fb6bb5349ea5a620062f34cda78eb4faed2aa8a6ec9cf43ad54010904b813107`，`formal_tree_fingerprint_sha256` 为 `6b52e122a14c0f78baf3fc0b046b312b780518771828702acf074ab8ac95583f`。
- manifest `adapter` exact keys：`git_commit` 为执行预检确认的 clean HEAD 并等于 CLI `--adapter-commit`，以及固定 `source_record_schema_version: "kairos-gsm8k-source-record-v1"`、`temporal_example_schema_version: "kairos-temporal-example-v1"`、`id_version: "kairos-stable-id-v1"`、`split_version: "sha256-first8-mod10-v1"`、`answer_parser_version: "gsm8k-single-delimiter-ascii-trim-v1"`。
- manifest `sources` exact keys：`train`/`test`；每个值只含 `official_split`、`relative_path`、`sha256`、`byte_size`、`record_count`，值必须等于上述固定 source binding。Manifest `outputs` exact keys：`source_train`、`source_test`、`example_train`、`example_test`；每个值只含 fixed `path`、final `byte_size`、`record_count`、final `sha256`，path 分别为上述四个 JSONL 文件名，count 分别为 7,473/1,319/7,473/1,319。
- manifest `duplicates` exact keys：对 train/test 各记 `question_group_count`、`question_record_count`、`raw_record_group_count`、`raw_record_record_count`，具体 key 为加 `train_`/`test_` 前缀的 8 个字段。Group count 是在该 official split 中出现次数 `>1` 的 distinct decoded question 或 `(question,answer)` 组合数；record count 是所有这些 group 内记录数之和。这些数据只在规则冻结后报告，不用于去重或选规则。
- CLI/commit roles：生产接口固定为 `python -m kairos.gsm8k prepare --adapter-commit <40-lowercase-hex>` 与无参 `verify`，不接受任意路径。外部执行预检必须确认 Git clean 且 `HEAD == --adapter-commit`；helper 严格验证参数文法并写 manifest。Acquisition provenance 不由 CLI 传入，只能从已验 raw completion 读取并与上述固定值比对。
- acquisition/final binding：prepare 在创建 target 前调用固定 acquisition verifier，并校验 completion/SHA256SUMS/tree fingerprint、source path/SHA/size/count 全部固定值；四个 JSONL 发布后必须从 final name no-follow 重开计 count/byte size/SHA/schema/linkage，manifest 只能由 final 值构造。Manifest 发布前再运行 acquisition verifier 与 final-output 验证；独立 `verify` 每次也重放两类验证。
- immutable publication：target root 为全新 0700 no-follow 目录，完成时不含子目录。每个输出用私有 0600 O_EXCL/no-follow temp 写入、flush/fsync/close，重开验证后在同一 dirfd 以 hardlink no-replace 发布 final，再 unlink temp 并 fsync root；final 必须 `nlink=1`。`processed-manifest.json` 最后以同样语义发布并 fsync root，是唯一完成标志。禁止直接使用 overwrite 型 `write_examples()`。
- failure/verify：任一失败保留 partial target，不清理、覆盖或在原目录重跑。Verifier 要求 flat root 恰好五个固定 regular/nlink=1 文件，拒绝额外文件/目录、symlink、special、unknown hardlink、private temp、缺 manifest、非 COMPLETE、非 canonical manifest 或任一 acquisition/output/schema/ID/linkage 不一致。
- 可识别性：本决定只标准化官方 GSM8K source，不会恢复论文未发布的 temporal subset IDs，也不得用 test 结果反向调整 parser 或 split。

## D-005-A：GSM8K target 与 generic answer invariant 的最小兼容修订

- 状态：FROZEN BEFORE IMPLEMENTATION
- 触发原因：D-005 的 ASCII-only trim 会把仅由 NBSP、EM SPACE 等 Unicode whitespace 构成的 suffix 保留为非空 target，但现有不变的 13-key `TemporalExample` 要求每个 answer 的无参 `strip()` 后非空；两者在该极端输入上矛盾。
- 修订：先令 `target = suffix.strip(" \\t\\n\\r\\v\\f")`；仍要求 `target != ""`，并新增兼容性判定 `target.strip() != ""`。第二个判定只决定接受/拒绝，输出值仍必须是第一步的 `target`；禁止用 Unicode `strip()` 的结果替换、删除或 normalization 任何 Unicode whitespace。
- 边界样例：suffix 仅为 NBSP/EM SPACE 等 Unicode whitespace 时拒绝；`X` 与 Unicode whitespace 的任意组合在兼容性判定后按 ASCII-trim 结果逐字符保留。全部回归只使用人工合成 fixture。
- 作用域：本修订只精确替代 D-005 `raw/parser contract` 中“ASCII-trim 后非空”的 target 接受判定；不改动 generic `TemporalExample`、source ledger 原值、ID、split、manifest、publication 或任何其他 D-005 语义。

## D-006：MuSiQue official metadata boundary

- 状态：`METADATA-ONLY`；不是 acquisition、schema 或 adapter freeze。
- Kairos 论文事实：PDF 第 4 页 §5.1说明从 MuSiQue Ans 选择需要 temporal dependency 或可靠 counterfactual relation update 的 temporal subset；第 5 页 Table 1以 per-benchmark answer accuracy 报告 standard/CF，第 5 页 Table 2只给 subset 418、marker-pair coverage 56.0% 和 relation-label coverage 39.5%。论文只写原始 dev/test format，未标识 MuSiQue 的具体 split，也未给 subset IDs、hash、完整筛选器或重建映射。
- Kairos 指标边界：PDF/TeX 未把 MuSiQue 原结果定义为 EM/F1。`docs/experiments/README.md` 的 official validation、EM/F1 与 CF accuracy 是本项目的新增独立评测设计；不得用它解释原论文 Table 1 数字。
- 官方 source：固定上游为 [StonyBrookNLP/musique](https://github.com/StonyBrookNLP/musique) commit `922ac98f19a201998dbdae6d7f2887a5258dbdeb`（提交主题 `Update LICENSE`）。该 revision README 声明数据采用 CC BY 4.0，官方 Drive object ID 为 `1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h`，内容包括 MuSiQue-Ans/Full 的 train/dev/test 与 `data/dev_test_singlehop_questions_v1.0.json`；这些仍是 README provenance，不是本地 archive inspection。
- 许可：固定 revision 的 README 与 LICENSE 均为 Creative Commons Attribution 4.0。下载后仍须检查 archive 内许可/notice 与 seed-source attribution；派生 temporal subset 必须保留 attribution 和变更说明。
- 官方 split/规模：[TACL primary paper](https://aclanthology.org/2022.tacl-1.31/) 报告 MuSiQue-Ans 共 24,814 条 2–4 hop 问题：train 19,938、dev 2,417、test 2,459。官方 README 用 `musique_ans_v1.0_dev.jsonl` 举例并把 dev称为 validation；标准指标为 answer F1 与 paragraph-level support F1。实例抽象为 `(Q,C;A,P_s)` 并额外包含 gold decomposition `G_Q`。
- leakage：固定 README 明确 MuSiQue 由 SQuAD、T-REx、Natural Questions、MLQA 和 Zero Shot RE 的 single-hop questions 组合而成；若模型使用这些 seed datasets，必须排除 released dev/test single-hop IDs。该文件是后续训练 provenance 的强制门禁，不得忽略。
- Drive 观测：2026-07-22 对固定 view URL 的一次 no-follow/no-body HEAD 在 10 秒连接阶段以 curl error 28 超时，未收到 HTTP response。过滤管道的 shell 外层状态 0 仅来自 `sed`，不代表 curl 成功。Redirect authority、MIME、Content-Length、availability、archive byte size/SHA256/tree/schema 均为 `UNVERIFIED`。
- 安全实现：`archive_safety.py` 的 ZIP/TAR/TAR.GZ held-fd inspect/extract、成员/metadata/展开预算、路径规范化和 symlink/hardlink/special/sparse/duplicate/prefix-conflict 拒绝可复用；`acquisition.py` 将 GSM8K URL、revision、layout、schema 与 counts 写死，不得参数化挪用或放宽。
- 下一门禁：先由 Agent 1提交固定 URL/authority、OS 与应用层字节上限、超时、stage/revision absent、HTTP observation、failure preservation 的单次 acquisition/probe 方案。Agent 2批准前不重试网络、不下载、不读取 body、不创建 raw/processed、不实现代码。
