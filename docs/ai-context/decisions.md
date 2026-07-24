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

## D-007：StrategyQA runtime redirect 原生环境门禁

- 状态：`BLOCKED_TOOLING / NO_NATIVE_EXEC_ENV`。
- 决定：StrategyQA runtime redirect 验证的最外层进程必须由调用 API 原生传入实际 executable、完整 argv、cwd 和完全替换式的空或已批准 allowlist `envp`；禁止以 shell、`env`、Python、Conda 或其他已在继承环境中动态加载的 wrapper 清理环境。
- 证据边界：V1、V2 与现有 approval 均保留为 `INVALID_NOT_EXECUTED` 且不得复用；未创建 V3、新 run ID、新 nonce 或新 approval，也未登记正式 run。详细证据唯一来源为 `checkpoints/phase-01-strategyqa-runtime-redirect.md`。
- 恢复：只有提供上述原生 API 后，才可用全新身份与 no-replace approval/V3 record 重新接受 Agent 2审核。FD/launcher contract 与 `RUNTIME_REDIRECT_SEMANTICS_VERIFIED=False` 保持不变；未来成功验证也不得在同一门禁中修改该 flag。

## D-008：2WikiMultihopQA corrected source metadata boundary

- 状态：`METADATA_ONLY / HEAD_NOT_ATTEMPTED`；后者仅指当前 corrected-literal exact gate 尚未执行 HEAD。2026-07-22 历史限时 HEAD 预检曾超时且未产生可验证 source property 的响应；不是 acquisition、archive observation、schema freeze 或实验结果。
- 官方来源：固定 `Alab-NII/2wikimultihop` commit `13800e5be57df1b4040b9b1588c6c811779e69e9` 及其 README 指向的 corrected `data_ids_april7.zip`。旧 `data_ids.zip?dl=0` 永久禁用，不得回退、镜像替换或解释为同一对象。
- 证据边界：README、repository LICENSE 与主论文只提供 revision-bound/paper-reported metadata；archive availability、内容、split/schema、SHA256 与许可证适用性仍为 `UNVERIFIED`。唯一详细来源为 `checkpoints/phase-01-2wiki-discovery.md`。
- 下一门禁：只允许 Agent 1起草 corrected literal Dropbox URL 的 exact no-body HEAD 计划；Agent 2批准前不得联网、创建 approval/record、实现 helper、访问数据或创建工件。
- 独立 HEAD disposition：该 exact 计划已单独评估为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`，原因是当前调用接口不能在最外层 `/usr/bin/curl` 首次进程创建时原生传入空 `envp` 与 `inherit_env=false`。这不修改或泛化 D-007；计划未执行，未创建 approval/record，全部 source properties 仍为 `UNVERIFIED`。

## D-009：TORQUE official metadata boundary

- 状态：`METADATA_ONLY / DOCUMENTS_READ`；不是 snapshot、data observation、schema/evaluator freeze 或实验结果。
- 来源：固定 `qiangning/TORQUE-dataset` commit `ab27019cc6a317fde3c879900499f02acce8b16d` 的 README/LICENSE，以及 ACL primary page/PDF。README 与论文事实分别标记 `README_REPORTED`/`PAPER_REPORTED`；唯一详细来源为 `checkpoints/phase-01-torque-discovery.md`。
- 评测边界：未来只考虑经独立获取与审计的 public dev gold；作者移除的 test annotations 视为 `UNAVAILABLE`，禁止从 fork、缓存或镜像恢复。Apache-2.0 当前只绑定 repository LICENSE，data-license applicability 仍为 `UNVERIFIED`。
- 冲突：paper prose 将 EM consistency 定义为所有 question 的 prediction 均 exact match 的 contrast-set 百分比；Table 4 caption 将 `C` 定义为组内每个 question 的 F1 均至少 80% 的 contrast-group 百分比。该 consistency formulation `SPEC_CONFLICT` 不是普通 per-question EM 冲突，本门禁不选择、不实现。
- 下一门禁：只允许 Agent 1起草 fixed-revision snapshot/acquisition 计划，明确区分 code metadata/data blobs 并冻结 native environment/process 边界；Agent 2批准前不得联网、实现代码、访问数据、创建 approval/record 或工件。
- Snapshot/acquisition disposition：A/B/C 计划独立判定为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`，因为当前调用接口不能为最外层 curl 原生替换 `envp` 或设置 pre-exec OS rlimit。A 若未来获批会传输并可能安全物化 whole archive，但 data/evaluator bytes 在 B/C 独立批准前保持 opaque/unconsumed；本次没有 snapshot/acquisition request、approval、record、stage、数据或工件。

## D-010：TimeQA official metadata and primary-PDF boundary

- 状态：repository README/LICENSE 与 official arXiv landing 为 metadata-only evidence；direct PDF 读取为 `BLOCKED_TOOLING / NO_PRE_FETCH_REDIRECT_AND_BYTE_GATES`。唯一详细来源为 `checkpoints/phase-01-timeqa-discovery.md`。
- 来源：固定 `wenhuchen/Time-Sensitive-QA` commit `38b05989070c1168b2bef3d5a2656afeeba763dc`。`dataset/human_test.hard.json` 仅为 `PROJECT_PLANNED`，不是已观察文件。
- 证据边界：README names/statements 为 `README_REPORTED`；固定 LICENSE 的 BSD-3-Clause/copyright 为 `LICENSE_EVIDENCE`，但具体 data/file applicability 未验；arXiv landing 数值只为 `ARXIV_LANDING_REPORTED`，不得解释为 split、本地数据或复现实验。
- 路由失败：先前 “View PDF” 导向 ar5iv HTML，定性为 `ROUTING_POLICY_FAILURE / OUT_OF_SCOPE_REDIRECT`；ar5iv HTML body/content 仅作为 routing failure 记录，不采纳任何内容。禁止采用 ar5iv Table 1、easy/hard 定义、schema、PDF-body 指标/表格、PDF bytes/pages 或样例内容。
- 下一门禁：只允许 Agent 1起草 fixed-revision snapshot/acquisition 计划；Agent 2批准前不得联网、实现代码、访问数据、创建 approval/record 或工件。
- Snapshot disposition：唯一 codeload literal 仅为未验证、未执行 candidate；A/B/C 计划独立为 `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`。A 未来可语义读取 README/LICENSE/tree metadata，其余成员的 opaque/unconsumed 只表示不语义解析、样例输出、import 或 execute，不表示 hash/extract/materialize 未读字节。B/C 各需独立批准；当前无 request、approval、record、stage、snapshot、数据、代码或实验工件。

## D-011：显式 marker 反事实构造 v0

- 状态：`FROZEN BEFORE IMPLEMENTATION`。
- 决定：下一个 dependency-independent 实现只组合 D-003 已有的保守抽取、marker 改写与确定性 UpdateAnswer；只有答案更新为 `KNOWN` 时才保留完整 original/counterfactual pair。它不定义 GSM8K temporal subset，不扩展 marker、模板或 task-specific updater。
- 输出边界：构造 envelope 仅存内存；不写 JSONL/manifest，不产生 relation-only 记录、数据或实验工件。本决定的精确输入先决条件、门禁顺序、terminal enum、funnel、ID、envelope、字段继承和测试合同的唯一详细来源是 `checkpoints/phase-01-temporal-construction-v0.md`。
- 实施门禁：当前只冻结语义与计划。智能体 1需另行提交仅限标准库和合成 fixture 的精确实施计划，智能体 2批准前不得修改源码或测试。

## D-012：Construction audit schema v1

- 状态：`FROZEN BEFORE IMPLEMENTATION`。
- 决定：以固定 `construction-audit-v1` schema 将一个未构造 `TemporalExample`、其 zero-based 输入顺序和 D-011 `ConstructionResult` 绑定为 typed、frozen、in-memory audit record。Audit ID 只由固定 source identity 载荷生成；完整记录 fingerprint 覆盖 audit ID、order、结果和诊断，free-text diagnostic 不参与稳定身份。
- 安全边界：P1 只提供显式 typed serialize/parse 和 in-memory 校验，不使用 `asdict`，不记录 repr，不读写 JSONL/manifest，不增加 CLI、registry、result 或工件。持久化 writer/verifier、batch order/uniqueness、no-replace 与 manifest-last 必须作为 P2 另行冻结。
- 唯一详细来源：16 个顶层字段及顺序、所有 nested exact schemas、ID/fingerprint 公式、diagnostic 深拷贝与上限、crosslink、测试和实施门禁只见 `checkpoints/phase-01-construction-audit-schema.md`。
- 实施门禁：当前只批准文档冻结。智能体 1可下一步起草精确两文件实施计划；智能体 2新批准前不得编码或运行测试。

## D-013：Construction audit persistence v1

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED`。
- 决定：P2 只持久化调用方已经产生的 D-012 typed records；不在 writer 内调用 D-011，也不把 persistence 与 temporal subset 选择混合。固定 source 为 `PROC-P01-GSM8K-20260722`，按 official train/test 物理顺序 lockstep 重放。
- 发布：每个 split 使用全新 0700 目录、0600 canonical JSONL、exclusive temp + fsync + hardlink no-replace，manifest 最后发布；已有或 partial target 不覆盖、不清理、不修复。执行 commit 在创建前、manifest 前和完整验证后均须与 clean HEAD 一致。
- 证据：manifest 绑定 source/acquisition/SHA256SUMS/LICENSE，记录输出 SHA/bytes/count、三类 unique identity、七个 terminal count 和完整 funnel；离线 verifier 逐条重建 D-012 并核对 source linkage。
- 数据边界：audit 包含完整 source text/question/answer 与构造诊断，属于 data-bearing 工件，仅保存在 `/data0` 的私有目录，不进入 Git、日志或作者报告逐样本内容。
- 已知预期：GSM8K adapter 当前令 `text == question` 且 answer type 为 numeric。冻结 D-011 可能因此得到 0 retained；生产结果必须如实登记，不得查看 test funnel 后修改 marker/updater 以制造正结果。
- 唯一详细来源：`checkpoints/phase-01-construction-audit-persistence.md`。

## D-014：手动官方 source acquisition disposition

- 状态：`PARTIAL / TWO_SOURCES_EXTRACTED`。
- 决定：按用户最新指令，以固定官方 URL/revision 手动获取 StrategyQA、TORQUE、TimeQA，并对 2Wiki corrected literal URL 作一次 bounded GET；仍保留路径、资源、HTTPS、no-upstream-execution 和不回退镜像边界。
- 结果：TORQUE/TimeQA fixed-commit TAR.GZ 通过既有 held-FD archive inspection/extraction 并完成无内容 schema 聚合；StrategyQA 官方 ZIP 因 data descriptor 被通用保守策略阻塞且未解压；2Wiki 在连接阶段 curl 28 且无 HTTP response，不重试。
- 评测边界：TORQUE 只允许 answer-bearing public dev（145 passages/1,483 QA），test 本地条目没有 answer；TimeQA-Hard 固定为 989 条 LF-delimited JSON。它们当前只是 source/schema evidence，不是 adapter、metric 或模型结果。
- 证据：唯一详细来源为 `checkpoints/phase-01-manual-source-acquisition.md` 与 raw revision 内 canonical acquisition manifests。

## D-015：TORQUE/TimeQA transfer metric contract

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED`；不是模型评测或论文结果。
- TORQUE：只读 public dev，预测与 gold 都按 NFC+casefold+whitespace collapse 后作为 span set；保留 punctuation。per-question 报 set EM/F1，空集对空集两者均为 1。contrast group 的唯一键为 `(passageID, cluster_id)`。
- 规格冲突处置：论文 prose 的“组内每题 exact”定为主指标 `cluster_exact_consistency`；Table 4 caption 风格的“组内每题 F1>=0.8”定为敏感性指标 `cluster_f1_80_consistency`。两者必须同时输出，禁止混名或只报告较优者。
- TimeQA：语义复刻固定 upstream `utils.py` 的 lowercase、ASCII punctuation 删除、article 删除、whitespace collapse、EM/token-F1 和多 gold 分别取最大值。989 条 hard 记录中 159 条的唯一 target 是空字符串；这是合法 gold，不能丢弃或改写。
- 证据和非结果边界：实现/测试/clean read-only smoke 的唯一详细来源为 `checkpoints/phase-01-transfer-eval-contract.md`。正式评测仍需先冻结 prediction JSONL/manifest；TORQUE test 和 upstream code execution 仍禁止。

## D-016：Model-agnostic prediction artifact contract

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED`；production publisher 未调用。
- 决定：正式预测只能以固定 source order 的完整 JSONL 发布，且同时绑定 run ID、dataset revision/SHA、adapter/metric schema、method/model revision、canonical config、clean commit、seed、UTC 时间和资源声明。TORQUE 值为 string array，TimeQA 值为 string。
- 发布/验证：0700 新 run 目录，0600 config/predictions/manifest；exclusive no-replace、manifest-last、创建前和 manifest 前 clean Git gate。offline verifier 重放 fixed adapter、record coverage/order、canonical bytes、SHA/size/count、权限/link 和 exact schemas。
- 边界：该层不运行模型、不聚合指标、不自动写 registry；partial/既有 run 永不覆盖或修复。唯一详细来源为 `checkpoints/phase-01-prediction-artifacts.md`。

## D-017：Kairos tensor core independent defaults

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED`；不是端到端模型或实验结果。
- 论文对齐：event span pool → latent start/positive duration/end → exact 8-d geometry → five known relation softmax → valid directed-pair graph pool → shared answer/graph candidate score；loss 为 answer + relation + counterfactual relation。
- 独立默认：mean span/graph pooling；directed non-self pairs；relation 顺序 `precedes/follows/overlaps/contains/during`；unknown/padding=`-100`；`softplus+1e-6` duration；shared size 256；Pair-MLP `[h_i,h_j,h_i-h_j,h_i*h_j]`/hidden 256。它们均非恢复出的作者配置。
- Pair-MLP 公平性：复用相同 event/candidate representations、pair mask、五类 label、graph pool、candidate scorer 和 losses，仅用 MLP pair features 替代 interval geometry。
- 边界：backbone、LoRA、event extraction/token alignment、candidate generation/prompt parsing 和 runner 不在本决定内。唯一详细来源为 `checkpoints/phase-03-kairos-tensor-core.md`。

## D-018：Transfer prompt、greedy generation 与 evidence contract

- 状态：`IMPLEMENTED / FIRST FORMAL RUN COMPLETE`。
- Prompt：Direct 与 CoT 共享固定 task instruction 和 strict terminal `FINAL_ANSWER: <JSON>`；TORQUE 只接受 string array，TimeQA 只接受 string。Prompt 不包含 gold，terminal parse 失败使用固定 sentinel 计错并保留 raw evidence，禁止人工修复输出。
- Generation：固定本地 `Qwen/Qwen2.5-7B-Instruct` revision `a09a35458c702b33eeacc393d103063234e8bc28`，greedy、无 sampling；Direct/CoT 分别最多生成 128/512 tokens。模型 context 为 32,768，输入上限分别保留对应生成预算。任何正式运行均须 clean exact commit、固定 seed/physical GPU、完整 source order 和全部 prediction rows。
- Artifact v2：正式目录 exact 包含 `config.json`、`predictions.jsonl`、`generation-evidence.jsonl` 和最后发布的 `manifest.json`。Evidence 记录 raw response、parse status 与 token counts；它是 data-bearing 私有工件，不回显、不进入 Git。旧 v1 development contract 被 v2 在首次 production publication 前替代。
- Metrics：派生指标不得写回冻结的 prediction 目录，固定发布到 `artifacts/derived-metrics/<run-id>`，只含 canonical `metrics.json` 和 manifest-last `manifest.json`。发布前后必须重放 prediction/source/aggregation，绑定 aggregation commit 和 prediction 的四个 SHA；offline verifier 必须重新计算指标。
- 当前证据：首个正式 TORQUE Direct run 的完整身份、指标与 SHA 唯一登记在 `checkpoints/phase-03-torque-direct-baseline.md` 和 experiment registry。Prediction 与 metrics artifact 均通过独立 replay，状态为 `VERIFIED / DETERMINISTIC SINGLE RUN / NO COMPARATIVE CI`。

## D-019：TimeQA strict primary 与 post-hoc recovery 边界

- 状态：`FROZEN AFTER PRIMARY RUNS / NO SENSITIVITY IMPLEMENTED`。
- Primary：Direct/CoT 均继续使用预先冻结的 terminal JSON string parser；parse failure 使用固定 sentinel 计错。不得用事后恢复值覆盖、重命名或删除 strict primary。
- 已观察结构：Direct/CoT 分别有 966/907 个可解析 terminal JSON object，而非要求的 string。仅做不输出值/未知键名的结构计数：Direct 只有 7 个 object 含唯一可用 `answer` string，CoT 的 907 个没有 `answer/final_answer/FINAL_ANSWER` 字段；其余结构不通过白名单。
- 决定：不读取 test raw object keys/values来设计 dataset-specific unwrapping，也不采用任意 first-value/recursive/stringification 规则。这样的规则会在观察测试输出后引入选择自由度且不可解释。未来若有训练外的预先定义 parser 或独立 validation 证据，可新登记 post-hoc sensitivity；当前不实现。
- 证据：strict run、错误类别、上限命中和工件 SHA 见 `checkpoints/phase-03-timeqa-direct-baseline.md`、`checkpoints/phase-03-timeqa-cot-baseline.md` 与 registry。

## D-020：配对 bootstrap、区间与多重校正

- 状态：`IMPLEMENTED / PRODUCTION VERIFIED`。
- 对比方向：所有差值固定为 candidate minus reference；当前 candidate 为 CoT、reference 为 Direct，模型 revision 与 model seed 必须相同。每项比较固定 10,000 resamples、bootstrap seed 20260723，不因观察结果调整。
- 重采样单位：TORQUE 使用 `(passage_id, cluster_id)` contrast group，组被有放回抽取且组内全部题一起进入题级和 cluster 指标；TimeQA 使用 record。这样避免把同一 TORQUE contrast group 内问题误当作独立样本。
- 推断：95% CI 使用 percentile linear interpolation；双侧 bootstrap sign p-value 使用 add-one correction；Holm 在每个 dataset comparison 的全部报告指标族内校正。该 p-value 是预先标明的 bootstrap sign 近似，不冒充 permutation test。
- 工件：固定 manifest-last/no-replace 目录绑定两侧 prediction/metrics SHA、aggregation clean commit/time、seed 和 resamples；发布前后及 offline verifier 都从 fixed source、逐样本预测重算。唯一详细证据为 `checkpoints/phase-03-paired-bootstrap.md`。
- 解释：TORQUE CoT 的题级下降得到统计支持，cluster 差异不显著。TimeQA strict 的 +0.506 pp 虽在该 bootstrap 下非零，但由约五条 CoT strict exact 与两方法 97.98%/99.70% parse failure 主导，只能解释 prompt/parser 格式交互，不能表述为 temporal reasoning 提升。D-019 不变。

## D-021：TORQUE CoT+Verifier 固定选择基线

- 状态：`IMPLEMENTED / PRODUCTION VERIFIED / NEGATIVE RESULT`。
- 候选与 prompt：只比较已冻结 Direct index 0 与 CoT index 1 的 span-set 候选；prompt 只含 passage、question 和两个候选，不序列化 gold。normalized set 相同则不调用模型并选择 Direct。
- 生成与失败：同一 Qwen revision、greedy、seed 13、batch 8、`max_new_tokens=32`。输出必须为唯一 terminal JSON integer 0/1；parse failure 固定回退 Direct。输入 run ID 与 manifest SHA、候选顺序、等价和 fallback 策略全部写入 config，结果后不放宽 parser。
- 结果：980 次 verifier 调用仅 218 个 strict index parsed，762 个回退；EM/F1 14.228/14.681，均显著低于 Direct。该结果说明此固定 verifier 未提供增益，保留为负 Baseline，不据此调 prompt。
- 证据：唯一完整资源、工件、SHA、选择计数、指标与 paired inference 见 `checkpoints/phase-03-torque-cot-verifier-baseline.md`。

## D-022：GSM8K relation-only supervision v1

- 状态：`IMPLEMENTED / TRAIN ARTIFACT VERIFIED / PARTIAL PAPER DEVIATION`。
- 触发原因：construction v0 的 production replay 已证明所有 GSM8K numeric answer update 均为 `UNKNOWN`，因此完整 original/CF pair 为零。复制 original answer、凭 marker 猜测 numeric CF answer 或把 relation label 冒充 answer supervision 都不可接受。
- 决定：v1 只保留 original numeric answer，并为可确定重放的显式 marker pair 保存 original relation 及其 inverse relation。counterfactual answer 固定为 `unavailable-relation-only` 且 schema 不含 counterfactual answer 字段；使用者必须 mask CF answer loss。
- 适用边界：该记录可支持 original-answer、relation 与 counterfactual-relation loss，不能支持 CF answer accuracy、update、stability 或 consistency。它是独立重实现中的部分监督桥接，不满足论文所称 reliable updated answer，也不恢复作者未公开的 subset IDs、prompt 或 updater。
- 防泄漏门禁：schema/publisher 均在 clean commit 前只用 synthetic fixture；随后只读取并发布 official train，CLI 与 production layout 不提供 test split。train 7,473 条中得到 370 个 pair；test、训练和正式模型指标仍禁止，直至两人 200 条人工审计完成。
- 证据：schema commit `17137bbf6e666381c148d40b7249032ab1d3a0b6`，publisher/execution commit `5f0b31ed27b9aa582259a61bfc0f4b7dd11cd578`；精确 schema 与 production 工件证据分别见 `checkpoints/phase-01-relation-only-supervision-v1.md`、`checkpoints/phase-01-relation-only-train-artifact.md`。

## D-023：Relation-only 200 条双人盲审包

- 状态：`PACKET VERIFIED / HUMAN REVIEW PENDING`；不是数据有效性结论或训练批准。
- 抽样：只绑定 official-train 的 370-pair immutable artifact；固定 seed 20260723，以 `(template_id, original_relation)` 分层，Hamilton largest remainder 分配 200 条，stratum 内选择与最终展示分别用独立 SHA256 rank。结果为 259→140 的 after/follows 与 111→60 的 before/precedes。
- 盲审：A/B 两个 reviewer slot 的模板完全相同且所有人工字段为 null；reviewer 彼此隔离。检查 event span、original relation、CF relation、grammar、non-target preservation，`overall_valid` 必须是前五项逻辑与。模板不可原地覆盖，完成副本必须先锁定哈希再互看。
- 判定：primary agreement 为 200 条 `overall_valid` 的 Cohen's kappa，阈值 0.80；分歧经作者共识后 validity threshold 为 95%。任一不达标则修订规则并使用新样本重审。AI 不得填写、推断或替代人工标签。
- 门禁：人工表未完成，因此 kappa/validity 均为 unavailable，GSM8K LoRA 仍禁止。实现 commit、五文件 SHA、资源和 replay 见 `checkpoints/phase-01-relation-human-audit-packet.md`。

## D-024：TORQUE Self-Consistency 固定采样与投票

- 状态：`IMPLEMENTED / PRODUCTION VERIFIED / NO SUPPORTED DIFFERENCE`。
- 采样：每题固定 8 个既有 CoT prompt samples，temperature 0.7、top-p 0.9、top-k 0、`max_new_tokens=512`、seed 13；同一 Qwen 与 TORQUE revision，不注入 gold。最终 batch 8 只是资源执行设置，不改变方法。
- 聚合：每个 sample 继续服从 strict terminal JSON string-array parser；无效 sample 不投票。对 normalized exact span set 作 plurality，平票取最早 valid sample；8 个全无效才输出固定 sentinel。原始 sample envelope 只保存在私有 evidence，offline verifier 必须逐题重算投票。
- 结果：题级 EM/F1 为 15.374/15.569，相对 Direct 为 -0.270/-0.500 pp；cluster 两口径为 1.926，相对 Direct +0.350 pp。四项 571-group paired bootstrap CI 均跨零、Holm p 均为 1，因此只能报告 single-seed 下无可支持差异，不能宣称改进。
- 边界：第一次 batch-1 尝试在 artifact 创建前因吞吐预检主动中断，登记为 `INTERRUPTED_PREFLIGHT / NO ARTIFACT`；结果后不修改投票、parser 或采样参数。唯一完整证据见 `checkpoints/phase-03-torque-self-consistency-baseline.md`。

## D-025：TORQUE LLM-Graph 严格结构化基线

- 状态：`IMPLEMENTED / PRODUCTION VERIFIED / SIGNIFICANT NEGATIVE RESULT`。
- 输入与生成：只给 passage/question，不注入 gold/candidate；greedy、seed 13、batch 8、`max_new_tokens=768`。响应倒数第二个 non-empty line 必须是 strict `TEMPORAL_GRAPH` JSON，最后一行沿用 strict span-array answer。
- Graph contract：节点 ID 为唯一 E1--E999、span 必须是 passage exact substring；边端点必须存在且不同，关系固定为 `precedes/follows/overlaps/contains/during`；非空答案必须在 TORQUE normalizer 下绑定 graph event。任何结构错误整题 sentinel，不作 post-hoc repair。
- 结果：667/1,483 strict parsed，816 parse errors；EM/F1 均 1.349，cluster 两口径 0。对 Direct 的差为 -14.295/-14.721/-1.576/-1.576 pp，四项 group-bootstrap CI 均低于零。主要失败来自 graph line 位置和非 exact event span，只有 1 条命中 token 上限。
- 解释边界：结果说明该模型下严格 one-pass graph serialization 基线失败，不说明 temporal graph 方法普遍无效，也不构成 Kairos effect。结果后不得用 dev raw output 放宽 primary parser；未来 repair/few-shot 只能另列 sensitivity。完整证据见 `checkpoints/phase-03-torque-llm-graph-baseline.md`。

## D-026：Qwen hidden-state 到 Kairos/Pair-MLP 的共享训练接口

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`。
- 公平性：Kairos 与 Pair-MLP 必须接收同一 strict batch、Qwen hidden states、event/candidate masks、answer/relation/CF-relation targets 和 `lambda_rel=lambda_cf=1`；除 interval geometry 与 pair MLP 外不得分叉输入或监督。
- Backbone：优先调用 `backbone.model`，固定 `use_cache=False`、`output_hidden_states=False`，只接受 exact finite last hidden state；仅 valid candidates 进入 encoder，padded candidates 全零回填后再走共享 span pool。
- LoRA 默认：rank 16、alpha 32、dropout 0.05、bias none、gradient checkpointing；targets 固定 Qwen attention/MLP 的 `q/k/v/o/gate/up/down_proj` 七类。当前只读验证目标存在且为 Linear，不注入 PEFT，属于独立默认而非作者设置。
- 边界：trainable-state 仅内存严格 round-trip，不是持久 checkpoint；optimizer/RNG/manifest/resume 和 production runner 均未实现。没有读取 production data/weights，人工审计训练门禁不变。唯一详细证据见 `checkpoints/phase-03-qwen-core-training-adapter.md`。

## D-027：审稿意见闭环、2Wiki 恢复与后续实验边界

- 状态：`FROZEN / EXECUTION AUTHORIZED WITHIN EXISTING GATES`。
- 证据优先级：剩余关键路径固定为监督有效性、可恢复训练器、Kairos 与 Same-data SFT/Pair-MLP 的同监督正式比较、TORQUE 迁移评测、marker/template 与 interval/failure 分析。2Wiki 恢复并行执行但不阻塞 TORQUE 关键路径。唯一完整计划与 reviewer-to-evidence matrix 见 `checkpoints/remaining-reviewer-response-plan.md`。
- Claim 边界：当前 370 条 relation-only 数据没有 counterfactual answer，只能支持 original answer、relation 与 CF-relation loss。它不能支持 CF-answer accuracy、update、stability 或 consistency，也不能作为 Same-data SFT 的完整 answer-update 监督。若无法在观察正式测试结果前冻结并通过人工审计的 answer-bearing v2，论文必须撤回或收窄 answer-update 效果 claim。
- 2Wiki 来源顺序：在查看任何新响应 body 前，固定为作者仓库引用的 April 2021 `data_ids_april7.zip` legacy/SCL 同对象路线，其次作者发布的旧 `data_ids.zip`，再次为原始 `data.zip`。三者是不同 revision 时必须分别登记，禁止静默替代。固定 HF `xanhho/2WikiMultihopQA@6ef4eb1bc94ca4a768bb86809fafe777ad795995` 明示为 unofficial mirror，只能在所有可用 split 对 ID、question、answer、context、supporting facts 与 evidences 做全量 canonical semantic hash 等价后升级；计数、抽样或 schema 相似均不足。失败记录和旧 stage 不覆盖、不删除。
- 2Wiki 执行：每个请求前执行资源门禁，使用禁用用户配置的固定系统 curl、HTTPS-only、前台有界传输、固定字节上限和允许 host，记录 request identity、redirect/effective URL、HTTP status、bytes、SHA256 与 terminal state但不记录样本内容。成功 body 先进入 `/data0/hk_data/kairos-zx/.tmp` 的新私有 stage；完成安全 archive/schema/license 验证前不发布为 formal raw revision。
- TimeQA 边界：D-019 strict Direct/CoT primary 与既有预测保持不可变。后续只能以新 method/run ID 执行 gold-blind output-contract follow-up；其 prompt/parser 必须只由合成输入或独立 validation 证据冻结，不读取 `human_test.hard` 的 raw response keys/values来选规则，也不能以 follow-up 覆盖、重命名或修复旧 primary。旧结果继续报告为 format failure。
- 公平比较：正式主比较固定为 Kairos 对 strongest same-supervision baseline；Same-data SFT、Pair-MLP 与 Kairos 复用数据 revision、candidate pool、parser、metrics 与 seeds 13/42/2026。Prompt-only 结果用于描述设定差异，不表述为完全对称的公平比较。当前 strict LLM-Graph 负结果保留；Rule-Graph/Constraint-Rerank 作为额外 structured baseline，不能删除或替换负结果。
- 论文处置：PDF/TeX 冲突数值继续为 `REPORTED / UNVERIFIED`。只有 registry 中绑定 clean commit、run ID、dataset revision、seed 和工件哈希且通过离线重放的 `VERIFIED` 数值可进入修改建议；负结果、格式失败和 deferred 必须保留。

## D-028：Synthetic-only 可恢复训练执行合同

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`；冻结父提交为 `7dd2110da1f239e63fc6292a9e216c341b9ee286`，实现 commit 为 `7772f7c0b83557c423456de62a3fd733781e3499`。本决定不授权 production 数据、7B 权重、PEFT 注入、GPU 或正式训练。
- 优化器：只允许两组 AdamW。`QwenCoreTrainingAdapter.backbone` 中 trainable 且名称含独立 LoRA component `lora_` 的参数进入 `lora` 组，LR `2e-5`；`core` 的全部 trainable 参数进入 `temporal_heads` 组，LR `2e-4`。任何重叠、遗漏、空组或其他 trainable backbone 参数均 fail closed。两组 weight decay `0.01`，betas `(0.9,0.999)`、eps `1e-8` 为独立默认。
- Batch/AMP：effective batch 固定 32；micro batch 只允许 1/2/4/8/16/32，gradient accumulation 必须精确为 `32/micro_batch`。loss 在 backward 前除以 accumulation steps，只能在 accumulation boundary 做 clip `1.0`、optimizer step、scheduler step和 checkpoint。AMP dtype 固定 BF16；CPU synthetic test 使用 CPU autocast，不使用 GradScaler；未来 CUDA BF16 也固定 scaler disabled。
- Scheduler/steps：linear warmup-decay v1，warmup 为 `floor(total_optimizer_steps*0.05)`；总 optimizer steps 必须预先冻结且为正。每次 optimizer step 后调用一次 scheduler step。最多 3 epochs；checkpoint progress 精确记录 epoch、next micro-batch cursor、optimizer steps和 samples seen。
- Seeds/order：run seed 只允许 13/42/2026。checkpoint 捕获 Python RNG、Torch CPU RNG、仅在 CUDA 已初始化时的全部 CUDA RNG，以及独立 dataloader `torch.Generator` state。恢复必须在继续取样/forward 前完成；样本顺序由 cursor 与 generator state共同绑定。
- Artifact：v1 checkpoint 为 mode-0700 新目录下的 mode-0600 canonical `config.json`、受限对象 `state.pt` 和最后发布的 canonical `manifest.json`。所有创建使用 no-replace、文件/目录 fsync；partial/既有目录不覆盖、不清理。manifest 绑定 execution commit、config/state SHA256/bytes、progress 与 exact filenames。加载先校验路径位于 `/data0/hk_data/kairos-zx`、无 symlink、namespace/mode/link、canonical JSON、hash/size、restricted `torch.load(weights_only=True)`、模型/optimizer/scheduler/RNG schema；任一失败不得改变 live state。
- 等价验收：只用 CPU synthetic Qwen-like backbone、Kairos/Pair-MLP 和 synthetic `TrainingBatch`，比较 uninterrupted 与 optimizer-boundary interrupted/save/new-process-style restore/resume 的 trainable tensors、optimizer tensors/scalars、scheduler、progress、RNG next draw和 loss trajectory。focused 与 full tests 均须通过；工件只在 `/data0/hk_data/kairos-zx/.tmp` 测试根创建并由测试自身清理。
- 实现边界：新增 `kairos.training_execution` 及对应测试；不新增读取 production 数据的 CLI，不接触 candidate materialization，不创建正式 checkpoint/run/registry metric，也不改变 D-023 人工门禁。实现差异和验证结果在完成后写入单一 Phase 03 checkpoint。
- 验证结果：focused training-execution/modeling 20/20、最终 full 528/528 通过；Kairos 与 Pair-MLP 的 CPU BF16 uninterrupted 与 interrupted/resumed 路径在 trainable/optimizer/scheduler/progress/loss/gradient/RNG 上逐项相等。首轮发现并修复 mask dtype 将 BF16 interval coordinates 错误提升回 FP32 的既有 autocast 缺陷；FP32 语义不变。
- 未完成边界：当前 API 消费调用方已物化的 deterministic batch sequence，不实现 sampler/epoch/data/candidate/CLI/PEFT/7B/GPU。`7772f7c...` 的 v1 synthetic checkpoint 当时尚未绑定 frozen backbone revision 与 production data manifest；该身份缺口随后由 D-029/v2 补齐，但 production artifact verification 与 training gate 仍未实现。D-028 的唯一详细证据见 `checkpoints/phase-03-resumable-training-execution.md`。

## D-029：训练 checkpoint 身份绑定与 PEFT 前置门禁

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY / PEFT BLOCKED`；冻结父提交为 `7a4cf6bca04a80e74d2635e180bbe4122ad24704`，实现 commit 为 `1d80f5d4196a5a89cb1b465f162c5822c07534cb`。局部环境只读检查结果为 `peft_spec=none`、`peft_version=none`，局部 Conda/package cache 未发现 PEFT 分发包。本决定不授权安装或升级依赖，不授权读取 production 样本、加载 7B 权重、使用 GPU 或正式训练。
- 身份对象：新增 canonical `TrainingArtifactBinding`。模型字段固定为 `Qwen/Qwen2.5-7B-Instruct`、revision `a09a35458c702b33eeacc393d103063234e8bc28`、本地 `SHA256SUMS` 文件 SHA256 `3ee6c9510b7e50bfcd46d6df33cafa3e2019f13a6a09bf1d2f9e80cdfe1164e8`；数据字段为 bounded dataset ID、40-hex revision、bounded split、bounded artifact ID 和 lowercase 64-hex immutable data-manifest SHA256；core type 只允许 `kairos` 或 `pair-mlp`。
- Checkpoint schema：由于不存在需要兼容的正式 checkpoint，config/state/manifest schema 原子升级为 v2。canonical config 和 manifest 都必须包含同一完整 binding；`VerifiedTrainingCheckpoint` 暴露解析后的 binding。state 仍只含受限 tensor/scalar/RNG/progress 对象，不放路径或任意用户对象。
- 保存门禁：保存前从 `QwenCoreTrainingAdapter.core` 推导实际 core type，并要求与 binding 完全一致；模型/data binding 由调用方提供的冻结 manifest 产生，本层不把一个 hash 声称为已经验证过对应文件。后续 production runner 必须先独立验证实际模型 `SHA256SUMS` 和数据 manifest，再传入 binding。
- 恢复门禁：resume 必须显式接收 expected binding；在读取和应用 state 前校验 execution commit、config 与 binding 全等，并再次校验 live adapter core type。任何 mismatch 必须在 model/optimizer/scheduler/RNG 状态变化前 fail closed。
- 验收：Kairos/Pair-MLP 保存、verify、resume 均覆盖；model revision、model checksum、dataset revision、data-manifest hash、split/artifact ID 与 core-type 任一篡改或 expected mismatch 都被拒绝；原 D-028 uninterrupted/resumed 等价继续成立；focused/full tests 通过且测试工件清理。
- PEFT 后续合同：只有在用户明确授权扩充局部依赖并冻结兼容版本后，才可 lazy-import PEFT，使用 D-028 的 rank 16/alpha 32/dropout 0.05、bias none 和七类 Qwen target modules 注入；注入后必须证明 base 参数冻结、trainable 参数仅为 `lora_` 与 temporal core，并重新跑全量测试。没有真实 PEFT 安装验证前，不创建伪适配层、不执行 7B/GPU smoke。
- 验证结果：v2 config/manifest 双重 binding、保存前 live core 推导及 resume expected binding 已实现；expected mismatch 在打开 `state.pt` 前失败。focused 8/8、最终 full 530/530 通过，测试工件已清理；唯一详细证据见 `checkpoints/phase-03-checkpoint-identity-binding.md`。
- 历史更新：上述 PEFT blocker 随后由用户授权及 D-030 解决；D-029 的 checkpoint identity 与 production-data 门禁不变。

## D-030：项目局部 PEFT 依赖与注入执行合同

- 状态：`IMPLEMENTED / DEVELOPMENT_VERIFIED / NOT A FORMAL RUN`；冻结父提交为 `8081855c462ad24c2934d1d82710259adb588c25`，合同 commit 为 `c37d86aa6b133125f5d32086ea8554f74c7d86a6`，实现 commit 为 `c68c77a2eceba9c34f93ac99bd5893807c02cecb`。用户明确授权继续核对并在当前数据目录内安装 PEFT；授权不放宽路径、资源、人工审计或正式训练门禁。
- 版本选择：固定 `peft==0.14.0`。官方 tag/release 与 `setup.py` 标明 Python `>=3.9.0`、Torch `>=1.13.0`、Accelerate `>=0.21.0`、Hugging Face Hub `>=0.25.0`，其余直接依赖无更高下限。当前局部环境为 Python 3.10.20、Torch 2.5.1、Transformers 4.48.3、Accelerate 1.2.1、Hub 0.28.1、Safetensors 0.5.2，安装前 `pip check` 无错误。0.14.0 与固定 Transformers 4.48.3 属同一兼容代际，避免采用面向 Transformers v5 的新 PEFT 版本。
- 下载与完整性：执行资源门禁后，只允许 `pip download --only-binary=:all: --no-deps peft==0.14.0` 到 `/data0/hk_data/kairos-zx/.tmp` 的新私有 stage。安装前记录 wheel filename、bytes、SHA256，并离线检查 wheel METADATA 的 Name/Version/Requires-Python/Requires-Dist；不得从未固定 Git branch、源码包或非官方镜像安装。
- 安装边界：只使用 `/data0/hk_data/kairos-zx/.conda/envs/kairos/bin/python -m pip`，从已校验本地 wheel 执行 `--isolated --no-index --no-deps` 安装。缓存和临时目录全部位于 `/data0/hk_data/kairos-zx`；禁止 `--user`、全局环境、依赖解析升级和 shell/Conda 初始化。安装前后包清单必须证明除新增 `peft==0.14.0` 外，Torch/Transformers/Accelerate/Hub/Safetensors 等版本不变；`pip check` 必须通过。
- 注入合同：实现 lazy-import PEFT 的单一入口，构造 `LoraConfig(task_type=CAUSAL_LM, r=16, lora_alpha=32, lora_dropout=0.05, bias="none", target_modules=D-028 七类 suffix)` 并调用官方 `get_peft_model`。注入前仍执行目标模块全覆盖/Linear 检查；注入后固定 `use_cache=False`、启用 gradient checkpointing，并验证 base 参数冻结、backbone trainable 参数全部且仅为 `lora_`、temporal core 保持 trainable。重复注入或任何遗漏/额外 trainable 参数 fail closed。
- 验证顺序：先在 synthetic Qwen-like module 上完成注入、forward/backward、optimizer groups、trainable-state round-trip 与 checkpoint/resume 测试，再运行 full suite。代码从 clean commit 推送后，重新执行资源门禁，才可加载固定本地 Qwen snapshot 做一个 micro-batch、单 optimizer-step 的前台 GPU development smoke；不读取 production 数据、不创建正式 run/checkpoint/指标。
- 停止条件：若 wheel 元数据不符、安装引起既有包版本变化、`pip check`/import/synthetic tests 失败、`/data0` 低于 120 GiB、无合适 GPU 或预计单卡内存超过安全余量，则保留证据并停止，不升级其他依赖、不更换未经冻结版本、不启动正式训练。
- 安装与验证结果：官方 wheel 374,831 bytes、SHA256 `2f04f3a870c3baf30f15e7dcaa5dd70d3e54cfdd146d3c6c187735d3ae0a0700`；仅新增 `peft==0.14.0`，核心依赖版本逐项未变，import 与 `pip check` 通过。实现覆盖 real tiny-Qwen PEFT forward/backward、optimizer/state/checkpoint；focused 9/9 + 9/9、full 533/533 通过。
- GPU smoke：clean `c68c77a...` 上使用 physical GPU 4、本地固定 7B、synthetic batch 32 完成一个 optimizer step；392 LoRA tensors，loss 1.96875，peak allocated 15,920,307,712 bytes，退出后 GPU 回到 11 MiB。首次仅因 CUDA 统计初始化次序在 model load 前失败且无工件；最终证据与边界唯一记录于 `checkpoints/phase-03-peft-injection-smoke.md`。

## D-031：确定性训练顺序、候选绑定与精确恢复游标

- 状态：`FROZEN FOR IMPLEMENTATION / SYNTHETIC ONLY`；冻结父提交为 `6a3f18ef1839dcdcf19c58593d809c07eb37f866`。本决定不授权读取 production 数据、候选预测或模型，不授权 GPU 或正式训练；D-023 人工审计门禁不变。
- Source/candidate binding：训练 corpus 必须绑定 dataset revision、不可变 source artifact ID/manifest SHA256 和 clean execution commit。每个样本按 source artifact 顺序保存连续 `source_order_index`、example/source/original/CF record IDs 与 canonical record SHA256；任一身份或 hash 重复即 fail closed。
- 候选合同：候选保留去重后的首次出现顺序，每项绑定 example ID、exact UTF-8 content SHA256 和有序来源集 `direct/cot/self-consistency/gold`。manifest 同时绑定 gold-answer SHA256、target index 和 `gold_injected`；若补 gold，它必须是末项且来源仅为 `gold`，未补时 target 不得声称 gold 来源。评测禁止 gold 的规则不因训练 manifest 改变。
- Epoch sampler：seed 仅为 `13/42/2026`，固定 3 epochs。每个 epoch 对 `(corpus_sha256, seed, epoch, source_order_index, example_id)` 的 canonical payload 做 SHA256 rank，以 `(rank, source_order_index, example_id)` 排序；不使用 Python/Torch shuffle 或 worker 时序决定样本顺序。所有真实样本在每轮恰好出现一次。
- Batch/tail policy：继承 D-028 的 effective batch 32 及固定 micro-batch divisor。三轮序列后若不足 32，只允许用独立 padding-rank 的确定性前缀补齐，且仅补 `0..31` 个 slot；这些 slot 必须显式标记 `repeat_padding=true`。不静默 drop 样本，不隐式改变最后一步的 effective batch。正式报告必须披露真实/repeat slot 计数。
- Manifest/cursor：canonical manifest 必须完整列出 source-order examples/candidates、epoch slots、repeat-padding slots、micro-batch 和 optimizer-step 归属，并可由最小输入独立重建后 exact equality 验证。恢复只允许 optimizer boundary；cursor 同时绑定 next micro-batch、optimizer steps、consumed total/real/repeat slots、completed epochs 和 next example，任一不一致即在取样或模型变更前失败。
- Checkpoint binding：未来 production runner 传入 D-029 `TrainingArtifactBinding.data_manifest_sha256` 的必须是本训练 manifest 的 SHA256；该 manifest 内部再绑定源数据 manifest，从而使候选、顺序、tail policy 和 source artifact 一起进入 checkpoint 身份。实现只先做 pure/synthetic 结构、严格 round-trip/tamper/cursor 测试与 CPU full suite。
